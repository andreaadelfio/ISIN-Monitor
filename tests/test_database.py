"""Il client REST di Supabase con una sessione HTTP finta."""

from datetime import datetime, timezone

import pytest

from core import database
from core.database import Database, ErroreDatabase


class Risposta:
    def __init__(self, dati, status=200, intestazioni=None):
        self.dati, self.status_code, self.headers = dati, status, intestazioni or {}
        self.text = str(dati)

    def json(self):
        return self.dati


class SessioneFinta:
    def __init__(self, risposte):
        self.risposte = list(risposte)
        self.richieste = []
        self.headers = {}

    def request(self, metodo, url, **kwargs):
        self.richieste.append((metodo, url, kwargs))
        return self.risposte.pop(0)


def db_con(*risposte):
    db = Database('https://progetto.supabase.co', 'sb_secret_finta')
    sessione = SessioneFinta(risposte)
    sessione.headers = db.session.headers
    db.session = sessione
    return db, sessione


def test_solo_header_apikey():
    db = Database('https://progetto.supabase.co', 'sb_secret_finta')
    assert db.session.headers['apikey'] == 'sb_secret_finta'
    assert 'Authorization' not in db.session.headers


def test_letture_a_pagine():
    pagina = [{'ts': f't{i}', 'prezzo': 1} for i in range(database.RIGHE_PER_PAGINA)]
    db, sessione = db_con(Risposta(pagina), Risposta(pagina[:3]))
    righe = db.serie('IT0000000001', datetime(2026, 10, 1, tzinfo=timezone.utc), '5 minutes')
    assert len(righe) == database.RIGHE_PER_PAGINA + 3
    assert [r[2]['params']['offset'] for r in sessione.richieste] == [0, database.RIGHE_PER_PAGINA]
    assert sessione.richieste[0][1].endswith('/rest/v1/rpc/serie_prezzi')


def test_scrittura_a_blocchi_senza_sovrascrivere(monkeypatch):
    monkeypatch.setattr(database, 'RIGHE_PER_SCRITTURA', 2)
    db, sessione = db_con(Risposta(None, 201), Risposta(None, 201))
    db.scrivi_prezzi([{'isin': 'I', 'ts': str(i), 'prezzo': 1, 'fonte': 'borsa'} for i in range(3)])
    assert len(sessione.richieste) == 2
    metodo, url, kwargs = sessione.richieste[0]
    assert metodo == 'POST' and url.endswith('/prezzi')
    assert kwargs['params'] == {'on_conflict': 'isin,ts'}
    assert 'resolution=ignore-duplicates' in kwargs['headers']['Prefer']


def test_errori_con_status():
    db, _ = db_con(Risposta({'message': 'no'}, 401))
    with pytest.raises(ErroreDatabase) as errore:
        db.titoli()
    assert errore.value.status == 401


def test_chiave_dal_file(tmp_path, monkeypatch):
    monkeypatch.delenv('SUPABASE_SECRET_KEY')
    file = tmp_path / 'supabase.env'
    file.write_text('# commento\nSUPABASE_SECRET_KEY="sb_secret_dal_file"\n')
    monkeypatch.setattr(database, 'FILE_CHIAVE', file)
    assert database.leggi_chiave() == 'sb_secret_dal_file'
    monkeypatch.setattr(database, 'FILE_CHIAVE', tmp_path / 'manca.env')
    assert database.leggi_chiave() is None
