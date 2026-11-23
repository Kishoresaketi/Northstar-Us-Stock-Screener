"""SEC Form 13F institutional-ownership aggregation — free, no API key.

Method (documented, verifiable — nothing here is estimated):
- 13F-HR / 13F-HR-A filings for one quarter, enumerated through EDGAR's
  full-text search (efts.sec.gov) and filtered to the quarter's
  period_ending. One filing per manager per quarter: an amendment
  replaces the original (latest file_date wins); 13F-NT notices carry no
  holdings table and are never counted.
- Each filing's information table is parsed for SH rows with no put/call.
  A block of shares is counted ONCE, not once per filing that reports
  it: when investment discretion is shared, every manager sharing it
  reports the same block (SEC Form 13F instructions), so summing
  filings double-counts — that is why 58 tickers exceeded 100% before
  the de-dup. The fix: a DFND/SHRD row names its other managers
  (otherManager = sequence numbers into the filing's own other-managers
  list, resolved to CIKs through the 13F file number, which efts
  reports per filing); rows for one CUSIP are grouped by their full
  participant set (reporter + named managers), and each group counts
  once, at the largest amount any participant reported for it
  (participants file the same block with the same quarter-end value, so
  the max survives a stale or partial report). SOLE rows are never
  shared, so they count as reported. A row whose other managers do not
  file separately (the usual case — a filer's own affiliates) is the
  only report of its block and counts as-is. Berkshire's June 2026
  table is the check: all 89 rows are DFND naming its non-filing
  affiliates, and the de-duped total equals its reported 227,917,808
  Apple shares.
- Institutional % = summed 13F shares / shares outstanding as of the
  quarter end (latest dei cover-page count dated within 90 days after
  the quarter end, else the latest current count).
- Coverage limits (stated in the UI): managers under $100M in 13(f)
  securities do not file; small positions may be omitted; some holdings
  sit under confidential treatment. The figure is the 13F-reported
  total, which can understate true institutional ownership slightly.
- Insiders % is NOT in 13F filings, and no free source supplies it per
  ticker (Yahoo quoteSummary and v7 quote both 401, Nasdaq holdings API
  404 — all re-verified Nov 16, 2026), so insiders render as "—" and the
  public figure is the remainder, labelled as including insiders.

EDGAR limits: max 10 requests/second; this module stays under 8/s and
uses the same User-Agent as lib/edgar.py.
"""

import gzip
import http.client
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import lib.edgar as edgar

UA = {
    "User-Agent": "NorthstarScreener research contact kishore.svjr@gmail.com",
    "Accept-Encoding": "gzip",
}
EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
# 13F-HR filings are due 45 days after the quarter ends. A quarter only
# counts as complete once that deadline is at least two weeks past, so
# late filers have landed (Berkshire filed its Q3 2026 13F two days late).
QUARTER_GRACE_DAYS = 14
# Filings for a quarter arrive over ~3 months after the quarter ends
# (deadline 45 days, stragglers after). The window is kept short enough
# that the efts hit total stays under its 10,000 cap (Q2 2026: 9,848
# 13F-HR + 406 amendments in Jul-Sep); a wider window would page past
# the cap and silently lose the oldest filings.
FILING_WINDOW_DAYS = 92
# efts caps its reported total at 10,000 hits; a query that reaches the
# cap is split in half and retried so no filing is lost to pagination.
EFTS_HIT_CAP = 10000
# Requests per second cap (EDGAR asks for 10; stay under it).
RATE_PER_SECOND = 8.0
MAX_WORKERS = 8

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Discretion codes counted in the legacy per-filing sums (SOLE + DFND).
# NOTE: these per-filing sums are NOT the headline figures — they
# double-count shared blocks. The headline figures come from the
# participant-set de-dup in aggregate() (see the module docstring):
# each shared block counts once, at the largest amount any participant
# reported. COUNTED_DISCRETION / shares_all below are kept only so the
# run can report how much the de-dup removed.
COUNTED_DISCRETION = ("SOLE", "DFND")

_rate_lock = threading.Lock()
_next_allowed = [0.0]


def _rate_wait():
    with _rate_lock:
        now = time.monotonic()
        wait = _next_allowed[0] - now
        if wait > 0:
            time.sleep(wait)
            now = time.monotonic()
        _next_allowed[0] = now + 1.0 / RATE_PER_SECOND


def _get(url, timeout=30, tries=3):
    """GET with the EDGAR user agent, gzip, retries on 429/5xx.

    Transport failures are retried too: EDGAR truncates responses
    mid-download (http.client.IncompleteRead — the Nov 22 top-holders
    run lost 869 of 8,898 filings to it, including every large manager
    table: BlackRock, all Vanguard entities, State Street) and drops
    connections (RemoteDisconnected). Both are http.client errors, not
    URLError, so they previously escaped unretried and the filing was
    lost on the first attempt.
    """
    last = None
    for attempt in range(tries):
        _rate_wait()
        request = urllib.request.Request(url, headers=UA)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except (urllib.error.URLError, TimeoutError,
                http.client.HTTPException, ConnectionError) as exc:
            last = exc
            if attempt < tries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    raise last


def _get_json(url, timeout=30):
    return json.loads(_get(url, timeout=timeout))


def latest_completed_quarter(today=None):
    """(quarter_end_date, label) for the latest 13F quarter whose filing
    deadline is at least QUARTER_GRACE_DAYS past.

    Quarters end Mar 31, Jun 30, Sep 30, Dec 31; filings are due 45 days
    later. E.g. on 2026-11-16 the Q3 deadline (Nov 14) is only 2 days
    past, so the latest complete quarter is Q2 2026.
    """
    today = today or date.today()
    year = today.year
    ends = [date(year, 12, 31), date(year, 9, 30), date(year, 6, 30),
            date(year, 3, 31), date(year - 1, 12, 31)]
    for end in ends:
        if today >= end + timedelta(days=45 + QUARTER_GRACE_DAYS):
            label = f"Q{(end.month - 1) // 3 + 1} {end.year}"
            return end, label
    return date(year - 1, 12, 31), f"Q4 {year - 1}"


def _efts_page(forms, start, end, offset):
    params = {
        "dateRange": "custom",
        "startdt": start.isoformat(),
        "enddt": end.isoformat(),
        "forms": forms,
        "from": offset,
        "size": 100,
    }
    url = EFTS_URL + "?" + urllib.parse.urlencode(params)
    return _get_json(url)


def _efts_query(forms, start, end, quarter_end):
    """One forms query over [start, end], paginated, filtered to the
    quarter's period_ending. If the hit total reaches the efts 10,000
    cap, the range is split in half and each half is queried, so no
    filing is lost to pagination. Returns {adsh: filing}."""
    by_adsh = {}
    offset = 0
    total = None
    while True:
        data = _efts_page(forms, start, end, offset)
        hits = data.get("hits", {}).get("hits", [])
        if total is None:
            total = data.get("hits", {}).get("total", {}).get("value", 0)
            if total >= EFTS_HIT_CAP and start < end:
                mid = start + (end - start) // 2
                left = _efts_query(forms, start, mid, quarter_end)
                right = _efts_query(forms, mid + timedelta(days=1), end, quarter_end)
                left.update(right)
                return left
        for hit in hits:
            src = hit.get("_source", {})
            if src.get("period_ending") != quarter_end.isoformat():
                continue
            adsh = src.get("adsh")
            ciks = src.get("ciks") or []
            if not adsh or not ciks:
                continue
            by_adsh[adsh] = {
                "cik": ciks[0].lstrip("0") or "0",
                "adsh": adsh,
                "file_date": src.get("file_date", ""),
                "form": src.get("form", forms),
                # The 13F file number ("028-27006") is the stable
                # per-manager identifier: a filing's other-managers
                # list names managers by this number, so it is how a
                # DFND/SHRD row's otherManager reference is resolved
                # to the other manager's filing (see _resolve_other_refs).
                "file_num": (src.get("file_num") or [None])[0],
                "display_name": (src.get("display_names") or [None])[0],
            }
        offset += len(hits)
        if not hits or offset >= total:
            break
    return by_adsh


def enumerate_filings(quarter_end):
    """All 13F-HR / 13F-HR-A filings for one quarter.

    Returns a list of {cik, adsh, file_date, form}, one per manager: the
    filing with the latest file_date wins per CIK (an amendment replaces
    the original). Filings are found by filing date (the quarter's
    reports arrive over ~3 months) and filtered to the quarter's
    period_ending.
    """
    start = quarter_end + timedelta(days=1)
    end = quarter_end + timedelta(days=FILING_WINDOW_DAYS)
    by_adsh = {}
    for forms in ("13F-HR", "13F-HR/A"):
        by_adsh.update(_efts_query(forms, start, end, quarter_end))
    # One filing per manager: latest file_date wins (amendment over
    # original); ties break on the later accession.
    best = {}
    for filing in by_adsh.values():
        key = filing["cik"]
        current = best.get(key)
        if (current is None
                or (filing["file_date"], filing["adsh"]) > (current["file_date"], current["adsh"])):
            best[key] = filing
    return sorted(best.values(), key=lambda f: f["file_date"])


