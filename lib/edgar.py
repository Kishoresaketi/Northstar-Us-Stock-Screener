"""SEC EDGAR company facts client — free, no API key.

Source of real fundamentals for US-listed companies: annual (10-K) and
quarterly (10-Q) figures straight from the filings, plus the ratios computed
from them. All values are as reported; nothing here is invented.

Data notes (learned the hard way, 2026-11-16):
- EDGAR's `fy` field is the fiscal year of the FILING, not the period — the
  reliable key is the period `end` date. Years are labelled by the end year.
- A concept can go stale while a synonym carries on (Apple's "Revenues"
  stops at FY2018; "SalesRevenueNet" carries the recent years), so the
  concept used is the one with the most recent period end, not the first
  one with any points.
- Quarterly income-statement points include year-to-date values with an
  empty or YTD frame; only points whose frame is a real calendar quarter
  (e.g. CY2025Q1, no YTD) are the quarter's own numbers.
"""

import gzip
import json
import os
import time
import urllib.parse
import urllib.request

UA = {
    "User-Agent": "NorthstarScreener research contact kishore.svjr@gmail.com",
    "Accept-Encoding": "gzip",
}
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{}.json"

# Curated sector peers for the screener's seeded stocks (same-industry names).
# Every built ticker gets peers: these curated lists for the seeded eight,
# and for every other ticker the sector-derived peer map built by
# scripts/build_static_data.py (data/peer-map.json: same sub-industry first,
# then same sector, ranked by market cap). No cap on the count — include
# every peer that genuinely belongs.
PEERS = {
    "AAPL": ["MSFT", "GOOGL", "NVDA", "META", "AVGO", "AMD", "AMZN", "ORCL", "CRM", "ADBE", "INTC", "QCOM"],
    "MSFT": ["AAPL", "GOOGL", "NVDA", "META", "AMZN", "ORCL", "CRM", "ADBE", "IBM", "INTU"],
    "NVDA": ["AMD", "MSFT", "AVGO", "MU", "INTC", "QCOM", "TXN", "MRVL", "LRCX", "AMAT"],
    "GOOGL": ["MSFT", "META", "AAPL", "AMZN", "NVDA", "NFLX", "CRM", "ADBE", "ORCL", "UBER"],
    "LLY": ["JNJ", "PFE", "MRK", "ABBV", "AMGN", "BMY", "GILD", "VRTX", "ZTS", "REGN"],
    "JPM": ["BAC", "WFC", "GS", "C", "MS", "USB", "PNC", "TFC", "COF", "AXP"],
    "XOM": ["CVX", "COP", "SLB", "EOG", "MPC", "PSX", "OXY", "HAL", "DVN", "FANG"],
    "VST": ["CEG", "NRG", "DUK", "NEE", "SO", "D", "EXC", "AEP", "XEL", "PEG"],
}

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UNIVERSE_PATH = os.path.join(_ROOT, "scripts", "universe", "universe.json")
_PEER_MAP_PATH = os.path.join(_ROOT, "data", "peer-map.json")
_universe = None
_peer_map = {"mtime": 0, "data": {}}


def universe():
    """S&P 500 + Nasdaq-100 snapshot: symbol -> {name, sector, subindustry, indices}."""
    global _universe
    if _universe is None:
        try:
            with open(_UNIVERSE_PATH, encoding="utf-8") as fh:
                _universe = json.load(fh)
        except (OSError, ValueError):
            _universe = {}
    return _universe


def universe_entry(symbol):
    return universe().get(symbol.upper())


def peer_map():
    """Sector-derived peer lists (data/peer-map.json), reloaded when the file changes."""
    try:
        mtime = os.path.getmtime(_PEER_MAP_PATH)
    except OSError:
        return {}
    if mtime != _peer_map["mtime"]:
        try:
            with open(_PEER_MAP_PATH, encoding="utf-8") as fh:
                _peer_map["data"] = json.load(fh)
            _peer_map["mtime"] = mtime
        except (OSError, ValueError):
            return {}
    return _peer_map["data"]


def peers_for(symbol):
    """Peer tickers for a symbol: curated list first, else the sector-derived map."""
    symbol = symbol.upper()
    if symbol in PEERS:
        return list(PEERS[symbol])
    return list(peer_map().get(symbol, []))


