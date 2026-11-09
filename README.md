# ISIN Monitor

Segue i titoli della watchlist di MyFinance durante l'orario di borsa: ogni 15 secondi
legge i prezzi su Borsa Italiana, li salva nel database Supabase di MyFinance e manda un
avviso su Telegram (grafico, tabella e link alla scheda in MyFinance) quando un prezzo si
muove almeno della soglia del titolo rispetto al prezzo salvato prima.

In orario di mercato è un processo solo, sempre acceso (lo avvia il timer systemd alle
08:55 ed esce da solo alle 18:05), con tre attività separate:

- **giri dei prezzi**, ogni 15 secondi esatti (:00, :15, :30, :45): le richieste a Borsa
  Italiana sono distribuite nei 15 secondi, una ogni 0,7 secondi circa con 17 titoli
  (dopo una risposta lenta recuperano a 0,35 secondi l'una dall'altra, così il giro resta
  nei 15 secondi), perché Borsa Italiana risponde **429** (troppe richieste) alle raffiche. Dopo un 429 il
  giro si interrompe e il monitor fa una pausa di 60 secondi. Si interrompe anche se due
  titoli di fila non hanno risposta (rete giù), invece di aspettare un timeout per titolo;
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
- **Prezzi**: Borsa Italiana, scheda del titolo per ISIN (azioni italiane ed estere, ETF
  e BTP; dopo la prima lettura il monitor ricorda l'indirizzo finale della pagina, così
  ogni titolo costa una richiesta sola; con la rete giù o un errore del server non prova
  altre pagine). Prima dell'apertura (08:55-09:00) la scheda non ha ancora il prezzo: il
  monitor la salta senza errori. Un prezzo si salva solo se è cambiato; tutti i prezzi
  nuovi di un giro vanno nel database con una sola scrittura (tabella `prezzi`, fonte
  `borsa`). Se Supabase non risponde restano in
  `~/.local/state/isin-monitor/prezzi_in_sospeso.json` e partono al giro dopo. Titoli
  poco scambiati a Milano (BNP, i titoli americani prima dell'apertura di New York)
  hanno pochi punti al giorno: il prezzo cambia solo quando c'è un contratto.
- **Avvisi**: variazione rispetto all'ultimo prezzo salvato ≥ `soglia_avviso` (in su o in
  giù). Dopo un avviso, per 3 minuti (`monitoring.cooldown_minuti`) non ne parte un
  altro sullo stesso titolo: un titolo in movimento continua a muoversi e con i giri
  ogni 15 secondi arriverebbero raffiche; il prezzo si salva comunque, gli altri titoli
  non sono bloccati e dopo un riavvio si riparte da zero. Il cooldown vale solo per
  questi avvisi: riepilogo, proposte, risposte ai comandi (anche /grafico) e `./setup.sh
  test` partono sempre. Un salto di più del 20% (spesso un prezzo letto male) si salva e
  si avvisa solo se il giro dopo lo conferma. L'avviso è il grafico con una didascalia
  di due righe: il nome del titolo e i link a Fineco, Borsa Italiana (la scheda letta
  dal monitor) e alla scheda in MyFinance (`<myfinance_url>/?isin=<ISIN>`); prezzo,
  variazioni, segnale e tabella sono nell'immagine. Se il grafico non si crea, o la foto
  non parte nemmeno dopo i nuovi tentativi (dopo 3 e 10 secondi, se la connessione con
  Telegram non parte), arriva un messaggio di testo con tutto: nome, prezzo e variazione
  dall'ultimo prezzo, il segnale di MyFinance, la tabella in colonne corte per il
  telefono (Prima, Apertura, chiusure di 1, 7, 30 e 360 giorni fa, Inizio, Max, Min,
  Carico col guadagno sulle quote) e i link. Lo stesso per /grafico. Un avviso rimasto
  in coda più di 30 minuti (Telegram giù) non si manda più.
  Nel canale resta solo l'ultimo grafico di ogni titolo: quando ne parte uno nuovo
  (anche per /grafico) il precedente si cancella, solo dopo che il nuovo è arrivato. Il
  `message_id` dell'ultimo grafico è in `~/.local/state/isin-monitor/grafici.json`,
  quindi vale anche dopo un riavvio. Telegram cancella solo messaggi di meno di 48 ore e
  solo se il bot, amministratore del canale, ha il permesso di eliminare i messaggi; se
  non riesce il log lo dice una volta. Riepilogo, proposte e messaggi di solo testo
  restano. Per spegnerlo: `telegram.cancella_grafico_precedente: false`.
  I grafici già nel canale si aggiornano da soli ogni 30 minuti
  (`telegram.aggiorna_grafici_minuti`, 0 per spegnerlo) e un'ultima volta alla chiusura:
  l'immagine cambia nello stesso messaggio, senza notifiche né messaggi nuovi. Lo fa il
  thread degli avvisi quando non ha avvisi da mandare, un grafico ogni 3 secondi, quindi
  i giri dei prezzi non rallentano e gli avvisi veri passano avanti. Un titolo col
  prezzo uguale all'ultimo grafico si salta; se il messaggio non c'è più (cancellato a
  mano) il titolo esce da `grafici.json`; gli altri errori vanno nel log una volta per
  tipo.
