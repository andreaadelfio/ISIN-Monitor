"""Lista dei titoli con la cache locale e il giro di controllo, con database, Borsa
Italiana e Telegram finti (nessun messaggio parte davvero)."""

from datetime import datetime

import pytest

from core import app as modulo_app
from core import stato
from core.app import ISINMonitor
from core.database import ErroreDatabase

RIGHE_WATCHLIST = [
    {'isin': 'IT0003132476', 'nome': 'Eni', 'simbolo': 'ENI.MI', 'simbolo_borsa': 'ENI.MI',
     'valuta': 'EUR', 'soglia_avviso': 0.5,
     'ultimo': [{'ts': '2026-10-27T09:00:00+01:00', 'prezzo': 20.0}]},
    {'isin': 'US0231351067', 'nome': 'Amazon', 'simbolo': 'AMZN', 'simbolo_borsa': '1AMZN.MI',
     'valuta': 'USD', 'soglia_avviso': 1, 'ultimo': []},
]


class DbFinto:
    def __init__(self, righe=RIGHE_WATCHLIST, rotto=False):
        self.righe = righe
        self.rotto = rotto
        self.scritture = []
        self.registro = {}   # operazioni del registro investimenti per ISIN

    def titoli(self):
        if self.rotto:
            raise ErroreDatabase('Supabase non raggiungibile: ConnectionError')
        return [dict(riga) for riga in self.righe]

    def scrivi_prezzi(self, righe):
        if self.rotto:
            raise ErroreDatabase('Supabase non raggiungibile: ConnectionError')
        self.scritture.append(list(righe))

    def prezzi(self, isin, da):
        return [{'ts': '2026-10-27T09:00:00+01:00', 'prezzo': 20.0}]

    def serie(self, isin, da, passo):
        return [{'ts': '2026-10-20T00:00:00+01:00', 'prezzo': 19.0},
                {'ts': '2026-10-27T00:00:00+01:00', 'prezzo': 20.0}]

    def operazioni(self, isin):
        return self.registro.get(isin, [])


class BorsaFinta:
    def __init__(self, prezzi):
        self.prezzi = prezzi
        self.troppe_richieste = False
        self.non_risponde = False

    def get_price(self, isin):
        return self.prezzi.get(isin), None

    def scheda(self, isin):
        return f'https://www.borsaitaliana.it/borsa/etf/scheda/{isin}-ETFP.html'


@pytest.fixture
def monitor(config, monkeypatch):
    istanza = ISINMonitor(config)
    istanza.db = DbFinto()
    istanza.telegram_inviati = []

    def telegram_finto(metodo, **kwargs):
        istanza.telegram_inviati.append((metodo, kwargs['data']))
        return True

    monkeypatch.setattr(istanza, '_telegram', telegram_finto)

    def nessuna_chiamata_vera(metodo, **kwargs):
        raise AssertionError(f'chiamata vera a Telegram: {metodo}')

    monkeypatch.setattr(istanza, 'chiama_telegram', nessuna_chiamata_vera)
    # Orologio finto: le pause fra una richiesta e l'altra non fanno aspettare i test
    istanza.pause = []
    orologio = [1000.0]

    def dormi(secondi):
        istanza.pause.append(secondi)
        orologio[0] += secondi

    monkeypatch.setattr(modulo_app.time, 'sleep', dormi)
    monkeypatch.setattr(modulo_app.time, 'monotonic', lambda: orologio[0])
    # Niente lavori del mattino (Yahoo, proposte) in questi test
    stato.scrivi('mattino.json', {'giorno': datetime.now(modulo_app.ROMA).date().isoformat()})
    return istanza


def test_lista_da_supabase_salvata_in_cache(monitor):
    titoli = monitor.carica_titoli()
    assert monitor.online
    assert [t['isin'] for t in titoli] == ['IT0003132476', 'US0231351067']
    assert titoli[0]['ultimo_prezzo'] == 20.0 and titoli[0]['soglia'] == 0.5
    assert titoli[1]['ultimo_prezzo'] is None
    assert stato.leggi('titoli.json') == titoli


def test_senza_supabase_usa_la_cache(monitor):
    monitor.carica_titoli()
    monitor.db = DbFinto(rotto=True)
    titoli = monitor.carica_titoli()
    assert not monitor.online
    assert [t['isin'] for t in titoli] == ['IT0003132476', 'US0231351067']


def test_senza_supabase_e_senza_cache_lista_vuota(monitor):
    monitor.db = DbFinto(rotto=True)
    assert monitor.carica_titoli() == []