def _fmt_short(value):
    if value is None:
        return None
    if abs(value) >= 1e12:
        return f"${value / 1e12:.1f}T"
    if abs(value) >= 1e9:
        return f"${value / 1e9:.1f}B"
    if abs(value) >= 1e6:
        return f"${value / 1e6:.0f}M"
    return f"${value:,.0f}"


def _median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def pros_cons(metrics, annual, ratios, peers):
    """Strengths and watchouts computed from the filing data — nothing here
    is editorial. Each item cites the figure it rests on; anything the data
    cannot support is simply left out."""
    pros, cons = [], []
    m = metrics or {}
    roe, roce = m.get("roe"), m.get("roce")
    growth, pe = m.get("growth"), m.get("pe")
    de = m.get("debt_equity")
    latest = annual[-1] if annual else {}
    prior = annual[-2] if len(annual) >= 2 else {}
    latest_ratio = ratios[-1] if ratios else {}
    prior_ratio = ratios[-2] if len(ratios) >= 2 else {}
    peer_pes = [p.get("pe") for p in (peers or [])]
    peer_pe_median = _median(peer_pes)

    if roe is not None and roe >= 0.20:
        pros.append(f"Return on equity of {roe:.1%} on trailing earnings.")
    if growth is not None and growth >= 0.10:
        pros.append(f"Revenue grew {growth:.1%} over the last twelve months.")
    nm = latest_ratio.get("net_margin")
    if nm is not None and nm >= 0.15:
        pros.append(f"Net margin of {nm:.1%} in FY{latest.get('fy')} — profitable at scale.")
    if roce is not None and roce >= 0.15:
        pros.append(f"Return on capital employed of {roce:.1%}.")
    fcf, prev_fcf = latest.get("fcf"), prior.get("fcf")
    if fcf is not None and fcf > 0 and prev_fcf:
        if fcf > prev_fcf:
            pros.append(f"Free cash flow of {_fmt_short(fcf)} in FY{latest.get('fy')}, up from {_fmt_short(prev_fcf)} the year before.")
        else:
            pros.append(f"Free cash flow of {_fmt_short(fcf)} in FY{latest.get('fy')}.")
    if de is not None and de < 0.5:
        pros.append(f"Modest leverage — debt is {de:.2f}× equity.")
    div = latest.get("dividends")
    if div:
        pros.append(f"Paid {_fmt_short(div)} in dividends in FY{latest.get('fy')}.")
    if pe is not None and peer_pe_median:
        if pe < peer_pe_median * 0.85:
            pros.append(f"Trades at {pe:.1f}× earnings, below the peer median of {peer_pe_median:.1f}×.")
    revs = [r.get("revenue") for r in annual if r.get("revenue")]
    if len(revs) >= 5 and revs[0] and revs[-1] and revs[-1] > 0 and revs[0] > 0:
        cagr = (revs[-1] / revs[0]) ** (1 / (len(revs) - 1)) - 1
        if cagr >= 0.08:
            pros.append(f"Revenue compounded at {cagr:.1%} a year over the last {len(revs) - 1} years.")
    cr = latest_ratio.get("current_ratio")
    if cr is not None and cr >= 1.5:
        pros.append(f"Current ratio of {cr:.2f} — short-term liquidity is comfortable.")

    if growth is not None and growth < 0:
        cons.append(f"Revenue fell {abs(growth):.1%} over the last twelve months.")
    if roe is not None and roe < 0.10:
        if roe < 0:
            cons.append(f"Return on equity was negative at {roe:.1%} on trailing earnings.")
        else:
            cons.append(f"Return on equity of {roe:.1%} is below 10%.")
    if nm is not None and nm < 0.05:
        cons.append(f"Net margin of {nm:.1%} in FY{latest.get('fy')} is thin.")
    if de is not None and de > 1.5:
        cons.append(f"Leverage is high — debt is {de:.2f}× equity.")
    if fcf is not None and fcf < 0:
        cons.append(f"Free cash flow was negative in FY{latest.get('fy')}.")
    elif fcf is not None and prev_fcf and fcf < prev_fcf * 0.8:
        cons.append(f"Free cash flow fell from {_fmt_short(prev_fcf)} to {_fmt_short(fcf)} in FY{latest.get('fy')}.")
    if pe is not None and peer_pe_median and pe > peer_pe_median * 1.25:
        cons.append(f"Trades at {pe:.1f}× earnings, above the peer median of {peer_pe_median:.1f}×.")
    ni, prev_ni = latest.get("net_income"), prior.get("net_income")
    if ni is not None and prev_ni and ni < prev_ni * 0.9:
        cons.append(f"Net income fell from {_fmt_short(prev_ni)} to {_fmt_short(ni)} in FY{latest.get('fy')}.")
    if cr is not None and cr < 1.0:
        cons.append(f"Current ratio of {cr:.2f} — current liabilities exceed current assets.")
    opm, prev_opm = latest_ratio.get("opm"), prior_ratio.get("opm")
    if opm is not None and prev_opm is not None and opm < prev_opm - 0.03:
        cons.append(f"Operating margin narrowed to {opm:.1%} in FY{latest.get('fy')}.")
    return {"pros": pros[:3], "cons": cons[:3]}


