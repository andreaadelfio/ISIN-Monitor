#!/usr/bin/env python3
"""
Provider di prezzi semplificato per Borsa Italiana
"""

import requests
import re
import pandas as pd
from typing import Any, Dict, Optional, Tuple
from datetime import datetime, timedelta
import time
from .profiler import profile


class BorsaItalianaProvider:
    """Provider per Borsa Italiana con estrazione prezzo migliorata."""
    
    def __init__(self):
        self.metadata_df = self._load_metadata()
        self._isin_by_ticker = dict(
            zip(self.metadata_df.get('ticker', []), self.metadata_df.get('isin', []))
        )
        self._name_by_ticker = dict(
            zip(self.metadata_df.get('ticker', []), self.metadata_df.get('company_name', []))
        )
        # Sessione condivisa: riusa la connessione HTTPS tra un ticker e l'altro
        self.session = requests.Session()
        
    def _load_metadata(self):
        """Carica i metadati dal CSV."""
        try:
            return pd.read_csv("isin_metadata.csv")
        except Exception as e:
            print(f"⚠️ Errore caricamento metadati: {e}")
            return pd.DataFrame(columns=['ticker', 'isin', 'company_name', 'target_discount'])

    @profile()

    def get_isin_for_ticker(self, ticker: str) -> Optional[str]:
        """Converte ticker in ISIN."""
        isin = self._isin_by_ticker.get(ticker)
        if not isin:
            print(f"⚠️ Ticker {ticker} non trovato")
            return None
        return isin

    @profile()

    def get_price(self, ticker: str) -> Tuple[Optional[float], Optional[datetime]]:
        """Ottiene il prezzo per un ticker."""
        print(f"🔄 Converto {ticker} → ISIN", end="")
        isin = self.get_isin_for_ticker(ticker)
        if not isin:
            return None, None
        print(f" {isin}")
        
        price, company_name, timestamp = self._fetch_data_for_isin(isin)
        
        # Aggiorna il nome dell'azienda nel metadata se trovato
        if company_name:
            self._update_company_name_in_metadata(ticker, company_name)
        
        return price, timestamp

    @profile()

    def get_company_name(self, ticker: str) -> Optional[str]:
        """Ottiene il nome dell'azienda per un ticker."""
        # Prima controlla se abbiamo già il nome nei metadati
        existing_name = self._name_by_ticker.get(ticker)
        if pd.notna(existing_name) and existing_name and existing_name != ticker:
            return existing_name
        
        # Se non abbiamo il nome, recuperalo via web
        isin = self.get_isin_for_ticker(ticker)
        if not isin:
            return ticker
        
        _, company_name, _ = self._fetch_data_for_isin(isin)
        
        if company_name:
            self._update_company_name_in_metadata(ticker, company_name)
            return company_name
        
        return ticker

    def _update_company_name_in_metadata(self, ticker: str, company_name: str):
        """Aggiorna il nome dell'azienda nei metadati in memoria."""
        self._name_by_ticker[ticker] = company_name
        ticker_idx = self.metadata_df.index[
            self.metadata_df['ticker'] == ticker
        ]
        if len(ticker_idx) > 0:
            self.metadata_df.loc[ticker_idx[0], 'company_name'] = company_name

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
                response = self.session.get(url, headers=headers, timeout=10)
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
    """Provider Yahoo per lo storico usato esclusivamente dai grafici."""

    URL = "https://query2.finance.yahoo.com/v8/finance/chart"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        settings = config or {}
        self.timeout = int(settings.get("timeout", 20))
        self.max_retries = max(0, int(settings.get("max_retries", 2)))
        self.cache_ttl = max(0, int(settings.get("cache_ttl_seconds", 300)))
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ISIN-Monitor/1.0"})
        self._history_cache: Dict[str, Tuple[datetime, pd.DataFrame]] = {}

    def get_history(
        self,
        ticker: str,
        isin: str,
        daily_range: str = "1y",
        intraday_range: str = "1mo",
        intraday_interval: str = "1h",
    ) -> pd.DataFrame:
        """Scarica storico giornaliero e intraday, mantenendolo solo in memoria."""
        cached = self._history_cache.get(ticker)
        if cached and datetime.now() - cached[0] < timedelta(seconds=self.cache_ttl):
            return cached[1].copy()

        daily = self._fetch_series(ticker, daily_range, "1d", isin)
        intraday = self._fetch_series(
            ticker, intraday_range, intraday_interval, isin
        )
        history = pd.concat([daily, intraday], ignore_index=True)
        history = (
            history.drop_duplicates(subset=["timestamp"], keep="last")
            .sort_values("timestamp")
            .reset_index(drop=True)
        )
        if history.empty:
            raise ValueError(f"Nessun dato storico restituito da Yahoo per {ticker}")

        self._history_cache[ticker] = (datetime.now(), history)
        return history.copy()

    def get_price(
        self, ticker: str, isin: str
    ) -> Tuple[Optional[float], Optional[datetime]]:
        """Restituisce l'ultima chiusura disponibile come fallback realtime."""
        history = self._fetch_series(ticker, "5d", "1d", isin)
        if history.empty:
            return None, None
        last_row = history.iloc[-1]
        return float(last_row["price"]), last_row["timestamp"].to_pydatetime()

    def _fetch_series(
        self, ticker: str, period: str, interval: str, isin: str
    ) -> pd.DataFrame:
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
                    f"{self.URL}/{ticker}", params=params, timeout=self.timeout
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
                return self._result_to_frame(result[0], ticker, isin)
            except (requests.RequestException, ValueError, KeyError, TypeError) as error:
                last_error = error
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                    continue
                break

        raise RuntimeError(
            f"Impossibile scaricare lo storico Yahoo per {ticker}: {last_error}"
        )

    @staticmethod
    def _result_to_frame(
        result: Dict[str, Any], ticker: str, isin: str
    ) -> pd.DataFrame:
        timestamps = result.get("timestamp", [])
        quote = result.get("indicators", {}).get("quote", [{}])[0]
        history = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(timestamps, unit="s", utc=True)
                .tz_convert("Europe/Rome")
                .tz_localize(None),
                "price": quote.get("close", []),
            }
        ).dropna(subset=["timestamp", "price"])
        history["ticker"] = ticker
        history["isin"] = isin
        history["price"] = pd.to_numeric(history["price"], errors="coerce")
        history = history.dropna(subset=["price"])
        if (history["price"] <= 0).any():
            raise ValueError(f"Prezzi Yahoo non validi per {ticker}")
        return history.sort_values("timestamp").reset_index(drop=True)


@profile()

def get_provider():
    """Restituisce il provider."""
    return BorsaItalianaProvider()