def test_giro_una_scrittura_e_avviso_con_link(monitor):
    # Eni +1% (soglia 0.5): avviso; Amazon senza prezzo precedente: solo salvato
    monitor.borsa = BorsaFinta({'IT0003132476': 20.2, 'US0231351067': 220.0})
    monitor.controlla_tutti()

    assert len(monitor.db.scritture) == 1
    righe = monitor.db.scritture[0]
    assert [(r['isin'], r['prezzo'], r['fonte']) for r in righe] == [
        ('IT0003132476', 20.2, 'borsa'), ('US0231351067', 220.0, 'borsa')]

    assert len(monitor.telegram_inviati) == 1
    metodo, dati = monitor.telegram_inviati[0]
    assert metodo == 'sendPhoto'
    # Sotto il grafico solo il nome e i link (il resto è nell'immagine); il link a Borsa
    # Italiana è la scheda letta dal monitor
    assert dati['caption'] == (
        'Eni\n'
        '<a href="https://finecobank.com/pvt/trading/snapshot/IT0003132476.AFF">Fineco</a> · '
        '<a href="https://www.borsaitaliana.it/borsa/etf/scheda/IT0003132476-ETFP.html">Borsa IT</a> · '
        '<a href="https://esempio.pages.dev/?isin=IT0003132476">MyFinance</a>')
    # La cache ha i prezzi nuovi: il prossimo giro (anche offline) confronta con questi
    assert stato.leggi('titoli.json')[0]['ultimo_prezzo'] == 20.2


def test_avviso_con_la_tua_posizione(monitor):
    monitor.db.registro['IT0003132476'] = [
        {'posizione': 3, 'data': '2026-01-10', 'operazione': 'Investimento', 'importo': '-180',
         'quantita': '10', 'abp': None}]
    monitor.borsa = BorsaFinta({'IT0003132476': 20.2})
    monitor.config['telegram']['send_charts'] = False     # il messaggio di testo, con la tabella
    monitor.controlla_tutti()
    metodo, dati = monitor.telegram_inviati[0]
    assert metodo == 'sendMessage'
    # Nome, prezzo e variazione in testa: si vedono già nella notifica
    assert dati['text'].startswith('<b>Eni</b> €20.2 📈 +1.00%\n')
    # Carico 18 €: +2.2 € per quota, +22 € su 10 quote
    assert 'Carico   €18.00 +12.22%\n  10 quote: +22.00€' in dati['text']
    # Massimo e minimo dell'anno, prezzo attuale compreso (qui è il nuovo massimo)
    assert 'Max      €20.20  +0.00%' in dati['text']
    assert 'Min      €19.00  +6.32%' in dati['text']


def test_foto_che_non_parte_messaggio_con_tutto(monitor):
    inviati = monitor.telegram_inviati

    def telegram(metodo, **kwargs):
        if metodo == 'sendPhoto':
            return False                                  # anche dopo i nuovi tentativi
        inviati.append((metodo, kwargs['data']))
        return True

    monitor._telegram = telegram
    monitor.borsa = BorsaFinta({'IT0003132476': 20.2})
    monitor.controlla_tutti()
    assert [metodo for metodo, dati in inviati] == ['sendMessage']
    assert inviati[0][1]['text'].startswith('<b>Eni</b> €20.2 📈 +1.00%\n') and '<code>' in inviati[0][1]['text']


def test_segnale_di_myfinance_solo_senza_errori():
    riga = {'isin': 'IT0003132476', 'segnale': 'compra', 'punteggio': 78, 'ultimo': []}
    assert (modulo_app.titolo_da_riga(riga)['segnale'], modulo_app.titolo_da_riga(riga)['punteggio']) == (
        'compra', 78)
    assert modulo_app.titolo_da_riga({**riga, 'errore': 'Yahoo non risponde'})['segnale'] is None


def test_sotto_soglia_niente_avviso_e_invariato_non_salvato(monitor):
    monitor.borsa = BorsaFinta({'IT0003132476': 20.0, 'US0231351067': None})
    monitor.controlla_tutti()
    assert monitor.db.scritture == [] and monitor.telegram_inviati == []

    monitor.borsa = BorsaFinta({'IT0003132476': 20.09})   # +0.45%
    monitor.controlla_tutti()
    assert len(monitor.db.scritture) == 1 and monitor.telegram_inviati == []


def test_calo_sopra_soglia_manda_avviso(monitor):
    monitor.borsa = BorsaFinta({'IT0003132476': 19.9})   # -0.5%
    monitor.controlla_tutti()
    assert len(monitor.telegram_inviati) == 1


def test_prezzi_in_sospeso_se_supabase_non_risponde(monitor):
    monitor.carica_titoli()
    monitor.db.rotto = True
    monitor.borsa = BorsaFinta({'IT0003132476': 20.3})
    monitor.controlla_tutti()   # lista dalla cache, scrittura fallita
    assert [r['prezzo'] for r in stato.leggi('prezzi_in_sospeso.json')] == [20.3]

    monitor.db.rotto = False
    monitor.borsa = BorsaFinta({'IT0003132476': 20.3})
    monitor.controlla_tutti()   # stesso prezzo del sospeso: niente avviso, sospeso scritto
    assert [r['prezzo'] for r in monitor.db.scritture[0]] == [20.3]
    assert stato.leggi('prezzi_in_sospeso.json') == []


