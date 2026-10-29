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
    assert titoli[1]['ultimo_prezzo'] is None and titoli[1]['senza_storico']
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
