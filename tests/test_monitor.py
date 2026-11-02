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

    def get_price(self, isin):
        return self.prezzi.get(isin), None


@pytest.fixture
def monitor(config, monkeypatch):
    istanza = ISINMonitor(config)
    istanza.db = DbFinto()
    istanza.telegram_inviati = []

    def telegram_finto(metodo, **kwargs):
        istanza.telegram_inviati.append((metodo, kwargs['data']))
        return True

    monkeypatch.setattr(istanza, '_telegram', telegram_finto)
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
    assert '<a href="https://esempio.pages.dev/?isin=IT0003132476">MyFinance</a>' in dati['caption']
    # La cache ha i prezzi nuovi: il prossimo giro (anche offline) confronta con questi
    assert stato.leggi('titoli.json')[0]['ultimo_prezzo'] == 20.2


def test_avviso_con_la_tua_posizione(monitor):
    monitor.db.registro['IT0003132476'] = [
        {'posizione': 3, 'data': '2026-01-10', 'operazione': 'Investimento', 'importo': '-180',
         'quantita': '10', 'abp': None}]
    monitor.borsa = BorsaFinta({'IT0003132476': 20.2})
    monitor.controlla_tutti()
    metodo, dati = monitor.telegram_inviati[0]
    assert metodo == 'sendPhoto'
    # Carico 18 €: +2.2 € per quota, +22 € su 10 quote
    assert 'Carico: €18 (+12.222% 📈) +2.200 → 10 quote, +22.00€' in dati['caption']
    # Massimo e minimo dell'anno, prezzo attuale compreso (qui è il nuovo massimo)
    assert 'Max: €20.2 (+0.000% ⚪) +0.000' in dati['caption']
    assert 'Min: €19 (+6.316% 📈) +1.200' in dati['caption']


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


class BorsaCrescente:
    """Eni sale dell'1% a ogni lettura: un avviso a ogni giro."""

    def __init__(self):
        self.prezzo = 20.0
        self.troppe_richieste = False

    def get_price(self, isin):
        if isin != 'IT0003132476':
            return None, None
        self.prezzo = round(self.prezzo * 1.01, 4)
        return self.prezzo, None


def test_monitora_avvisi_in_un_thread_che_non_blocca_i_giri(monitor, monkeypatch):
    import threading

    monitor.borsa = BorsaCrescente()
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
    assert threading.main_thread().name not in thread_avvisi


def test_monitora_esce_fuori_orario(monitor, monkeypatch):
    monkeypatch.setattr(modulo_app, 'in_orario', lambda monitoring, adesso: False)
    monitor.borsa = BorsaFinta({})
    monitor.monitora()
    assert monitor.db.scritture == []


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
    # Dopo i 10 secondi gli altri tre restano a 3 secondi l'uno dall'altro
    assert monitor.pause == [10, 3, 3]


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
