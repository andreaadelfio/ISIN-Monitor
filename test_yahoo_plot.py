#!/usr/bin/env python3
"""Proof of concept: generate an ISIN plot from Yahoo Finance in memory."""

import argparse
import io
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import requests
from PIL import Image

from core.chart_generator import ChartGenerator
from core.message_templates import CaptionTemplates
from core.utils import TableDataGenerator


SYMBOL = "ENI.MI"
ISIN = "IT0003132476"
COMPANY_NAME = "Eni"
YAHOO_URL = "https://query2.finance.yahoo.com/v8/finance/chart"


def fetch_daily_history(symbol: str, period: str = "1y") -> tuple[pd.DataFrame, Dict[str, Any]]:
    """Fetch daily closes and metadata without writing a local data file."""
    response = requests.get(
        f"{YAHOO_URL}/{symbol}",
        params={"range": period, "interval": "1d", "events": "history"},
        headers={"User-Agent": "ISIN-Monitor/1.0"},
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]

    history = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(result["timestamp"], unit="s"),
            "price": quote["close"],
        }
    ).dropna(subset=["timestamp", "price"])
    history["ticker"] = symbol
    history["isin"] = ISIN
    history = history.sort_values("timestamp").reset_index(drop=True)

    if history.empty:
        raise ValueError(f"Nessun dato storico restituito per {symbol}")
    if not history["timestamp"].is_monotonic_increasing:
        raise ValueError("La serie storica non è ordinata cronologicamente")
    if history["price"].le(0).any():
        raise ValueError("La serie contiene prezzi non validi")

    return history, result["meta"]


def create_plot(history: pd.DataFrame, metadata: Dict[str, Any]) -> tuple[bytes, str]:
    """Create and validate a PNG using only the in-memory history."""
    current_price = float(history["price"].iloc[-1])
    previous_price = float(history["price"].iloc[-2]) if len(history) > 1 else None
    historical_prices = {}
    for days in (1, 7, 30, 360):
        target = datetime.now() - pd.Timedelta(days=days)
        candidates = history[history["timestamp"] <= target]
        if not candidates.empty:
            historical_prices[days] = float(candidates["price"].iloc[-1])

    table_data = TableDataGenerator.generate_table_data(
        current_price=current_price,
        previous_price=previous_price,
        historical_prices=historical_prices,
        oldest_price=float(history["price"].iloc[0]),
    )
    chart = ChartGenerator(history, comparison_days=[7, 30, 360])
    image = chart.create_comprehensive_chart(
        {
            "ticker": SYMBOL,
            "isin": ISIN,
            "target_discount": 0,
            "company_name": metadata.get("longName", COMPANY_NAME),
        },
        current_price,
        previous_price=previous_price,
        table_data=table_data,
    )
    Image.open(io.BytesIO(image)).verify()
    return image, CaptionTemplates.format_caption(
        {
            "ticker": SYMBOL,
            "isin": ISIN,
            "company_name": metadata.get("longName", COMPANY_NAME),
        },
        current_price,
        table_data,
    )


def send_to_telegram(image: bytes, caption: str, config_path: Path) -> None:
    """Send the in-memory PNG to Telegram when explicitly requested."""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    telegram = config["telegram"]
    if not telegram.get("enabled") or not telegram.get("bot_token"):
        raise ValueError("Telegram non configurato nel file JSON")

    response = requests.post(
        f"https://api.telegram.org/bot{telegram['bot_token']}/sendPhoto",
        files={"photo": ("yahoo_eni.png", image, "image/png")},
        data={
            "chat_id": telegram["chat_id"],
            "caption": caption,
            "parse_mode": "HTML",
        },
        timeout=config.get("api", {}).get("request_timeout", 30),
    )
    response.raise_for_status()
    if not response.json().get("ok"):
        raise RuntimeError(response.json().get("description", "Invio Telegram fallito"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", default="1y", help="Periodo Yahoo, default: 1y")
    parser.add_argument("--output", type=Path, help="Salva il PNG solo se esplicitamente richiesto")
    parser.add_argument("--send-telegram", action="store_true", help="Invia il PNG a Telegram")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    args = parser.parse_args()

    started = time.perf_counter()
    history, metadata = fetch_daily_history(SYMBOL, args.period)
    image, caption = create_plot(history, metadata)

    if args.output:
        args.output.write_bytes(image)
    if args.send_telegram:
        send_to_telegram(image, caption, args.config)

    elapsed = time.perf_counter() - started
    print(f"Provider: Yahoo Finance Chart API ({YAHOO_URL})")
    print(f"Strumento: {SYMBOL} | ISIN: {ISIN}")
    print(f"Mercato: {metadata.get('fullExchangeName', 'n/d')}")
    print(f"Valuta: {metadata.get('currency', 'n/d')}")
    print(f"Record: {len(history)}")
    print(f"Periodo: {history['timestamp'].iloc[0].date()} -> {history['timestamp'].iloc[-1].date()}")
    print(f"Ultimo prezzo: €{history['price'].iloc[-1]:.3f}")
    print(f"PNG in memoria: {len(image):,} bytes")
    print(f"Tempo totale: {elapsed:.2f} s")
    print(f"Serie salvata localmente: {'sì' if args.output else 'no'}")
    print(f"Telegram: {'inviato' if args.send_telegram else 'non richiesto'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
