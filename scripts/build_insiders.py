#!/usr/bin/env python3
"""Build the per-ticker Form 4 insider holdings for the 517-ticker universe.

Staging output only — nothing here writes into data/ or merges into
data/top-holders.json (the parent merges the staging file later).
The 13F institutional half is built separately, concurrently, by
scripts/build_top_holders.py at 5 req/s; this script stays at 4 req/s
(lib/form4.RATE_PER_SECOND) so the two together stay under EDGAR's
10 req/s.

Usage:
    python3 scripts/build_insiders.py [--quarter 2026-06-30]
    python3 scripts/build_insiders.py --tickers AAPL,GOOGL  # smoke test
    python3 scripts/build_insiders.py --limit 5
    python3 scripts/build_insiders.py --finalize-only  # rebuild output from checkpoint

Progress is checkpointed after every ticker to
~/workspace/northstar-screener/insiders-checkpoint-2026Q2.json, so an
interrupted run resumes instead of restarting. Downloaded Form 4 XMLs
are cached under ~/workspace/northstar-screener/form4-cache/ (shared
across tickers — class pairs enumerate the same filings). The staging
output is ~/workspace/northstar-screener/insiders-q2-2026.json.
data/shareholding.json is read-only here: its md5 is checked at start
and at end (expected 4883705c0778f77f9b8e88ff3fc0c4d6).
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import lib.form4 as form4

SHAREHOLDING_MD5 = "4883705c0778f77f9b8e88ff3fc0c4d6"
WORKSPACE = os.path.join(ROOT, "..")
METHOD = (
    "Form 4 insider holdings, Q2 2026 label. Per issuer, Form 4 and 4/A "
    "filings enumerated via EDGAR full-text search (efts.sec.gov) over "
    "2016-01-01 to 2026-11-22; one XML per reporting owner, their most "
    "recent filing by file_date (accession breaks ties), an amendment "
    "superseding the original; if that filing reports no common-stock "
    "non-derivative holding, the next most recent filing is tried (up "
    "to 10). Parsing uses the nonDerivativeTable only; rows group into "
    "holding buckets by (title, direct/indirect, natureOfOwnership "
    "text), the last row per bucket is its balance, and the holding is "
    "the sum of the buckets (one filing can carry several indirect "
    "trusts). Security title must be the ticker's common stock: 53 "
    "class tickers match their class letter (derived from the ticker's "
    "own 13F titleOfClass variants, plus BF-B and META by hand), a bare "
    "'Common Stock' title also counts. Joint filings are attributed "
    "once, to the first reporting owner in the XML. Indirect-mirror "
    "de-dup: an indirect bucket naming another measured owner whose "
    "total exactly equals the bucket is removed, so the block counts "
    "once under the direct holder; the gross total is kept as "
    "insiders_total_shares_gross with dedup_notes naming each removed "
    "block. Percentages use shares_outstanding from "
    "data/shareholding.json. As-of caveat: each holder's figure is as "
    "of their most recent Form 4, which may be after the Jun 30, 2026 "
    "quarter end; former insiders who still hold shares keep their "
    "last reported holding; holders who only ever filed a Form 3 never "
    "appear in Form 4 data."
)


def _md5(path):
    digest = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp, path)


def build(quarter_end, checkpoint_path, out_path, cache_dir, tickers=None,
          limit=None, log=print):
    shareholding_path = os.path.join(ROOT, "data", "shareholding.json")
    md5 = _md5(shareholding_path)
    if md5 != SHAREHOLDING_MD5:
        raise SystemExit(f"shareholding.json md5 {md5} != expected {SHAREHOLDING_MD5}; refusing to run")
    log(f"shareholding.json md5 OK ({md5})")
    shareholding = _load_json(shareholding_path)
    cik_map = _load_json(os.path.join(ROOT, "data", "cik-map.json"))

    symbols = sorted(shareholding["entries"])
    if tickers:
        symbols = [s for s in tickers if s in shareholding["entries"]]
        missing = [s for s in tickers if s not in shareholding["entries"]]
        if missing:
            log(f"WARNING: not in shareholding.json, skipped: {missing}")
    if limit:
        symbols = symbols[:limit]
    log(f"insiders {quarter_end.isoformat()}: {len(symbols)} tickers")

    entries = {}
    diagnostics = {}
    failed = []
    if os.path.exists(checkpoint_path):
        ck = _load_json(checkpoint_path)
        entries = ck.get("entries", {})
        diagnostics = ck.get("diagnostics", {})
        failed = ck.get("failed", [])
        log(f"resumed from checkpoint ({len(entries)}/{len(symbols)} tickers done)")
    failed_symbols = {f[0] for f in failed}

    started = time.time()
    for i, symbol in enumerate(symbols):
        if symbol in entries:
            continue
        entry_data = shareholding["entries"][symbol]
        shares_out = entry_data.get("shares_outstanding")
        cik_entry = cik_map.get(symbol, {})
        issuer_cik = form4.issuer_cik_for(symbol, cik_entry.get("cik"))
        if not shares_out or not issuer_cik:
            failed.append([symbol, "no shares_outstanding or CIK"])
            log(f"  {symbol}: FAILED (no shares_outstanding or CIK)")
            continue
        try:
            entry, diag = form4.build_ticker(
                symbol, issuer_cik, shares_out, cache_dir=cache_dir, log=log)
        except Exception as exc:  # noqa: BLE001 — one bad ticker must not stop the run
            failed.append([symbol, str(exc)])
            log(f"  {symbol}: FAILED ({exc})")
            _write(checkpoint_path, {"quarter": quarter_end.isoformat(),
                                     "entries": entries,
                                     "diagnostics": diagnostics,
                                     "failed": failed})
            continue
        entries[symbol] = entry
        diagnostics[symbol] = diag
        failed_symbols.discard(symbol)
        failed = [f for f in failed if f[0] != symbol]
        _write(checkpoint_path, {"quarter": quarter_end.isoformat(),
                                 "entries": entries,
                                 "diagnostics": diagnostics,
                                 "failed": failed})
        _write(out_path, {"quarter": quarter_end.isoformat(),
                          "built": date.today().isoformat(),
                          "method": METHOD,
                          "entries": entries})
        elapsed = time.time() - started
        done = len(entries)
        log(f"[{done}/{len(symbols)}] {symbol} done "
            f"({elapsed / 60:.1f} min elapsed, "
            f"{elapsed / max(done, 1):.1f}s/ticker avg)")

    # Verification pass: a transient SEC failure makes build_ticker fall
    # back to an owner's older filing (a failed fetch is not a "no
    # holding" verdict), which silently changes that owner's holding —
    # on AAPL, Robert Iger's 2019 filing failed once and the run used
    # his 2018 filing instead (49,050 vs 50,571 shares). Rebuild every
    # ticker whose diagnostics record fetch errors: the cache makes the
    # re-run cheap (only the failed accessions re-download), and any
    # changed total is logged. Tickers that still fail keep their
    # first-pass entry and stay listed in the report.
    retry_symbols = [s for s in symbols
                     if diagnostics.get(s, {}).get("fetch_errors")]
    if retry_symbols:
        log(f"verification pass: re-running {len(retry_symbols)} tickers "
            f"with fetch errors: {retry_symbols}")
        for symbol in retry_symbols:
            entry_data = shareholding["entries"][symbol]
            try:
                entry, diag = form4.build_ticker(
                    symbol, form4.issuer_cik_for(symbol, cik_map[symbol]["cik"]),
                    entry_data.get("shares_outstanding"),
                    cache_dir=cache_dir, log=log)
            except Exception as exc:  # noqa: BLE001 — keep the first-pass entry
                log(f"  {symbol}: verification re-run failed ({exc}); keeping first pass")
                continue
            old_total = entries[symbol]["insiders_total_shares"]
            new_total = entry["insiders_total_shares"]
            entries[symbol] = entry
            diagnostics[symbol] = diag
            _write(checkpoint_path, {"quarter": quarter_end.isoformat(),
                                     "entries": entries,
                                     "diagnostics": diagnostics,
                                     "failed": failed})
            _write(out_path, {"quarter": quarter_end.isoformat(),
                              "built": date.today().isoformat(),
                              "method": METHOD,
                              "entries": entries})
            if new_total != old_total:
                log(f"  {symbol}: total changed on re-run "
                    f"{old_total:,} -> {new_total:,} shares")
            else:
                log(f"  {symbol}: re-run confirms {new_total:,} shares "
                    f"(fetch errors now: {len(diag.get('fetch_errors', []))})")

    payload = {"quarter": quarter_end.isoformat(),
               "built": date.today().isoformat(),
               "method": METHOD,
               "entries": entries}
    _write(out_path, payload)
    stats = {
        "tickers_built": len(entries),
        "tickers_failed": failed,
        "owners_measured": sum(e["owners_measured"] for e in entries.values()),
        "owners_no_holding": sum(e["owners_no_holding"] for e in entries.values()),
        "joint_filings": sum(e["joint_filings"] for e in entries.values()),
        "owners_joint_covered": sum(e.get("owners_joint_covered", 0) for e in entries.values()),
        "insiders_total_shares": sum(e["insiders_total_shares"] for e in entries.values()),
        "insiders_total_shares_gross": sum(e.get("insiders_total_shares_gross", e["insiders_total_shares"]) for e in entries.values()),
        "deduped_shares": sum(e.get("deduped_shares", 0) for e in entries.values()),
        "xml_fetched": sum(d.get("xml_fetched", 0) for d in diagnostics.values()),
        "xml_cache_hits": sum(d.get("xml_cache_hits", 0) for d in diagnostics.values()),
        "fetch_errors": sum(len(d.get("fetch_errors", [])) for d in diagnostics.values()),
        "efts_hits": sum(d.get("hits", 0) for d in diagnostics.values()),
        "efts_union_extra": sum(d.get("efts_union_extra", 0) for d in diagnostics.values()),
    }
    payload["stats"] = stats
    _write(out_path, payload)
    end_md5 = _md5(shareholding_path)
    log(f"shareholding.json md5 at end: {end_md5} "
        f"({'OK' if end_md5 == SHAREHOLDING_MD5 else 'CHANGED — INVESTIGATE'})")
    log(f"wrote {out_path} ({len(entries)} tickers, "
        f"{stats['owners_measured']} owners measured, "
        f"{stats['owners_no_holding']} no holding, "
        f"{stats['joint_filings']} joint filings, "
        f"{len(failed)} failed)")
    # Tripwire (review only, never auto-excludes): insiders cannot
    # plausibly own >50% of a listed issuer. A hit here means a
    # spoof filing (cf. Antonio Lee, EXCLUDED_OWNER_CIKS) or a class/
    # denominator error — investigate before merging.
    implausible = sorted(
        (s, round(e["insiders_total_pct"], 4))
        for s, e in entries.items()
        if e.get("insiders_total_pct") and e["insiders_total_pct"] > 0.5)
    if implausible:
        log(f"  IMPLAUSIBLE (>50% insider-owned) — investigate: {implausible}")
    if failed:
        for symbol, error in failed:
            log(f"  FAILED: {symbol}: {error}")
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quarter", default="2026-06-30", help="quarter end YYYY-MM-DD")
    parser.add_argument("--tickers", default=None, help="comma-separated tickers (smoke test)")
    parser.add_argument("--limit", type=int, default=None, help="build only the first N tickers")
    parser.add_argument("--finalize-only", action="store_true",
                        help="rebuild output from checkpoint, no downloading")
    parser.add_argument("--out", default=None, help="staging output path")
    parser.add_argument("--checkpoint", default=None, help="checkpoint path")
    parser.add_argument("--cache-dir", default=None, help="Form 4 XML cache dir")
    args = parser.parse_args()

    quarter_end = date.fromisoformat(args.quarter)
    suffix = f"{quarter_end.year}Q{(quarter_end.month - 1) // 3 + 1}"
    checkpoint_path = args.checkpoint or os.path.join(WORKSPACE, f"insiders-checkpoint-{suffix}.json")
    out_path = args.out or os.path.join(WORKSPACE, f"insiders-{suffix}.json")
    cache_dir = args.cache_dir or os.path.join(WORKSPACE, "form4-cache")

    if args.finalize_only:
        if not os.path.exists(checkpoint_path):
            raise SystemExit(f"checkpoint not found: {checkpoint_path}")
        ck = _load_json(checkpoint_path)
        payload = {"quarter": quarter_end.isoformat(),
                   "built": date.today().isoformat(),
                   "method": METHOD,
                   "entries": ck.get("entries", {})}
        _write(out_path, payload)
        print(f"wrote {out_path} ({len(payload['entries'])} tickers from checkpoint)")
        return 0

    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None
    build(quarter_end, checkpoint_path, out_path, cache_dir,
          tickers=tickers, limit=args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
