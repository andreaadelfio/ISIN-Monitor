#!/bin/bash

# Setup script per aggiornare ISIN Monitor

SERVICE_NAME="isin-monitor"
TIMER_NAME="isin-monitor.timer"

echo "=== ISIN Monitor Setup ==="

if [[ "$1" == "restart" || "$1" == "" ]]; then
    echo "Fermando servizio..."
    sudo systemctl stop $TIMER_NAME
    
    echo "Ricaricando systemd..."
    sudo systemctl daemon-reload
    
    echo "Avviando servizio..."
    sudo systemctl start $TIMER_NAME
    
    echo "Status:"
    sudo systemctl status $TIMER_NAME --no-pager -l
    
elif [[ "$1" == "stop" ]]; then
    echo "Fermando servizio..."
    sudo systemctl stop $TIMER_NAME
    
elif [[ "$1" == "start" ]]; then
    echo "Avviando servizio..."
    sudo systemctl start $TIMER_NAME
    
elif [[ "$1" == "status" ]]; then
    echo "Status servizio:"
    sudo systemctl status $TIMER_NAME --no-pager -l
    
elif [[ "$1" == "logs" ]]; then
    echo "Log servizio (tempo reale - premi Ctrl+C per uscire):"
    sudo journalctl -u $SERVICE_NAME -f --no-pager
    
elif [[ "$1" == "test" ]]; then
    echo "Test manuale:"
    python3 monitor.py --check-once
    
elif [[ "$1" == "profile" ]]; then
    echo "Profile with --check-once manuale:"
    python3 monitor.py --check-once --with-profiling

elif [[ "$1" == "install" ]]; then
    echo "=== INSTALLAZIONE SERVIZIO ==="
    
    # Percorso corrente
    CURRENT_DIR=$(pwd)
    
    echo "Creando file servizio systemd..."
    sudo tee /etc/systemd/system/$SERVICE_NAME.service > /dev/null << EOF
[Unit]
Description=ISIN Monitor Service
After=network.target

[Service]
Type=oneshot
WorkingDirectory=$CURRENT_DIR
ExecStart=/home/andrea-adelfio/anaconda3/envs/rootenv/bin/python monitor.py --monitor
User=andrea-adelfio
Group=andrea-adelfio

[Install]
WantedBy=multi-user.target
EOF
    
    echo "Creando file timer systemd..."
    sudo tee /etc/systemd/system/$TIMER_NAME > /dev/null << EOF
[Unit]
Description=ISIN Monitor Timer - Esecuzione ogni 15 secondi
Requires=$SERVICE_NAME.service

[Timer]
OnCalendar=*:*:0/15
Persistent=true

[Install]
WantedBy=timers.target
EOF
    
    echo "Ricaricando systemd..."
    sudo systemctl daemon-reload
    
    echo "Abilitando e avviando il timer..."
    sudo systemctl enable $TIMER_NAME
    sudo systemctl start $TIMER_NAME
    
    echo "Installazione completata! Status:"
    sudo systemctl status $TIMER_NAME --no-pager -l
    
elif [[ "$1" == "uninstall" ]]; then
    echo "=== DISINSTALLAZIONE SERVIZIO ==="
    
    echo "Fermando e disabilitando servizio..."
    sudo systemctl stop $TIMER_NAME
    sudo systemctl disable $TIMER_NAME
    
    echo "Rimuovendo file systemd..."
    sudo rm -f /etc/systemd/system/$SERVICE_NAME.service
    sudo rm -f /etc/systemd/system/$TIMER_NAME
    
    echo "Ricaricando systemd..."
    sudo systemctl daemon-reload
    
    echo "Disinstallazione completata!"
    
elif [[ "$1" == "reinstall" ]]; then
    echo "=== REINSTALLAZIONE SERVIZIO ==="
    
    echo "Fermando e disabilitando servizio..."
    sudo systemctl stop $TIMER_NAME
    sudo systemctl disable $TIMER_NAME
    
    echo "Rimuovendo file systemd..."
    sudo rm -f /etc/systemd/system/$SERVICE_NAME.service
    sudo rm -f /etc/systemd/system/$TIMER_NAME
    
    echo "Ricaricando systemd..."
    sudo systemctl daemon-reload
    
    # Percorso corrente
    CURRENT_DIR=$(pwd)
    
    echo "Creando file servizio systemd..."
    sudo tee /etc/systemd/system/$SERVICE_NAME.service > /dev/null << EOF
[Unit]
Description=ISIN Monitor Service
After=network.target

[Service]
Type=oneshot
WorkingDirectory=$CURRENT_DIR
ExecStart=/home/andrea-adelfio/anaconda3/envs/rootenv/bin/python monitor.py --monitor
User=andrea-adelfio
Group=andrea-adelfio

[Install]
WantedBy=multi-user.target
EOF
    
    echo "Creando file timer systemd..."
    sudo tee /etc/systemd/system/$TIMER_NAME > /dev/null << EOF
[Unit]
Description=ISIN Monitor Timer - Esecuzione ogni 15 secondi
Requires=$SERVICE_NAME.service

[Timer]
OnCalendar=*:*:0/15
Persistent=true

[Install]
WantedBy=timers.target
EOF
    
    echo "Ricaricando systemd..."
    sudo systemctl daemon-reload
    
    echo "Abilitando e avviando il timer..."
    sudo systemctl enable $TIMER_NAME
    sudo systemctl start $TIMER_NAME
    
    echo "Installazione completata! Status:"
    sudo systemctl status $TIMER_NAME --no-pager -l

else
    echo "Comandi disponibili:"
    echo "  ./setup.sh restart    # Riavvia servizio (default)"
    echo "  ./setup.sh stop       # Ferma servizio"
    echo "  ./setup.sh start      # Avvia servizio"
    echo "  ./setup.sh status     # Stato servizio"
    echo "  ./setup.sh logs       # Mostra log"
    echo "  ./setup.sh test       # Test manuale"
    echo "  ./setup.sh install    # Installa servizio systemd"
    echo "  ./setup.sh reinstall  # Reinstalla servizio systemd"
    echo "  ./setup.sh uninstall  # Rimuove servizio systemd"
fi
