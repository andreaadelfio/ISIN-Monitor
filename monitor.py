#!/usr/bin/env python3
"""
ISIN Monitor - Monitoraggio prezzi e notifiche Telegram
Monitora una lista di ISIN e invia notifiche quando raggiungono soglie di sconto predefinite.
"""

import builtins
import os
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import requests

from core.message_templates import CaptionTemplates
from core.price_providers import BorsaItalianaProvider, YahooFinanceProvider
from core.data_manager import DataManager
from core.utils import TableDataGenerator
from core.profiler import profile, profile_detailed
# core.chart_generator e core.profiling_analysis (matplotlib) sono importati solo quando servono

class ISINMonitor:
    @profile()
    def __init__(self, config_file='config.json'):
        self.config_file = config_file
        self.config = self.load_config()
        
        self.bot_token = self.config['telegram']['bot_token']
        self.chat_id = self.config['telegram']['chat_id']
        self.telegram_enabled = self.config['telegram']['enabled']
        
        if self.telegram_enabled and self.bot_token != "123456789:ABCdefGHIjklMNOpqrsTUVwxyz-1234567890":
            self.telegram_configured = True
        else:
            self.telegram_configured = False
            print("Telegram non configurato o disabilitato.")
        
        # Storico prezzi caricato solo al primo uso: fuori orario non si legge il file
        self._data_manager = None
        self._chart_generator = None
        self.price_manager = BorsaItalianaProvider()
        self.yahoo_provider = YahooFinanceProvider(
            self.config.get('yahoo', {})
        )
        self.telegram_session = requests.Session()
        self._company_names: Dict[str, Optional[str]] = {}

        monitoring = self.config['monitoring']
        self._market_open = datetime.strptime(
            monitoring.get('market_open_time', '08:55'), '%H:%M'
        ).time()
        self._market_close = datetime.strptime(
            monitoring.get('market_close_time', '18:05'), '%H:%M'
        ).time()

        print("ISIN Monitor inizializzato")

    @property
    def data_manager(self) -> DataManager:
        if self._data_manager is None:
            self._data_manager = DataManager(self.config)
        return self._data_manager

    @property
    def chart_generator(self):
        if self._chart_generator is None:
            from core.chart_generator import ChartGenerator
            comparison_days = self.config['monitoring'].get(
                'price_comparison_days', [7, 30, 90]
            )
            self._chart_generator = ChartGenerator(
                self.data_manager.to_long_format(),
                comparison_days=comparison_days,
            )
        return self._chart_generator

    @profile_detailed

    def load_config(self) -> Dict:
        """Carica la configurazione dal file JSON."""
        if not os.path.exists(self.config_file):
            print(f"ERRORE: File di configurazione {self.config_file} non trovato!")
            raise FileNotFoundError(f"Config file {self.config_file} not found")
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as file:
                config = json.load(file)
            return config
        except json.JSONDecodeError as e:
            print(f"ERRORE: Errore nel parsing del file di configurazione: {e}")
            raise
        except Exception as e:
            print(f"ERRORE: Errore nel caricamento della configurazione: {e}")
            raise

    @profile_detailed

    def get_max_price_last_days(self, ticker: str, days: int) -> Optional[float]:
        """Calcola il prezzo massimo degli ultimi N giorni."""
        result = self.data_manager.get_max_prices_for_days(ticker, [days])
        return result.get(days)

    @profile_detailed

    def add_to_price_history(self, ticker: str, price: float) -> datetime:
        """Aggiunge un prezzo allo storico e restituisce il timestamp."""
        result_timestamp = self.data_manager.add_price(ticker, price)
        # Aggiorna solo il nuovo punto invece di ricostruire tutto il DataFrame.
        if self._chart_generator is not None:
            isin = self.price_manager.get_isin_for_ticker(ticker) or ''
            self._chart_generator.append_price(
                ticker, isin, result_timestamp, price
            )
        
        return result_timestamp

    @profile_detailed

    def save_price_history(self) -> None:
        """Salva lo storico dei prezzi."""
        self.data_manager.save_data()

    @profile_detailed

    def calculate_price_change(self, ticker: str, current_price: float) -> Tuple[float, bool]:
        """Calcola il cambiamento di prezzo rispetto all'ultimo controllo dal CSV."""
        previous_price = self.data_manager.get_last_price(ticker)
        
        if previous_price is None or previous_price <= 0:
            return 0.0, False
        
        price_change = ((current_price - previous_price) / previous_price) * 100
        
        return price_change, True

    @profile_detailed

    def load_isin_config(self) -> List[Dict]:
        """Carica la configurazione degli ISIN dal DataManager."""
        try:
            metadata_df = self.data_manager.metadata_df
            
            if metadata_df.empty:
                print("⚠️ Nessun metadato trovato nel DataManager")
                return []
            
            isin_list = metadata_df[['isin', 'ticker']].to_dict('records')
            if 'target_discount' in metadata_df:
                discounts = metadata_df['target_discount'].fillna(0.001)
                for isin_data, target_discount in zip(isin_list, discounts):
                    isin_data['target_discount'] = target_discount
            else:
                for isin_data in isin_list:
                    isin_data['target_discount'] = 0.001
            
            print(f"Caricati {len(isin_list)} ticker dalla configurazione CSV")
            
        except Exception as e:
            print(f"ERRORE nella lettura della configurazione: {e}")
            return []
        
        return isin_list

    @profile_detailed

    def get_current_price(self, ticker: str) -> tuple[Optional[float], Optional[datetime]]:
        """Ottiene il prezzo corrente e timestamp tramite il manager dei provider."""
        price, timestamp = self.price_manager.get_price(ticker)
        if price is not None:
            return price, timestamp

        yahoo_config = self.config.get('yahoo', {})
        isin = self.price_manager.get_isin_for_ticker(ticker)
        if not yahoo_config.get('enabled', True) or not isin:
            return None, None

        try:
            fallback = self.yahoo_provider.get_price(ticker, isin)
            if fallback[0] is not None:
                print(f"⚠️ Prezzo realtime Yahoo usato come fallback per {ticker}")
            return fallback
        except (RuntimeError, ValueError) as error:
            print(f"❌ Fallback Yahoo non disponibile per {ticker}: {error}")
            return None, None

    @profile_detailed

    def get_company_name(self, ticker: str) -> Optional[str]:
        """Ottiene il nome dell'azienda tramite il manager dei provider."""
        if ticker not in self._company_names:
            self._company_names[ticker] = self.price_manager.get_company_name(ticker)
        return self._company_names[ticker]

    @profile_detailed
    def prepare_chart_history(self, ticker: str, isin: str) -> None:
        """Usa Yahoo per i grafici e mantiene lo storico locale come fallback."""
        yahoo_config = self.config.get('yahoo', {})
        if not yahoo_config.get('enabled', True):
            return

        try:
            history = self.yahoo_provider.get_history(
                ticker=ticker,
                isin=isin,
                daily_range=yahoo_config.get('daily_range', '1y'),
                intraday_range=yahoo_config.get('intraday_range', '1mo'),
                intraday_interval=yahoo_config.get('intraday_interval', '1h'),
            )
            self.chart_generator.replace_ticker_history(ticker, history)
            print(f"📈 Storico grafico Yahoo caricato: {ticker} ({len(history)} record)")
        except (RuntimeError, ValueError) as error:
            print(f"⚠️ Yahoo non disponibile per {ticker}, uso storico locale: {error}")

    @profile_detailed

    def calculate_price_variation(self, current_price: float, reference_price: float) -> float:
        """
        Calcola la variazione percentuale rispetto a un prezzo di riferimento.
        
        Args:
            current_price: Prezzo attuale
            reference_price: Prezzo di riferimento
            
        Returns:
            Variazione percentuale: positiva se aumentato, negativa se diminuito
        """
        if reference_price is None or reference_price <= 0:
            return 0.0
        if current_price is None or current_price <= 0:
            return 0.0
        return ((current_price - reference_price) / reference_price) * 100

    @profile_detailed

    def calculate_discount(self, current_price: float, reference_price: float) -> float:
        """Calcola la percentuale di sconto rispetto al prezzo di riferimento."""
        if reference_price is None or reference_price <= 0:
            return 0.0
        if current_price is None or current_price <= 0:
            return 0.0
        return ((reference_price - current_price) / reference_price) * 100

    @profile_detailed

    def send_telegram_message(self, message: str) -> bool:
        """Invia un messaggio su Telegram usando richieste HTTP dirette."""
        if not self.telegram_configured:
            return False
        
        try:
            chat_id = self.config['telegram'].get('chat_id')
            if not chat_id:
                print("ERRORE: Chat ID Telegram non configurato!")
                return False
            
            request_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            
            params = {
                'chat_id': chat_id,
                'parse_mode': 'HTML',
                'text': message,
                'disable_web_page_preview': False  # Abilita preview dei link
            }
            
            timeout = self.config['api'].get('request_timeout', 5)
            response = self.telegram_session.get(
                request_url, params=params, timeout=timeout
            )
            response.raise_for_status()
            response_data = response.json()
            
            if not response_data.get("ok", False):
                error_desc = response_data.get("description", "Errore sconosciuto")
                print(f"ERRORE: Errore nell'invio Telegram: {error_desc}")
                return False
            
            return True
            
        except requests.RequestException as e:
            print(f"ERRORE: Errore nella richiesta Telegram: {e}")
            return False
        except Exception as e:
            print(f"ERRORE: Errore nell'invio del messaggio Telegram: {e}")
            return False

    @profile_detailed

    def send_telegram_photo(self, photo_data: bytes, caption: str = "", filename: str = "chart.png") -> bool:
        """Invia una foto su Telegram usando dati binari."""
        if not self.telegram_configured:
            return False
        
        try:
            chat_id = self.config['telegram'].get('chat_id')
            if not chat_id:
                print("ERRORE: Chat ID Telegram non configurato!")
                return False
            
            request_url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
            
            files = {'photo': (filename, photo_data, 'image/png')}
            data = {
                'chat_id': chat_id,
                'caption': caption,
                'parse_mode': 'HTML'
            }
            
            timeout = self.config['api'].get('request_timeout', 30)  # Timeout più alto per upload
            response = self.telegram_session.post(
                request_url, files=files, data=data, timeout=timeout
            )
            response.raise_for_status()
            response_data = response.json()
            
            if not response_data.get("ok", False):
                error_desc = response_data.get("description", "Errore sconosciuto")
                print(f"ERRORE: Errore nell'invio foto Telegram: {error_desc}")
                return False
            
            return True
            
        except Exception as e:
            print(f"ERRORE: Eccezione nell'invio foto Telegram: {e}")
            return False

    @profile_detailed

    def check_single_isin(self, isin_data: Dict) -> None:
        """Controlla un singolo ISIN."""
        try:
            current_price, _ = self.get_current_price(isin_data['ticker'])
            
            if current_price is None:
                print(f"❌ Impossibile ottenere il prezzo per {isin_data['ticker']} - ticker potrebbe essere errato")
                return
            
            ticker = isin_data['ticker']
            
            company_name = self.get_company_name(ticker)
            
            isin_data_with_name = isin_data.copy()
            isin_data_with_name['company_name'] = company_name
            
            price_change, has_previous = self.calculate_price_change(ticker, current_price)
            previous_price_for_messages = (
                self.data_manager.get_last_price(ticker)
                if has_previous else None
            )
            
            if not has_previous or current_price != previous_price_for_messages:
                self.add_to_price_history(ticker, current_price)
                print(f"💾 Prezzo aggiornato: {ticker} €{current_price:.4f}")
            else:
                print(f"⏭️ Prezzo invariato: {ticker} €{current_price:.4f} (saltato)")
                if isin_data.get('target_discount', 0.001) > 0:
                    return
            
            max_change = abs(price_change)
            if has_previous and max_change >= isin_data['target_discount']:
                
                if self.telegram_configured:
                    historical_prices = self.get_historical_closing_prices(
                        isin_data['isin']
                    )
                    oldest_price = self.data_manager.get_oldest_price_for_isin(
                        isin_data['isin']
                    )
                    today = datetime.now().date()
                    opening_price = self.data_manager.get_opening_price_for_date(isin_data['isin'], today)
                    
                    table_data = TableDataGenerator.generate_table_data(
                        current_price, opening_price, previous_price_for_messages,
                        historical_prices, oldest_price
                    )
                    
                    caption = CaptionTemplates.format_caption(
                        isin_data_with_name,
                        current_price,
                        table_data=table_data
                    )

                    send_charts = self.config.get('telegram', {}).get('send_charts', True)
                    success = False
                    
                    if send_charts:
                        try:
                            self.prepare_chart_history(
                                ticker, isin_data['isin']
                            )
                            chart_data = self.chart_generator.create_comprehensive_chart(
                                isin_data_with_name, current_price,
                                previous_price=previous_price_for_messages,
                                table_data=table_data
                            )
                            filename = f'isin_chart_{ticker}_{int(datetime.now().timestamp())}.png'
                            success = self.send_telegram_photo(chart_data, caption, filename)
                            
                            if success:
                                print(f"Grafico inviato per {isin_data['isin']} (variazione: {price_change:+.1f}%)")
                        except Exception as e:
                            print(f"❌ Errore generazione grafico per {isin_data['isin']}: {e}")
                    
                    if not success:
                        success = self.send_telegram_message(caption)
                        if success:
                            print(f"Messaggio {'testuale' if not send_charts else 'di fallback'} inviato per {isin_data['isin']}")
                        else:
                            print(f"❌ Fallito invio notifica per {isin_data['isin']}")
                
                direction = "aumento" if price_change > 0 else "calo"
                print(f"🎯 VARIAZIONE SIGNIFICATIVA! {isin_data['isin']} - {direction}: {abs(price_change):.1f}%")
        except Exception as e:
            print(f"ERRORE: Errore nel controllo di {isin_data['isin']}: {e}")

    @profile_detailed

    def get_historical_closing_prices(self, isin_code: str) -> Dict[int, float]:
        """
        Calcola i prezzi di chiusura storici per N giorni fa.
        
        Returns:
            Dict con {giorni: prezzo_chiusura}, es. {30: 207.34, 7: 185.50}
        """
        historical_prices = {}
        periods = self.config['monitoring'].get(
            'historical_table_days', [1, 7, 30, 90, 365]
        )
        
        for days in periods:
            target_date = datetime.now() - timedelta(days=days)
            closing_price = self.data_manager.get_closing_price_for_date(isin_code, target_date.date())
            
            if closing_price is not None:
                historical_prices[days] = closing_price
        
        return historical_prices

    @profile_detailed

    def check_all_isin(self) -> None:
        """Controlla tutti gli ISIN configurati."""
        print("🔍 Inizio controllo prezzi ISIN...")
        
        isin_list = self.load_isin_config()
        if not isin_list:
            print("⚠️ Nessun ISIN configurato!")
            return
        
        rate_limit_delay = self.config['api'].get('rate_limit_delay', 0.5)
        for i, isin_data in enumerate(isin_list):
            if i > 0:
                time.sleep(rate_limit_delay)
            self.check_single_isin(isin_data)
        
        self.save_price_history()
        
        print("✅ Controllo prezzi completato")

    @profile_detailed

    def is_market_hours(self) -> bool:
        """Controlla se siamo nell'orario di mercato configurato (con weekdays_only, solo lun-ven)."""
        if not self.config['monitoring'].get('market_hours_only', True):
            return True

        now = datetime.now()
        # Sabato e domenica le borse sono chiuse
        if self.config['monitoring'].get('weekdays_only', True) and now.weekday() >= 5:
            return False
        current_time = now.time()
        return self._market_open <= current_time <= self._market_close

    def _market_hours_label(self) -> str:
        """Descrive l'orario configurato, es. 'lun-ven 08:55-18:05'."""
        monitoring = self.config['monitoring']
        hours = (
            f"{monitoring.get('market_open_time', '08:55')}-"
            f"{monitoring.get('market_close_time', '18:05')}"
        )
        return f"lun-ven {hours}" if monitoring.get('weekdays_only', True) else hours

    @profile_detailed

    def run_check(self) -> None:
        """Wrapper per il controllo."""
        try:
            if not self.is_market_hours():
                now = datetime.now()
                print(f"⏰ Fuori orario di mercato ({now.strftime('%a %H:%M')}) - Controllo saltato (orario: {self._market_hours_label()})")
                return
            
            self.check_all_isin()
        except Exception as e:
            print(f"ERRORE: Errore nel controllo: {e}")

    @profile_detailed

    def run_test(self) -> None:
        """Wrapper per il controllo di test (controlla un solo ISIN con target_discount=0)."""
        try:
            if not self.is_market_hours():
                now = datetime.now()
                print(f"⏰ Fuori orario di mercato ({now.strftime('%a %H:%M')}) - Controllo saltato (orario: {self._market_hours_label()})")
                return

            isin_list = self.load_isin_config()
            if not isin_list:
                print("⚠️ Nessun ISIN configurato!")
                return
            
            # Prende solo il primo ISIN per il test
            test_isin = isin_list[0].copy()
            test_isin['target_discount'] = 0  # Forza la notifica impostando soglia a 0
            
            print(f"🧪 Test mode: controllo singolo ISIN {test_isin['isin']} con target_discount=0")
            self.check_single_isin(test_isin)
        except Exception as e:
            print(f"ERRORE: Errore nel controllo: {e}")

    @profile_detailed

    def test_telegram(self) -> None:
        """Testa la connessione Telegram."""
        if not self.telegram_configured:
            print("❌ Telegram non configurato!")
            return
        
        try:
            test_message = CaptionTemplates.format_test_caption()
            success = self.send_telegram_message(test_message)
            if success:
                print("✅ Messaggio di test inviato con successo!")
            else:
                print("❌ Errore nell'invio del messaggio di test")
        except Exception as e:
            print(f"❌ Errore nel test Telegram: {e}")

    @profile_detailed

    def start_monitoring(self) -> None:
        """Esegue un singolo controllo di monitoraggio (per uso con systemd timer)."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"🚀 [{timestamp}] Esecuzione controllo ISIN via systemd timer")
        
        # Mostra informazioni sull'orario di mercato
        market_hours_enabled = self.config['monitoring'].get('market_hours_only', True)
        if market_hours_enabled:
            in_market_hours = self.is_market_hours()
            status = "attivo" if in_market_hours else "fuori orario"
            print(f"   ⏰ Orario di lavoro: {self._market_hours_label()} - Status: {status}")
        else:
            print("   ⏰ Monitoraggio 24/7 (orario di mercato disabilitato)")
        
        # Esegui il controllo
        try:
            self.run_check()
            print(f"✅ [{datetime.now().strftime('%H:%M:%S')}] Controllo completato con successo")
        except Exception as e:
            print(f"❌ [{datetime.now().strftime('%H:%M:%S')}] ERRORE nel controllo: {e}")
            raise

@profile_detailed

def main():
    """Funzione principale."""
    import argparse
    
    parser = argparse.ArgumentParser(description='ISIN Monitor - Monitoraggio prezzi e notifiche')
    parser.add_argument('--test-telegram', action='store_true', 
                       help='Testa la connessione Telegram')
    parser.add_argument('--check-once', action='store_true',
                       help='Esegue un singolo controllo senza monitoraggio continuo')
    parser.add_argument('--monitor', action='store_true',
                       help='Avvia il monitoraggio continuo (usare con systemd timer)')
    parser.add_argument('--with-profiling', action='store_true',
                       help='Abilita il profiling delle funzioni')
    args = parser.parse_args()

    # Imposta variabile globale per profiling
    builtins.ENABLE_PROFILING = args.with_profiling

    monitor = ISINMonitor()
    
    
    if args.test_telegram:
        monitor.test_telegram()
    elif args.check_once or monitor.config['test']:
        monitor.run_test()
    elif args.monitor:
        monitor.start_monitoring()
    else:
        parser.print_help()

    if args.with_profiling:
        from core.profiling_analysis import main as profile_analyser_main
        profile_analyser_main()

if __name__ == "__main__":
    main()
