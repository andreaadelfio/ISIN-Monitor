# ISIN Monitor

Segue i titoli della watchlist di MyFinance durante l'orario di borsa: ogni 15 secondi
legge i prezzi su Borsa Italiana, li salva nel database Supabase di MyFinance e manda un
avviso su Telegram (grafico, tabella e link alla scheda in MyFinance) quando un prezzo si
muove almeno della soglia del titolo rispetto al prezzo salvato prima.

In orario di mercato è un processo solo, sempre acceso (lo avvia il timer systemd alle
08:55 ed esce da solo alle 18:05), con tre attività separate:

- **giri dei prezzi**, ogni 15 secondi esatti (:00, :15, :30, :45): le richieste a Borsa
  Italiana sono distribuite nei 15 secondi, una ogni 0,7 secondi circa con 17 titoli,
  perché Borsa Italiana risponde **429** (troppe richieste) alle raffiche. Dopo un 429 il
  giro si interrompe e il monitor fa una pausa di 60 secondi;
- **avvisi**: passano da una coda a un thread che disegna il grafico e lo manda su
  Telegram, così un grafico o un invio lento non fanno saltare i giri;
- **lavori del mattino** (Yahoo e proposte), in un altro thread al primo giro del giorno.

Ogni mattina, al primo avvio, riempie con Yahoo Finance i buchi dello storico (giorni a
PC spento) e manda su Telegram i cambiamenti delle proposte di MyFinance.

## Come funziona

- **Titoli**: la tabella `watchlist` di MyFinance (si aggiungono e tolgono dal sito, nella
  sezione ISIN Monitor). Per ISIN Monitor contano `isin`, `nome`, `simbolo_borsa` (il
  titolo quotato a Milano su Yahoo, in euro, es. `1AMZN.MI`, `ENI.MI`) e `soglia_avviso`
  (variazione in % fra due prezzi che fa scattare un avviso, di solito 0,5). L'ultima lista
  è salvata anche in `~/.local/state/isin-monitor/titoli.json`: se Supabase non risponde,
  il monitor continua con quella.
- **Prezzi**: Borsa Italiana, scheda del titolo per ISIN (dopo la prima lettura il monitor
  ricorda l'indirizzo finale della pagina, così ogni titolo costa una richiesta sola). Un
  prezzo si salva solo se è cambiato; tutti i prezzi nuovi di un giro vanno nel database
  con una sola scrittura
  (tabella `prezzi`, fonte `borsa`). Se Supabase non risponde restano in
  `~/.local/state/isin-monitor/prezzi_in_sospeso.json` e partono al giro dopo. Titoli
  poco scambiati a Milano (BNP, i titoli americani prima dell'apertura di New York) hanno
  pochi punti al giorno: il prezzo cambia solo quando c'è un contratto.
- **Avvisi**: variazione rispetto all'ultimo prezzo salvato ≥ `soglia_avviso` (in su o in
  giù). Non c'è pausa fra un avviso e l'altro: è voluto. L'avviso ha i link a Fineco,
  Borsa Italiana e alla scheda in MyFinance (`<myfinance_url>/?isin=<ISIN>`).
- **Grafici**: solo da Supabase, quattro richieste per avviso. In alto 360 giorni
  (una chiusura al giorno, date ogni 15 giorni), 30 e 7 giorni (un prezzo ogni 15 minuti,
  una linea per seduta su fondo grigio, senza notti e weekend); in basso Oggi (tutti i
  prezzi di Borsa Italiana di oggi, con i punti verdi sopra l'apertura e rossi sotto) e la
  tabella con apertura, chiusure di 1, 7, 30 e 360 giorni fa, massimo e minimo dell'anno
  (prezzi in centesimi, variazioni fino alla prima cifra decimale significativa). Il punto
  rosso è il prezzo attuale. Ogni periodo ha il suo colore anche dentro i pannelli più
  lunghi (blu 360 giorni, verde acqua 30, arancio 7, viola oggi) e la legenda di ogni
  pannello ne dà la variazione. Nel pannello annuale anche le righe del massimo e del
  minimo. In alto a destra il segnale e il punteggio dell'analisi di MyFinance (che usa le
  medie mobili a 50 e 200 giorni per il trend), coi colori del sito.
- **Le tue posizioni**: dal registro `investimenti` di MyFinance. Se hai il titolo, una riga
  punteggiata scura segna il prezzo di carico (calcolato come nel sito: ABP del conto, o
  costo diviso quote), la tabella ha la riga "Carico" e il messaggio il guadagno o la
  perdita su tutte le quote; se il carico è lontano dai prezzi di un pannello la legenda
  dice "sopra" o "sotto". Acquisti (▲) e vendite (▼) sono triangoli nei pannelli in alto;
  il prezzo di vendita è il Rimborso più la Cedola dello stesso giorno.
- **Proposte**: l'analisi serale di MyFinance assegna a ogni titolo un segnale (Compra, Da
  valutare, Attendi, Evita per ora) e un punteggio. Al primo avvio del mattino, se un
  segnale o la proposta del giorno (il "Compra" con il punteggio più alto) sono cambiati,
  arriva un solo messaggio con i cambiamenti e i link. L'ultimo stato mandato è in
  `~/.local/state/isin-monitor/proposte.json` (la prima volta si salva senza messaggio).

