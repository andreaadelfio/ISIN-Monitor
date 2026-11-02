"""Borsa Italiana con una sessione HTTP finta: nessuna richiesta parte davvero."""

from core import price_providers
from core.price_providers import RIPROVA_SENZA_SCHEDA, BorsaItalianaProvider

SCHEDA = ('<span class="-formatPrice"><strong>20,31</strong></span>')


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
        return Risposta('https://www.borsaitaliana.it/borsa/azioni/listino-a-z.html?initial=A')


def test_titolo_senza_scheda_riprovato_dopo_dieci_minuti(monkeypatch):
    orologio = [1000.0]
    monkeypatch.setattr(price_providers.time, 'monotonic', lambda: orologio[0])
    borsa = BorsaItalianaProvider()
    borsa.session = SessioneFinta({('IT0003132476', '/azioni/')})

    assert borsa.get_price('IT0003132476') == (20.31, None)
    assert borsa.get_price('IT0003497168') == (None, None)
    assert len(borsa.session.richieste) == 3          # mercato italiano e globale
    borsa.get_price('IT0003497168')                    # al giro dopo nessuna richiesta
    assert len(borsa.session.richieste) == 3
    orologio[0] += RIPROVA_SENZA_SCHEDA + 1
    borsa.get_price('IT0003497168')
    assert len(borsa.session.richieste) == 5


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


def test_scheda_senza_prezzo_riprovata_al_giro_dopo():
    class SessioneVuota(SessioneFinta):
        def get(self, url, **kwargs):
            self.richieste.append(url)
            return Risposta(url, testo='<html>manutenzione</html>')

    borsa = BorsaItalianaProvider()
    borsa.session = SessioneVuota(set())
    borsa.get_price('IT0003132476')
    borsa.get_price('IT0003132476')
    assert len(borsa.session.richieste) == 4


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