- **Grafici**: solo da Supabase, quattro richieste per avviso. Immagine verticale per il
  telefono (1200×1800): in alto, a tutta larghezza, Oggi (tutti i prezzi di Borsa
  Italiana di oggi, con i punti verdi sopra l'apertura e rossi sotto); sotto, su due
  colonne, 7 e 30 giorni (un prezzo ogni 15 minuti, una linea per seduta su fondo
  grigio, senza notti e weekend), 360 giorni (una chiusura al giorno) e la tabella con
  apertura, chiusure di 1, 7, 30 e 360 giorni fa, massimo e minimo dell'anno (prezzi in
  centesimi, variazioni fino alla prima cifra decimale significativa). Il punto rosso è
  il prezzo attuale (in Oggi quello verde bordato è l'apertura). Ogni periodo ha il suo
  colore anche dentro i pannelli più lunghi (blu 360 giorni, verde acqua 30, arancio 7,
  viola oggi) e la legenda di ogni pannello ne dà la variazione. Nel pannello annuale
  anche le righe del massimo e del minimo. In alto a destra il segnale e il punteggio
  dell'analisi di MyFinance (che usa le medie mobili a 50 e 200 giorni per il trend),
  coi colori del sito.
- **Le tue posizioni**: dal registro `investimenti` di MyFinance. Se hai il titolo, una riga
  punteggiata scura segna il prezzo di carico (calcolato come nel sito: ABP del conto, o
  costo diviso quote), la tabella ha la riga "Carico" e il messaggio il guadagno o la
  perdita su tutte le quote; se il carico è lontano dai prezzi di un pannello la legenda
  dice "sopra" o "sotto". Acquisti (▲) e vendite (▼) sono triangoli nei pannelli in alto;
  il prezzo di vendita è il Rimborso più la Cedola dello stesso giorno. Per i BTP il carico
  non è ancora giusto: nel registro la quantità è in titoli da 1000 €, Borsa dà il prezzo
  per 100 di nominale.
- **Proposte**: l'analisi serale di MyFinance assegna a ogni titolo un segnale (Compra, Da
  valutare, Attendi, Evita per ora) e un punteggio. Al primo avvio del mattino, se un
  segnale o la proposta del giorno (il "Compra" con il punteggio più alto) sono cambiati,
  arriva un solo messaggio con i cambiamenti (prima i Compra, col pallino del colore del
  segnale e il punteggio) e i link. L'ultimo stato mandato è in
  `~/.local/state/isin-monitor/proposte.json` (la prima volta si salva senza messaggio).
- **Riepilogo della giornata**: alla chiusura (18:05) un messaggio con tutti i titoli,
  l'ultimo prezzo e la variazione da ieri, dal migliore al peggiore
  (`telegram.riepilogo: false` per spegnerlo).

## Comandi del bot Telegram

Mentre il monitor è acceso (in orario di borsa) il bot risponde, solo alla chat di
`config.json`, a questi comandi (in privato e nei gruppi sono anche nel menu accanto al
campo di testo; se la chat è un canale si scrivono a mano nel canale, il bot dev'essere
amministratore, e la risposta arriva nel canale; `chat_id` può essere `@nome` del canale o
il suo id numerico):