def test_proposte_al_primo_avvio_del_giorno(monitor, monkeypatch):
    righe = [{'isin': 'A', 'nome': 'Alfa', 'segnale': 'attendi', 'punteggio': 50, 'errore': None}]
    monitor.db.proposte = lambda: righe
    monitor.controlla_proposte()                       # primo stato: salvato, niente messaggio
    assert monitor.telegram_inviati == []
    righe[0] = {**righe[0], 'segnale': 'compra'}
    monitor.controlla_proposte()
    assert len(monitor.telegram_inviati) == 1
    assert 'https://esempio.pages.dev/?isin=A' in monitor.telegram_inviati[0][1]['text']
    monitor.controlla_proposte()                       # già mandate: niente di nuovo
    assert len(monitor.telegram_inviati) == 1


def test_lavori_del_mattino_una_volta_al_giorno(monitor, monkeypatch):
    chiamate = []
    monkeypatch.setattr(monitor, 'lavori_del_mattino', lambda titoli: chiamate.append(len(titoli)))
    stato.scrivi('mattino.json', {'giorno': '2000-01-01'})
    monitor.borsa = BorsaFinta({})
    monitor.controlla_tutti()
    monitor.controlla_tutti()
    assert chiamate == [2]


class BorsaCrescente(BorsaFinta):
    """Eni sale dell'1% a ogni lettura: un avviso a ogni giro."""

    def __init__(self):
        self.prezzo = 20.0
        self.troppe_richieste = False
        self.non_risponde = False

    def get_price(self, isin):
        if isin != 'IT0003132476':
            return None, None
        self.prezzo = round(self.prezzo * 1.01, 4)
        return self.prezzo, None


def test_monitora_avvisi_in_un_thread_che_non_blocca_i_giri(monitor, monkeypatch, capsys):
    import threading

    from datetime import timedelta
    monitor.borsa = BorsaCrescente()
    monitor.cooldown = timedelta(0)        # qui servono due avvisi di fila sullo stesso titolo
    tutti_e_due_i_giri = threading.Event()
    thread_avvisi = []

    def telegram_lento(metodo, **kwargs):
        # Il primo avviso aspetta che il loop abbia già fatto anche il secondo giro:
        # se gli avvisi bloccassero i giri, qui si resterebbe fermi fino al timeout
        assert tutti_e_due_i_giri.wait(timeout=5)
        thread_avvisi.append(threading.current_thread().name)
        monitor.telegram_inviati.append((metodo, kwargs['data']))
        return True

    monkeypatch.setattr(monitor, '_telegram', telegram_lento)
    scrivi = monitor.db.scrivi_prezzi

    def scrivi_e_segna(righe):
        scrivi(righe)
        if len(monitor.db.scritture) == 2:
            tutti_e_due_i_giri.set()

    monitor.db.scrivi_prezzi = scrivi_e_segna
    monitor.monitora(ignora_orario=True, giri=2)

    assert [r[0]['prezzo'] for r in monitor.db.scritture] == [20.2, 20.402]
    assert len(monitor.telegram_inviati) == 2          # monitora aspetta la coda prima di uscire
    assert 'Fine dei giri: 2 giri (0 con errori), 2 avvisi' in capsys.readouterr().out
    assert threading.main_thread().name not in thread_avvisi


def test_monitora_esce_fuori_orario(monitor, monkeypatch):
    monkeypatch.setattr(modulo_app, 'in_orario', lambda monitoring, adesso: False)
    monitor.borsa = BorsaFinta({})
    monitor.monitora()
    assert monitor.db.scritture == []
    assert monitor.telegram_inviati == []          # nessun giro: niente riepilogo


def test_riepilogo_alla_chiusura_dopo_i_giri(monitor, monkeypatch):
    orari = iter([True, False])
    monkeypatch.setattr(modulo_app, 'in_orario', lambda monitoring, adesso: next(orari))
    monitor.borsa = BorsaFinta({'IT0003132476': 20.0})
    monitor.monitora()
    assert [dati['text'].startswith('📊 <b>Chiusura di oggi, ') for metodo, dati in monitor.telegram_inviati] == [True]


def test_soglia_zero_avvisa_anche_a_prezzo_invariato(monitor):
    titolo = monitor.carica_titoli()[0]
    riga, avviso = monitor.esamina(titolo, 20.0, datetime(2026, 10, 29, 10, tzinfo=modulo_app.ROMA), soglia=0)
    assert riga is None and avviso['prezzo'] == 20.0


def test_richieste_distribuite_nei_15_secondi(monitor):
    titoli = [{'isin': f'I{i}'} for i in range(4)]
    monitor.borsa = BorsaFinta({f'I{i}': 1.0 for i in range(4)})
    letture = monitor.leggi_prezzi(titoli, durata=12)
    assert [p for p, _ in letture] == [1.0] * 4
    assert monitor.pause == [3, 3, 3]          # una richiesta ogni 3 secondi, nessuna raffica


class BorsaCheLimita:
    """Alla seconda richiesta risponde come Borsa Italiana con un 429."""

    def __init__(self):
        self.troppe_richieste = False
        self.non_risponde = False
        self.richieste = 0

    def get_price(self, isin):
        self.richieste += 1
        if self.richieste == 2:
            self.troppe_richieste = True
            return None, None
        return 20.3, None


