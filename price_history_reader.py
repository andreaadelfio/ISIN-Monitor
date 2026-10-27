#!/usr/bin/env python3
"""Lettore user friendly per lo storico prezzi (formato long: timestamp, ticker, price)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
METADATA_PATH = BASE_DIR / "isin_metadata.csv"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_price_history() -> pd.DataFrame:
    config = load_config()
    history_path = BASE_DIR / config["data"]["price_history_data"]
    # La compressione (es. .zst) è dedotta dall'estensione del file
    df = pd.read_pickle(history_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    return df.sort_values("timestamp", kind="stable").reset_index(drop=True)


def load_metadata() -> pd.DataFrame:
    if not METADATA_PATH.exists():
        return pd.DataFrame(columns=["ticker", "isin", "target_discount"])
    return pd.read_csv(METADATA_PATH)


def filter_ticker(df: pd.DataFrame, ticker: str | None) -> pd.DataFrame:
    return df[df["ticker"] == ticker] if ticker else df


def format_number(value: object) -> str:
    if pd.isna(value):
        return "-"
    if isinstance(value, (int, float)):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def print_table(df: pd.DataFrame, empty_message: str) -> None:
    if df.empty:
        print(empty_message)
        return
    print(df.to_string(index=False))


def build_latest_snapshot(df: pd.DataFrame, metadata_df: pd.DataFrame, selected_ticker: str | None = None) -> pd.DataFrame:
    metadata_map = metadata_df.set_index("ticker").to_dict("index") if not metadata_df.empty else {}
    rows: list[dict] = []

    for ticker, ticker_df in filter_ticker(df, selected_ticker).groupby("ticker", observed=True, sort=False):
        last_row = ticker_df.iloc[-1]
        meta = metadata_map.get(ticker, {})
        rows.append(
            {
                "ticker": ticker,
                "prezzo": last_row["price"],
                "ultimo_aggiornamento": last_row["timestamp"],
                "isin": meta.get("isin", ""),
                "campioni": len(ticker_df),
            }
        )

    snapshot_df = pd.DataFrame(rows)
    if snapshot_df.empty:
        return snapshot_df

    snapshot_df = snapshot_df.sort_values(["ultimo_aggiornamento", "ticker"], ascending=[False, True]).reset_index(drop=True)
    snapshot_df["prezzo"] = snapshot_df["prezzo"].map(format_number)
    return snapshot_df


def build_recent_events(df: pd.DataFrame, limit: int, selected_ticker: str | None = None) -> pd.DataFrame:
    recent_df = filter_ticker(df, selected_ticker).sort_values("timestamp", ascending=False, kind="stable").head(limit)
    recent_df = recent_df[["timestamp", "ticker", "price"]].rename(columns={"price": "prezzo"})
    recent_df["prezzo"] = recent_df["prezzo"].map(format_number)
    return recent_df.reset_index(drop=True)


def print_summary(df: pd.DataFrame) -> None:
    print("=== Riepilogo storico prezzi ===")
    print(f"Prezzi archiviati: {len(df)}")
    print(f"Ticker monitorati: {df['ticker'].nunique()}")
    print(f"Prima rilevazione: {df['timestamp'].min()}")
    print(f"Ultima rilevazione: {df['timestamp'].max()}")


def print_latest_prices(df: pd.DataFrame, metadata_df: pd.DataFrame, limit: int, ticker: str | None) -> None:
    snapshot_df = build_latest_snapshot(df, metadata_df, ticker)
    if ticker and snapshot_df.empty:
        print(f"Ticker '{ticker}' non trovato o senza prezzi registrati.")
        return

    title = f"=== Ultimo prezzo disponibile per {ticker} ===" if ticker else f"=== Ultimi {limit} ticker aggiornati ==="
    print(f"\n{title}")
    print_table(snapshot_df.head(limit), "Nessun prezzo disponibile.")


def print_recent_activity(df: pd.DataFrame, rows: int, ticker: str | None) -> None:
    recent_df = build_recent_events(df, rows, ticker)
    title = f"=== Ultimi {rows} aggiornamenti di {ticker} ===" if ticker else f"=== Ultimi {rows} aggiornamenti registrati ==="
    print(f"\n{title}")
    print_table(recent_df, "Nessun aggiornamento disponibile.")


def print_ticker_history(df: pd.DataFrame, ticker: str, rows: int) -> None:
    ticker_df = filter_ticker(df, ticker)[["timestamp", "price"]].rename(columns={"price": "prezzo"})
    if ticker_df.empty:
        print(f"Ticker '{ticker}' non presente nel file storico.")
        return

    print(f"\n=== Storico {ticker} ===")
    print(f"Campioni trovati: {len(ticker_df)}")
    print(f"Ultimo prezzo: {format_number(ticker_df['prezzo'].iloc[-1])}")
    print(f"Minimo storico: {format_number(ticker_df['prezzo'].min())}")
    print(f"Massimo storico: {format_number(ticker_df['prezzo'].max())}")
    ticker_df["prezzo"] = ticker_df["prezzo"].map(format_number)
    print_table(ticker_df.tail(rows), "Nessun dato disponibile.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Legge lo storico prezzi di ISIN Monitor")
    parser.add_argument("--ticker", help="Mostra i dati di un ticker specifico, ad esempio ENI.MI")
    parser.add_argument("--rows", type=int, default=10, help="Numero di righe/eventi da mostrare")
    parser.add_argument("--history", action="store_true", help="Con --ticker mostra lo storico recente del ticker")
    parser.add_argument("--raw", action="store_true", help="Con --ticker mostra solo gli aggiornamenti di quel ticker")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    df = load_price_history()
    metadata_df = load_metadata()

    print_summary(df)

    if args.ticker and args.history:
        print_ticker_history(df, args.ticker, args.rows)
        return 0

    print_latest_prices(df, metadata_df, args.rows, args.ticker)
    print_recent_activity(df, args.rows, args.ticker if args.raw else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