| Comando | Risposta |
| --- | --- |
| `/prezzi` | tutti i titoli: ultimo prezzo e variazione da ieri, dal migliore al peggiore |
| `/grafico eni` | il grafico di un titolo (nome, anche in parte, simbolo come `ENI` o `RACE.MI`, o ISIN) |
| `/stato` | da quando gira, l'ultimo giro, giri e avvisi di oggi, Supabase |
| `/aiuto` | l'elenco dei comandi |

I comandi mandati a monitor spento (sera, weekend) non vengono eseguiti dopo. Per
spegnerli: `telegram.comandi: false`.

Il monitor legge i comandi con `getUpdates`, che Telegram rifiuta (errore 409) se il bot ha
un webhook o se un altro programma legge lo stesso bot. Il webhook il monitor non lo toglie
da solo, perché potrebbe servire a un altro programma: lo dice nel log e
`./setup.sh telegram` mostra lo stato del bot (senza mandare messaggi né stampare il
token); `./setup.sh telegram togli-webhook` lo toglie quando lo decidi tu.

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

Nei giorni feriali in cui Borsa Italiana è chiusa (Capodanno, Venerdì Santo, Pasquetta,
1° maggio, 24, 25, 26 e 31 dicembre; vedi `festivo` in `core/orario.py`) il monitor
scrive "Borsa Italiana chiusa oggi" e resta acceso senza fare niente fino alla chiusura,
così il timer non lo rilancia ogni 15 secondi. Le altre feste italiane (6 gennaio,
25 aprile, 2 giugno, Ferragosto, 1° novembre, 8 dicembre) sono giorni di borsa aperta.

## Comandi da terminale

```bash
./setup.sh status                     # stato del timer e prossimi avvii
./setup.sh stato                      # monitor acceso?, prezzi in sospeso, ultimo mattino
./setup.sh telegram                   # stato del bot: nome, webhook, errori (sola lettura)
./setup.sh logs                       # log in tempo reale
./setup.sh restart | stop | start
./setup.sh test                       # primo titolo con soglia 0: manda sempre un avviso
./setup.sh grafico IT0003132476 eni.png   # salva il grafico di un titolo, senza Telegram
./setup.sh riempi-storico --prova     # quanti punti Yahoo mancano (senza scrivere)
./setup.sh riempi-storico             # li scrive
./setup.sh profile                    # come test, con il profiling delle funzioni
python3 monitor.py --test-telegram    # messaggio di prova
python3 monitor.py --giro --ignora-orario      # un giro solo, anche fuori orario
```

## Configurazione (`config.json`)

| Chiave | Significato |
| --- | --- |
| `myfinance_url` | indirizzo del sito, per i link `?isin=<ISIN>` |
| `telegram.bot_token`, `chat_id` | bot e chat degli avvisi |
| `telegram.enabled`, `send_charts` | avvisi attivi; grafico o solo testo |
| `telegram.comandi`, `riepilogo` | comandi del bot; riepilogo alla chiusura (tutti e due attivi se mancano) |
| `telegram.cancella_grafico_precedente` | nel canale solo l'ultimo grafico di ogni titolo (attivo se manca) |
| `telegram.aggiorna_grafici_minuti` | ogni quanto si aggiornano i grafici già nel canale (30 se manca, 0 per spegnerlo) |
| `monitoring.market_hours_only`, `weekdays_only` | solo in orario di borsa, solo lun-ven |
| `monitoring.cooldown_minuti` | minuti fra due avvisi sullo stesso titolo (3 se manca) |
| `monitoring.market_open_time`, `market_close_time` | orario (anche del timer systemd) |
| `monitoring.price_comparison_days` | i tre periodi dei grafici in alto (1 è ignorato) |
| `monitoring.historical_table_days` | le chiusure nella tabella |
| `api.request_timeout` | timeout delle richieste a Supabase e Telegram |
| `api.borsa_timeout` | timeout delle richieste a Borsa Italiana (5 secondi se manca) |
| `yahoo.enabled`, `timeout`, `max_retries` | riempimento dei buchi con Yahoo |
| `supabase.url` | progetto Supabase di MyFinance |
| `test` | `true`: `--monitor` fa il test del primo titolo (un avviso) e poi resta fermo fino alla chiusura |

