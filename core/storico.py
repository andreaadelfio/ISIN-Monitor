#!/usr/bin/env python3
"""
Riempimento dei buchi dello storico con Yahoo Finance.

Borsa Italiana resta la fonte degli avvisi; Yahoo serve solo dove la tabella prezzi
non ha dati (PC spento, titolo appena aggiunto) e mai al momento di un avviso.
Un buco è un intervallo di 5 minuti (o un giorno, per le chiusure giornaliere) senza
nessun prezzo salvato: lì si aggiungono i punti di Yahoo con fonte 'yahoo'.

  - una tantum (monitor.py --riempi-storico): ultimi 7 giorni al minuto, fino a 60
    giorni ai 5 minuti, l'anno prima con una chiusura al giorno;
  - ogni mattina, al primo avvio: gli ultimi 7 giorni al minuto (copre il giorno
    prima e i giorni a PC spento; ai 5 minuti solo se Yahoo non ha il dato al minuto,
    come per i titoli americani quotati a Milano), il completo per i titoli senza prezzi.

Oggi non si riempie mai: i prezzi di oggi arrivano da Borsa Italiana.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Set
from zoneinfo import ZoneInfo

import pandas as pd

from .database import righe_prezzi

ROMA = ZoneInfo('Europe/Rome')
# Lo stesso inizio degli intervalli di serie_prezzi (date_bin) nel database
ORIGINE = datetime(2000, 1, 3, tzinfo=timezone(timedelta(hours=1)))
# La chiusura giornaliera di Yahoo si salva all'ora di chiusura della borsa
ORA_CHIUSURA = (17, 30)

# (intervallo Yahoo, periodo Yahoo, intervallo dei buchi, passo per serie_prezzi, di riserva)
# Un passo "di riserva" si fa solo se i passi prima non hanno avuto dati da Yahoo
COMPLETO = [
    ('1m', '7d', timedelta(minutes=5), '5 minutes', False),
    ('5m', '60d', timedelta(minutes=5), '5 minutes', False),
    ('1d', '1y', timedelta(days=1), '1 day', False),
]
GIORNALIERO = [
    ('1m', '7d', timedelta(minutes=5), '5 minutes', False),
    ('5m', '7d', timedelta(minutes=5), '5 minutes', True),
]


def inizio_intervallo(ts: datetime, passo: timedelta) -> datetime:
    """Inizio dell'intervallo di `passo` che contiene ts (come date_bin in Postgres)."""
    return ORIGINE + ((ts - ORIGINE) // passo) * passo


def simbolo_yahoo(titolo: Dict) -> str:
    """Il simbolo Yahoo in euro: simbolo_borsa, o simbolo se il titolo è quotato in euro.

    Il simbolo principale di un titolo americano (es. AMZN) è in dollari: mescolato ai
    prezzi in euro di Borsa Italiana rovinerebbe lo storico, quindi non si usa.
    """
    if titolo.get('simbolo_borsa'):
        return titolo['simbolo_borsa']
    if titolo.get('simbolo') and (titolo.get('valuta') == 'EUR' or titolo['simbolo'].endswith('.MI')):
        return titolo['simbolo']
    return ''


def punti_mancanti(serie: pd.DataFrame, occupati: Set[datetime], passo: timedelta,
                   giornaliera: bool, fino_a: datetime) -> List[tuple]:
    """I punti di Yahoo (ts UTC, price) che cadono in intervalli senza prezzi salvati.

    Con `giornaliera` ogni barra diventa la chiusura del suo giorno (alle 17:30 di Roma).
    Esclude tutto da `fino_a` in poi (l'inizio di oggi).
    """
    punti = []
    for ts, prezzo in zip(serie['ts'], serie['price']):
        ts = ts.to_pydatetime().astimezone(ROMA)
        if giornaliera:
            ts = ts.replace(hour=ORA_CHIUSURA[0], minute=ORA_CHIUSURA[1], second=0)
        if ts >= fino_a or inizio_intervallo(ts, passo) in occupati:
            continue
        punti.append((ts, float(prezzo)))
    return punti


def riempi_titolo(db, yahoo, titolo: Dict, passi: List[tuple], adesso: datetime,
                  scrivi: bool = True) -> int:
    """Riempie i buchi di un titolo, un passo alla volta; restituisce i punti aggiunti."""
    simbolo = simbolo_yahoo(titolo)
    if not simbolo:
        print(f"⏭️ {titolo['isin']}: manca simbolo_borsa (il simbolo Yahoo in euro), salto")
        return 0

    fino_a = adesso.astimezone(ROMA).replace(hour=0, minute=0, second=0, microsecond=0)
    aggiunti = []  # anche senza scrivere, i passi dopo non devono ricontarli
    con_dati = False
    for intervallo, periodo, passo, passo_sql, di_riserva in passi:
        if di_riserva and con_dati:
            continue
        try:
            serie = yahoo.get_series(simbolo, periodo, intervallo)
        except RuntimeError as errore:
            print(f"⚠️ {simbolo} {intervallo}: {errore}")
            continue
        if serie.empty:
            print(f"📭 {simbolo} {intervallo}: nessun dato da Yahoo")
            continue
        con_dati = True
        # Gli intervalli già coperti, dal primo punto di Yahoo in poi (una query, a pagine)
        da = inizio_intervallo(serie['ts'].iloc[0].to_pydatetime(), passo)
        occupati = {
            datetime.fromisoformat(riga['ts']) for riga in db.serie(titolo['isin'], da, passo_sql)
        }
        occupati |= {inizio_intervallo(ts, passo) for ts, _ in aggiunti}
        punti = punti_mancanti(serie, occupati, passo, intervallo == '1d', fino_a)
        if punti and scrivi:
            db.scrivi_prezzi(righe_prezzi(titolo['isin'], punti, 'yahoo'))
        print(f"📥 {simbolo} {intervallo}: {len(punti)} punti Yahoo "
              f"{'aggiunti' if scrivi else 'da aggiungere'} su {len(serie)}")
        aggiunti.extend(punti)
    return len(aggiunti)
