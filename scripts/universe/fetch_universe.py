#!/usr/bin/env python3
"""Fetch the screener universe (S&P 500 + Nasdaq-100) from free public lists
and snapshot it into this directory, so the universe is reproducible.

Sources:
- S&P 500: datasets/s-and-p-500-companies on GitHub (Wikipedia-derived CSV)
- Nasdaq-100: Wikipedia "List of NASDAQ-100 companies" via the MediaWiki API

Run: python3 scripts/universe/fetch_universe.py
Outputs: sp500.csv, nasdaq100.csv, universe.json
"""

import csv
import json
import os
import urllib.request
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "NorthstarScreener research contact kishore.svjr@gmail.com"}
SP500_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
NDX_URL = ("https://en.wikipedia.org/w/api.php?action=parse"
           "&page=List_of_NASDAQ-100_companies&prop=text&format=json&formatversion=2")

# ICB industry (Nasdaq-100 list) -> GICS sector (S&P 500 list) for one sector key.
ICB_TO_GICS = {
    "Technology": "Information Technology",
    "Telecommunications": "Communication Services",
    "Consumer Discretionary": "Consumer Discretionary",
    "Consumer Staples": "Consumer Staples",
    "Health Care": "Health Care",
    "Financials": "Financials",
    "Industrials": "Industrials",
    "Energy": "Energy",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
    "Materials": "Materials",
    "Communication Services": "Communication Services",
}


def normalize_symbol(symbol):
    """Yahoo and SEC both use BRK-B style (dash) for share classes."""
    return symbol.strip().upper().replace(".", "-")


# The Wikipedia Nasdaq-100 list uses ICB classifications, which do not line
# up with the S&P 500 list's GICS sectors (e.g. ASML lands in "Industrial
# Machinery", PDD in "Technology"). For the Nasdaq-100-only names — the ones
# with no GICS entry — the sector below was verified against Nasdaq's quote
# summary API and the sub-industry aligned to the GICS name, so peer
# grouping compares like with like. Applied only to tickers that are NOT in
# the S&P 500 (their GICS entry wins).
# Tickers to leave out even if a source lists them: SPCX/SpaceX is a
# private company with no public ticker — it appeared as a bad row in
# the Wikipedia Nasdaq-100 list (Nov 2026) and its EDGAR match is an
# unrelated entity, so including it would publish invented figures.
EXCLUDED_TICKERS = {"SPCX"}

NDX_ONLY_OVERRIDES = {
    "ALAB": ("Information Technology", "Semiconductors"),
    "ALNY": ("Health Care", "Biotechnology"),
    "ARM": ("Information Technology", "Semiconductors"),
    "ASML": ("Information Technology", "Semiconductors"),
    "CCEP": ("Consumer Staples", "Soft Drinks"),
    "CRWV": ("Information Technology", "Application Software"),
    "FER": ("Industrials", "Construction & Engineering"),
    "MELI": ("Consumer Discretionary", "Internet & Direct Marketing Retail"),
    "MSTR": ("Information Technology", "Application Software"),
    "NBIS": ("Information Technology", "Application Software"),
    "PDD": ("Consumer Discretionary", "Internet & Direct Marketing Retail"),
    "RKLB": ("Industrials", "Aerospace & Defense"),
    "SHOP": ("Information Technology", "Application Software"),
    "TRI": ("Industrials", "Professional Services"),
}

# S&P 500 entries the upstream CSV mislabels (verified Nov 16, 2026 — the
# live constituents.csv still lists DD as Industrials). Applied on every
# re-fetch so the error cannot come back.
SP500_OVERRIDES = {
    # DuPont is a chemicals company (Materials / Specialty Chemicals), not
    # an industrial conglomerate — without this, its peers come out as
    # 3M, Honeywell, Caterpillar and the like instead of Sherwin-Williams,
    # Ecolab, PPG, Linde and Dow.
    "DD": ("Materials", "Specialty Chemicals"),
}


def fetch_sp500():
    req = urllib.request.Request(SP500_URL, headers=UA)
    text = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    rows = list(csv.DictReader(text.splitlines()))
    out = []
    for r in rows:
        out.append({
            "symbol": normalize_symbol(r["Symbol"]),
            "name": r["Security"].strip(),
            "sector": r["GICS Sector"].strip(),
            "subindustry": r["GICS Sub-Industry"].strip(),
        })
    return out


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self.cur_table = None
        self.cur_row = None
        self.cur_cell = None
        self.in_table = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.cur_table = []
            self.in_table = True
        elif tag == "tr" and self.in_table:
            self.cur_row = []
        elif tag in ("td", "th") and self.cur_row is not None:
            self.cur_cell = ""

    def handle_endtag(self, tag):
        if tag == "table" and self.in_table:
            self.tables.append(self.cur_table)
            self.cur_table = None
            self.in_table = False
        elif tag == "tr" and self.cur_row is not None:
            self.cur_table.append(self.cur_row)
            self.cur_row = None
        elif tag in ("td", "th") and self.cur_cell is not None:
            self.cur_row.append(self.cur_cell.strip())
            self.cur_cell = None

    def handle_data(self, d):
        if self.cur_cell is not None:
            self.cur_cell += d


def fetch_nasdaq100():
    req = urllib.request.Request(NDX_URL, headers=UA)
    data = json.load(urllib.request.urlopen(req, timeout=30))
    parser = _TableParser()
    parser.feed(data["parse"]["text"])
    for table in parser.tables:
        if not table:
            continue
        header = [c.lower() for c in table[0]]
        if "ticker" in header and "company" in header:
            out = []
            for row in table[1:]:
                if len(row) < 5:
                    continue
                out.append({
                    "symbol": normalize_symbol(row[0]),
                    "name": row[1],
                    "sector": ICB_TO_GICS.get(row[3], row[3]),
                    "subindustry": row[4],
                })
            return out
    raise RuntimeError("Nasdaq-100 constituents table not found on Wikipedia")


def main():
    sp500 = [r for r in fetch_sp500() if r["symbol"] not in EXCLUDED_TICKERS]
    ndx = [r for r in fetch_nasdaq100() if r["symbol"] not in EXCLUDED_TICKERS]
    with open(os.path.join(HERE, "sp500.csv"), "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["symbol", "name", "sector", "subindustry"])
        writer.writeheader()
        writer.writerows(sp500)
    with open(os.path.join(HERE, "nasdaq100.csv"), "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["symbol", "name", "sector", "subindustry"])
        writer.writeheader()
        writer.writerows(ndx)
    universe = {}
    for row in sp500:
        universe[row["symbol"]] = {**row, "indices": ["SP500"]}
    for row in ndx:
        if row["symbol"] in universe:
            universe[row["symbol"]]["indices"].append("NDX")
        else:
            universe[row["symbol"]] = {**row, "indices": ["NDX"]}
    for symbol, (sector, subindustry) in NDX_ONLY_OVERRIDES.items():
        entry = universe.get(symbol)
        if entry and entry["indices"] == ["NDX"]:
            entry["sector"] = sector
            entry["subindustry"] = subindustry
    for symbol, (sector, subindustry) in SP500_OVERRIDES.items():
        entry = universe.get(symbol)
        if entry:
            entry["sector"] = sector
            entry["subindustry"] = subindustry
    with open(os.path.join(HERE, "universe.json"), "w", encoding="utf-8") as fh:
        json.dump(universe, fh, indent=1, sort_keys=True)
    print(f"S&P 500: {len(sp500)}  Nasdaq-100: {len(ndx)}  unique: {len(universe)}")


if __name__ == "__main__":
    main()
