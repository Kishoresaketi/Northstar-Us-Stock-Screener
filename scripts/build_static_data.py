#!/usr/bin/env python3
"""Build the static data files served on GitHub Pages (data/*.json).

Reads live data with the same functions the /api/* endpoints use, so the
static files have exactly the same shapes as the API responses. Run by
.github/workflows/refresh-data.yml every hour, or locally:

    python3 scripts/build_static_data.py

A file that fails to refresh keeps its previous version; the run only fails
if nothing at all was written.
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from api.chart import get_chart
from api.financials import get_financials
from api.fundamentals import get_fundamentals
from api.quotes import get_quote

TICKERS = ["AAPL", "MSFT", "NVDA", "GOOGL", "LLY", "JPM", "XOM", "VST"]
INDICES = ["^GSPC", "^IXIC", "^DJI", "^VIX"]
RANGES = ["1mo", "6mo", "1y", "3y", "5y", "10y", "max"]
DATA = os.path.join(ROOT, "data")


def file_for(symbol):
    return "".join(c if c.isalnum() or c == "." else "_" for c in symbol)


def write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp, path)


def build_quote(symbol):
    quote = get_quote(symbol)
    quote["generatedAt"] = int(time.time())
    write(os.path.join(DATA, "quotes", file_for(symbol) + ".json"), quote)


def build_fundamentals(symbol):
    metrics = get_fundamentals([symbol])["fundamentals"][symbol]
    write(os.path.join(DATA, "fundamentals", file_for(symbol) + ".json"), metrics)


def build_financials(symbol):
    write(os.path.join(DATA, "financials", file_for(symbol) + ".json"), get_financials(symbol))


def build_chart(symbol, period):
    write(os.path.join(DATA, "chart", f"{file_for(symbol)}-{period}.json"), get_chart(symbol, period))


def guard(fn, *args):
    try:
        fn(*args)
        return True
    except Exception as exc:
        print(f"skip {fn.__name__} {args}: {exc}")
        return False


def main():
    jobs = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        for symbol in TICKERS + INDICES:
            jobs.append(executor.submit(guard, build_quote, symbol))
        for symbol in TICKERS:
            jobs.append(executor.submit(guard, build_fundamentals, symbol))
            jobs.append(executor.submit(guard, build_financials, symbol))
            for period in RANGES:
                jobs.append(executor.submit(guard, build_chart, symbol, period))
        results = [future.result() for future in as_completed(jobs)]
    ok = sum(results)
    print(f"refreshed {ok}/{len(results)} files")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
