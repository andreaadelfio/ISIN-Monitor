#!/usr/bin/env python3
"""
Gestione dati per ISIN Monitor
Gestisce prezzi e metadati in formato pulito e semplificato
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import os
from .profiler import profile


class DataManager:
    """Manager semplificato per gestione prezzi e metadati.

    Lo storico prezzi è in formato long: una riga per prezzo con colonne
    timestamp (datetime64), ticker (category) e price (float64).
    """

    def __init__(self, config: Dict):
        self.config = config
        self.price_data_df = pd.DataFrame()
        self.metadata_df = pd.DataFrame()

        # File paths - usa direttamente la configurazione CSV
        self.metadata_file = config['data']['isin_config_file']
        self.price_file = config['data']['price_history_data']

        # True solo se add_price() ha aggiunto prezzi non ancora salvati
        self._dirty = False
        self._ticker_cache: Dict[str, pd.DataFrame] = {}
        self._ticker_dates_cache: Dict[str, pd.Series] = {}
        self._ticker_to_isin_cache: Optional[Dict[str, str]] = None

        self.load_data()

    @profile()
    def load_data(self) -> None:
        """Carica prezzi e metadati."""
        # Carica metadati dal CSV configurato
        if os.path.exists(self.metadata_file):
            try:
                self.metadata_df = pd.read_csv(self.metadata_file)
                print(f"📋 Metadati caricati: {len(self.metadata_df)} ticker")
                # Invalida cache per to_long_format dopo reload metadati
                self._invalidate_ticker_cache()
            except Exception as e:
                print(f"⚠️ Errore caricamento metadati: {e}")
                self._create_empty_metadata()
        else:
            print(f"⚠️ File metadati {self.metadata_file} non trovato")
            self._create_empty_metadata()

        # Carica prezzi (la compressione è dedotta dall'estensione, es. .zst)
        if os.path.exists(self.price_file):
            try:
                self.price_data_df = pd.read_pickle(self.price_file)
                self.price_data_df['timestamp'] = pd.to_datetime(self.price_data_df['timestamp'])
                self.price_data_df['ticker'] = self.price_data_df['ticker'].astype('category')

                # Pulisci dati vecchi
                self._cleanup_old_data()
                print(f"📊 Dati prezzi caricati: {len(self.price_data_df)} record")

            except Exception as e:
                print(f"⚠️ Errore caricamento prezzi: {e}")
                self._create_empty_price_data()
        else:
            print(f"📊 File prezzi {self.price_file} non trovato, parto da uno storico vuoto")
            self._create_empty_price_data()

    def _create_empty_metadata(self):
        """Crea DataFrame metadati vuoto."""
        self.metadata_df = pd.DataFrame(columns=['ticker', 'isin', 'target_discount'])

    def _create_empty_price_data(self):
        """Crea DataFrame prezzi vuoto."""
        self.price_data_df = pd.DataFrame({
            'timestamp': pd.Series(dtype='datetime64[ns]'),
            'ticker': pd.Series(dtype='category'),
            'price': pd.Series(dtype='float64'),
        })

    def _cleanup_old_data(self):
        """Rimuove dati più vecchi di max_history_days."""
        max_days = self.config['data']['max_history_days']
        cutoff_date = datetime.now() - timedelta(days=max_days)
        old_count = len(self.price_data_df)
        self.price_data_df = self.price_data_df[
            self.price_data_df['timestamp'] > cutoff_date
        ]
        self._ticker_cache.clear()
        self._ticker_dates_cache.clear()
        cleaned_count = old_count - len(self.price_data_df)
        if cleaned_count > 0:
            print(f"🧹 Rimossi {cleaned_count} record più vecchi di {max_days} giorni")

    def _ticker_data(self, ticker: str) -> pd.DataFrame:
        """Righe dello storico di un ticker, in ordine cronologico."""
        if ticker not in self._ticker_cache:
            self._ticker_cache[ticker] = self.price_data_df[
                self.price_data_df['ticker'] == ticker
            ]
        return self._ticker_cache[ticker]

    def _ticker_dates(self, ticker: str, ticker_data: pd.DataFrame) -> pd.Series:
        """Restituisce le date per ticker evitando conversioni ripetute."""
        if ticker not in self._ticker_dates_cache:
            self._ticker_dates_cache[ticker] = ticker_data['timestamp'].dt.date
        return self._ticker_dates_cache[ticker]

    def _ticker_for_isin(self, isin_code: str) -> Optional[str]:
        """Trova il ticker di un ISIN nei metadati."""
        if self.metadata_df.empty:
            return None
        ticker_row = self.metadata_df[self.metadata_df['isin'] == isin_code]
        if ticker_row.empty:
            return None
        return ticker_row.iloc[0]['ticker']

    @profile()
    def save_data(self) -> None:
        """Salva prezzi (i metadati sono read-only dal CSV configurato)."""
        if not self._dirty:
            print("💾 Nessun prezzo nuovo: file non riscritto")
            return

        # Il .tmp va prima dell'ultima estensione (es. storico.pk.tmp.zst),
        # così pandas deduce la stessa compressione del file finale
        root, ext = os.path.splitext(self.price_file)
        tmp_file = f"{root}.tmp{ext}"
        try:
            self._cleanup_old_data()

            # Scrittura atomica: un'interruzione non lascia il file a metà
            # e Dropbox vede una sola modifica
            self.price_data_df.to_pickle(tmp_file)
            os.replace(tmp_file, self.price_file)
            self._dirty = False

            # Statistiche
            ticker_count = self.price_data_df['ticker'].nunique()
            print(f"💾 Dati salvati: {len(self.price_data_df)} record, {ticker_count} ticker")

        except Exception as e:
            print(f"❌ Errore salvataggio: {e}")
            if os.path.exists(tmp_file):
                os.remove(tmp_file)

    @profile()
    def add_price(self, ticker: str, price: float) -> datetime:
        """Aggiunge un prezzo per un ticker."""
        # Al secondo, come sempre salvato nello storico
        now = datetime.now().replace(microsecond=0)

        # Il ticker deve essere tra le categorie, altrimenti concat perde il tipo category
        tickers = self.price_data_df['ticker']
        if ticker not in tickers.cat.categories:
            self.price_data_df = self.price_data_df.assign(
                ticker=tickers.cat.add_categories([ticker])
            )

        # Crea nuovo record
        new_row = pd.DataFrame({
            'timestamp': [now],
            'ticker': pd.Categorical([ticker], categories=self.price_data_df['ticker'].cat.categories),
            'price': [price],
        })

        # Concatena
        if self.price_data_df.empty:
            self.price_data_df = new_row
        else:
            self.price_data_df = pd.concat([self.price_data_df, new_row], ignore_index=True)

        self._ticker_cache.pop(ticker, None)
        self._ticker_dates_cache.pop(ticker, None)
        self._dirty = True
        return now

    @profile()
    def get_last_price(self, ticker: str) -> Optional[float]:
        """Ottiene l'ultimo prezzo per un ticker."""
        ticker_prices = self._ticker_data(ticker)['price']
        if ticker_prices.empty:
            return None

        return ticker_prices.iloc[-1]

    @profile()
    def get_max_prices_for_days(self, ticker: str, days_list: List[int]) -> Dict[int, Optional[float]]:
        """Calcola i prezzi massimi per una lista di periodi."""
        ticker_data = self._ticker_data(ticker)
        if ticker_data.empty:
            return {days: None for days in days_list}

        now = datetime.now()
        result = {}
        for days in days_list:
            cutoff_date = now - timedelta(days=days)
            recent_data = ticker_data[ticker_data['timestamp'] > cutoff_date]

            if recent_data.empty:
                recent_data = ticker_data

            result[days] = recent_data['price'].max()

        return result

    @profile()
    def get_company_name(self, ticker: str) -> Optional[str]:
        """Ottiene il nome dell'azienda dai metadati - ora restituisce solo il ticker."""
        # Non abbiamo più company_name nei metadati, il nome reale
        # verrà ottenuto dal price_manager tramite Borsa Italiana
        return ticker

    @profile()
    def to_long_format(self) -> pd.DataFrame:
        """
        Restituisce lo storico per il ChartGenerator (timestamp, ticker, price, isin).
        Lo storico è già in formato long: aggiunge solo la colonna isin.
        """
        if self.price_data_df.empty:
            return pd.DataFrame(columns=['timestamp', 'ticker', 'price', 'isin'])

        # Cache dei mapping ticker -> ISIN (evita lookup ripetuti)
        if self._ticker_to_isin_cache is None:
            self._ticker_to_isin_cache = {}
            if not self.metadata_df.empty:
                self._ticker_to_isin_cache = dict(
                    zip(self.metadata_df['ticker'], self.metadata_df['isin'])
                )

        # Ticker come stringhe semplici, come si aspetta il ChartGenerator
        long_df = self.price_data_df.astype({'ticker': str})

        # Mappa ticker -> ISIN usando la cache (operazione vectorizzata)
        long_df['isin'] = long_df['ticker'].map(self._ticker_to_isin_cache).fillna('')

        return long_df

    def _invalidate_ticker_cache(self):
        """Invalida la cache dei mapping ticker -> ISIN"""
        self._ticker_to_isin_cache = None
        self._ticker_cache.clear()

    @profile()
    def get_closing_price_for_date(self, isin_code: str, target_date) -> Optional[float]:
        """
        Ottiene il prezzo di chiusura per una data specifica.

        Args:
            isin_code: Codice ISIN
            target_date: Data target (datetime.date)

        Returns:
            Prezzo di chiusura o None se non trovato
        """
        ticker = self._ticker_for_isin(isin_code)
        if ticker is None:
            return None

        ticker_data = self._ticker_data(ticker)
        if ticker_data.empty:
            return None

        dates = self._ticker_dates(ticker, ticker_data)
        target_day_data = ticker_data[dates == target_date]

        if target_day_data.empty:
            # take first available date before target_date
            previous_dates = dates[dates < target_date]
            if previous_dates.empty:
                return None
            target_day_data = ticker_data[dates == previous_dates.max()]

        # Prendi l'ultimo prezzo della giornata (chiusura)
        return target_day_data['price'].iloc[-1]

    @profile()
    def get_opening_price_for_date(self, isin_code: str, target_date) -> Optional[float]:
        """
        Ottiene il prezzo di apertura per una data specifica.

        Args:
            isin_code: Codice ISIN
            target_date: Data target (datetime.date)

        Returns:
            Prezzo di apertura o None se non trovato
        """
        ticker = self._ticker_for_isin(isin_code)
        if ticker is None:
            return None

        ticker_data = self._ticker_data(ticker)
        if ticker_data.empty:
            return None

        # Prendi il primo prezzo della giornata (apertura)
        dates = self._ticker_dates(ticker, ticker_data)
        valid_prices = ticker_data.loc[dates == target_date, 'price']

        if valid_prices.empty:
            return None

        return valid_prices.iloc[0]

    @profile()
    def get_oldest_price_for_isin(self, isin_code: str) -> Optional[float]:
        """Restituisce il primo prezzo realmente disponibile nello storico."""
        ticker = self._ticker_for_isin(isin_code)
        if ticker is None:
            return None

        ticker_data = self._ticker_data(ticker)
        if ticker_data.empty:
            return None

        oldest_index = ticker_data['timestamp'].idxmin()
        return float(ticker_data.loc[oldest_index, 'price'])
