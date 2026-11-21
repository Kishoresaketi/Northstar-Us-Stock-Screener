#!/usr/bin/env python3
"""Regression tests for the quarterly pipeline in lib/edgar.py:
quarterly balance sheet (point-in-time), quarterly cash flow derived
by differencing year-to-date 10-Q figures, quarterly debt (concept
or component sum), and TTM windows with gaps.

Run:  python3 tests/test_edgar_quarterly.py
  or: python3 -m unittest discover -s tests -v

No network access: every test uses synthetic companyfacts fixtures.
Real company data is used by the rebuild validation script, which
checks the same properties against AAPL / MSFT / DOW filings.
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


def q10(end, fp, val, **kw):
    d = {"end": end, "form": "10-Q", "fp": fp, "val": val}
    d.update(kw)
    return d


def k10(end, val, **kw):
    d = {"end": end, "form": "10-K", "fp": "FY", "val": val}
    d.update(kw)
    return d


# A fiscal year ending 2025-09-27, quarters ending Dec / Mar / Jun.
CFO = "NetCashProvidedByOperatingActivities"
CAPEX = "PaymentsToAcquirePropertyPlantAndEquipment"


class TestYtdDifferencing(unittest.TestCase):
    def test_quarters_from_ytd(self):
        # YTD: Q1 100, Q2 250, Q3 400, FY 500 -> quarters 100/150/150/100.
        f = facts_for({CFO: [
            q10("2024-12-28", "Q1", 100),
            q10("2025-03-29", "Q2", 250),
            q10("2025-06-28", "Q3", 400),
            k10("2025-09-27", 500),
        ]})
        out = edgar._quarterly_flow_ytd_series(f, [CFO], {2025: 500})
        self.assertEqual(out, {(2025, "Q1"): 100, (2025, "Q2"): 150,
                               (2025, "Q3"): 150, (2025, "Q4"): 100})

    def test_missing_q2_ytd(self):
        # YTD(Q2) missing: Q2 and Q3 cannot be derived, but Q4 still
        # can (FY - YTD(Q3) needs only the 9-month figure).
        f = facts_for({CFO: [
            q10("2024-12-28", "Q1", 100),
            q10("2025-06-28", "Q3", 400),
            k10("2025-09-27", 500),
        ]})
        out = edgar._quarterly_flow_ytd_series(f, [CFO], {2025: 500})
        self.assertEqual(out.get((2025, "Q1")), 100)
        self.assertIsNone(out.get((2025, "Q2")))
        self.assertIsNone(out.get((2025, "Q3")))
        self.assertEqual(out.get((2025, "Q4")), 100)

    def test_missing_q3_ytd_blocks_q4(self):
        # No YTD(Q3): Q4 cannot be derived even though FY is known.
        f = facts_for({CFO: [
            q10("2024-12-28", "Q1", 100),
            q10("2025-03-29", "Q2", 250),
            k10("2025-09-27", 500),
        ]})
        out = edgar._quarterly_flow_ytd_series(f, [CFO], {2025: 500})
        self.assertEqual(out.get((2025, "Q2")), 150)
        self.assertIsNone(out.get((2025, "Q3")))
        self.assertIsNone(out.get((2025, "Q4")))

    def test_negative_capex_from_restatement_is_null(self):
        # A restated YTD that falls below the prior YTD would derive a
        # negative quarter. Payments cannot be negative: null, not a
        # made-up value.
        f = facts_for({CAPEX: [
            q10("2024-12-28", "Q1", 100),
            q10("2025-03-29", "Q2", 90),
            k10("2025-09-27", 300),
        ]})
        out = edgar._quarterly_flow_ytd_series(f, [CAPEX], {2025: 300},
                                               non_negative=True)
        self.assertEqual(out.get((2025, "Q1")), 100)
        self.assertIsNone(out.get((2025, "Q2")))

    def test_negative_operating_cash_flow_is_kept(self):
        # A company can genuinely burn cash in a quarter: a negative
        # derived CFO is real data, not an artefact.
        f = facts_for({CFO: [
            q10("2024-12-28", "Q1", 100),
            q10("2025-03-29", "Q2", 80),
            k10("2025-09-27", 300),
        ]})
        out = edgar._quarterly_flow_ytd_series(f, [CFO], {2025: 300})
        self.assertEqual(out.get((2025, "Q2")), -20)

    def test_quarterly_machinery_would_return_ytd(self):
        # Documents WHY cash flow needs its own builder: the generic
        # _quarterly picker returns the YTD figure as the "quarter"
        # (Q2 reads 250, the 6-month total, not the 150 quarter).
        f = facts_for({CFO: [
            q10("2024-12-28", "Q1", 100),
            q10("2025-03-29", "Q2", 250),
            q10("2025-06-28", "Q3", 400),
        ]})
        pts = {p["fp"]: p["val"] for p in edgar._quarterly(f, CFO)}
        self.assertEqual(pts.get("Q2"), 250)


class TestStockSeries(unittest.TestCase):
    def test_quarter_end_balances_not_summed(self):
        f = facts_for({"Assets": [
            q10("2024-12-28", "Q1", 1000),
            q10("2025-03-29", "Q2", 1100),
            q10("2025-06-28", "Q3", 1200),
            k10("2025-09-27", 1300),
        ]})
        out = edgar._quarterly_stock_series(f, ["Assets"], {2025: 1300})
        self.assertEqual(out, {(2025, "Q1"): 1000, (2025, "Q2"): 1100,
                               (2025, "Q3"): 1200, (2025, "Q4"): 1300})

    def test_comparative_column_lands_as_q4(self):
        # A later 10-Q's comparative column carries the prior year-end
        # balance (end 2025-09-27) under the filing's own fp Q1. Its
        # end is a year-end, so it is Q4 — never Q1 of the next year.
        f = facts_for({"Assets": [
            q10("2024-12-28", "Q1", 1000),
            q10("2025-03-29", "Q2", 1100),
            q10("2025-06-28", "Q3", 1200),
            k10("2025-09-27", 1300),
            q10("2025-09-27", "Q1", 1300, filed="2026-01-30"),
        ]})
        out = edgar._quarterly_stock_series(f, ["Assets"], {2025: 1300})
        self.assertEqual(out.get((2025, "Q4")), 1300)
        self.assertIsNone(out.get((2026, "Q1")))

    def test_later_filing_fp_does_not_rename_the_quarter(self):
        # Real Apple case: the Dec 2024 equity balance is reported by
        # the Q2 FY2026 10-Q (filed 2026-05-01) as fp Q2, although it
        # is the Q1 FY2025 balance. The label comes from the earliest
        # filing (the quarter's own 10-Q, fp Q1); the value comes from
        # the latest filing (a restatement to 67000 wins over 66500).
        f = facts_for({"StockholdersEquity": [
            q10("2024-12-28", "Q1", 66500, filed="2025-01-31"),
            q10("2024-12-28", "Q2", 67000, filed="2026-05-01"),
            q10("2025-03-29", "Q2", 66758, filed="2025-05-02"),
            q10("2025-06-28", "Q3", 65830, filed="2025-08-01"),
            k10("2025-09-27", 73733),
        ]})
        out = edgar._quarterly_stock_series(f, ["StockholdersEquity"], {2025: 73733})
        self.assertEqual(out.get((2025, "Q1")), 67000)
        self.assertEqual(out.get((2025, "Q2")), 66758)
        self.assertEqual(out.get((2025, "Q3")), 65830)
        self.assertEqual(out.get((2025, "Q4")), 73733)

    def test_q4_comes_from_annual_table(self):
        # The annual table's value wins for Q4, so the quarterly Q4
        # always matches the annual figure shown for that year.
        f = facts_for({"Assets": [
            q10("2024-12-28", "Q1", 1000),
            k10("2025-09-27", 1300),
        ]})
        out = edgar._quarterly_stock_series(f, ["Assets"], {2025: 1350})
        self.assertEqual(out.get((2025, "Q4")), 1350)

    def test_trailing_quarters_after_last_annual(self):
        f = facts_for({"Assets": [
            q10("2024-12-28", "Q1", 1000),
            k10("2025-09-27", 1300),
            q10("2025-12-27", "Q1", 1400),
            q10("2026-03-28", "Q2", 1500),
        ]})
        out = edgar._quarterly_stock_series(f, ["Assets"], {2025: 1300})
        self.assertEqual(out.get((2026, "Q1")), 1400)
        self.assertEqual(out.get((2026, "Q2")), 1500)


class TestDebtSeries(unittest.TestCase):
    def test_debt_concept_wins(self):
        f = facts_for({"Debt": [q10("2024-12-28", "Q1", 500),
                                k10("2025-09-27", 600)],
                       "LongTermDebt": [q10("2024-12-28", "Q1", 999)]})
        out = edgar._quarterly_debt_series(f, {2025: 600})
        self.assertEqual(out.get((2025, "Q1")), 500)

    def test_components_summed_when_no_debt_concept(self):
        f = facts_for({"LongTermDebt": [q10("2024-12-28", "Q1", 400),
                                        k10("2025-09-27", 450)],
                       "ShortTermBorrowings": [q10("2024-12-28", "Q1", 100),
                                               k10("2025-09-27", 150)]})
        out = edgar._quarterly_debt_series(f, {2025: 600})
        self.assertEqual(out.get((2025, "Q1")), 500)
        self.assertEqual(out.get((2025, "Q4")), 600)


class TestTtm(unittest.TestCase):
    def test_four_consecutive_quarters_sum(self):
        qmap = {(2025, "Q1"): 10, (2025, "Q2"): 20, (2025, "Q3"): 30,
                (2025, "Q4"): 40, (2026, "Q1"): 50}
        self.assertEqual(edgar._ttm_at(qmap, 2026, "Q1"), 140)
        self.assertEqual(edgar._ttm_at(qmap, 2025, "Q4"), 100)

    def test_gap_makes_ttm_unknown(self):
        qmap = {(2025, "Q1"): 10, (2025, "Q3"): 30, (2025, "Q4"): 40,
                (2026, "Q1"): 50}
        self.assertIsNone(edgar._ttm_at(qmap, 2026, "Q1"))

    def test_prev_quarter_wraps_year(self):
        self.assertEqual(edgar._prev_q(2026, "Q1"), (2025, "Q4"))
        self.assertEqual(edgar._prev_q(2026, "Q3"), (2026, "Q2"))


if __name__ == "__main__":
    unittest.main()
