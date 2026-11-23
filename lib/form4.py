"""SEC Form 4 insider holdings — free, no API key.

Method (documented, verifiable — nothing here is estimated):
- Form 4 and 4/A filings per issuer, enumerated through EDGAR's
  full-text search (efts.sec.gov) over 2016-01-01 to today, one query
  per form (forms=4 and forms=4/A, paginated, size=100). efts returns
  ONE hit per filing, with _source.ciks listing every CIK on it —
  reporting owners AND the issuer, in no guaranteed order (one
  Microsoft filing lists [issuer 789019, owner 1576843], so ciks[0]
  is NOT reliably the owner). Each hit therefore expands to one entry
  per NON-ISSUER cik, with the owner name taken from the matching
  display_names index. Per-company totals are a few hundred hits —
  well under efts's 10,000 cap. The XML's own <issuer> block is then
  checked against the target issuer: efts matches ANY CIK on a filing,
  so a filing where the target is only a reporting owner (Alphabet on
  GV funds' Form 4s for Magenta Therapeutics, ARMO BioSciences and
  Arcus Biosciences) is dropped as a false positive, and owners whose
  every filing is such a false positive are excluded entirely
  (owners_not_issuer), not counted as no-holding. Enumeration runs
  TWICE per ticker and unions the results on (owner, accession):
  efts pagination is occasionally short (BAC, 2026-11-22: one run
  returned 1,335 hits and missed Berkshire's latest filing, a later
  run 1,635), so a filing missed by one run is caught by the other.
- One XML per owner: their most recent Form 4 by file_date (accession
  breaks ties); an amendment (4/A) supersedes the original because it
  files later. If that filing reports no common-stock non-derivative
  holding (derivatives only), the next most recent filing is tried,
  up to MAX_FILINGS_PER_OWNER attempts; if none reports one, the owner
  is counted under owners_no_holding, never guessed.
- XML URL (verified 2026-11-22 — the accession prefix is the filer's
  CIK, NOT the directory): the filing lives under the ISSUER's CIK:
  https://www.sec.gov/Archives/edgar/data/{issuer CIK, no leading
  zeros}/{adsh without dashes}/form4.xml. The task brief's stated rule
  (first 10 digits of adsh + xslF345X06/form4.xml) 404s on a live
  filing (Apple adsh 0001140361-26-044952, verified). The driver first
  tries form4.xml under the issuer CIK, then falls back to the filing's
  index.json and takes the .xml it lists (usually form4.xml).
- Parsing uses the nonDerivativeTable only (derivativeTable — options,
  RSUs, warrants — is never counted). The security title must be common
  stock for that ticker: for the 53 class tickers (CLASS_TICKERS — the
  letter derived from the ticker's own 13F titleOfClass variants, plus
  BF-B and META by hand) the title must name the ticker's class
  ("Class A Common Stock", "Class C Capital Stock" for Alphabet's
  Class C, "Class B Common" for Brown-Forman, "Class A Subordinate
  Voting Shares" for Shopify, "Class A ordinary shares" for Accenture
  and Aon) or carry no class letter at all (a bare "Common Stock"
  title counts — see title_matches); for plain tickers any "Common
  Stock", "Common Shares" (Abbott: "Common shares without par value")
  or "Ordinary Shares" title counts. Rows are grouped into holding
  buckets by (title, direct/indirect, the natureOfOwnership text — the
  trust or entity the shares sit in); within a bucket the LAST row's
  sharesOwnedFollowingTransaction is the balance, and the holding is
  the sum of the buckets. One filing can carry several indirect
  buckets (Pichai's 2026-10-27 filing holds Class C in two separate
  annuity trusts, 555,732 shares each), so per-nature last-wins would
  drop whole trusts. A genuine zero after a sale is a real zero and
  is kept.
- Joint filings (one Form 4, several reporting owners): the XML's
  nonDerivativeTable does not separate holdings per owner, so the
  holding is attributed once, to the FIRST reportingOwner listed in
  the XML. A co-owner whose most recent filing is a joint filing where
  they are not first falls through to their earlier filings, exactly
  like the derivatives-only fallback. Joint filings used are counted
  in joint_filings; co-owners resolved this way are reported as
  owners_joint_covered (they are neither measured nor no-holding).
- Indirect-mirror de-dup (same idea as the 13F participant-set de-dup:
  one block of shares counts once): a reporting owner often reports
  shares held by an entity they control as INDIRECT ("By LGC Holdco,
  LLC"), while the entity files its own Form 4 reporting the same
  shares as DIRECT (Lachlan Murdoch's FOX filing reports 85,372,810
  Class B indirect "By LGC Holdco, LLC"; LGC Holdco's own filing
  reports the same 85,372,810 direct). When an indirect bucket's
  natureOfOwnership names another measured owner (normalized name
  match, exactly one such owner) AND the bucket's shares exactly equal
  that owner's total holding, the bucket is removed from the first
  owner's total and the block counts once, under the direct holder.
  The gross (pre-dedup) total is kept as insiders_total_shares_gross
  alongside the deduped insiders_total_shares, with dedup_notes naming
  every removed block — so the merge step can audit or revert it.
  Buckets naming a holder who files no Form 4 of their own are kept:
  the indirect report is then the only record of that block.
- Known-fabrication owners are excluded outright (EXCLUDED_OWNER_CIKS):
  Antonio Lee (CIK 1695879) filed fake Feb 2017 Form 4s claiming
  Alphabet bought his "YNoFace Holdings" for 4.5 billion Alphabet
  shares (~76-81% of the class) at $0.001/share — Bloomberg, Feb 2017:
  "none of it was true". The SEC rarely removes known shams, so the
  exclusion lives in code with its evidence. Excluded owners count
  under owners_excluded_spoof, never as no-holding.
- Insiders % = shares / shares_outstanding from data/shareholding.json
  (the same denominator as the institutional %, per-class for class
  tickers). Top 5 ranked by shares desc, CIK asc tie-break.
- Coverage limits (stated in the UI by the parent): a holder's figure
  is as of their most recent Form 4, which may be after the quarter
  end; former insiders who still hold shares keep their last reported
  holding in the total; holders who only ever filed a Form 3 initial
  statement never appear in Form 4 data; managers under the Section 16
  threshold do not file. Missing data shows as absent, never zero-filled.

EDGAR limits: max 10 requests/second; this module stays at 4/s because
the 13F institutional build runs concurrently at 5/s against the same
endpoint (4 + 5 < 10). Retries on 429/5xx.
"""

