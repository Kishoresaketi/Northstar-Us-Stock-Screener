#!/usr/bin/env python3
"""Build the per-manager 13F top holders for the 517-ticker universe.

The audited totals (data/shareholding.json) hold per-CUSIP sums only —
the per-manager rows were summed and discarded — so top holders cannot
be derived from the cache. This script re-downloads every 13F-HR/HR-A
information table for one quarter and keeps, per filing, only the SOLE
shares for universe CUSIPs. The shared (DFND/SHRD) part is NOT
re-downloaded: the participant-set groups already recorded in the
13F de-dup checkpoint (13f-checkpoint-2026Q2-dedup.json) carry the
per-reporter amounts, and reusing them guarantees the shared
attribution matches the audited totals exactly.

Per-manager holdings are then built with the same de-dup as the audited
totals (lib.thirteenf.per_manager_holdings): SOLE rows attribute to
their reporter in full; each shared block counts once, at the largest
amount any participant reported, attributed to the group winner (see
lib.thirteenf.group_winner). The per-manager sums reconcile exactly
with data/shareholding.json — the script reports the difference per
ticker and flags any ticker where the top-5 sum exceeds the total.

Usage:
    python3 scripts/build_top_holders.py [--quarter 2026-06-30]
    python3 scripts/build_top_holders.py --limit-filings 20   # smoke test
    python3 scripts/build_top_holders.py --finalize-only       # rebuild output from checkpoint

The download takes ~1 hour at the 5 req/s cap (index + information
table per filing, ~17,800 requests). Progress is checkpointed after
every 500 filings to top-holders-checkpoint-2026Q2.json next to the
repo, so an interrupted run resumes. The output is a staging file
outside the repo (top-holders-institutional.json); the merge into
data/top-holders.json happens in a separate step once the Form 4
insiders are ready. Nothing in data/shareholding.json is touched.
"""

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import lib.thirteenf as thirteenf

# The Form 4 insiders build ran concurrently against the same SEC
# endpoint; the two together stay under EDGAR's 10 requests/second.
# That build is finished, so the retry runs at the module default 8/s.
thirteenf.RATE_PER_SECOND = 8.0

BATCH_SIZE = 500


def _clean_name(display):
    """A filing's display name for the top-holders list: the trailing
    " (CIK ...)" suffix efts appends is dropped, and so is a trailing
    ticker-style parenthetical ("BlackRock, Inc. (BLK)", "STATE STREET
    CORP (STT, STT-PG)") — the CIK stays the key, the name is display
    only. A parenthetical with lowercase or other characters is left
    alone, so a real part of a name is never stripped."""
    name = re.sub(r"\s*\(CIK[^)]*\)\s*$", "", display or "").strip()
    name = re.sub(r"\s*\([A-Z0-9,\- ]{1,20}\)\s*$", "", name).strip()
    return name


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp, path)


def _fetch_sole(filing, universe_cusips):
    """SOLE shares for universe CUSIPs in one filing's information table.

    Returns (adsh, {cusip: shares}, error). Only the filing index and
    the information table are fetched — no cover document, because the
    shared-row resolution already lives in the de-dup checkpoint.
    """
    try:
        items = thirteenf._index_items(filing["cik"], filing["adsh"])
        url = thirteenf._infotable_url_from_items(filing["cik"], filing["adsh"], items)
        if not url:
            return filing["adsh"], {}, "no information table in index"
        xml_bytes = thirteenf._get(url, timeout=60)
        _counted, sole, _all_disc, _names, _shared = thirteenf.parse_infotable(xml_bytes)
        return filing["adsh"], {c: s for c, s in sole.items() if c in universe_cusips}, None
    except Exception as exc:  # noqa: BLE001 — one bad filing must not stop the run
        return filing["adsh"], {}, str(exc)


