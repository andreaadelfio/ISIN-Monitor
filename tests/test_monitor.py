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