def test_dopo_un_429_giro_interrotto_e_pausa(monitor):
    terzo = {**RIGHE_WATCHLIST[0], 'isin': 'IT0000000003', 'nome': 'Terzo'}
    monitor.db = DbFinto(RIGHE_WATCHLIST + [terzo])
    monitor.borsa = BorsaCheLimita()
    monitor.monitora(ignora_orario=True, giri=1)
    assert monitor.borsa.richieste == 2                 # il terzo titolo non è stato chiesto
    assert modulo_app.PAUSA_429 in monitor.pause
    assert [r['isin'] for r in monitor.db.scritture[0]] == ['IT0003132476']


def test_anno_intero_una_volta_per_titolo_anche_se_aggiunto_in_giornata(monitor, monkeypatch):
    chiamate = []

    def riempi_finto(db, yahoo, titolo, passi, adesso, scrivi=True):
        chiamate.append((titolo['isin'], 'completo' if passi is modulo_app.storico.COMPLETO else '7 giorni'))
        return None if titolo['isin'] == 'US0231351067' else 0   # Yahoo senza dati per Amazon

    monkeypatch.setattr(modulo_app.storico, 'riempi_titolo', riempi_finto)
    titoli = monitor.carica_titoli()
    adesso = datetime(2026, 10, 28, 9, tzinfo=modulo_app.ROMA)
    monitor.riempi_buchi(titoli, adesso)
    monitor.riempi_buchi(titoli, adesso)
    # Eni ha l'anno intero una volta sola, Amazon (Yahoo senza dati) finché non riesce
    assert chiamate == [('IT0003132476', 'completo'), ('US0231351067', 'completo'),
                        ('IT0003132476', '7 giorni'), ('US0231351067', 'completo')]

    # Un simbolo_borsa nuovo è un altro titolo per Yahoo: di nuovo l'anno intero
    chiamate.clear()
    monitor.riempi_buchi([{**titoli[0], 'simbolo_borsa': 'ENI.DE'}], adesso)
    assert chiamate == [('IT0003132476', 'completo')]


def test_dopo_una_risposta_lenta_niente_raffica(monitor):
    class BorsaLenta(BorsaFinta):
        def get_price(self, isin):
            if isin == 'I0':
                modulo_app.time.sleep(10)        # timeout: 10 secondi per il primo titolo
            return super().get_price(isin)

    titoli = [{'isin': f'I{i}'} for i in range(4)]
    monitor.borsa = BorsaLenta({f'I{i}': 1.0 for i in range(4)})
    monitor.leggi_prezzi(titoli, durata=12)
    # Dopo i 10 secondi il secondo parte subito, gli altri a mezzo passo (1,5 s): il ritardo
    # si recupera senza raffiche
    assert monitor.pause == [10, 1.5, 1.5]


def test_sospeso_piu_vecchio_del_database_non_vince_anche_con_fusi_diversi(monitor):
    # Supabase: 10:00 UTC (11:00 a Roma); in sospeso: 10:30 a Roma, più vecchio
    monitor.db = DbFinto([{**RIGHE_WATCHLIST[0],
                           'ultimo': [{'ts': '2026-10-28T10:00:00+00:00', 'prezzo': 20.0}]}])
    stato.scrivi('prezzi_in_sospeso.json', [
        {'isin': 'IT0003132476', 'ts': '2026-10-28T10:30:00+01:00', 'prezzo': 19.0, 'fonte': 'borsa'}])
    assert monitor.carica_titoli()[0]['ultimo_prezzo'] == 20.0


@pytest.mark.parametrize('status, tenuti', [(401, True), (503, True), (None, True), (400, False)])
def test_prezzi_tenuti_se_la_chiave_e_sbagliata_buttati_se_rifiutati(monitor, status, tenuti):
    monitor.carica_titoli()

    def rifiuta(righe):
        raise ErroreDatabase('Supabase POST prezzi', status)

    monitor.db.scrivi_prezzi = rifiuta
    monitor.borsa = BorsaFinta({'IT0003132476': 20.3})
    monitor.controlla_tutti()
    assert bool(stato.leggi('prezzi_in_sospeso.json')) == tenuti


def test_telegram_aspetta_retry_after_e_riprova(config, monkeypatch):
    istanza = ISINMonitor(config)
    risposte = [{'ok': False, 'error_code': 429, 'description': 'Too Many Requests: retry after 3',
                 'parameters': {'retry_after': 3}}, {'ok': True}]
    pause = []

    class Risposta:
        def __init__(self, dati):
            self.dati = dati

        def json(self):
            return self.dati

    monkeypatch.setattr(modulo_app.requests, 'post', lambda *a, **k: Risposta(risposte.pop(0)))
    monkeypatch.setattr(modulo_app.time, 'sleep', pause.append)
    assert istanza.send_telegram_message('ciao')
    assert pause == [3] and risposte == []


