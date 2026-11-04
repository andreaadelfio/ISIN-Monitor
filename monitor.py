#!/usr/bin/env python3
"""
ISIN Monitor - prezzi da Borsa Italiana, storico in Supabase (MyFinance), avvisi Telegram.

Il timer systemd lo avvia in orario di mercato con --monitor: resta acceso e fa un
giro ogni 15 secondi fino alla chiusura (il timer lo riavvia se si ferma).
Fuori orario esce subito, prima degli import pesanti (pandas, matplotlib); nei giorni
feriali di borsa chiusa (core/orario.py, festivo) resta acceso senza fare niente fino
alla chiusura, così il timer non lo rilancia. Un solo monitor alla volta (monitor.lock).
"""

import argparse
import builtins
import json
import os
import sys
import time
from datetime import datetime

from core import stato
from core.orario import descrizione_orario, festivo, in_orario


def carica_config(percorso: str = 'config.json') -> dict:
    if not os.path.exists(percorso):
        sys.exit(f"ERRORE: File di configurazione {percorso} non trovato!")
    try:
        with open(percorso, encoding='utf-8') as file:
            return json.load(file)
    except json.JSONDecodeError as errore:
        sys.exit(f"ERRORE: Errore nel parsing del file di configurazione: {errore}")


def borsa_chiusa(monitoring: dict, adesso: datetime) -> bool:
    """True nei giorni feriali di chiusura di Borsa Italiana (se si segue l'orario di borsa)."""
    return (monitoring.get('market_hours_only', True) and monitoring.get('weekdays_only', True)
            and bool(festivo(adesso.date())))


def aspetta_la_chiusura(monitoring: dict) -> None:
    """Resta acceso, fermo, fino alla chiusura: se --monitor uscisse prima, il timer
    systemd lo riavvierebbe ogni 15 secondi per tutto il giorno."""
    while in_orario(monitoring, datetime.now()):
        time.sleep(60)


def mostra_stato() -> None:
    """Lo stato locale in poche righe (i file di ~/.local/state/isin-monitor)."""
    # Solo se il file c'è già: con sudo, root non deve crearlo (il servizio non potrebbe aprirlo)
    acceso = False
    if (stato.CARTELLA / 'monitor.lock').exists():
        lock = stato.blocca('monitor.lock')
        acceso = lock is None
        if lock:
            lock.close()
    print("Monitor acceso: " + ("sì" if acceso else "no"))
    chiusa = festivo(datetime.now().date())
    if chiusa:
        print(f"Oggi Borsa Italiana è chiusa ({chiusa}): il monitor resta fermo")
    in_sospeso = stato.leggi('prezzi_in_sospeso.json', [])
    print(f"Prezzi in sospeso (non ancora in Supabase): {len(in_sospeso)}"
          + (f", dal {min((riga['ts'] for riga in in_sospeso), key=datetime.fromisoformat)}"
             if in_sospeso else ''))
    print(f"Ultimi lavori del mattino: {stato.leggi('mattino.json', {}).get('giorno', 'mai')}")
    print(f"Titoli con lo storico Yahoo completo: {len(stato.leggi('storico_completo.json', []))}")
    titoli = stato.leggi('titoli.json', [])
    # Le ore come date: quelle di Supabase sono in UTC, quelle del monitor con il fuso di Roma
    ultimo = max((t['ultimo_ts'] for t in titoli if t.get('ultimo_ts')),
                 key=datetime.fromisoformat, default='nessuno')
    print(f"Titoli nell'ultima lista salvata: {len(titoli)}, ultimo prezzo: {ultimo}")


def main():
    parser = argparse.ArgumentParser(description='ISIN Monitor - Monitoraggio prezzi e notifiche')
    parser.add_argument('--monitor', action='store_true',
                        help='Un giro ogni 15 secondi fino alla chiusura (lo usa systemd)')
    parser.add_argument('--giro', action='store_true',
                        help='Un giro solo su tutti i titoli, avvisi compresi (per le prove)')
    parser.add_argument('--check-once', action='store_true',
                        help='Test: controlla il primo titolo con soglia 0 (manda sempre l\'avviso)')
    parser.add_argument('--test-telegram', action='store_true',
                        help='Manda un messaggio di prova su Telegram')
    parser.add_argument('--telegram', action='store_true',
                        help='Stato del bot (nome, webhook, errori), senza mandare messaggi')
    parser.add_argument('--togli-webhook', action='store_true',
                        help='Con --telegram: toglie il webhook del bot (serve per i comandi)')
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
    parser.add_argument('--stato', action='store_true',
                        help='Stato locale: monitor acceso, prezzi in sospeso, ultimo mattino')
    parser.add_argument('--with-profiling', action='store_true',
                        help='Abilita il profiling delle funzioni')
    args = parser.parse_args()

    if args.stato:
        mostra_stato()
        return

    config = carica_config()
    builtins.ENABLE_PROFILING = args.with_profiling
    # Nel journal di systemd ogni riga subito, non a blocchi
    sys.stdout.reconfigure(line_buffering=True)
    controllo = args.monitor or args.giro or args.check_once

    if controllo:
        adesso = datetime.now()
        print(f"🚀 [{adesso:%Y-%m-%d %H:%M:%S}] Controllo ISIN "
              f"(orario: {descrizione_orario(config['monitoring'])})")
        if not args.ignora_orario and not in_orario(config['monitoring'], adesso):
            print(f"⏰ Fuori orario di mercato ({adesso:%a %H:%M}): controllo saltato")
            return
        if not args.ignora_orario and borsa_chiusa(config['monitoring'], adesso):
            print(f"🏖️ Borsa Italiana chiusa oggi ({festivo(adesso.date())}): niente giri")
            if args.monitor:
                aspetta_la_chiusura(config['monitoring'])
            return
    elif not (args.test_telegram or args.telegram or args.grafico or args.riempi_storico):
        parser.print_help()
        return

    if args.monitor or args.giro:
        # Un monitor alla volta: due insieme raddoppierebbero le richieste a Borsa Italiana (429)
        lock = stato.blocca('monitor.lock')
        if lock is None:
            print("⏭️ Un altro monitor sta già girando (il servizio systemd?): esco")
            return

    from core.app import ISINMonitor
    monitor = ISINMonitor(config)

    if args.test_telegram:
        monitor.test_telegram()
    elif args.telegram:
        monitor.stato_telegram(togli_webhook=args.togli_webhook)
    elif args.grafico:
        monitor.salva_grafico(args.grafico, args.uscita)
    elif args.riempi_storico:
        monitor.riempi_storico(scrivi=not args.prova)
    elif args.check_once or config.get('test'):
        monitor.run_test()
        if args.monitor:
            aspetta_la_chiusura(config['monitoring'])
    elif args.giro:
        monitor.controlla_tutti()
    else:
        monitor.monitora(ignora_orario=args.ignora_orario)

    if args.with_profiling:
        from core.profiling_analysis import main as profile_analyser_main
        profile_analyser_main()


if __name__ == "__main__":
    main()
