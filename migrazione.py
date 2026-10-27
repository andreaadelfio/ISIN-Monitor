#!/usr/bin/env python3
"""
Migrazione una tantum dei dati locali di ISIN Monitor nel database di MyFinance.

    python3 migrazione.py cambia-isin VECCHIO NUOVO [--scrivi]   # ISIN sbagliato in watchlist
    python3 migrazione.py titoli              # prova: cosa cambierebbe nella watchlist
    python3 migrazione.py titoli --scrivi     # aggiunge i titoli mancanti, simbolo_borsa e soglia
    python3 migrazione.py storico             # prova: righe per titolo dello storico locale
    python3 migrazione.py storico --scrivi    # copia lo storico in prezzi (fonte 'borsa')

Senza --scrivi non cambia niente. Rieseguirla è innocuo: i prezzi già presenti
(stesso isin e ora) restano come sono. Prima "titoli", poi "storico": lo storico
locale ha solo i ticker (es. 1AMZN.MI), che diventano ISIN tramite simbolo_borsa.

Un titolo del CSV con un ISIN che non è nella watchlist, ma con un ticker già usato
da un altro ISIN della watchlist, non si tocca: va deciso a mano quale ISIN è giusto,
e se è quello del CSV si corregge con cambia-isin (es. Telecom Italia:
cambia-isin IT0003497168 IT0005712671), poi si rilancia "titoli".
"""

import argparse
import json
import sys

import pandas as pd

from core.database import Database, ErroreDatabase
from core.price_providers import BorsaItalianaProvider


def connetti() -> Database:
    with open('config.json', encoding='utf-8') as file:
        config = json.load(file)
    db = Database.da_configurazione(config)
    if db is None:
        sys.exit(1)
    return db


def migra_titoli(db: Database, percorso_csv: str, scrivi: bool) -> None:
    csv = pd.read_csv(percorso_csv)
    watchlist = {riga['isin']: riga for riga in db.titoli()}
    da_decidere = []

    for riga in csv.itertuples(index=False):
        ticker, isin, soglia = riga.ticker, riga.isin, float(riga.target_discount)
        titolo = watchlist.get(isin)
        if titolo:
            campi = {}
            if titolo.get('simbolo_borsa') != ticker:
                campi['simbolo_borsa'] = ticker
            if titolo.get('soglia_avviso') is None or float(titolo['soglia_avviso']) != soglia:
                campi['soglia_avviso'] = soglia
            if campi:
                print(f"✏️  {ticker:9} {isin}: {campi}")
                if scrivi:
                    db.aggiorna_titolo(isin, campi)
            else:
                print(f"✔️  {ticker:9} {isin}: già a posto")
            continue

        altri = [t['isin'] for t in watchlist.values() if ticker in (t.get('simbolo'), t.get('simbolo_borsa'))]
        if altri:
            da_decidere.append(f"{ticker}: nel CSV è {isin}, nella watchlist {', '.join(altri)}")
            print(f"⚠️  {ticker:9} {isin}: DA DECIDERE (nella watchlist c'è {', '.join(altri)})")
            continue

        nome = BorsaItalianaProvider().get_price(isin)[1]
        print(f"➕ {ticker:9} {isin}: nuovo nella watchlist ({nome or 'nome sconosciuto'})")
        if scrivi:
            db.aggiungi_titoli([{'isin': isin, 'simbolo': ticker, 'simbolo_borsa': ticker,
                                 'nome': nome, 'soglia_avviso': soglia}])

    if da_decidere:
        print("\nDa decidere a mano (non toccati):")
        for riga in da_decidere:
            print(f"  - {riga}")
    if not scrivi:
        print("\nProva: niente è stato scritto (aggiungi --scrivi)")


