#!/usr/bin/env python3
"""
Utilità condivise per ISIN Monitor
"""

from typing import Dict, Optional
from .profiler import profile


class NumberFormatter:
    """Classe per formattazione uniforme dei numeri nel sistema."""
    
    @staticmethod
    @profile()
    def format_number(value: float, max_decimals: int = 4) -> str:
        """
        Formatta i numeri in modo intelligente:
        - 0 -> "0" (non "0.000")
        - 0.45943 -> "0.459" (max 4 decimali)
        - 1.0 -> "1" (rimuove .0)
        - 123.456789 -> "123.457" (max 4 decimali)
        
        Args:
            value: Il valore numerico da formattare
            max_decimals: Numero massimo di decimali (default 4)
            
        Returns:
            str: Valore formattato
        """
        if value == 0:
            return "0"
        
        # Arrotonda al numero massimo di decimali
        rounded = round(value, max_decimals)
        
        # Usa :g per rimuovere zeri finali, ma limita i decimali
        formatted = f"{rounded:.{max_decimals}f}".rstrip('0').rstrip('.')
        
        return formatted


class TableDataGenerator:
    """Classe per generazione dati delle tabelle finanziarie."""
    
    @staticmethod
    @profile()
    def generate_table_data(current_price: float, opening_price: Optional[float] = None,
                            previous_price: Optional[float] = None,
                            historical_prices: Optional[Dict[int, float]] = None,
                            oldest_price: Optional[float] = None,
                            position: Optional[Dict] = None,
                            extremes: Optional[tuple] = None):
        """Le righe della tabella: {'label', 'price', 'variation', 'difference'} (più 'quote'
        per il carico), con variazione e differenza del prezzo attuale da ogni riferimento."""

        def riga(label: str, price: float, **altro) -> Dict:
            difference = current_price - price
            return {'label': label, 'price': price, 'variation': difference / price * 100,
                    'difference': difference, **altro}

        righe = []
        if previous_price:
            righe.append(riga('Prima', previous_price))
        if opening_price and opening_price != current_price:
            righe.append(riga('Apertura', opening_price))
        for days, price in sorted((historical_prices or {}).items()):
            if price is not None:
                righe.append(riga(f'{days}gg', price))
        if oldest_price is not None and oldest_price > 0:
            righe.append(riga('Inizio', oldest_price))
        # Massimo e minimo del periodo più lungo dei grafici (le righe del pannello annuale)
        for label, price in zip(('Max', 'Min'), extremes or ()):
            if price:
                righe.append(riga(label, price))
        # La tua posizione (prezzo di carico di MyFinance), con le quote per il totale
        if position:
            righe.append(riga('Carico', position['prezzo'], quote=position['quote']))
        return righe