_tickers = {"at": 0, "data": {}}
_facts_cache = {}
_price_cache = {}


def _get_json(url):
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=10) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return json.loads(raw)


def tickers():
    """ticker -> (cik, title), cached a day."""
    if time.time() - _tickers["at"] > 86400:
        data = _get_json(TICKERS_URL)
        _tickers["data"] = {v["ticker"]: (v["cik_str"], v["title"]) for v in data.values()}
        _tickers["at"] = time.time()
    return _tickers["data"]


def company_name(symbol):
    entry = tickers().get(symbol.upper())
    return entry[1] if entry else symbol.upper()


def facts(symbol):
    """Parsed companyfacts JSON for a ticker, cached an hour.

    The cache is bounded (16 entries): a parsed facts file can be tens of
    megabytes in memory, and a build over ~500 tickers would otherwise
    exhaust RAM by holding them all. Eviction is FIFO — the working set for
    one company's financials (itself + ~10 peers) fits comfortably.
    """
    symbol = symbol.upper()
    entry = _facts_cache.get(symbol)
    if entry and time.time() - entry[0] < 3600:
        return entry[1]
    found = tickers().get(symbol)
    if not found:
        raise ValueError(f"No SEC filings for {symbol}")
    data = _get_json(FACTS_URL.format(str(found[0]).zfill(10)))
    while len(_facts_cache) >= 16:
        _facts_cache.pop(next(iter(_facts_cache)))
    _facts_cache[symbol] = (time.time(), data)
    return data


def live_price(symbol):
    """Current price + daily change % from Yahoo's public chart API.

    Cached 60 seconds in-process so a build that asks for the same symbol
    repeatedly (table, fundamentals, financials, peer warm-up) does not
    hammer Yahoo with duplicate calls.
    """
    symbol = symbol.upper()
    cached = _price_cache.get(symbol)
    if cached and time.time() - cached[0] < 60:
        return cached[1]
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=1d&interval=1m"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Northstar Screener)"})
    with urllib.request.urlopen(request, timeout=6) as response:
        meta = json.load(response)["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice", meta.get("previousClose"))
    previous = meta.get("chartPreviousClose", meta.get("previousClose"))
    change = ((price - previous) / previous) * 100 if price and previous else None
    result = {"price": price, "changePercent": change}
    _price_cache[symbol] = (time.time(), result)
    return result


def _points(facts, concept):
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return []
    points = []
    for arr in units.values():
        for p in arr:
            if p.get("val") is None or not p.get("end"):
                continue
            points.append({
                "end": p["end"], "fy": p.get("fy"), "fp": p.get("fp"),
                "form": p.get("form"), "frame": p.get("frame", ""),
                "val": p["val"], "filed": p.get("filed", ""), "accn": p.get("accn", ""),
            })
    return points


def _is_quarter_frame(point):
    # The frame is the CALENDAR quarter, so a fiscal Q1 can carry a Q4 frame
    # (Apple's fiscal Q1 ends in December). Any 3-month frame counts; YTD
    # frames and frameless points are the year-to-date values, not quarters.
    frame = point["frame"]
    return bool(frame) and "YTD" not in frame and frame.endswith(("Q1", "Q2", "Q3", "Q4"))


