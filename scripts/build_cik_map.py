#!/usr/bin/env python3
"""Build data/cik-map.json: ticker -> {cik, name} for the universe.

The CIK is what the profile's SEC Documents links are built from.
Source is the SEC company_tickers list — the same source
lib/edgar.py uses for its ticker -> (cik, title) map — so the map
stays consistent with the filings pipeline. CIKs change only when
the universe changes, so this file is rebuilt in full mode only
(see build_static_data.py); the hourly quotes refresh leaves it
alone.

Usage:
    python3 scripts/build_cik_map.py
"""
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import lib.edgar as edgar

UNIVERSE_PATH = os.path.join(ROOT, "scripts", "universe", "universe.json")
OUT_PATH = os.path.join(ROOT, "data", "cik-map.json")


def build_cik_map(tickers):
    """Return {ticker: {cik, name}} for tickers found in the SEC list."""
    tickers_map = edgar.tickers()
    out = {}
    missing = []
    for symbol in sorted(tickers):
        entry = tickers_map.get(symbol)
        if entry:
            out[symbol] = {"cik": str(entry[0]), "name": entry[1]}
        else:
            missing.append(symbol)
    return out, missing


def main():
    with open(UNIVERSE_PATH, encoding="utf-8") as fh:
        universe = json.load(fh)
    out, missing = build_cik_map(sorted(universe))
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    os.replace(tmp, OUT_PATH)
    print(f"cik map: {len(out)} tickers -> {OUT_PATH}")
    if missing:
        print(f"  no SEC entry for: {', '.join(missing)}")
    return 0 if out else 1


if __name__ == "__main__":
    raise SystemExit(main())
