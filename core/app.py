#!/usr/bin/env python3
"""
ISIN Monitor: controlla i prezzi dei titoli della watchlist di MyFinance su Borsa
Italiana, li salva nella tabella prezzi di Supabase e manda un avviso su Telegram
(con grafico e link alla scheda in MyFinance) quando un prezzo si muove almeno della
soglia del titolo rispetto al prezzo salvato prima.

In orario di mercato gira come processo unico (monitora): un giro ogni 15 secondi
legge i prezzi di tutti i titoli (richieste distribuite nei 15 secondi, senza raffiche)
e li salva con una sola scrittura; gli
avvisi (grafico e invio su Telegram) passano da una coda a un thread a parte, così non
rallentano mai i giri. Al primo giro di ogni giorno, in un altro thread, riempie con
Yahoo i buchi dello storico e manda i cambiamenti delle proposte di MyFinance.
"""

import queue
import threading
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

from . import posizioni, proposte, stato, storico
from .database import Database, ErroreDatabase
from .orario import INTERVALLO, in_orario, secondi_al_prossimo_giro
from .message_templates import CaptionTemplates
from .price_providers import BorsaItalianaProvider, YahooFinanceProvider
from .profiler import profile
from .utils import TableDataGenerator
# core.chart_generator (matplotlib) è importato solo quando serve un grafico

ROMA = ZoneInfo('Europe/Rome')
MYFINANCE_URL = 'https://andreaadelfiomyfinance.pages.dev'
TOKEN_ESEMPIO = '123456789:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890'
# Prezzi tenuti da parte se Supabase non risponde (circa una giornata di controlli)
MAX_IN_SOSPESO = 50000
# Risposte di Supabase per dati sbagliati: quei prezzi si buttano. Con gli altri errori
# (rete, 5xx, chiave sbagliata o revocata, troppe richieste) aspettano in locale
RIFIUTATI = (400, 409, 422)
# Variazione in % (rispetto all'ultimo prezzo salvato) da confermare al giro dopo
SALTO_SOSPETTO = 20
# Secondi fra una riga di log e l'altra quando Supabase è giù
LOG_OFFLINE = 300
# Un avviso più vecchio di così (rimasto in coda con Telegram giù) non si manda più
MAX_RITARDO_AVVISO = timedelta(minutes=30)
# Attesa massima chiesta da Telegram (retry_after) per riprovare un invio
MAX_ATTESA_TELEGRAM = 120
# Pausa dopo una risposta 429 (troppe richieste) di Borsa Italiana
PAUSA_429 = 60


def descrivi(errore: Exception) -> str:
    """Tipo, messaggio e punto del codice di un errore: dal solo messaggio (es. 'isin')
    nel log non si capirebbe cosa è successo."""
    testo = f"{errore.__class__.__name__}: {errore}"
    if errore.__traceback__:
        riga = traceback.extract_tb(errore.__traceback__)[-1]
        testo += f" ({Path(riga.filename).name}:{riga.lineno})"
    return testo


def titolo_da_riga(riga: Dict) -> Dict:
    """Un titolo della watchlist (con l'ultimo prezzo salvato) nel formato del monitor."""
    ultimo = (riga.get('ultimo') or [None])[0]
    soglia = riga.get('soglia_avviso')
    return {
        'isin': riga['isin'],
        'nome': riga.get('nome') or riga['isin'],
        'simbolo': riga.get('simbolo'),
        'simbolo_borsa': riga.get('simbolo_borsa'),
        'valuta': riga.get('valuta'),
        'soglia': float(soglia) if soglia is not None else 0.5,
        'ultimo_prezzo': float(ultimo['prezzo']) if ultimo else None,
        'ultimo_ts': ultimo['ts'] if ultimo else None,
        # L'analisi serale di MyFinance (niente segnale se l'analisi è andata in errore)
        'segnale': None if riga.get('errore') else riga.get('segnale'),
        'punteggio': riga.get('punteggio'),
    }


def chiusure_storiche(giornaliero, oggi: datetime, periodi: List[int]) -> Dict[int, float]:
    """La chiusura di N giorni fa (o del giorno con dati prima), per la tabella."""
    risultato = {}
    for giorni in periodi:
        giorno = (oggi - timedelta(days=giorni)).date()
        precedenti = giornaliero[giornaliero['ts'].dt.date <= giorno]
        if not precedenti.empty:
            risultato[giorni] = float(precedenti['prezzo'].iloc[-1])
    return risultato