def _quarterly(facts, concept):
    """One 10-Q point per quarter-end.

    The same quarter can appear several times in the facts (the filing year
    `fy` is inconsistent even within one filing, and a 10-Q carries both the
    3-month figure and the year-to-date figure), so the end date is the key,
    not (fy, fp). Per end date, a framed quarter point (the 3-month figure)
    beats a frameless one, and among frameless points the smallest by
    magnitude wins, since the 3-month figure is smaller than the YTD one.
    """
    by_end = {}
    for p in _points(facts, concept):
        if p["form"] != "10-Q" or p["fp"] not in ("Q1", "Q2", "Q3"):
            continue
        key = p["end"]
        framed = _is_quarter_frame(p)
        current = by_end.get(key)
        if current is None:
            by_end[key] = (framed, p)
        elif framed and not current[0]:
            by_end[key] = (True, p)
        elif framed == current[0]:
            if framed:
                by_end[key] = (True, p)
            elif abs(p["val"]) < abs(current[1]["val"]):
                by_end[key] = (False, p)
    return sorted([v[1] for v in by_end.values()], key=lambda p: p["end"])


def _annual(facts, concept):
    """One 10-K FY point per fiscal year-end (latest filing wins on restatement).

    A 10-K also restates quarterly figures with fp FY, so the ends include
    quarter-ends; a fiscal year is ~365 days, so keeping points at least
    300 days apart leaves only the true year-ends.
    """
    by_end = {}
    for p in _points(facts, concept):
        if p["form"] != "10-K" or p["fp"] != "FY":
            continue
        key = p["end"]
        if key not in by_end or (p["filed"], p["accn"]) > (by_end[key]["filed"], by_end[key]["accn"]):
            by_end[key] = p
    # Anchor on the latest end (a true year-end: quarter-ends inside the same
    # filing are always earlier) and work backwards, keeping points at least
    # 300 days apart, so only true year-ends survive.
    out = []
    last_kept = None
    for p in sorted(by_end.values(), key=lambda p: p["end"], reverse=True):
        if last_kept is None or _days_between(p["end"], last_kept) >= 300:
            out.append(p)
            last_kept = p["end"]
    return sorted(out, key=lambda p: p["end"])


def _days_between(start, end):
    from datetime import date
    a = date.fromisoformat(start[:10])
    b = date.fromisoformat(end[:10])
    return (b - a).days


def _annual_concept(facts, concepts, flow=True, prefer=None):
    """Annual points for the concept with the most recent coverage.

    If `prefer` is given and its coverage is as current as the best
    (latest end within 45 days), its points win: for net income this
    prefers income attributable to common shareholders over total
    income, which is the figure that belongs to the share price (a
    filer with large noncontrolling interests would otherwise show
    total income divided by common shares only — a wrong EPS).
    """
    by_concept = {}
    for concept in concepts:
        points = _annual(facts, concept) or _annual_derived(facts, concept, flow)
        if points:
            by_concept[concept] = points
    if not by_concept:
        return []
    best = max(by_concept.values(), key=lambda pts: pts[-1]["end"])
    if prefer in by_concept:
        pref = by_concept[prefer]
        if _days_between(pref[-1]["end"], best[-1]["end"]) <= 45:
            return pref
    return best


def _annual_derived(facts, concept, flow):
    """Annual figures built from quarterly points, for filers with no 10-K
    history under this concept (e.g. a newly formed registrant).

    Flows (revenue, income, cash flow) sum the four quarters of a year and
    need all four; stocks (assets, equity, debt, cash) take the latest
    quarter-end point of the year, which is the year-end balance.
    """
    by_year = {}
    for q in _quarterly(facts, concept):
        by_year.setdefault(int(q["end"][:4]), []).append(q)
    out = []
    for year in sorted(by_year):
        pts = by_year[year]
        if flow:
            if len(pts) < 4:
                continue
            out.append({"end": f"{year}-12-31", "val": sum(p["val"] for p in pts),
                        "filed": "", "accn": "", "fy": year, "fp": "FY", "form": "10-K", "frame": ""})
        else:
            latest = max(pts, key=lambda p: p["end"])
            out.append({"end": latest["end"], "val": latest["val"],
                        "filed": "", "accn": "", "fy": year, "fp": "FY", "form": "10-K", "frame": ""})
    return out


