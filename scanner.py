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
TARGET_MINUTES = {2, 7, 12}
GAP_THRESHOLD_PCT = -0.5
MIN_TURNOVER_PLN = 10_000
GPW_COMPANIES_URL = "https://www.gpw.pl/spolki"

def should_run(now):
    if os.getenv("FORCE_RUN") == "1":
        return True
    return now.weekday() < 5 and now.hour == 9 and now.minute in TARGET_MINUTES

def load_static_tickers():
    out = {}
    with TICKERS_FILE.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            ticker = row["ticker"].strip()
            if ticker:
                out[ticker] = row.get("name", "").strip()
    return out

def discover_gpw_tickers():
    out = {}
    try:
        r = requests.get(
            GPW_COMPANIES_URL,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0 gpw-gap-scanner/0.2"},
        )
        r.raise_for_status()
        text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
        for m in re.finditer(r"([A-Z0-9ĄĆĘŁŃÓŚŹŻ .!&+\-]{3,120})\s+\(([A-Z0-9]{2,6})\)", text):
            code = m.group(2)
            name = " ".join(m.group(1).split())[-100:]
            out[f"{code}.WA"] = name
    except Exception as exc:
        print(f"GPW universe warning: {exc}")
    return out

def build_universe():
    universe = discover_gpw_tickers()
    universe.update(load_static_tickers())
    return universe

def safe_float(v):
    try:
        return None if pd.isna(v) else float(v)
    except Exception:
        return None

def fetch_symbol(symbol):
    t = yf.Ticker(symbol)
    daily = t.history(period="5d", interval="1d", auto_adjust=False)
    if daily.empty or len(daily) < 2:
        return None

    prev = daily.iloc[-2]
    cur = daily.iloc[-1]
    previous_close = safe_float(prev.get("Close"))
    day_open = safe_float(cur.get("Open"))
    if not previous_close or day_open is None:
        return None

    intraday = t.history(period="1d", interval="1m", auto_adjust=False)
    last_price = safe_float(cur.get("Close"))
    volume = 0
    turnover_pln = 0.0

    if not intraday.empty:
        last_price = safe_float(intraday.iloc[-1].get("Close")) or last_price
        vols = intraday["Volume"].fillna(0)
        closes = intraday["Close"].ffill()
        volume = int(vols.sum())
        turnover_pln = float((closes * vols).sum())

    gap_pct = ((day_open / previous_close) - 1) * 100
    remaining = ((previous_close / last_price) - 1) * 100 if last_price else None

    return {
        "previous_close": round(previous_close, 4),
        "open": round(day_open, 4),
        "last": round(last_price, 4) if last_price is not None else None,
        "gap_pct": round(gap_pct, 3),
        "remaining_to_gap_close_pct": round(remaining, 3) if remaining is not None else None,
        "volume": volume,
        "turnover_pln": round(turnover_pln, 2),
    }

def append_history(scan_time, stocks):
    fields = [
        "scan_datetime","ticker","name","previous_close","open","last",
        "gap_pct","remaining_to_gap_close_pct","volume","turnover_pln"
    ]
    exists = HISTORY_FILE.exists() and HISTORY_FILE.stat().st_size > 0
    with HISTORY_FILE.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            w.writeheader()
        for stock in stocks:
            row = {k: stock.get(k) for k in fields}
            row["scan_datetime"] = scan_time.isoformat()
            w.writerow(row)

def main():
    now = datetime.now(WARSAW_TZ)
    if not should_run(now):
        print(f"No-op at {now:%Y-%m-%d %H:%M}; target 09:02/09:07/09:12 Europe/Warsaw.")
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    universe = build_universe()
    candidates, errors = [], []

    for symbol, name in sorted(universe.items()):
        try:
            d = fetch_symbol(symbol)
            if d is None:
                errors.append({"ticker": symbol, "reason": "no usable market data"})
                continue
            d.update({"ticker": symbol, "name": name})
            if d["gap_pct"] < GAP_THRESHOLD_PCT and d["turnover_pln"] >= MIN_TURNOVER_PLN:
                candidates.append(d)
        except Exception as exc:
            errors.append({"ticker": symbol, "reason": str(exc)[:180]})

    candidates.sort(key=lambda x: x["gap_pct"])

    payload = {
        "version": "0.2",
        "generated_at": now.isoformat(),
        "timezone": "Europe/Warsaw",
        "snapshot_minute": now.strftime("%H:%M"),
        "strategy": "GPW lower-gap scanner",
        "gap_filter_pct": "< -0.5%",
        "min_turnover_pln": MIN_TURNOVER_PLN,
        "source": "Yahoo Finance via yfinance; free test source, delayed data possible",
        "gpw_universe_url": GPW_COMPANIES_URL,
        "universe_count": len(universe),
        "candidate_count": len(candidates),
        "stocks": candidates,
        "error_count": len(errors),
        "errors": errors[:100],
    }

    LATEST_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    append_history(now, candidates)
    print(f"v0.2 complete: universe={len(universe)}, candidates={len(candidates)}, errors={len(errors)}")

if __name__ == "__main__":
    main()
