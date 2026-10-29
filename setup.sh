#!/bin/bash

# Gestione del servizio systemd di ISIN Monitor.
# Si lancia con o senza sudo (sudo ./setup.sh install oppure ./setup.sh install): il
# servizio gira comunque come il tuo utente, con il suo python3 (es. Anaconda) e la sua
# cartella home. Un altro python si sceglie con PYTHON_BIN=/percorso/python3.

SERVICE_NAME="isin-monitor"
TIMER_NAME="isin-monitor.timer"
CARTELLA="$(cd "$(dirname "$0")" && pwd)"
UTENTE="${SUDO_USER:-$(id -un)}"
HOME_UTENTE="$(getent passwd "$UTENTE" | cut -d: -f6)"
if [[ -z "$PYTHON_BIN" ]]; then
    if [[ $EUID -eq 0 && -n "$SUDO_USER" ]]; then
        # Con sudo il PATH è quello di root: il python3 lo dice la shell dell'utente
        PYTHON_BIN="$(sudo -u "$UTENTE" env -i HOME="$HOME_UTENTE" bash -lic 'command -v python3' 2>/dev/null | tail -1)"
    else
        PYTHON_BIN="$(command -v python3)"
    fi
fi
ENV_DIR="$HOME_UTENTE/.config/isin-monitor"
ENV_FILE="$ENV_DIR/supabase.env"

echo "=== ISIN Monitor Setup ==="

installa() {
    if [[ $EUID -eq 0 && -z "$SUDO_USER" ]]; then
        echo "Lancialo dal tuo utente (./setup.sh install o sudo ./setup.sh install), non da root."
        exit 1
    fi
    if [[ ! -x "$PYTHON_BIN" ]]; then
        echo "python3 non trovato: rilancia con PYTHON_BIN=/percorso/python3 ./setup.sh install"
        exit 1
    fi
    echo "Utente: $UTENTE, python: $PYTHON_BIN"
    cd "$CARTELLA" || exit 1

    # La chiave secret di Supabase: fuori da Dropbox, leggibile solo dal tuo utente
    if [[ ! -f "$ENV_FILE" ]]; then
        mkdir -p "$ENV_DIR" && chmod 700 "$ENV_DIR"
        echo "SUPABASE_SECRET_KEY=" > "$ENV_FILE"
        echo "Creato $ENV_FILE: scrivici la chiave secret (sb_secret_...) dopo SUPABASE_SECRET_KEY="
    fi
    chmod 600 "$ENV_FILE"
    chown -R "$UTENTE": "$ENV_DIR" 2>/dev/null

    # Gli avvii del timer dagli orari di config.json (vedi core/orario.py)
    CALENDARIO=$("$PYTHON_BIN" core/orario.py config.json) || exit 1

    echo "Creando file servizio systemd..."
    sudo tee /etc/systemd/system/$SERVICE_NAME.service > /dev/null << EOF
[Unit]
Description=ISIN Monitor Service
After=network.target

[Service]
# Resta acceso in orario di mercato (un giro ogni 15 secondi) ed esce alla chiusura
Type=simple
WorkingDirectory=$CARTELLA
EnvironmentFile=$ENV_FILE
ExecStart=$PYTHON_BIN monitor.py --monitor
Restart=on-failure
RestartSec=15
User=$UTENTE
Group=$(id -gn "$UTENTE")

[Install]
WantedBy=multi-user.target
EOF

    echo "Creando file timer systemd..."
    sudo tee /etc/systemd/system/$TIMER_NAME > /dev/null << EOF
[Unit]
Description=ISIN Monitor Timer - avvia il monitor in orario di mercato

[Timer]
# Ogni 15 secondi in orario: avvia il monitor se non sta già girando (all'apertura,
# dopo una sospensione del PC o se si è fermato); se gira già non fa niente
$CALENDARIO
# Senza, systemd può ritardare gli avvii fino a un minuto
AccuracySec=1s

[Install]
WantedBy=timers.target
EOF

    echo "Ricaricando systemd..."
    sudo systemctl daemon-reload
    echo "Abilitando e avviando il timer..."
    sudo systemctl enable $TIMER_NAME
    sudo systemctl restart $TIMER_NAME
    # Se il monitor sta girando, riparte con il codice nuovo
    sudo systemctl try-restart $SERVICE_NAME
    echo "Installazione completata! Status:"
    sudo systemctl status $TIMER_NAME --no-pager -l
}

disinstalla() {
    echo "Fermando e disabilitando servizio..."
    sudo systemctl stop $TIMER_NAME
    sudo systemctl disable $TIMER_NAME
    echo "Rimuovendo file systemd..."
    sudo rm -f /etc/systemd/system/$SERVICE_NAME.service
    sudo rm -f /etc/systemd/system/$TIMER_NAME
    sudo systemctl daemon-reload
}

case "$1" in
    restart|"")
        echo "Riavviando timer e monitor..."
        sudo systemctl daemon-reload
        sudo systemctl restart $TIMER_NAME
        sudo systemctl try-restart $SERVICE_NAME
        sudo systemctl status $TIMER_NAME --no-pager -l
        ;;
    stop)
        sudo systemctl stop $TIMER_NAME $SERVICE_NAME
        ;;
    start)
        sudo systemctl start $TIMER_NAME
        ;;
    status)
        sudo systemctl status $TIMER_NAME $SERVICE_NAME --no-pager -l
        systemctl list-timers $TIMER_NAME --no-pager
        ;;
    logs)
        echo "Log servizio (tempo reale - premi Ctrl+C per uscire):"
        sudo journalctl -u $SERVICE_NAME -f --no-pager
        ;;
    test)
        echo "Test manuale (primo titolo, soglia 0: manda sempre l'avviso):"
        cd "$CARTELLA" && "$PYTHON_BIN" monitor.py --check-once --ignora-orario
        ;;
    grafico)
        cd "$CARTELLA" && "$PYTHON_BIN" monitor.py --grafico "$2" --uscita "${3:-grafico.png}"
        ;;
    riempi-storico)
        cd "$CARTELLA" && "$PYTHON_BIN" monitor.py --riempi-storico ${2:+"$2"}
        ;;
    profile)
        cd "$CARTELLA" && "$PYTHON_BIN" monitor.py --check-once --ignora-orario --with-profiling
        ;;
    install)
        echo "=== INSTALLAZIONE SERVIZIO ==="
        installa
        ;;
    reinstall)
        echo "=== REINSTALLAZIONE SERVIZIO ==="
        disinstalla
        installa
        ;;
    uninstall)
        echo "=== DISINSTALLAZIONE SERVIZIO ==="
        disinstalla
        echo "Disinstallazione completata!"
        ;;
    *)
        echo "Comandi disponibili:"
        echo "  ./setup.sh install            # Installa (o aggiorna) servizio e timer systemd"
        echo "  ./setup.sh restart            # Riavvia il timer (default)"
        echo "  ./setup.sh stop | start       # Ferma timer e monitor / riavvia il timer"
        echo "  ./setup.sh status             # Stato del timer e prossimi avvii"
        echo "  ./setup.sh logs               # Log in tempo reale"
        echo "  ./setup.sh test               # Test manuale con avviso Telegram"
        echo "  ./setup.sh grafico ISIN [file.png]   # Salva il grafico di un titolo"
        echo "  ./setup.sh riempi-storico [--prova]  # Riempie i buchi dello storico con Yahoo"
        echo "  ./setup.sh reinstall | uninstall"
        ;;
esac