def _quarterly_concept(facts, concepts, prefer=None):
    by_concept = {}
    for concept in concepts:
        points = _quarterly(facts, concept)
        if points:
            by_concept[concept] = points
    if not by_concept:
        return []
    best = max(by_concept.values(), key=lambda pts: pts[-1]["end"])
    if prefer in by_concept:
        pref = by_concept[prefer]
        if _days_between(pref[-1]["end"], best[-1]["end"]) <= 45:
            return pref
    return best


def _quarterly_series(facts, concept, fallbacks=(), prefer=None):
    """Chronological quarters including Q4 derived as FY minus Q1-Q3."""
    annual = _annual_concept(facts, [concept, *fallbacks], prefer=prefer)
    quarters = _quarterly_concept(facts, [concept, *fallbacks], prefer=prefer)
    out = []
    prev_end = None
    for a in annual:
        qs = [q for q in quarters if (prev_end is None or q["end"] > prev_end) and q["end"] <= a["end"]]
        for q in qs:
            out.append({"fy": int(a["end"][:4]), "fp": q["fp"], "end": q["end"], "val": q["val"], "derived": False})
        if len(qs) == 3:
            out.append({"fy": int(a["end"][:4]), "fp": "Q4", "end": None,
                        "val": a["val"] - sum(q["val"] for q in qs), "derived": True})
        prev_end = a["end"]
    last_annual_year = int(annual[-1]["end"][:4]) if annual else 0
    for q in quarters:
        if prev_end is None or q["end"] > prev_end:
            if annual:
                fy = last_annual_year + 1
            else:
                # No 10-K history: infer the fiscal year from the quarter end
                # (an Oct-Dec quarter belongs to the next fiscal year).
                fy = int(q["end"][:4]) + (1 if int(q["end"][5:7]) >= 10 else 0)
            out.append({"fy": fy, "fp": q["fp"], "end": q["end"], "val": q["val"], "derived": False})
    return out


def _ttm(series, n=4):
    if len(series) < n:
        return None
    return sum(p["val"] for p in series[-n:])


def _shares_points(facts):
    """Shares outstanding: the cover-page figure (dei) is current for every
    filer; the us-gaap concept goes stale for some (Citi's stops in 2010)."""
    pts = []
    dei = facts.get("facts", {}).get("dei", {}).get("EntityCommonStockSharesOutstanding", {})
    for arr in dei.get("units", {}).values():
        for p in arr:
            if p.get("val") is not None and p.get("end"):
                pts.append({"end": p["end"], "val": p["val"]})
    pts += [{"end": p["end"], "val": p["val"]} for p in _points(facts, "CommonStockSharesOutstanding")]
    return pts


def _shares_by_end(facts):
    by_year = {}
    for p in _shares_points(facts):
        year = int(p["end"][:4])
        if year not in by_year or p["end"] > by_year[year]["end"]:
            by_year[year] = p
    return {p["end"]: p["val"] for p in by_year.values()}


def _latest_weighted_shares(facts):
    """Weighted-average shares from the latest 10-K (the EPS denominator).

    Reported EPS is net income divided by this figure, so it is the
    consistent choice for P/E — and unlike the cover-page figure it is
    reported by virtually every filer, every year.
    """
    from datetime import date
    pts = _annual_concept(facts, ["WeightedAverageNumberOfSharesOutstandingBasic"], flow=False)
    if not pts:
        return None
    latest = pts[-1]
    if (date.today() - date.fromisoformat(latest["end"][:10])).days > 730:
        return None
    return latest["val"]


def _latest_shares(facts):
    """Most recent shares outstanding — but only a CURRENT count.

    The cover-page figure (dei) goes stale for many filers — Visa's stops
    in 2010, Nike's in 2015, Berkshire's in 2011 — and a share count years
    out of date mixed with today's price produces a nonsense market cap
    and P/E (Berkshire showed P/E 0.007, Fox $2B of EPS). So: a cover-page
    count older than two years is ignored, and the weighted-average shares
    from the latest 10-K are used instead. If neither is current, the
    share-derived figures render as a dash instead of a wrong number.
    """
    from datetime import date
    today = date.today()
    points = [p for p in _shares_points(facts)
              if (today - date.fromisoformat(p["end"][:10])).days <= 730]
    if points:
        return max(points, key=lambda p: p["end"])["val"]
    return _latest_weighted_shares(facts)