@pytest.mark.parametrize('ultimo, completo', [('2026-10-22', False), ('2026-10-20', True)])
def test_dopo_le_vacanze_riempimento_completo(monitor, monkeypatch, ultimo, completo):
    class Giorno(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 28, 9, 0, tzinfo=tz)

    chiamate = []
    monkeypatch.setattr(modulo_app, 'datetime', Giorno)
    monkeypatch.setattr(monitor, 'riempi_buchi', lambda titoli, adesso, completo=False: chiamate.append(completo))
    monkeypatch.setattr(monitor, 'controlla_proposte', lambda: None)
    stato.scrivi('mattino.json', {'giorno': ultimo})
    monitor.borsa = BorsaFinta({})
    monitor.controlla_tutti()
    assert chiamate == [completo]


def test_salto_enorme_salvato_solo_se_confermato(monitor):
    # Eni da 20 a 2,03: un prezzo letto male non entra nello storico...
    monitor.borsa = BorsaFinta({'IT0003132476': 2.03})
    monitor.controlla_tutti()
    assert monitor.db.scritture == [] and monitor.telegram_inviati == []
    monitor.borsa = BorsaFinta({'IT0003132476': 20.05})
    monitor.controlla_tutti()
    assert [r['prezzo'] for r in monitor.db.scritture[0]] == [20.05]

    # ...un salto vero (frazionamento) sì, al giro dopo, anche se il prezzo si è mosso un po'
    monitor.borsa = BorsaFinta({'IT0003132476': 10.0})
    monitor.controlla_tutti()
    assert len(monitor.db.scritture) == 1
    monitor.borsa = BorsaFinta({'IT0003132476': 10.1})
    monitor.controlla_tutti()
    assert [r['prezzo'] for r in monitor.db.scritture[1]] == [10.1]
    assert len(monitor.telegram_inviati) == 1


def test_supabase_irraggiungibile_un_timeout_solo_per_giro(monitor):
    monitor.carica_titoli()
    monitor.db.rotto = True
    tentativi = []
    scrivi = monitor.db.scrivi_prezzi
    monitor.db.scrivi_prezzi = lambda righe: (tentativi.append(righe), scrivi(righe))
    monitor.borsa = BorsaFinta({'IT0003132476': 20.3})
    monitor.controlla_tutti()
    # La lista non è arrivata per rete: la scrittura non si prova, i prezzi aspettano
    assert tentativi == []
    assert [r['prezzo'] for r in stato.leggi('prezzi_in_sospeso.json')] == [20.3]


def test_didascalia_senza_tabella_niente_code_vuoto():
    from core.message_templates import CaptionTemplates
    testo = CaptionTemplates.format_caption({'isin': 'X', 'nome': 'A & B'}, 1.5, [])
    assert testo.startswith('<b>A &amp; B</b> €1.5\n') and '<code>' not in testo


def test_borsa_che_non_risponde_giro_interrotto_dopo_due_titoli(monitor, capsys):
    class BorsaGiu(BorsaFinta):
        def get_price(self, isin):
            self.richieste = getattr(self, 'richieste', 0) + 1
            self.non_risponde = True
            return None, None

    titoli = [{'isin': f'I{i}'} for i in range(5)]
    monitor.borsa = BorsaGiu({})
    letture = monitor.leggi_prezzi(titoli, durata=10)
    # I primi due senza risposta, gli altri tre nemmeno chiesti
    assert monitor.borsa.richieste == 2 and [p for p, _ in letture] == [None] * 5
    assert 'non risponde' in capsys.readouterr().out


def test_supabase_giu_poche_righe_nel_log(monitor, capsys):
    uscite = []
    monitor.carica_titoli()
    monitor.db.rotto = True
    monitor.borsa = BorsaFinta({'IT0003132476': 20.3})
    for _ in range(3):                       # tre giri di fila, 15 secondi l'uno
        monitor.controlla_tutti()
        uscite.append(capsys.readouterr().out)
    assert "Uso l'ultima lista" in uscite[0] and 'in sospeso' in uscite[0]
    assert "Uso l'ultima lista" not in uscite[1] + uscite[2]
    assert 'in sospeso' not in uscite[1] + uscite[2]
    modulo_app.time.sleep(modulo_app.LOG_OFFLINE)    # dopo 5 minuti di nuovo
    monitor.controlla_tutti()
    assert "Uso l'ultima lista" in capsys.readouterr().out
    monitor.db.rotto = False
    monitor.controlla_tutti()
    assert 'Supabase di nuovo raggiungibile' in capsys.readouterr().out


def test_didascalia_variazione_in_testa_solo_con_il_prezzo_precedente():
    from core.message_templates import CaptionTemplates
    from core.utils import TableDataGenerator
    con = TableDataGenerator.generate_table_data(19.9, previous_price=20.0)
    senza = TableDataGenerator.generate_table_data(19.9, opening_price=20.0)
    assert CaptionTemplates.format_caption({'isin': 'X', 'nome': 'Eni'}, 19.9, con).startswith(
        '<b>Eni</b> €19.9 📉 -0.50%\n')
    assert CaptionTemplates.format_caption({'isin': 'X', 'nome': 'Eni'}, 19.9, senza).startswith(
        '<b>Eni</b> €19.9\n')


