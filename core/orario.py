#!/usr/bin/env python3
"""
Orario di mercato di ISIN Monitor.

Solo libreria standard: monitor.py lo usa prima degli import pesanti (pandas,
matplotlib), così un avvio fuori orario finisce subito. setup.sh lo lancia per
scrivere gli OnCalendar del timer systemd dagli orari di config.json:

    python3 core/orario.py config.json
"""

import json
import sys
from datetime import datetime, time


# Un giro di controllo ogni INTERVALLO secondi (anche il timer systemd usa questo passo)
INTERVALLO = 15


def secondi_al_prossimo_giro(adesso: datetime) -> float:
    """Quanto manca al prossimo multiplo di INTERVALLO secondi (es. :00, :15, :30, :45)."""
    return INTERVALLO - adesso.timestamp() % INTERVALLO


def _ora(testo: str) -> time:
    return datetime.strptime(testo, '%H:%M').time()


def in_orario(monitoring: dict, adesso: datetime) -> bool:
    """True se adesso è dentro l'orario configurato (con weekdays_only, solo lun-ven)."""
    if not monitoring.get('market_hours_only', True):
        return True
    # Sabato e domenica le borse sono chiuse
    if monitoring.get('weekdays_only', True) and adesso.weekday() >= 5:
        return False
    apertura = _ora(monitoring.get('market_open_time', '08:55'))
    chiusura = _ora(monitoring.get('market_close_time', '18:05'))
    return apertura <= adesso.time().replace(tzinfo=None) <= chiusura


def descrizione_orario(monitoring: dict) -> str:
    """Descrive l'orario configurato, es. 'lun-ven 08:55-18:05'."""
    if not monitoring.get('market_hours_only', True):
        return '24/7'
    ore = (f"{monitoring.get('market_open_time', '08:55')}-"
           f"{monitoring.get('market_close_time', '18:05')}")
    return f"lun-ven {ore}" if monitoring.get('weekdays_only', True) else ore


def calendario_timer(monitoring: dict, secondi: int = INTERVALLO) -> list:
    """Righe OnCalendar del timer: un avvio ogni `secondi` solo nell'orario di mercato.

    Con 08:55-18:05 dà Mon..Fri 08:55..59:00/15, Mon..Fri 09..17:*:00/15 e
    Mon..Fri 18:00..05:00/15 (systemd non accetta un intervallo 08:55..18:05).
    """
    if not monitoring.get('market_hours_only', True):
        return [f"*:*:00/{secondi}"]

    giorni = 'Mon..Fri' if monitoring.get('weekdays_only', True) else '*-*-*'
    apertura = _ora(monitoring.get('market_open_time', '08:55'))
    chiusura = _ora(monitoring.get('market_close_time', '18:05'))
    sec = f"00/{secondi}"

    if apertura.hour == chiusura.hour:
        return [f"{giorni} {apertura.hour:02d}:{apertura.minute:02d}..{chiusura.minute:02d}:{sec}"]

    righe = []
    prima_ora_piena = apertura.hour
    if apertura.minute > 0:
        righe.append(f"{giorni} {apertura.hour:02d}:{apertura.minute:02d}..59:{sec}")
        prima_ora_piena += 1
    ultima_ora_piena = chiusura.hour - 1
    if prima_ora_piena == ultima_ora_piena:
        righe.append(f"{giorni} {prima_ora_piena:02d}:*:{sec}")
    elif prima_ora_piena < ultima_ora_piena:
        righe.append(f"{giorni} {prima_ora_piena:02d}..{ultima_ora_piena:02d}:*:{sec}")
    righe.append(f"{giorni} {chiusura.hour:02d}:00..{chiusura.minute:02d}:{sec}")
    return righe


if __name__ == '__main__':
    percorso = sys.argv[1] if len(sys.argv) > 1 else 'config.json'
    with open(percorso, encoding='utf-8') as file:
        configurazione = json.load(file)
    for riga in calendario_timer(configurazione.get('monitoring', {})):
        print(f"OnCalendar={riga}")
