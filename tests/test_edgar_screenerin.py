#!/usr/bin/env python3
"""Regression tests for the Screener.in additions in lib/edgar.py:
accounts payable (annual + quarterly, including the plain
AccountsPayable fallback tag) and the three new ratios — days
payable, working capital days, and the cash conversion cycle.

Run:  python3 tests/test_edgar_screenerin.py
  or: python3 -m unittest discover -s tests -v

No network access: statements() runs against a synthetic
companyfacts fixture via a monkeypatched edgar.facts.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lib.edgar as edgar


def facts_for(points_by_concept):
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
    return facts


def q10(end, fp, val, frame):
    return {"end": end, "form": "10-Q", "fp": fp, "val": val, "frame": frame}


def k10(end, val):
    return {"end": end, "form": "10-K", "fp": "FY", "val": val}


# Calendar fiscal year. FY2024 annuals and Q1-Q3; FY2025 annuals and
# Q1-Q3. Q4 values are derived by the pipeline (flows: FY minus the
# first three quarters; stocks: the annual year-end balance).
def fixture(payables_concept="AccountsPayableCurrent"):
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
        "PaymentsOfDividends": [
            k10("2024-12-31", 25), k10("2025-12-31", 30),
            q10("2024-03-31", "Q1", 6, "CY2024Q1"),
            q10("2024-06-30", "Q2", 12, "CY2024Q2"),
            q10("2024-09-30", "Q3", 18, "CY2024Q3"),
            q10("2025-03-31", "Q1", 7, "CY2025Q1"),
            q10("2025-06-30", "Q2", 15, "CY2025Q2"),
            q10("2025-09-30", "Q3", 22, "CY2025Q3"),
        ],
    }
    # Point-in-time concepts: 10-K year-ends plus 10-Q quarter-ends.
    stocks = {
        "Assets": [1800, 2000, 1700, 1750, 1800, 1900, 1950, 2000],
        "StockholdersEquity": [900, 1000, 850, 875, 900, 950, 975, 1000],
        "Debt": [450, 500, 430, 440, 450, 480, 490, 500],
        "CashAndCashEquivalentsAtCarryingValue": [180, 200, 170, 175, 180, 190, 195, 200],
        "AssetsCurrent": [700, 800, 660, 680, 700, 760, 780, 800],
        "LiabilitiesCurrent": [350, 400, 330, 340, 350, 380, 390, 400],
        "AccountsReceivableNetCurrent": [90, 100, 85, 88, 90, 95, 98, 100],
        "InventoryNet": [100, 120, 95, 98, 100, 110, 115, 120],
        payables_concept: [80, 90, 75, 78, 80, 85, 88, 90],
    }
    ends = [("2024-12-31", "10-K", "FY"), ("2025-12-31", "10-K", "FY"),
            ("2024-03-31", "10-Q", "Q1"), ("2024-06-30", "10-Q", "Q2"),
            ("2024-09-30", "10-Q", "Q3"), ("2025-03-31", "10-Q", "Q1"),
            ("2025-06-30", "10-Q", "Q2"), ("2025-09-30", "10-Q", "Q3")]
    for concept, vals in stocks.items():
        pts[concept] = [{"end": e, "form": f, "fp": fp, "val": v}
                        for (e, f, fp), v in zip(ends, vals)]
    return facts_for(pts)


class TestPayablesAndNewRatios(unittest.TestCase):
    def setUp(self):
        self._orig_facts = edgar.facts

    def tearDown(self):
        edgar.facts = self._orig_facts

    def statements(self, concept="AccountsPayableCurrent"):
        edgar.facts = lambda symbol: fixture(concept)
        return edgar.statements("TEST")

    def test_annual_payables_and_ratios(self):
        out = self.statements()
        row = next(r for r in out["annual"] if r["fy"] == 2025)
        self.assertEqual(row["payables"], 90)
        ratio = next(r for r in out["ratios"] if r["fy"] == 2025)
        self.assertAlmostEqual(ratio["payable_days"], 90 / 600 * 365)
        self.assertAlmostEqual(ratio["working_capital_days"], (800 - 400) / 1000 * 365)
        self.assertAlmostEqual(ratio["debtor_days"], 100 / 1000 * 365)
        self.assertAlmostEqual(ratio["inventory_days"], 120 / 600 * 365)
        self.assertAlmostEqual(
            ratio["ccc"],
            ratio["debtor_days"] + ratio["inventory_days"] - ratio["payable_days"])

    def test_annual_ratios_fy2024(self):
        out = self.statements()
        ratio = next(r for r in out["ratios"] if r["fy"] == 2024)
        self.assertAlmostEqual(ratio["payable_days"], 80 / 540 * 365)
        self.assertAlmostEqual(ratio["working_capital_days"], (700 - 350) / 900 * 365)
        self.assertAlmostEqual(
            ratio["ccc"],
            ratio["debtor_days"] + ratio["inventory_days"] - ratio["payable_days"])

    def test_quarterly_payables_and_ratios(self):
        out = self.statements()
        q3 = next(q for q in out["quarterly"] if q["label"] == "Q3 FY2025")
        self.assertEqual(q3["payables"], 90)
        # TTM at Q3 FY2025: Q4 FY2024 + Q1-Q3 FY2025.
        ttm_rev = 240 + 240 + 250 + 260
        ttm_cogs = 144 + 144 + 150 + 156
        ratio = next(r for r in out["quarterly_ratios"] if r["label"] == "Q3 FY2025")
        self.assertAlmostEqual(ratio["payable_days"], 90 / ttm_cogs * 365)
        self.assertAlmostEqual(ratio["working_capital_days"], (800 - 400) / ttm_rev * 365)
        self.assertAlmostEqual(
            ratio["ccc"],
            ratio["debtor_days"] + ratio["inventory_days"] - ratio["payable_days"])
        # Q4 balances come from the annual year-end figure.
        q4 = next(q for q in out["quarterly"] if q["label"] == "Q4 FY2024")
        self.assertEqual(q4["payables"], 80)

    def test_payables_fallback_tag(self):
        # Filers reporting the plain AccountsPayable tag (no "Current")
        # still get payables and the ratios built from it.
        out = self.statements("AccountsPayable")
        row = next(r for r in out["annual"] if r["fy"] == 2025)
        self.assertEqual(row["payables"], 90)
        ratio = next(r for r in out["ratios"] if r["fy"] == 2025)
        self.assertAlmostEqual(ratio["payable_days"], 90 / 600 * 365)

    def test_missing_payables_is_null_not_zero(self):
        # A filer that reports no payables concept at all gets nulls,
        # never a zero that would read as "pays suppliers instantly".
        f = fixture()
        del f["facts"]["us-gaap"]["AccountsPayableCurrent"]
        edgar.facts = lambda symbol: f
        out = edgar.statements("TEST")
        row = next(r for r in out["annual"] if r["fy"] == 2025)
        self.assertIsNone(row["payables"])
        ratio = next(r for r in out["ratios"] if r["fy"] == 2025)
        self.assertIsNone(ratio["payable_days"])
        self.assertIsNone(ratio["ccc"])
        # Working capital days needs only currents + revenue, so it
        # still computes when payables are missing.
        self.assertAlmostEqual(ratio["working_capital_days"], (800 - 400) / 1000 * 365)


if __name__ == "__main__":
    unittest.main()
