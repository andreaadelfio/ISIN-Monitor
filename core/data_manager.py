#!/usr/bin/env python3
"""
Gestione dati per ISIN Monitor
Gestisce prezzi e metadati in formato pulito e semplificato
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import os
from .profiler import profile


class DataManager:
    """Manager semplificato per gestione prezzi e metadati."""
    
    def __init__(self, config: Dict):
        self.config = config
        self.price_data_df = pd.DataFrame()
        self.metadata_df = pd.DataFrame()
        
        # File paths - usa direttamente la configurazione CSV
        self.metadata_file = config['data']['isin_config_file']
        self.price_file = 'price_history_wide.csv'
        
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
        
        # Carica prezzi
        if os.path.exists(self.price_file):
            try:
                self.price_data_df = pd.read_csv(self.price_file)
                self.price_data_df['timestamp'] = pd.to_datetime(self.price_data_df['timestamp'])
                
                # Pulisci dati vecchi
                self._cleanup_old_data()
                print(f"📊 Dati prezzi caricati: {len(self.price_data_df)} record")
                        
            except Exception as e:
                print(f"⚠️ Errore caricamento prezzi: {e}")
                self._create_empty_price_data()
        else:
            print("📊 Formato wide già presente, uso quello")
            self._create_empty_price_data()
    
    def _create_empty_metadata(self):
        """Crea DataFrame metadati vuoto."""
        self.metadata_df = pd.DataFrame(columns=['ticker', 'isin', 'target_discount'])
    
    def _create_empty_price_data(self):
        """Crea DataFrame prezzi vuoto."""
        self.price_data_df = pd.DataFrame(columns=['timestamp'])
    
    def _cleanup_old_data(self):
        """Rimuove dati più vecchi di max_history_days."""
        max_days = self.config['data']['max_history_days']
        cutoff_date = datetime.now() - timedelta(days=max_days)
        old_count = len(self.price_data_df)
        self.price_data_df = self.price_data_df[
            self.price_data_df['timestamp'] > cutoff_date
        ]
        cleaned_count = old_count - len(self.price_data_df)
        if cleaned_count > 0:
            print(f"🧹 Rimossi {cleaned_count} record più vecchi di {max_days} giorni")
    
    @profile()    
    def save_data(self) -> None:
        """Salva prezzi (i metadati sono read-only dal CSV configurato)."""
        try:
            self._cleanup_old_data()
            
            # Salva solo i prezzi
            save_df = self.price_data_df.copy()
            
            # Converti le date in stringa solo se sono datetime
            if pd.api.types.is_datetime64_any_dtype(save_df['timestamp']):
                save_df['timestamp'] = save_df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
                
            save_df.to_csv(self.price_file, index=False)
            
            # Statistiche
            ticker_columns = [col for col in self.price_data_df.columns 
                            if col not in ['timestamp']]
            print(f"💾 Dati salvati: {len(self.price_data_df)} record, {len(ticker_columns)} ticker")
            
        except Exception as e:
            print(f"❌ Errore salvataggio: {e}")
    
    @profile()    
    def add_price(self, ticker: str, price: float) -> datetime:
        """Aggiunge un prezzo per un ticker."""
        now = datetime.now()
        
        # Aggiungi colonna ticker se non esiste
        if ticker not in self.price_data_df.columns:
            self.price_data_df[ticker] = np.nan
        
        # Crea nuovo record
        new_row = pd.DataFrame([{
            'timestamp': now,
            ticker: price
        }])
        
        # Aggiungi colonne mancanti con NaN
        for col in self.price_data_df.columns:
            if col not in new_row.columns:
                new_row[col] = np.nan
        
        # Concatena
        if self.price_data_df.empty:
            self.price_data_df = new_row
        else:
            self.price_data_df = pd.concat([self.price_data_df, new_row], ignore_index=True)
        
        return now
    
    @profile()    
    def get_last_price(self, ticker: str) -> Optional[float]:
        """Ottiene l'ultimo prezzo per un ticker."""
        if ticker not in self.price_data_df.columns or self.price_data_df.empty:
            return None
        
        ticker_data = self.price_data_df[self.price_data_df[ticker].notna()]
        if ticker_data.empty:
            return None
        
        return ticker_data.iloc[-1][ticker]
    
    @profile()    
    def get_max_prices_for_days(self, ticker: str, days_list: List[int]) -> Dict[int, Optional[float]]:
        """Calcola i prezzi massimi per una lista di periodi."""
        if ticker not in self.price_data_df.columns or self.price_data_df.empty:
            return {days: None for days in days_list}
        
        result = {}
        for days in days_list:
            cutoff_date = datetime.now() - timedelta(days=days)
            recent_data = self.price_data_df[
                (self.price_data_df['timestamp'] > cutoff_date) & 
                (self.price_data_df[ticker].notna())
            ]
            
            if recent_data.empty:
                recent_data = self.price_data_df[self.price_data_df[ticker].notna()]
            
            result[days] = recent_data[ticker].max() if not recent_data.empty else None
        
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
        Converte in formato long per il ChartGenerator.
        VERSIONE OTTIMIZZATA con cache e vectorizzazione.
        """
        if self.price_data_df.empty:
            return pd.DataFrame(columns=['timestamp', 'ticker', 'price', 'isin'])
        
        # Cache dei mapping ticker -> ISIN (evita lookup ripetuti)
        if not hasattr(self, '_ticker_to_isin_cache'):
            self._ticker_to_isin_cache = {}
            if not self.metadata_df.empty:
                self._ticker_to_isin_cache = dict(
                    zip(self.metadata_df['ticker'], self.metadata_df['isin'])
                )
        
        ticker_columns = [col for col in self.price_data_df.columns 
                         if col not in ['timestamp']]
        
        # OTTIMIZZAZIONE: Usa pandas melt() invece di loop manuali
        # Questo è ordini di grandezza più veloce
        long_df = pd.melt(
            self.price_data_df,
            id_vars=['timestamp'],
            value_vars=ticker_columns,
            var_name='ticker',
            value_name='price'
        )
        
        # Rimuovi righe con prezzi NaN
        long_df = long_df.dropna(subset=['price'])
        
        # Mappa ticker -> ISIN usando la cache (operazione vectorizzata)
        long_df['isin'] = long_df['ticker'].map(self._ticker_to_isin_cache).fillna('')
        
        return long_df
    
    def _invalidate_ticker_cache(self):
        """Invalida la cache dei mapping ticker -> ISIN"""
        if hasattr(self, '_ticker_to_isin_cache'):
            delattr(self, '_ticker_to_isin_cache')

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
        # Trova il ticker dal metadati
        if self.metadata_df.empty:
            return None
            
        ticker_row = self.metadata_df[self.metadata_df['isin'] == isin_code]
        if ticker_row.empty:
            return None
            
        ticker = ticker_row.iloc[0]['ticker']
        
        # Controlla se il ticker esiste nei dati prezzi
        if ticker not in self.price_data_df.columns:
            return None
        
        # Filtra per la data target
        target_day_data = self.price_data_df[
            self.price_data_df['timestamp'].dt.date == target_date
        ]
        
        if target_day_data.empty:
            return None
        
        # Prendi l'ultimo prezzo della giornata (chiusura)
        valid_prices = target_day_data[ticker].dropna()
        
        if valid_prices.empty:
            return None
            
        return valid_prices.iloc[-1]

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
        # Trova il ticker dal metadati
        if self.metadata_df.empty:
            return None
            
        ticker_row = self.metadata_df[self.metadata_df['isin'] == isin_code]
        if ticker_row.empty:
            return None
            
        ticker = ticker_row.iloc[0]['ticker']
        
        # Controlla se il ticker esiste nei dati prezzi
        if ticker not in self.price_data_df.columns:
            return None
        
        # Filtra per la data target
        target_day_data = self.price_data_df[
            self.price_data_df['timestamp'].dt.date == target_date
        ]
        
        if target_day_data.empty:
            return None
        
        # Prendi il primo prezzo della giornata (apertura)
        valid_prices = target_day_data[ticker].dropna()
        
        if valid_prices.empty:
            return None
            
        return valid_prices.iloc[0]