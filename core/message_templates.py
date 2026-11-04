#!/usr/bin/env python3
"""
Template delle caption per grafici ISIN Monitor
"""

from html import escape
from typing import Dict, Optional, List
from .profiler import profile
from .proposte import ETICHETTE, PALLINI
from .utils import NumberFormatter


def etichetta_segnale(segnale: Optional[str], punteggio) -> Optional[str]:
    """La riga del segnale di MyFinance, es. '🟢 MyFinance: Compra · 72/100', o None."""
    if segnale not in ETICHETTE:
        return None
    return (f"{PALLINI[segnale]} MyFinance: {ETICHETTE[segnale]}"
            + (f" · {punteggio}/100" if punteggio is not None else ''))


def decimali(prezzo: float) -> int:
    """Decimali per i prezzi di un messaggio: 2 da 10 € in su, 3 da 1 €, 4 sotto."""
    return 2 if abs(prezzo) >= 10 else 3 if abs(prezzo) >= 1 else 4


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
        
        isin_code = isin_data['isin']
        fineco_url = f"https://finecobank.com/pvt/trading/snapshot/{isin_code}.AFF"
        # La scheda vera (ETF e BTP non sono fra le azioni), se il monitor l'ha già letta
        borsa_url = borsa_url or f"https://www.borsaitaliana.it/borsa/azioni/scheda/{isin_code}.html"
        links = [f'<a href="{fineco_url}">Fineco</a>', f'<a href="{borsa_url}">Borsa IT</a>']
        if myfinance_url:
            links.append(f'<a href="{myfinance_url}">MyFinance</a>')
        company_name = escape(isin_data.get('nome') or isin_code)

        if table_data is None:
            return f"{company_name}: Dati non disponibili\n{' · '.join(links)}"

        # Prima riga: nome, prezzo e variazione dall'ultimo prezzo, o da ieri per un grafico
        # chiesto col comando /grafico (è la riga che si vede nella notifica del telefono)
        prima = next((row for row in table_data if row['label'] == 'Prima'), None)
        ieri = next((row for row in table_data if row['label'] == '1gg'), None)
        riferimento = prima or ieri
        variazione = (f" {CaptionTemplates._get_percentage_emoji(riferimento['variation'])} "
                      f"{riferimento['variation']:+.2f}%" + ('' if prima else ' da ieri')
                      if riferimento else '')
        righe_messaggio = [f"<b>{company_name}</b> €{NumberFormatter.format_number(current_price)}"
                           f"{variazione}"]
        segnale = etichetta_segnale(isin_data.get('segnale'), isin_data.get('punteggio'))
        if segnale:
            righe_messaggio.append(segnale)

        # Tabella a colonne allineate (circa 35 caratteri, una riga sul telefono). L'emoji va
        # in fondo: nel testo a larghezza fissa di Telegram non è larga come le lettere
        cifre = decimali(current_price)
        prezzi = [f"€{row['price']:.{cifre}f}" for row in table_data]
        variazioni = [f"{row['variation']:+.2f}%" for row in table_data]
        differenze = [f"{row['difference']:+.{cifre}f}" for row in table_data]
        larghezze = [max((len(testo) for testo in colonna), default=0)
                     for colonna in ([row['label'] for row in table_data], prezzi, variazioni, differenze)]
        tabella = []
        for row, prezzo, variaz, differenza in zip(table_data, prezzi, variazioni, differenze):
            emoji = CaptionTemplates._get_percentage_emoji(row['variation'], is_positive_good=True)
            tabella.append(f"{row['label']:<{larghezze[0]}} {prezzo:<{larghezze[1]}} "
                           f"{variaz:>{larghezze[2]}} {differenza:>{larghezze[3]}} {emoji}")
            if row.get('quote'):   # la tua posizione: guadagno o perdita su tutte le quote
                quote = NumberFormatter.format_number(row['quote'])
                tabella.append(f"{'':<{larghezze[0]}} {quote} quote: {row['difference'] * row['quote']:+.2f}€")
        if tabella:   # un <code></code> vuoto Telegram lo rifiuta
            righe_messaggio.append("\n<code>" + "\n".join(tabella) + "</code>")
        righe_messaggio.append(' · '.join(links))
        message = "\n".join(righe_messaggio)

        return message
    
    @staticmethod
    @profile()
    def format_test_caption(titoli: int = 0, orario: str = '') -> str:
        """Il messaggio di prova: Telegram funziona, quanti titoli segue il monitor e quando."""
        righe = ["🧪 <b>ISIN Monitor</b>: Telegram funziona"]
        if titoli:
            righe.append(f"Titoli seguiti: {titoli}" + (f" · orario {orario}" if orario else ''))
        righe.append("Comandi del bot (a monitor acceso): /prezzi /grafico /stato /aiuto")
        return '\n'.join(righe)
