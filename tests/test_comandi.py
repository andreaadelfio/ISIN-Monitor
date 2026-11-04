"""Comandi del bot Telegram con un monitor e un database finti: nessun messaggio parte davvero."""

import queue
import time
from datetime import datetime

from core import comandi, stato
from core.comandi import ROMA

TITOLI = [
    {'isin': 'IT0003132476', 'nome': 'Eni S.p.A.', 'simbolo_borsa': 'ENI.MI', 'ultimo_prezzo': 20.2},
    {'isin': 'NL0011585146', 'nome': 'Ferrari N.V.', 'simbolo_borsa': 'RACE.MI', 'ultimo_prezzo': 355.5},
    {'isin': 'US69608A1088', 'nome': 'Palantir Technologies Inc.', 'simbolo_borsa': '1PLTR.MI',
     'ultimo_prezzo': None},
    {'isin': 'IT0005239360', 'nome': 'UniCredit S.p.A.', 'simbolo_borsa': 'UCG.MI', 'ultimo_prezzo': 74.0},
]


class DbFinto:
    """Ieri: Eni 20, Ferrari 360; UniCredit senza storico."""
    chiusure = {'IT0003132476': 20.0, 'NL0011585146': 360.0}

    def serie(self, isin, da, passo):
        if isin not in self.chiusure:
            return []
        return [{'ts': '2026-11-02T00:00:00+01:00', 'prezzo': self.chiusure[isin] - 1},
                {'ts': '2026-11-03T00:00:00+01:00', 'prezzo': self.chiusure[isin]},
                {'ts': '2026-11-04T00:00:00+01:00', 'prezzo': 1.0}]   # oggi: non conta


class MonitorFinto:
    def __init__(self):
        self.config = {'telegram': {'chat_id': '42'},
                       'monitoring': {'market_open_time': '08:55', 'market_close_time': '18:05'}}
        self.db = DbFinto()
        self.online = True
        self.avviato = datetime(2026, 11, 4, 8, 55, tzinfo=ROMA)
        self.ultimo_giro = (datetime(2026, 11, 4, 10, 32, 15, tzinfo=ROMA), 17, 18)
        self.giri_fatti, self.avvisi_di_oggi = 1500, 12
        self.errore_telegram = ''
        self.messaggi = []

    def send_telegram_message(self, testo, anteprima=True):
        self.messaggi.append(testo)
        return True


def test_nome_breve_e_ricerca_dei_titoli():
    assert comandi.nome_breve(TITOLI[0]) == 'Eni'
    assert comandi.nome_breve(TITOLI[2]) == 'Palantir'
    assert [t['isin'] for t in comandi.trova_titoli(TITOLI, 'eni')] == ['IT0003132476']   # simbolo
    assert [t['isin'] for t in comandi.trova_titoli(TITOLI, 'race.mi')] == ['NL0011585146']
    assert [t['isin'] for t in comandi.trova_titoli(TITOLI, 'us69608a1088')] == ['US69608A1088']
    assert [t['isin'] for t in comandi.trova_titoli(TITOLI, 'ferr')] == ['NL0011585146']   # nome
    assert len(comandi.trova_titoli(TITOLI, 's.p.a.')) == 2
    assert comandi.trova_titoli(TITOLI, '') == []


def test_prezzi_dal_migliore_al_peggiore_con_la_variazione_da_ieri():
    testo = comandi.testo_prezzi(DbFinto(), TITOLI, datetime(2026, 11, 4, 10, 32, tzinfo=ROMA))
    assert testo.startswith('📊 <b>Prezzi alle 10:32</b> (variazione da ieri)')
    righe = testo.split('<code>')[1].removesuffix('</code>').split('\n')
    assert righe == ['Eni        €20.20  +1.00% 📈',
                     'Ferrari   €355.50  -1.25% 📉',
                     'UniCredit  €74.00      —']        # senza storico in fondo; Palantir senza prezzo


def test_prezzi_prima_dell_apertura():
    senza = [{**titolo, 'ultimo_prezzo': None} for titolo in TITOLI]
    assert 'la borsa apre' in comandi.testo_prezzi(DbFinto(), senza, datetime.now(ROMA))


def test_grafico_passa_dalla_coda_degli_avvisi():
    stato.scrivi('titoli.json', TITOLI)
    monitor, coda = MonitorFinto(), queue.Queue()
    comandi.rispondi(monitor, coda, '/grafico@ISINMonitorBot ferrari')
    avviso = coda.get_nowait()
    assert avviso['titolo']['isin'] == 'NL0011585146' and avviso['prezzo'] == 355.5
    assert avviso['precedente'] is None and monitor.messaggi == []


def test_grafico_senza_prezzo_ambiguo_o_sconosciuto():
    stato.scrivi('titoli.json', TITOLI)
    monitor, coda = MonitorFinto(), queue.Queue()
    comandi.rispondi(monitor, coda, '/grafico palantir')
    comandi.rispondi(monitor, coda, '/grafico s.p.a.')
    comandi.rispondi(monitor, coda, '/grafico tesla')
    assert coda.empty()
    assert monitor.messaggi[0] == 'Nessun prezzo ancora per Palantir Technologies Inc.'
    assert monitor.messaggi[1] == 'Più titoli per «s.p.a.»: Eni, UniCredit. Scrivi di più.'
    assert monitor.messaggi[2].startswith('Nessun titolo per «tesla»') and '/grafico eni' in monitor.messaggi[2]