def test_giro_lento_dice_chi_lo_ha_rallentato(monitor, capsys):
    class BorsaLenta(BorsaFinta):
        def get_price(self, isin):
            if isin == 'US0231351067':
                modulo_app.time.sleep(14)        # una risposta lentissima
            return super().get_price(isin)

    monitor.borsa = BorsaLenta({'IT0003132476': 20.0, 'US0231351067': 220.0})
    monitor.controlla_tutti()
    riga = next(r for r in capsys.readouterr().out.splitlines() if r.startswith('🔍'))
    assert '(più lenta US0231351067 14.0 s), Supabase 0.0 s)' in riga


def test_timeout_di_borsa_separato_da_quello_di_supabase(config):
    assert ISINMonitor(config).borsa.timeout == 5
    assert ISINMonitor({**config, 'api': {'request_timeout': 20, 'borsa_timeout': 3}}).borsa.timeout == 3


def test_mai_due_richieste_a_meno_di_mezzo_passo(monitor):
    import random
    casuale = random.Random(7)
    partenze = []

    class BorsaAltalenante(BorsaFinta):
        def get_price(self, isin):
            partenze.append(modulo_app.time.monotonic())
            modulo_app.time.sleep(casuale.choice([0.2, 0.2, 0.2, 3.0]))   # ogni tanto lenta
            return 1.0, None

    titoli = [{'isin': f'I{i}'} for i in range(18)]
    monitor.borsa = BorsaAltalenante({})
    for _ in range(20):
        partenze.clear()
        monitor.leggi_prezzi(titoli, durata=12)
        distanze = [b - a for a, b in zip(partenze, partenze[1:])]
        assert min(distanze) >= 12 / 18 / 2 - 1e-9


def test_avvisi_troppo_vecchi_non_si_mandano(monitor, capsys):
    import queue
    from datetime import timedelta
    coda = queue.Queue()
    titolo = monitor.carica_titoli()[0]
    adesso = datetime.now(modulo_app.ROMA)
    coda.put({'titolo': titolo, 'prezzo': 20.2, 'precedente': 20.0,
              'adesso': adesso - timedelta(hours=2)})
    coda.put({'titolo': titolo, 'prezzo': 20.4, 'precedente': 20.2, 'adesso': adesso})
    import threading
    threading.Thread(target=monitor._spedisci_avvisi, args=(coda,), daemon=True).start()
    coda.join()
    assert len(monitor.telegram_inviati) == 1           # solo quello recente
    assert 'non mandato: troppo vecchio' in capsys.readouterr().out


def test_risposta_non_json_usa_la_lista_salvata(monitor):
    monitor.carica_titoli()

    def non_json():
        raise ValueError('Expecting value: line 1 column 1 (char 0)')

    monitor.db.titoli = non_json
    titoli = monitor.carica_titoli()
    assert not monitor.online and [t['isin'] for t in titoli] == ['IT0003132476', 'US0231351067']


def test_errore_nello_storico_non_ferma_le_proposte(monitor, monkeypatch):
    def rotto(*args, **kwargs):
        raise ValueError('risposta non JSON')

    proposte = []
    monkeypatch.setattr(monitor, 'riempi_buchi', rotto)
    monkeypatch.setattr(monitor, 'controlla_proposte', lambda: proposte.append(1))
    monitor.lavori_del_mattino([])
    assert proposte == [1]


def test_errore_nel_giro_dice_tipo_e_riga(monitor, monkeypatch, capsys):
    def rotto():
        return {}['isin']

    monkeypatch.setattr(monitor, 'giro', rotto)
    monitor.monitora(ignora_orario=True, giri=1)
    assert "ERRORE: Errore nel giro: KeyError: 'isin' (test_monitor.py:" in capsys.readouterr().out


def test_didascalia_col_segnale_di_myfinance_e_i_link_in_fondo():
    from core.message_templates import CaptionTemplates
    from core.utils import TableDataGenerator
    tabella = TableDataGenerator.generate_table_data(5.953, previous_price=5.92)
    testo = CaptionTemplates.format_caption(
        {'isin': 'IT0000072618', 'nome': 'Intesa', 'segnale': 'compra', 'punteggio': 72},
        5.953, tabella, 'https://esempio/?isin=IT0000072618')
    righe = testo.split('\n')
    assert righe[0] == '<b>Intesa</b> €5.953 📈 +0.56%'
    assert righe[1] == '🟢 MyFinance: Compra · 72/100'
    assert '<code>Prima €5.920 +0.56%</code>' in testo     # 3 decimali sotto i 10 €
    assert righe[-1].startswith('<a href="https://finecobank.com') and righe[-1].endswith('MyFinance</a>')


def test_messaggio_di_prova(monitor):
    monitor.test_telegram()
    metodo, dati = monitor.telegram_inviati[0]
    assert dati['text'].split('\n') == [
        '🧪 <b>ISIN Monitor</b>: Telegram funziona',
        'Titoli seguiti: 2 · orario lun-ven 08:55-18:05',
        'Comandi del bot (a monitor acceso): /prezzi /grafico /stato /aiuto',
    ]


