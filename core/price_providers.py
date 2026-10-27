#!/usr/bin/env python3
"""
Fonti dei prezzi: Borsa Italiana (in tempo reale, per gli avvisi) e Yahoo Finance
(solo per riempire i buchi dello storico, mai al momento di un avviso).
"""

import requests
import re
import pandas as pd
from typing import Any, Dict, Optional, Tuple
from datetime import datetime
import time
from .profiler import profile


class BorsaItalianaProvider:
    """Prezzo in tempo reale dalla scheda del titolo su Borsa Italiana (per ISIN)."""

    def __init__(self, timeout: float = 10):
        self.timeout = timeout
        # Sessione condivisa: riusa la connessione HTTPS tra un titolo e l'altro
        self.session = requests.Session()

    @profile()
    def get_price(self, isin: str) -> Tuple[Optional[float], Optional[str]]:
        """Prezzo e nome del titolo, oppure (None, None)."""
        price, company_name, _ = self._fetch_data_for_isin(isin)
        return price, company_name

    def _fetch_data_for_isin(self, isin: str) -> Tuple[Optional[float], Optional[str], Optional[datetime]]:
        """Recupera prezzo e nome azienda per un ISIN in una singola richiesta."""
        
        markets = [
            ("italiano", f"https://www.borsaitaliana.it/borsa/azioni/scheda/{isin}.html"),
            ("globale", f"https://www.borsaitaliana.it/borsa/azioni/global-equity-market/scheda/{isin}.html")
        ]
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        }
        
        for market_type, url in markets:
            try:
                response = self.session.get(url, headers=headers, timeout=self.timeout)
                if response.status_code == 200:
                    html_content = response.text
                    
                    # Estrai sia prezzo che nome azienda dalla stessa risposta
                    price = self._extract_price_from_html(html_content)
                    company_name = self._extract_company_name_from_html(html_content)
                    
                    if price is not None:
                        market_timestamp = datetime.now()
                        print(f"✅ Prezzo trovato: €{price:.4f}")
                        if company_name:
                            print(f"✅ Nome azienda: {company_name}")
                        return price, company_name, market_timestamp
                    else:
                        print(f"❌ Prezzo non estratto da {market_type}")
                else:
                    print(f"❌ Status {response.status_code} per {market_type}")
                    
            except Exception as e:
                print(f"❌ Errore per {market_type}: {e}")
                continue
        
        print(f"❌ Nessun dato trovato per ISIN {isin}")
        return None, None, None

    def _extract_price_from_html(self, html_content):
        """Estrae il prezzo dal contenuto HTML usando il metodo formatPrice."""
        try:
            # Metodo principale: cerca formatPrice + strong
            pattern = r'-formatPrice[^>]*>\s*<strong[^>]*>([^<]+)</strong>'
            matches = re.findall(pattern, html_content, re.IGNORECASE)
            
            if matches:
                price_text = matches[0].strip()
                price = self._parse_price_string(price_text)
                if price is not None:
                    return price
            
            # Metodo fallback: cerca strong generici con numeri
            strong_pattern = r'<strong[^>]*>([0-9]+[,\.][0-9]+)</strong>'
            strong_matches = re.findall(strong_pattern, html_content)
            
            for match in strong_matches:
                price = self._parse_price_string(match)
                if price is not None and 0.001 <= price <= 100000:
                    return price
            
            return None
        
        except Exception as e:
            print(f"❌ Errore estrazione prezzo: {e}")
            return None

    def _extract_company_name_from_html(self, html_content: str) -> Optional[str]:
        """Estrae il nome dell'azienda dal contenuto HTML di Borsa Italiana."""
        try:
            # Pattern principale: cerca la classe specifica t-text -flola-bold -size-xlg -inherit
            # che contiene il nome dell'azienda in un tag <a> dentro <h1>
            main_pattern = r'<h1[^>]*class="[^"]*t-text[^"]*-flola-bold[^"]*-size-xlg[^"]*-inherit[^"]*"[^>]*>\s*<a[^>]*>([^<]+)</a>\s*</h1>'
            main_match = re.search(main_pattern, html_content, re.IGNORECASE)
            
            if main_match:
                company_name = main_match.group(1).strip()
                if company_name and len(company_name) > 2:
                    return company_name
            
            # Pattern alternativo: cerca solo la classe senza il tag <a>
            alt_pattern = r'class="[^"]*t-text[^"]*-flola-bold[^"]*-size-xlg[^"]*-inherit[^"]*"[^>]*>([^<]+)<'
            alt_match = re.search(alt_pattern, html_content, re.IGNORECASE)
            
            if alt_match:
                company_name = alt_match.group(1).strip()
                if company_name and len(company_name) > 2:
                    return company_name
            
            # Fallback: pattern originale per il titolo
            title_pattern = r'<title>Azioni\s+([^:]+):\s*quotazioni'
            title_match = re.search(title_pattern, html_content, re.IGNORECASE)
            
            if title_match:
                company_name = title_match.group(1).strip()
                if company_name and len(company_name) > 2:
                    return company_name
            
            return None
            
        except Exception as e:
            print(f"❌ Errore estrazione nome azienda: {e}")
            return None

    def _parse_price_string(self, price_str: str) -> Optional[float]:
        """Converte stringa prezzo in float."""
        if not price_str:
            return None
        
        try:
            # Rimuovi tutto tranne numeri, virgole e punti
            clean_price = re.sub(r'[^\d,.]', '', str(price_str))
            
            if not clean_price:
                return None
            
            # Gestisci formato italiano (virgola come decimale)
            if ',' in clean_price and '.' not in clean_price:
                # Solo virgola - assume sempre decimale per prezzi finanziari
                clean_price = clean_price.replace(',', '.')
            elif ',' in clean_price and '.' in clean_price:
                # Formato italiano: 1.234,56
                if clean_price.rfind(',') > clean_price.rfind('.'):
                    clean_price = clean_price.replace('.', '').replace(',', '.')
                else:
                    # Formato US: 1,234.56
                    clean_price = clean_price.replace(',', '')
            
            price = float(clean_price)
            
            # Sanity check
            if 0.001 <= price <= 100000:
                return price
            
            return None
                
        except (ValueError, TypeError):
            return None