import gzip
import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

UA = {
    "User-Agent": "NorthstarScreener research contact kishore.svjr@gmail.com",
    "Accept-Encoding": "gzip",
}
EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
# Requests per second cap (EDGAR asks for 10; the 13F build runs at 5/s
# concurrently, so this module stays at 4/s — combined under 10/s).
RATE_PER_SECOND = 4.0
# Workers only keep the pipe full up to the rate cap: SEC latency is
# ~1s per request, so 4 workers would start only ~2.7/s. 8 workers
# saturate the 4/s cap without ever exceeding it (the limiter gates
# every request start).
MAX_WORKERS = 8
# How many of an owner's filings to try, most recent first, before
# concluding they report no common-stock holding. The first filing
# almost always has one; the cap only bounds derivatives-only owners.
MAX_FILINGS_PER_OWNER = 10

# Issuer CIKs the Form 4 enumeration must NOT take from data/cik-map.json.
# XOM: the SEC's company_tickers list (and the filings pipeline) maps XOM
# to ExxonMobil Holdings Corp (CIK 2115436), the listed holding company —
# but that registrant has filed zero Form 4s (efts returns no Form 4 hits
# for it since 2016) and no 10-K yet. The operating company's insiders
# file under Exxon Mobil Corp (CIK 34088: 300 Form 4s in its recent
# window, latest Nov 2025). The override is Form 4-only: the financials
# pipeline and the Documents links keep the listed registrant's CIK, and
# data/cik-map.json is NOT edited for this — it is regenerated from
# company_tickers.json by the daily full rebuild, so a hand edit there
# would be overwritten by the next rebuild anyway.
FORM4_CIK_OVERRIDES = {
    "XOM": "34088",
}


def issuer_cik_for(symbol, cik):
    """The CIK whose Form 4s to enumerate for a ticker: the override
    above when one exists, else the cik-map CIK."""
    return FORM4_CIK_OVERRIDES.get(symbol, cik)
# Reporting-owner CIKs excluded outright — their Form 4s are
# DOCUMENTED fabrications, not holdings. The SEC accepts EDGAR
# submissions with no vetting and rarely removes known shams, so the
# exclusion lives here, with the evidence, rather than in the data.
#
#   1695879 "Lee Antonio": Feb 2017 Form 4s claiming Alphabet bought
#   his "YNoFace Holdings" for stock worth $3.6 trillion — 4.5 billion
#   Alphabet shares (~76-81% of the class) "acquired" at $0.001/share,
#   remarks about "planned global tours", "shipping costs" and a
#   "$100,000 per share" target. Bloomberg, "A $3.6 Trillion M&A Deal?
#   Really? Just Disregard That SEC Filing" (Feb 2017): "none of it
#   was true... his fabricated report in... the U.S. Securities and
#   Exchange Commission's Edgar database". He filed the same
#   fabrication for Bank of America (Oct 2016, $88B). Excluded owners
#   are counted under owners_excluded_spoof, never as no-holding.
#   1584209 "YNOFACE Holdings Inc": Lee's own entity, the other half
#   of the same fabrication — its Oct 19, 2016 Form 4 for Bank of
#   America claims 4,201,596,806 BAC shares (60% of the class)
#   "acquired" in equity-swap transactions; the Bloomberg piece names
#   the Oct 19 filing as the BofA half of the hoax.
EXCLUDED_OWNER_CIKS = {"1695879", "1584209"}

# Enumeration window: Form 4 history from 2016 (officers/directors from
# before then who never filed again are out of scope by design).
WINDOW_START = date(2016, 1, 1)

# Share-class tickers: the ticker's class letter picks the Form 4
# security title ("Class A Common Stock" etc.). Derived 2026-11-22
# from data/13f-totals-2026Q2.json: for each ticker, the class letter
# named in any variant of its own CUSIP's 13F titleOfClass ("COM CL A",
# "BERKSHIRE HATHAWAY INC DEL CL B NEW", ...). 51 tickers carry a
# letter, with NO conflicts (no ticker's variants named two letters).
# Two manual additions: BF-B (13F variants write "Brown-Forman Corp.
# - B" with no CL letter; Class B verified against live Form 4s) and
# META (13F variants carry no letter, but Meta's traded class is
# Class A and Class B is founder-held and non-traded; Zuckerberg's
# filings title their shares "Class A Common Stock"). Single-class
# issuers have no entry and take the plain rule below.
CLASS_TICKERS = {
    "GOOGL": "A", "GOOG": "C",
    "BRK-B": "B", "BF-B": "B",
    "FOXA": "A", "FOX": "B",
    "NWSA": "A", "NWS": "B",
    "LEN": "A", "META": "A",
    "ABNB": "A", "ACN": "A", "AON": "A", "APP": "A", "ARES": "A",
    "BE": "A", "BKR": "A", "CBRE": "A", "CMCSA": "A", "COIN": "A",
    "CRWD": "A", "CRWV": "A", "DASH": "A", "DDOG": "A", "DELL": "C",
    "ECHO": "A", "EL": "A", "FCX": "B", "GDDY": "A", "HOOD": "A",
    "IBKR": "A", "KKR": "A", "MA": "A", "MAR": "A", "MDLZ": "A",
    "MSTR": "A", "NBIS": "A", "NKE": "B", "OKTA": "A", "P": "A",
    "PLTR": "A", "RDDT": "A", "SBAC": "A", "SHOP": "A", "SKYD": "B",
    "TKO": "A", "TSN": "A", "TWLO": "A", "UPS": "B", "VEEV": "A",
    "WDAY": "A", "XYZ": "A", "ZBRA": "A",
}

