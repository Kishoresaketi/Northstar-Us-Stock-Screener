#!/usr/bin/env python3
"""Regression tests for lib/thirteenf.py (SEC 13F aggregation).

Run:  python3 tests/test_thirteenf.py
  or: python3 -m unittest discover -s tests -v

No network access: every test uses synthetic totals fixtures or the
pinned SHARES_OUTSTANDING_OVERRIDES (checked before any EDGAR call).
Real company data is used where the Q2 2026 audit established it:
Rocket Lab / Rocket Companies (RKLB), Hubbell / Hub Group (HUBB),
Accenture / Bank of America / Exxon Mobil exact-name stubs, Alphabet
class split (GOOGL/GOOG), Honeywell multi-CUSIP group (HON), and the
Skyworks over-100% case (SWKS).
"""
import http.client
import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lib.thirteenf as tf

Q2 = date(2026, 6, 30)


def entry(name, cls, shares, filers, shares_sole=None, shares_all=None):
    """One cached-totals entry, in the shape aggregate() produces."""
    return {
        "shares": shares,
        "shares_sole": shares if shares_sole is None else shares_sole,
        "shares_all": shares if shares_all is None else shares_all,
        "filers": filers,
        "name": name,
        "class": cls,
    }


class TestNormalizeName(unittest.TestCase):
    def test_en_dash_is_a_space(self):
        # Brown-Forman is written with an en dash in the universe; dropping
        # it ("BROWNFORMAN") broke the exact match and the other-issuer
        # veto for BRO/BF-B (Q2 2026 audit).
        self.assertEqual(tf._normalize_name("Brown–Forman Corporation"), "BROWN FORMAN")

    def test_accents_stripped(self):
        # "COMPANIES" is a dropped legal-suffix word, like INC/CORP.
        self.assertEqual(tf._normalize_name("Estée Lauder Companies Inc."),
                         "ESTEE LAUDER")

    def test_abbreviations_expanded(self):
        self.assertEqual(tf._normalize_name("MTR Corp"), "MOTOR")
        self.assertEqual(tf._normalize_name("ABC SV"), "ABC SERVICES")

    def test_initials_joined(self):
        self.assertEqual(tf._normalize_name("J.M. Smucker Co"), "JM SMUCKER")
        self.assertEqual(tf._normalize_name("W. W. Grainger, Inc."), "WW GRAINGER")

    def test_trailing_class_designator_stripped(self):
        self.assertEqual(tf._normalize_name("ALPHABET INC CL A"), "ALPHABET")
        self.assertEqual(tf._normalize_name("WALMART INC COM"), "WALMART")
        self.assertEqual(tf._normalize_name("Lowe's Companies, Inc."), "LOWES")


class TestCommonClass(unittest.TestCase):
    def test_common_stock_forms(self):
        for cls in ("COM", "Common Stock", "COM CL A", "COM CL C"):
            with self.subTest(cls=cls):
                self.assertTrue(tf._is_common_class(cls))

    def test_non_equity_rejected(self):
        for cls in ("NOTE", "BOND", "PREFERRED", "OPTION", "DEBENTURE", ""):
            with self.subTest(cls=cls):
                self.assertFalse(tf._is_common_class(cls))

    def test_fixed_income_is_not_common(self):
        # "INCOME" contains "COM" as a substring; the match must be
        # word-boundary aware or FIXED INCOME passes as common stock.
        self.assertFalse(tf._is_common_class("FIXED INCOME"))


