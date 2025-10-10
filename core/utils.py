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
                           historical_prices: Optional[Dict[int, float]] = None):
        """
        Genera i dati per la tabella in formato standardizzato.
        
        Returns:
            List[Dict]: Lista di righe con keys: 'label', 'price', 'variation', 'difference'
        """
        table_rows = []
        
        # Riga prezzo attuale vs previous_price
        if previous_price:
            price_change = ((current_price - previous_price) / previous_price) * 100
            price_diff = current_price - previous_price
            table_rows.append({
                'label': 'Prev',
                'price': previous_price,
                'variation': price_change,
                'difference': price_diff,
                'reference_price': previous_price
            })

        # Riga rispetto ad apertura (se disponibile)
        if opening_price and opening_price != current_price:
            price_diff = current_price - opening_price
            price_change = (price_diff / opening_price) * 100
            table_rows.append({
                'label': 'Open',
                'price': opening_price,
                'variation': price_change,
                'difference': price_diff,
                'reference_price': opening_price
            })

        # Righe storiche
        if historical_prices:
            for days in sorted(historical_prices.keys()):
                price = historical_prices[days]
                if price is not None:
                    price_diff = current_price - price
                    variation = (price_diff / price) * 100
                    table_rows.append({
                        'label': f'{days}gg',
                        'price': price,
                        'variation': variation,
                        'difference': price_diff,
                        'reference_price': price
                    })
        
        return table_rows