#!/usr/bin/env python3
"""Rebuild data/financials/*.json with the Screener.in additions: the
accounts-payable field plus the days-payable, working-capital-days
and cash-conversion-cycle ratios added by the pipeline change.

Only the statements keys are replaced (annual / quarterly / ratios /
quarterly_ratios); price, metrics, peers, pros, cons, asOf and source
are preserved from the existing file, so the rebuild changes no
unrelated data. A ticker that fails to rebuild keeps its old file.

Usage:
    python3 scripts/rebuild_financials.py [--backup DIR] [--workers N]
    python3 scripts/rebuild_financials.py --validate-only [--backup DIR]

The validation pass compares every rebuilt file against its backup
and writes scripts/screenerin-rebuild-validation-2026-11-21.json plus
a printed summary: old-field diffs, annual changes (new years vs
restated values), quarterly cash-flow sum checks, and Q4-vs-annual
balance checks. New fields (payables and the three new ratios) are
counted as coverage, not as changes to old values.
"""
import argparse
import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import lib.edgar as edgar

DATA = os.path.join(ROOT, "data", "financials")
REPORT = os.path.join(os.path.dirname(__file__),
                      "screenerin-rebuild-validation-2026-11-21.json")
OLD_FIELDS = ["revenue", "operating_income", "net_income", "eps"]
FLOW_FIELDS = ["cfo", "capex", "dividends"]
BALANCE_FIELDS = ["assets", "equity", "cash", "debt"]


def file_for(symbol):
    return "".join(c if c.isalnum() or c == "." else "_" for c in symbol)


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def rebuild_one(symbol, backup_dir):
    """Rebuild one ticker's financials file; returns (symbol, error)."""
    path = os.path.join(DATA, file_for(symbol) + ".json")
    try:
        old = load(path)
    except (OSError, ValueError) as exc:
        return symbol, f"no readable old file: {exc}"
    try:
        stmts = edgar.statements(symbol)
    except Exception as exc:  # noqa: BLE001 - keep the old file
        return symbol, f"statements failed: {exc!r}"
    new = dict(old)
    new["annual"] = stmts["annual"]
    new["quarterly"] = stmts["quarterly"]
    new["ratios"] = stmts["ratios"]
    new["quarterly_ratios"] = stmts["quarterly_ratios"]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(new, fh)
    os.replace(tmp, path)
    return symbol, None