def download(quarter_end, checkpoint_path, shareholding, limit=None, log=print):
    """Download SOLE rows for universe CUSIPs, resumable via checkpoint."""
    dedup_path = os.path.join(ROOT, "..",
                              f"13f-checkpoint-{quarter_end.year}Q{(quarter_end.month - 1) // 3 + 1}-dedup.json")
    if not os.path.exists(dedup_path):
        raise SystemExit(f"de-dup checkpoint not found: {dedup_path}")
    dedup = _load_json(dedup_path)
    filings = dedup["filings"]
    if limit:
        filings = filings[:limit]
    log(f"top holders {quarter_end.isoformat()}: {len(filings)} manager filings "
        f"(groups from {dedup_path})")

    universe_cusips = set()
    for entry in shareholding["entries"].values():
        universe_cusips.update(entry.get("cusips") or ([entry["cusip"]] if entry.get("cusip") else []))
    log(f"universe CUSIPs: {len(universe_cusips)}")

    sole_by_manager = {}
    # Names come from the full enumeration, not just the downloaded
    # filings: group winners can be managers whose filing has not been
    # downloaded yet (or failed), and their names must still resolve.
    names = {f["cik"]: _clean_name(f.get("display_name")) for f in dedup["filings"]}
    done = set()
    failed = []
    if os.path.exists(checkpoint_path):
        ck = _load_json(checkpoint_path)
        sole_by_manager = ck.get("sole_by_manager", {})
        names.update(ck.get("names", {}))
        done = set(ck.get("done_adsh", []))
        failed = ck.get("failed", [])
        log(f"resumed from checkpoint ({len(done)}/{len(filings)} filings done)")

    by_adsh = {f["adsh"]: f for f in filings}
    pending = [f for f in filings if f["adsh"] not in done]
    log(f"{len(pending)} filings left to parse")
    started = time.time()
    for batch_start in range(0, len(pending), BATCH_SIZE):
        batch = pending[batch_start:batch_start + BATCH_SIZE]
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(_fetch_sole, f, universe_cusips): f for f in batch}
            for future in as_completed(futures):
                filing = futures[future]
                adsh, sole, error = future.result()
                if error:
                    failed.append([adsh, error])
                    continue
                done.add(adsh)
                # A filing that failed in an earlier run and succeeds now
                # leaves the stale failure behind, or the checkpoint would
                # report it failed forever (the Nov 22 retry's checkpoint
                # still listed 869 failures after all 8,898 had succeeded).
                failed = [f for f in failed if f[0] != adsh]
                names[filing["cik"]] = _clean_name(filing.get("display_name"))
                if sole:
                    slot = sole_by_manager.setdefault(filing["cik"], {})
                    for cusip, shares in sole.items():
                        slot[cusip] = slot.get(cusip, 0) + shares
        _write(checkpoint_path, {"sole_by_manager": sole_by_manager,
                                 "names": names,
                                 "done_adsh": sorted(done),
                                 "failed": failed})
        elapsed = time.time() - started
        log(f"  ... {min(batch_start + BATCH_SIZE, len(pending))}/{len(pending)} filings parsed "
            f"({len(done)}/{len(filings)} total, {elapsed / 60:.1f} min elapsed)")
    log(f"download done: {len(done)} filings, {len(failed)} failed, "
        f"{len(sole_by_manager)} managers with universe SOLE rows")
    return sole_by_manager, names, done, failed, dedup