def test_riepilogo_della_giornata(monitor):
    monitor.carica_titoli()
    monitor.manda_riepilogo()
    metodo, dati = monitor.telegram_inviati[0]
    assert dati['text'].startswith('📊 <b>Chiusura di oggi, ')
    # Eni 20 € (ieri 20 €: il DbFinto dà la stessa chiusura), Amazon senza prezzo: fuori
    assert '<code>Eni €20.00  +0.00% ⚪</code>' in dati['text']
    assert dati['disable_web_page_preview']


def test_grafico_a_richiesta_variazione_da_ieri_in_testa():
    from core.message_templates import CaptionTemplates
    from core.utils import TableDataGenerator
    tabella = TableDataGenerator.generate_table_data(20.2, historical_prices={1: 20.0, 7: 19.0})
    testo = CaptionTemplates.format_caption({'isin': 'X', 'nome': 'Eni'}, 20.2, tabella)
    assert testo.startswith('<b>Eni</b> €20.2 📈 +1.00% da ieri\n')


def test_cooldown_di_tre_minuti_per_titolo(monitor):
    from datetime import timedelta
    assert monitor.cooldown == timedelta(minutes=3)            # predefinito senza cooldown_minuti
    eni, amazon = [dict(t) for t in monitor.carica_titoli()]
    amazon['ultimo_prezzo'] = 200.0
    alle = datetime(2026, 11, 4, 10, 0, tzinfo=modulo_app.ROMA)

    assert monitor.esamina(eni, 20.2, alle)[1]                              # primo avviso
    riga, avviso = monitor.esamina(eni, 20.4, alle + timedelta(minutes=2))
    assert avviso is None and riga['prezzo'] == 20.4                      # saltato, ma salvato
    assert monitor.esamina(amazon, 202.0, alle + timedelta(minutes=2))[1]   # altro titolo: sì
    assert monitor.esamina(eni, 20.6, alle + timedelta(minutes=3))[1]       # dopo 3 minuti: sì
    # Il test di ./setup.sh test (soglia data a mano) non conta e non è bloccato
    assert monitor.esamina(eni, 20.6, alle + timedelta(minutes=3, seconds=15), soglia=0)[1]


def test_cooldown_da_config(config):
    from datetime import timedelta
    config['monitoring']['cooldown_minuti'] = 0
    assert ISINMonitor(config).cooldown == timedelta(0)


def test_errore_di_telegram_ricordato_senza_token(config, monkeypatch, capsys):
    config['telegram']['bot_token'] = '123:SEGRETO'
    istanza = ISINMonitor(config)

    class Risposta:
        def json(self):
            return {'ok': False, 'error_code': 409,
                    'description': "Conflict: can't use getUpdates method while webhook is active"}

    monkeypatch.setattr(modulo_app.requests, 'post', lambda *a, **k: Risposta())
    assert istanza.chiama_telegram('getUpdates', silenzioso=True, data={}) is None
    assert istanza.errore_telegram == "Conflict: can't use getUpdates method while webhook is active (409)"
    assert capsys.readouterr().out == ''                      # silenzioso: lo scrive ascolta
    assert 'SEGRETO' not in istanza.errore_telegram


def test_stato_del_bot_con_webhook(monitor, monkeypatch, capsys):
    chiamate = []
    risposte = {'getMe': {'username': 'ISINMonitorBot', 'first_name': 'ISIN Monitor'},
                'getWebhookInfo': {'url': 'https://altro.example.com/hook/segreto', 'pending_update_count': 3},
                'deleteWebhook': True}

    def chiama(metodo, **kwargs):
        chiamate.append(metodo)
        return risposte[metodo]

    monkeypatch.setattr(monitor, 'chiama_telegram', chiama)
    monitor.stato_telegram()
    uscita = capsys.readouterr().out
    assert '@ISINMonitorBot' in uscita and 'Webhook attivo verso altro.example.com' in uscita
    assert 'segreto' not in uscita and 'Messaggi in attesa: 3' in uscita
    assert 'deleteWebhook' not in chiamate                   # di suo non toglie niente
    monitor.stato_telegram(togli_webhook=True)
    assert chiamate[-2:] == ['deleteWebhook', 'getWebhookInfo']


def test_foto_riprovata_se_la_connessione_non_parte(config, monkeypatch, capsys):
    istanza = ISINMonitor(config)
    tentativi, pause = [], []

    class Risposta:
        def json(self):
            return {'ok': True, 'result': {'message_id': 1}}

    def post(*args, **kwargs):
        tentativi.append(kwargs.get('files'))
        if len(tentativi) < 3:
            raise modulo_app.requests.ConnectionError('rete giù')
        return Risposta()

    monkeypatch.setattr(modulo_app.requests, 'post', post)
    monkeypatch.setattr(modulo_app.time, 'sleep', pause.append)
    assert istanza.send_telegram_photo(b'png', 'didascalia')
    assert len(tentativi) == 3 and pause == [3, 10] and tentativi[2]['photo'][1] == b'png'
    assert capsys.readouterr().out.count('riprovo fra') == 2