def _index_items(cik, adsh):
    """The filing's directory listing (index.json), fetched once per
    filing — both the information-table URL and the primary-document
    URL are derived from it."""
    adsh_nodash = adsh.replace("-", "")
    index = _get_json(f"{ARCHIVES}/{cik}/{adsh_nodash}/index.json")
    return index.get("directory", {}).get("item", [])


def _infotable_url_from_items(cik, adsh, items):
    """The information-table document URL, from a filing index.

    The table's file name varies (infotable.xml, informationtable.xml, or
    a bare number like 56757.xml), so the filing index decides: prefer a
    name containing "info", else the largest .xml that is not the cover
    document (primary_doc.xml).
    """
    adsh_nodash = adsh.replace("-", "")
    xmls = [it for it in items if it.get("name", "").lower().endswith(".xml")]
    if not xmls:
        return None
    info = [it for it in xmls if "info" in it["name"].lower()]
    if info:
        chosen = info[0]
    else:
        rest = [it for it in xmls if it["name"] != "primary_doc.xml"]
        chosen = max(rest or xmls, key=lambda it: it.get("size", 0))
    return f"{ARCHIVES}/{cik}/{adsh_nodash}/{chosen['name']}"


def _infotable_url(cik, adsh):
    return _infotable_url_from_items(cik, adsh, _index_items(cik, adsh))


def _primary_doc_url_from_items(cik, adsh, items):
    """The cover document (primary_doc.xml) URL, from a filing index.
    Returns None when the filing has no XML cover (then its
    otherManager references cannot be resolved and its shared rows
    count as-is)."""
    adsh_nodash = adsh.replace("-", "")
    for it in items:
        if it.get("name") == "primary_doc.xml":
            return f"{ARCHIVES}/{cik}/{adsh_nodash}/primary_doc.xml"
    return None


def _norm_file_num(num):
    """Normalize a 13F file number so spellings agree: "028-04545" and
    "28-4545" are the same manager. Returns None for a blank value."""
    if not num:
        return None
    parts = str(num).strip().split("-")
    try:
        return "-".join(str(int(p)) for p in parts)
    except ValueError:
        return str(num).strip()


_FILER_NS = "{http://www.sec.gov/edgar/thirteenffiler}"


