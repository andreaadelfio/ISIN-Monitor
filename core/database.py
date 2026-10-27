#!/usr/bin/env python3
"""
Accesso al database Supabase di MyFinance (API REST di PostgREST).

Tabelle usate (lo schema è in MyFinance/supabase/schema.sql):
  - watchlist: i titoli (isin, simbolo, simbolo_borsa, nome, soglia_avviso, segnale, ...)
  - prezzi: lo storico (isin, ts, prezzo, fonte 'borsa' | 'yahoo')
  - serie_prezzi(p_isin, p_da, p_passo): lo storico già sfoltito, un prezzo per intervallo

Serve la chiave secret (sb_secret_...): la legge da SUPABASE_SECRET_KEY o, se manca,
dal file ~/.config/isin-monitor/supabase.env. La chiave non va mai nel repository,
in config.json o nei log.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import requests

URL_PREDEFINITO = 'https://fvhzmkvqizfnbgxexdgu.supabase.co'
FILE_CHIAVE = Path.home() / '.config' / 'isin-monitor' / 'supabase.env'
# Supabase restituisce al massimo 1000 righe per richiesta: oltre si chiede a pagine
RIGHE_PER_PAGINA = 1000
# Righe per ogni scrittura (la migrazione dello storico ne manda centinaia di migliaia)
RIGHE_PER_SCRITTURA = 5000


class ErroreDatabase(RuntimeError):
    """Supabase non raggiungibile (status None) o richiesta rifiutata (status HTTP)."""

    def __init__(self, messaggio: str, status: Optional[int] = None):
        super().__init__(messaggio)
        self.status = status


def leggi_chiave() -> Optional[str]:
    """La chiave secret dall'ambiente o dal file supabase.env (righe CHIAVE=valore)."""
    chiave = os.environ.get('SUPABASE_SECRET_KEY', '').strip()
    if chiave:
        return chiave
    try:
        for riga in FILE_CHIAVE.read_text(encoding='utf-8').splitlines():
            nome, _, valore = riga.partition('=')
            if nome.strip() == 'SUPABASE_SECRET_KEY':
                return valore.strip().strip('"\'') or None
    except OSError:
        pass
    return None