class ISINMonitor:

    def __init__(self, config: Dict):
        self.config = config
        telegram = config['telegram']
        self.bot_token = telegram['bot_token']
        self.telegram_configured = bool(telegram.get('enabled')) and self.bot_token != TOKEN_ESEMPIO
        if not self.telegram_configured:
            print("Telegram non configurato o disabilitato.")

        self.db = Database.da_configurazione(config)
        self.online = False  # True se la lista dei titoli è arrivata da Supabase
        self.irraggiungibile = False  # True se in questo giro Supabase non ha risposto (rete)
        self.log_offline = True  # False nei giri in cui le righe di Supabase giù si saltano
        self._ultimo_log_offline = float('-inf')  # time.monotonic() dell'ultima volta
        # Borsa Italiana risponde in meno di un secondo: un timeout lungo farebbe sforare il giro
        self.borsa = BorsaItalianaProvider(config.get('api', {}).get('borsa_timeout', 5))
        self.yahoo = YahooFinanceProvider(config.get('yahoo', {}))
        self.myfinance_url = config.get('myfinance_url', MYFINANCE_URL)
        self._chart_generator = None
        self.ultimo_mattino: Optional[str] = None  # giorno dei lavori del mattino prima di oggi
        self._sospetti: Dict[str, float] = {}  # ISIN -> prezzo con un salto da confermare
        # Pausa fra due avvisi sullo stesso titolo (in memoria: dopo un riavvio si riparte)
        self.errore_telegram = ''  # l'ultimo errore di Telegram, per il log dei comandi
        self.cooldown = timedelta(minutes=config['monitoring'].get('cooldown_minuti', 3))
        self._ultimi_avvisi: Dict[str, datetime] = {}  # ISIN -> ora dell'ultimo avviso
        self.richiesta_piu_lenta = ('', 0.0)  # la richiesta a Borsa più lenta dell'ultimo giro
        # Per il comando /stato del bot
        self.avviato: Optional[datetime] = None
        self.giri_fatti = self.avvisi_di_oggi = 0
        self.ultimo_giro: Optional[tuple] = None  # (ora, prezzi letti, titoli)

    @property
    def chart_generator(self):
        if self._chart_generator is None:
            from .chart_generator import ChartGenerator
            monitoring = self.config['monitoring']
            self._chart_generator = ChartGenerator(
                monitoring.get('price_comparison_days', [7, 30, 360]),
                monitoring.get('market_open_time', '08:55'),
                monitoring.get('market_close_time', '18:05'),
            )
        return self._chart_generator

    # --- titoli e prezzi -------------------------------------------------------------

    @profile()
    def carica_titoli(self) -> List[Dict]:
        """La watchlist da Supabase (salvata anche in locale); se non risponde, l'ultima salvata."""
        self.online = False
        self.irraggiungibile = False
        errore_db = None
        if self.db:
            try:
                titoli = [titolo_da_riga(riga) for riga in self.db.titoli()]
                self.online = True
            except ErroreDatabase as errore:
                errore_db = errore
                self.irraggiungibile = errore.status is None
            except ValueError:
                # Risposta 200 ma non JSON (es. la pagina d'errore di un proxy)
                errore_db = "Supabase: risposta non valida (non JSON)"
        if not self.online:
            titoli = stato.leggi('titoli.json', [])
            # Con Supabase giù le stesse righe a ogni giro: la prima volta e poi ogni 5 minuti
            self.log_offline = time.monotonic() - self._ultimo_log_offline >= LOG_OFFLINE
            if self.log_offline:
                self._ultimo_log_offline = time.monotonic()
                if errore_db:
                    print(f"⚠️ {errore_db}")
                print(f"⚠️ Uso l'ultima lista salvata ({len(titoli)} titoli)")
            return titoli
        if self._ultimo_log_offline != float('-inf'):
            print("✅ Supabase di nuovo raggiungibile")
            self._ultimo_log_offline = float('-inf')

        # I prezzi non ancora scritti nel database sono più recenti dell'ultimo salvato.
        # Le ore si confrontano come date: Supabase le dà in UTC, il monitor con il fuso di Roma
        for riga in stato.leggi('prezzi_in_sospeso.json', []):
            for titolo in titoli:
                if titolo['isin'] == riga['isin'] and (
                        not titolo['ultimo_ts']
                        or datetime.fromisoformat(titolo['ultimo_ts']) < datetime.fromisoformat(riga['ts'])):
                    titolo['ultimo_prezzo'], titolo['ultimo_ts'] = riga['prezzo'], riga['ts']
        stato.scrivi('titoli.json', titoli)
        return titoli

    def salva_prezzi(self, nuovi: List[Dict], titoli: List[Dict]) -> None:
        """Una sola scrittura per giro; se Supabase non risponde, i prezzi aspettano in locale."""
        isin_validi = {titolo['isin'] for titolo in titoli}
        in_sospeso = [riga for riga in stato.leggi('prezzi_in_sospeso.json', [])
                      if riga['isin'] in isin_validi]
        righe = in_sospeso + nuovi
        if not righe:
            return
        # Se Supabase non ha risposto per la lista, la scrittura aspetterebbe un altro timeout
        if self.db and not self.irraggiungibile:
            try:
                self.db.scrivi_prezzi(righe)
                if in_sospeso:
                    stato.scrivi('prezzi_in_sospeso.json', [])
                    print(f"💾 Scritti anche {len(in_sospeso)} prezzi rimasti in sospeso")
                return
            except ErroreDatabase as errore:
                print(f"❌ {errore}")
                if errore.status in RIFIUTATI:
                    # Rifiutati i dati: riprovarli non servirebbe
                    stato.scrivi('prezzi_in_sospeso.json', [])
                    return
        stato.scrivi('prezzi_in_sospeso.json', righe[-MAX_IN_SOSPESO:])
        if self.online or self.log_offline:
            print(f"⚠️ {len(righe)} prezzi in sospeso: li scrivo al prossimo giro")

    def leggi_prezzi(self, titoli: List[Dict], durata: float = INTERVALLO * 0.8) -> List[tuple]:
        """(prezzo o None, ora della lettura) di ogni titolo da Borsa Italiana.

        Le richieste sono distribuite su `durata` secondi, una ogni durata/N: Borsa Italiana
        risponde 429 (troppe richieste) alle raffiche. Dopo una risposta lenta le successive
        recuperano il ritardo a mezzo passo l'una dall'altra. Dopo un 429 il giro si
        interrompe, e anche dopo due titoli di fila senza risposta (rete giù: ogni timeout
        costa secondi).
        """
        self.borsa.troppe_richieste = False
        passo = durata / len(titoli)
        inizio = time.monotonic()
        prossima = inizio
        letture = []
        senza_risposta = saltati = 0
        self.richiesta_piu_lenta = ('', 0.0)  # (ISIN, secondi), per il log dei giri lenti
        for indice, titolo in enumerate(titoli):
            if self.borsa.troppe_richieste or senza_risposta >= 2:
                letture.append((None, None))
                saltati += 1
                continue
            attesa = prossima - time.monotonic()
            if attesa > 0:
                time.sleep(attesa)
            # Dopo una risposta lenta si recupera il ritardo (così il giro resta, se si può,
            # nei 15 secondi), ma con almeno mezzo passo fra due richieste: niente raffiche
            partenza = time.monotonic()
            prossima = max(inizio + (indice + 1) * passo, partenza + passo / 2)
            prezzo, _ = self.borsa.get_price(titolo['isin'])
            secondi = time.monotonic() - partenza
            if secondi > self.richiesta_piu_lenta[1]:
                self.richiesta_piu_lenta = (titolo['isin'], secondi)
            letture.append((prezzo, datetime.now(ROMA).replace(microsecond=0)))
            senza_risposta = senza_risposta + 1 if self.borsa.non_risponde else 0
        if self.borsa.troppe_richieste:
            print("⚠️ Borsa Italiana: troppe richieste (429 o 403), giro interrotto")
        elif saltati:
            print("⚠️ Borsa Italiana non risponde (rete o server): giro interrotto, riprovo al prossimo")
        return letture

    def esamina(self, titolo: Dict, prezzo: float, adesso: datetime,
                soglia: Optional[float] = None) -> Tuple[Optional[Dict], Optional[Dict]]:
        """Confronta il prezzo con l'ultimo salvato.

        Restituisce la riga da salvare (solo se il prezzo è cambiato) e l'avviso da
        mandare (se la variazione è almeno la soglia del titolo), o None. Dopo un avviso,
        per cooldown_minuti non ne parte un altro sullo stesso titolo (il prezzo si salva
        comunque); `soglia` data a mano (il test di ./setup.sh test) non ha cooldown.
        """
        prova = soglia is not None
        prezzo = round(prezzo, 4)
        precedente = titolo.get('ultimo_prezzo')
        soglia = titolo['soglia'] if soglia is None else soglia
        avviso = None
        if precedente:
            variazione = (prezzo - precedente) / precedente * 100
            # Un salto enorme può essere un prezzo letto male: si salva (e si avvisa) solo
            # se il giro dopo lo conferma, così un errore non resta nello storico
            sospetto = self._sospetti.pop(titolo['isin'], None)
            if abs(variazione) > SALTO_SOSPETTO and not (
                    sospetto and abs(prezzo / sospetto - 1) * 100 <= SALTO_SOSPETTO / 4):
                self._sospetti[titolo['isin']] = prezzo
                print(f"⚠️ {titolo['nome']}: {precedente:g} → {prezzo:g} ({variazione:+.1f}%), "
                      f"lo salvo solo se il prossimo giro lo conferma")
                return None, None
            ultimo_avviso = self._ultimi_avvisi.get(titolo['isin'])
            if abs(variazione) >= soglia and not prova and ultimo_avviso and \
                    adesso - ultimo_avviso < self.cooldown:
                # Un titolo in movimento continua a muoversi: niente raffiche di avvisi
                print(f"⏳ {titolo['nome']} {variazione:+.2f}%: avviso saltato, l'ultimo è "
                      f"delle {ultimo_avviso:%H:%M:%S}")
            elif abs(variazione) >= soglia:
                direzione = "aumento" if variazione > 0 else "calo"
                print(f"🎯 VARIAZIONE SIGNIFICATIVA! {titolo['nome']} - {direzione}: {abs(variazione):.2f}%")
                avviso = {'titolo': dict(titolo), 'prezzo': prezzo, 'precedente': precedente,
                          'adesso': adesso}
                if not prova:
                    self._ultimi_avvisi[titolo['isin']] = adesso
        if prezzo == precedente:
            return None, avviso
        titolo['ultimo_prezzo'], titolo['ultimo_ts'] = prezzo, adesso.isoformat()
        return {'isin': titolo['isin'], 'ts': adesso.isoformat(), 'prezzo': prezzo, 'fonte': 'borsa'}, avviso

    @profile()
    def giro(self) -> Tuple[List[Dict], List[Dict]]:
        """Un giro su tutti i titoli: prezzi da Borsa Italiana, una scrittura nel database.

        Restituisce i titoli e gli avvisi da mandare (li manda chi chiama).
        """
        inizio = time.monotonic()
        titoli = self.carica_titoli()
        supabase = time.monotonic() - inizio
        if not titoli:
            print("⚠️ Nessun titolo da controllare!")
            return [], []

        adesso = datetime.now(ROMA).replace(microsecond=0)
        nuovi, avvisi, letti = [], [], 0
        letture = self.leggi_prezzi(titoli)
        borsa = time.monotonic() - inizio - supabase
        for titolo, (prezzo, letto_alle) in zip(titoli, letture):
            if prezzo is None:
                continue
            letti += 1
            riga, avviso = self.esamina(titolo, prezzo, letto_alle)
            if riga:
                nuovi.append(riga)
            if avviso:
                avvisi.append(avviso)

        prima_di_salvare = time.monotonic()
        self.salva_prezzi(nuovi, titoli)
        supabase += time.monotonic() - prima_di_salvare
        stato.scrivi('titoli.json', titoli)
        cambiati = ', '.join(f"{t.get('simbolo_borsa') or t['nome']} {t['ultimo_prezzo']:g}"
                             for t in titoli if t['isin'] in {riga['isin'] for riga in nuovi})
        durata = time.monotonic() - inizio
        self.ultimo_giro = (adesso, letti, len(titoli))
        # Un giro oltre i 15 secondi salta il successivo: si dice chi l'ha rallentato
        lento = ''
        if durata > INTERVALLO:
            isin, secondi = self.richiesta_piu_lenta
            lento = (f": Borsa {borsa:.1f} s (più lenta {isin} {secondi:.1f} s), "
                     f"Supabase {supabase:.1f} s")
        print(f"🔍 {adesso:%H:%M:%S} {letti}/{len(titoli)} prezzi, {len(nuovi)} nuovi, "
              f"{len(avvisi)} avvisi ({durata:.1f} s{lento})"
              + (f": {cambiati}" if cambiati else ''))
        return titoli, avvisi

    def mattino_da_fare(self) -> bool:
        """True al primo giro del giorno con Supabase raggiungibile (e lo segna come fatto).

        In self.ultimo_mattino resta il giorno dei lavori del mattino precedenti.
        """
        oggi = datetime.now(ROMA).date().isoformat()
        prima = stato.leggi('mattino.json', {}).get('giorno')
        if not self.online or prima == oggi:
            return False
        self.ultimo_mattino = prima
        stato.scrivi('mattino.json', {'giorno': oggi})
        return True

    def controlla_tutti(self) -> None:
        """Un giro solo, tutto di seguito: prezzi, avvisi, lavori del mattino (per le prove)."""
        titoli, avvisi = self.giro()
        for avviso in avvisi:
            self.invia_avviso(**avviso)
        if self.mattino_da_fare():
            self.lavori_del_mattino(titoli)

    def monitora(self, ignora_orario: bool = False, giri: Optional[int] = None) -> None:
        """Un giro ogni 15 secondi finché si è in orario di mercato (poi esce).

        Avvisi, lavori del mattino e comandi del bot girano in thread a parte: un grafico
        lento o Yahoo non fanno saltare i giri dei prezzi. `giri` limita i giri (per i test).
        """
        coda: queue.Queue = queue.Queue()
        threading.Thread(target=self._spedisci_avvisi, args=(coda,), daemon=True).start()
        if self.telegram_configured and self.config['telegram'].get('comandi', True):
            from . import comandi
            threading.Thread(target=comandi.ascolta, args=(self, coda), daemon=True).start()
        mattino = None
        self.avviato = datetime.now(ROMA)
        fatti = errori = mandati = 0
        while ignora_orario or in_orario(self.config['monitoring'], datetime.now()):
            try:
                titoli, avvisi = self.giro()
                mandati += len(avvisi)
                self.avvisi_di_oggi = mandati
                for avviso in avvisi:
                    coda.put(avviso)
                if self.mattino_da_fare():
                    mattino = threading.Thread(target=self.lavori_del_mattino, args=(titoli,),
                                               daemon=True)
                    mattino.start()
            except Exception as errore:
                print(f"ERRORE: Errore nel giro: {descrivi(errore)}")
                errori += 1
            fatti += 1
            self.giri_fatti = fatti
            if self.borsa.troppe_richieste:
                print(f"⏸️ Pausa di {PAUSA_429} s per non farsi bloccare da Borsa Italiana")
                time.sleep(PAUSA_429)
            if giri is not None and fatti >= giri:
                break
            time.sleep(secondi_al_prossimo_giro(datetime.now()))

        print(f"⏹️ Fine dei giri: {fatti} giri ({errori} con errori), {mandati} avvisi; "
              f"finisco quelli in coda ed esco")
        coda.join()
        # Il riepilogo solo alla vera chiusura, dopo una giornata di giri (non nelle prove)
        if (fatti and not ignora_orario and giri is None and self.telegram_configured
                and self.config['telegram'].get('riepilogo', True)):
            self.manda_riepilogo()
        if mattino:
            mattino.join()

    def manda_riepilogo(self) -> None:
        """Alla chiusura, un messaggio con tutti i titoli e la variazione del giorno."""
        from .comandi import testo_prezzi
        adesso = datetime.now(ROMA)
        testo = testo_prezzi(self.db, stato.leggi('titoli.json', []), adesso,
                             f"Chiusura di oggi, {adesso:%d/%m}")
        if self.send_telegram_message(testo, anteprima=False):
            print("📨 Riepilogo della giornata inviato")

    def _spedisci_avvisi(self, coda: queue.Queue) -> None:
        """Thread degli avvisi: uno alla volta, nell'ordine in cui arrivano.

        Un avviso rimasto in coda troppo a lungo (Telegram giù per ore) non si manda più:
        arriverebbe insieme a tutti gli altri, con un prezzo ormai vecchio.
        """
        while True:
            avviso = coda.get()
            try:
                ritardo = datetime.now(ROMA) - avviso['adesso']
                if ritardo > MAX_RITARDO_AVVISO:
                    print(f"⏭️ Avviso per {avviso['titolo']['nome']} delle {avviso['adesso']:%H:%M} "
                          f"non mandato: troppo vecchio")
                    continue
                self.invia_avviso(**avviso)
            except Exception as errore:
                print(f"ERRORE: Avviso non mandato per {avviso['titolo']['isin']}: {descrivi(errore)}")
            finally:
                coda.task_done()

    # --- avvisi ------------------------------------------------------------------

    @profile()
    def dati_grafico(self, isin: str, adesso: datetime) -> Dict:
        """Storico per grafico e tabella, e la tua posizione sul titolo, tutto da Supabase."""
        from .chart_generator import GIORNI_DETTAGLIO, tabella_prezzi
        monitoring = self.config['monitoring']
        giorni = max(monitoring.get('price_comparison_days', [360])
                     + monitoring.get('historical_table_days', [360]))
        mezzanotte = adesso.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            operazioni = self.db.operazioni(isin)
        except ErroreDatabase as errore:
            print(f"⚠️ Operazioni di MyFinance non lette: {errore}")
            operazioni = []
        return {
            'oggi': tabella_prezzi(self.db.prezzi(isin, mezzanotte)),
            'recente': tabella_prezzi(
                self.db.serie(isin, mezzanotte - timedelta(days=GIORNI_DETTAGLIO), '15 minutes')),
            'giornaliero': tabella_prezzi(
                self.db.serie(isin, mezzanotte - timedelta(days=giorni + 5), '1 day')),
            'carico': posizioni.carico(operazioni, adesso.date()),
            'segni': posizioni.acquisti_e_vendite(operazioni),
        }

    def dati_tabella(self, prezzo: float, precedente: Optional[float], dati: Optional[Dict],
                     adesso: datetime) -> List[Dict]:
        if not dati:
            return TableDataGenerator.generate_table_data(prezzo, previous_price=precedente)
        from .chart_generator import dati_pannello
        monitoring = self.config['monitoring']
        periodi = monitoring.get('historical_table_days', [1, 7, 30, 360])
        giornaliero, oggi = dati['giornaliero'], dati['oggi']
        # Massimo e minimo sul periodo più lungo dei grafici, prezzo attuale compreso
        lungo = max(monitoring.get('price_comparison_days', [360]))
        chiusure = [*dati_pannello(lungo, dati['recente'], giornaliero,
                                   adesso.replace(tzinfo=None))['prezzo'], prezzo]
        return TableDataGenerator.generate_table_data(
            prezzo,
            opening_price=float(oggi['prezzo'].iloc[0]) if not oggi.empty else None,
            previous_price=precedente,
            historical_prices=chiusure_storiche(giornaliero, adesso, periodi),
            oldest_price=float(giornaliero['prezzo'].iloc[0]) if not giornaliero.empty else None,
            position=dati.get('carico'),
            extremes=(max(chiusure), min(chiusure)),
        )

    def grafico(self, titolo: Dict, prezzo: float, precedente: Optional[float],
                adesso: datetime, disegna: bool = True) -> tuple:
        """(PNG o None, righe della tabella) per un titolo, dallo storico di Supabase."""
        dati = None
        if self.db:
            try:
                dati = self.dati_grafico(titolo['isin'], adesso)
            except ErroreDatabase as errore:
                print(f"⚠️ Storico non disponibile per il grafico: {errore}")
        tabella = self.dati_tabella(prezzo, precedente, dati, adesso)
        if not dati or not disegna:
            return None, tabella
        png = self.chart_generator.create_comprehensive_chart(
            titolo['nome'], prezzo, precedente, tabella,
            dati['oggi'], dati['recente'], dati['giornaliero'],
            adesso.replace(tzinfo=None),
            carico=dati['carico']['prezzo'] if dati.get('carico') else None,
            segni=dati.get('segni'),
            segnale=titolo.get('segnale'), punteggio=titolo.get('punteggio'),
        )
        return png, tabella

    @profile()
    def invia_avviso(self, titolo: Dict, prezzo: float, precedente: Optional[float],
                     adesso: datetime) -> None:
        """Avviso su Telegram: grafico con didascalia, o solo testo se il grafico non riesce."""
        if not self.telegram_configured:
            return
        link = proposte.link_myfinance(self.myfinance_url, titolo['isin'])
        png, tabella = None, None
        try:
            png, tabella = self.grafico(titolo, prezzo, precedente, adesso,
                                        self.config['telegram'].get('send_charts', True))
        except Exception as errore:
            print(f"❌ Errore generazione grafico per {titolo['isin']}: {descrivi(errore)}")
        if tabella is None:
            tabella = TableDataGenerator.generate_table_data(prezzo, previous_price=precedente)
        caption = CaptionTemplates.format_caption(titolo, prezzo, tabella, link,
                                                  self.borsa.scheda(titolo['isin']))

        if png and self.send_telegram_photo(png, caption, f"isin_chart_{titolo['isin']}.png"):
            print(f"📨 Grafico inviato per {titolo['nome']}")
        elif self.send_telegram_message(caption):
            print(f"📨 Messaggio inviato per {titolo['nome']}")
        else:
            print(f"❌ Fallito invio notifica per {titolo['nome']}")

    # --- lavori del mattino ------------------------------------------------------

    def lavori_del_mattino(self, titoli: List[Dict]) -> None:
        """Primo avvio del giorno: buchi dello storico con Yahoo e proposte di MyFinance."""
        print("🌅 Primo avvio di oggi: riempio i buchi dello storico e controllo le proposte")
        if self.config.get('yahoo', {}).get('enabled', True):
            adesso = datetime.now(ROMA)
            # Più di 6 giorni senza monitor (vacanze): i 7 giorni al minuto non bastano
            prima = self.ultimo_mattino
            lontano = prima is not None and (adesso.date() - date.fromisoformat(prima)).days > 6
            if lontano:
                print(f"🧳 Ultimo avvio il {prima}: riempio tutto lo storico, non solo 7 giorni")
            try:
                self.riempi_buchi(titoli, adesso, completo=lontano)
            except Exception as errore:
                # Un errore imprevisto nello storico non deve fermare le proposte
                print(f"ERRORE: Riempimento dello storico interrotto: {errore}")
        try:
            self.controlla_proposte()
        except (ErroreDatabase, ValueError) as errore:
            print(f"⚠️ Proposte non controllate: {errore}")

    def riempi_buchi(self, titoli: List[Dict], adesso: datetime, completo: bool = False,
                     scrivi: bool = True) -> int:
        """Buchi dello storico con Yahoo: gli ultimi 7 giorni, o l'anno intero (`completo`).

        Ogni titolo ha l'anno intero una volta (anche se aggiunto in giornata, o se cambia
        simbolo_borsa): i titoli già riempiti sono in storico_completo.json.
        """
        completi = set(stato.leggi('storico_completo.json', []))
        totale = 0
        for titolo in titoli:
            chiave = f"{titolo['isin']} {storico.simbolo_yahoo(titolo)}"
            intero = completo or chiave not in completi
            try:
                aggiunti = storico.riempi_titolo(
                    self.db, self.yahoo, titolo,
                    storico.COMPLETO if intero else storico.GIORNALIERO, adesso, scrivi)
            except ErroreDatabase as errore:
                print(f"⚠️ {titolo['isin']}: {errore}")
                continue
            totale += aggiunti or 0
            if intero and aggiunti is not None and scrivi:
                completi.add(chiave)
        stato.scrivi('storico_completo.json', sorted(completi))
        return totale

    def controlla_proposte(self) -> None:
        """Manda su Telegram i cambiamenti di segnale e proposta del giorno, se ce ne sono."""
        attuale = proposte.stato_attuale(self.db.proposte())
        prima = stato.leggi('proposte.json')
        if prima is None:
            stato.scrivi('proposte.json', attuale)
            print("📋 Proposte: primo stato salvato (i cambiamenti arriveranno dai prossimi giorni)")
            return
        cambi = proposte.cambiamenti(prima, attuale)
        testo = proposte.messaggio(prima, attuale, cambi, self.myfinance_url)
        if testo is None:
            print("📋 Proposte: nessun cambiamento")
            return
        if self.send_telegram_message(testo, anteprima=False):
            stato.scrivi('proposte.json', attuale)
            print(f"📨 Proposte inviate ({len(cambi['segnali'])} segnali cambiati)")

    # --- comandi manuali ---------------------------------------------------------

    def run_test(self) -> None:
        """Controlla il primo titolo con soglia 0: manda sempre l'avviso, non salva niente."""
        titoli = self.carica_titoli()
        if not titoli:
            print("⚠️ Nessun titolo configurato!")
            return
        titolo = titoli[0]
        print(f"🧪 Test: controllo {titolo['nome']} con soglia 0")
        prezzo, _ = self.borsa.get_price(titolo['isin'])
        if prezzo is None:
            print(f"❌ Nessun prezzo per {titolo['nome']} (borsa non ancora aperta?): niente avviso")
            return
        _, avviso = self.esamina(titolo, prezzo, datetime.now(ROMA).replace(microsecond=0), soglia=0)
        if avviso:
            self.invia_avviso(**avviso)

    def salva_grafico(self, isin: str, percorso: str) -> None:
        """Disegna il grafico di un titolo con l'ultimo prezzo salvato (senza Telegram)."""
        titolo = next((t for t in self.carica_titoli() if t['isin'] == isin), None)
        if not titolo or titolo['ultimo_prezzo'] is None:
            print(f"❌ {isin}: titolo non in watchlist o senza prezzi")
            return
        adesso = datetime.now(ROMA).replace(microsecond=0)
        png, tabella = self.grafico(titolo, titolo['ultimo_prezzo'], None, adesso)
        if png is None:
            print("❌ Grafico non disponibile")
            return
        with open(percorso, 'wb') as file:
            file.write(png)
        print(f"🖼️ Grafico salvato in {percorso}")
        print(CaptionTemplates.format_caption(
            titolo, titolo['ultimo_prezzo'], tabella,
            proposte.link_myfinance(self.myfinance_url, isin)))

    def riempi_storico(self, scrivi: bool = True) -> None:
        """Riempimento completo con Yahoo (7 giorni al minuto, 60 ai 5 minuti, un anno al giorno)."""
        titoli = self.carica_titoli()
        if not self.online:
            print("❌ Serve Supabase per riempire lo storico")
            return
        totale = self.riempi_buchi(titoli, datetime.now(ROMA), completo=True, scrivi=scrivi)
        print(f"✅ {totale} punti Yahoo {'aggiunti' if scrivi else 'da aggiungere (prova)'}")

    def stato_telegram(self, togli_webhook: bool = False) -> None:
        """Lo stato del bot per capire perché i comandi non vanno: nome, webhook, errori.

        Non manda messaggi e non legge i comandi (getUpdates li toglierebbe al monitor).
        Il token non si stampa; del webhook solo il nome del server.
        """
        if not self.telegram_configured:
            print("❌ Telegram non configurato!")
            return
        bot = self.chiama_telegram('getMe')
        if bot is None:
            return
        print(f"🤖 Bot: @{bot.get('username')} ({bot.get('first_name')})")
        if togli_webhook and self.chiama_telegram('deleteWebhook', data={'drop_pending_updates': False}):
            print("🗑️ Webhook tolto: i comandi del bot ripartono al prossimo tentativo (entro 30 s)")
        info = self.chiama_telegram('getWebhookInfo') or {}
        if info.get('url'):
            from urllib.parse import urlparse
            print(f"🔗 Webhook attivo verso {urlparse(info['url']).netloc}: Telegram manda lì i "
                  f"messaggi e i comandi di ISIN Monitor non funzionano. Se quel programma non "
                  f"ti serve più: ./setup.sh telegram togli-webhook")
        else:
            print("🔗 Nessun webhook: i comandi li legge ISIN Monitor (getUpdates)")
        print(f"📬 Messaggi in attesa: {info.get('pending_update_count', 0)}")
        if info.get('last_error_message'):
            quando = datetime.fromtimestamp(info.get('last_error_date', 0), ROMA)
            print(f"⚠️ Ultimo errore del webhook ({quando:%d/%m %H:%M}): {info['last_error_message']}")

    def test_telegram(self) -> None:
        if not self.telegram_configured:
            print("❌ Telegram non configurato!")
            return
        from .orario import descrizione_orario
        testo = CaptionTemplates.format_test_caption(
            len(self.carica_titoli()), descrizione_orario(self.config['monitoring']))
        if self.send_telegram_message(testo):
            print("✅ Messaggio di test inviato con successo!")
        else:
            print("❌ Errore nell'invio del messaggio di test")

    # --- Telegram ----------------------------------------------------------------

    def send_telegram_message(self, message: str, anteprima: bool = True) -> bool:
        """Invia un messaggio su Telegram (HTML), con l'anteprima del primo link se `anteprima`."""
        if not self.telegram_configured:
            return False
        return self._telegram('sendMessage', data={
            'chat_id': self.config['telegram'].get('chat_id'),
            'parse_mode': 'HTML',
            'text': message,
            'disable_web_page_preview': not anteprima,
        })

    def send_telegram_photo(self, photo_data: bytes, caption: str = "", filename: str = "chart.png") -> bool:
        """Invia una foto su Telegram con didascalia (HTML)."""
        if not self.telegram_configured:
            return False
        return self._telegram('sendPhoto', data={
            'chat_id': self.config['telegram'].get('chat_id'),
            'caption': caption,
            'parse_mode': 'HTML',
        }, files={'photo': (filename, photo_data, 'image/png')})

    def _telegram(self, metodo: str, **kwargs) -> bool:
        """Manda qualcosa su Telegram: True se è andato."""
        return self.chiama_telegram(metodo, **kwargs) is not None

    def chiama_telegram(self, metodo: str, timeout: Optional[float] = None,
                        silenzioso: bool = False, **kwargs):
        """Il risultato di un metodo dell'API di Telegram, o None se non è andato.

        `silenzioso` non scrive gli errori nel log (per la lettura dei comandi, che riprova
        da sola e scrive lei una riga quando smette di funzionare).
        """
        if not self.config['telegram'].get('chat_id'):
            print("ERRORE: Chat ID Telegram non configurato!")
            return None
        # Timeout più alto per l'upload delle foto
        timeout = timeout or max(self.config.get('api', {}).get('request_timeout', 10), 30)
        for tentativo in range(2):
            try:
                # Senza sessione condivisa: lo chiamano i thread degli avvisi, del mattino e dei comandi
                risposta = requests.post(
                    f"https://api.telegram.org/bot{self.bot_token}/{metodo}", timeout=timeout, **kwargs
                )
                dati = risposta.json()
            except (requests.RequestException, ValueError) as errore:
                # Il messaggio di requests contiene l'URL con il token: non si stampa
                self.errore_telegram = f"non raggiungibile ({errore.__class__.__name__})"
                if not silenzioso:
                    print(f"ERRORE: Telegram non raggiungibile ({errore.__class__.__name__})")
                return None
            if dati.get('ok', False):
                return dati.get('result', True)
            # Troppi messaggi insieme (es. tanti avvisi all'apertura): Telegram dice quanto aspettare
            attesa = (dati.get('parameters') or {}).get('retry_after')
            if attesa and tentativo == 0 and attesa <= MAX_ATTESA_TELEGRAM:
                print(f"⏸️ Telegram: troppi messaggi, riprovo fra {attesa} s")
                time.sleep(attesa)
                continue
            break
        # La risposta di Telegram (es. "Conflict: ..." 409), senza l'URL col token
        self.errore_telegram = f"{dati.get('description', 'errore sconosciuto')} ({dati.get('error_code')})"
        if not silenzioso:
            print(f"ERRORE: Errore nell'invio Telegram: {dati.get('description', 'sconosciuto')}")
        return None
