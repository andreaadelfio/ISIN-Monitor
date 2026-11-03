#!/usr/bin/env python3
"""
Template delle caption per grafici ISIN Monitor
"""

from html import escape
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
    def format_caption(isin_data: Dict, current_price: float, table_data: Optional[List[Dict]] = None,
                       myfinance_url: Optional[str] = None, borsa_url: Optional[str] = None) -> str:
        """
        Template per caption dei grafici Telegram
        
        Args:
            isin_data: Dati del titolo (isin, nome)
            table_data: Dati pre-calcolati della tabella (richiesti)
            myfinance_url: Link alla scheda del titolo in MyFinance
            borsa_url: Link alla scheda del titolo su Borsa Italiana
        """
        
        # Link cliccabili per varie piattaforme
        isin_code = isin_data['isin']
        
        fineco_url = f"https://finecobank.com/pvt/trading/snapshot/{isin_code}.AFF"
        # La scheda vera (ETF e BTP non sono fra le azioni), se il monitor l'ha già letta
        borsa_url = borsa_url or f"https://www.borsaitaliana.it/borsa/azioni/scheda/{isin_code}.html"
        links = [f'<a href="{fineco_url}">Fineco</a>', f'<a href="{borsa_url}">Borsa IT</a>']
        if myfinance_url:
            links.append(f'<a href="{myfinance_url}">MyFinance</a>')
        
        company_name = escape(isin_data.get('nome') or isin_code)
        
        # Usa i dati pre-calcolati (devono essere sempre forniti)
        if table_data is None:
            return f"{company_name}: Dati non disponibili ({' | '.join(links)})"

        # La variazione dall'ultimo prezzo subito dopo il prezzo: si vede già nella notifica
        prima = next((row for row in table_data if row['label'] == 'Prev'), None)
        variazione = (f" {CaptionTemplates._get_percentage_emoji(prima['variation'])} "
                      f"{prima['variation']:+.2f}%" if prima else '')
        message = (f"<b>{company_name}</b> €{NumberFormatter.format_number(current_price)}{variazione} "
                   f"({' | '.join(links)})")

        # Colonne allineate (circa 34 caratteri): sul telefono ogni riga sta su una riga
        prezzi = [f"€{NumberFormatter.format_number(row['price'], max_decimals=4)}" for row in table_data]
        variazioni = [f"{row['variation']:+.3f}%" for row in table_data]
        differenze = [f"{row['difference']:+.3f}" for row in table_data]
        larghezze = [max((len(testo) for testo in colonna), default=0)
                     for colonna in ([row['label'] for row in table_data], prezzi, variazioni, differenze)]
        righe = []
        for row, prezzo, variazione, differenza in zip(table_data, prezzi, variazioni, differenze):
            emoji = CaptionTemplates._get_percentage_emoji(row['variation'], is_positive_good=True)
            righe.append(f"{row['label']:<{larghezze[0]}} {prezzo:<{larghezze[1]}} "
                         f"{variazione:>{larghezze[2]}} {emoji} {differenza:>{larghezze[3]}}")
            if row.get('quote'):   # la tua posizione: guadagno o perdita su tutte le quote
                quote = NumberFormatter.format_number(row['quote'])
                righe.append(f"{'':<{larghezze[0]}} {quote} quote: {row['difference'] * row['quote']:+.2f}€")
        if righe:   # un <code></code> vuoto Telegram lo rifiuta
            message += "\n\n<code>" + "\n".join(righe) + "</code>"

        return message
    
    @staticmethod
    @profile()
    def format_test_caption() -> str:
        return "🧪 Test ISIN Monitor OK!"