class TestScoreCandidates(unittest.TestCase):
    def test_most_filers_beats_most_shares_rklb(self):
        # Q2 2026: Rocket Companies' 77311W101 carried 946M shares under
        # a mislabeled "ROCKET LAB CORP CLASS A" name, over Rocket Lab's
        # own 773121108 (317M shares). Most-shares picked the wrong
        # issuer and produced 158%; most-filers picks the right one.
        totals = {
            "773121108": entry("ROCKET LAB CORP", "COM", 317056393, 1095),
            "77311W101": entry("ROCKET LAB CORP CLASS A", "COM", 946000000, 770),
        }
        self.assertEqual(
            tf._resolve_candidates("RKLB", ["773121108", "77311W101"], totals),
            "773121108")

    def test_most_filers_beats_most_shares_hubb(self):
        totals = {
            "443510607": entry("HUBBELL INC", "COM", 49460982, 993),
            "443510201": entry("HUB GROUP INC", "COM", 62000000, 276),
        }
        self.assertEqual(
            tf._resolve_candidates("HUBB", ["443510607", "443510201"], totals),
            "443510607")

    def test_zero_share_stub_never_wins(self):
        totals = {
            "111111111": entry("ACME CORP", "COM", 0, 5, shares_all=0),
            "222222222": entry("ACME CORP", "COM", 9000000, 400),
        }
        self.assertEqual(
            tf._resolve_candidates("ACME", ["111111111", "222222222"], totals),
            "222222222")

    def test_non_common_class_never_competes(self):
        totals = {
            "111111111": entry("ACME CORP", "NOTE", 999999999, 5000),
            "222222222": entry("ACME CORP", "COM", 1000000, 50),
        }
        self.assertEqual(
            tf._resolve_candidates("ACME", ["111111111", "222222222"], totals),
            "222222222")

    def test_class_match_outranks_filers(self):
        # GOOGL must resolve to the Class A CUSIP even though the
        # Class C CUSIP has far more reporting managers.
        totals = {
            "02079K305": entry("ALPHABET INC", "COM CL A", 4617540488, 1200),
            "02079K107": entry("ALPHABET INC", "COM CL C", 3323769756, 5198),
        }
        self.assertEqual(
            tf._resolve_candidates("GOOGL", ["02079K305", "02079K107"], totals),
            "02079K305")
        self.assertEqual(
            tf._resolve_candidates("GOOG", ["02079K305", "02079K107"], totals),
            "02079K107")

    def test_exact_stage_stub_loses_to_fuzzy_real_cusip(self):
        # Q2 2026 audit, 18 tickers (ACN, BAC, XOM, ...): an exact-name
        # stub with 1-3 filers must not beat the real CUSIP that only
        # matches at the token stage with thousands of filers.
        totals = {
            "000000001": entry("ACCENTURE PLC", "COM", 78000, 1),
            "000000002": entry("ACCENTURE PLC", "COM", 473900000, 1870),
        }
        scored = tf._score_candidates(
            "ACN", ["000000001", "000000002"], totals,
            stages={"000000001": 0, "000000002": 1})
        self.assertEqual(scored[0][0], "000000002")
        # Fidelity is still recorded in the score for diagnostics.
        self.assertEqual(scored[1][1]["stage"], "exact")

    def test_no_eligible_candidate_resolves_none(self):
        totals = {"111111111": entry("ACME CORP", "NOTE", 1000, 10)}
        self.assertIsNone(tf._resolve_candidates("ACME", ["111111111"], totals))
        self.assertIsNone(tf._resolve_candidates("ACME", [], totals))


