#!/usr/bin/env python3
"""
Proposte di MyFinance su Telegram.

L'analisi serale di MyFinance (Edge Function "aggiorna-quotazioni") scrive nella
watchlist un segnale (compra, valuta, attendi, evita) e un punteggio per ogni titolo.
Al primo avvio del mattino ISIN Monitor confronta i segnali e la proposta del giorno
(il "Compra" con il punteggio più alto) con quelli già mandati, e se qualcosa è
cambiato manda un solo messaggio con i cambiamenti e i link alle schede.
"""

from html import escape
from typing import Dict, List, Optional

ETICHETTE = {
    'compra': 'Compra',
    'valuta': 'Da valutare',
    'attendi': 'Attendi',
    'evita': 'Evita per ora',
}


def link_myfinance(base_url: str, isin: str) -> str:
    """La scheda del titolo nel sito (?isin= resta anche dopo il login di Cloudflare Access)."""
    return f"{base_url.rstrip('/')}/?isin={isin}"


def stato_attuale(titoli: List[Dict]) -> Dict:
    """Segnali, nomi e proposta del giorno dalla watchlist (titoli con un segnale valido)."""
    validi = [t for t in titoli if t.get('segnale') and not t.get('errore')]
    compra = [t for t in validi if t['segnale'] == 'compra']
    migliore = max(compra, key=lambda t: (t.get('punteggio') or 0, t['isin']), default=None)
    return {
        'segnali': {t['isin']: t['segnale'] for t in validi},
        'nomi': {t['isin']: t.get('nome') or t['isin'] for t in validi},
        'proposta': migliore['isin'] if migliore else None,
        'punteggi': {t['isin']: t.get('punteggio') for t in validi},
    }


def cambiamenti(prima: Dict, adesso: Dict) -> Dict:
    """Cosa è cambiato: segnali diversi (anche titoli nuovi) e proposta del giorno."""
    segnali = []
    for isin, segnale in adesso['segnali'].items():
        precedente = prima.get('segnali', {}).get(isin)
        if precedente != segnale:
            segnali.append((isin, precedente, segnale))
    proposta_cambiata = prima.get('proposta') != adesso['proposta']
    return {'segnali': segnali, 'proposta': proposta_cambiata}


def messaggio(prima: Dict, adesso: Dict, cambi: Dict, base_url: str) -> Optional[str]:
    """Il messaggio Telegram (HTML) con i cambiamenti, o None se non è cambiato niente."""
    if not cambi['segnali'] and not cambi['proposta']:
        return None

    def nome(isin: str) -> str:
        testo = adesso['nomi'].get(isin) or prima.get('nomi', {}).get(isin) or isin
        return f'<a href="{link_myfinance(base_url, isin)}">{escape(testo)}</a>'

    righe = ['📋 <b>Proposte di MyFinance aggiornate</b>']
    if cambi['proposta']:
        isin = adesso['proposta']
        if isin:
            punteggio = adesso['punteggi'].get(isin)
            dettaglio = f" (punteggio {punteggio})" if punteggio is not None else ''
            righe.append(f"⭐ Proposta del giorno: {nome(isin)}{dettaglio}")
        else:
            righe.append("⭐ Nessuna proposta oggi: nessun titolo da comprare")
        if prima.get('proposta'):
            righe.append(f"    prima era {nome(prima['proposta'])}")
    if cambi['segnali']:
        righe.append('')
        for isin, precedente, segnale in sorted(cambi['segnali'], key=lambda c: adesso['nomi'][c[0]]):
            da = ETICHETTE.get(precedente, precedente) if precedente else 'nuovo'
            righe.append(f"• {nome(isin)}: {da} → <b>{ETICHETTE.get(segnale, segnale)}</b>")
    return '\n'.join(righe)
