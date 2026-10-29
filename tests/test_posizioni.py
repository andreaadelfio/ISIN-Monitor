"""Prezzo di carico e operazioni dal registro investimenti di MyFinance."""

from datetime import date

import pytest

from core.posizioni import acquisti_e_vendite, carico

OGGI = date(2026, 10, 29)


def riga(posizione, data, operazione, importo, quantita=None, abp=None):
    return {'posizione': posizione, 'data': data, 'operazione': operazione,
            'importo': importo, 'quantita': quantita, 'abp': abp}


def test_carico_dall_abp_del_conto():
    # Due acquisti, l'ABP è quello dell'operazione più recente che ce l'ha
    operazioni = [riga(6, '2025-09-03', 'Investimento', '-100', '20', '5.2'),
                  riga(6, '2025-11-24', 'Dividendi', '4.5', '20'),
                  riga(6, '2026-03-02', 'Investimento', '-60', '10', '5.5145')]
    assert carico(operazioni, OGGI) == {'quote': 30, 'prezzo': pytest.approx(5.5145)}


def test_senza_abp_costo_diviso_quote_e_senza_quantita_quote_dall_abp():
    assert carico([riga(1, '2026-01-10', 'Investimento', -180, 10)], OGGI) == {
        'quote': 10, 'prezzo': 18}
    assert carico([riga(1, '2026-01-10', 'Investimento', -180, None, 20)], OGGI) == {
        'quote': 9, 'prezzo': 20}
    # Né quantità né ABP: le quote non si possono sapere
    assert carico([riga(1, '2026-01-10', 'Investimento', -180)], OGGI) is None


def test_posizioni_vendute_escluse_e_piu_posizioni_aperte_insieme():
    operazioni = [riga(4, '2025-01-29', 'Investimento', -1000, 10),
                  riga(4, '2025-07-01', 'Rimborso', 1300, 10),       # venduta
                  riga(5, '2025-09-02', 'Investimento', -150, 10),
                  riga(7, '2026-02-01', 'Investimento', -250, 10),
                  riga(7, '2026-11-02', 'Rimborso', 300, 10)]        # vendita futura: ancora aperta
    assert carico(operazioni, OGGI) == {'quote': 20, 'prezzo': 20}
    assert carico(operazioni[:2], OGGI) is None


def test_acquisti_e_vendite_col_prezzo():
    # Vendita = Rimborso del capitale + Cedola col guadagno, lo stesso giorno
    operazioni = [riga(4, '2025-01-29', 'Investimento', '-1000', '8'),
                  riga(4, '2025-04-03', 'Dividendi', '2'),
                  riga(4, '2025-07-01', 'Cedola', '300', '8'),
                  riga(4, '2025-07-01', 'Rimborso', '1000', '8'),
                  riga(5, '2025-09-02', 'Investimento', '-150'),
                  riga(6, '2025-10-01', 'Investimento', '-200', '10'),
                  riga(6, '2025-12-01', 'Rimborso', '200', '10'),
                  riga(6, '2025-12-01', 'Cedola', '-20', '10')]    # venduta in perdita
    assert acquisti_e_vendite(operazioni) == [
        {'data': date(2025, 1, 29), 'acquisto': True, 'prezzo': 125},
        {'data': date(2025, 7, 1), 'acquisto': False, 'prezzo': 162.5},
        {'data': date(2025, 9, 2), 'acquisto': True, 'prezzo': None},   # va sulla curva
        {'data': date(2025, 10, 1), 'acquisto': True, 'prezzo': 20},
        {'data': date(2025, 12, 1), 'acquisto': False, 'prezzo': 18},
    ]