class Database:

    def __init__(self, url: str, chiave: str, timeout: float = 10):
        self.url = url.rstrip('/') + '/rest/v1'
        self.timeout = timeout
        self.session = requests.Session()
        # Con le chiavi sb_secret_ basta l'header apikey (niente Authorization)
        self.session.headers.update({'apikey': chiave})

    @classmethod
    def da_configurazione(cls, config: Dict) -> Optional['Database']:
        """Il database di config.json (SUPABASE_URL lo sostituisce, per le prove locali)."""
        chiave = leggi_chiave()
        if not chiave:
            print(f"⚠️ Chiave Supabase mancante: imposta SUPABASE_SECRET_KEY in {FILE_CHIAVE}")
            return None
        url = os.environ.get('SUPABASE_URL') or config.get('supabase', {}).get('url', URL_PREDEFINITO)
        timeout = config.get('api', {}).get('request_timeout', 10)
        return cls(url, chiave, timeout)

    # --- richieste ---------------------------------------------------------------

    def _richiesta(self, metodo: str, percorso: str, **kwargs) -> requests.Response:
        try:
            risposta = self.session.request(
                metodo, f"{self.url}/{percorso}", timeout=self.timeout, **kwargs
            )
        except requests.RequestException as errore:
            raise ErroreDatabase(f"Supabase non raggiungibile: {errore.__class__.__name__}") from None
        if risposta.status_code >= 400:
            raise ErroreDatabase(
                f"Supabase {metodo} {percorso}: {risposta.status_code} {risposta.text[:300]}",
                risposta.status_code,
            )
        return risposta

    def _leggi(self, percorso: str, parametri: Dict) -> List[Dict]:
        """GET con tutte le pagine (parametri deve avere un order, per pagine stabili)."""
        righe: List[Dict] = []
        while True:
            pagina = self._richiesta('GET', percorso, params={
                **parametri, 'limit': RIGHE_PER_PAGINA, 'offset': len(righe),
            }).json()
            righe.extend(pagina)
            if len(pagina) < RIGHE_PER_PAGINA:
                return righe

    # --- titoli ------------------------------------------------------------------

    def titoli(self) -> List[Dict]:
        """La watchlist, con l'ultimo prezzo salvato di ogni titolo (una sola richiesta)."""
        return self._richiesta('GET', 'watchlist', params={
            'select': 'isin,simbolo,simbolo_borsa,valuta,nome,soglia_avviso,ultimo:prezzi(ts,prezzo)',
            'ultimo.order': 'ts.desc',
            'ultimo.limit': 1,
            'order': 'isin',
        }).json()

    def proposte(self) -> List[Dict]:
        """Segnale e punteggio dell'analisi di MyFinance per ogni titolo."""
        return self._richiesta('GET', 'watchlist', params={
            'select': 'isin,nome,segnale,punteggio,errore', 'order': 'isin',
        }).json()

    def aggiungi_titoli(self, righe: List[Dict]) -> None:
        """Nuovi titoli nella watchlist (quelli già presenti restano come sono)."""
        self._richiesta('POST', 'watchlist', params={'on_conflict': 'isin'}, json=righe,
                        headers={'Prefer': 'resolution=ignore-duplicates,return=minimal'})

    def aggiorna_titolo(self, isin: str, campi: Dict) -> None:
        self._richiesta('PATCH', 'watchlist', params={'isin': f'eq.{isin}'}, json=campi,
                        headers={'Prefer': 'return=minimal'})

    # --- prezzi ------------------------------------------------------------------

    def scrivi_prezzi(self, righe: List[Dict]) -> None:
        """Aggiunge prezzi (isin, ts, prezzo, fonte); quelli con lo stesso isin e ts restano."""
        for inizio in range(0, len(righe), RIGHE_PER_SCRITTURA):
            self._richiesta(
                'POST', 'prezzi', params={'on_conflict': 'isin,ts'},
                json=righe[inizio:inizio + RIGHE_PER_SCRITTURA],
                headers={'Prefer': 'resolution=ignore-duplicates,return=minimal'},
            )

    def prezzi(self, isin: str, da: datetime) -> List[Dict]:
        """Tutti i prezzi di un titolo da `da` in poi, in ordine di tempo."""
        return self._leggi('prezzi', {
            'select': 'ts,prezzo,fonte', 'isin': f'eq.{isin}',
            'ts': f'gte.{da.isoformat()}', 'order': 'ts',
        })

    def serie(self, isin: str, da: datetime, passo: str) -> List[Dict]:
        """Un prezzo (l'ultimo) per ogni intervallo `passo` (es. '15 minutes', '1 day')."""
        return self._leggi('rpc/serie_prezzi', {
            'p_isin': isin, 'p_da': da.isoformat(), 'p_passo': passo, 'order': 'ts',
        })

    def conta_prezzi(self, isin: str, fonte: Optional[str] = None) -> int:
        """Quanti prezzi ha un titolo nel database (per i controlli della migrazione)."""
        parametri = {'select': 'ts', 'isin': f'eq.{isin}', 'limit': 1}
        if fonte:
            parametri['fonte'] = f'eq.{fonte}'
        risposta = self._richiesta('GET', 'prezzi', params=parametri,
                                   headers={'Prefer': 'count=exact'})
        # Content-Range: 0-0/12345
        return int(risposta.headers.get('Content-Range', '*/0').rsplit('/', 1)[1])


def righe_prezzi(isin: str, punti: Iterable, fonte: str) -> List[Dict]:
    """Righe per la tabella prezzi da coppie (timestamp con fuso, prezzo)."""
    return [
        {'isin': isin, 'ts': ts.isoformat(), 'prezzo': round(float(prezzo), 4), 'fonte': fonte}
        for ts, prezzo in punti
    ]
