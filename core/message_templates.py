#!/usr/bin/env python3
"""
Template delle caption per grafici ISIN Monitor
"""

from typing import Dict, Optional, List
from .utils import NumberFormatter
from .profiler import profile

class CaptionTemplates:
    
    @staticmethod
    def _get_percentage_emoji(percentage: float, is_positive_good: bool = True) -> str:
        """
        Restituisce l'emoji grafico/trend appropriata per una percentuale
        
        Args:
            percentage: La percentuale di variazione
            is_positive_good: True se valori positivi sono buoni (default), False altrimenti
        """
        if percentage > 0:
            return "📈" if is_positive_good else "📉"
        elif percentage < 0:
            return "📉" if is_positive_good else "📈"
        else:
            return "⚪"

    @staticmethod
    @profile()
    def format_caption(isin_data: Dict, current_price: float, table_data: Optional[List[Dict]] = None) -> str:
        """
        Template per caption dei grafici Telegram
        
        Args:
            isin_data: Dati ISIN con ticker, target_discount, etc.
            table_data: Dati pre-calcolati della tabella (richiesti)
        """
        
        # Link cliccabili per varie piattaforme
        isin_code = isin_data['isin']
        ticker = isin_data['ticker']
        
        fineco_url = f"https://finecobank.com/pvt/trading/snapshot/{isin_code}.AFF"
        borsa_url = f"https://www.borsaitaliana.it/borsa/azioni/scheda/{isin_code}.html"
        
        # Nome dell'azienda (fallback su ticker se non disponibile)
        company_name = isin_data.get('company_name', ticker)
        
        # Usa i dati pre-calcolati (devono essere sempre forniti)
        if table_data is None:
            return f"{company_name}: Dati non disponibili"

        message = f"""{company_name}, €{current_price} (<a href="{fineco_url}">Fineco</a> | <a href="{borsa_url}">Borsa IT</a>)"""
        message += """\n\n<code>"""

        # Aggiungi tutte le altre righe (esclusa "Now")
        for row in table_data:
            variation_emoji = CaptionTemplates._get_percentage_emoji(row['variation'], is_positive_good=True)
            price_formatted = NumberFormatter.format_number(row['price'], max_decimals=4)
            message += f"{row['label']}: €{price_formatted} ({row['variation']:+.3f}% {variation_emoji}) {row['difference']:+.3f}\n"

        message += "\r</code>"

        return message
    
    @staticmethod
    @profile()
    def format_test_caption() -> str:
        return "🧪 Test ISIN Monitor OK!"