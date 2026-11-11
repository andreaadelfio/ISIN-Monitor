from datetime import date, datetime

import pytest

from core.orario import calendario_timer, festivo, in_orario, pasqua

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


def test_prossimo_giro_ai_multipli_di_15_secondi():
    from core.orario import secondi_al_prossimo_giro
    assert secondi_al_prossimo_giro(datetime(2026, 10, 29, 10, 0, 7)) == 8
    assert secondi_al_prossimo_giro(datetime(2026, 10, 29, 10, 0, 15)) == 15


def test_pasqua_e_chiusure_di_borsa_italiana():
    assert [pasqua(anno) for anno in (2024, 2025, 2026, 2027)] == [
        date(2024, 3, 31), date(2025, 4, 20), date(2026, 4, 5), date(2027, 3, 28)]
    chiusi = [date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 6), date(2026, 5, 1),
              date(2026, 12, 24), date(2026, 12, 25), date(2026, 12, 31), date(2025, 12, 26)]
    assert all(festivo(giorno) for giorno in chiusi)
    assert festivo(date(2026, 4, 3)) == 'Venerdì Santo'
    # Feste italiane con la borsa aperta
    aperti = [date(2026, 1, 6), date(2026, 4, 2), date(2026, 4, 7), date(2026, 6, 2),
              date(2025, 8, 15), date(2026, 12, 8), date(2026, 10, 27)]
    assert not any(festivo(giorno) for giorno in aperti)


def test_monitor_fermo_nei_giorni_di_borsa_chiusa(monkeypatch, capsys, tmp_path):
    import monitor
    venerdi_santo = datetime(2026, 4, 3, 10)
    orari = iter([venerdi_santo, venerdi_santo, datetime(2026, 4, 3, 18, 6)])

    class Orologio(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(orari)

    pause = []
    monkeypatch.setattr(monitor, 'datetime', Orologio)
    monkeypatch.setattr(monitor.time, 'sleep', pause.append)
    monkeypatch.setattr(monitor, 'carica_config', lambda: {'monitoring': ORARIO})
    monkeypatch.setattr('sys.argv', ['monitor.py', '--monitor'])
    monkeypatch.setattr('core.app.ISINMonitor', lambda config: pytest.fail('giri a borsa chiusa'))
    monitor.main()
    # Resta acceso fino alle 18:05 (il timer non lo riavvia) e non arriva mai ai giri
    assert pause == [60]
    assert 'chiusa oggi (Venerdì Santo)' in capsys.readouterr().out


def test_un_monitor_alla_volta(monkeypatch, capsys):
    import monitor
    from core import stato
    gia_acceso = stato.blocca('monitor.lock')
    assert gia_acceso is not None and stato.blocca('monitor.lock') is None
    monkeypatch.setattr(monitor, 'carica_config', lambda: {'monitoring': {'market_hours_only': False}})
    monkeypatch.setattr('sys.argv', ['monitor.py', '--giro'])
    monkeypatch.setattr('core.app.ISINMonitor', lambda config: pytest.fail('secondo monitor'))
    monitor.main()                       # esce prima di caricare il monitor e fare richieste
    assert 'Un altro monitor sta già girando' in capsys.readouterr().out
    gia_acceso.close()
    assert stato.blocca('monitor.lock') is not None


def test_con_test_nel_config_un_avviso_solo_al_giorno(monkeypatch):
    import monitor
    martedi = datetime(2026, 10, 27, 10)
    orari = iter([martedi, martedi, datetime(2026, 10, 27, 18, 6)])

    class Orologio(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(orari)

    class MonitorFinto:
        test = 0

        def __init__(self, config):
            pass

        def run_test(self):
            MonitorFinto.test += 1

    pause = []
    monkeypatch.setattr(monitor, 'datetime', Orologio)
    monkeypatch.setattr(monitor.time, 'sleep', pause.append)
    monkeypatch.setattr(monitor, 'carica_config', lambda: {'monitoring': ORARIO, 'test': True})
    monkeypatch.setattr('core.app.ISINMonitor', MonitorFinto)
    monkeypatch.setattr('sys.argv', ['monitor.py', '--monitor'])
    monitor.main()
    # Dopo il test resta fermo fino alla chiusura: il timer non lo rilancia ogni 15 secondi
    assert MonitorFinto.test == 1 and pause == [60]


def test_stato_locale_in_poche_righe(monkeypatch, capsys):
    import monitor
    from core import stato
    stato.scrivi('prezzi_in_sospeso.json', [{'isin': 'A', 'ts': '2026-11-03T10:00:00+01:00', 'prezzo': 1}])
    stato.scrivi('mattino.json', {'giorno': '2026-11-03'})
    stato.scrivi('titoli.json', [{'ultimo_ts': '2026-11-03T09:30:00+00:00'},    # 10:30 a Roma
                                 {'ultimo_ts': '2026-11-03T10:00:00+01:00'}])
    acceso = stato.blocca('monitor.lock')
    monkeypatch.setattr('sys.argv', ['monitor.py', '--stato'])
    monitor.main()
    uscita = capsys.readouterr().out
    assert 'Monitor acceso: sì' in uscita
    assert 'Prezzi in sospeso (non ancora in Supabase): 1, dal 2026-11-03T10:00:00+01:00' in uscita
    assert 'Ultimi lavori del mattino: 2026-11-03' in uscita
    assert 'ultimo prezzo: 2026-11-03T09:30:00+00:00' in uscita
    acceso.close()


def test_stato_dice_se_oggi_la_borsa_e_chiusa(monkeypatch, capsys):
    import monitor

    class Natale(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 12, 25, 10)

    monkeypatch.setattr(monitor, 'datetime', Natale)
    monitor.mostra_stato()
    assert 'Oggi Borsa Italiana è chiusa (Natale)' in capsys.readouterr().out


def test_stato_non_crea_il_lock(monkeypatch, capsys):
    import monitor
    from core import stato
    monitor.mostra_stato()
    assert 'Monitor acceso: no' in capsys.readouterr().out
    assert not (stato.CARTELLA / 'monitor.lock').exists()


def test_appena_chiuso_solo_nei_15_minuti_dopo_la_chiusura():
    from core.orario import appena_chiuso
    giorno = datetime(2026, 11, 11)
    assert appena_chiuso(ORARIO, giorno.replace(hour=18, minute=5, second=1))
    assert appena_chiuso(ORARIO, giorno.replace(hour=18, minute=19))
    assert not appena_chiuso(ORARIO, giorno.replace(hour=18, minute=21))
    assert not appena_chiuso(ORARIO, giorno.replace(hour=23, minute=49))   # risveglio la sera
    assert not appena_chiuso(ORARIO, giorno.replace(hour=16, minute=40))