def finalize(quarter_end, checkpoint_path, shareholding, dedup, sole_by_manager, names,
             out_path, log=print):
    """Attribute shared blocks, rank top 5 per ticker, reconcile, write output."""
    groups = thirteenf._groups_from_json(dedup.get("groups"))
    log(f"attributing {len(groups)} shared groups ...")
    holdings = thirteenf.per_manager_holdings(sole_by_manager, groups)
    log(f"{len(holdings)} managers hold universe CUSIPs")

    entries = {}
    worst = []
    for symbol, entry in sorted(shareholding["entries"].items()):
        cusips = entry.get("cusips") or ([entry["cusip"]] if entry.get("cusip") else [])
        shares_out = entry.get("shares_outstanding")
        ranked = thirteenf.rank_top_holders(holdings, cusips, shares_out, top_n=5)
        total = ranked["total"]
        target = entry.get("institutions_shares")
        diff = (total - target) if (target is not None) else None
        diff_pct = (diff / target) if (target and diff is not None) else None
        if diff is not None and abs(diff_pct) > 0.001:
            worst.append((symbol, diff, diff_pct))
        top = []
        for item in ranked["top"]:
            top.append({"name": names.get(item["cik"], item["cik"]),
                        "cik": item["cik"],
                        "shares": item["shares"],
                        "pct": item["pct"]})
        entries[symbol] = {
            "top": top,
            "managers": ranked["managers"],
            "total_shares": total,
            "institutions_shares": target,
            "diff_shares": diff,
            "cusips": cusips,
        }
    top5_over = [s for s, e in entries.items()
                 if e["institutions_shares"] is not None
                 and sum(t["shares"] for t in e["top"]) > e["institutions_shares"]]
    payload = {
        "quarter": quarter_end.isoformat(),
        "label": shareholding.get("label"),
        "method": ("Per-manager 13F holdings, Q2 2026. SOLE rows attribute to "
                   "their reporter in full; each shared-discretion block counts "
                   "once, at the largest amount any participant reported, "
                   "attributed to the participant who reported the largest amount "
                   "(DFND reporter wins ties). Same participant-set de-dup as "
                   "data/shareholding.json; per-manager sums reconcile with its "
                   "institutions_shares."),
        "entries": entries,
    }
    _write(out_path, payload)
    log(f"wrote {out_path} ({len(entries)} tickers)")
    if worst:
        log(f"RECONCILIATION: {len(worst)} tickers differ from shareholding.json by >0.1%:")
        for symbol, diff, diff_pct in sorted(worst, key=lambda w: -abs(w[2]))[:20]:
            log(f"  {symbol}: diff {diff:+,} shares ({diff_pct:+.2%})")
    else:
        log("reconciliation: all tickers within 0.1% of shareholding.json")
    if top5_over:
        log(f"FLAG: top-5 sum exceeds the audited total for: {top5_over}")
    else:
        log("top-5 sums are all <= the audited totals")
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quarter", default="2026-06-30", help="quarter end YYYY-MM-DD")
    parser.add_argument("--limit-filings", type=int, default=None, help="smoke test: parse only the first N filings")
    parser.add_argument("--finalize-only", action="store_true", help="rebuild output from checkpoint, no downloading")
    parser.add_argument("--out", default=None, help="staging output path")
    args = parser.parse_args()

    quarter_end = date.fromisoformat(args.quarter)
    suffix = f"{quarter_end.year}Q{(quarter_end.month - 1) // 3 + 1}"
    checkpoint_path = os.path.join(ROOT, "..", f"top-holders-checkpoint-{suffix}.json")
    out_path = args.out or os.path.join(ROOT, "..", "top-holders-institutional.json")
    shareholding = _load_json(os.path.join(ROOT, "data", "shareholding.json"))

    if args.finalize_only:
        ck = _load_json(checkpoint_path)
        dedup = _load_json(os.path.join(ROOT, "..", f"13f-checkpoint-{suffix}-dedup.json"))
        # Names from the full enumeration (see download()): group winners
        # can be managers whose filing is not in this checkpoint's names.
        names = {f["cik"]: _clean_name(f.get("display_name")) for f in dedup["filings"]}
        names.update(ck.get("names", {}))
        finalize(quarter_end, checkpoint_path, shareholding, dedup,
                 ck.get("sole_by_manager", {}), names, out_path)
        return 0

    sole_by_manager, names, _done, _failed, dedup = download(
        quarter_end, checkpoint_path, shareholding, limit=args.limit_filings)
    finalize(quarter_end, checkpoint_path, shareholding, dedup,
             sole_by_manager, names, out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