def cambia_isin(db: Database, vecchio: str, nuovo: str, scrivi: bool) -> None:
    """Corregge l'ISIN di un titolo della watchlist (solo se non ha ancora prezzi salvati)."""
    titoli = {riga['isin']: riga for riga in db.titoli()}
    if vecchio not in titoli:
        sys.exit(f"❌ {vecchio} non è nella watchlist")
    if nuovo in titoli:
        sys.exit(f"❌ {nuovo} è già nella watchlist")
    prezzi = db.conta_prezzi(vecchio)
    if prezzi:
        # prezzi.isin punta alla watchlist senza "on update cascade": prima andrebbero spostati
        sys.exit(f"❌ {vecchio} ha già {prezzi} prezzi salvati: ISIN non cambiato")
    print(f"✏️  {titoli[vecchio].get('nome')} ({titoli[vecchio].get('simbolo')}): {vecchio} → {nuovo}")
    if scrivi:
        db.aggiorna_titolo(vecchio, {'isin': nuovo})
        print("✅ ISIN cambiato")
    else:
        print("Prova: niente è stato scritto (aggiungi --scrivi)")


def migra_storico(db: Database, percorso: str, scrivi: bool) -> None:
    storico = pd.read_pickle(percorso)
    # Solo simbolo_borsa (scritto da "titoli"): un ticker con l'ISIN da decidere resta fuori
    mappa = {titolo['simbolo_borsa']: titolo['isin'] for titolo in db.titoli() if titolo.get('simbolo_borsa')}

    totale = scritte = 0
    for ticker, gruppo in storico.groupby('ticker', observed=True):
        isin = mappa.get(ticker)
        # Ora locale di Roma senza fuso; le ore doppie o saltate del cambio d'ora si scartano
        ts = pd.to_datetime(gruppo['timestamp']).dt.tz_localize(
            'Europe/Rome', ambiguous='NaT', nonexistent='NaT')
        validi = ts.notna() & (gruppo['price'] > 0)
        punti = list(zip(ts[validi], gruppo['price'][validi]))
        totale += len(punti)
        intervallo = f"dal {ts.min():%d/%m/%Y} al {ts.max():%d/%m/%Y}"
        if not isin:
            print(f"⚠️  {ticker:9} {'-':12} {len(punti):7} righe {intervallo}: "
                  f"ticker non nella watchlist (simbolo_borsa), salto")
            continue
        prima = db.conta_prezzi(isin, 'borsa')
        if scrivi:
            db.scrivi_prezzi([
                {'isin': isin, 'ts': t.isoformat(), 'prezzo': round(float(p), 4), 'fonte': 'borsa'}
                for t, p in punti
            ])
            dopo = db.conta_prezzi(isin, 'borsa')
            scritte += dopo - prima
            print(f"✅ {ticker:9} {isin} {len(punti):7} righe {intervallo}: "
                  f"nel database {prima} → {dopo} prezzi 'borsa'")
        else:
            print(f"🔎 {ticker:9} {isin} {len(punti):7} righe {intervallo} "
                  f"(nel database ora {prima} prezzi 'borsa')")

    print(f"\nTotale storico locale: {totale} righe valide su {len(storico)}")
    if scrivi:
        print(f"Aggiunte al database: {scritte}")
    else:
        print("Prova: niente è stato scritto (aggiungi --scrivi)")


def main():
    parser = argparse.ArgumentParser(description='Migrazione dei dati locali in Supabase')
    parser.add_argument('cosa', choices=['titoli', 'storico', 'cambia-isin'])
    parser.add_argument('isin', nargs='*', help='Con cambia-isin: VECCHIO NUOVO')
    parser.add_argument('--scrivi', action='store_true', help='Scrive davvero (senza è una prova)')
    parser.add_argument('--csv', default='isin_metadata.csv')
    parser.add_argument('--file', default='price_history_long.pk.zst')
    args = parser.parse_args()

    db = connetti()
    try:
        if args.cosa == 'cambia-isin':
            if len(args.isin) != 2:
                parser.error('cambia-isin vuole due ISIN: VECCHIO NUOVO')
            cambia_isin(db, args.isin[0], args.isin[1], args.scrivi)
        elif args.cosa == 'titoli':
            migra_titoli(db, args.csv, args.scrivi)
        else:
            migra_storico(db, args.file, args.scrivi)
    except ErroreDatabase as errore:
        sys.exit(f"❌ {errore}")


if __name__ == '__main__':
    main()
