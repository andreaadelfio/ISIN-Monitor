#!/usr/bin/env python3
"""
Stato locale di ISIN Monitor, fuori da Dropbox (~/.local/state/isin-monitor/):
l'ultima lista dei titoli con gli ultimi prezzi (usata se Supabase non risponde),
i prezzi non ancora scritti nel database, il giorno degli ultimi lavori del
mattino, i titoli con lo storico Yahoo già completo, le proposte già mandate su
Telegram e il message_id dell'ultimo grafico di ogni titolo. Sono piccoli file JSON.
"""

import fcntl
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
    # Un temporaneo per processo: un --giro a mano non pesta quello del servizio
    temporaneo = CARTELLA / f"{nome}.{os.getpid()}.tmp"
    with open(temporaneo, 'w', encoding='utf-8') as file:
        json.dump(dati, file, ensure_ascii=False, indent=1)
    os.replace(temporaneo, CARTELLA / nome)


def blocca(nome: str):
    """Lock esclusivo su un file di stato, finché il processo è vivo.

    Restituisce il file aperto (da tenere in una variabile) o None se lo tiene già un
    altro processo. Il sistema lo libera da solo quando il processo esce, anche se muore.
    """
    CARTELLA.mkdir(parents=True, exist_ok=True)
    file = open(CARTELLA / nome, 'a')   # 'a': non tocca il file se il lock è di un altro
    try:
        fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        file.close()
        return None
    return file
