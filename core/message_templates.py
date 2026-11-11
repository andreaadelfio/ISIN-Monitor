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


def emoji_variazione(variazione: float) -> str:
    return '📈' if variazione > 0 else '📉' if variazione < 0 else '⚪'


def decimali(prezzo: float) -> int:
    """Decimali per i prezzi di un messaggio: 2 da 10 € in su, 3 da 1 €, 4 sotto."""
    return 2 if abs(prezzo) >= 10 else 3 if abs(prezzo) >= 1 else 4


class CaptionTemplates:

    @staticmethod
    def link(isin: str, myfinance_url: Optional[str] = None, borsa_url: Optional[str] = None) -> str:
        """I link al titolo: Fineco · Borsa IT · MyFinance."""
        fineco_url = f"https://finecobank.com/pvt/trading/snapshot/{isin}.AFF"
        # La scheda vera (ETF e BTP non sono fra le azioni), se il monitor l'ha già letta
        borsa_url = borsa_url or f"https://www.borsaitaliana.it/borsa/azioni/scheda/{isin}.html"
        links = [f'<a href="{fineco_url}">Fineco</a>', f'<a href="{borsa_url}">Borsa IT</a>']
        if myfinance_url:
            links.append(f'<a href="{myfinance_url}">MyFinance</a>')
        return ' · '.join(links)

    @staticmethod
    def didascalia_foto(isin_data: Dict, myfinance_url: Optional[str] = None,
                        borsa_url: Optional[str] = None) -> str:
        """La didascalia del grafico: solo il nome e i link (prezzo, variazioni, segnale e
        tabella sono già nell'immagine)."""
        nome = escape(isin_data.get('nome') or isin_data['isin'])
        return f"{nome}\n{CaptionTemplates.link(isin_data['isin'], myfinance_url, borsa_url)}"

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
        links = CaptionTemplates.link(isin_code, myfinance_url, borsa_url)
        company_name = escape(isin_data.get('nome') or isin_code)

        if table_data is None:
            return f"{company_name}: Dati non disponibili\n{links}"

        # Prima riga: nome, prezzo e variazione dall'ultimo prezzo, o da ieri per un grafico
        # chiesto col comando /grafico (è la riga che si vede nella notifica del telefono)
        prima = next((row for row in table_data if row['label'] == 'Prima'), None)
        ieri = next((row for row in table_data if row['label'] == '1gg'), None)
        riferimento = prima or ieri
        variazione = (f" {emoji_variazione(riferimento['variation'])} "
                      f"{riferimento['variation']:+.2f}%" + ('' if prima else ' da ieri')
                      if riferimento else '')
        righe_messaggio = [f"<b>{company_name}</b> €{NumberFormatter.format_number(current_price)}"
                           f"{variazione}"]
        segnale = etichetta_segnale(isin_data.get('segnale'), isin_data.get('punteggio'))
        if segnale:
            righe_messaggio.append(segnale)

        # Tabella a colonne allineate, corta (circa 23 caratteri): sotto la foto il fumetto
        # è largo quanto l'immagine verticale e le righe più lunghe andavano a capo. La
        # differenza in euro e i colori sono nella tabella del grafico
        cifre = decimali(current_price)
        prezzi = [f"€{row['price']:.{cifre}f}" for row in table_data]
        variazioni = [f"{row['variation']:+.2f}%" for row in table_data]
        larghezze = [max((len(testo) for testo in colonna), default=0)
                     for colonna in ([row['label'] for row in table_data], prezzi, variazioni)]
        tabella = []
        for row, prezzo, variaz in zip(table_data, prezzi, variazioni):
            tabella.append(f"{row['label']:<{larghezze[0]}} {prezzo:>{larghezze[1]}} "
                           f"{variaz:>{larghezze[2]}}")
            if row.get('quote'):   # la tua posizione: guadagno o perdita su tutte le quote
                quote = NumberFormatter.format_number(row['quote'])
                tabella.append(f"  {quote} quote: {row['difference'] * row['quote']:+.2f}€")
        if tabella:   # un <code></code> vuoto Telegram lo rifiuta
            righe_messaggio.append("\n<code>" + "\n".join(tabella) + "</code>")
        righe_messaggio.append(links)
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
