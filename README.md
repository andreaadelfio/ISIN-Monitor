# ISIN Monitor# ISIN Monitor# ISIN Monitor# ISIN Monitor



Sistema di monitoraggio automatico per prezzi di titoli finanziari con notifiche Telegram.



## 📁 Struttura ProgettoSistema di monitoraggio automatico per prezzi di titoli finanziari con notifiche Telegram.



```

ISIN Monitor/

├── monitor.py              # Script principale## 📁 Struttura ProgettoSistema di monitoraggio automatico per prezzi di titoli finanziari con notifiche Telegram.Sistema di monitoraggio automatico per prezzi di titoli finanziari con notifiche Telegram.

├── config.json             # Configurazione

├── isin_metadata.csv       # Metadati ticker e ISIN

├── price_history_wide.csv  # Storico prezzi

├── setup.sh                # Script di gestione systemd```

├── requirements.txt        # Dipendenze Python

├── core/                   # Moduli coreISIN Monitor/

│   ├── __init__.py

│   ├── chart_generator.py  # Generazione grafici├── monitor.py              # Script principale## 📁 Struttura Progetto## 🚀 Setup Rapido

│   ├── data_manager.py     # Gestione dati CSV

│   ├── message_templates.py # Template messaggi Telegram├── config.json             # Configurazione

│   ├── price_providers.py  # Provider prezzi (Borsa Italiana)

│   └── utils.py            # Utilità condivise├── isin_metadata.csv       # Metadati ticker e ISIN

└── README.md

```├── price_history_wide.csv  # Storico prezzi



## 🚀 Setup Rapido├── setup.sh                # Script di gestione systemd```bash



```bash├── requirements.txt        # Dipendenze Python

./setup.sh install    # Installa servizio systemd

./setup.sh restart    # Riavvia servizio├── core/                   # Moduli coreISIN Monitor/./setup.sh

./setup.sh status     # Controlla stato

./setup.sh logs       # Visualizza log in tempo reale│   ├── __init__.py

./setup.sh test       # Test manuale

```│   ├── chart_generator.py  # Generazione grafici├── monitor.py              # Script principale```



## ⚙️ Configurazione│   ├── data_manager.py     # Gestione dati CSV



### config.json│   ├── message_templates.py # Template messaggi Telegram├── config.json             # Configurazione

```json

{│   ├── price_providers.py  # Provider prezzi (Borsa Italiana)

  "telegram": {

    "enabled": true,│   └── utils.py            # Utilità condivise├── isin_metadata.csv       # Metadati ticker e ISIN## ⚙️ Configurazione

    "bot_token": "IL_TUO_BOT_TOKEN",

    "chat_id": "IL_TUO_CHAT_ID",└── README.md

    "send_charts": true

  },```├── price_history_wide.csv  # Storico prezzi

  "monitoring": {

    "notification_cooldown_hours": 1,

    "market_hours_only": true,

    "market_open_time": "08:55",## 🚀 Setup Rapido├── setup.sh                # Script di gestione systemd### config.json

    "market_close_time": "18:05",

    "price_comparison_days": [30, 7]

  },

  "api": {```bash├── requirements.txt        # Dipendenze Python```json

    "rate_limit_delay": 0.5,

    "request_timeout": 10./setup.sh install    # Installa servizio systemd

  }

}./setup.sh restart    # Riavvia servizio├── core/                   # Moduli core{

```

./setup.sh status     # Controlla stato

### isin_metadata.csv

```csv./setup.sh logs       # Visualizza log in tempo reale│   ├── __init__.py  "telegram": {

ticker,isin,company_name,target_discount

ENI.MI,IT0003132476,Eni S.p.A.,0.02./setup.sh test       # Test manuale

NVDA,US67066G1040,NVIDIA Corporation,0.02

ASML.AS,NL0010273215,ASML Holding N.V.,0.02```│   ├── chart_generator.py  # Generazione grafici    "bot_token": "IL_TUO_BOT_TOKEN",

```



## 🎛️ Controllo

## ⚙️ Configurazione│   ├── data_manager.py     # Gestione dati CSV    "chat_id": "IL_TUO_CHAT_ID"

```bash

# Status servizio

./setup.sh status

### config.json│   ├── message_templates.py # Template messaggi Telegram  }

# Log in tempo reale

./setup.sh logs```json



# Test manuale{│   ├── price_providers.py  # Provider prezzi (Borsa Italiana)}

