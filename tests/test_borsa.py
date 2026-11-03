"""Borsa Italiana con una sessione HTTP finta: nessuna richiesta parte davvero."""

import pytest

from core import price_providers
from core.price_providers import RIPROVA_SENZA_SCHEDA, BorsaItalianaProvider

SCHEDA = ('<span class="-formatPrice"><strong>20,31</strong></span>')

PRIMA_DELL_APERTURA = ('<span class="t-text -black-warm-60 -formatPrice">\n<strong></strong>\n</span>'
                       '<span class="t-text -size-lg -percPrice">\n<strong>+0,00%</strong>')


class Risposta:
    def __init__(self, url, status=200, testo=''):
        self.url, self.status_code, self.text = url, status, testo


class SessioneFinta:
    """Risponde come Borsa Italiana: scheda per ISIN noti, listino A-Z per gli altri."""

    def __init__(self, noti):
        self.noti = noti
        self.richieste = []

    def get(self, url, **kwargs):
        self.richieste.append(url)
        if any(isin in url and percorso in url for isin, percorso in self.noti):
            return Risposta(url, testo=SCHEDA)
        # Anche il listino ha un prezzo vuoto: non va scambiato per una scheda
        return Risposta('https://www.borsaitaliana.it/borsa/azioni/listino-a-z.html?initial=A',
                        testo=PRIMA_DELL_APERTURA)


def test_titolo_senza_scheda_riprovato_dopo_dieci_minuti(monkeypatch):
    orologio = [1000.0]
    monkeypatch.setattr(price_providers.time, 'monotonic', lambda: orologio[0])
    borsa = BorsaItalianaProvider()
    borsa.session = SessioneFinta({('IT0003132476', '/azioni/')})

    assert borsa.get_price('IT0003132476') == (20.31, None)
    assert not borsa.non_risponde
    assert borsa.get_price('IT0003497168') == (None, None)
    assert len(borsa.session.richieste) == 5          # azioni, globale, ETF e BTP
    borsa.get_price('IT0003497168')                    # al giro dopo nessuna richiesta
    assert len(borsa.session.richieste) == 5
    orologio[0] += RIPROVA_SENZA_SCHEDA + 1
    borsa.get_price('IT0003497168')
    assert len(borsa.session.richieste) == 9


def test_errori_di_rete_riprovati_al_giro_dopo_senza_altri_timeout():
    class SessioneRotta:
        richieste = 0

        def get(self, url, **kwargs):
            SessioneRotta.richieste += 1
            raise price_providers.requests.ConnectionError()

    borsa = BorsaItalianaProvider()
    borsa.session = SessioneRotta()
    borsa.get_price('IT0003132476')
    borsa.get_price('IT0003132476')
    # Una richiesta per giro: dopo un errore di rete le altre pagine non si provano
    assert SessioneRotta.richieste == 2
    assert borsa.non_risponde


def test_scheda_senza_prezzo_riprovata_al_giro_dopo():
    class SessioneVuota(SessioneFinta):
        def get(self, url, **kwargs):
            self.richieste.append(url)
            return Risposta(url, testo='<html>manutenzione</html>')

    borsa = BorsaItalianaProvider()
    borsa.session = SessioneVuota(set())
    borsa.get_price('IT0003132476')
    borsa.get_price('IT0003132476')
    # La scheda c'è: le altre pagine non si provano, e al giro dopo si riprova
    assert len(borsa.session.richieste) == 2


def test_yahoo_non_riprova_un_simbolo_sconosciuto(monkeypatch):
    import pytest
    from core.price_providers import YahooFinanceProvider

    class Risposta404:
        status_code = 404

        def raise_for_status(self):
            raise price_providers.requests.HTTPError('404', response=self)

    yahoo = YahooFinanceProvider({'max_retries': 2})
    chiamate = []
    monkeypatch.setattr(yahoo.session, 'get', lambda *a, **k: chiamate.append(1) or Risposta404())
    monkeypatch.setattr(price_providers.time, 'sleep', lambda s: pytest.fail('nessuna attesa'))
    with pytest.raises(RuntimeError):
        yahoo.get_series('NONESISTE.MI', '7d', '1m')
    assert chiamate == [1]


