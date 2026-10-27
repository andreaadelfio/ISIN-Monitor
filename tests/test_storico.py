from datetime import datetime, timedelta, timezone

import pandas as pd

from core import storico
from core.storico import ROMA, inizio_intervallo, punti_mancanti, riempi_titolo, simbolo_yahoo

CINQUE_MINUTI = timedelta(minutes=5)
UN_GIORNO = timedelta(days=1)


def serie(*punti):
    return pd.DataFrame({'ts': pd.to_datetime([t for t, _ in punti], utc=True),
                         'price': [p for _, p in punti]})


def test_intervalli_come_date_bin():
    ts = datetime(2026, 10, 27, 9, 7, 30, tzinfo=ROMA)
    assert inizio_intervallo(ts, CINQUE_MINUTI) == datetime(2026, 10, 27, 9, 5, tzinfo=ROMA)
    # Un giorno: dalla mezzanotte di Roma in ora solare (+01:00), anche d'estate
    estate = datetime(2026, 7, 1, 17, 30, tzinfo=ROMA)
    assert inizio_intervallo(estate, UN_GIORNO) == datetime(2026, 7, 1, tzinfo=timezone(timedelta(hours=1)))


def test_solo_i_buchi_e_mai_oggi():
    oggi = datetime(2026, 10, 27, tzinfo=ROMA)
    dati = serie(
        ('2026-10-26 08:00:00', 10.0),   # 09:00 a Roma: intervallo già coperto
        ('2026-10-26 08:04:00', 10.1),   # stesso intervallo 09:00-09:05
        ('2026-10-26 08:05:00', 10.2),   # 09:05: buco
        ('2026-10-27 08:00:00', 10.3),   # oggi: mai
    )
    occupati = {datetime(2026, 10, 26, 9, 0, tzinfo=ROMA)}
    punti = punti_mancanti(dati, occupati, CINQUE_MINUTI, False, oggi)
    assert punti == [(datetime(2026, 10, 26, 9, 5, tzinfo=ROMA), 10.2)]


def test_chiusure_giornaliere_alle_17_30():
    oggi = datetime(2026, 10, 27, tzinfo=ROMA)
    dati = serie(('2026-10-22 07:00:00', 20.0), ('2026-10-23 07:00:00', 21.0))
    occupati = {inizio_intervallo(datetime(2026, 10, 22, 12, tzinfo=ROMA), UN_GIORNO)}
    punti = punti_mancanti(dati, occupati, UN_GIORNO, True, oggi)
    assert punti == [(datetime(2026, 10, 23, 17, 30, tzinfo=ROMA), 21.0)]


def test_simbolo_yahoo_solo_in_euro():
    assert simbolo_yahoo({'simbolo_borsa': '1AMZN.MI', 'simbolo': 'AMZN'}) == '1AMZN.MI'
    assert simbolo_yahoo({'simbolo': 'AMZN', 'valuta': 'USD'}) == ''
    assert simbolo_yahoo({'simbolo': 'BNP.PA', 'valuta': 'EUR'}) == 'BNP.PA'
    assert simbolo_yahoo({'simbolo': 'ENI.MI'}) == 'ENI.MI'


class DbFinto:
    def __init__(self, occupati):
        self.occupati = occupati
        self.scritte = []
        self.richieste = []

    def serie(self, isin, da, passo):
        self.richieste.append(passo)
        return [{'ts': ts.isoformat(), 'prezzo': 1} for ts in self.occupati.get(passo, [])]

    def scrivi_prezzi(self, righe):
        self.scritte.append(righe)


class YahooFinto:
    def __init__(self, serie_per_intervallo):
        self.serie_per_intervallo = serie_per_intervallo
        self.chiamate = []

    def get_series(self, simbolo, periodo, intervallo):
        self.chiamate.append((simbolo, periodo, intervallo))
        return self.serie_per_intervallo[intervallo]


def test_riempi_titolo_una_chiamata_per_passo_e_niente_doppioni():
    adesso = datetime(2026, 10, 27, 10, tzinfo=ROMA)
    yahoo = YahooFinto({
        '1m': serie(('2026-10-26 09:00:00', 1.0), ('2026-10-26 09:01:00', 1.1)),   # 10:00 a Roma
        '5m': serie(('2026-10-26 09:00:00', 1.0), ('2026-10-26 10:00:00', 1.2)),   # 10:00 già dal passo 1m
        '1d': serie(('2026-10-26 07:00:00', 1.3), ('2026-10-23 07:00:00', 1.4)),
    })
    db = DbFinto({})
    titolo = {'isin': 'IT0000000001', 'simbolo_borsa': 'X.MI'}
    aggiunti = riempi_titolo(db, yahoo, titolo, storico.COMPLETO, adesso)
    assert [c[2] for c in yahoo.chiamate] == ['1m', '5m', '1d']
    righe = [r for scrittura in db.scritte for r in scrittura]
    assert all(r['fonte'] == 'yahoo' and r['isin'] == 'IT0000000001' for r in righe)
    # 2 al minuto, 1 ai 5 minuti (11:00), 1 chiusura (il 26 è già coperto dai punti al minuto)
    assert aggiunti == len(righe) == 4
    assert righe[-1]['ts'] == '2026-10-23T17:30:00+02:00'


def test_riempi_titolo_in_prova_non_scrive():
    adesso = datetime(2026, 10, 27, 10, tzinfo=ROMA)
    yahoo = YahooFinto({'1m': serie(('2026-10-26 09:00:00', 1.0))})
    db = DbFinto({})
    assert riempi_titolo(db, yahoo, {'isin': 'I', 'simbolo_borsa': 'X.MI'}, storico.GIORNALIERO,
                         adesso, scrivi=False) == 1
    assert db.scritte == []


def test_mattino_ai_5_minuti_solo_senza_dato_al_minuto():
    adesso = datetime(2026, 10, 27, 10, tzinfo=ROMA)
    vuota = serie()
    yahoo = YahooFinto({'1m': vuota, '5m': serie(('2026-10-26 09:00:00', 1.0))})
    db = DbFinto({})
    assert riempi_titolo(db, yahoo, {'isin': 'I', 'simbolo_borsa': '1AMD.MI'}, storico.GIORNALIERO, adesso) == 1
    assert [c[2] for c in yahoo.chiamate] == ['1m', '5m']

    yahoo = YahooFinto({'1m': serie(('2026-10-26 09:00:00', 1.0))})
    riempi_titolo(DbFinto({}), yahoo, {'isin': 'I', 'simbolo_borsa': 'ENI.MI'}, storico.GIORNALIERO, adesso)
    assert [c[2] for c in yahoo.chiamate] == ['1m']