def validate(backup_dir):
    """Compare every rebuilt file against its backup. Returns a report."""
    report = {"tickers": 0, "failed": [], "old_quarterly_diffs": [],
              "annual_new_years": [], "annual_changed": [],
              "ratio_new_years": [], "ratio_changed": [],
              "sum_mismatches": [], "q4_mismatches": [],
              "coverage": {}, "no_quarterly_ratios": []}
    symbols = sorted(f[:-5] for f in os.listdir(backup_dir)
                     if f.endswith(".json"))
    new_fields = ["cash", "assets", "debt", "equity", "curr_assets",
                  "curr_liab", "receivables", "inventory", "cfo",
                  "capex", "fcf", "dividends", "cogs", "payables"]
    ratio_fields = ["opm", "net_margin", "roe", "roce", "debt_equity",
                    "current_ratio", "asset_turnover", "debtor_days",
                    "inventory_days", "payable_days",
                    "working_capital_days", "ccc"]
    cover = {f: 0 for f in new_fields + ["q_" + r for r in ratio_fields]}
    cover_quarters = 0
    for symbol in symbols:
        report["tickers"] += 1
        try:
            old = load(os.path.join(backup_dir, symbol + ".json"))
            new = load(os.path.join(DATA, symbol + ".json"))
        except (OSError, ValueError) as exc:
            report["failed"].append({"symbol": symbol, "error": str(exc)})
            continue
        oldq = {x["label"]: x for x in old.get("quarterly", [])}
        newq = {x["label"]: x for x in new.get("quarterly", [])}
        for lab, ox in oldq.items():
            nx = newq.get(lab)
            if nx is None:
                report["old_quarterly_diffs"].append(
                    {"symbol": symbol, "label": lab, "field": "label",
                     "old": "present", "new": "missing"})
                continue
            for f in OLD_FIELDS:
                if ox.get(f) != nx.get(f):
                    report["old_quarterly_diffs"].append(
                        {"symbol": symbol, "label": lab, "field": f,
                         "old": ox.get(f), "new": nx.get(f)})
        olda = {a["fy"]: a for a in old.get("annual", [])}
        for na in new.get("annual", []):
            oa = olda.get(na["fy"])
            if oa is None:
                report["annual_new_years"].append(
                    {"symbol": symbol, "fy": na["fy"]})
            else:
                # Only keys the old row already had count as a change;
                # brand-new fields (payables) are coverage, not a diff.
                changed = {k: [oa.get(k), na.get(k)] for k in na
                           if k in oa and oa.get(k) != na.get(k)}
                if changed:
                    report["annual_changed"].append(
                        {"symbol": symbol, "fy": na["fy"], "fields": changed})
        oldr = {r["fy"]: r for r in old.get("ratios", [])}
        for nr in new.get("ratios", []):
            orr = oldr.get(nr["fy"])
            if orr is None:
                report["ratio_new_years"].append(
                    {"symbol": symbol, "fy": nr["fy"]})
            else:
                changed = {k: [orr.get(k), nr.get(k)] for k in nr
                           if k in orr and orr.get(k) != nr.get(k)}
                if changed:
                    report["ratio_changed"].append(
                        {"symbol": symbol, "fy": nr["fy"], "fields": changed})
        ann = {a["fy"]: a for a in new.get("annual", [])}
        for lab, nx in newq.items():
            cover_quarters += 1
            for f in new_fields:
                if nx.get(f) is not None:
                    cover[f] += 1
        if not new.get("quarterly_ratios"):
            report["no_quarterly_ratios"].append(symbol)
        else:
            for qr in new["quarterly_ratios"]:
                for r in ratio_fields:
                    if qr.get(r) is not None:
                        cover["q_" + r] += 1
        # Four quarterly flows must sum to the annual figure (the Q4
        # derivation anchors on the annual value, so a mismatch means
        # the inputs were inconsistent, not a rounding error).
        by_fy = {}
        for lab, nx in newq.items():
            try:
                fy = int(lab.split("FY")[1])
            except (IndexError, ValueError):
                continue
            by_fy.setdefault(fy, {})[lab.split()[0]] = nx
        for fy, qs in by_fy.items():
            if fy not in ann or not all(f"Q{n}" in qs for n in (1, 2, 3, 4)):
                continue
            for f in FLOW_FIELDS:
                vals = [qs[f"Q{n}"].get(f) for n in (1, 2, 3, 4)]
                if any(v is None for v in vals):
                    continue
                if ann[fy].get(f) is None:
                    continue
                if abs(sum(vals) - ann[fy][f]) > 1:
                    report["sum_mismatches"].append(
                        {"symbol": symbol, "fy": fy, "field": f,
                         "four_quarter_sum": sum(vals),
                         "annual": ann[fy][f]})
            for f in BALANCE_FIELDS:
                if qs["Q4"].get(f) is not None and ann[fy].get(f) is not None:
                    if qs["Q4"][f] != ann[fy][f]:
                        report["q4_mismatches"].append(
                            {"symbol": symbol, "fy": fy, "field": f,
                             "q4": qs["Q4"][f], "annual": ann[fy][f]})
    report["coverage"] = {"quarters": cover_quarters, **cover}
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", default="/tmp/financials-backup-screenerin-2026-11-21")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--validate-only", action="store_true")
    args = ap.parse_args()

    if not args.validate_only:
        if os.path.isdir(args.backup):
            shutil.rmtree(args.backup)
        shutil.copytree(DATA, args.backup)
        print(f"backup: {args.backup} ({len(os.listdir(args.backup))} files)")
        universe = json.load(open(os.path.join(
            ROOT, "scripts", "universe", "universe.json"), encoding="utf-8"))
        symbols = sorted(universe)
        print(f"rebuilding {len(symbols)} tickers with {args.workers} workers...")
        failed = []
        done = 0
        started = time.time()
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(rebuild_one, s, args.backup): s for s in symbols}
            for fut in as_completed(futs):
                sym, err = fut.result()
                done += 1
                if err:
                    failed.append({"symbol": sym, "error": err})
                if done % 100 == 0:
                    print(f"  {done}/{len(symbols)} ({time.time()-started:.0f}s)")
        print(f"rebuilt {done - len(failed)}/{len(symbols)} "
              f"in {time.time()-started:.0f}s; failed: {len(failed)}")
        for f in failed:
            print("  FAILED:", f)
    report = validate(args.backup)
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(f"validation report: {REPORT}")
    print(f"tickers checked: {report['tickers']}")
    print(f"old quarterly field diffs: {len(report['old_quarterly_diffs'])}")
    print(f"annual new years: {len(report['annual_new_years'])}; "
          f"annual changed values: {len(report['annual_changed'])}")
    print(f"ratio new years: {len(report['ratio_new_years'])}; "
          f"ratio changed values: {len(report['ratio_changed'])}")
    print(f"quarterly sum mismatches: {len(report['sum_mismatches'])}")
    print(f"Q4-vs-annual mismatches: {len(report['q4_mismatches'])}")
    print(f"tickers with no quarterly ratios: {len(report['no_quarterly_ratios'])}")
    cov = report["coverage"]
    print(f"quarters total: {cov['quarters']}")
    for f in ["cash", "assets", "debt", "equity", "cfo", "capex", "fcf",
              "dividends", "cogs", "curr_assets", "receivables", "inventory",
              "payables"]:
        print(f"  {f}: {cov[f]} / {cov['quarters']}")
    for r in ["opm", "net_margin", "roe", "roce", "debt_equity",
              "current_ratio", "asset_turnover", "debtor_days",
              "inventory_days", "payable_days", "working_capital_days",
              "ccc"]:
        print(f"  ratio {r}: {cov['q_' + r]} / {cov['quarters']}")


if __name__ == "__main__":
    main()
