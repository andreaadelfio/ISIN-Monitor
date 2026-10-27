#!/usr/bin/env python3
"""
Stato locale di ISIN Monitor, fuori da Dropbox (~/.local/state/isin-monitor/):
l'ultima lista dei titoli con gli ultimi prezzi (usata se Supabase non risponde),
i prezzi non ancora scritti nel database, il giorno degli ultimi lavori del
mattino e le proposte già mandate su Telegram. Sono piccoli file JSON.
"""

import json
import os
from pathlib import Path

CARTELLA = Path(os.environ.get(
    'ISIN_MONITOR_STATO', Path.home() / '.local' / 'state' / 'isin-monitor'
))


def leggi(nome: str, predefinito=None):
    """Legge un file di stato; se manca o è rovinato restituisce `predefinito`."""
    try:
        with open(CARTELLA / nome, encoding='utf-8') as file:
            return json.load(file)
    except (OSError, ValueError):
        return predefinito


def scrivi(nome: str, dati) -> None:
    """Scrive un file di stato in modo atomico (un'interruzione non lo lascia a metà)."""
    CARTELLA.mkdir(parents=True, exist_ok=True)
    temporaneo = CARTELLA / f"{nome}.tmp"
    with open(temporaneo, 'w', encoding='utf-8') as file:
        json.dump(dati, file, ensure_ascii=False, indent=1)
    os.replace(temporaneo, CARTELLA / nome)
