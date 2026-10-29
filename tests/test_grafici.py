from datetime import datetime, time

import pandas as pd

from core.app import chiusure_storiche
import matplotlib.pyplot as plt

from core.chart_generator import (COLORI_PERIODI, SEDUTA, ChartGenerator, asse_sedute, colore_di,
                                  dati_oggi, dati_pannello, in_orario, periodi, tabella_prezzi)

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
    assert x[0] == 0 and abs(x[1] - SEDUTA) < 1e-9       # venerdì: tutta la seduta
    assert 1 < x[2] < 1 + SEDUTA and x[3] == 2 + SEDUTA   # lunedì a metà, martedì oltre la chiusura
    assert etichette == ['23/10', '26/10', '27/10'] and tick == [i + SEDUTA / 2 for i in range(3)]


def test_asse_sedute_dirada_le_etichette():
    ts = pd.Series(pd.date_range('2026-09-01 10:00', periods=22, freq='D'))
    _, _, etichette = asse_sedute(ts, time(8, 55), time(18, 5))
    assert len(etichette) <= 7 and etichette[-1] == '22/09'


def test_fuori_orario_esclusi_dalle_sedute():
    dati = tabella(('2026-10-23 01:00', 1), ('2026-10-23 08:55', 2), ('2026-10-23 17:36', 3),
                   ('2026-10-23 18:05', 4), ('2026-10-27 20:32', 5))
    assert list(in_orario(dati, time(8, 55), time(18, 5))['prezzo']) == [2, 3, 4]


BLU, ACQUA, ARANCIO, VIOLA = COLORI_PERIODI


def linee(asse):
    """(colore, prezzi) delle linee disegnate, senza la linea del prezzo attuale (l'ultima)."""
    return [(linea.get_color(), list(linea.get_ydata())) for linea in asse.get_lines()][:-1]


def test_colori_dei_periodi():
    elenco = periodi([7, 30, 360], ADESSO)
    assert [giorni for giorni, _, _ in elenco] == [360, 30, 7, 0]
    assert colore_di(pd.Timestamp('2026-09-01 10:00'), elenco) == BLU      # oltre 30 giorni
    assert colore_di(pd.Timestamp('2026-09-27 00:00'), elenco) == ACQUA    # 30 giorni: dal 27/09
    assert colore_di(pd.Timestamp('2026-10-20 00:00'), elenco) == ARANCIO  # 7 giorni: dal 20/10
    assert colore_di(pd.Timestamp('2026-10-27 09:00'), elenco) == VIOLA    # oggi


def test_una_linea_per_seduta_col_colore_del_periodo():
    dati = tabella(('2026-10-16 10:00', 0), ('2026-10-23 09:00', 1), ('2026-10-23 17:30', 2),
                   ('2026-10-26 12:00', 3), ('2026-10-27 09:00', 4), ('2026-10-27 15:00', 5))
    fig, asse = plt.subplots()
    ChartGenerator()._plot_sedute(asse, dati, 30, 5.0, periodi([7, 30, 360], ADESSO))
    disegnate = linee(asse)
    plt.close(fig)
    assert disegnate == [(ACQUA, [0]), (ARANCIO, [1, 2]), (ARANCIO, [3]), (VIOLA, [4, 5])]


def test_annuale_un_tratto_per_periodo_attaccato_al_precedente():
    fig, asse = plt.subplots()
    ChartGenerator()._plot_giornaliero(asse, GIORNALIERO, 360, 14.0, periodi([7, 30, 360], ADESSO))
    disegnate = linee(asse)
    plt.close(fig)
    # nessuna chiusura negli ultimi 30 giorni prima del 20/10: niente tratto verde acqua
    assert disegnate == [(BLU, [10, 11]), (ARANCIO, [11, 12, 13]), (VIOLA, [13, 14])]


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