## Storico con Yahoo

Borsa Italiana resta la fonte degli avvisi; Yahoo serve solo a riempire i buchi, mai al
momento di un avviso. Un buco è un intervallo di 5 minuti (un giorno, per le chiusure)
senza nessun prezzo nel database: lì si aggiungono i punti di Yahoo con fonte `yahoo`,
mai per oggi.

- Una tantum (`./setup.sh riempi-storico`): ultimi 7 giorni al minuto, fino a 60 giorni ai
  5 minuti, l'anno prima una chiusura al giorno (salvata alle 17:30).
- Ogni mattina, al primo avvio: gli ultimi 7 giorni al minuto (ai 5 minuti se Yahoo non ha
  il minuto, come per i titoli americani quotati a Milano). Ogni titolo nuovo (anche
  aggiunto in giornata) o con un `simbolo_borsa` nuovo ha una volta il riempimento
  completo, la mattina dopo; quelli già fatti sono in
  `~/.local/state/isin-monitor/storico_completo.json` (cancellalo per rifarli tutti).
  Dopo più di 6 giorni senza monitor (vacanze, PC spento) il primo mattino fa il
  riempimento completo per tutti i titoli: i 7 giorni al minuto non basterebbero.

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
core/comandi.py       comandi del bot Telegram (/prezzi, /grafico, /stato, /aiuto)
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
  partono appena torna ("Supabase di nuovo raggiungibile"). Finché è giù il messaggio si
  ripete ogni 5 minuti, non a ogni giro (quanti prezzi aspettano: `./setup.sh stato`). Un
  `401` vuol dire chiave sbagliata o revocata.
- **"Nessun prezzo per ..."**: Borsa Italiana non ha la scheda di quell'ISIN (titolo non
  quotato a Milano o ISIN cambiato): correggi l'ISIN dal sito. Finché la scheda non
  c'è, il monitor la richiede ogni 10 minuti invece che a ogni giro.
- **"Borsa Italiana: troppe richieste (429 o 403)"**: Borsa Italiana limita le richieste; il
  monitor fa una pausa di 60 secondi e riprende. Un `--giro` o un secondo `--monitor`
  lanciati mentre il servizio gira escono subito ("Un altro monitor sta già girando"):
  le richieste si sommerebbero. `./setup.sh test` (una richiesta sola) si può usare.
- **"Borsa Italiana non risponde (rete o server): giro interrotto"**: due titoli di fila
  senza risposta; il giro dopo riprova. Se dura, controlla la rete del PC.
- **Giro lento** (`🔍 ... (27.7 s: Borsa 22.1 s (più lenta ... 14.0 s), Supabase 0.4 s)`): un
  giro oltre i 15 secondi salta il successivo; la riga dice se ha rallentato Borsa Italiana
  (e quale titolo) o Supabase.
- **Troppi avvisi da un titolo** (es. un titolo americano quotato a Milano, con pochi
  contratti e prezzi che saltano): alza la sua `soglia_avviso` dalla sezione ISIN Monitor
  del sito; vale dal giro dopo, senza riavviare niente.
- **"Comandi del bot non attivi, Telegram dice: Conflict: ..."**: con "webhook is active"
  il bot ha un webhook (`./setup.sh telegram` mostra verso dove; se non ti serve,
  `./setup.sh telegram togli-webhook`); con "terminated by other getUpdates request" un
  altro programma legge lo stesso bot (un altro ISIN Monitor, su un altro PC?) e va fermato.
- **Nessun avviso**: guarda `./setup.sh logs`; fuori orario il timer non parte;
  `./setup.sh test` prova Telegram con un avviso vero.
- **Grafici vuoti o con buchi**: `./setup.sh riempi-storico --prova` dice quanti punti
  mancano; un titolo senza `simbolo_borsa` non viene riempito da Yahoo.
- **Timer che non parte**: `./setup.sh status` mostra i prossimi avvii; dopo aver cambiato
  gli orari serve `./setup.sh install`.