def test_stato_e_aiuto():
    monitor = MonitorFinto()
    comandi.rispondi(monitor, queue.Queue(), '/stato')
    comandi.rispondi(monitor, queue.Queue(), '/start')
    assert monitor.messaggi[0].split('\n') == [
        '🟢 <b>ISIN Monitor acceso</b> dalle 08:55',
        'Ultimo giro alle 10:32:15: 17/18 prezzi letti',
        'Giri fatti: 1500, avvisi mandati: 12',
        'Supabase: ok',
        'Orario: lun-ven 08:55-18:05',
    ]
    assert '/prezzi' in monitor.messaggi[1] and '/grafico' in monitor.messaggi[1]


def test_solo_la_chat_di_andrea_e_niente_comandi_vecchi():
    monitor, adesso = MonitorFinto(), time.time()

    def messaggio(numero, chat, eta, testo='/stato'):
        return {'update_id': numero, 'message': {'chat': {'id': chat}, 'date': int(adesso - eta), 'text': testo}}

    offset = comandi.gestisci(monitor, queue.Queue(), [
        messaggio(10, 42, 5),           # Andrea, adesso: sì
        messaggio(11, 999, 5),          # un'altra chat: no
        messaggio(12, 42, 3600),        # di un'ora fa, a monitor spento: no
        messaggio(13, 42, 5, 'ciao'),   # non è un comando: niente risposta
    ], adesso)
    assert offset == 14 and len(monitor.messaggi) == 1 and 'acceso' in monitor.messaggi[0]


WEBHOOK = ("Conflict: can't use getUpdates method while webhook is active; "
           "use deleteWebhook to delete the webhook first (409)")


def test_ascolta_menu_offset_e_webhook_attivo(monkeypatch, capsys):
    import pytest
    monitor = MonitorFinto()
    chiamate = []
    risposte = [None, None, [{'update_id': 7, 'message': {'chat': {'id': 42}, 'date': int(time.time()),
                                                          'text': '/aiuto'}}], []]

    def chiama(metodo, **kwargs):
        chiamate.append((metodo, kwargs['data'].get('offset')))
        if metodo == 'getUpdates':   # anche i messaggi del canale
            assert kwargs['data']['allowed_updates'] == '["message", "channel_post"]'
        if metodo == 'setMyCommands':
            return True
        if not risposte:
            raise KeyboardInterrupt   # fine del test
        risposta = risposte.pop(0)
        if risposta is None:   # come chiama_telegram quando Telegram risponde 409
            monitor.errore_telegram = WEBHOOK
        return risposta

    monitor.chiama_telegram = chiama
    monkeypatch.setattr(comandi.time, 'sleep', lambda secondi: None)
    with pytest.raises(KeyboardInterrupt):
        comandi.ascolta(monitor, queue.Queue())
    assert chiamate[0] == ('setMyCommands', None)
    assert [offset for metodo, offset in chiamate[1:]] == [None, None, None, 8, 8]
    uscita = capsys.readouterr().out
    # L'errore vero di Telegram, una volta sola, con cosa fare; poi di nuovo attivi
    assert uscita.count('Comandi del bot non attivi') == 1
    assert f'Telegram dice: {WEBHOOK}' in uscita and './setup.sh telegram togli-webhook' in uscita
    assert 'di nuovo attivi' in uscita
    assert 'Comandi di ISIN Monitor' in monitor.messaggi[0]


def test_altro_programma_che_legge_lo_stesso_bot():
    consiglio = comandi.consiglio('Conflict: terminated by other getUpdates request; make sure that '
                                  'only one bot instance is running (409)')
    assert 'un altro programma legge i messaggi con lo stesso bot' in consiglio
    assert comandi.consiglio('non raggiungibile (ConnectionError)') == ''


def test_comandi_scritti_nel_canale():
    monitor, adesso = MonitorFinto(), time.time()
    post = {'update_id': 20, 'channel_post': {'chat': {'id': 42, 'type': 'channel'},
                                              'date': int(adesso), 'text': '/stato'}}
    altro = {'update_id': 21, 'channel_post': {'chat': {'id': -100, 'type': 'channel'},
                                               'date': int(adesso), 'text': '/stato'}}
    assert comandi.gestisci(monitor, queue.Queue(), [post, altro], adesso) == 22
    assert len(monitor.messaggi) == 1 and 'acceso' in monitor.messaggi[0]   # risponde nel canale


def test_canale_indicato_con_lo_username(capsys):
    comandi.CHAT_IGNORATE.clear()
    monitor, adesso = MonitorFinto(), time.time()
    monitor.config['telegram']['chat_id'] = '@Canale_Prova'

    def post(numero, chat):
        return {'update_id': numero, 'channel_post': {'chat': chat, 'date': int(adesso), 'text': '/stato'}}

    comandi.gestisci(monitor, queue.Queue(), [
        post(1, {'id': -1001234567890, 'type': 'channel', 'username': 'canale_prova'}),   # sì
        post(2, {'id': -1009999999999, 'type': 'channel', 'username': 'altro'}),           # no
        post(3, {'id': -1009999999999, 'type': 'channel', 'username': 'altro'}),           # no
    ], adesso)
    assert len(monitor.messaggi) == 1 and 'acceso' in monitor.messaggi[0]
    uscita = capsys.readouterr().out
    # La chat sbagliata nel log una volta sola, con id e username
    assert uscita.count('chat diversa da chat_id') == 1 and 'id -1009999999999, @altro' in uscita


def test_canale_indicato_con_l_id_numerico():
    assert comandi.stessa_chat({'id': -1001234567890, 'username': 'prova'}, -1001234567890)
    assert comandi.stessa_chat({'id': -1001234567890}, '-1001234567890')
    assert not comandi.stessa_chat({'id': -1001234567890, 'username': 'prova'}, '-100')
    assert not comandi.stessa_chat({'id': 5, 'username': None}, '@prova')