def _parse_primary_doc(xml_bytes):
    """Parse a 13F-HR cover document (primary_doc.xml).

    Returns {"file_num": the filer's own normalized 13F file number,
    "managers": {sequence_number: {"name":, "file_num":}}} — the
    other-managers list the info table's otherManager field points
    into. Returns None when the document is not a parseable 13F cover.
    Element lookup tolerates a missing or different namespace, since
    older schema versions vary.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    def _find_all(elem, tag):
        found = elem.findall(f".//{_FILER_NS}{tag}")
        if found:
            return found
        return [e for e in elem.iter() if e.tag.split("}")[-1] == tag]

    def _find_text(elem, tag):
        found = _find_all(elem, tag)
        return (found[0].text or "").strip() if found else ""

    managers = {}
    for om2 in _find_all(root, "otherManager2"):
        try:
            seq = int(_find_text(om2, "sequenceNumber"))
        except ValueError:
            continue
        oms = _find_all(om2, "otherManager")
        if not oms:
            continue
        managers[seq] = {
            "name": _find_text(oms[0], "name"),
            "file_num": _norm_file_num(_find_text(oms[0], "form13FFileNumber")),
        }
    return {"file_num": _norm_file_num(_find_text(root, "form13FFileNumber")),
            "managers": managers}


def _build_resolution(filings):
    """Identity maps for resolving otherManager references, built from
    the enumeration alone (no extra fetches):
    - file_num_map: normalized 13F file number -> CIK (exact; a manager
      keeps one file number across quarters and amendments).
    - name_map: normalized display name -> CIK, only for names that map
      to exactly one CIK (collisions are dropped, never guessed).
    Returns (file_num_map, name_map, collisions)."""
    file_num_map, name_map, collisions = {}, {}, 0
    by_name = {}
    for filing in filings:
        cik = filing["cik"]
        fnum = _norm_file_num(filing.get("file_num"))
        if fnum:
            if fnum in file_num_map and file_num_map[fnum] != cik:
                collisions += 1
            else:
                file_num_map[fnum] = cik
        display = filing.get("display_name") or ""
        # efts appends " (CIK 0001234567)" to the name; strip it.
        display = re.sub(r"\s*\(CIK[^)]*\)\s*$", "", display).strip()
        if display:
            by_name.setdefault(_normalize_name(display), set()).add(cik)
    for norm, ciks in by_name.items():
        if len(ciks) == 1:
            name_map[norm] = next(iter(ciks))
        else:
            collisions += 1
    return file_num_map, name_map, collisions


def _resolve_other_refs(ref_text, primary, file_num_map, name_map):
    """Resolve an info-table otherManager field to participant keys.

    The field is usually a comma-separated list of sequence numbers
    into the filing's own other-managers list ("4,11"), resolved
    through that list's 13F file number (exact) or name (unique match
    only). Rarely a filer writes a bare CIK or file number instead;
    those resolve directly. Returns one key per reference: a CIK
    (digits, no leading zeros) when the manager is identified, else
    "REF:<raw>" — kept distinct per filing, so an unresolvable
    reference can never pair across filings and its row counts as-is.
    Unresolvable managers are usually non-filing affiliates, which is
    exactly the case where the row is the only report of its block.
    """
    refs = [r.strip() for r in (ref_text or "").split(",") if r.strip()]
    out = []
    for ref in refs:
        cik = None
        if "-" in ref:
            fnum = _norm_file_num(ref)
            if fnum:
                cik = file_num_map.get(fnum)
        elif ref.isdigit():
            mgr = None
            if primary:
                try:
                    mgr = primary["managers"].get(int(ref))
                except ValueError:
                    mgr = None
            if mgr:
                if mgr.get("file_num"):
                    cik = file_num_map.get(mgr["file_num"])
                if not cik and mgr.get("name"):
                    cik = name_map.get(_normalize_name(mgr["name"]))
            if not cik and len(ref) >= 4:
                # Not a sequence number in this filing's list: a bare
                # CIK written without leading zeros.
                cik = ref.lstrip("0") or "0"
        out.append(cik if cik else f"REF:{ref}")
    return out


def parse_infotable(xml_bytes):
    """Parse one information table.

    Returns (counted, sole, all_disc, names, shared):
    - counted: {cusip: shares} under SOLE+DFND (legacy per-filing sums;
      double-counts shared blocks — kept only for the de-dup report).
    - sole: {cusip: shares} under SOLE only.
    - all_disc: {cusip: shares} under any discretion (legacy sums).
    - names: {cusip: (issuer_name, title_of_class)}.
    - shared: [{cusip, shares, disc, refs}] for DFND/SHRD rows, where
      refs is the raw otherManager field (sequence numbers into the
      filing's other-managers list, or None) — the input to the
      participant-set de-dup in aggregate().
    Only SH rows with no put/call count — option rows report the shares
    underlying the option, not shares held.
    """
    import io
    ns = "{http://www.sec.gov/edgar/document/thirteenf/informationtable}"
    counted, sole, all_disc, names, shared = {}, {}, {}, {}, []
    try:
        context = ET.iterparse(io.BytesIO(xml_bytes), events=("end",))
        for _, elem in context:
            if elem.tag != ns + "infoTable":
                continue
            cusip = (elem.findtext(ns + "cusip") or "").strip().upper()
            amt = elem.find(ns + "shrsOrPrnAmt")
            shares = None
            if amt is not None:
                if (amt.findtext(ns + "sshPrnamtType") or "").strip() == "SH":
                    try:
                        shares = int((amt.findtext(ns + "sshPrnamt") or "").replace(",", ""))
                    except ValueError:
                        shares = None
            if cusip and shares:
                if elem.findtext(ns + "putCall") is None:
                    disc = (elem.findtext(ns + "investmentDiscretion") or "").strip().upper()
                    all_disc[cusip] = all_disc.get(cusip, 0) + shares
                    if disc == "SOLE":
                        sole[cusip] = sole.get(cusip, 0) + shares
                    if disc in COUNTED_DISCRETION:
                        counted[cusip] = counted.get(cusip, 0) + shares
                    if disc in ("DFND", "SHRD"):
                        refs = (elem.findtext(ns + "otherManager") or "").strip()
                        shared.append({"cusip": cusip, "shares": shares,
                                       "disc": disc, "refs": refs or None})
                name = (elem.findtext(ns + "nameOfIssuer") or "").strip()
                cls = (elem.findtext(ns + "titleOfClass") or "").strip()
                if cusip not in names and name:
                    names[cusip] = (name, cls)
            elem.clear()
    except ET.ParseError:
        return counted, sole, all_disc, names, shared
    return counted, sole, all_disc, names, shared


def _fetch_filing(filing, resolution=None):
    """Download + parse one filing's information table.

    Returns (adsh, counted, sole, all_disc, names, groups, diag, error)
    where groups maps (cusip, participants_tuple) -> (dfnd_shares,
    all_shares) for this filing's DFND/SHRD rows, and participants_tuple
    is the sorted tuple of participant keys for that block — the
    reporter CIK plus the resolved other-manager CIKs (or "REF:<raw>"
    when a reference cannot be resolved). Rows naming the same
    participant set are one block of shares, so they are summed here
    and counted once, at the group level, in aggregate(). diag carries
    de-dup diagnostics (resolved/unresolved reference counts, whether
    the cover document was readable, multi-named rows).
    The cover document is fetched only when the filing actually has
    DFND/SHRD rows with references — all-SOLE filings need no third
    request.
    """
    file_num_map, name_map = resolution or ({}, {})
    reporter = filing["cik"]
    diag = {"shared_rows": 0, "unresolved": 0, "multi_named": 0,
            "primary_missing": 0}
    try:
        items = _index_items(filing["cik"], filing["adsh"])
        url = _infotable_url_from_items(filing["cik"], filing["adsh"], items)
        if not url:
            return filing["adsh"], {}, {}, {}, {}, {}, diag, "no information table in index"
        xml_bytes = _get(url, timeout=60)
        counted, sole, all_disc, names, shared = parse_infotable(xml_bytes)
        groups = {}
        if shared:
            diag["shared_rows"] = len(shared)
            primary = None
            primary_url = _primary_doc_url_from_items(filing["cik"], filing["adsh"], items)
            if primary_url:
                try:
                    primary = _parse_primary_doc(_get(primary_url, timeout=30))
                except Exception:  # noqa: BLE001 — an unreadable cover only loses pairing
                    primary = None
            if primary is None:
                diag["primary_missing"] = 1
            for row in shared:
                refs = row["refs"]
                others = []
                if refs:
                    for ref in [r.strip() for r in refs.split(",") if r.strip()]:
                        others.extend(_resolve_other_refs(ref, primary, file_num_map, name_map))
                    if len([r for r in refs.split(",") if r.strip()]) > 1:
                        diag["multi_named"] += 1
                # Count resolution outcomes from the keys themselves:
                # a CIK key resolved, a REF: key did not.
                for key in others:
                    if key.startswith("REF:"):
                        diag["unresolved"] += 1
                participants = tuple(sorted({reporter, *others}))
                dfnd, allsh = groups.get((row["cusip"], participants), (0, 0))
                if row["disc"] == "DFND":
                    dfnd += row["shares"]
                groups[(row["cusip"], participants)] = (dfnd, allsh + row["shares"])
        return filing["adsh"], counted, sole, all_disc, names, groups, diag, None
    except Exception as exc:  # noqa: BLE001 — one bad filing must not stop the run
        return filing["adsh"], {}, {}, {}, {}, {}, diag, str(exc)


def _groups_to_json(groups):
    """Serialize participant-set groups for the checkpoint: the key is
    cusip + unit-separator + participants, the value maps each
    reporting manager to its [dfnd_shares, all_shares] for the group."""
    out = {}
    for (cusip, participants), per_reporter in groups.items():
        key = "\x1f".join([cusip, *participants])
        out[key] = {reporter: list(amounts) for reporter, amounts in per_reporter.items()}
    return out


def _groups_from_json(data):
    groups = {}
    for key, per_reporter in (data or {}).items():
        parts = key.split("\x1f")
        groups[(parts[0], tuple(parts[1:]))] = {
            reporter: tuple(amounts) for reporter, amounts in per_reporter.items()}
    return groups


def _finalize_dedup(totals, groups):
    """Apply the participant-set de-dup to per-CUSIP totals.

    For each (cusip, participant set) group, the block counts once, at
    the largest amount any participant reported for it — separately for
    the DFND slice (headline SOLE+DFND) and the all-discretion slice
    (headline ALL). SOLE rows were never shared, so they add in full.
    Returns (dfnd_sums, all_sums) per CUSIP, plus group diagnostics.
    """
    dfnd_sums, all_sums = {}, {}
    multi_reporter = 0
    for (_cusip, _participants), per_reporter in groups.items():
        if len(per_reporter) > 1:
            multi_reporter += 1
    for (cusip, _participants), per_reporter in groups.items():
        dfnd_sums[cusip] = dfnd_sums.get(cusip, 0) + max(v[0] for v in per_reporter.values())
        all_sums[cusip] = all_sums.get(cusip, 0) + max(v[1] for v in per_reporter.values())
    return dfnd_sums, all_sums, {"groups": len(groups), "multi_reporter_groups": multi_reporter}


def aggregate(quarter_end, log=print, checkpoint_path=None, batch_size=500):
    """Aggregate one quarter's 13F holdings by CUSIP.

    Returns (totals, stats) where totals maps CUSIP to
    {shares (SOLE+DFND, DE-DUPLICATED — each shared block counted once),
    shares_sole (SOLE only), shares_all (any discretion, DE-DUPLICATED),
    filers, name, class} and stats records the enumeration/download
    counts, failures, and de-dup diagnostics.

    checkpoint_path: a JSON file outside the repo where progress is saved
    after every batch (the filing list, the per-CUSIP totals so far, the
    participant-set groups, and the accessions already parsed). A run
    interrupted by a VM restart resumes from the checkpoint instead of
    starting over; only the current batch (at most batch_size filings)
    is lost. NOTE: a checkpoint from the pre-de-dup build cannot be
    reused — its totals hold double-counted sums and it has no groups —
    so the de-dup run uses a fresh checkpoint path.
    """
    filings = None
    totals = {}
    groups = {}
    diag = {"shared_rows": 0, "unresolved": 0, "multi_named": 0, "primary_missing": 0}
    done = set()
    failed = []
    rows = 0

    def _write_checkpoint(path, filings, totals, groups, diag, done, failed, rows):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"filings": filings, "totals": totals,
                       "groups": _groups_to_json(groups), "diag": diag,
                       "done_adsh": sorted(done), "failed": failed,
                       "rows_counted": rows}, fh)
        os.replace(tmp, path)

    if checkpoint_path and os.path.exists(checkpoint_path):
        try:
            with open(checkpoint_path, encoding="utf-8") as fh:
                ck = json.load(fh)
            filings = ck.get("filings")
            totals = ck.get("totals", {})
            groups = _groups_from_json(ck.get("groups"))
            diag = ck.get("diag", diag)
            done = set(ck.get("done_adsh", []))
            failed = ck.get("failed", [])
            rows = ck.get("rows_counted", 0)
            log(f"13F: resumed from checkpoint ({len(done)}/{len(filings or [])} filings done)")
        except (OSError, ValueError):
            filings = None
    if filings is None:
        filings = enumerate_filings(quarter_end)
        log(f"13F {quarter_end.isoformat()}: {len(filings)} manager filings (latest per CIK)")
        if checkpoint_path:
            _write_checkpoint(checkpoint_path, filings, totals, groups, diag, done, failed, rows)

    file_num_map, name_map, collisions = _build_resolution(filings)
    log(f"13F: resolution maps — {len(file_num_map)} file numbers, "
        f"{len(name_map)} names, {collisions} collisions dropped")
    resolution = (file_num_map, name_map)

    pending = [f for f in filings if f["adsh"] not in done]
    log(f"13F: {len(pending)} filings left to parse")
    for batch_start in range(0, len(pending), batch_size):
        batch = pending[batch_start:batch_start + batch_size]
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(_fetch_filing, f, resolution): f for f in batch}
            for future in as_completed(futures):
                filing = futures[future]
                adsh, counted, sole, all_disc, names, fgroups, fdiag, error = future.result()
                if error:
                    failed.append((adsh, error))
                    continue
                done.add(adsh)
                for key, value in fdiag.items():
                    diag[key] = diag.get(key, 0) + value
                for cusip, shares in counted.items():
                    entry = totals.setdefault(cusip, {"shares": 0, "shares_sole": 0, "shares_all": 0, "filers": 0, "name": None, "class": None})
                    entry["shares"] += shares
                    entry["filers"] += 1
                for cusip, shares in sole.items():
                    entry = totals.setdefault(cusip, {"shares": 0, "shares_sole": 0, "shares_all": 0, "filers": 0, "name": None, "class": None})
                    entry["shares_sole"] += shares
                for cusip, shares in all_disc.items():
                    entry = totals.setdefault(cusip, {"shares": 0, "shares_sole": 0, "shares_all": 0, "filers": 0, "name": None, "class": None})
                    entry["shares_all"] += shares
                for cusip, (name, cls) in names.items():
                    entry = totals.setdefault(cusip, {"shares": 0, "shares_sole": 0, "shares_all": 0, "filers": 0, "name": None, "class": None})
                    if entry["name"] is None:
                        entry["name"] = name
                        entry["class"] = cls
                    # Keep the distinct (name, class) spellings managers
                    # use for this CUSIP (up to 4). The single recorded
                    # name is first-filer-wins and therefore
                    # order-dependent — a truncated spelling ("INTL
                    # BUSINESS MACHS", "ILLINOIS TOOL WKS") can make
                    # the real CUSIP unmatchable while a stub matches.
                    # build_cusip_map matches against ALL variants, so
                    # the mapping no longer depends on which filing
                    # happened to finish first.
                    variants = entry.setdefault("variants", [])
                    pair = [name, cls]
                    if pair not in variants and len(variants) < 4:
                        variants.append(pair)
                for (cusip, participants), (dfnd, allsh) in fgroups.items():
                    slot = groups.setdefault((cusip, participants), {})
                    prev = slot.get(filing["cik"], (0, 0))
                    slot[filing["cik"]] = (prev[0] + dfnd, prev[1] + allsh)
                rows += len(counted)
        if checkpoint_path:
            _write_checkpoint(checkpoint_path, filings, totals, groups, diag, done, failed, rows)
        log(f"  ... {min(batch_start + batch_size, len(pending))}/{len(pending)} filings parsed "
            f"({len(done)}/{len(filings)} total, {len(totals)} CUSIPs, {len(groups)} groups)")
    # De-dup finalize: totals["shares"] / ["shares_all"] currently hold
    # the legacy double-counted sums (kept so the run can report how
    # much the de-dup removed); overwrite them with the de-duplicated
    # figures before returning.
    old_shares = sum(t.get("shares", 0) for t in totals.values())
    old_all = sum(t.get("shares_all", 0) for t in totals.values())
    dfnd_sums, all_sums, gdiag = _finalize_dedup(totals, groups)
    for cusip, entry in totals.items():
        sole = entry.get("shares_sole", 0)
        entry["shares"] = sole + dfnd_sums.get(cusip, 0)
        entry["shares_all"] = sole + all_sums.get(cusip, 0)
    new_shares = sum(t.get("shares", 0) for t in totals.values())
    new_all = sum(t.get("shares_all", 0) for t in totals.values())
    stats = {
        "quarter_end": quarter_end.isoformat(),
        "filings": len(filings),
        "failed": len(failed),
        "failed_sample": failed[:20],
        "cusips": len(totals),
        "rows_counted": rows,
        "dedup": {
            "groups": gdiag["groups"],
            "multi_reporter_groups": gdiag["multi_reporter_groups"],
            "old_shares_sole_dfnd": old_shares,
            "new_shares_sole_dfnd": new_shares,
            "old_shares_all": old_all,
            "new_shares_all": new_all,
            "removed_shares_all": old_all - new_all,
            "removed_pct_all": (old_all - new_all) / old_all if old_all else 0,
            "shared_rows": diag.get("shared_rows", 0),
            "unresolved_refs": diag.get("unresolved", 0),
            "multi_named_rows": diag.get("multi_named", 0),
            "primary_missing": diag.get("primary_missing", 0),
            "resolution_collisions": collisions,
        },
    }
    log(f"13F {quarter_end.isoformat()}: {len(totals)} CUSIPs, {len(failed)} failed filings, "
        f"de-dup removed {old_all - new_all:,} shares "
        f"({(old_all - new_all) / old_all:.1%} of the legacy all-discretion total)")
    return totals, stats


def shares_outstanding_asof(symbol, quarter_end):
    """Shares outstanding as of a quarter end, from EDGAR cover pages.

    The latest dei count dated within 90 days after the quarter end (a
    10-Q cover filed just after the quarter is the quarter-end count),
    and no more than two years before it — the same recency rule
    lib/edgar._latest_shares applies, because a cover-page count years
    out of date mixed with a current quarter's holdings produces a
    nonsense percentage (Berkshire's dei count stops in 2011, Fox's is
    a single 2019 point of 1 share, News Corp has none at all). If no
    qualifying cover-page count exists, fall back to
    edgar._latest_shares — the current count the project's market cap
    uses (dei if current, else the weighted-average shares from the
    latest 10-K) — with no as-of date attached. Returns
    (shares, end_date); (None, None) when neither source has a current
    count, and the ticker renders as a dash.
    """
    if symbol in SHARES_OUTSTANDING_OVERRIDES:
        return SHARES_OUTSTANDING_OVERRIDES[symbol]
    facts = edgar.facts(symbol)
    points = edgar._shares_points(facts)
    cutoff = quarter_end + timedelta(days=90)
    floor = quarter_end - timedelta(days=730)
    current = [p for p in points
               if p["val"] and p["val"] > 0
               and floor <= date.fromisoformat(p["end"][:10]) <= cutoff]
    if current:
        best = max(current, key=lambda p: p["end"])
        return best["val"], best["end"][:10]
    shares = edgar._latest_shares(facts)
    return shares, None


# 13F issuer names are written by thousands of different managers, so
# they arrive abbreviated ("AMERICAN ELEC PWR"), truncated
# ("AUTOMATIC DATA PRO"), word-swapped ("GALLAGHER ARTHUR J & CO") and
# with the share class attached ("WALMART INC COM", "COINBASE GLOBAL INC
# CLASS A"). Normalization expands the abbreviations, drops legal
# suffixes and connectors, and strips a trailing class designator, so
# variants of one issuer collapse to the same key.
_ABBREVIATIONS = {
    "ELEC": "ELECTRIC", "PWR": "POWER", "PRODS": "PRODUCTS",
    "CHEMS": "CHEMICALS", "CHEM": "CHEMICAL", "INTL": "INTERNATIONAL",
    "SVCS": "SERVICES", "SYS": "SYSTEMS", "TECH": "TECHNOLOGY",
    "LABS": "LABORATORIES", "MFG": "MANUFACTURING", "GEN": "GENERAL",
    "NATL": "NATIONAL", "FINL": "FINANCIAL",
    "INV": "INVESTMENT", "CAP": "CAPITAL", "INDS": "INDUSTRIES",
    "IND": "INDUSTRIES", "COS": "COMPANIES", "HLDG": "HOLDING",
    "HLDGS": "HOLDINGS", "CRP": "CORP", "BROS": "BROTHERS",
    "PHARM": "PHARMACEUTICAL", "MTLS": "MATERIALS",
    "EQUIP": "EQUIPMENT", "RES": "RESOURCES", "COMMS": "COMMUNICATIONS",
    "SCI": "SCIENTIFIC", "ENGR": "ENGINEERING", "STK": "STOCK",
    "PPTY": "PROPERTY", "RLTY": "REALTY", "TR": "TRUST", "BK": "BANK",
    "MGMT": "MANAGEMENT", "FGHT": "FREIGHT", "INVT": "INVESTMENT",
    "INVS": "INVESTMENT", "TRST": "TRUST", "MKTS": "MARKETS",
    "AIRLS": "AIRLINES", "SVC": "SERVICE", "INSTRS": "INSTRUMENTS",
    "INSTR": "INSTRUMENT", "HLTH": "HEALTH", "SOUTHN": "SOUTHERN",
    "SVSC": "SERVICES",
    # Manager truncations seen in 13F names (Q2 2026): "INTERNATIONAL
    # BUSINESS MACHS" for IBM, "ILLINOIS TOOL WKS" for ITW.
    "MACHS": "MACHINES", "WKS": "WORKS",
    # Abbreviations that hid real CUSIPs from the name matcher (Q2 2026
    # audit): "FORD MTR CO" for Ford, "JOHNSON CTLS INTL" for Johnson
    # Controls, "LIVE NATION ENTMT" for Live Nation, "APPLIED MATLS"
    # for Applied Materials, "MARTIN MARIETTA MATLS", "FIDELITY NATL
    # INFORMATION SV" for FIS. Without these the matcher fell back to
    # near-zero stub CUSIPs (Ford showed 0.0003% institutional).
    "MTR": "MOTOR", "CTLS": "CONTROLS", "ENTMT": "ENTERTAINMENT",
    "MATLS": "MATERIALS", "SV": "SERVICES",
}
_DROPPED_WORDS = {
    "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "LTD", "LIMITED",
    "LLC", "PLC", "LP", "LLP", "COMPANY", "COMPANIES", "GROUP", "HOLDINGS",
    "HOLDING", "DELAWARE", "THE", "AND", "OF", "COMMON", "TRUST",
    # Filler words in REIT share descriptions ("EQUITY RESIDENTIAL SH
    # BEN INT" is the shares of beneficial interest, not a different
    # company from "EQUITY RESIDENTIAL").
    "SH", "BEN", "INT",
    # Foreign legal suffixes.
    "NV", "SA", "AG", "SE", "AB", "BV", "KK", "ASA", "AS", "OYJ", "SPA",
    "SL", "SAS", "GMBH",
}
_TRAILING_CLASS = re.compile(
    r"\b(COM NEW|COM|NEW|STOCK|SHS|ORD SHS|ORD|CL [ABC]|CLASS [ABC]|ADR|SPONSORED ADR|ADS|SPONSORED ADS|[ABC])$")


def _normalize_name(name):
    """Company names, normalized for matching 13F issuer names to the
    universe: upper case, no punctuation, abbreviations expanded, legal
    suffixes and connectors dropped, and a trailing share-class
    designator stripped ("WALMART INC COM", "ALPHABET INC CL A") so
    every class of one issuer collapses to the same key — the class is
    resolved separately, via CLASS_TICKERS or the common-class rule in
    build_cusip_map."""
    # Strip accents first ("Estée" -> "Estee") so accented universe names
    # match the plain-ASCII names managers write, then drop apostrophes
    # and periods without spacing ("Lowe's" -> "LOWES", "J.M." -> "JM").
    # Dashes are spaces, not nothing: the universe writes "Brown–Forman"
    # with an en dash, and dropping it ("BROWNFORMAN") broke both the
    # exact match and the other-issuer veto for BRO/BF-B.
    import unicodedata
    name = name.replace("–", " ").replace("—", " ").replace("‐", " ")
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    text = text.upper().replace("'", "").replace(".", "")
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    tokens = [_ABBREVIATIONS.get(tok, tok) for tok in text.split()]
    tokens = [tok for tok in tokens if tok not in _DROPPED_WORDS]
    # Join runs of single-letter tokens ("W. W. Grainger" -> "WW GRAINGER",
    # "M & T Bank" -> "MT BANK", "J.M. Smucker" -> "JM SMUCKER") so
    # initials match whether the filer wrote them spaced, dotted or joined.
    joined, buf = [], ""
    for tok in tokens:
        if len(tok) == 1:
            buf += tok
        else:
            if buf:
                joined.append(buf)
                buf = ""
            joined.append(tok)
    if buf:
        joined.append(buf)
    text = " ".join(joined)
    # Strip trailing class designators repeatedly ("CL A COM STK" ->
    # "CL A COM" -> "CL A" -> "").
    while True:
        stripped = _TRAILING_CLASS.sub("", text).strip()
        if stripped == text:
            break
        text = re.sub(r"\s+", " ", stripped).strip()
    return text


def _tokens_match(tokens_u, tokens_t):
    """Order-insensitive token-set match: same size, each token exact or
    a >=3-char prefix of its counterpart (catches manager truncations
    like "AUTOMATIC DATA PRO" for Automatic Data Processing)."""
    if len(tokens_u) != len(tokens_t):
        return False
    remaining = list(tokens_t)
    for u in sorted(tokens_u):
        hit = None
        for i, t in enumerate(remaining):
            if t == u:
                hit = i
                break
        if hit is None:
            for i, t in enumerate(remaining):
                if (len(u) >= 3 and t.startswith(u)) or (len(t) >= 3 and u.startswith(t)):
                    hit = i
                    break
        if hit is None:
            return False
        remaining.pop(hit)
    return True


# Share-class tickers whose issuer name maps to several CUSIPs: the
# ticker's class letter picks the 13F titleOfClass ("COM CL A" etc.).
CLASS_TICKERS = {
    "GOOGL": "A", "GOOG": "C",
    "BRK-B": "B", "BF-B": "B",
    "FOXA": "A", "FOX": "B",
    "NWSA": "A", "NWS": "B",
    "DISCA": "A", "DISCK": "C",
    "LBRDA": "A", "LBRDK": "C",
    "LSXMA": "A", "LSXMK": "C",
    "FWONA": "A", "FWONK": "C",
}


# Title-of-class values that are NOT plain common stock. 13F tables list
# an issuer's bonds, notes, options and ETFs under the same issuer name,
# so a name match alone is not enough: the common-stock CUSIP is the one
# whose class is plain equity, and among several such CUSIPs (stale
# zero-share entries are common) the one with the most reported shares.
# REIT is equity here: managers label a REIT's own common stock "REIT"
# (Equinix, Realty Income); a REIT's bonds/notes still carry BOND/NOTE
# and its preferreds PFD, so they stay excluded.
_NON_EQUITY_CLASS_WORDS = (
    "PUT", "CALL", "OPTION", "BOND", "NOTE", "DEBENTURE", "DEB ",
    "PREF", "PFD", "ETF", "WARRANT", "RIGHT", "UNIT", "MUNI",
    "CEF", "FUND", "%", "DEP SHS",
)
_EQUITY_CLASS_WORDS = ("COM", "STOCK", "SHS", "ORD", "COMMON", "ADR",
                       "ADS", "SHARES", "EQUITY", "EQUITIES", "DEPOSITARY",
                       "REIT", "STK", "STOK")
_EQUITY_CLASS_RE = re.compile(
    r"\b(" + "|".join(_EQUITY_CLASS_WORDS) + r")\b")
_BARE_CLASS = re.compile(r"^(CL|CLASS)\s*[ABC]$")


def _is_common_class(cls):
    text = (cls or "").upper().strip()
    if any(word in text for word in _NON_EQUITY_CLASS_WORDS):
        return False
    if _BARE_CLASS.match(text):
        return True
    # Word-boundary match: a substring test would call "FIXED INCOME"
    # common stock ("INCOME" contains "COM").
    return bool(_EQUITY_CLASS_RE.search(text))


# Universe names that are short forms of the legal name the 13F filers
# write (verified against the Q2 2026 totals: share counts and filer
# counts confirm these are the right CUSIPs). Keys and values are
# NORMALIZED names (post-_normalize_name form).
NAME_ALIASES = {
    "IBM": "INTERNATIONAL BUSINESS MACHINES",
    "BXP": "BOSTON PROPERTIES",
    "DECKERS BRANDS": "DECKERS OUTDOOR",
    "SCHLUMBERGER": "SLB",
    "SUPERMICRO": "SUPER MICRO COMPUTER",
    "HONEYWELL TECHNOLOGIES": "HONEYWELL INTERNATIONAL",
    "UNIVERSAL HEALTH SERVICES": "UNIVERSAL HEALTH",
    # Renames the matcher cannot bridge (Q2 2026 audit): MicroStrategy
    # became Strategy in 2025 (filers write "STRATEGY INC"); BNY Mellon
    # files as "BANK NEW YORK MELLON CORP"; Healthpeak was formerly
    # Health Care Property Investors ("HEALTH CARE PPTY INVS INC");
    # Vivmark Residential was formerly Equity Residential.
    "MICROSTRATEGY": "STRATEGY",
    "BNY MELLON": "BANK NEW YORK MELLON",
    "HEALTHPEAK PROPERTIES": "HEALTH CARE PROPERTY INVESTMENT",
    "VIVMARK RESIDENTIAL": "EQUITY RESIDENTIAL",
}

# Tickers whose common stock is reported under several CUSIPs in 13F
# filings (old/new CUSIPs after a spinoff or reorganization): the
# holdings are summed across the group instead of picking one CUSIP.
# HON, Q2 2026: the Aerospace spinoff was already complete by Jun 30,
# 2026 — the 10-Q cover count halved to 316,940,010 (from 633,653,119
# on Mar 31) and 43849R105 is the separate Honeywell Aerospace Inc.
# (HONA, not in the universe), so it must NOT be summed into HON.
# 438516205 (259.4M shares) is the new Honeywell Automation common and
# 438516106 (2.6M) is the residual old CUSIP; together 262.0M /
# 316.9M = ~82.6% institutional. (An earlier version of this group
# wrongly included HONA and produced 160%.)
CUSIP_GROUPS = {
    "HON": ["438516205", "438516106"],
}

# Tickers the name matcher gets wrong, pinned to the verified CUSIP:
# MSCI matched the iShares Core MSCI Europe ETF (46434V738) — the
# subset stage lets the short name "MSCI" sit inside the ETF's name,
# and the ETF's 13F rows label its class "COM" so the class rule
# cannot catch it. EG matched Eve Holding (29970N104) — the
# prefix-fuzzy stage treats "EVE" as a prefix of "EVEREST".
# Verified: MSCI Inc is 55354G100 (66.9M shares), Everest Group Ltd
# is G3223R108 (38.7M shares).
CUSIP_OVERRIDES = {
    "MSCI": "55354G100",
    "EG": "G3223R108",
}

# Shares outstanding the EDGAR facts API cannot supply, pinned to the
# value read off the company's own filing (the facts API's dei count
# is absent or stale for these filers):
# CVNA — Carvana reports no dei cover-page count in the facts API and
# its weighted-average (137,634,000, FY2025 10-K) predates the 2026
# share-count jump. The Q2 2026 10-Q cover (filed Jul 29, 2026,
# accession 0001690820-26-000055) reports Class A 719,916,415 +
# Class B 380,547,355 = 1,100,463,770 total.
# Per-class cover counts (Q2 2026 audit): the facts API's
# dei:EntityCommonStockSharesOutstanding is the TOTAL across classes
# (Alphabet, Berkshire, Fox, News Corp) or absent/stale (Visa's stops
# in 2010, Berkshire's in 2011, Erie/Constellation/Tyson/Thomson
# Reuters have none), so dividing a single class's 13F shares by the
# total understates that class's ownership. Each value below was read
# off the company's own filing cover or balance sheet and verified
# against the filing text in Nov 2026:
# GOOGL/GOOG — Alphabet Q2 2026 10-Q balance sheet (filed Jul 23,
# 2026, accession 0001652044-26-000071): issued and outstanding at
# Jun 30, 2026, Class A 5,868,000,000, Class B 835,000,000,
# Class C 5,527,000,000 (total 12,230,000,000, matching dei).
# BRK-B — Berkshire Q2 2026 10-Q cover (filed Aug 10, 2026, accession
# 0001193125-26-341032): Class B 1,408,035,161 shares outstanding as
# of Jul 29, 2026 (Class A 488,450).
# BF-B — Brown-Forman Q1 FY2027 10-Q cover (filed Sep 2, 2026,
# accession 0000014693-26-000052): Class B 290,383,416 shares
# outstanding as of Aug 31, 2026 (Class A 168,480,849).
# FOXA/FOX — Fox Q1 FY2027 10-Q balance-sheet footnote (filed Nov 2,
# 2026, accession 0001628280-26-068670): Class A 199,338,182 and
# Class B 220,248,764 issued and outstanding at Jun 30, 2026.
# NWSA/NWS — News Corp Q1 FY2027 10-Q balance-sheet footnote (filed
# Nov 5, 2026, accession 0001564708-26-000250): Class A 362,139,890
# and Class B 181,281,012 issued and outstanding at Jun 30, 2026.
# V — Visa Q2 2026 10-Q cover (filed Jul 29, 2026, accession
# 0001403161-26-000104): Class A 1,704,112,694 shares outstanding as
# of Jul 21, 2026.
# ERIE — Erie Indemnity Q2 2026 10-Q cover and balance sheet (filed
# Jul 30, 2026, accession 0001628280-26-051079): Class A 46,189,068
# shares outstanding as of Jul 24, 2026.
# STZ — Constellation Brands Q2 FY2027 10-Q balance sheet (filed
# Oct 7, 2026, accession 0000016918-26-000040): Class A issued
# 212,699,732 less treasury 42,893,874 = 169,805,858 outstanding at
# Aug 31, 2026 (cover count Sep 30, 2026 is 169,198,487 after further
# buybacks; the Aug 31 count is closer to the quarter end).
# TSN — Tyson Q2 2026 10-Q cover (filed Aug 3, 2026, accession
# 0000100493-26-000058): Class A 281,792,507 shares outstanding as of
# Jun 27, 2026 (Class B 70,009,005).
# TRI — Thomson Reuters files no dei share count (foreign filer, IFRS).
# Q2 2026 6-K XBRL (filed Aug 6, 2026, accession 0001193125-26-338256)
# reports H1 2026 weighted-average basic shares 438,384,963; no
# point-in-time count is stated, so this weighted average is the
# closest verified Q2 figure. Cross-check: independent 13F trackers
# report ~404.8M shares / 92% for Q2 2026, consistent with
# 402,530,885 / 438,384,963 = 91.82%.
# DLR — the facts API's latest dei point is Apr 29, 2026 (351,406,070),
# but Digital Realty issued ~18.6M shares in Q2 2026. The Q2 2026
# 10-Q cover (filed Jul 31, 2026, accession 0001104659-26-089296)
# reports 370,036,176 shares outstanding at Jul 29, 2026. With the
# April count the figure reads 100.83%; with the cover count it is
# 95.75% — a denominator correction, not a numerator problem.
# CNP — the facts API's latest dei point is Apr 15, 2026 (654,169,480).
# The Q2 2026 10-Q cover (filed Jul 2026) reports 658,720,288 shares
# outstanding as of Jul 22, 2026. The correction moves the figure
# from 105.32% to 104.59% — still over 100%, so the overage is
# genuine; only the denominator was stale.
SHARES_OUTSTANDING_OVERRIDES = {
    "CVNA": (1100463770, "2026-06-30"),
    "GOOGL": (5868000000, "2026-06-30"),
    "GOOG": (5527000000, "2026-06-30"),
    "BRK-B": (1408035161, "2026-07-29"),
    "BF-B": (290383416, "2026-08-31"),
    "FOXA": (199338182, "2026-06-30"),
    "FOX": (220248764, "2026-06-30"),
    "NWSA": (362139890, "2026-06-30"),
    "NWS": (181281012, "2026-06-30"),
    "V": (1704112694, "2026-07-21"),
    "ERIE": (46189068, "2026-07-24"),
    "STZ": (169805858, "2026-08-31"),
    "TSN": (281792507, "2026-06-27"),
    "TRI": (438384963, "2026-06-30"),
    "DLR": (370036176, "2026-07-29"),
    "CNP": (658720288, "2026-07-22"),
}


def _cusip_variants(entry):
    """All (name, class) spellings recorded for a CUSIP: the variants
    list when present (see aggregate()), else the single recorded pair.
    Matching uses every variant, so a truncated first-filer spelling
    cannot hide the real CUSIP behind a stub."""
    variants = (entry or {}).get("variants")
    if variants:
        return [(n, c) for n, c in variants if n]
    if (entry or {}).get("name"):
        return [(entry["name"], entry.get("class"))]
    return []


def _class_letter_match(symbol, totals, cusip):
    """Does any recorded variant of this CUSIP name the ticker's share
    class? The class letter lives in the titleOfClass ("COM CL A"), in
    the issuer name ("ALPHABET INC. CLASS A", "BERKSHIRE HATHAWAY INC
    DEL CL B NEW", "BROWN-FORMAN CORP. - B"), or as a trailing letter
    on the issuer name ("BERKSHIRE HATHAWAY INC B"). The dash/trailing
    forms matter: Brown-Forman's Class B CUSIP (115637209, 584 filers)
    names its class only as "- B", and without them the resolver fell
    back to zero-share "CL B" stubs and left BF-B blank."""
    wanted = CLASS_TICKERS.get(symbol)
    if not wanted:
        return False
    for n, cl in _cusip_variants(totals.get(cusip, {})):
        hay = ((n or "") + " " + (cl or "")).upper()
        if (re.search(rf"\bCL\.?\s*{wanted}\b", hay)
                or re.search(rf"\bCLASS\s*{wanted}\b", hay)
                or re.search(rf"\s{wanted}$", (n or "").upper())):
            return True
    return False


_STAGE_SCORE = {"exact": 3, "token": 2, "subset": 1, "spaceless": 1,
                "override": 3}


def _score_candidates(symbol, candidates, totals, stages=None):
    """Rank eligible CUSIP candidates with a transparent score.

    Eligibility: plain common stock (see _is_common_class) with
    reported shares — a zero-share stub can never win, and a bond,
    note, option or preferred never competes with the common stock.
    Ranking, in order: share-class match (CLASS_TICKERS only), most
    distinct reporting managers (filers), most reported shares, best
    matching stage as a tie-break. Filers lead on purpose: the Q2 2026
    audit found exact-name stubs (1-3 filers, a few thousand shares)
    for 18 tickers — Accenture, Bank of America, Exxon Mobil — where
    a fidelity-first rule would pick the stub over the real CUSIP
    with thousands of filers. Name fidelity is recorded in the score
    for the diagnostics file, but it never outranks overwhelming
    manager consensus; a wrong issuer is caught by the other-issuer
    veto in build_cusip_map, not by the ranking. Returns [(cusip,
    score)] sorted best-first.
    """
    stages = stages or {}
    scored = []
    for c in candidates:
        entry = totals.get(c, {})
        if not any(_is_common_class(cl)
                   for _n, cl in _cusip_variants(entry)):
            continue
        if (entry.get("shares_all") or 0) <= 0:
            continue
        stage = stages.get(c)
        stage_name = _STAGE_NAMES[stage] if stage is not None else "?"
        scored.append((c, {
            "class_match": _class_letter_match(symbol, totals, c),
            "filers": entry.get("filers") or 0,
            "shares_all": entry.get("shares_all") or 0,
            "stage": stage_name,
            "stage_score": _STAGE_SCORE.get(stage_name, 1),
        }))
    scored.sort(key=lambda kv: (not kv[1]["class_match"],
                                -kv[1]["filers"], -kv[1]["shares_all"],
                                -kv[1]["stage_score"], kv[0]))
    return scored


def _resolve_candidates(symbol, candidates, totals, stages=None):
    """Pick one CUSIP from the candidates under one issuer name: the
    ticker's share class first (CLASS_TICKERS), else the plain
    common-stock CUSIP reported by the MOST DISTINCT 13F MANAGERS
    (filers), tie-broken by most reported shares, then best matching
    stage. Returns None if no candidate resolves. A zero-share stub
    CUSIP must never beat the real one.

    Most-filers, not most-shares, is the discriminator — Q2 2026 proved
    why: a mislabeled variant can attach a WRONG CUSIP that carries
    more reported shares than the real one. Rocket Lab (RKLB) matched
    both 773121108 (Rocket Lab common, 317M shares, 1,095 filers) and
    77311W101 (Rocket Companies' Class A — a different issuer, whose
    recorded name a filer mislabeled "ROCKET LAB CORP CLASS A" —
    946M shares, 770 filers); most-shares picked the wrong one and
    produced 158%. Hubbell (HUBB) matched Hub Group's CUSIP the same
    way (62M shares, 276 filers) over Hubbell's own (49M shares, 993
    filers). The true common-stock CUSIP is the one the most managers
    report; the share total follows from it, never the other way round.
    """
    scored = _score_candidates(symbol, candidates, totals, stages)
    return scored[0][0] if scored else None


_STAGE_NAMES = ("exact", "token", "subset", "spaceless")


def _pool_candidates(norm, by_name, by_tokens):
    """Pool candidate CUSIPs for one normalized universe name, recording
    the best (strictest) matching stage per CUSIP: 0 exact normalized
    name, 1 order-insensitive token-set match, 2 subset match (the
    universe name's tokens are all inside one 13F name), 3 spaceless
    match. The pool is the union over stages — a candidate that matches
    exactly and fuzzily is recorded at stage 0."""
    tokens_u = frozenset(norm.split())
    stage = {}

    def add(cusips, st):
        for c in cusips:
            if c not in stage or st < stage[c]:
                stage[c] = st

    add(by_name.get(norm, []), 0)
    if tokens_u:
        # (b) token-set match
        for tokens_t, cusips in by_tokens.items():
            if _tokens_match(tokens_u, tokens_t):
                add(cusips, 1)
        # (c) subset match
        for tokens_t, cusips in by_tokens.items():
            if tokens_u < tokens_t:
                add(cusips, 2)
        # (d) spaceless match
        if norm:
            spaceless_u = norm.replace(" ", "")
            for name13, cusips in by_name.items():
                if name13.replace(" ", "") == spaceless_u:
                    add(cusips, 3)
    return stage


def _candidate_record(symbol, cusip, stage, totals):
    """One diagnostic record for a pooled candidate CUSIP: its
    reporting-manager count, share totals, matching stage, whether any
    recorded variant is plain common stock, and whether it was
    excluded as an ETF (an ETF is never a universe company's common
    stock, even when managers label its class "COM")."""
    entry = totals.get(cusip, {})
    variant_names = [n.upper().split()
                     for n, _cl in _cusip_variants(entry)]
    excluded = "ETF" if any("ETF" in toks for toks in variant_names) else None
    return {
        "cusip": cusip,
        "stage": _STAGE_NAMES[stage] if stage is not None else "override",
        "filers": entry.get("filers") or 0,
        "shares_all": entry.get("shares_all") or 0,
        "shares": entry.get("shares") or 0,
        "common_class": any(_is_common_class(cl)
                            for _n, cl in _cusip_variants(entry)),
        "excluded": excluded,
        "name": entry.get("name"),
        "class": entry.get("class"),
    }


def build_cusip_map(totals, universe):
    """Map universe tickers to CUSIPs using the 13F issuer names.

    Returns (mapping, unmatched, ambiguous, pools): mapping is ticker
    -> CUSIP; unmatched lists tickers with no name match; ambiguous
    lists tickers whose name matched several CUSIPs without a class
    resolution; pools maps every ticker to its candidate records
    (see _candidate_record), including ETF-excluded candidates, so the
    audit and the diagnostics file can show exactly what was
    considered and why a candidate lost.

    Matching is staged, most to least strict, so a short universe name
    never steals another company's CUSIP:
    (a) exact normalized name; (b) order-insensitive token-set match
    (catches word-swapped names and manager truncations); (c) subset
    match — the universe name's tokens are all inside one 13F name
    (catches short universe names like "Coinbase" for "Coinbase Global"
    or "Air Products" for "Air Products & Chemicals"); (d) spaceless
    match ("MERCADOLIBRE" for "Mercado Libre"). Candidates from ALL
    stages are pooled and resolved once by _score_candidates: share
    class first, then most distinct reporting managers, then most
    reported shares, then best matching stage. A stray small CUSIP
    whose name happens to match exactly (e.g. a 25k-share Bank of
    America stub) must never beat the real 5.3B-share CUSIP that only
    matches fuzzily.

    Vetoes (recorded on the candidate record, never silent): a
    candidate naming an ETF; a candidate whose recorded name
    normalizes to a DIFFERENT universe company's name (one CUSIP on
    two companies — e.g. Brown & Brown's CUSIP in Brown-Forman's
    pool). The selected record is marked with its score, a mapping
    confidence (high/medium/low) and warnings (close-margin, thin,
    no-exact-stage, class-fallback, ambiguous-near-tie) so the
    diagnostics file can flag mappings that need a human look instead
    of silently picking an unreliable identifier.
    """
    by_name = {}
    for cusip, entry in totals.items():
        for name, _cls in _cusip_variants(entry):
            by_name.setdefault(_normalize_name(name), []).append(cusip)
    by_tokens = {}
    for name, cusips in by_name.items():
        by_tokens.setdefault(frozenset(name.split()), []).extend(cusips)
    # Normalized universe name -> tickers of that issuer (multi-class
    # tickers share one name: GOOGL/GOOG are both "ALPHABET"). A
    # candidate whose recorded name normalizes to one of these names
    # belongs to that issuer; claimed by any other ticker it is vetoed.
    issuer_names = {}
    for symbol2, info2 in universe.items():
        norm2 = _normalize_name(info2.get("name", ""))
        norm2 = NAME_ALIASES.get(norm2, norm2)
        issuer_names.setdefault(norm2, set()).add(symbol2)
    mapping, unmatched, ambiguous, pools = {}, [], [], {}
    for symbol, info in universe.items():
        # Pinned CUSIP (see CUSIP_OVERRIDES): the name matcher gets
        # these wrong, so skip matching entirely.
        if symbol in CUSIP_OVERRIDES and CUSIP_OVERRIDES[symbol] in totals:
            mapping[symbol] = CUSIP_OVERRIDES[symbol]
            record = _candidate_record(symbol, CUSIP_OVERRIDES[symbol], None, totals)
            record["selected"] = True
            record["confidence"] = "override"
            record["warnings"] = ["override"]
            pools[symbol] = [record]
            continue
        norm = _normalize_name(info.get("name", ""))
        norm = NAME_ALIASES.get(norm, norm)
        stage = _pool_candidates(norm, by_name, by_tokens)
        records = [_candidate_record(symbol, c, st, totals)
                   for c, st in sorted(stage.items(), key=lambda kv: (kv[1], -(totals.get(kv[0], {}).get("filers") or 0)))]
        for record in records:
            if record["excluded"]:
                continue
            for variant_name, _cl in _cusip_variants(totals.get(record["cusip"], {})):
                owners = issuer_names.get(_normalize_name(variant_name))
                if owners and symbol not in owners:
                    record["excluded"] = "OTHER_ISSUER"
                    record["excluded_owner"] = sorted(owners)
                    break
        pools[symbol] = records
        candidates = [r["cusip"] for r in records if not r["excluded"]]
        scored = _score_candidates(symbol, candidates, totals, stage) if candidates else []
        if scored:
            resolved = scored[0][0]
            mapping[symbol] = resolved
            winner = scored[0][1]
            runner_up = scored[1][1] if len(scored) > 1 else None
            warnings = []
            if runner_up and runner_up["filers"] > 0.5 * winner["filers"]:
                warnings.append("close-margin")
            if winner["filers"] < 100:
                warnings.append("thin")
            if not any(r["stage"] == "exact" and not r["excluded"]
                       for r in records):
                warnings.append("no-exact-stage")
            if symbol in CLASS_TICKERS and not winner["class_match"]:
                warnings.append("class-fallback")
            if (runner_up and runner_up["filers"] >= 0.9 * winner["filers"]
                    and runner_up["stage"] != winner["stage"]):
                warnings.append("ambiguous-near-tie")
            if runner_up and runner_up["filers"] >= 2 * winner["filers"]:
                warnings.append("runner-up-dominates")
            if winner["filers"] >= 2 * (runner_up["filers"] if runner_up else 0):
                confidence = "high"
            elif runner_up and winner["filers"] >= 1.5 * runner_up["filers"]:
                confidence = "medium"
            else:
                confidence = "low"
            for record in records:
                if record["cusip"] == resolved:
                    record["selected"] = True
                    record["score"] = winner
                    record["confidence"] = confidence
                    record["warnings"] = warnings
                    break
        elif candidates:
            ambiguous.append((symbol, candidates))
        else:
            unmatched.append(symbol)
    return mapping, unmatched, ambiguous, pools


def build_shareholding(tickers, quarter_end=None, totals=None, log=print):
    """Per-ticker institutional ownership for one quarter.

    tickers: symbols to compute. totals: a prior aggregate() result (to
    reuse the download); otherwise the quarter is aggregated here.
    Returns the shareholding dict keyed by ticker, plus the totals/stats.
    """
    if quarter_end is None:
        quarter_end, _label = latest_completed_quarter()
    if totals is None:
        totals, stats = aggregate(quarter_end, log=log)
    else:
        stats = {"quarter_end": quarter_end.isoformat(), "reused_totals": True}
    universe = edgar.universe()
    mapping, unmatched, ambiguous, pools = build_cusip_map(totals, {s: universe[s] for s in tickers if s in universe})
    if unmatched:
        log(f"13F: no CUSIP match for {len(unmatched)} tickers: {unmatched[:20]}")
    if ambiguous:
        log(f"13F: ambiguous CUSIP for {len(ambiguous)} tickers: {[a[0] for a in ambiguous[:20]]}")
    out = {}
    for symbol in tickers:
        cusip = mapping.get(symbol)
        if not cusip:
            out[symbol] = {"institutions_pct": None, "cusip": None, "quarter": quarter_end.isoformat()}
            continue
        entry = totals.get(cusip, {})
        group = CUSIP_GROUPS.get(symbol)
        if group:
            # Sum the group's CUSIPs (same stock under several CUSIPs).
            # Filers is the max, not the sum: one manager can hold the
            # stock under two of the group's CUSIPs.
            merged = {"shares": 0, "shares_sole": 0, "shares_all": 0, "filers": 0}
            for gcusip in group:
                gentry = totals.get(gcusip, {})
                merged["shares"] += gentry.get("shares") or 0
                merged["shares_sole"] += gentry.get("shares_sole") or 0
                merged["shares_all"] += gentry.get("shares_all") or 0
                merged["filers"] = max(merged["filers"], gentry.get("filers") or 0)
            entry = merged
        try:
            shares_out, so_end = shares_outstanding_asof(symbol, quarter_end)
        except Exception:  # noqa: BLE001 — a missing facts file is a dash, not a crash
            shares_out, so_end = None, None
        # Headline figure: ALL discretion (SOLE + DFND + SHRD), DE-DUPLICATED
        # by participant-set grouping in aggregate() — each shared block
        # counts once, at the largest amount any participant reported.
        # Validated against independent references for Q2 2026 — AAPL
        # 66.03% vs 66.01% (stockanalysis.com), MSFT 73.23% vs 73.86%
        # (BusinessQuant) — while SOLE+DFND undershoots both by 0.6–1.4pp.
        # SHRD ("shared-other") is the mirror side of a DFND block (the
        # other manager's report of the same shares), so it counts only
        # through the group max, never on top of the DFND report. The
        # SOLE+DFND figure is kept below for comparison.
        inst = entry.get("shares_all")
        pct = (inst / shares_out) if inst and shares_out else None
        selected = next((r for r in pools.get(symbol, [])
                         if r.get("selected")), None)
        out[symbol] = {
            "institutions_pct": pct,
            "institutions_shares": inst,
            "institutions_pct_sole_dfnd": (entry.get("shares") / shares_out) if entry.get("shares") and shares_out else None,
            "institutions_pct_sole": (entry.get("shares_sole") / shares_out) if entry.get("shares_sole") and shares_out else None,
            "shares_outstanding": shares_out,
            "shares_outstanding_asof": so_end,
            "filers": entry.get("filers"),
            "cusip": cusip,
            "cusips": group if group else [cusip],
            "quarter": quarter_end.isoformat(),
            # Mapping quality, from the CUSIP resolution (see
            # build_cusip_map): high/medium/low/override, plus any
            # warnings (close-margin, thin, no-exact-stage,
            # class-fallback, ambiguous-near-tie). The full candidate
            # pool lives in the diagnostics file, not here.
            "mapping_confidence": (selected or {}).get("confidence"),
            "mapping_warnings": (selected or {}).get("warnings") or [],
        }
    return out, totals, stats


# ---------------------------------------------------------------------------
# Top holders (per-manager attribution)
#
# The aggregate() totals above hold per-CUSIP sums only — the per-manager
# rows were summed and discarded. The top-holders build re-downloads the
# information tables and keeps, per filing, the SOLE shares for universe
# CUSIPs; the shared (DFND/SHRD) part comes from the participant-set
# groups, which the checkpoint already records per reporting manager.
#
# Attribution rule (documented, same de-dup as the audited totals): a
# shared block counts ONCE, at the largest amount any participant
# reported for it, and is attributed to ONE participant — the winner
# below. The winner is the participant who reported the largest amount
# for the block (the "all" figure: DFND + SHRD for that reporter in
# that group). Ties are the normal case — every participant in a group
# reports the same block value — so they break toward the manager who
# reported the block under DFND (the one who defined the discretion;
# the SHRD reporters are mirrors), then toward the largest DFND amount,
# then toward the lowest CIK (deterministic, arbitrary, recorded).
# SOLE rows are never shared, so they attribute to their reporter in
# full. The per-manager sums reconcile exactly with the audited totals:
# sum over managers == the finalized shares_all == shares (the two
# coincide after de-dup — verified for all 30,368 CUSIPs in Q2 2026).
# ---------------------------------------------------------------------------

def group_winner(per_reporter):
    """One winner for a shared block.

    per_reporter: {reporter_cik: (dfnd_shares, all_shares)} for one
    (cusip, participant-set) group. Returns (winner_cik, amount) where
    amount is the block counted once, at the largest amount any
    participant reported. Tie-breaks, in order: largest "all" amount;
    reporter under DFND (dfnd > 0) over a SHRD-only reporter; largest
    DFND amount; lowest CIK. Returns (None, 0) when no reporter has
    shares (an all-zero group counts nothing).
    """
    best = None
    for cik, amounts in per_reporter.items():
        dfnd, all_shares = amounts[0], amounts[1]
        if not all_shares:
            continue
        # Sort key, best-first: amount desc, DFND reporter first,
        # DFND amount desc, CIK asc (deterministic).
        key = (-all_shares, 0 if dfnd else 1, -dfnd, cik)
        if best is None or key < best[0]:
            best = (key, cik, all_shares)
    if best is None:
        return None, 0
    return best[1], best[2]


def per_manager_holdings(sole_by_manager, groups):
    """Per-manager holdings by CUSIP from SOLE rows + shared groups.

    sole_by_manager: {manager_cik: {cusip: sole_shares}}.
    groups: {(cusip, participants_tuple): {reporter_cik: (dfnd, all)}}.
    Returns {manager_cik: {cusip: shares}} with each shared block
    counted once and attributed to its group winner (see group_winner).
    """
    holdings = {}
    for cik, per_cusip in sole_by_manager.items():
        slot = holdings.setdefault(cik, {})
        for cusip, shares in per_cusip.items():
            if shares:
                slot[cusip] = slot.get(cusip, 0) + shares
    for (cusip, _participants), per_reporter in groups.items():
        winner, amount = group_winner(per_reporter)
        if winner is None or not amount:
            continue
        slot = holdings.setdefault(winner, {})
        slot[cusip] = slot.get(cusip, 0) + amount
    return holdings


def rank_top_holders(holdings, cusips, shares_outstanding, top_n=5):
    """Rank managers holding one ticker's stock.

    holdings: {manager_cik: {cusip: shares}} (see per_manager_holdings).
    cusips: the ticker's common-stock CUSIP(s) — several for CUSIP_GROUPS
    tickers (HON), one otherwise. shares_outstanding: the same
    denominator data/shareholding.json uses for the ticker.
    Returns {"top": [{cik, shares, pct}], "managers": n, "total": shares}
    where total is the sum over ALL managers (reconciliation target:
    it must equal the ticker's institutions_shares in shareholding.json)
    and top is the top_n managers by shares, pct = shares / shares_out.
    Managers are ranked by shares desc, CIK asc as a deterministic tie-break.
    """
    by_manager = {}
    for cik, per_cusip in holdings.items():
        total = sum(per_cusip.get(c, 0) for c in cusips)
        if total:
            by_manager[cik] = total
    ranked = sorted(by_manager.items(), key=lambda kv: (-kv[1], kv[0]))
    total = sum(by_manager.values())
    top = [{"cik": cik, "shares": shares,
            "pct": (shares / shares_outstanding) if shares_outstanding else None}
           for cik, shares in ranked[:top_n]]
    return {"top": top, "managers": len(by_manager), "total": total}
