#!/usr/bin/env python3
"""
Comandi del bot Telegram, mentre il monitor è acceso (in orario di borsa).

Il bot risponde solo alla chat di config.json (chat_id):
  /prezzi          tutti i titoli, con la variazione dalla chiusura precedente
  /grafico eni     il grafico di un titolo (nome, simbolo o ISIN)
  /stato           come sta il monitor
  /aiuto           l'elenco dei comandi

Legge i messaggi con getUpdates (long polling) in un thread a parte. I grafici passano
dalla coda degli avvisi, così li disegna sempre lo stesso thread (matplotlib non ama i
thread). I comandi mandati a monitor spento (fuori orario) non si eseguono dopo.
"""

import json
import time
from datetime import datetime, timedelta
from html import escape
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from . import stato
from .database import ErroreDatabase
from .message_templates import decimali
from .orario import descrizione_orario

ROMA = ZoneInfo('Europe/Rome')
COMANDI = [
    ('prezzi', 'Tutti i titoli: prezzo e variazione da ieri'),
    ('grafico', 'Il grafico di un titolo, es. /grafico eni'),
    ('stato', 'Come sta il monitor'),
    ('aiuto', 'I comandi del bot'),
]
# Un comando più vecchio di così (mandato a monitor spento) non si esegue
MAX_ETA_COMANDO = 120
# Parti del nome che sul telefono non servono
SUFFISSI = (' S.p.A.', ' SpA', ' N.V.', ' SA', ', Inc.', ' Inc.', ' Corporation', ' Technologies')


def nome_breve(titolo: Dict, lunghezza: int = 14) -> str:
    """Il nome senza S.p.A., Inc. e simili, al massimo `lunghezza` caratteri."""
    nome = titolo.get('nome') or titolo['isin']
    for suffisso in SUFFISSI:
        nome = nome.replace(suffisso, '')
    return nome if len(nome) <= lunghezza else nome[:lunghezza - 1] + '…'


def trova_titoli(titoli: List[Dict], testo: str) -> List[Dict]:
    """I titoli che corrispondono a `testo`: ISIN o simbolo esatti, altrimenti parte del nome."""
    cercato = testo.strip().upper()
    if not cercato:
        return []
    for titolo in titoli:
        simboli = {titolo['isin'], titolo.get('simbolo_borsa') or '', titolo.get('simbolo') or ''}
        simboli |= {simbolo.split('.')[0] for simbolo in simboli}   # ENI.MI anche come ENI
        if cercato in simboli:
            return [titolo]
    return [titolo for titolo in titoli if cercato in (titolo.get('nome') or '').upper()]


def chiusura_precedente(db, isin: str, oggi: datetime) -> Optional[float]:
    """L'ultimo prezzo di un giorno prima di oggi (di solito la chiusura di ieri)."""
    mezzanotte = oggi.replace(hour=0, minute=0, second=0, microsecond=0)
    giorni = [riga for riga in db.serie(isin, mezzanotte - timedelta(days=10), '1 day')
              if datetime.fromisoformat(riga['ts']) < mezzanotte]
    return float(giorni[-1]['prezzo']) if giorni else None


def testo_prezzi(db, titoli: List[Dict], adesso: datetime, intestazione: str = '') -> str:
    """Tutti i titoli con l'ultimo prezzo e la variazione dalla chiusura precedente,
    dal migliore al peggiore. `intestazione` sostituisce "Prezzi alle HH:MM"."""
    righe = []
    for titolo in titoli:
        prezzo = titolo.get('ultimo_prezzo')
        if prezzo is None:
            continue
        variazione = None
        try:
            chiusura = chiusura_precedente(db, titolo['isin'], adesso) if db else None
            if chiusura:
                variazione = (prezzo / chiusura - 1) * 100
        except (ErroreDatabase, ValueError):
            pass
        righe.append((nome_breve(titolo), f"€{prezzo:.{decimali(prezzo)}f}", variazione))
    if not righe:
        return "📊 Nessun prezzo ancora: la borsa apre alle 9"
    righe.sort(key=lambda riga: -999 if riga[2] is None else riga[2], reverse=True)
    nome = max(len(riga[0]) for riga in righe)
    prezzo = max(len(riga[1]) for riga in righe)
    testo = []
    for nome_titolo, prezzo_titolo, variazione in righe:
        if variazione is None:
            fine = '     —'
        else:
            fine = f"{variazione:+6.2f}% " + ('📈' if variazione > 0 else '📉' if variazione < 0 else '⚪')
        # Prima si allinea, poi l'HTML (& diventa &amp; e sposterebbe le colonne)
        testo.append(escape(f"{nome_titolo:<{nome}} {prezzo_titolo:>{prezzo}} ") + fine)
    return (f"📊 <b>{intestazione or f'Prezzi alle {adesso:%H:%M}'}</b> (variazione da ieri)\n\n<code>"
            + '\n'.join(testo) + "</code>")


def testo_stato(monitor) -> str:
    """Come sta il monitor: da quando gira, l'ultimo giro, Supabase, avvisi di oggi."""
    righe = ["🟢 <b>ISIN Monitor acceso</b>"
             + (f" dalle {monitor.avviato:%H:%M}" if monitor.avviato else '')]
    if monitor.ultimo_giro:
        ora, letti, totale = monitor.ultimo_giro
        righe.append(f"Ultimo giro alle {ora:%H:%M:%S}: {letti}/{totale} prezzi letti")
    righe.append(f"Giri fatti: {monitor.giri_fatti}, avvisi mandati: {monitor.avvisi_di_oggi}")
    in_sospeso = len(stato.leggi('prezzi_in_sospeso.json', []))
    righe.append("Supabase: " + ("ok" if monitor.online else "non risponde")
                 + (f", {in_sospeso} prezzi in sospeso" if in_sospeso else ''))
    righe.append(f"Orario: {descrizione_orario(monitor.config['monitoring'])}")
    return '\n'.join(righe)