## Dati in Supabase

Lo schema è in `MyFinance/supabase/schema.sql` (si applica dall'editor SQL di Supabase):

- `watchlist`: i titoli, con le colonne `simbolo_borsa` e `soglia_avviso`;
- `prezzi`: `isin`, `ts`, `prezzo`, `fonte` (`borsa` o `yahoo`). Al minuto per 60 giorni;
  più vecchio resta una chiusura al giorno (`sfoltisci_prezzi`, ogni notte con pg_cron);
- `serie_prezzi(isin, da, passo)`: lo storico già sfoltito, usato dai grafici.

Si accede solo con la chiave **secret** (`sb_secret_...`): il monitor la legge dalla
variabile `SUPABASE_SECRET_KEY` o dal file `~/.config/isin-monitor/supabase.env`. La
chiave non va mai in `config.json`, nel repository o nei log.

## Installazione

1. Dipendenze (Anaconda le ha già): `pip install -r requirements.txt`.
2. `cp config.example.json config.json` e inserisci token e chat id del bot Telegram.
3. Servizio e timer systemd (anche senza `sudo` davanti: la password la chiede lo script;
   in tutti e due i casi il servizio gira come il tuo utente, con il tuo python3):

   ```bash
   sudo ./setup.sh install
   ```

   La prima volta crea `~/.config/isin-monitor/supabase.env` (permessi 600): scrivici la
   chiave dopo `SUPABASE_SECRET_KEY=` e rilancia `./setup.sh restart`.

Il timer scatta solo in orario di mercato, ogni 15 secondi: se il monitor non sta già
girando lo avvia (all'apertura, dopo una sospensione del PC o se si è fermato), altrimenti
non fa niente. Gli `OnCalendar` sono generati
da `market_open_time`/`market_close_time` di `config.json` (con 08:55-18:05:
`Mon..Fri 08:55..59:00/15`, `Mon..Fri 09..17:*:00/15`, `Mon..Fri 18:00..05:00/15`). Se
cambi gli orari, rilancia `./setup.sh install`. Lanciato a mano fuori orario,
`monitor.py` esce subito, prima di caricare pandas e matplotlib.

## Comandi

```bash
./setup.sh status                     # stato del timer e prossimi avvii
./setup.sh logs                       # log in tempo reale
./setup.sh restart | stop | start
./setup.sh test                       # primo titolo con soglia 0: manda sempre un avviso
./setup.sh grafico IT0003132476 eni.png   # salva il grafico di un titolo, senza Telegram
./setup.sh riempi-storico --prova     # quanti punti Yahoo mancano (senza scrivere)
./setup.sh riempi-storico             # li scrive
python3 monitor.py --test-telegram    # messaggio di prova
python3 monitor.py --giro --ignora-orario      # un giro solo, anche fuori orario
```

## Configurazione (`config.json`)

| Chiave | Significato |
| --- | --- |
| `myfinance_url` | indirizzo del sito, per i link `?isin=<ISIN>` |
| `telegram.bot_token`, `chat_id` | bot e chat degli avvisi |
| `telegram.enabled`, `send_charts` | avvisi attivi; grafico o solo testo |
| `monitoring.market_hours_only`, `weekdays_only` | solo in orario di borsa, solo lun-ven |
| `monitoring.market_open_time`, `market_close_time` | orario (anche del timer systemd) |
| `monitoring.price_comparison_days` | i tre periodi dei grafici in alto (1 è ignorato) |
| `monitoring.historical_table_days` | le chiusure nella tabella |
| `api.request_timeout` | timeout delle richieste |
| `yahoo.enabled`, `timeout`, `max_retries` | riempimento dei buchi con Yahoo |
| `supabase.url` | progetto Supabase di MyFinance |
| `test` | `true`: `--monitor` fa il test del primo titolo |

## Storico con Yahoo

Borsa Italiana resta la fonte degli avvisi; Yahoo serve solo a riempire i buchi, mai al
momento di un avviso. Un buco è un intervallo di 5 minuti (un giorno, per le chiusure)
senza nessun prezzo nel database: lì si aggiungono i punti di Yahoo con fonte `yahoo`,
mai per oggi.

- Una tantum (`./setup.sh riempi-storico`): ultimi 7 giorni al minuto, fino a 60 giorni ai
  5 minuti, l'anno prima una chiusura al giorno (salvata alle 17:30).
- Ogni mattina, al primo avvio: gli ultimi 7 giorni al minuto (ai 5 minuti se Yahoo non ha
  il minuto, come per i titoli americani quotati a Milano); per un titolo appena aggiunto
  senza nessun prezzo, il riempimento completo.

Yahoo usa `simbolo_borsa`; senza, il `simbolo` solo se il titolo è quotato in euro (i
prezzi in dollari rovinerebbero lo storico).

## Migrazione dallo storico locale (una tantum)

Prima di Supabase titoli e storico stavano in `isin_metadata.csv` e
`price_history_long.pk.zst`. `migrazione.py` li copia nel database; senza `--scrivi` è
solo una prova, e rieseguirlo non crea doppioni:

```bash
python3 migrazione.py titoli            # cosa cambierebbe nella watchlist
python3 migrazione.py titoli --scrivi   # titoli mancanti, simbolo_borsa e soglia dal CSV
python3 migrazione.py storico           # righe per titolo
python3 migrazione.py storico --scrivi  # copia nei prezzi (fonte borsa) e riconta
```

Un titolo del CSV con un ISIN diverso da quello della watchlist per lo stesso ticker non
viene toccato e va deciso a mano. Se è giusto quello del CSV (come per Telecom Italia), si
corregge la watchlist prima di "titoli", finché il titolo non ha prezzi salvati:

```bash
python3 migrazione.py cambia-isin IT0003497168 IT0005712671 --scrivi
```

## Sviluppo e test

```bash
python3 -m pytest tests                 # test con database, Borsa e Telegram finti
```

`dev/supabase_locale.py` avvia un finto Supabase locale (Postgres + PostgREST, con le
tabelle di `schema.sql`) per provare tutto senza toccare il database vero; le istruzioni
sono in cima al file.

Struttura:

```
monitor.py            punto d'ingresso (controllo d'orario, poi core/app.py)
migrazione.py         migrazione una tantum di CSV e storico locale
setup.sh              servizio e timer systemd
core/app.py           i giri ogni 15 secondi, coda degli avvisi, lavori del mattino
core/database.py      Supabase (watchlist, prezzi, serie_prezzi, investimenti)
core/price_providers.py  Borsa Italiana e Yahoo
core/storico.py       riempimento dei buchi con Yahoo
core/chart_generator.py  grafici
core/proposte.py      cambiamenti delle proposte di MyFinance
core/posizioni.py     prezzo di carico, acquisti e vendite dal registro investimenti
core/orario.py        orario di mercato e OnCalendar del timer
core/stato.py         file di stato in ~/.local/state/isin-monitor
core/message_templates.py, core/utils.py   testo e tabella degli avvisi
tests/                test (pytest)
```

## Problemi frequenti

- **"Chiave Supabase mancante"**: manca `SUPABASE_SECRET_KEY` in
  `~/.config/isin-monitor/supabase.env` (o il servizio non ha `EnvironmentFile=`: rilancia
  `./setup.sh install`).
- **"Uso l'ultima lista salvata"**: Supabase non risponde; i prezzi aspettano in locale e
  partono appena torna. Un `401` vuol dire chiave sbagliata o revocata.
- **"Nessun prezzo per ..."**: Borsa Italiana non ha la scheda di quell'ISIN (titolo non
  quotato a Milano o ISIN cambiato): correggi l'ISIN dal sito.
- **"Borsa Italiana: troppe richieste (429)"**: Borsa Italiana limita le richieste; il
  monitor fa una pausa di 60 secondi e riprende. Non lanciare altri `--giro` o prove mentre
  il servizio gira: le richieste si sommano.
- **Nessun avviso**: guarda `./setup.sh logs`; fuori orario il timer non parte;
  `./setup.sh test` prova Telegram con un avviso vero.
- **Grafici vuoti o con buchi**: `./setup.sh riempi-storico --prova` dice quanti punti
  mancano; un titolo senza `simbolo_borsa` non viene riempito da Yahoo.
- **Timer che non parte**: `./setup.sh status` mostra i prossimi avvii; dopo aver cambiato
  gli orari serve `./setup.sh install`.
