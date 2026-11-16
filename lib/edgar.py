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
PEERS = {
    "AAPL": ["MSFT", "GOOGL", "NVDA"],
    "MSFT": ["AAPL", "GOOGL", "NVDA"],
    "NVDA": ["AMD", "MSFT", "AVGO"],
    "GOOGL": ["MSFT", "META", "AAPL"],
    "LLY": ["JNJ", "PFE", "MRK", "NVO"],
    "JPM": ["BAC", "WFC", "GS", "C"],
    "XOM": ["CVX", "COP", "SLB"],
}

_tickers = {"at": 0, "data": {}}
_facts_cache = {}


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
    """Parsed companyfacts JSON for a ticker, cached an hour."""
    symbol = symbol.upper()
    entry = _facts_cache.get(symbol)
    if entry and time.time() - entry[0] < 3600:
        return entry[1]
    found = tickers().get(symbol)
    if not found:
        raise ValueError(f"No SEC filings for {symbol}")
    data = _get_json(FACTS_URL.format(str(found[0]).zfill(10)))
    _facts_cache[symbol] = (time.time(), data)
    return data


def live_price(symbol):
    """Current price + daily change % from Yahoo's public chart API."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=1d&interval=1m"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Northstar Screener)"})
    with urllib.request.urlopen(request, timeout=6) as response:
        meta = json.load(response)["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice", meta.get("previousClose"))
    previous = meta.get("chartPreviousClose", meta.get("previousClose"))
    change = ((price - previous) / previous) * 100 if price and previous else None
    return {"price": price, "changePercent": change}


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


def _annual_concept(facts, concepts, flow=True):
    """Annual points for the concept with the most recent coverage."""
    best = []
    for concept in concepts:
        points = _annual(facts, concept) or _annual_derived(facts, concept, flow)
        if points and (not best or points[-1]["end"] > best[-1]["end"]):
            best = points
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


def _quarterly_concept(facts, concepts):
    best = []
    for concept in concepts:
        points = _quarterly(facts, concept)
        if points and (not best or points[-1]["end"] > best[-1]["end"]):
            best = points
    return best


def _quarterly_series(facts, concept, fallbacks=()):
    """Chronological quarters including Q4 derived as FY minus Q1-Q3."""
    annual = _annual_concept(facts, [concept, *fallbacks])
    quarters = _quarterly_concept(facts, [concept, *fallbacks])
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


def _latest_shares(facts):
    points = _shares_points(facts)
    if not points:
        return None
    return max(points, key=lambda p: p["end"])["val"]


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
    income_q = _quarterly_series(data, "NetIncomeLoss", ("NetIncomeLossAvailableToCommonStockholdersBasic",))
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
    return {
        "symbol": symbol.upper(),
        "name": company_name(symbol),
        "price": price,
        "cap": (price * shares) if price and shares else None,
        "pe": (price / eps_ttm) if price and eps_ttm and eps_ttm > 0 else None,
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

    def annual(concepts, flow=True):
        return _year_map(_annual_concept(data, concepts, flow=flow))

    revenue = annual(["Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenuesNetOfInterestExpense"])
    cogs = annual(["CostOfRevenue", "CostOfGoodsAndServicesSold"])
    op_income = annual(["OperatingIncomeLoss"])
    net_income = annual(["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"])
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
    ni_q = {(p["fy"], p["fp"]): p["val"] for p in _quarterly_series(data, "NetIncomeLoss", ("NetIncomeLossAvailableToCommonStockholdersBasic",))}
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