_CLASS_RE = re.compile(r"\bCLASS\s+([ABC])\b|\bCL\.?\s+([ABC])\b", re.IGNORECASE)

# Words that mark a title as something other than the common stock itself,
# even though the phrase "common stock" appears in it ("Common Stock
# Purchase Warrants" are warrants, not shares; "Common Stock Option" is
# an option; "Common Stock Units" are deferred units, not shares).
# Checked before the "common stock" test below.
_NON_COMMON_WORDS = ("warrant", "option", "restricted stock", "preferred",
                     "preference", "depositary",
                     "phantom", "debenture", "convertible", "stock unit")

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


def _get(url, timeout=30, tries=4):
    """GET with the EDGAR user agent, gzip, retries on 429/5xx and on
    transport failures. http.client errors MUST be retried: EDGAR
    truncates responses mid-download (IncompleteRead at ~1,304 bytes)
    and drops connections (RemoteDisconnected) — both are
    http.client.HTTPException, not URLError, so an earlier version of
    this function let them escape unretried, which failed ~100 tickers
    in the G-M stretch of the full run (2026-11-22) at the enumeration
    step. A truncated efts page must never kill a ticker."""
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
                http.client.HTTPException) as exc:
            last = exc
            if attempt < tries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    raise last


def _get_json(url, timeout=30):
    return json.loads(_get(url, timeout=timeout))


def _clean_display_name(display):
    """A filing's display name without the trailing " (CIK ...)" suffix."""
    return re.sub(r"\s*\(CIK[^)]*\)\s*$", "", display or "").strip()


def _class_letter(title):
    """The share-class letter in a security title, or None.

    "Class A Common Stock" -> "A"; "COM CL C" -> "C"; bare
    "Common Stock" -> None.
    """
    match = _CLASS_RE.search(title or "")
    if not match:
        return None
    return (match.group(1) or match.group(2)).upper()


def title_matches(title, symbol):
    """Does this Form 4 security title name the ticker's common stock?

    The title must name the ticker's common stock (so "Restricted Stock
    Units", "Stock Options", "Common Stock Purchase Warrants" and the
    like never match — and the derivativeTable is not parsed at all).
    Class tickers must name their own class letter: the classed title
    takes several spellings in the wild — "Class A Common Stock",
    "Class C Capital Stock" (Alphabet titles its Class C shares that
    way, verified on Pichai's 2026-10-27 filing, 0001193125-26-434831),
    "Class B Common" (Brown-Forman drops "Stock", verified 2026-11-22),
    "Class A Subordinate Voting Shares" (Shopify, per its 13F class
    "CL A SUB VTG SHS"), "Class A ordinary shares" (Accenture, Aon —
    Irish-domiciled issuers title their shares "ordinary shares"), or
    the bare "Class A Shares" (Nebius Group titles its Class A shares
    that way; without the "shares" word, NBIS measured ZERO owners in
    the full run, 2026-11-22) — so a title naming the right class with
    "common", "capital", "voting", "ordinary" or "shares" in it counts,
    while "Class C Google Stock Units" (GSUs) name the class but are
    units, not shares, and stay excluded. "Preference" and "depositary"
    are exclusion words, so "Class A Preference Shares" and "Class A
    Depositary Shares" never count even though they name a class and
    "shares".
    A bare "Common Stock" title (no class letter) also counts for a
    class ticker: dual-class filers name the class on classed rows, so
    a bare title is the filer's unlettered spelling of the traded class
    — and the lenient rule keeps a wrongly-mapped ticker (the letter
    map is derived from manager-written 13F classes) from losing all
    its holdings. Every other plain ticker accepts any title
    containing "common stock", "common shares" or "ordinary shares":
    Abbott titles its stock "Common shares without par value" and Arch
    Capital "Common Shares, $.0011 par value per share" — before this
    rule both measured ZERO owners (ABT/ACGL, full run 2026-11-22).
    "Depositary Shares", "Preference Shares" and the like name no
    common/ordinary stock and stay excluded. Abbreviations are
    expanded first: Analog Devices titles its stock "Comm Stock -
    $.16-2/3 value" (720 rows in the cache), and one filing misspells
    it "Commons shares" — both normalize to "common stock"/"common
    shares" before matching. Without this, ADI measured ZERO owners
    in the full run (2026-11-22).
    """
    text = (title or "").strip()
    lowered = text.lower()
    # Collapse runs of whitespace: some filers write "common  stock"
    # or "Class  B Common" with double spaces, which breaks substring
    # matching.
    lowered = re.sub(r"\s+", " ", lowered)
    # Expand the "Comm Stock" abbreviation (Analog Devices) and the
    # "Commons shares" typo to "common" before any matching; also
    # fix the "Common Sock" typo (Pinnacle West, 27 rows).
    lowered = re.sub(r"\bcomm(?:on)?s?\b", "common", lowered)
    lowered = re.sub(r"\bsock\b", "stock", lowered)
    if any(word in lowered for word in _NON_COMMON_WORDS):
        return False
    letter = _class_letter(text)
    wanted = CLASS_TICKERS.get(symbol)
    if wanted:
        if letter is None:
            return _is_common_title(lowered)
        if letter != wanted:
            return False
        return bool(re.search(r"\b(common|capital|voting|ordinary|shares)\b", lowered))
    return _is_common_title(lowered)