class YahooFinanceProvider:
    """Storico Yahoo (chart API) per riempire i buchi della tabella prezzi."""

    URL = "https://query2.finance.yahoo.com/v8/finance/chart"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        settings = config or {}
        self.timeout = int(settings.get("timeout", 20))
        self.max_retries = max(0, int(settings.get("max_retries", 2)))
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ISIN-Monitor/1.0"})

    def get_series(self, symbol: str, period: str, interval: str) -> pd.DataFrame:
        """Prezzi di chiusura di ogni barra: colonne ts (UTC) e price.

        Es. period '7d' con interval '1m', '60d' con '5m', '1y' con '1d'
        (Yahoo dà il dato al minuto solo per gli ultimi 7 giorni, ai 5 minuti per 60).
        """
        params = {
            "range": period,
            "interval": interval,
            "events": "history",
            "includePrePost": "false",
            "includeAdjustedClose": "false",
        }
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    f"{self.URL}/{symbol}", params=params, timeout=self.timeout
                )
                if response.status_code == 429 and attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                payload = response.json()
                result = payload.get("chart", {}).get("result")
                if not result:
                    error = payload.get("chart", {}).get("error")
                    raise ValueError(f"Risposta Yahoo vuota: {error}")
                return self._result_to_frame(result[0])
            except (requests.RequestException, ValueError, KeyError, TypeError) as error:
                last_error = error
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                    continue
                break

        raise RuntimeError(
            f"Impossibile scaricare lo storico Yahoo per {symbol}: {last_error}"
        )

    @staticmethod
    def _result_to_frame(result: Dict[str, Any]) -> pd.DataFrame:
        timestamps = result.get("timestamp") or []
        quote = (result.get("indicators", {}).get("quote") or [{}])[0]
        series = pd.DataFrame(
            {
                "ts": pd.to_datetime(timestamps, unit="s", utc=True),
                "price": pd.to_numeric(pd.Series(quote.get("close") or [None] * len(timestamps)),
                                       errors="coerce"),
            }
        ).dropna()
        series = series[series["price"] > 0]
        return series.sort_values("ts").reset_index(drop=True)
