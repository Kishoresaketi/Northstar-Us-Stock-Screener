#!/usr/bin/env python3
"""Regression tests for the fuller Screener.in remainder in lib/edgar.py:
the fuller P&L lines (expenses, other income, interest, depreciation,
profit before tax, tax), the dividends CommonStock fallback tag, and the
dividend yield / book value in metrics().

Run:  python3 tests/test_edgar_fuller.py
  or: python3 -m unittest discover -s tests -v

No network access: statements() and metrics() run against a synthetic
companyfacts fixture via a monkeypatched edgar.facts (and company_name
for metrics, which would otherwise fetch the SEC tickers list).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lib.edgar as edgar


def facts_for(points_by_concept, dei_shares=None):
    """Minimal companyfacts dict: {concept: [points]}. Each point needs
    end/form/fp/val; frame/filed/accn default sensibly."""
    facts = {"facts": {"us-gaap": {}}}
    for concept, points in points_by_concept.items():
        units = []
        for p in points:
            q = {"end": p["end"], "form": p["form"], "fp": p["fp"],
                 "val": p["val"], "frame": p.get("frame", ""),
                 "filed": p.get("filed", "2025-01-01"), "accn": p.get("accn", "x")}
            units.append(q)
        facts["facts"]["us-gaap"][concept] = {"units": {"USD": units}}
    if dei_shares is not None:
        facts["facts"]["dei"] = {"EntityCommonStockSharesOutstanding": {
            "units": {"shares": [
                {"end": e, "val": v, "form": "10-K", "fp": "FY"}
                for e, v in dei_shares]}}}
    return facts


def q10(end, fp, val, frame):
    return {"end": end, "form": "10-Q", "fp": fp, "val": val, "frame": frame}


def k10(end, val):
    return {"end": end, "form": "10-K", "fp": "FY", "val": val}


PBT = "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"


# Calendar fiscal year. FY2024 annuals and Q1-Q3; FY2025 annuals and
# Q1-Q3. Q4 values are derived by the pipeline (flows: FY minus the
# first three quarters; stocks: the annual year-end balance).
# The numbers are internally consistent: PBT = operating income +
# other income - interest, and tax is ~20% of PBT.
def fixture(dividends_concept="PaymentsOfDividends", pbt_concept=PBT):
    pts = {
        "Revenues": [
            k10("2024-12-31", 900), k10("2025-12-31", 1000),
            q10("2024-03-31", "Q1", 210, "CY2024Q1"),
            q10("2024-06-30", "Q2", 220, "CY2024Q2"),
            q10("2024-09-30", "Q3", 230, "CY2024Q3"),
            q10("2025-03-31", "Q1", 240, "CY2025Q1"),
            q10("2025-06-30", "Q2", 250, "CY2025Q2"),
            q10("2025-09-30", "Q3", 260, "CY2025Q3"),
        ],
        "CostOfRevenue": [
            k10("2024-12-31", 540), k10("2025-12-31", 600),
            q10("2024-03-31", "Q1", 126, "CY2024Q1"),
            q10("2024-06-30", "Q2", 132, "CY2024Q2"),
            q10("2024-09-30", "Q3", 138, "CY2024Q3"),
            q10("2025-03-31", "Q1", 144, "CY2025Q1"),
            q10("2025-06-30", "Q2", 150, "CY2025Q2"),
            q10("2025-09-30", "Q3", 156, "CY2025Q3"),
        ],
        "OperatingIncomeLoss": [
            k10("2024-12-31", 180), k10("2025-12-31", 200),
            q10("2024-03-31", "Q1", 42, "CY2024Q1"),
            q10("2024-06-30", "Q2", 44, "CY2024Q2"),
            q10("2024-09-30", "Q3", 46, "CY2024Q3"),
            q10("2025-03-31", "Q1", 48, "CY2025Q1"),
            q10("2025-06-30", "Q2", 50, "CY2025Q2"),
            q10("2025-09-30", "Q3", 52, "CY2025Q3"),
        ],
        "NetIncomeLoss": [
            k10("2024-12-31", 135), k10("2025-12-31", 150),
            q10("2024-03-31", "Q1", 31, "CY2024Q1"),
            q10("2024-06-30", "Q2", 33, "CY2024Q2"),
            q10("2024-09-30", "Q3", 34, "CY2024Q3"),
            q10("2025-03-31", "Q1", 36, "CY2025Q1"),
            q10("2025-06-30", "Q2", 38, "CY2025Q2"),
            q10("2025-09-30", "Q3", 39, "CY2025Q3"),
        ],
        "NonoperatingIncomeExpense": [
            k10("2024-12-31", 18), k10("2025-12-31", 20),
            q10("2024-03-31", "Q1", 4, "CY2024Q1"),
            q10("2024-06-30", "Q2", 5, "CY2024Q2"),
            q10("2024-09-30", "Q3", 6, "CY2024Q3"),
            q10("2025-03-31", "Q1", 5, "CY2025Q1"),
            q10("2025-06-30", "Q2", 6, "CY2025Q2"),
            q10("2025-09-30", "Q3", 7, "CY2025Q3"),
        ],
        "InterestExpense": [
            k10("2024-12-31", 9), k10("2025-12-31", 10),
            q10("2024-03-31", "Q1", 2, "CY2024Q1"),
            q10("2024-06-30", "Q2", 2, "CY2024Q2"),
            q10("2024-09-30", "Q3", 3, "CY2024Q3"),
            q10("2025-03-31", "Q1", 2, "CY2025Q1"),
            q10("2025-06-30", "Q2", 3, "CY2025Q2"),
            q10("2025-09-30", "Q3", 3, "CY2025Q3"),
        ],
        pbt_concept: [
            k10("2024-12-31", 189), k10("2025-12-31", 210),
            q10("2024-03-31", "Q1", 44, "CY2024Q1"),
            q10("2024-06-30", "Q2", 47, "CY2024Q2"),
            q10("2024-09-30", "Q3", 49, "CY2024Q3"),
            q10("2025-03-31", "Q1", 51, "CY2025Q1"),
            q10("2025-06-30", "Q2", 53, "CY2025Q2"),
            q10("2025-09-30", "Q3", 56, "CY2025Q3"),
        ],
        "IncomeTaxExpenseBenefit": [
            k10("2024-12-31", 38), k10("2025-12-31", 42),
            q10("2024-03-31", "Q1", 9, "CY2024Q1"),
            q10("2024-06-30", "Q2", 9, "CY2024Q2"),
            q10("2024-09-30", "Q3", 10, "CY2024Q3"),
            q10("2025-03-31", "Q1", 10, "CY2025Q1"),
            q10("2025-06-30", "Q2", 11, "CY2025Q2"),
            q10("2025-09-30", "Q3", 11, "CY2025Q3"),
        ],
        # Depreciation is a cash-flow-statement line: 10-Q figures are
        # year-to-date, so the quarter's own value is the difference.
        "DepreciationDepletionAndAmortization": [
            k10("2024-12-31", 27), k10("2025-12-31", 30),
            q10("2024-03-31", "Q1", 6, ""),
            q10("2024-06-30", "Q2", 13, ""),
            q10("2024-09-30", "Q3", 20, ""),
            q10("2025-03-31", "Q1", 7, ""),
            q10("2025-06-30", "Q2", 15, ""),
            q10("2025-09-30", "Q3", 22, ""),
        ],
        "NetCashProvidedByOperatingActivities": [
            k10("2024-12-31", 220), k10("2025-12-31", 250),
            q10("2024-03-31", "Q1", 55, "CY2024Q1"),
            q10("2024-06-30", "Q2", 115, "CY2024Q2"),
            q10("2024-09-30", "Q3", 175, "CY2024Q3"),
            q10("2025-03-31", "Q1", 60, "CY2025Q1"),
            q10("2025-06-30", "Q2", 130, "CY2025Q2"),
            q10("2025-09-30", "Q3", 190, "CY2025Q3"),
        ],
        "PaymentsToAcquirePropertyPlantAndEquipment": [
            k10("2024-12-31", 45), k10("2025-12-31", 50),
            q10("2024-03-31", "Q1", 10, "CY2024Q1"),
            q10("2024-06-30", "Q2", 22, "CY2024Q2"),
            q10("2024-09-30", "Q3", 33, "CY2024Q3"),
            q10("2025-03-31", "Q1", 12, "CY2025Q1"),
            q10("2025-06-30", "Q2", 25, "CY2025Q2"),
            q10("2025-09-30", "Q3", 38, "CY2025Q3"),
        ],
        dividends_concept: [
            k10("2024-12-31", 25), k10("2025-12-31", 30),
            q10("2024-03-31", "Q1", 6, "CY2024Q1"),
            q10("2024-06-30", "Q2", 12, "CY2024Q2"),
            q10("2024-09-30", "Q3", 18, "CY2024Q3"),
            q10("2025-03-31", "Q1", 7, "CY2025Q1"),
            q10("2025-06-30", "Q2", 15, "CY2025Q2"),
            q10("2025-09-30", "Q3", 22, "CY2025Q3"),
        ],
    }
    stocks = {
        "Assets": [1800, 2000, 1700, 1750, 1800, 1900, 1950, 2000],
        "StockholdersEquity": [900, 1000, 850, 875, 900, 950, 975, 1000],
        "Debt": [450, 500, 430, 440, 450, 480, 490, 500],
        "CashAndCashEquivalentsAtCarryingValue": [180, 200, 170, 175, 180, 190, 195, 200],
        "AssetsCurrent": [700, 800, 660, 680, 700, 760, 780, 800],
        "LiabilitiesCurrent": [350, 400, 330, 340, 350, 380, 390, 400],
        "AccountsReceivableNetCurrent": [90, 100, 85, 88, 90, 95, 98, 100],
        "InventoryNet": [100, 120, 95, 98, 100, 110, 115, 120],
        "AccountsPayableCurrent": [80, 90, 75, 78, 80, 85, 88, 90],
    }
    ends = [("2024-12-31", "10-K", "FY"), ("2025-12-31", "10-K", "FY"),
            ("2024-03-31", "10-Q", "Q1"), ("2024-06-30", "10-Q", "Q2"),
            ("2024-09-30", "10-Q", "Q3"), ("2025-03-31", "10-Q", "Q1"),
            ("2025-06-30", "10-Q", "Q2"), ("2025-09-30", "10-Q", "Q3")]
    for concept, vals in stocks.items():
        pts[concept] = [{"end": e, "form": f, "fp": fp, "val": v}
                        for (e, f, fp), v in zip(ends, vals)]
    return facts_for(pts, dei_shares=[("2024-12-31", 50), ("2025-12-31", 50)])


class TestFullerPLRows(unittest.TestCase):
    def setUp(self):
        self._orig_facts = edgar.facts
        self._orig_name = edgar.company_name

    def tearDown(self):
        edgar.facts = self._orig_facts
        edgar.company_name = self._orig_name

    def statements(self, **kw):
        edgar.facts = lambda symbol: fixture(**kw)
        return edgar.statements("TEST")

    def test_annual_fuller_rows(self):
        out = self.statements()
        row = next(r for r in out["annual"] if r["fy"] == 2025)
        self.assertEqual(row["expenses"], 1000 - 200)
        self.assertEqual(row["other_income"], 20)
        self.assertEqual(row["interest"], 10)
        self.assertEqual(row["depreciation"], 30)
        self.assertEqual(row["pbt"], 210)
        self.assertEqual(row["tax"], 42)
        row24 = next(r for r in out["annual"] if r["fy"] == 2024)
        self.assertEqual(row24["expenses"], 900 - 180)
        self.assertEqual(row24["pbt"], 189)
        self.assertEqual(row24["tax"], 38)

    def test_quarterly_fuller_rows(self):
        out = self.statements()
        q3 = next(q for q in out["quarterly"] if q["label"] == "Q3 FY2025")
        self.assertEqual(q3["expenses"], 260 - 52)
        self.assertEqual(q3["other_income"], 7)
        self.assertEqual(q3["interest"], 3)
        self.assertEqual(q3["pbt"], 56)
        self.assertEqual(q3["tax"], 11)
        # Depreciation is YTD in 10-Qs: Q3 is the difference, not the
        # cumulative 22.
        self.assertEqual(q3["depreciation"], 22 - 15)
        q2 = next(q for q in out["quarterly"] if q["label"] == "Q2 FY2025")
        self.assertEqual(q2["depreciation"], 15 - 7)
        # Q4 is derived as FY minus Q1-Q3 for every flow line.
        q4 = next(q for q in out["quarterly"] if q["label"] == "Q4 FY2025")
        self.assertEqual(q4["expenses"], 250 - 50)
        self.assertEqual(q4["other_income"], 2)
        self.assertEqual(q4["interest"], 2)
        self.assertEqual(q4["depreciation"], 30 - 22)
        self.assertEqual(q4["pbt"], 50)
        self.assertEqual(q4["tax"], 10)

    def test_quarterly_sums_match_annual(self):
        out = self.statements()
        for fy in (2024, 2025):
            ann = next(r for r in out["annual"] if r["fy"] == fy)
            qs = [q for q in out["quarterly"] if q["label"].endswith(f"FY{fy}")]
            self.assertEqual(len(qs), 4)
            for field in ("other_income", "interest", "pbt", "tax",
                          "depreciation", "expenses"):
                self.assertEqual(sum(q[field] for q in qs), ann[field],
                                 f"{field} FY{fy} quarters sum to annual")

    def test_expenses_null_without_operating_income(self):
        f = fixture()
        del f["facts"]["us-gaap"]["OperatingIncomeLoss"]
        edgar.facts = lambda symbol: f
        out = edgar.statements("TEST")
        row = next(r for r in out["annual"] if r["fy"] == 2025)
        self.assertIsNone(row["expenses"])
        q3 = next(q for q in out["quarterly"] if q["label"] == "Q3 FY2025")
        self.assertIsNone(q3["expenses"])
        # The other fuller lines are unaffected.
        self.assertEqual(row["pbt"], 210)
        self.assertEqual(q3["pbt"], 56)

    def test_pbt_fallback_tag(self):
        # Filers reporting only the older PBT tag still get PBT.
        out = self.statements(
            pbt_concept="IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments")
        row = next(r for r in out["annual"] if r["fy"] == 2025)
        self.assertEqual(row["pbt"], 210)
        q3 = next(q for q in out["quarterly"] if q["label"] == "Q3 FY2025")
        self.assertEqual(q3["pbt"], 56)

    def test_dividends_commonstock_fallback(self):
        # Filers reporting only PaymentsOfDividendsCommonStock
        # (Microsoft, Dow) still get dividends, annual and quarterly.
        out = self.statements(dividends_concept="PaymentsOfDividendsCommonStock")
        row = next(r for r in out["annual"] if r["fy"] == 2025)
        self.assertEqual(row["dividends"], 30)
        q3 = next(q for q in out["quarterly"] if q["label"] == "Q3 FY2025")
        self.assertEqual(q3["dividends"], 22 - 15)
        q4 = next(q for q in out["quarterly"] if q["label"] == "Q4 FY2025")
        self.assertEqual(q4["dividends"], 30 - 22)


class TestDividendYield(unittest.TestCase):
    def setUp(self):
        self._orig_facts = edgar.facts
        self._orig_name = edgar.company_name
        edgar.company_name = lambda symbol: "Test Corp"

    def tearDown(self):
        edgar.facts = self._orig_facts
        edgar.company_name = self._orig_name

    def metrics(self, **kw):
        edgar.facts = lambda symbol: fixture(**kw)
        return edgar.metrics("TEST", price=30)

    def test_dividend_yield_and_book_value(self):
        # Latest dividends 30 over 50 shares = $0.60 per share;
        # at a $30 price the yield is 2%. Book value is equity 1000
        # over 50 shares = $20.
        m = self.metrics()
        self.assertAlmostEqual(m["dividend_per_share"], 0.6)
        self.assertAlmostEqual(m["dividend_yield"], 0.02)
        self.assertAlmostEqual(m["book_value_per_share"], 20)

    def test_dividend_yield_commonstock_fallback(self):
        m = self.metrics(dividends_concept="PaymentsOfDividendsCommonStock")
        self.assertAlmostEqual(m["dividend_per_share"], 0.6)
        self.assertAlmostEqual(m["dividend_yield"], 0.02)

    def test_no_dividends_yield_none(self):
        f = fixture()
        del f["facts"]["us-gaap"]["PaymentsOfDividends"]
        edgar.facts = lambda symbol: f
        m = edgar.metrics("TEST", price=30)
        self.assertIsNone(m["dividend_per_share"])
        self.assertIsNone(m["dividend_yield"])
        # Book value does not depend on dividends.
        self.assertAlmostEqual(m["book_value_per_share"], 20)


if __name__ == "__main__":
    unittest.main()
