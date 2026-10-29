#!/usr/bin/env python3
"""
Le tue posizioni su un titolo, dal registro investimenti di MyFinance (tabella investimenti).

Una posizione raggruppa le operazioni dello stesso investimento ed è aperta finché non ha
un rimborso (la vendita). Le righe "domani" non sono operazioni vere (il valore se si
vendesse domani) e il database le lascia già fuori.

Il prezzo di carico è calcolato come in MyFinance (Edge Function "aggiorna-quotazioni"):
l'ABP del conto dell'operazione più recente che ce l'ha; senza ABP, quanto speso negli
acquisti diviso le quote comprate.
"""

from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional


def _numero(valore) -> Optional[float]:
    return float(valore) if valore not in (None, '') else None


def carico(operazioni: List[Dict], oggi: date) -> Optional[Dict]:
    """{'quote', 'prezzo'} delle posizioni aperte sul titolo, o None se non ne hai.

    Una posizione senza quantità né ABP (in MyFinance ha le quote stimate dal prezzo del
    giorno d'acquisto) resta fuori: qui non c'è quel prezzo per stimarle.
    """
    posizioni = defaultdict(list)
    for riga in operazioni:
        posizioni[riga['posizione']].append(riga)
    quote_totali = costo_totale = 0.0
    for righe in posizioni.values():
        acquisti = [r for r in righe if r['operazione'] == 'Investimento']
        venduta = any(r['operazione'] == 'Rimborso' and date.fromisoformat(r['data']) <= oggi
                      for r in righe)
        if not acquisti or venduta:
            continue
        # Le righe sono in ordine di data: l'ABP è quello dell'ultima che ce l'ha
        abp = next((v for v in (_numero(r.get('abp')) for r in reversed(righe)) if v and v > 0),
                   None)
        speso = sum(abs(float(r['importo'])) for r in acquisti)
        if all(_numero(r.get('quantita')) for r in acquisti):
            quote = sum(float(r['quantita']) for r in acquisti)
        elif abp:
            quote = speso / abp
        else:
            continue
        quote_totali += quote
        costo_totale += quote * abp if abp else speso
    if not quote_totali:
        return None
    return {'quote': quote_totali, 'prezzo': costo_totale / quote_totali}


def acquisti_e_vendite(operazioni: List[Dict]) -> List[Dict]:
    """Le operazioni da segnare sul grafico: {'data', 'acquisto', 'prezzo'}.

    Nel registro una vendita è un Rimborso (il capitale, quanto si era speso) più una Cedola
    lo stesso giorno (il guadagno, negativa se in perdita): il prezzo di vendita è la somma
    diviso la quantità. Senza quantità il prezzo è None (il segno va sulla curva).
    """
    guadagni = defaultdict(float)
    for riga in operazioni:
        if riga['operazione'] == 'Cedola':
            guadagni[riga['posizione'], riga['data']] += float(riga['importo'])
    segni = []
    for riga in operazioni:
        if riga['operazione'] not in ('Investimento', 'Rimborso'):
            continue
        importo = abs(float(riga['importo']))
        if riga['operazione'] == 'Rimborso':
            importo += guadagni[riga['posizione'], riga['data']]
        quantita = _numero(riga.get('quantita'))
        segni.append({
            'data': date.fromisoformat(riga['data']),
            'acquisto': riga['operazione'] == 'Investimento',
            'prezzo': importo / quantita if quantita else None,
        })
    return segni
