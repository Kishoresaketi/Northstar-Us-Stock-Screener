#!/usr/bin/env python3
"""Build the 13F institutional-ownership data (data/shareholding.json).

Quarterly job — 13F filings only change once a quarter, so this does NOT
run in the hourly/daily workflow. Run it by hand after a quarter's
filings are complete (or wire it into a quarterly workflow later):

    python3 scripts/build_shareholding.py                     # latest complete quarter, full universe
    python3 scripts/build_shareholding.py --tickers AAPL,MSFT,WMT
    python3 scripts/build_shareholding.py --quarter 2026-06-30

The expensive part (downloading ~8,900 information tables) is cached in
data/13f-totals-<quarter>.json, so a re-run for more tickers reuses it.
The per-ticker file data/shareholding.json is what the profile reads
(via api/financials.py, which embeds it in each financials payload).
"""

import argparse
import json
import os
import sys
from datetime import date

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import lib.edgar as edgar
import lib.thirteenf as thirteenf


def _totals_path(quarter_end):
    return os.path.join(ROOT, "data", f"13f-totals-{quarter_end.year}Q{(quarter_end.month - 1) // 3 + 1}.json")


def _write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp, path)


def _fmt_pct(x):
    return f"{x:.2%}" if x is not None else "—"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quarter", default=None, help="quarter end YYYY-MM-DD (default: latest complete quarter)")
    parser.add_argument("--tickers", default=None, help="comma-separated symbols (default: full universe)")
    parser.add_argument("--out", default=None, help="shareholding output path (default: data/shareholding.json)")
    args = parser.parse_args()

    if args.quarter:
        quarter_end = date.fromisoformat(args.quarter)
        _q, label = thirteenf.latest_completed_quarter()
    else:
        quarter_end, label = thirteenf.latest_completed_quarter()
    print(f"13F quarter: {quarter_end.isoformat()} ({label})")

    tickers = sorted(s.strip().upper() for s in args.tickers.split(",")) if args.tickers else sorted(edgar.universe())
    print(f"tickers: {len(tickers)}")

    totals = None
    totals_path = _totals_path(quarter_end)
    if os.path.exists(totals_path):
        with open(totals_path, encoding="utf-8") as fh:
            cached = json.load(fh)
        totals = cached.get("totals")
        print(f"reusing cached totals from {totals_path} ({len(totals)} CUSIPs)")
    if totals is None:
        # Checkpoint lives next to the repo (not in data/): the run takes
        # ~40 minutes and a VM restart must not lose it. A resume picks
        # up from the last finished batch.
        checkpoint_path = os.path.join(
            ROOT, "..", f"13f-checkpoint-{quarter_end.year}Q{(quarter_end.month - 1) // 3 + 1}.json")
        totals, stats = thirteenf.aggregate(quarter_end, checkpoint_path=checkpoint_path)
        _write(totals_path, {"quarter_end": quarter_end.isoformat(), "stats": stats, "totals": totals})
        print(f"cached totals to {totals_path}")

    out, _totals, stats = thirteenf.build_shareholding(tickers, quarter_end, totals=totals)
    have = sum(1 for v in out.values() if v.get("institutions_pct") is not None)
    print(f"shareholding: {have}/{len(out)} tickers have an institutional %")
    for symbol in tickers:
        entry = out[symbol]
        pct = entry.get("institutions_pct")
        sole = entry.get("institutions_pct_sole")
        sole_dfnd = entry.get("institutions_pct_sole_dfnd")
        if pct is None:
            print(f"  {symbol}: — (cusip {entry.get('cusip')}, filers {entry.get('filers')})")
        else:
            print(f"  {symbol}: institutions {_fmt_pct(pct)} "
                  f"(SOLE-only {_fmt_pct(sole)} / SOLE+DFND {_fmt_pct(sole_dfnd)}), "
                  f"shares {entry['institutions_shares']:,} / {entry['shares_outstanding']:,} "
                  f"as of {entry['shares_outstanding_asof']}, {entry['filers']} filers")

    out_path = args.out or os.path.join(ROOT, "data", "shareholding.json")
    _write(out_path, {
        "quarter": quarter_end.isoformat(),
        "label": label,
        "method": "SEC Form 13F-HR/HR-A information tables, all discretion (SOLE + DFND + SHRD), SH rows only, no put/call; "
                  "the common-stock CUSIP for each ticker is the candidate reported by the most distinct 13F managers, not the one "
                  "with the most reported shares — a mislabeled variant can attach a wrong CUSIP with a larger share total, as "
                  "Rocket Companies' 77311W101 did for Rocket Lab and Hub Group's did for Hubbell. "
                  "Shared-discretion blocks are de-duplicated by participant set (a DFND/SHRD row's otherManager references are "
                  "resolved to the other manager's filing via the 13F file number, and each block counts once at the largest amount "
                  "any participant reported). "
                  "Even after de-duplication the raw 13F sum can exceed 100% of shares outstanding for heavily shorted/lent stocks "
                  "(the same shares are reported by both the lender, which still owns them, and the buyer of the shorted shares), "
                  "so a figure above 100% is the raw filing total, not an aggregation error — independent references show the same "
                  "for Domino's (109%) and Skyworks (122%) in Q2 2026. "
                  "Denominator is shares outstanding as of the quarter end (EDGAR cover page). "
                  "Managers under $100M do not file; small positions and confidential-treatment holdings may be omitted, "
                  "so the figure can understate true institutional ownership. Insiders % is not in 13F filings.",
        "entries": out,
    })
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
