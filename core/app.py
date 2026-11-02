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
from datetime import date, datetime, timedelta
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
# Attesa massima chiesta da Telegram (retry_after) per riprovare un invio
MAX_ATTESA_TELEGRAM = 120
# Pausa dopo una risposta 429 (troppe richieste) di Borsa Italiana
PAUSA_429 = 60


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
        timeout = config.get('api', {}).get('request_timeout', 10)
        self.borsa = BorsaItalianaProvider(timeout)
        self.yahoo = YahooFinanceProvider(config.get('yahoo', {}))
        self.myfinance_url = config.get('myfinance_url', MYFINANCE_URL)
        self._chart_generator = None
        self.ultimo_mattino: Optional[str] = None  # giorno dei lavori del mattino prima di oggi
        self._sospetti: Dict[str, float] = {}  # ISIN -> prezzo con un salto da confermare

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
        if self.db:
            try:
                titoli = [titolo_da_riga(riga) for riga in self.db.titoli()]
                self.online = True
            except ErroreDatabase as errore:
                print(f"⚠️ {errore}")
                self.irraggiungibile = errore.status is None
        if not self.online:
            titoli = stato.leggi('titoli.json', [])
            print(f"⚠️ Uso l'ultima lista salvata ({len(titoli)} titoli)")
            return titoli

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
        print(f"⚠️ {len(righe)} prezzi in sospeso: li scrivo al prossimo giro")

    def leggi_prezzi(self, titoli: List[Dict], durata: float = INTERVALLO * 0.8) -> List[tuple]:
        """(prezzo o None, ora della lettura) di ogni titolo da Borsa Italiana.

        Le richieste sono distribuite su `durata` secondi, una ogni durata/N: Borsa Italiana
        risponde 429 (troppe richieste) alle raffiche. Dopo un 429 il giro si interrompe.
        """
        self.borsa.troppe_richieste = False
        passo = durata / len(titoli)
        prossima = time.monotonic()
        letture = []
        for titolo in titoli:
            if self.borsa.troppe_richieste:
                letture.append((None, None))
                continue
            attesa = prossima - time.monotonic()
            if attesa > 0:
                time.sleep(attesa)
            # Il passo conta dall'inizio di questa richiesta: dopo una risposta lenta le
            # richieste dopo restano distanziate (il giro dura di più) invece di partire a raffica
            prossima = time.monotonic() + passo
            prezzo, _ = self.borsa.get_price(titolo['isin'])
            letture.append((prezzo, datetime.now(ROMA).replace(microsecond=0)))
        if self.borsa.troppe_richieste:
            print("⚠️ Borsa Italiana: troppe richieste (429), giro interrotto")
        return letture

    def esamina(self, titolo: Dict, prezzo: float, adesso: datetime,
                soglia: Optional[float] = None) -> Tuple[Optional[Dict], Optional[Dict]]:
        """Confronta il prezzo con l'ultimo salvato.

        Restituisce la riga da salvare (solo se il prezzo è cambiato) e l'avviso da
        mandare (se la variazione è almeno la soglia del titolo), o None.
        """
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
            if abs(variazione) >= soglia:
                direzione = "aumento" if variazione > 0 else "calo"
                print(f"🎯 VARIAZIONE SIGNIFICATIVA! {titolo['nome']} - {direzione}: {abs(variazione):.2f}%")
                avviso = {'titolo': dict(titolo), 'prezzo': prezzo, 'precedente': precedente,
                          'adesso': adesso}
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
        if not titoli:
            print("⚠️ Nessun titolo da controllare!")
            return [], []

        adesso = datetime.now(ROMA).replace(microsecond=0)
        nuovi, avvisi, letti = [], [], 0
        for titolo, (prezzo, letto_alle) in zip(titoli, self.leggi_prezzi(titoli)):
            if prezzo is None:
                continue
            letti += 1
            riga, avviso = self.esamina(titolo, prezzo, letto_alle)
            if riga:
                nuovi.append(riga)
            if avviso:
                avvisi.append(avviso)

        self.salva_prezzi(nuovi, titoli)
        stato.scrivi('titoli.json', titoli)
        cambiati = ', '.join(f"{t.get('simbolo_borsa') or t['nome']} {t['ultimo_prezzo']:g}"
                             for t in titoli if t['isin'] in {riga['isin'] for riga in nuovi})
        print(f"🔍 {adesso:%H:%M:%S} {letti}/{len(titoli)} prezzi, {len(nuovi)} nuovi, "
              f"{len(avvisi)} avvisi ({time.monotonic() - inizio:.1f} s)"
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

        Avvisi e lavori del mattino girano in thread a parte: un grafico lento o Yahoo
        non fanno saltare i giri dei prezzi. `giri` limita i giri (per i test).
        """
        coda: queue.Queue = queue.Queue()
        threading.Thread(target=self._spedisci_avvisi, args=(coda,), daemon=True).start()
        mattino = None
        fatti = 0
        while ignora_orario or in_orario(self.config['monitoring'], datetime.now()):
            try:
                titoli, avvisi = self.giro()
                for avviso in avvisi:
                    coda.put(avviso)
                if self.mattino_da_fare():
                    mattino = threading.Thread(target=self.lavori_del_mattino, args=(titoli,),
                                               daemon=True)
                    mattino.start()
            except Exception as errore:
                print(f"ERRORE: Errore nel giro: {errore}")
            fatti += 1
            if self.borsa.troppe_richieste:
                print(f"⏸️ Pausa di {PAUSA_429} s per non farsi bloccare da Borsa Italiana")
                time.sleep(PAUSA_429)
            if giri is not None and fatti >= giri:
                break
            time.sleep(secondi_al_prossimo_giro(datetime.now()))

        print("⏹️ Fine dei giri (fuori orario): finisco gli avvisi in coda ed esco")
        coda.join()
        if mattino:
            mattino.join()

    def _spedisci_avvisi(self, coda: queue.Queue) -> None:
        """Thread degli avvisi: uno alla volta, nell'ordine in cui arrivano."""
        while True:
            avviso = coda.get()
            try:
                self.invia_avviso(**avviso)
            except Exception as errore:
                print(f"ERRORE: Avviso non mandato per {avviso['titolo']['isin']}: {errore}")
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
            print(f"❌ Errore generazione grafico per {titolo['isin']}: {errore}")
        if tabella is None:
            tabella = TableDataGenerator.generate_table_data(prezzo, previous_price=precedente)
        caption = CaptionTemplates.format_caption(titolo, prezzo, tabella, link)

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
            self.riempi_buchi(titoli, adesso, completo=lontano)
        try:
            self.controlla_proposte()
        except ErroreDatabase as errore:
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

    def test_telegram(self) -> None:
        if not self.telegram_configured:
            print("❌ Telegram non configurato!")
            return
        if self.send_telegram_message(CaptionTemplates.format_test_caption()):
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
        if not self.config['telegram'].get('chat_id'):
            print("ERRORE: Chat ID Telegram non configurato!")
            return False
        # Timeout più alto per l'upload delle foto
        timeout = max(self.config.get('api', {}).get('request_timeout', 10), 30)
        for tentativo in range(2):
            try:
                # Senza sessione condivisa: lo chiamano sia il thread degli avvisi sia quello del mattino
                risposta = requests.post(
                    f"https://api.telegram.org/bot{self.bot_token}/{metodo}", timeout=timeout, **kwargs
                )
                dati = risposta.json()
            except (requests.RequestException, ValueError) as errore:
                # Il messaggio di requests contiene l'URL con il token: non si stampa
                print(f"ERRORE: Telegram non raggiungibile ({errore.__class__.__name__})")
                return False
            if dati.get('ok', False):
                return True
            # Troppi messaggi insieme (es. tanti avvisi all'apertura): Telegram dice quanto aspettare
            attesa = (dati.get('parameters') or {}).get('retry_after')
            if attesa and tentativo == 0 and attesa <= MAX_ATTESA_TELEGRAM:
                print(f"⏸️ Telegram: troppi messaggi, riprovo fra {attesa} s")
                time.sleep(attesa)
                continue
            break
        print(f"ERRORE: Errore nell'invio Telegram: {dati.get('description', 'sconosciuto')}")
        return False