def _debt_by_end(facts):
    points = _annual_concept(facts, ["Debt"], flow=False)
    if points:
        return {p["end"]: p["val"] for p in points}
    lt = {p["end"]: p["val"] for p in _annual(facts, "LongTermDebt")}
    ltc = {p["end"]: p["val"] for p in _annual(facts, "LongTermDebtCurrent")}
    ltl = {p["end"]: p["val"] for p in _annual(facts, "LongTermDebtAndCapitalLeaseObligations")}
    st = {p["end"]: p["val"] for p in _annual(facts, "ShortTermBorrowings")}
    ends = set(lt) | set(ltc) | set(ltl) | set(st)
    return {end: lt.get(end, 0) + ltc.get(end, 0) + ltl.get(end, 0) + st.get(end, 0) for end in ends}


def _year_map(points):
    return {int(p["end"][:4]): p["val"] for p in points}


def metrics(symbol, price=None):
    """Live valuation + return metrics for one ticker, from filings + price."""
    data = facts(symbol)
    if price is None:
        price = live_price(symbol)["price"]
    shares = _latest_shares(data)
    revenue_q = _quarterly_series(data, "Revenues", ("SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenuesNetOfInterestExpense"))
    income_q = _quarterly_series(data, "NetIncomeLoss", ("ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"), prefer="NetIncomeLossAvailableToCommonStockholdersBasic")
    ebit_q = _quarterly_series(data, "OperatingIncomeLoss")
    equity = _year_map(_annual_concept(data, ["StockholdersEquity"], flow=False))
    debt = _year_map(_annual_concept(data, ["Debt"], flow=False) or []) or {int(k[:4]): v for k, v in _debt_by_end(data).items()}
    latest_year = max(equity) if equity else None
    latest_equity = equity.get(latest_year) if latest_year else None
    latest_debt = debt.get(latest_year) if latest_year else None

    ttm_revenue = _ttm(revenue_q)
    ttm_income = _ttm(income_q)
    ttm_ebit = _ttm(ebit_q)
    prior_ttm_revenue = _ttm(revenue_q[:-4]) if len(revenue_q) >= 8 else None

    eps_ttm = (ttm_income / shares) if ttm_income and shares else None
    pe = (price / eps_ttm) if price and eps_ttm and eps_ttm > 0 else None
    if pe is not None and pe < 0.1:
        # A P/E under 0.1 means the share count and the price do not belong
        # to the same share class (see _latest_shares): the share-derived
        # figures are not credible, so they render as unknown rather than
        # as a nonsense number.
        return {
            "symbol": symbol.upper(),
            "name": company_name(symbol),
            "price": price,
            "cap": None,
            "pe": None,
            "eps_ttm": None,
            "roe": (ttm_income / latest_equity) if ttm_income and latest_equity else None,
            "roce": (ttm_ebit / (latest_equity + latest_debt)) if ttm_ebit and latest_equity and latest_debt is not None else None,
            "growth": ((ttm_revenue / prior_ttm_revenue) - 1) if ttm_revenue and prior_ttm_revenue else None,
            "debt_equity": (latest_debt / latest_equity) if latest_debt is not None and latest_equity else None,
            "book_value_per_share": None,
        }
    return {
        "symbol": symbol.upper(),
        "name": company_name(symbol),
        "price": price,
        "cap": (price * shares) if price and shares else None,
        "pe": pe,
        "eps_ttm": eps_ttm,
        "roe": (ttm_income / latest_equity) if ttm_income and latest_equity else None,
        "roce": (ttm_ebit / (latest_equity + latest_debt)) if ttm_ebit and latest_equity and latest_debt is not None else None,
        "growth": ((ttm_revenue / prior_ttm_revenue) - 1) if ttm_revenue and prior_ttm_revenue else None,
        "debt_equity": (latest_debt / latest_equity) if latest_debt is not None and latest_equity else None,
        "book_value_per_share": (latest_equity / shares) if latest_equity and shares else None,
    }


