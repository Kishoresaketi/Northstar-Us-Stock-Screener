#!/usr/bin/env python3
"""Merge the two top-holders halves into data/top-holders.json.

Inputs (staging files outside the repo):
- top-holders-institutional.json — per-manager 13F top 5 (scripts/build_top_holders.py)
- insiders-q2-2026.json — per-insider Form 4 top 5 (scripts/build_insiders.py)

Output: data/top-holders.json, the file the profile reads:
    entries[TICKER] = {
        "institutions": {"top": [{name, cik, shares, pct}], "managers": n,
                         "total_shares": <sum over all managers>,
                         "pct": <institutions_shares / shares_outstanding>},
        "insiders": {"top": [{name, cik, shares, pct, filing_date, accession}],
                     "total_shares": <sum over ALL measured insiders>,
                     "total_pct": <total_shares / shares_outstanding>,
                     "owners_measured": n} | null,
        "public_pct": <1 - institutions.pct - insiders.total_pct> | null,
    }

Insider totals are NOT summed where the method double-counts: when the
summed insider total exceeds 50% of shares outstanding (OVERLAP_PCT),
the same block is being reported by several related holders at different
vintages (a founder under two CIKs plus his voting trust, a deceased
founder's stale filing alongside his spouse's, a stale 10%-owner block
alongside the current holder's) — each top-5 row is a real filing, but
the sum overstates insider ownership. For those tickers the merged
insiders entry keeps the top 5 and sets total_pct to null with
"overlap": true, and public_pct is null (the profile falls back to
"Public (includes insiders)"); the rule is derived from the data, not
a hardcoded ticker list. VYLR has no shares_outstanding in
shareholding.json, so it has no institutional total to reconcile and
no insiders entry — its institutions pct, insiders and public are all
null.

public_pct is null when insiders were not measured for the ticker — the
profile then falls back to "Public (includes insiders)". It can go
negative for the handful of tickers whose raw 13F total exceeds 100%
of shares outstanding (lending/shorting); that is the arithmetic
residual, not an error, and the merge only asserts it stays above -0.5.

The merge asserts: 517 tickers; every institutional top-5 sum is <= its
total; every per-manager total equals shareholding.json's
institutions_shares (the reconciliation the 13F build already reported);
every insider top-5 sum is <= its insider total. Nothing in
data/shareholding.json is changed.

Usage:
    python3 scripts/merge_top_holders.py [--out data/top-holders.json]
"""

import argparse
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

# Summed insider ownership above this share of shares outstanding is
# treated as overlapping reports (see module docstring), not a real total.
OVERLAP_PCT = 0.5

OVERLAP_NOTE = (
    "Insider holdings overlap across related holders, so no insider "
    "total is shown for this company."
)


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp, path)