class TestBuildCusipMap(unittest.TestCase):
    def test_other_issuer_veto(self):
        # Short-name subset pooling puts a long-named company's CUSIP in
        # a short-named ticker's pool (BRO vs Brown-Forman in Q2 2026);
        # the veto must exclude it as OTHER_ISSUER, not let it win.
        universe = {
            "AAA": {"name": "Acme Corp"},
            "BBB": {"name": "Acme Widgets"},
        }
        totals = {
            "111111111": entry("ACME WIDGETS INC", "COM", 500000000, 1000),
            "222222222": entry("ACME CORP", "COM", 9000000, 10),
        }
        mapping, _unmatched, _ambiguous, pools = tf.build_cusip_map(totals, universe)
        self.assertEqual(mapping["AAA"], "222222222")
        self.assertEqual(mapping["BBB"], "111111111")
        vetoed = [r for r in pools["AAA"] if r["cusip"] == "111111111"]
        self.assertEqual(len(vetoed), 1)
        self.assertEqual(vetoed[0]["excluded"], "OTHER_ISSUER")
        self.assertEqual(vetoed[0]["excluded_owner"], ["BBB"])

    def test_etf_candidate_excluded(self):
        universe = {"TEST": {"name": "Test Index Corp"}}
        totals = {
            "111111111": entry("TEST INDEX ETF", "COM", 900000000, 3000),
            "222222222": entry("TEST INDEX CORP", "COM", 5000000, 200),
        }
        mapping, _u, _a, pools = tf.build_cusip_map(totals, universe)
        self.assertEqual(mapping["TEST"], "222222222")
        excluded = [r for r in pools["TEST"] if r["cusip"] == "111111111"]
        self.assertEqual(excluded[0]["excluded"], "ETF")

    def test_unmatched_ticker_listed(self):
        universe = {"ZZZZ": {"name": "Nonexistent Holdings Corp"}}
        _m, unmatched, _a, _p = tf.build_cusip_map({}, universe)
        self.assertEqual(unmatched, ["ZZZZ"])

    def test_ambiguous_when_only_non_common_pools(self):
        universe = {"ACME": {"name": "Acme Corp"}}
        totals = {"111111111": entry("ACME CORP", "NOTE", 1000000, 50)}
        _m, _u, ambiguous, _p = tf.build_cusip_map(totals, universe)
        self.assertEqual([a[0] for a in ambiguous], ["ACME"])

    def test_multi_class_same_issuer_no_veto(self):
        # GOOGL/GOOG share one normalized issuer name; neither class
        # CUSIP may veto the other.
        universe = {
            "GOOGL": {"name": "Alphabet Inc."},
            "GOOG": {"name": "Alphabet Inc."},
        }
        totals = {
            "02079K305": entry("ALPHABET INC", "COM CL A", 4617540488, 5734),
            "02079K107": entry("ALPHABET INC", "COM CL C", 3323769756, 5198),
        }
        mapping, unmatched, ambiguous, _p = tf.build_cusip_map(totals, universe)
        self.assertEqual(mapping, {"GOOGL": "02079K305", "GOOG": "02079K107"})
        self.assertEqual(unmatched, [])
        self.assertEqual(ambiguous, [])

    def test_rename_aliases(self):
        # MicroStrategy -> Strategy (2025 rename); Healthpeak -> its
        # former name Health Care Property Investors.
        universe = {
            "MSTR": {"name": "MicroStrategy Inc"},
            "DOC": {"name": "Healthpeak Properties Inc"},
        }
        totals = {
            "594972408": entry("STRATEGY INC", "COM", 203000000, 829),
            "42250P103": entry("HEALTH CARE PPTY INVS INC", "COM", 641141307, 740),
        }
        mapping, _u, _a, _p = tf.build_cusip_map(totals, universe)
        self.assertEqual(mapping["MSTR"], "594972408")
        self.assertEqual(mapping["DOC"], "42250P103")

    def test_cusip_override_pinned(self):
        # MSCI's name matcher would pick the iShares MSCI ETF; the
        # verified CUSIP is pinned instead.
        universe = {"MSCI": {"name": "MSCI Inc"}}
        totals = {
            "46434V738": entry("ISHARES MSCI ETF", "COM", 900000000, 3000),
            "55354G100": entry("MSCI INC", "COM", 66900000, 800),
        }
        mapping, _u, _a, pools = tf.build_cusip_map(totals, universe)
        self.assertEqual(mapping["MSCI"], "55354G100")
        self.assertEqual(pools["MSCI"][0]["confidence"], "override")


class TestParseInfotable(unittest.TestCase):
    NS = "http://www.sec.gov/edgar/document/thirteenf/informationtable"

    def _xml(self, rows):
        body = "".join(rows)
        return (f'<informationTable xmlns="{self.NS}">'
                f"{body}</informationTable>").encode()

    def _row(self, cusip, name, cls, shares, disc="SOLE", typ="SH",
             put_call=None, other=None):
        pc = f"<putCall>{put_call}</putCall>" if put_call else ""
        om = f"<otherManager>{other}</otherManager>" if other else ""
        return (f"<infoTable><nameOfIssuer>{name}</nameOfIssuer>"
                f"<titleOfClass>{cls}</titleOfClass><cusip>{cusip}</cusip>"
                f"<shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt>"
                f"<sshPrnamtType>{typ}</sshPrnamtType></shrsOrPrnAmt>"
                f"<investmentDiscretion>{disc}</investmentDiscretion>"
                f"{pc}{om}</infoTable>")

    def test_sole_rows_sum_legitimate_multi_fund_holdings(self):
        # Two SOLE rows for one CUSIP (two funds, same manager filing)
        # are legitimate separate holdings and must both count.
        counted, sole, all_disc, _names, _shared = tf.parse_infotable(
            self._xml([
                self._row("037833100", "APPLE INC", "COM", 100),
                self._row("037833100", "APPLE INC", "COM", 50),
            ]))
        self.assertEqual(counted["037833100"], 150)
        self.assertEqual(sole["037833100"], 150)
        self.assertEqual(all_disc["037833100"], 150)

    def test_discretion_slices(self):
        counted, sole, all_disc, _n, shared = tf.parse_infotable(
            self._xml([
                self._row("037833100", "APPLE INC", "COM", 100, "SOLE"),
                self._row("037833100", "APPLE INC", "COM", 40, "DFND", other="1"),
                self._row("037833100", "APPLE INC", "COM", 30, "SHRD", other="2"),
            ]))
        self.assertEqual(counted["037833100"], 140)   # SOLE + DFND only
        self.assertEqual(sole["037833100"], 100)
        self.assertEqual(all_disc["037833100"], 170)  # all discretion
        self.assertEqual(len(shared), 2)
        self.assertEqual(shared[0]["refs"], "1")
        self.assertEqual(shared[1]["disc"], "SHRD")

    def test_put_call_and_principal_rows_excluded(self):
        counted, sole, all_disc, names, _shared = tf.parse_infotable(
            self._xml([
                self._row("037833100", "APPLE INC", "COM", 100, "SOLE"),
                self._row("037833100", "APPLE INC", "COM", 500, "SOLE",
                          put_call="CALL"),
                self._row("037833100", "APPLE INC", "COM", 700, "SOLE",
                          typ="PRN"),
            ]))
        # Option rows report the underlying shares, not shares held;
        # principal rows are not shares at all.
        self.assertEqual(counted["037833100"], 100)
        self.assertEqual(all_disc["037833100"], 100)
        self.assertEqual(names["037833100"], ("APPLE INC", "COM"))