def _is_common_title(lowered):
    """A bare common-stock title: "common stock", "common shares"
    ("Common shares without par value", Abbott), "ordinary shares"
    (Irish-domiciled issuers: Accenture, Aon, Medtronic), "registered
    shares" (Swiss issuers: Garmin titles its stock "Registered
    Shares" — without this, GRMN measured ZERO owners in the full run,
    2026-11-22), "<Name> Common" (Humana titles its stock "Humana
    Common" — 1,106 rows in the cache; without this, HUM measured ZERO
    owners in the full run, 2026-11-22), or the bare word "common"
    (Cummins titles its stock just "Common" — 1,250 rows in the cache;
    without this, CMI measured ZERO owners in the full run,
    2026-11-22). The "<Name> Common" clause requires no "class" in
    the title, so "Class B Common" still never counts for a plain
    ticker. "Common Units" (partnership interests) are not common
    stock and stay excluded."""
    return bool(
        lowered == "common"
        or "common stock" in lowered or "common shares" in lowered
        or "ordinary shares" in lowered
        or "registered shares" in lowered
        or re.search(r"common\s*\(ordinary\)\s*shares", lowered)
        or (lowered.endswith(" common") and "class" not in lowered))


def _local(tag):
    return tag.split("}")[-1]


def _child_text(elem, name):
    """Text of the first direct child with local name `name`, stripped."""
    for child in elem:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _descendant_text(elem, *path):
    """Text found by walking direct children named in `path` in order.

    Form 4 values sit one level down (securityTitle/value,
    postTransactionAmounts/sharesOwnedFollowingTransaction/value), so
    each step is a direct-child lookup, not a deep search.
    """
    current = elem
    for name in path:
        found = None
        for child in current:
            if _local(child.tag) == name:
                found = child
                break
        if found is None:
            return ""
        current = found
    return (current.text or "").strip()


def _parse_shares(text):
    """A shares figure as an int, or None when it is not a number."""
    if not text:
        return None
    try:
        return int(float(text.replace(",", "").strip()))
    except ValueError:
        return None


def _norm_holder_name(name):
    """A holder name, normalized for matching: "By LGC Holdco, LLC" and
    "LGC Holdco, LLC" are the same holder; case, punctuation and extra
    spaces do not matter."""
    text = (name or "").strip()
    text = re.sub(r"^by\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^A-Z0-9 ]", " ", text.upper())
    return re.sub(r"\s+", " ", text).strip()


