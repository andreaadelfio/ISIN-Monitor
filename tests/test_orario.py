from datetime import datetime

from core.orario import calendario_timer, in_orario

ORARIO = {'market_hours_only': True, 'weekdays_only': True,
          'market_open_time': '08:55', 'market_close_time': '18:05'}


def test_dentro_e_fuori_orario():
    martedi = datetime(2026, 10, 27)
    assert in_orario(ORARIO, martedi.replace(hour=8, minute=55))
    assert in_orario(ORARIO, martedi.replace(hour=12))
    assert in_orario(ORARIO, martedi.replace(hour=18, minute=5))
    assert not in_orario(ORARIO, martedi.replace(hour=8, minute=54, second=59))
    assert not in_orario(ORARIO, martedi.replace(hour=18, minute=5, second=1))
    assert not in_orario(ORARIO, martedi.replace(hour=22))


def test_weekend_e_sempre_attivo():
    sabato = datetime(2026, 10, 31, 12)
    assert not in_orario(ORARIO, sabato)
    assert in_orario({**ORARIO, 'weekdays_only': False}, sabato)
    assert in_orario({'market_hours_only': False}, datetime(2026, 11, 1, 3))


def test_calendario_timer():
    assert calendario_timer(ORARIO) == [
        'Mon..Fri 08:55..59:00/15',
        'Mon..Fri 09..17:*:00/15',
        'Mon..Fri 18:00..05:00/15',
    ]
    assert calendario_timer({**ORARIO, 'market_open_time': '09:00', 'market_close_time': '10:30'}) == [
        'Mon..Fri 09:*:00/15', 'Mon..Fri 10:00..30:00/15',
    ]
    assert calendario_timer({**ORARIO, 'market_open_time': '09:00', 'market_close_time': '09:30',
                              'weekdays_only': False}) == ['*-*-* 09:00..30:00/15']
    assert calendario_timer({'market_hours_only': False}) == ['*:*:00/15']