class TestDedup(unittest.TestCase):
    def test_shared_block_counts_once_at_max(self):
        # Two managers report the same shared-discretion block (100 and
        # 80 shares); the block counts once, at the largest amount.
        groups = {
            ("037833100", ("1111111", "2222222")): {
                "1111111": (100, 100), "2222222": (80, 120)},
            ("037833100", ("3333333",)): {
                "3333333": (50, 50)},
        }
        dfnd, all_sums, diag = tf._finalize_dedup({}, groups)
        self.assertEqual(dfnd["037833100"], 150)     # 100 + 50
        self.assertEqual(all_sums["037833100"], 170)  # 120 + 50
        self.assertEqual(diag["multi_reporter_groups"], 1)

    def test_groups_json_round_trip(self):
        groups = {("037833100", ("1111111", "2222222")):
                  {"1111111": (100, 100), "2222222": (80, 120)}}
        restored = tf._groups_from_json(tf._groups_to_json(groups))
        self.assertEqual(restored, groups)


class TestBuildShareholding(unittest.TestCase):
    DENOMS = {
        "GOOGL": (5868000000, "2026-06-30"),
        "GOOG": (5527000000, "2026-06-30"),
        "SWKS": (100000000, "2026-06-30"),
        "HON": (316940010, "2026-06-30"),
        "CVNA": (1100463770, "2026-06-30"),
    }

    def setUp(self):
        self._orig = tf.shares_outstanding_asof
        tf.shares_outstanding_asof = lambda symbol, _qe: self.DENOMS[symbol]

    def tearDown(self):
        tf.shares_outstanding_asof = self._orig

    def _totals(self):
        return {
            "02079K305": entry("ALPHABET INC", "COM CL A", 4617540488, 5734),
            "02079K107": entry("ALPHABET INC", "COM CL C", 3323769756, 5198),
            "830566105": entry("SKYWORKS SOLUTIONS INC", "COM", 118550000, 900),
            "438516205": entry("HONEYWELL INTERNATIONAL", "COM", 259400000, 1500),
            "438516106": entry("HONEYWELL INTERNATIONAL", "COM", 2600000, 300),
            "194170106": entry("CARVANA CO", "COM", 500000000, 700),
        }

    def test_class_tickers_use_per_class_denominators(self):
        out, _t, _s = tf.build_shareholding(
            ["GOOGL", "GOOG"], Q2, totals=self._totals(), log=lambda *a: None)
        self.assertAlmostEqual(out["GOOGL"]["institutions_pct"],
                               4617540488 / 5868000000, places=6)
        self.assertAlmostEqual(out["GOOG"]["institutions_pct"],
                               3323769756 / 5527000000, places=6)
        self.assertEqual(out["GOOGL"]["cusip"], "02079K305")
        self.assertEqual(out["GOOG"]["cusip"], "02079K107")
        self.assertNotEqual(out["GOOGL"]["institutions_pct"],
                            out["GOOG"]["institutions_pct"])

    def test_over_100_pct_is_not_capped(self):
        # Skyworks Q2 2026: 118.55% is the genuine raw 13F total
        # (lending/shorting), not an error to clamp.
        out, _t, _s = tf.build_shareholding(
            ["SWKS"], Q2, totals=self._totals(), log=lambda *a: None)
        self.assertAlmostEqual(out["SWKS"]["institutions_pct"], 1.1855, places=4)
        self.assertGreater(out["SWKS"]["institutions_pct"], 1.0)

    def test_below_100_pct(self):
        out, _t, _s = tf.build_shareholding(
            ["CVNA"], Q2, totals=self._totals(), log=lambda *a: None)
        self.assertAlmostEqual(out["CVNA"]["institutions_pct"],
                               500000000 / 1100463770, places=6)
        self.assertLess(out["CVNA"]["institutions_pct"], 1.0)

    def test_multi_cusip_group_sums_shares_max_filers(self):
        # HON: the Automation CUSIP plus the residual old CUSIP sum;
        # filers is the max, not the sum (one manager can hold both).
        out, _t, _s = tf.build_shareholding(
            ["HON"], Q2, totals=self._totals(), log=lambda *a: None)
        self.assertEqual(out["HON"]["institutions_shares"], 262000000)
        self.assertEqual(out["HON"]["filers"], 1500)
        self.assertAlmostEqual(out["HON"]["institutions_pct"],
                               262000000 / 316940010, places=6)

    def test_missing_cusip_is_blank_not_zero(self):
        out, _t, _s = tf.build_shareholding(
            ["VMRK"], Q2, totals=self._totals(), log=lambda *a: None)
        self.assertIsNone(out["VMRK"]["institutions_pct"])
        self.assertIsNone(out["VMRK"]["cusip"])

    def test_missing_denominator_is_blank_not_zero(self):
        # A ticker whose facts file is missing raises in the denominator
        # lookup; the entry is blank, the build does not crash.
        orig = tf.shares_outstanding_asof

        def _boom(symbol, _qe):
            raise FileNotFoundError(f"no facts for {symbol}")

        tf.shares_outstanding_asof = _boom
        try:
            out, _t, _s = tf.build_shareholding(
                ["SWKS"], Q2, totals=self._totals(), log=lambda *a: None)
        finally:
            tf.shares_outstanding_asof = orig
        self.assertIsNone(out["SWKS"]["institutions_pct"])
        self.assertEqual(out["SWKS"]["institutions_shares"], 118550000)

    def test_mapping_quality_recorded(self):
        out, _t, _s = tf.build_shareholding(
            ["GOOGL"], Q2, totals=self._totals(), log=lambda *a: None)
        self.assertIn(out["GOOGL"]["mapping_confidence"],
                      ("high", "medium", "low", "override"))
        self.assertIsInstance(out["GOOGL"]["mapping_warnings"], list)