./setup.sh test

  "telegram": {

# Test Telegram

python monitor.py --test-telegram    "enabled": true,│   └── utils.py            # Utilità condivise```

```

    "bot_token": "IL_TUO_BOT_TOKEN",

## 🔧 Comandi Avanzati

    "chat_id": "IL_TUO_CHAT_ID",└── README.md

```bash

# Gestione servizio    "send_charts": true

./setup.sh install      # Installa servizio systemd

./setup.sh uninstall    # Rimuove servizio systemd  },```### isin_config.txt

./setup.sh reinstall    # Reinstalla servizio systemd

./setup.sh start        # Avvia servizio  "monitoring": {

./setup.sh stop         # Ferma servizio

./setup.sh restart      # Riavvia servizio    "notification_cooldown_hours": 1,```



# Test e debug    "market_hours_only": true,

python monitor.py --check-once    # Test singolo controllo

python monitor.py --monitor       # Controllo normale (usato da systemd)    "market_open_time": "08:55",## 🚀 Setup RapidoIT0003132476:ENI.MI:5

python monitor.py --test-telegram # Test connessione Telegram

```    "market_close_time": "18:05",



## ⚡ Caratteristiche    "price_comparison_days": [30, 7]US67066G1040:NVDA:5



- **📊 Grafici automatici**: Generazione automatica di grafici con prezzi storici  },

- **📱 Notifiche Telegram**: Invio automatico di grafici e messaggi

- **⏰ Controllo orari**: Monitoraggio solo durante orari di mercato  "api": {```bash```

- **🚫 Anti-spam**: Cooldown per evitare notifiche duplicate

- **📈 Multi-timeframe**: Confronto prezzi su più periodi (7, 30, 90, 365 giorni)    "rate_limit_delay": 0.5,

- **💾 Ottimizzazioni**: Salvataggio prezzi solo se cambiati

- **🔄 Rate limiting**: Protezione contro limitazioni API    "request_timeout": 10./setup.sh install    # Installa servizio systemd

- **🧪 Modalità test**: Test con target_discount=0 per forzare notifiche

  }

## 📋 Log e Debugging

}./setup.sh restart    # Riavvia servizio## 🎛️ Controllo

Il sistema genera log dettagliati visibili con:

```bash```

./setup.sh logs

```./setup.sh status     # Controlla stato



I log includono:### isin_metadata.csv

- ✅ Prezzi aggiornati vs ⏭️ prezzi invariati

- 🎯 Variazioni significative```csv./setup.sh logs       # Visualizza log in tempo reale```bash

- 📊 Sconti attuali rispetto ai massimi storici

- ❌ Errori di connessione o APIticker,isin,company_name,target_discount



## 🎯 Modalità OperativeENI.MI,IT0003132476,Eni S.p.A.,0.02./setup.sh test       # Test manuale# Status



### Produzione (Systemd)NVDA,US67066G1040,NVIDIA Corporation,0.02

Il sistema funziona automaticamente tramite systemd timer ogni 15 secondi:

- Controlla tutti i ticker configuratiASML.AS,NL0010273215,ASML Holding N.V.,0.02```systemctl status isin-monitor.timer

- Usa i target_discount dal CSV

- Invia notifiche solo per variazioni significative```



### Test Manuale

```bash

./setup.sh test## 🎛️ Controllo

```

- Controlla solo il primo ticker## ⚙️ Configurazione# Log

- Forza target_discount=0 per generare sempre notifica

- Utile per testare grafici e messaggi```bash



### Debug# Status serviziojournalctl -fu isin-monitor.service

```bash

./setup.sh logs./setup.sh status

```

- Mostra log in tempo reale### config.json

- Aggiornamento ogni secondo

- Premi Ctrl+C per uscire# Log in tempo reale



## 💡 Tips./setup.sh logs```json# Test



- **Primo avvio**: Il sistema inizializza i prezzi di riferimento al primo controllo

- **Rate limiting**: Delay di 0.5s tra richieste per evitare blocchi API

- **Orari mercato**: Per default attivo solo 08:55-18:05 (configurabile)# Test manuale{python monitor.py --test-telegram

- **Cooldown**: Notifiche max 1 volta/ora per stesso livello di variazione
./setup.sh test

  "telegram": {python test_nvidia.py

# Test Telegram

python monitor.py --test-telegram    "enabled": true,```

```

    "bot_token": "IL_TUO_BOT_TOKEN",

## 🔧 Comandi Avanzati

    "chat_id": "IL_TUO_CHAT_ID",## � Comandi

```bash

# Gestione servizio    "send_charts": true

./setup.sh install      # Installa servizio systemd

./setup.sh uninstall    # Rimuove servizio systemd  },```bash

./setup.sh reinstall    # Reinstalla servizio systemd

./setup.sh start        # Avvia servizio  "monitoring": {# Start/Stop

./setup.sh stop         # Ferma servizio

./setup.sh restart      # Riavvia servizio    "notification_cooldown_hours": 1,sudo systemctl start isin-monitor.timer



# Test e debug    "market_hours_only": true,sudo systemctl stop isin-monitor.timer

python monitor.py --check-once    # Test singolo controllo

python monitor.py --monitor       # Controllo normale (usato da systemd)    "market_open_time": "08:55",

python monitor.py --test-telegram # Test connessione Telegram

```    "market_close_time": "18:05",# Test manuale



## ⚡ Caratteristiche    "price_comparison_days": [30, 7]python monitor.py --check-once



- **📊 Grafici automatici**: Generazione automatica di grafici con prezzi storici  },```

- **📱 Notifiche Telegram**: Invio automatico di grafici e messaggi  "api": {

- **⏰ Controllo orari**: Monitoraggio solo durante orari di mercato    "rate_limit_delay": 0.5,

- **🚫 Anti-spam**: Cooldown per evitare notifiche duplicate    "request_timeout": 10

- **📈 Multi-timeframe**: Confronto prezzi su più periodi (7, 30, 90, 365 giorni)  }

- **💾 Ottimizzazioni**: Salvataggio prezzi solo se cambiati}

- **🔄 Rate limiting**: Protezione contro limitazioni API```

- **🧪 Modalità test**: Test con target_discount=0 per forzare notifiche

### isin_metadata.csv

## 📋 Log e Debugging```csv

ticker,isin,company_name,target_discount

Il sistema genera log dettagliati visibili con:ENI.MI,IT0003132476,Eni S.p.A.,0.02

```bashNVDA,US67066G1040,NVIDIA Corporation,0.02

./setup.sh logsASML.AS,NL0010273215,ASML Holding N.V.,0.02

``````



I log includono:## 🎛️ Controllo

- ✅ Prezzi aggiornati vs ⏭️ prezzi invariati

- 🎯 Variazioni significative```bash

- 📊 Sconti attuali rispetto ai massimi storici# Status servizio

- ❌ Errori di connessione o API./setup.sh status



## 🎯 Modalità Operative# Log in tempo reale

./setup.sh logs

### Produzione (Systemd)

Il sistema funziona automaticamente tramite systemd timer ogni 15 secondi:# Test manuale

- Controlla tutti i ticker configurati./setup.sh test

- Usa i target_discount dal CSV

- Invia notifiche solo per variazioni significative# Test Telegram

python monitor.py --test-telegram

### Test Manual```

```bash

./setup.sh test## 🔧 Comandi Avanzati

```

- Controlla solo il primo ticker```bash

- Forza target_discount=0 per generare sempre notifica# Gestione servizio

- Utile per testare grafici e messaggi./setup.sh install      # Installa servizio systemd

./setup.sh uninstall    # Rimuove servizio systemd

### Debug./setup.sh reinstall    # Reinstalla servizio systemd

```bash./setup.sh start        # Avvia servizio

./setup.sh logs./setup.sh stop         # Ferma servizio

```./setup.sh restart      # Riavvia servizio

- Mostra log in tempo reale

- Aggiornamento ogni secondo# Test e debug

- Premi Ctrl+C per uscirepython monitor.py --check-once    # Test singolo controllo

python monitor.py --monitor       # Controllo normale (usato da systemd)

## 💡 Tipspython monitor.py --test-telegram # Test connessione Telegram

```

- **Primo avvio**: Il sistema inizializza i prezzi di riferimento al primo controllo

- **Rate limiting**: Delay di 0.5s tra richieste per evitare blocchi API## ⚡ Caratteristiche

- **Orari mercato**: Per default attivo solo 08:55-18:05 (configurabile)

- **Cooldown**: Notifiche max 1 volta/ora per stesso livello di variazione- **📊 Grafici automatici**: Generazione automatica di grafici con prezzi storici
- **📱 Notifiche Telegram**: Invio automatico di grafici e messaggi
- **⏰ Controllo orari**: Monitoraggio solo durante orari di mercato
- **🚫 Anti-spam**: Cooldown per evitare notifiche duplicate
- **📈 Multi-timeframe**: Confronto prezzi su più periodi (7, 30, 90, 365 giorni)
- **💾 Ottimizzazioni**: Salvataggio prezzi solo se cambiati
- **🔄 Rate limiting**: Protezione contro limitazioni API
- **🧪 Modalità test**: Test con target_discount=0 per forzare notifiche

## 📋 Log e Debugging

Il sistema genera log dettagliati visibili con:
```bash
./setup.sh logs
```

I log includono:
- ✅ Prezzi aggiornati vs ⏭️ prezzi invariati
- 🎯 Variazioni significative
- 📊 Sconti attuali rispetto ai massimi storici
- ❌ Errori di connessione o API