def parse_form4_xml(xml_bytes, symbol):
    """Parse one Form 4 XML for one ticker.

    Returns {"owners": [{"cik", "name"}], "direct": shares|None,
    "indirect": shares|None, "total": shares|None,
    "has_holding": bool, "joint": bool, "titles": [matched titles],
    "issuer_cik": the XML's <issuer> CIK (no leading zeros),
    "issuer_symbol": the XML's <issuer> trading symbol,
    "direct_buckets": [{"title", "shares", "nature"}],
    "indirect_buckets": [{"title", "shares", "nature"}]}.
    "total" is None when no matching common-stock row carries a
    sharesOwnedFollowingTransaction figure (derivatives-only filing).
    A genuine zero holding is total == 0 with has_holding True.

    Only the nonDerivativeTable is read, in document order. Rows are
    grouped into holding buckets by (title, direct/indirect, the
    natureOfOwnership text — the trust or entity the shares sit in);
    within a bucket the LAST row wins (its
    sharesOwnedFollowingTransaction is the bucket's balance after its
    last transaction), and the holding is the sum of the buckets.
    Per-nature last-wins would be wrong here: one filing can carry
    several indirect buckets (Pichai's 2026-10-27 filing holds Class C
    in two separate annuity trusts, 555,732 shares each — the per-nature
    last would drop one trust entirely; Zuckerberg's Sep 2026 filing
    carries CZI Holdings and the Chan Zuckerberg Biohub as separate
    indirect buckets). Both nonDerivativeTransaction rows (which report
    the holding after the transaction) and nonDerivativeHolding rows
    (holdings with no transaction in the period) carry
    sharesOwnedFollowingTransaction.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return {"owners": [], "direct": None, "indirect": None,
                "total": None, "has_holding": False, "joint": False,
                "titles": [], "issuer_cik": "", "issuer_symbol": "",
                "direct_buckets": [], "indirect_buckets": [],
                "parse_error": True}

    # The filing's own issuer, from the <issuer> block. The caller
    # checks it against the enumerated issuer: efts matches ANY CIK on
    # a filing, so a filing where the target issuer is only a reporting
    # owner (Alphabet on GV funds' Form 4s for Magenta Therapeutics,
    # ARMO BioSciences and Arcus Biosciences) must not count for the
    # target ticker.
    issuer_cik = ""
    issuer_symbol = ""
    for elem in root.iter():
        if _local(elem.tag) == "issuer":
            issuer_cik = _child_text(elem, "issuerCik").lstrip("0") or "0"
            issuer_symbol = _child_text(elem, "issuerTradingSymbol")
            break

    owners = []
    for owner_elem in root.iter():
        if _local(owner_elem.tag) != "reportingOwner":
            continue
        owner_id = None
        for child in owner_elem:
            if _local(child.tag) == "reportingOwnerId":
                owner_id = child
                break
        if owner_id is None:
            continue
        cik = _child_text(owner_id, "rptOwnerCik").lstrip("0") or "0"
        name = _child_text(owner_id, "rptOwnerName")
        owners.append({"cik": cik, "name": name})

    # {(title, nature, normalized natureOfOwnership): (shares, nature text)}
    buckets = {}
    titles = []
    for elem in root.iter():
        if _local(elem.tag) != "nonDerivativeTable":
            continue
        for row in elem:
            if _local(row.tag) not in ("nonDerivativeTransaction",
                                       "nonDerivativeHolding"):
                continue
            title = _descendant_text(row, "securityTitle", "value")
            if not title_matches(title, symbol):
                continue
            shares = _parse_shares(
                _descendant_text(row, "postTransactionAmounts",
                                 "sharesOwnedFollowingTransaction", "value"))
            if shares is None:
                continue
            nature = _descendant_text(row, "ownershipNature",
                                      "directOrIndirectOwnership", "value")
            nature = (nature or "D").upper()
            if nature not in ("D", "I"):
                nature = "D"
            holder_text = _descendant_text(row, "ownershipNature",
                                           "natureOfOwnership", "value")
            key = (title, nature, _norm_holder_name(holder_text))
            # Last row per bucket wins; earlier rows for the same bucket
            # are superseded balances, never summed.
            buckets[key] = (shares, holder_text)
            if title not in titles:
                titles.append(title)

    direct_buckets = [{"title": t, "shares": s, "nature": n}
                      for (t, nat, _h), (s, n) in buckets.items() if nat == "D"]
    indirect_buckets = [{"title": t, "shares": s, "nature": n}
                        for (t, nat, _h), (s, n) in buckets.items() if nat == "I"]
    if buckets:
        # A genuine zero holding stays a zero, never collapses to None.
        direct = sum(b["shares"] for b in direct_buckets)
        indirect = sum(b["shares"] for b in indirect_buckets)
        total = direct + indirect
    else:
        direct = indirect = total = None
    return {"owners": owners,
            "direct": direct,
            "indirect": indirect,
            "total": total,
            "has_holding": bool(buckets),
            "joint": len(owners) > 1,
            "titles": titles,
            "issuer_cik": issuer_cik,
            "issuer_symbol": issuer_symbol,
            "direct_buckets": direct_buckets,
            "indirect_buckets": indirect_buckets}


def _efts_page(issuer_cik, forms, start, end, offset):
    params = {
        "dateRange": "custom",
        "startdt": start.isoformat(),
        "enddt": end.isoformat(),
        "forms": forms,
        "ciks": str(issuer_cik).zfill(10),
        "from": offset,
        "size": 100,
    }
    url = EFTS_URL + "?" + urllib.parse.urlencode(params)
    return _get_json(url)


def _efts_hits_from_page(data, issuer_cik):
    """Owner hits from one efts page.

    efts returns ONE hit per filing, with _source.ciks listing every CIK
    on it — reporting owners AND the issuer, in no guaranteed order
    (one Microsoft filing lists [issuer 789019, owner 1576843], so
    ciks[0] is NOT reliably the owner). Each hit therefore expands to
    one entry per NON-ISSUER cik — a joint filing appears under each of
    its reporting owners with the same adsh. Hits listing only the
    issuer CIK have no reporting owner and are dropped. display_names
    align with ciks by index.
    """
    issuer_norm = str(issuer_cik).lstrip("0") or "0"
    hits = []
    for hit in data.get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        ciks = src.get("ciks") or []
        adsh = src.get("adsh")
        if not adsh or not ciks:
            continue
        names = src.get("display_names") or []
        for i, cik in enumerate(ciks):
            owner_cik = cik.lstrip("0") or "0"
            if owner_cik == issuer_norm:
                continue
            hits.append({
                "owner_cik": owner_cik,
                "owner_name": _clean_display_name(names[i] if i < len(names) else ""),
                "adsh": adsh,
                "file_date": src.get("file_date", ""),
                "form": src.get("form", ""),
            })
    return hits


def _efts_query(issuer_cik, forms, start, end):
    """All efts hits for one form, paginated (later pages in parallel).

    Page 0 is fetched first to learn the total; the remaining pages
    are fetched concurrently through the shared 4/s rate limiter.
    """
    first = _efts_page(issuer_cik, forms, start, end, 0)
    total = first.get("hits", {}).get("total", {}).get("value", 0)
    hits = _efts_hits_from_page(first, issuer_cik)
    # Early return is keyed on FILINGS seen, not owner entries: one
    # filing expands to several owner entries, so len(hits) can pass
    # total while pages are still unfetched.
    seen_filings = len(first.get("hits", {}).get("hits", []))
    if total <= 100 or seen_filings >= total:
        return hits
    offsets = list(range(100, total, 100))
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_efts_page, issuer_cik, forms, start, end, off): off
                   for off in offsets}
        for future in as_completed(futures):
            hits.extend(_efts_hits_from_page(future.result(), issuer_cik))
    return hits


def enumerate_filings(issuer_cik, start=None, end=None):
    """All Form 4 / 4-A filings for one issuer CIK in the window.

    Returns a list of {owner_cik, owner_name, adsh, file_date, form},
    one hit per (filing, reporting owner) — a joint filing appears once
    per reporting owner, with the same adsh. Hits are returned newest
    first as efts serves them; callers sort per owner.
    """
    start = start or WINDOW_START
    end = end or date.today()
    hits = []
    for forms in ("4", "4/A"):
        hits.extend(_efts_query(issuer_cik, forms, start, end))
    return hits


def latest_per_owner(hits):
    """{owner_cik: [filings, most recent first]}.

    Most recent = latest file_date, accession breaks ties — so a 4/A
    amendment (filed later than the original) supersedes it.
    """
    by_owner = {}
    for hit in hits:
        by_owner.setdefault(hit["owner_cik"], []).append(hit)
    for filings in by_owner.values():
        filings.sort(key=lambda f: (f["file_date"], f["adsh"]), reverse=True)
    return by_owner


def form4_url(issuer_cik, adsh):
    """Direct Form 4 XML URL: under the ISSUER's CIK (no leading zeros).

    Verified 2026-11-22: the accession prefix is the filer's CIK, not
    the directory — /data/{adsh prefix}/... 404s.
    """
    adsh_nodash = adsh.replace("-", "")
    return f"{ARCHIVES}/{int(issuer_cik)}/{adsh_nodash}/form4.xml"


def _xml_name_from_index(issuer_cik, adsh):
    """The Form 4 XML file name from the filing's index.json.

    The name is usually form4.xml but varies (doc4.xml, a bare number);
    prefer a name containing "form4", else the largest .xml.
    Returns None when the index cannot be read or lists no .xml.
    """
    adsh_nodash = adsh.replace("-", "")
    url = f"{ARCHIVES}/{int(issuer_cik)}/{adsh_nodash}/index.json"
    try:
        index = _get_json(url, timeout=30)
    except Exception:  # noqa: BLE001 — caller falls through to an error
        return None
    items = index.get("directory", {}).get("item", [])
    xmls = [it for it in items if it.get("name", "").lower().endswith(".xml")]
    if not xmls:
        return None
    preferred = [it for it in xmls if "form4" in it["name"].lower()]
    chosen = preferred[0] if preferred else max(xmls, key=lambda it: it.get("size", 0))
    return chosen["name"]


def fetch_form4_xml(issuer_cik, adsh, cache_dir=None):
    """Download one Form 4 XML (disk-cached by accession).

    Tries the direct form4.xml URL under the issuer CIK, then the
    index.json fallback. The cache is shared across tickers (class
    pairs GOOGL/GOOG etc. enumerate the same filings), so a filing
    fetched for one ticker is never re-downloaded for the other.
    Returns (xml_bytes, from_cache, error).
    """
    cache_path = None
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, f"{adsh}.xml")
        if os.path.exists(cache_path):
            with open(cache_path, "rb") as fh:
                return fh.read(), True, None
    url = form4_url(issuer_cik, adsh)
    try:
        xml_bytes = _get(url, timeout=30)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            return None, False, f"HTTP {exc.code} on {url}"
        name = _xml_name_from_index(issuer_cik, adsh)
        if not name:
            return None, False, f"404 on {url} and no .xml in index.json"
        adsh_nodash = adsh.replace("-", "")
        alt = f"{ARCHIVES}/{int(issuer_cik)}/{adsh_nodash}/{name}"
        try:
            xml_bytes = _get(alt, timeout=30)
        except Exception as exc2:  # noqa: BLE001 — one bad filing must not stop the run
            return None, False, f"404 on {url}; fallback {alt} failed: {exc2}"
    except Exception as exc:  # noqa: BLE001 — one bad filing must not stop the run
        return None, False, str(exc)
    if cache_path:
        tmp = cache_path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(xml_bytes)
        os.replace(tmp, cache_path)
    return xml_bytes, False, None


def _fetch_many(issuer_cik, adshs, cache_dir):
    """Fetch several Form 4 XMLs in parallel (rate limiter caps at 4/s).

    Returns {adsh: (xml_bytes, from_cache, error)}.
    """
    results = {}
    if not adshs:
        return results
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_form4_xml, issuer_cik, adsh, cache_dir): adsh
                   for adsh in adshs}
        for future in as_completed(futures):
            adsh = futures[future]
            try:
                results[adsh] = future.result()
            except Exception as exc:  # noqa: BLE001 — defensive; fetch already catches
                results[adsh] = (None, False, str(exc))
    return results


def rank_holders(holders, shares_outstanding, top_n=5):
    """Rank measured holders: shares desc, CIK asc tie-break; pct each."""
    ranked = sorted(holders, key=lambda h: (-h["shares"], h["cik"]))
    top = []
    for holder in ranked[:top_n]:
        top.append({
            "name": holder["name"],
            "cik": holder["cik"],
            "shares": holder["shares"],
            "pct": holder["shares"] / shares_outstanding if shares_outstanding else None,
            "filing_date": holder["filing_date"],
            "accession": holder["accession"],
        })
    return top


def dedup_indirect_mirrors(holders):
    """Remove indirect buckets that mirror another measured owner's holding.

    A reporting owner often reports shares held by an entity they control
    as INDIRECT ("By LGC Holdco, LLC"), while the entity files its own
    Form 4 reporting the same shares as DIRECT — counting both
    double-counts the block (FOX: Lachlan Murdoch 85,372,810 indirect
    "By LGC Holdco, LLC" + LGC Holdco 85,372,810 direct). A bucket is
    removed only when its natureOfOwnership names another measured owner
    (normalized-name match, exactly one such owner — ambiguous names
    never dedup), the named owner is not the holder themselves, and the
    bucket's shares exactly equal that owner's total holding: the block
    then counts once, under the direct holder. Buckets naming a holder
    who files no Form 4 of their own are kept — the indirect report is
    the only record of that block.

    Holders are mutated in place (their "shares" become the deduped
    total; the pre-dedup total is kept as "shares_gross"). Decisions are
    computed against the pre-dedup totals, so the result does not depend
    on processing order. Returns (notes, removed_shares).
    """
    by_name = {}
    for holder in holders:
        by_name.setdefault(_norm_holder_name(holder["name"]), []).append(holder)
    unique = {name: group[0] for name, group in by_name.items() if len(group) == 1}
    gross = {holder["cik"]: holder["shares"] for holder in holders}
    notes = []
    removed = 0
    for holder in holders:
        own_name = _norm_holder_name(holder["name"])
        for bucket in holder.get("indirect_buckets", []):
            shares = bucket["shares"]
            if not shares:
                continue
            named = _norm_holder_name(bucket.get("nature", ""))
            if not named or named == own_name:
                continue
            mirror = unique.get(named)
            if mirror is None or mirror["cik"] == holder["cik"]:
                continue
            if gross.get(mirror["cik"]) != shares:
                continue
            holder["shares"] -= shares
            removed += shares
            notes.append({
                "owner": holder["name"],
                "owner_cik": holder["cik"],
                "via": mirror["name"],
                "via_cik": mirror["cik"],
                "shares": shares,
                "title": bucket["title"],
                "accession": holder["accession"],
            })
    for holder in holders:
        holder["shares_gross"] = gross[holder["cik"]]
    return notes, removed


def build_ticker(symbol, issuer_cik, shares_outstanding, cache_dir=None,
                 start=None, end=None, log=None):
    """Build one ticker's insider entry from its Form 4 filings.

    Returns (entry, diagnostics). entry follows the staging schema:
    top, insiders_total_shares, insiders_total_pct, owners_measured,
    owners_no_holding, joint_filings (plus owners_joint_covered, the
    co-owners of joint filings attributed to the first reporting
    owner). diagnostics records enumeration/fetch counts and failures.
    """
    log = log or (lambda *a: None)
    issuer_norm = str(issuer_cik).lstrip("0") or "0"
    hits = enumerate_filings(issuer_cik, start=start, end=end)
    # efts pagination is occasionally short: one BAC run (2026-11-22)
    # returned 1,335 hits and missed Berkshire's latest filing entirely
    # (its 2020 filing stood, overstating BAC by 266M shares); a later
    # run returned 1,635. A second enumeration, unioned on
    # (owner, accession), catches one-off shortfalls — a filing missed
    # by one run is caught by the other. (A sustained index fault could
    # still fool both; the post-run diff sweep is the backstop.)
    hits2 = enumerate_filings(issuer_cik, start=start, end=end)
    union_extra = 0
    if len(hits2) != len(hits):
        seen = {(h["owner_cik"], h["adsh"]) for h in hits}
        extra = [h for h in hits2
                 if (h["owner_cik"], h["adsh"]) not in seen]
        union_extra = len(extra)
        hits.extend(extra)
        log(f"  {symbol}: efts runs disagree ({len(hits) - union_extra} vs "
            f"{len(hits2)} owner-hits); union added {union_extra}")
    efts_runs = (len(hits) - union_extra, len(hits2))
    by_owner = latest_per_owner(hits)
    # A joint filing appears once per reporting owner with the same
    # adsh; it is attributed once, to the first reportingOwner in the
    # XML, so track which accessions are already attributed.
    attributed_adsh = set()
    holders = []
    owners_no_holding = 0
    joint_filings = 0
    joint_covered = 0
    fetch_errors = []
    fetched = 0
    cache_hits = 0
    multi_title_filings = 0

    # Round-based fetch: round 0 fetches every owner's most recent
    # filing; later rounds fetch the next filing only for owners whose
    # latest reported no attributable holding.
    pending = {}  # owner_cik -> next filing index to try
    for owner_cik in sorted(by_owner):
        pending[owner_cik] = 0
    resolved = {}  # owner_cik -> holder dict or "no_holding" or "joint_covered"
    # Per-owner audit trail: which accession supplied the holding (or
    # why none was found), and how many filings were tried. Stored in
    # diagnostics so a run can be verified owner by owner.
    audit = {}
    # Owners whose every tried filing turned out to belong to another
    # issuer (efts false positives — the target issuer is only a
    # reporting owner there). They are not insiders of this ticker at
    # all: excluded from owners_measured AND owners_no_holding.
    mismatch_only = {owner_cik: True for owner_cik in by_owner}
    issuer_mismatches = []
    not_issuer_owners = []
    # Documented-fabrication owners (EXCLUDED_OWNER_CIKS): never fetch
    # their filings at all.
    excluded_spoof = sorted(c for c in by_owner if c in EXCLUDED_OWNER_CIKS)
    for owner_cik in excluded_spoof:
        resolved[owner_cik] = "excluded_spoof"
        audit[owner_cik] = {"attempts": [], "fetch_errors": [],
                            "status": "excluded_spoof"}
        del pending[owner_cik]

    def _mark_unresolved(owner_cik):
        """Resolve an owner who ran out of filings without a holding:
        "not_issuer" when every filing tried belonged to another issuer,
        else "no_holding"."""
        if mismatch_only.get(owner_cik):
            resolved[owner_cik] = "not_issuer"
            not_issuer_owners.append(owner_cik)
            status = "not_issuer"
        else:
            resolved[owner_cik] = "no_holding"
            status = "no_holding"
        audit.setdefault(owner_cik, {"attempts": [], "fetch_errors": []})
        audit[owner_cik]["status"] = status
    for round_no in range(MAX_FILINGS_PER_OWNER):
        if not pending:
            break
        wanted = {}
        for owner_cik, idx in list(pending.items()):
            filings = by_owner[owner_cik]
            if idx >= len(filings):
                _mark_unresolved(owner_cik)
                del pending[owner_cik]
                continue
            wanted[filings[idx]["adsh"]] = True
        if not wanted:
            break
        fetched_xml = _fetch_many(issuer_cik, sorted(wanted), cache_dir)
        for owner_cik in sorted(pending):
            idx = pending[owner_cik]
            filings = by_owner[owner_cik]
            if idx >= len(filings):
                _mark_unresolved(owner_cik)
                del pending[owner_cik]
                continue
            filing = filings[idx]
            xml_bytes, from_cache, error = fetched_xml.get(
                filing["adsh"], (None, False, "not fetched"))
            fetched += 1
            cache_hits += 1 if from_cache else 0
            if error or xml_bytes is None:
                fetch_errors.append((filing["adsh"], error or "unknown fetch error"))
                audit.setdefault(owner_cik, {"attempts": [], "fetch_errors": []})
                audit[owner_cik]["attempts"].append(filing["adsh"])
                audit[owner_cik]["fetch_errors"].append(
                    (filing["adsh"], error or "unknown fetch error"))
                # A failed fetch is not a "no holding" verdict: try the
                # owner's next filing rather than dropping them.
                pending[owner_cik] = idx + 1
                continue
            parsed = parse_form4_xml(xml_bytes, symbol)
            if parsed.get("parse_error"):
                fetch_errors.append((filing["adsh"], "unparseable XML"))
                audit.setdefault(owner_cik, {"attempts": [], "fetch_errors": []})
                audit[owner_cik]["attempts"].append(filing["adsh"])
                audit[owner_cik]["fetch_errors"].append((filing["adsh"], "unparseable XML"))
                pending[owner_cik] = idx + 1
                continue
            audit.setdefault(owner_cik, {"attempts": [], "fetch_errors": []})
            audit[owner_cik]["attempts"].append(filing["adsh"])
            if parsed.get("issuer_cik") and parsed["issuer_cik"] != issuer_norm:
                # efts false positive: this filing belongs to another
                # issuer (the target is only a reporting owner on it).
                # Not this ticker's filing at all — try the next one.
                issuer_mismatches.append(filing["adsh"])
                pending[owner_cik] = idx + 1
                continue
            mismatch_only[owner_cik] = False
            if len(parsed["titles"]) > 1:
                multi_title_filings += 1
            if not parsed["has_holding"]:
                pending[owner_cik] = idx + 1
                continue
            if parsed["joint"]:
                if filing["adsh"] in attributed_adsh:
                    # Already attributed to the first reporting owner.
                    joint_covered += 1
                    audit.setdefault(owner_cik, {"attempts": [], "fetch_errors": []})
                    audit[owner_cik]["status"] = "joint_covered"
                    audit[owner_cik]["accession"] = filing["adsh"]
                    audit[owner_cik]["filing_date"] = filing["file_date"]
                    resolved[owner_cik] = "joint_covered"
                    del pending[owner_cik]
                    continue
                first_owner = parsed["owners"][0]["cik"] if parsed["owners"] else None
                if first_owner is not None and first_owner != owner_cik:
                    # This filing's holding belongs to the first
                    # reporting owner; fall through to this owner's
                    # earlier filings for their own holding.
                    pending[owner_cik] = idx + 1
                    continue
                joint_filings += 1
                attributed_adsh.add(filing["adsh"])
            name = ""
            if parsed["owners"]:
                name = parsed["owners"][0]["name"]
            if not name:
                name = by_owner[owner_cik][0].get("owner_name") or owner_cik
            holders.append({
                "name": name,
                "cik": owner_cik,
                "shares": parsed["total"],
                "filing_date": filing["file_date"],
                "accession": filing["adsh"],
                "indirect_buckets": parsed["indirect_buckets"],
            })
            audit[owner_cik]["status"] = "measured"
            audit[owner_cik]["accession"] = filing["adsh"]
            audit[owner_cik]["filing_date"] = filing["file_date"]
            audit[owner_cik]["shares"] = parsed["total"]
            resolved[owner_cik] = "measured"
            del pending[owner_cik]
    for owner_cik in pending:
        _mark_unresolved(owner_cik)
    owners_no_holding = sum(1 for v in resolved.values() if v == "no_holding")
    joint_covered = sum(1 for v in resolved.values() if v == "joint_covered")

    gross_total = sum(h["shares"] for h in holders)
    dedup_notes, deduped_shares = dedup_indirect_mirrors(holders)
    for holder in holders:
        entry_audit = audit.get(holder["cik"], {})
        entry_audit["shares"] = holder["shares"]
        if holder["shares"] != holder["shares_gross"]:
            entry_audit["shares_gross"] = holder["shares_gross"]
        audit[holder["cik"]] = entry_audit
    total_shares = sum(h["shares"] for h in holders)
    entry = {
        "top": rank_holders(holders, shares_outstanding),
        "insiders_total_shares": total_shares,
        "insiders_total_shares_gross": gross_total,
        "deduped_shares": deduped_shares,
        "dedup_notes": dedup_notes,
        "insiders_total_pct": (total_shares / shares_outstanding
                               if shares_outstanding else None),
        "owners_measured": len(holders),
        "owners_no_holding": owners_no_holding,
        "owners_not_issuer": len(not_issuer_owners),
        "owners_excluded_spoof": len(excluded_spoof),
        "joint_filings": joint_filings,
        "owners_joint_covered": joint_covered,
    }
    diagnostics = {
        "hits": len(hits),
        "efts_runs": list(efts_runs),
        "efts_union_extra": union_extra,
        "owners_enumerated": len(by_owner),
        "xml_fetched": fetched,
        "xml_cache_hits": cache_hits,
        "fetch_errors": fetch_errors,
        "multi_title_filings": multi_title_filings,
        "issuer_mismatches": issuer_mismatches,
        "not_issuer_owners": not_issuer_owners,
        "excluded_spoof_owners": excluded_spoof,
        # Full per-owner audit trail (accession + filing_date behind
        # every holder, attempts + errors behind every no-holding).
        "owners": audit,
    }
    log(f"  {symbol}: {len(hits)} hits, {len(by_owner)} owners, "
        f"{len(holders)} measured, {owners_no_holding} no holding, "
        f"{joint_filings} joint, total {total_shares:,} shares"
        + (f" (gross {gross_total:,}, deduped {deduped_shares:,})"
           if deduped_shares else "")
        + (f" [{len(not_issuer_owners)} not-issuer owners excluded]"
           if not_issuer_owners else "")
        + (f" [{len(excluded_spoof)} spoof owner(s) excluded]"
           if excluded_spoof else ""))
    return entry, diagnostics
