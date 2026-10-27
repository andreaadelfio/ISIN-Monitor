from datetime import datetime, time

import pandas as pd

from core.app import chiusure_storiche
from core.chart_generator import (ChartGenerator, asse_sedute, dati_oggi, dati_pannello,
                                  tabella_prezzi)

ADESSO = datetime(2026, 10, 27, 15, 0)


def tabella(*punti):
    return pd.DataFrame({'ts': pd.to_datetime([t for t, _ in punti]),
                         'prezzo': [float(p) for _, p in punti]})


RECENTE = tabella(('2026-09-25 10:00', 1), ('2026-10-19 10:00', 2), ('2026-10-20 17:30', 3),
                  ('2026-10-27 09:15', 4))
GIORNALIERO = tabella(('2025-10-20 00:00', 10), ('2025-11-03 00:00', 11), ('2026-10-20 00:00', 12),
                      ('2026-10-26 00:00', 13), ('2026-10-27 00:00', 14))


def test_tabella_prezzi_in_ora_di_roma():
    dati = tabella_prezzi([{'ts': '2026-10-27T08:00:00+00:00', 'prezzo': 1.5},
                           {'ts': '2026-07-01T07:00:00+00:00', 'prezzo': '2'}])
    assert list(dati['ts']) == [pd.Timestamp('2026-07-01 09:00'), pd.Timestamp('2026-10-27 09:00')]
    assert list(dati['prezzo']) == [2.0, 1.5]
    assert tabella_prezzi([]).empty


def test_pannelli_brevi_dai_dati_ogni_15_minuti():
    sette = dati_pannello(7, RECENTE, GIORNALIERO, ADESSO)
    assert list(sette['prezzo']) == [3, 4]   # dal 20/10 compreso
    trenta = dati_pannello(30, RECENTE, GIORNALIERO, ADESSO)
    assert list(trenta['prezzo']) == [2, 3, 4]   # dal 27/09: il 25/09 resta fuori


def test_pannello_annuale_una_chiusura_al_giorno():
    anno = dati_pannello(360, RECENTE, GIORNALIERO, ADESSO)
    assert list(anno['prezzo']) == [11, 12, 13, 14]   # niente dettaglio dell'ultimo mese


def test_oggi_solo_i_punti_di_oggi():
    oggi = tabella(('2026-10-26 17:30', 1), ('2026-10-27 09:00', 2), ('2026-10-27 09:01', 3))
    assert list(dati_oggi(oggi, ADESSO)['prezzo']) == [2, 3]


def test_asse_sedute_senza_notti_e_weekend():
    ts = pd.Series(pd.to_datetime(['2026-10-23 08:55', '2026-10-23 18:05', '2026-10-26 13:30',
                                   '2026-10-27 20:00']))
    x, tick, etichette = asse_sedute(ts, time(8, 55), time(18, 5))
    assert x[0] == 0 and abs(x[1] - 0.9) < 1e-9          # venerdì: tutta la seduta
    assert 1 < x[2] < 1.9 and x[3] == 2.9                 # lunedì a metà, martedì oltre la chiusura
    assert etichette == ['23/10', '26/10', '27/10'] and tick == [0.45, 1.45, 2.45]


def test_asse_sedute_dirada_le_etichette():
    ts = pd.Series(pd.date_range('2026-09-01 10:00', periods=22, freq='D'))
    _, _, etichette = asse_sedute(ts, time(8, 55), time(18, 5))
    assert len(etichette) <= 7 and etichette[-1] == '22/09'


def test_chiusure_storiche_per_la_tabella():
    adesso = datetime(2026, 10, 27, 15)
    assert chiusure_storiche(GIORNALIERO, adesso, [1, 7, 30, 360, 1000]) == {
        1: 13.0, 7: 12.0, 30: 11.0, 360: 10.0,   # 360 giorni fa è l'1/11/2025: vale il 20/10
    }


def test_grafico_anche_senza_dati():
    vuoto = tabella_prezzi([])
    png = ChartGenerator([7, 30, 360]).create_comprehensive_chart(
        'Titolo', 10.0, None, [], vuoto, vuoto, vuoto, ADESSO)
    assert png.startswith(b'\x89PNG')
    png = ChartGenerator([7, 30, 360]).create_comprehensive_chart(
        'Titolo', 10.0, 9.5, None, tabella(('2026-10-27 09:00', 9.6)), RECENTE, GIORNALIERO, ADESSO)
    assert png.startswith(b'\x89PNG')