def testo_aiuto() -> str:
    righe = ["🤖 <b>Comandi di ISIN Monitor</b> (quando il monitor è acceso, in orario di borsa)", '']
    righe += [f"/{comando} – {descrizione}" for comando, descrizione in COMANDI]
    return '\n'.join(righe)


def rispondi(monitor, coda, testo: str) -> None:
    """Esegue un comando ricevuto (testo del messaggio) e risponde nella chat."""
    parole = testo.strip().split(maxsplit=1)
    if not parole or not parole[0].startswith('/'):
        return
    comando = parole[0][1:].split('@')[0].lower()   # /grafico@nome_del_bot nei gruppi
    argomento = parole[1] if len(parole) > 1 else ''
    print(f"💬 Comando /{comando} {argomento}".rstrip())
    titoli = stato.leggi('titoli.json', [])
    adesso = datetime.now(ROMA).replace(microsecond=0)

    if comando == 'prezzi':
        monitor.send_telegram_message(testo_prezzi(monitor.db, titoli, adesso), anteprima=False)
    elif comando == 'grafico':
        trovati = trova_titoli(titoli, argomento)
        if len(trovati) == 1 and trovati[0].get('ultimo_prezzo') is not None:
            titolo = trovati[0]
            # Dalla coda degli avvisi: il grafico lo disegna il thread degli avvisi
            coda.put({'titolo': dict(titolo), 'prezzo': titolo['ultimo_prezzo'],
                      'precedente': None, 'adesso': adesso})
        elif len(trovati) == 1:
            monitor.send_telegram_message(f"Nessun prezzo ancora per {escape(trovati[0]['nome'])}")
        elif trovati:
            nomi = ', '.join(escape(nome_breve(titolo)) for titolo in trovati)
            monitor.send_telegram_message(f"Più titoli per «{escape(argomento)}»: {nomi}. Scrivi di più.")
        else:
            esempio = escape(nome_breve(titoli[0]).split()[0].lower()) if titoli else 'eni'
            monitor.send_telegram_message(
                f"Nessun titolo per «{escape(argomento)}». Scrivi nome, simbolo o ISIN, "
                f"es. /grafico {esempio}")
    elif comando == 'stato':
        monitor.send_telegram_message(testo_stato(monitor))
    else:
        monitor.send_telegram_message(testo_aiuto())


def gestisci(monitor, coda, aggiornamenti: List[Dict], avvio: float) -> Optional[int]:
    """Esegue i comandi di un blocco di getUpdates; restituisce il prossimo offset."""
    offset = None
    chat = str(monitor.config['telegram'].get('chat_id'))
    for aggiornamento in aggiornamenti:
        offset = aggiornamento['update_id'] + 1
        messaggio = aggiornamento.get('message') or {}
        if str(messaggio.get('chat', {}).get('id')) != chat:
            continue   # solo la chat di Andrea
        if messaggio.get('date', 0) < avvio - MAX_ETA_COMANDO:
            continue   # mandato a monitor spento
        try:
            rispondi(monitor, coda, messaggio.get('text') or '')
        except Exception as errore:
            print(f"ERRORE: Comando non eseguito: {errore.__class__.__name__}: {errore}")
    return offset


def consiglio(errore: str) -> str:
    """Cosa fare per i due errori di getUpdates che capitano davvero (409 di Telegram)."""
    if 'webhook' in errore:
        return ("; il bot ha un webhook (lo usa un altro programma?): ./setup.sh telegram lo "
                "mostra, ./setup.sh telegram togli-webhook lo toglie")
    if 'other getUpdates' in errore:
        return ("; un altro programma legge i messaggi con lo stesso bot (un altro ISIN Monitor, "
                "su un altro PC?): va fermato, un bot si legge da un posto solo")
    return ''


def ascolta(monitor, coda) -> None:
    """Thread dei comandi: legge i messaggi del bot finché il monitor è acceso."""
    avvio = time.time()
    # Il menu dei comandi nell'app di Telegram (il pulsante accanto al campo di testo)
    monitor.chiama_telegram('setMyCommands', silenzioso=True, data={'commands': json.dumps(
        [{'command': comando, 'description': descrizione} for comando, descrizione in COMANDI])})
    offset = None
    errore = ''   # l'errore già scritto nel log: si riscrive solo se cambia
    while True:
        aggiornamenti = monitor.chiama_telegram(
            'getUpdates', timeout=40, silenzioso=True,
            data={'timeout': 30, 'offset': offset, 'allowed_updates': json.dumps(['message'])})
        if aggiornamenti is None:
            if monitor.errore_telegram != errore:
                errore = monitor.errore_telegram
                print(f"⚠️ Comandi del bot non attivi, Telegram dice: {errore}. "
                      f"Riprovo ogni 30 secondi{consiglio(errore)}")
            time.sleep(30)
            continue
        if errore:
            print("✅ Comandi del bot di nuovo attivi")
            errore = ''
        offset = gestisci(monitor, coda, aggiornamenti, avvio) or offset
