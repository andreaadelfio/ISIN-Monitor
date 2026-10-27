#!/usr/bin/env python3
"""
ISIN Monitor - prezzi da Borsa Italiana, storico in Supabase (MyFinance), avvisi Telegram.

Il timer systemd lo avvia ogni 15 secondi in orario di mercato con --monitor.
Fuori orario esce subito, prima degli import pesanti (pandas, matplotlib).
"""

import argparse
import builtins
import json
import os
import sys
from datetime import datetime

from core.orario import descrizione_orario, in_orario


def carica_config(percorso: str = 'config.json') -> dict:
    if not os.path.exists(percorso):
        sys.exit(f"ERRORE: File di configurazione {percorso} non trovato!")
    try:
        with open(percorso, encoding='utf-8') as file:
            return json.load(file)
    except json.JSONDecodeError as errore:
        sys.exit(f"ERRORE: Errore nel parsing del file di configurazione: {errore}")


def main():
    parser = argparse.ArgumentParser(description='ISIN Monitor - Monitoraggio prezzi e notifiche')
    parser.add_argument('--monitor', action='store_true',
                        help='Un controllo di tutti i titoli (lo usa il timer systemd)')
    parser.add_argument('--check-once', action='store_true',
                        help='Test: controlla il primo titolo con soglia 0 (manda sempre l\'avviso)')
    parser.add_argument('--test-telegram', action='store_true',
                        help='Manda un messaggio di prova su Telegram')
    parser.add_argument('--grafico', metavar='ISIN',
                        help='Salva il grafico di un titolo in un PNG (senza Telegram)')
    parser.add_argument('--uscita', default='grafico.png',
                        help='File del grafico per --grafico (default grafico.png)')
    parser.add_argument('--riempi-storico', action='store_true',
                        help='Riempie una tantum i buchi dello storico con Yahoo')
    parser.add_argument('--prova', action='store_true',
                        help='Con --riempi-storico: conta i punti senza scriverli')
    parser.add_argument('--ignora-orario', action='store_true',
                        help='Controlla anche fuori dall\'orario di mercato')
    parser.add_argument('--with-profiling', action='store_true',
                        help='Abilita il profiling delle funzioni')
    args = parser.parse_args()

    config = carica_config()
    builtins.ENABLE_PROFILING = args.with_profiling
    controllo = args.monitor or args.check_once

    if controllo:
        adesso = datetime.now()
        print(f"🚀 [{adesso:%Y-%m-%d %H:%M:%S}] Controllo ISIN "
              f"(orario: {descrizione_orario(config['monitoring'])})")
        if not args.ignora_orario and not in_orario(config['monitoring'], adesso):
            print(f"⏰ Fuori orario di mercato ({adesso:%a %H:%M}): controllo saltato")
            return
    elif not (args.test_telegram or args.grafico or args.riempi_storico):
        parser.print_help()
        return

    from core.app import ISINMonitor
    monitor = ISINMonitor(config)

    if args.test_telegram:
        monitor.test_telegram()
    elif args.grafico:
        monitor.salva_grafico(args.grafico, args.uscita)
    elif args.riempi_storico:
        monitor.riempi_storico(scrivi=not args.prova)
    elif args.check_once or config.get('test'):
        monitor.run_test()
    else:
        monitor.controlla_tutti()
        print(f"✅ [{datetime.now():%H:%M:%S}] Controllo completato")

    if args.with_profiling:
        from core.profiling_analysis import main as profile_analyser_main
        profile_analyser_main()


if __name__ == "__main__":
    main()
