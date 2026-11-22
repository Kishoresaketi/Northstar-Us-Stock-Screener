#!/usr/bin/env python3
"""Build the static data files served on GitHub Pages (data/*.json).

Reads live data with the same functions the /api/* endpoints use, so the
static files have exactly the same shapes as the API responses. The universe
is the S&P 500 + Nasdaq-100 snapshot in scripts/universe/universe.json
(~518 tickers), each with quotes, fundamentals, financials, and all seven
chart ranges.

Modes:
    python3 scripts/build_static_data.py            # full rebuild (default)
    python3 scripts/build_static_data.py --mode fast # quotes only (hourly)
    python3 scripts/build_static_data.py --mode full # everything (daily)
    python3 scripts/build_static_data.py --mode auto # full at 02 UTC, else fast

The workflow (.github/workflows/refresh-data.yml) runs auto on both its
schedules: fast hourly and full once a day at 02:07 UTC. Quotes move every
hour, but filings and chart history only change on new filings and new
trading days, so a full rebuild every hour would burn the free data
sources and the git history for nothing.

A file that fails to refresh keeps its previous version; the run only fails
if nothing at all was written. Failed jobs are retried once at the end.

Full mode also refreshes the 13F institutional-ownership data, but only
when a newer completed quarter exists (scripts/refresh_shareholding_if_due.py);
on all other days that step is a fast no-op, and a failure there never
breaks the daily rebuild.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import lib.edgar as edgar
from api.chart import get_chart
from api.financials import get_financials
from api.fundamentals import get_fundamentals
from api.quotes import get_quote

UNIVERSE_PATH = os.path.join(ROOT, "scripts", "universe", "universe.json")
INDICES = ["^GSPC", "^IXIC", "^DJI", "^VIX"]
RANGES = ["1mo", "6mo", "1y", "3y", "5y", "10y", "max"]
DATA = os.path.join(ROOT, "data")
PEER_COUNT = 10


def load_universe():
    with open(UNIVERSE_PATH, encoding="utf-8") as fh:
        universe = json.load(fh)
    return sorted(universe)


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


def build_cik_map(tickers):
    """Ticker -> SEC CIK for the universe, written to data/cik-map.json.

    The profile's SEC Documents links are built from this file. CIKs
    change only when the universe changes, so it is built in full mode
    only; the hourly quotes refresh leaves it alone.
    """
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from build_cik_map import build_cik_map as _build
    out, missing = _build(tickers)
    write(os.path.join(DATA, "cik-map.json"), out)
    print(f"cik map: {len(out)} tickers" + (f"; no SEC entry for: {', '.join(missing)}" if missing else ""))


def build_search_index(tickers):
    with open(UNIVERSE_PATH, encoding="utf-8") as fh:
        universe = json.load(fh)
    index = [{"symbol": s, "name": universe[s]["name"], "sector": universe[s].get("sector")}
             for s in tickers if s in universe]
    write(os.path.join(DATA, "search-index.json"), index)


def build_fundamentals_summary(tickers):
    """One compact JSON with the numbers the screener table filters and
    sorts on (market cap, P/E, ROE, growth, price, daily change) for the
    whole universe. The table only fetches live data for its visible page,
    so filtering/sorting across all 517 rows needs this summary instead of
    517 separate requests. Built from the already-built quote + fundamentals
    files, so it costs no extra EDGAR calls."""
    out = {}
    for symbol in tickers:
        try:
            with open(os.path.join(DATA, "fundamentals", file_for(symbol) + ".json"), encoding="utf-8") as fh:
                f = json.load(fh)
        except (OSError, ValueError):
            f = {}
        try:
            with open(os.path.join(DATA, "quotes", file_for(symbol) + ".json"), encoding="utf-8") as fh:
                q = json.load(fh)
        except (OSError, ValueError):
            q = {}
        out[symbol] = {
            "cap": f.get("cap"), "pe": f.get("pe"), "roe": f.get("roe"),
            "growth": f.get("growth"), "price": q.get("price"),
            "change": q.get("changePercent"),
        }
    write(os.path.join(DATA, "fundamentals-summary.json"), out)


def build_peer_map(tickers):
    """Peer lists for every ticker, written to data/peer-map.json.

    The seeded eight keep their curated lists (lib/edgar.py PEERS). Every
    other ticker gets same-sub-industry peers first, then same-sector peers,
    ranked by market cap — up to PEER_COUNT. Caps come from live metrics;
    a ticker whose filings cannot be read still gets peers by sector order.
    """
    with open(UNIVERSE_PATH, encoding="utf-8") as fh:
        universe = json.load(fh)

    def _cap(symbol):
        try:
            return edgar.metrics(symbol).get("cap") or 0
        except Exception:
            return 0

    caps = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_cap, s): s for s in tickers}
        for future in as_completed(futures):
            caps[futures[future]] = future.result()

    by_sub = {}
    by_sector = {}
    for symbol in tickers:
        entry = universe.get(symbol, {})
        by_sub.setdefault(entry.get("subindustry"), []).append(symbol)
        by_sector.setdefault(entry.get("sector"), []).append(symbol)
    for group in list(by_sub.values()) + list(by_sector.values()):
        group.sort(key=lambda s: caps.get(s, 0), reverse=True)

    peer_map = {}
    for symbol in tickers:
        if symbol in edgar.PEERS:
            peer_map[symbol] = list(edgar.PEERS[symbol])
            continue
        entry = universe.get(symbol, {})
        chosen = [s for s in by_sub.get(entry.get("subindustry"), []) if s != symbol]
        if len(chosen) < PEER_COUNT:
            chosen += [s for s in by_sector.get(entry.get("sector"), [])
                       if s != symbol and s not in chosen]
        peer_map[symbol] = chosen[:PEER_COUNT]
    write(os.path.join(DATA, "peer-map.json"), peer_map)
    counts = {s: len(v) for s, v in peer_map.items()}
    print(f"peer map: {len(peer_map)} tickers, "
          f"min {min(counts.values())} / max {max(counts.values())} peers")


def guard(fn, *args):
    try:
        fn(*args)
        return True
    except Exception as exc:
        print(f"skip {fn.__name__} {args}: {exc}")
        return False


def run_jobs(jobs):
    failed = []
    done = 0
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(guard, fn, *args): (fn, args) for fn, args in jobs}
        for i, future in enumerate(as_completed(futures), 1):
            if future.result():
                done += 1
            else:
                failed.append(futures[future])
            if i % 250 == 0:
                print(f"  ... {i}/{len(futures)} jobs done")
    return done, failed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["fast", "full", "auto"], default="full")
    args = parser.parse_args()
    mode = args.mode
    if mode == "auto":
        # The workflow runs this on both schedules: full rebuild once a day
        # at 02 UTC (after the US close settles), quotes-only every other hour.
        mode = "full" if datetime.now(timezone.utc).hour == 2 else "fast"
        print(f"auto mode -> {mode} (UTC hour {datetime.now(timezone.utc).hour})")
    tickers = load_universe()
    print(f"universe: {len(tickers)} tickers (+ {len(INDICES)} indices)")

    if mode == "fast":
        jobs = [(build_quote, (s,)) for s in tickers + INDICES]
        done, failed = run_jobs(jobs)
        if failed:
            print(f"retrying {len(failed)} failed quote jobs")
            done2, _ = run_jobs(failed)
            done += done2
        build_fundamentals_summary(tickers)
        print(f"refreshed {done}/{len(jobs)} files (fast mode)")
        return 0 if done else 1

    build_peer_map(tickers)
    build_search_index(tickers)
    build_cik_map(tickers)
    jobs = []
    for symbol in tickers + INDICES:
        jobs.append((build_quote, (symbol,)))
    for symbol in tickers:
        jobs.append((build_fundamentals, (symbol,)))
        jobs.append((build_financials, (symbol,)))
        for period in RANGES:
            jobs.append((build_chart, (symbol, period)))
    done, failed = run_jobs(jobs)
    if failed:
        print(f"retrying {len(failed)} failed jobs")
        done2, failed2 = run_jobs(failed)
        done += done2
        if failed2:
            print(f"still failing after retry: {len(failed2)}")
            for fn, fn_args in failed2[:20]:
                print(f"  {fn.__name__} {fn_args}")
    build_fundamentals_summary(tickers)
    # Monthly 13F refresh: shareholding only changes quarterly, and the
    # gate script is a fast no-op unless a newer completed quarter exists
    # (Q3 2026 becomes due Nov 28). A failure here must never break the
    # daily rebuild, so the step is best-effort by design.
    try:
        subprocess.run(
            [sys.executable,
             os.path.join(ROOT, "scripts", "refresh_shareholding_if_due.py")],
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 - 13F must never break the rebuild
        print(f"13F refresh step failed (non-fatal): {exc}")
    print(f"refreshed {done}/{len(jobs)} files (full mode)")
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