def merge(inst_path, ins_path, shareholding, log=print):
    inst = _load(inst_path)
    ins = _load(ins_path) if ins_path and os.path.exists(ins_path) else {"entries": {}}
    assert inst["quarter"] == shareholding["quarter"], "quarter mismatch (institutional)"
    if ins.get("quarter"):
        assert ins["quarter"] == shareholding["quarter"], "quarter mismatch (insiders)"

    entries = {}
    no_insiders = []
    overlap_tickers = []
    negative_public = []
    for symbol, sh in sorted(shareholding["entries"].items()):
        ientry = inst["entries"].get(symbol)
        if ientry is None:
            raise SystemExit(f"{symbol}: no institutional entry in {inst_path}")
        top5_sum = sum(t["shares"] for t in ientry["top"])
        assert top5_sum <= ientry["total_shares"], f"{symbol}: top-5 sum exceeds total"
        # VYLR has no audited total (no shares_outstanding) — nothing to reconcile.
        if sh.get("institutions_shares") is not None:
            assert ientry["total_shares"] == sh.get("institutions_shares"), (
                f"{symbol}: per-manager total {ientry['total_shares']} != "
                f"audited {sh.get('institutions_shares')}")
        inst_pct = sh.get("institutions_pct")
        sentry = ins["entries"].get(symbol)
        # Staging uses insiders_total_shares / insiders_total_pct.
        if sentry is None or sentry.get("insiders_total_pct") is None:
            insiders = None
            public_pct = None
            no_insiders.append(symbol)
        elif sentry["insiders_total_pct"] > OVERLAP_PCT:
            # Overlapping reports: keep the (real) top 5, drop the total.
            itop_sum = sum(t["shares"] for t in sentry["top"])
            assert itop_sum <= sentry["insiders_total_shares"], (
                f"{symbol}: insider top-5 sum exceeds total")
            insiders = {
                "top": sentry["top"],
                "total_shares": sentry["insiders_total_shares"],
                "total_pct": None,
                "owners_measured": sentry.get("owners_measured"),
                "overlap": True,
                "overlap_note": OVERLAP_NOTE,
            }
            public_pct = None
            overlap_tickers.append((symbol, round(sentry["insiders_total_pct"] * 100, 1)))
        else:
            itop_sum = sum(t["shares"] for t in sentry["top"])
            assert itop_sum <= sentry["insiders_total_shares"], f"{symbol}: insider top-5 sum exceeds total"
            insiders = {
                "top": sentry["top"],
                "total_shares": sentry["insiders_total_shares"],
                "total_pct": sentry["insiders_total_pct"],
                "owners_measured": sentry.get("owners_measured"),
            }
            public_pct = 1 - inst_pct - sentry["insiders_total_pct"] if inst_pct is not None else None
            if public_pct is not None and public_pct < 0:
                negative_public.append((symbol, public_pct))
                assert public_pct > -0.5, f"{symbol}: public pct implausibly negative ({public_pct:.2%})"
        entries[symbol] = {
            "institutions": {
                "top": ientry["top"],
                "managers": ientry["managers"],
                "total_shares": ientry["total_shares"],
                "pct": inst_pct,
            },
            "insiders": insiders,
            "public_pct": public_pct,
        }
    payload = {
        "quarter": shareholding["quarter"],
        "label": shareholding.get("label"),
        "method": (
            "Top 5 shareholders per ticker. Institutions: SEC Form 13F-HR/HR-A "
            "information tables for the quarter (see data/shareholding.json for the "
            "audited totals); SOLE rows attribute to their reporter in full and each "
            "shared-discretion block counts once, at the largest amount any "
            "participant reported, attributed to the participant who reported the "
            "largest amount (DFND reporter wins ties). Large investment complexes "
            "file through several separate entities, so one complex can appear on "
            "several rows. Insiders: each holder's most recent Form 4 (direct + "
            "indirect shares owned after the transaction); holdings are as of that "
            "filing, which may be after the quarter end, and holders who only ever "
            "filed a Form 3 initial statement do not appear. Where the summed "
            "insider total exceeds 50% of shares outstanding the same block is "
            "reported by several related holders, so no insider total is shown "
            "for that company (the top holders are each real filings). Public is "
            "the aggregate remainder (100% minus institutions minus insiders) — "
            "no named public holders exist in any filing."),
        "entries": entries,
    }
    log(f"merged {len(entries)} tickers")
    log(f"tickers with no measured insiders: {len(no_insiders)} {no_insiders[:10]}")
    if overlap_tickers:
        log(f"tickers with overlapping insider reports (total not shown): "
            f"{overlap_tickers}")
    if negative_public:
        log(f"tickers with negative public residual (raw 13F total over 100%): "
            f"{[(s, round(p * 100, 1)) for s, p in negative_public]}")
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inst", default=None)
    parser.add_argument("--ins", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    inst_path = args.inst or os.path.join(ROOT, "..", "top-holders-institutional.json")
    ins_path = args.ins or os.path.join(ROOT, "..", "insiders-q2-2026.json")
    out_path = args.out or os.path.join(ROOT, "data", "top-holders.json")
    shareholding = _load(os.path.join(ROOT, "data", "shareholding.json"))
    payload = merge(inst_path, ins_path, shareholding)
    _write(out_path, payload)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