def test_read_timeout_non_si_riprova(config, monkeypatch):
    istanza = ISINMonitor(config)
    tentativi = []

    def post(*args, **kwargs):
        tentativi.append(1)
        raise modulo_app.requests.ReadTimeout('lento')

    monkeypatch.setattr(modulo_app.requests, 'post', post)
    monkeypatch.setattr(modulo_app.time, 'sleep', lambda s: None)
    assert not istanza.send_telegram_photo(b'png', 'didascalia')
    assert tentativi == [1]          # la foto potrebbe essere già arrivata: niente doppioni


def test_righe_della_tabella_corte_anche_sotto_la_foto(monitor):
    # Sotto un grafico verticale il fumetto è stretto: nessuna riga oltre i 26 caratteri
    monitor.db.registro['IT0003132476'] = [
        {'posizione': 3, 'data': '2026-01-10', 'operazione': 'Investimento', 'importo': '-1800',
         'quantita': '100', 'abp': None}]
    monitor.borsa = BorsaFinta({'IT0003132476': 20.2})
    monitor.config['telegram']['send_charts'] = False
    monitor.controlla_tutti()
    tabella = monitor.telegram_inviati[0][1]['text'].split('<code>')[1].split('</code>')[0]
    assert max(len(riga) for riga in tabella.split('\n')) <= 26


class TelegramConFoto:
    """sendPhoto con un message_id crescente; deleteMessage che riesce o fallisce."""

    def __init__(self, monitor, cancella_ok=True, foto_ok=True):
        self.monitor, self.cancella_ok, self.foto_ok = monitor, cancella_ok, foto_ok
        self.prossimo, self.cancellati, self.mandati = 100, [], []

    def telegram(self, metodo, **kwargs):
        self.mandati.append(metodo)
        if metodo == 'sendPhoto':
            if not self.foto_ok:
                return None
            self.prossimo += 1
            return {'message_id': self.prossimo}
        return {'message_id': 1}

    def chiama(self, metodo, **kwargs):
        assert metodo == 'deleteMessage' and kwargs['data']['chat_id'] == '1'
        if self.cancella_ok:
            self.cancellati.append(kwargs['data']['message_id'])
            return True
        self.monitor.errore_telegram = 'Bad Request: message can\'t be deleted (400)'
        return None


def manda_grafico(monitor, prezzo):
    titolo = monitor.carica_titoli()[0]
    monitor.invia_avviso(titolo, prezzo, 20.0, datetime.now(modulo_app.ROMA))


def test_nel_canale_resta_solo_l_ultimo_grafico(monitor):
    finto = TelegramConFoto(monitor)
    monitor._telegram, monitor.chiama_telegram = finto.telegram, finto.chiama
    manda_grafico(monitor, 20.2)                       # primo grafico: niente da cancellare
    assert finto.cancellati == [] and stato.leggi('grafici.json') == {'IT0003132476': 101}
    manda_grafico(monitor, 20.4)                       # il secondo cancella il primo
    assert finto.cancellati == [101] and stato.leggi('grafici.json') == {'IT0003132476': 102}

    # Dopo un riavvio il message_id è ancora nel file di stato
    nuovo = ISINMonitor(monitor.config)
    nuovo.db, nuovo.borsa = monitor.db, monitor.borsa
    nuovo._telegram, nuovo.chiama_telegram = finto.telegram, finto.chiama
    manda_grafico(nuovo, 20.6)
    assert finto.cancellati == [101, 102]


def test_se_la_foto_non_parte_il_vecchio_grafico_resta(monitor):
    stato.scrivi('grafici.json', {'IT0003132476': 55})
    finto = TelegramConFoto(monitor, foto_ok=False)
    monitor._telegram, monitor.chiama_telegram = finto.telegram, finto.chiama
    manda_grafico(monitor, 20.2)
    assert finto.mandati == ['sendPhoto', 'sendMessage'] and finto.cancellati == []
    assert stato.leggi('grafici.json') == {'IT0003132476': 55}


def test_cancellazione_fallita_scritta_una_volta(monitor, capsys):
    finto = TelegramConFoto(monitor, cancella_ok=False)
    monitor._telegram, monitor.chiama_telegram = finto.telegram, finto.chiama
    for prezzo in (20.2, 20.4, 20.6):
        manda_grafico(monitor, prezzo)
    uscita = capsys.readouterr().out
    assert uscita.count('non cancellato') == 1 and "message can't be deleted" in uscita
    assert stato.leggi('grafici.json') == {'IT0003132476': 103}   # si va avanti col nuovo


def test_cancellazione_spenta_da_config(monitor):
    monitor.config['telegram']['cancella_grafico_precedente'] = False
    finto = TelegramConFoto(monitor)
    monitor._telegram, monitor.chiama_telegram = finto.telegram, finto.chiama
    manda_grafico(monitor, 20.2)
    manda_grafico(monitor, 20.4)
    assert finto.cancellati == []