class TestSharesOutstandingOverrides(unittest.TestCase):
    # Per-class cover counts verified against the filings in Nov 2026
    # (Q2 2026 audit): the facts API carries only the total across
    # classes for these issuers, or nothing at all.
    EXPECTED = {
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

    def test_overrides_pinned(self):
        for symbol, expected in self.EXPECTED.items():
            with self.subTest(symbol=symbol):
                self.assertEqual(
                    tf.shares_outstanding_asof(symbol, Q2), expected)


class TestGetRetries(unittest.TestCase):
    """EDGAR truncates responses mid-download (IncompleteRead) and drops
    connections (RemoteDisconnected) — both must be retried, not lost.
    The Nov 22 top-holders run lost 869 of 8,898 filings to exactly
    these two errors, including every large manager table."""

    class _Resp:
        def __init__(self, body):
            self._body = body
            self.headers = {}

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _patched(self, urlopen):
        return (mock.patch("urllib.request.urlopen", side_effect=urlopen),
                mock.patch.object(tf, "_rate_wait", lambda: None),
                mock.patch("time.sleep", lambda s: None))

    def test_incomplete_read_retried_then_succeeds(self):
        calls = {"n": 0}

        def flaky(request, timeout=None):
            calls["n"] += 1
            if calls["n"] < 3:
                raise http.client.IncompleteRead(b"partial", 100)
            return self._Resp(b"ok")

        patches = self._patched(flaky)
        for p in patches:
            p.start()
        try:
            self.assertEqual(tf._get("https://example.com/x"), b"ok")
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(calls["n"], 3)

    def test_remote_disconnected_retried_then_raised(self):
        def dead(request, timeout=None):
            raise http.client.RemoteDisconnected(
                "Remote end closed connection without response")

        patches = self._patched(dead)
        for p in patches:
            p.start()
        try:
            with self.assertRaises(http.client.RemoteDisconnected):
                tf._get("https://example.com/x")
        finally:
            for p in patches:
                p.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