def test_etf_e_btp_dalla_loro_scheda_poi_una_richiesta_sola():
    borsa = BorsaItalianaProvider()
    borsa.session = SessioneFinta({('IE00B4L5Y983', '/etf/'), ('IT0005083057', '/btp/')})
    assert borsa.get_price('IE00B4L5Y983')[0] == 20.31
    assert borsa.get_price('IT0005083057')[0] == 20.31
    assert len(borsa.session.richieste) == 3 + 4
    borsa.get_price('IE00B4L5Y983')
    assert len(borsa.session.richieste) == 8 and '/etf/' in borsa.session.richieste[-1]
    assert '/etf/scheda/IE00B4L5Y983' in borsa.scheda('IE00B4L5Y983')
    assert borsa.scheda('X') == 'https://www.borsaitaliana.it/borsa/azioni/scheda/X.html'


def test_errore_del_server_niente_altre_pagine():
    class SessioneGuasta(SessioneFinta):
        def get(self, url, **kwargs):
            self.richieste.append(url)
            return Risposta(url, status=503)

    borsa = BorsaItalianaProvider()
    borsa.session = SessioneGuasta(set())
    borsa.get_price('IT0003132476')
    borsa.get_price('IT0003132476')
    assert len(borsa.session.richieste) == 2


def test_prima_dell_apertura_nessun_prezzo_una_richiesta_e_niente_errore(capsys):
    class SessioneMattino(SessioneFinta):
        def get(self, url, **kwargs):
            self.richieste.append(url)
            return Risposta(url.replace('.html', '-MTAA.html'), testo=PRIMA_DELL_APERTURA)

    borsa = BorsaItalianaProvider()
    borsa.session = SessioneMattino(set())
    assert borsa.get_price('IT0003132476') == (None, None)
    assert borsa.get_price('IT0003132476') == (None, None)
    assert borsa.session.richieste[1].endswith('IT0003132476-MTAA.html')   # l'indirizzo finale
    assert len(borsa.session.richieste) == 2 and not borsa.non_risponde
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('testo, prezzo', [
    ('20,31', 20.31), ('1.234,5', 1234.5), ('0,4521', 0.4521), ('101,23 ', 101.23), ('', None)])
def test_prezzi_nel_formato_italiano(testo, prezzo):
    pagina = f'<span class="-formatPrice"><strong>{testo}</strong></span>'
    assert BorsaItalianaProvider()._extract_price_from_html(pagina) == prezzo


def test_niente_prezzi_presi_da_altri_numeri_della_pagina():
    pagina = '<span class="-percPrice"><strong>0,52</strong></span><strong>12,30</strong>'
    assert BorsaItalianaProvider()._extract_price_from_html(pagina) is None


@pytest.mark.parametrize('status', [403, 429])
def test_bloccati_o_troppe_richieste_si_smette(status):
    class SessioneBloccata(SessioneFinta):
        def get(self, url, **kwargs):
            self.richieste.append(url)
            return Risposta(url, status=status)

    borsa = BorsaItalianaProvider()
    borsa.session = SessioneBloccata(set())
    assert borsa.get_price('IT0003132476') == (None, None)
    assert borsa.troppe_richieste and len(borsa.session.richieste) == 1


def test_titolo_tolto_dal_listino_dimentica_la_pagina_ricordata(monkeypatch):
    orologio = [1000.0]
    monkeypatch.setattr(price_providers.time, 'monotonic', lambda: orologio[0])
    borsa = BorsaItalianaProvider()
    borsa.session = SessioneFinta({('IT0003132476', '/azioni/')})
    borsa.get_price('IT0003132476')
    borsa.session.noti.clear()                     # la scheda non c'è più
    assert borsa.get_price('IT0003132476') == (None, None)
    assert len(borsa.session.richieste) == 1 + 5   # la pagina ricordata e le quattro solite
    orologio[0] += RIPROVA_SENZA_SCHEDA + 1
    borsa.get_price('IT0003132476')
    assert len(borsa.session.richieste) == 1 + 5 + 4