def statements(symbol):
    """Ten years of annuals, twelve quarters, and ten years of ratios."""
    data = facts(symbol)

    def annual(concepts, flow=True, prefer=None):
        return _year_map(_annual_concept(data, concepts, flow=flow, prefer=prefer))

    revenue = annual(["Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenuesNetOfInterestExpense"])
    cogs = annual(["CostOfRevenue", "CostOfGoodsAndServicesSold"])
    op_income = annual(["OperatingIncomeLoss"])
    net_income = annual(["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"], prefer="NetIncomeLossAvailableToCommonStockholdersBasic")
    assets = annual(["Assets"], flow=False)
    equity = annual(["StockholdersEquity"], flow=False)
    debt = {int(k[:4]): v for k, v in _debt_by_end(data).items()}
    cash = annual(["CashAndCashEquivalentsAtCarryingValue"], flow=False)
    cfo = annual(["NetCashProvidedByOperatingActivities", "NetCashProvidedByUsedInOperatingActivities"])
    capex = annual(["PaymentsToAcquirePropertyPlantAndEquipment"])
    dividends = annual(["PaymentsOfDividends"])
    curr_assets = annual(["AssetsCurrent"], flow=False)
    curr_liab = annual(["LiabilitiesCurrent"], flow=False)
    receivables = annual(["AccountsReceivableNetCurrent"], flow=False)
    inventory = annual(["InventoryNet"], flow=False)
    shares = {int(k[:4]): v for k, v in _shares_by_end(data).items()}

    years = sorted(set(revenue) | set(net_income))[-10:]
    annual_rows = []
    ratio_rows = []
    for fy in years:
        rev = revenue.get(fy)
        ni = net_income.get(fy)
        sh = shares.get(fy)
        eq = equity.get(fy)
        db = debt.get(fy)
        ebit = op_income.get(fy)
        annual_rows.append({
            "fy": fy,
            "revenue": rev,
            "cogs": cogs.get(fy),
            "operating_income": ebit,
            "net_income": ni,
            "eps": (ni / sh) if ni is not None and sh else None,
            "assets": assets.get(fy),
            "equity": eq,
            "debt": db,
            "cash": cash.get(fy),
            "cfo": cfo.get(fy),
            "capex": capex.get(fy),
            "fcf": ((cfo.get(fy) or 0) - (capex.get(fy) or 0)) if cfo.get(fy) is not None and capex.get(fy) is not None else None,
            "dividends": dividends.get(fy),
        })
        ratio_rows.append({
            "fy": fy,
            "opm": (ebit / rev) if ebit is not None and rev else None,
            "net_margin": (ni / rev) if ni is not None and rev else None,
            "roe": (ni / eq) if ni is not None and eq else None,
            "roce": (ebit / (eq + db)) if ebit is not None and eq and db is not None else None,
            "debt_equity": (db / eq) if db is not None and eq else None,
            "current_ratio": (curr_assets.get(fy) / curr_liab.get(fy)) if curr_assets.get(fy) and curr_liab.get(fy) else None,
            "asset_turnover": (rev / assets.get(fy)) if rev and assets.get(fy) else None,
            "debtor_days": (receivables.get(fy) / rev * 365) if receivables.get(fy) is not None and rev else None,
            "inventory_days": (inventory.get(fy) / cogs.get(fy) * 365) if inventory.get(fy) is not None and cogs.get(fy) else None,
        })

    quarters = []
    rev_q = _quarterly_series(data, "Revenues", ("SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenuesNetOfInterestExpense"))
    op_q = {(p["fy"], p["fp"]): p["val"] for p in _quarterly_series(data, "OperatingIncomeLoss")}
    ni_q = {(p["fy"], p["fp"]): p["val"] for p in _quarterly_series(data, "NetIncomeLoss", ("ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"), prefer="NetIncomeLossAvailableToCommonStockholdersBasic")}
    latest_shares = _latest_shares(data)
    for p in rev_q[-12:]:
        ni = ni_q.get((p["fy"], p["fp"]))
        quarters.append({
            "label": f"{p['fp']} FY{p['fy']}",
            "end": p["end"],
            "revenue": p["val"],
            "operating_income": op_q.get((p["fy"], p["fp"])),
            "net_income": ni,
            "eps": (ni / latest_shares) if ni is not None and latest_shares else None,
        })

    return {"annual": annual_rows, "quarterly": quarters, "ratios": ratio_rows}
