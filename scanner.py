from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
TICKERS_FILE = ROOT / "tickers.csv"
LATEST_FILE = DATA_DIR / "latest.json"
HISTORY_FILE = DATA_DIR / "history.csv"

WARSAW_TZ = ZoneInfo("Europe/Warsaw")

GAP_THRESHOLD_PCT = -0.5
MIN_TURNOVER_PLN = 10_000

GPW_COMPANIES_URL = "https://www.gpw.pl/spolki"


def should_run(now: datetime) -> bool:
    if os.getenv("FORCE_RUN") == "1":
        return True

    # Weekend - nie skanujemy.
    if now.weekday() >= 5:
        return False

    # GitHub Actions może uruchomić cron z kilkuminutowym opóźnieniem.
    # Akceptujemy uruchomienia od 08:58 do końca godziny 09:xx.
    if now.hour == 8 and now.minute >= 58:
        return True

    if now.hour == 9:
        return True

    return False


def load_static_tickers():
    out = {}

    if not TICKERS_FILE.exists():
        return out

    with TICKERS_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        for row in csv.DictReader(f):
            ticker = row.get("ticker", "").strip()
            name = row.get("name", "").strip()

            if ticker:
                out[ticker] = name

    return out


def discover_gpw_tickers():
    out = {}

    try:
        response = requests.get(
            GPW_COMPANIES_URL,
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0 gpw-gap-scanner/0.2"
            },
        )

        response.raise_for_status()

        text = BeautifulSoup(
            response.text,
            "html.parser"
        ).get_text(" ", strip=True)

        pattern = (
            r"([A-Z0-9ĄĆĘŁŃÓŚŹŻ .!&+\-]{3,120})"
            r"\s+\(([A-Z0-9]{2,6})\)"
        )

        for match in re.finditer(pattern, text):
            code = match.group(2)

            name = " ".join(
                match.group(1).split()
            )[-100:]

            out[f"{code}.WA"] = name

    except Exception as exc:
        print(
            f"GPW universe warning: {exc}"
        )

    return out


def build_universe():
    universe = discover_gpw_tickers()

    # tickers.csv działa jako fallback i miejsce ręcznych korekt
    universe.update(
        load_static_tickers()
    )

    return universe


def safe_float(value):
    try:
        if pd.isna(value):
            return None

        return float(value)

    except Exception:
        return None


def fetch_symbol(symbol):
    ticker = yf.Ticker(symbol)

    daily = ticker.history(
        period="5d",
        interval="1d",
        auto_adjust=False
    )

    if daily.empty or len(daily) < 2:
        return None

    previous_day = daily.iloc[-2]
    current_day = daily.iloc[-1]

    previous_close = safe_float(
        previous_day.get("Close")
    )

    day_open = safe_float(
        current_day.get("Open")
    )

    if not previous_close or day_open is None:
        return None

    intraday = ticker.history(
        period="1d",
        interval="1m",
        auto_adjust=False
    )

    last_price = safe_float(
        current_day.get("Close")
    )

    volume = 0
    turnover_pln = 0.0
    quote_time = None

    if not intraday.empty:
        valid_closes = intraday["Close"].dropna()

        if not valid_closes.empty:
            last_price = safe_float(
                valid_closes.iloc[-1]
            ) or last_price

            quote_time = str(
                valid_closes.index[-1]
            )

        volumes = intraday["Volume"].fillna(0)
        closes = intraday["Close"].ffill()

        volume = int(
            volumes.sum()
        )

        turnover_pln = float(
            (closes * volumes).sum()
        )

    if not last_price:
        return None

    gap_pct = (
        (day_open / previous_close) - 1
    ) * 100

    remaining_to_gap_close_pct = (
        (previous_close / last_price) - 1
    ) * 100

    return {
        "previous_close": round(
            previous_close,
            4
        ),
        "open": round(
            day_open,
            4
        ),
        "last": round(
            last_price,
            4
        ),
        "gap_pct": round(
            gap_pct,
            3
        ),
        "remaining_to_gap_close_pct": round(
            remaining_to_gap_close_pct,
            3
        ),
        "volume": volume,
        "turnover_pln": round(
            turnover_pln,
            2
        ),
        "quote_time": quote_time,
    }


def append_history(
    scan_time,
    stocks
):
    fields = [
        "scan_datetime",
        "ticker",
        "name",
        "previous_close",
        "open",
        "last",
        "gap_pct",
        "remaining_to_gap_close_pct",
        "volume",
        "turnover_pln",
        "quote_time",
    ]

    exists = (
        HISTORY_FILE.exists()
        and HISTORY_FILE.stat().st_size > 0
    )

    with HISTORY_FILE.open(
        "a",
        encoding="utf-8",
        newline=""
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields
        )

        if not exists:
            writer.writeheader()

        for stock in stocks:
            row = {
                key: stock.get(key)
                for key in fields
            }

            row["scan_datetime"] = (
                scan_time.isoformat()
            )

            writer.writerow(row)


def main():
    now = datetime.now(
        WARSAW_TZ
    )

    if not should_run(now):
        print(
            f"No-op at "
            f"{now:%Y-%m-%d %H:%M}; "
            f"accepted window: "
            f"08:58-09:59 Europe/Warsaw."
        )

        return

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    universe = build_universe()

    candidates = []
    errors = []

    print(
        f"Starting GPW scanner v0.2. "
        f"Universe: {len(universe)}"
    )

    for symbol, name in sorted(
        universe.items()
    ):
        try:
            data = fetch_symbol(
                symbol
            )

            if data is None:
                errors.append({
                    "ticker": symbol,
                    "reason": (
                        "no usable market data"
                    )
                })

                continue

            data.update({
                "ticker": symbol,
                "name": name,
            })

            if (
                data["gap_pct"]
                < GAP_THRESHOLD_PCT
                and data["turnover_pln"]
                >= MIN_TURNOVER_PLN
            ):
                candidates.append(
                    data
                )

        except Exception as exc:
            errors.append({
                "ticker": symbol,
                "reason": str(exc)[:180]
            })

    candidates.sort(
        key=lambda x: x["gap_pct"]
    )

    payload = {
        "version": "0.2",
        "generated_at": now.isoformat(),
        "timezone": "Europe/Warsaw",
        "snapshot_minute": (
            now.strftime("%H:%M")
        ),
        "freshness": {
            "status": "FRESH",
            "age_minutes": 0,
            "max_age_minutes_for_report": 30
        },
        "strategy": (
            "GPW lower-gap scanner"
        ),
        "gap_filter_pct": "< -0.5%",
        "min_turnover_pln": (
            MIN_TURNOVER_PLN
        ),
        "source": (
            "Yahoo Finance via yfinance; "
            "free test source, delayed "
            "data possible"
        ),
        "gpw_universe_url": (
            GPW_COMPANIES_URL
        ),
        "universe_count": len(
            universe
        ),
        "candidate_count": len(
            candidates
        ),
        "stocks": candidates,
        "error_count": len(
            errors
        ),
        "errors": errors[:100],
    }

    LATEST_FILE.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    append_history(
        now,
        candidates
    )

    print(
        f"v0.2 complete: "
        f"universe={len(universe)}, "
        f"candidates={len(candidates)}, "
        f"errors={len(errors)}"
    )


if __name__ == "__main__":
    main()
