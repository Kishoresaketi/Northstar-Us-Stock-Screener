#!/usr/bin/env python3
"""Regenerate the per-ticker 13F diagnostics file.

    python3 scripts/validate_shareholding.py
    python3 scripts/validate_shareholding.py --quarter 2026-06-30

Reads data/shareholding.json (the built ownership figures) and the
cached per-CUSIP totals data/13f-totals-2026Q2.json, re-runs the CUSIP
resolution to rebuild every ticker's candidate pool, and writes
data/shareholding-diagnostics-2026Q2.json: one record per ticker with
the selected CUSIP, every candidate CUSIP considered, distinct
reporting managers, institutional shares, shares outstanding,
calculated ownership, reporting period, security class, mapping
confidence, and data-quality flags. No network access — everything
comes from the cached totals and the built shareholding file, so the
diagnostics for a quarter are reproducible without re-downloading
~8,900 filings.

Flags (each record's "flags" list):
  over_100            institutional % above 100 — investigate, never cap
  no_pct              no ownership figure (no CUSIP or no denominator)
  low_confidence      mapping confidence low (close margin vs runner-up)
  medium_confidence   mapping confidence medium
  close_margin        runner-up has >50% of the winner's filers
  thin                winner reported by <100 managers
  no_exact_stage      no non-excluded candidate matched the name exactly
  class_fallback      class ticker whose winner has no class match
  ambiguous_near_tie  runner-up within 90% of winner at another stage
  runner_up_dominates runner-up has >=2x the winner's filers
  stale_denominator   shares-outstanding as-of date before the quarter end
  fallback_denominator no as-of date (weighted-average fallback, not a cover count)
  override_denominator denominator pinned from a filing cover (see
                      SHARES_OUTSTANDING_OVERRIDES in lib/thirteenf.py)
  multi_cusip_group   holdings summed across several CUSIPs (CUSIP_GROUPS)
  no_cusip            no CUSIP resolved for the ticker
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


def _write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
    os.replace(tmp, path)


def _totals_path(quarter_end):
    return os.path.join(
        ROOT, "data",
        f"13f-totals-{quarter_end.year}Q{(quarter_end.month - 1) // 3 + 1}.json")


def build_diagnostics(quarter_end, shareholding_path, totals_path):
    with open(shareholding_path, encoding="utf-8") as fh:
        shareholding = json.load(fh)
    entries = shareholding.get("entries", shareholding)
    with open(totals_path, encoding="utf-8") as fh:
        totals = json.load(fh).get("totals", {})

    universe = edgar.universe()
    _mapping, _unmatched, _ambiguous, pools = thirteenf.build_cusip_map(
        totals, universe)

    records = {}
    for symbol in sorted(entries):
        entry = entries[symbol]
        info = universe.get(symbol, {})
        cusip = entry.get("cusip")
        tot = totals.get(cusip, {}) if cusip else {}
        pool = pools.get(symbol, [])
        selected = next((r for r in pool if r.get("selected")), None)
        confidence = (selected or {}).get("confidence") or entry.get("mapping_confidence")
        warnings = (selected or {}).get("warnings") or entry.get("mapping_warnings") or []
        pct = entry.get("institutions_pct")
        so_asof = entry.get("shares_outstanding_asof")
        flags = list(warnings)
        if pct is None:
            flags.append("no_pct")
        elif pct > 1.0:
            flags.append("over_100")
        if confidence == "low":
            flags.append("low_confidence")
        elif confidence == "medium":
            flags.append("medium_confidence")
        if not cusip:
            flags.append("no_cusip")
        if so_asof is None and entry.get("shares_outstanding") is not None:
            flags.append("fallback_denominator")
        elif so_asof and so_asof < quarter_end.isoformat():
            flags.append("stale_denominator")
        if symbol in thirteenf.SHARES_OUTSTANDING_OVERRIDES:
            flags.append("override_denominator")
        if len(entry.get("cusips") or []) > 1:
            flags.append("multi_cusip_group")
        records[symbol] = {
            "ticker": symbol,
            "company": info.get("name"),
            "quarter": entry.get("quarter") or quarter_end.isoformat(),
            "cusip": cusip,
            "cusips": entry.get("cusips") or ([cusip] if cusip else []),
            "security_class": tot.get("class"),
            "candidate_cusips": [
                {
                    "cusip": r["cusip"],
                    "stage": r["stage"],
                    "filers": r["filers"],
                    "shares": r["shares"],
                    "shares_all": r["shares_all"],
                    "common_class": r["common_class"],
                    "excluded": r["excluded"],
                    "name": r["name"],
                    "class": r["class"],
                    "selected": bool(r.get("selected")),
                    "score": r.get("score"),
                    "confidence": r.get("confidence"),
                    "warnings": r.get("warnings"),
                }
                for r in pool
            ],
            "distinct_managers": entry.get("filers"),
            "institutions_shares": entry.get("institutions_shares"),
            "shares_outstanding": entry.get("shares_outstanding"),
            "shares_outstanding_asof": so_asof,
            "institutions_pct": pct,
            "institutions_pct_sole": entry.get("institutions_pct_sole"),
            "institutions_pct_sole_dfnd": entry.get("institutions_pct_sole_dfnd"),
            "mapping_confidence": confidence,
            "mapping_warnings": warnings,
            "flags": sorted(set(flags)),
        }

    summary = {
        "quarter": quarter_end.isoformat(),
        "tickers": len(records),
        "with_pct": sum(1 for r in records.values() if r["institutions_pct"] is not None),
        "no_pct": [s for s, r in records.items() if r["institutions_pct"] is None],
        "over_100": sorted(
            (s for s, r in records.items()
             if r["institutions_pct"] is not None and r["institutions_pct"] > 1.0),
            key=lambda s: -records[s]["institutions_pct"]),
        "by_confidence": {
            c: sum(1 for r in records.values() if r["mapping_confidence"] == c)
            for c in ("high", "medium", "low", "override", None)
        },
        "flag_counts": {},
    }
    for r in records.values():
        for f in r["flags"]:
            summary["flag_counts"][f] = summary["flag_counts"].get(f, 0) + 1
    return {"summary": summary, "records": records}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quarter", default="2026-06-30",
                        help="quarter end YYYY-MM-DD (default: 2026-06-30)")
    parser.add_argument("--shareholding", default=None,
                        help="shareholding.json path (default: data/shareholding.json)")
    parser.add_argument("--totals", default=None,
                        help="13f-totals path (default: data/13f-totals-<quarter>.json)")
    parser.add_argument("--out", default=None,
                        help="diagnostics output path (default: data/shareholding-diagnostics-2026Q2.json)")
    args = parser.parse_args()

    quarter_end = date.fromisoformat(args.quarter)
    shareholding_path = args.shareholding or os.path.join(ROOT, "data", "shareholding.json")
    totals_path = args.totals or _totals_path(quarter_end)
    out_path = args.out or os.path.join(
        ROOT, "data", f"shareholding-diagnostics-{quarter_end.year}Q{(quarter_end.month - 1) // 3 + 1}.json")

    payload = build_diagnostics(quarter_end, shareholding_path, totals_path)
    _write(out_path, payload)
    s = payload["summary"]
    print(f"diagnostics: {s['tickers']} tickers, {s['with_pct']} with a %, "
          f"{len(s['over_100'])} over 100%, {len(s['no_pct'])} without a %")
    print(f"confidence: {s['by_confidence']}")
    print(f"flags: {s['flag_counts']}")
    print(f"no pct: {s['no_pct']}")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
