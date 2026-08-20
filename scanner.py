from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent
TICKERS_FILE = ROOT / "tickers.csv"
DATA_DIR = ROOT / "data"
LATEST_FILE = DATA_DIR / "latest.json"
HISTORY_FILE = DATA_DIR / "history.csv"

GAP_THRESHOLD_PCT = -0.5
WARSAW_TZ = ZoneInfo("Europe/Warsaw")
TARGET_MINUTES = {2, 7, 12}


def should_run_now(now: datetime) -> bool:
    # Manual runs can bypass the time guard.
    if os.getenv("FORCE_RUN") == "1":
        return True
    return now.hour == 9 and now.minute in TARGET_MINUTES


def load_tickers() -> list[dict[str, str]]:
    with TICKERS_FILE.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def safe_float(value):
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_symbol(symbol: str) -> dict | None:
    ticker = yf.Ticker(symbol)

    daily = ticker.history(period="5d", interval="1d", auto_adjust=False)
    if daily.empty or len(daily) < 2:
        return None

    prev_row = daily.iloc[-2]
    curr_row = daily.iloc[-1]

    previous_close = safe_float(prev_row.get("Close"))
    day_open = safe_float(curr_row.get("Open"))

    if previous_close in (None, 0) or day_open is None:
        return None

    intraday = ticker.history(period="1d", interval="1m", auto_adjust=False)

    last_price = None
    intraday_volume = 0

    if not intraday.empty:
        last_price = safe_float(intraday.iloc[-1].get("Close"))
        try:
            intraday_volume = int(intraday["Volume"].fillna(0).sum())
        except Exception:
            intraday_volume = 0

    if last_price is None:
        last_price = safe_float(curr_row.get("Close"))

    gap_pct = ((day_open / previous_close) - 1) * 100
    remaining_to_close_pct = (
        ((previous_close / last_price) - 1) * 100 if last_price else None
    )

    return {
        "previous_close": round(previous_close, 4),
        "open": round(day_open, 4),
        "last": round(last_price, 4) if last_price is not None else None,
        "gap_pct": round(gap_pct, 3),
        "remaining_to_gap_close_pct": (
            round(remaining_to_close_pct, 3)
            if remaining_to_close_pct is not None
            else None
        ),
        "volume": intraday_volume,
        "data_note": "Yahoo Finance / yfinance; GPW data may be delayed about 15 min",
    }


def append_history(scan_time: datetime, stocks: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    exists = HISTORY_FILE.exists() and HISTORY_FILE.stat().st_size > 0

    fieldnames = [
        "scan_datetime",
        "ticker",
        "name",
        "previous_close",
        "open",
        "last",
        "gap_pct",
        "remaining_to_gap_close_pct",
        "volume",
    ]

    with HISTORY_FILE.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()

        for stock in stocks:
            row = {key: stock.get(key) for key in fieldnames}
            row["scan_datetime"] = scan_time.isoformat()
            writer.writerow(row)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(WARSAW_TZ)

    if not should_run_now(now):
        print(
            f"Skipping scan at {now:%H:%M} Europe/Warsaw. "
            "Scheduled snapshots are 09:02, 09:07 and 09:12."
        )
        return

    candidates = []
    errors = []

    for row in load_tickers():
        symbol = row["ticker"].strip()
        name = row.get("name", "").strip()

        try:
            result = fetch_symbol(symbol)

            if result is None:
                errors.append({"ticker": symbol, "reason": "no usable market data"})
                continue

            result.update({"ticker": symbol, "name": name})

            if result["gap_pct"] < GAP_THRESHOLD_PCT and result["volume"] > 0:
                candidates.append(result)

        except Exception as exc:
            errors.append({"ticker": symbol, "reason": str(exc)[:200]})

    candidates.sort(key=lambda x: x["gap_pct"])

    payload = {
        "generated_at": now.isoformat(),
        "timezone": "Europe/Warsaw",
        "strategy": "GPW lower-gap scanner v0.1",
        "gap_filter_pct": "< -0.5%",
        "source": "Yahoo Finance via yfinance (free test source; delayed data possible)",
        "candidate_count": len(candidates),
        "stocks": candidates,
        "errors": errors,
    }

    LATEST_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    append_history(now, candidates)

    print(f"Scan complete: {len(candidates)} candidates, {len(errors)} errors")


if __name__ == "__main__":
    main()
