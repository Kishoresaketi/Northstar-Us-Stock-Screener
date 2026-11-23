"""Tests for lib/form4.py (SEC Form 4 insider holdings).

Run:  python3 tests/test_form4.py
  or: python3 -m unittest discover -s tests -v

No network access: every test uses small fixture XML strings or
synthetic efts hits. Live verification (filing dates, accessions) is
reported by the build script run, not by these tests.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lib.form4 as f4


def _xml(rows, owners=(("1234567", "Cook Timothy D"),), doc_type="4"):
    """A minimal Form 4 XML: `rows` is a list of (title, shares, nature)
    or (title, shares, nature, natureOfOwnership text) non-derivative
    rows in document order; a row with shares=None omits
    sharesOwnedFollowingTransaction."""
    owner_xml = "".join(
        f"""<reportingOwner><reportingOwnerId>
        <rptOwnerCik>{cik}</rptOwnerCik><rptOwnerName>{name}</rptOwnerName>
        </reportingOwnerId></reportingOwner>"""
        for cik, name in owners)
    row_xml = ""
    for row in rows:
        title, shares, nature = row[0], row[1], row[2]
        holder_text = row[3] if len(row) > 3 else ""
        post = (f"<postTransactionAmounts><sharesOwnedFollowingTransaction>"
                f"<value>{shares}</value></sharesOwnedFollowingTransaction>"
                f"</postTransactionAmounts>") if shares is not None else ""
        nature_xml = (f"<natureOfOwnership><value>{holder_text}</value>"
                      f"</natureOfOwnership>") if holder_text else ""
        row_xml += (f"""<nonDerivativeTransaction>
            <securityTitle><value>{title}</value></securityTitle>
            <transactionDate><value>2026-01-15</value></transactionDate>
            <transactionAmounts><transactionShares><value>100</value>
            </transactionShares></transactionAmounts>{post}
            <ownershipNature><directOrIndirectOwnership>
            <value>{nature}</value></directOrIndirectOwnership>
            {nature_xml}</ownershipNature></nonDerivativeTransaction>""")
    return f"""<?xml version="1.0"?><ownershipDocument>
    <documentType>{doc_type}</documentType>
    <issuer><issuerCik>0000320193</issuerCik><issuerName>Apple Inc.</issuerName>
    <issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer>
    {owner_xml}
    <nonDerivativeTable>{row_xml}</nonDerivativeTable>
    </ownershipDocument>""".encode()


def _derivatives_only_xml():
    return b"""<?xml version="1.0"?><ownershipDocument>
    <documentType>4</documentType>
    <issuer><issuerCik>0000320193</issuerCik><issuerName>Apple Inc.</issuerName>
    <issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer>
    <reportingOwner><reportingOwnerId>
    <rptOwnerCik>1234567</rptOwnerCik><rptOwnerName>Doe Jane</rptOwnerName>
    </reportingOwnerId></reportingOwner>
    <derivativeTable><derivativeTransaction>
    <securityTitle><value>Restricted Stock Units</value></securityTitle>
    <transactionAmounts><transactionShares><value>500</value>
    </transactionShares></transactionAmounts>
    <postTransactionAmounts><sharesOwnedFollowingTransaction><value>500</value>
    </sharesOwnedFollowingTransaction></postTransactionAmounts>
    </derivativeTransaction></derivativeTable>
    </ownershipDocument>"""


class TestTitleMatches(unittest.TestCase):
    def test_plain_accepts_bare_common_stock(self):
        self.assertTrue(f4.title_matches("Common Stock", "AAPL"))
        self.assertTrue(f4.title_matches("Common Stock, $0.00001 par value", "AAPL"))

    def test_plain_accepts_common_shares_and_ordinary_shares(self):
        # Abbott titles its stock "Common shares without par value"
        # and Arch Capital "Common Shares, $.0011 par value per
        # share"; Irish-domiciled issuers use "Ordinary Shares".
        # Before this rule ABT and ACGL measured ZERO owners in the
        # full run (2026-11-22) and each burned ~4 min on 10 rounds
        # of fallback fetches.
        self.assertTrue(f4.title_matches("Common shares without par value", "ABT"))
        self.assertTrue(f4.title_matches("Common Shares, $.0011 par value per share", "ACGL"))
        self.assertTrue(f4.title_matches("Ordinary Shares", "MDT"))
        self.assertTrue(f4.title_matches("Class A ordinary shares", "ACN"))
        self.assertTrue(f4.title_matches("Class A Ordinary Shares", "AON"))
        self.assertTrue(f4.title_matches("Common Shares", "GOOGL"))
        # Depositary/preference shares are not common stock.
        self.assertFalse(f4.title_matches("Depositary Shares", "AAPL"))
        self.assertFalse(f4.title_matches("Depositary Shares, Series F", "ACGL"))
        self.assertFalse(f4.title_matches("8.5% Cumulative Redeemable Preference Shares", "ACGL"))
        self.assertFalse(f4.title_matches("Class A Preference Shares", "ACN"))

    def test_plain_accepts_comm_stock_abbreviation(self):
        # Analog Devices titles its stock "Comm Stock - $.16-2/3
        # value" (720 rows in the cache); one filing misspells it
        # "Commons shares". Without the abbreviation expansion, ADI
        # measured ZERO owners in the full run (2026-11-22).
        self.assertTrue(f4.title_matches("Comm Stock - $.16-2/3 value", "ADI"))
        self.assertTrue(f4.title_matches("Comm Stock-$.16-2/3 value", "ADI"))
        self.assertTrue(f4.title_matches("Commons shares without par value", "ABT"))
        # The expansion must not turn real common stock into a miss.
        self.assertTrue(f4.title_matches("Common Stock", "ADI"))
        self.assertTrue(f4.title_matches("Common Stock, $0.16 2/3 par value", "ADI"))

    def test_plain_accepts_bare_common(self):
        # Cummins titles its stock just "Common" (1,250 rows in the
        # cache). Without this, CMI measured ZERO owners in the full
        # run (2026-11-22). Partnership units are not common stock.
        self.assertTrue(f4.title_matches("Common", "CMI"))
        self.assertTrue(f4.title_matches("Common", "AAPL"))
        self.assertFalse(f4.title_matches("Common Units", "AAPL"))
        self.assertFalse(f4.title_matches(
            "Common Units representing Limited Partner Interests", "AAPL"))

    def test_plain_accepts_registered_shares(self):
        # Garmin (Swiss) titles its stock "Registered Shares" (114
        # rows in the cache). Without this, GRMN measured ZERO owners
        # in the full run (2026-11-22).
        self.assertTrue(f4.title_matches("Registered Shares", "GRMN"))
        self.assertTrue(f4.title_matches("Registered Shares", "AAPL"))

    def test_plain_accepts_name_common_and_double_spaces(self):
        # Humana titles its stock "Humana Common" (1,106 rows in the
        # cache). Without the "<Name> Common" clause, HUM measured
        # ZERO owners in the full run (2026-11-22). Some filers use
        # double spaces ("common  stock"), which broke substring
        # matching before whitespace was collapsed.
        self.assertTrue(f4.title_matches("Humana Common", "HUM"))
        self.assertTrue(f4.title_matches("common  stock", "AAPL"))
        self.assertTrue(f4.title_matches("Common  Stock", "AAPL"))
        # The "<Name> Common" clause requires no "class" in the
        # title, so a class title still never counts for a plain
        # ticker.
        self.assertFalse(f4.title_matches("Class B Common", "AAPL"))
        self.assertFalse(f4.title_matches("Class A Common", "AAPL"))

    def test_plain_accepts_ordinary_shares_paren_and_sock_typo(self):
        # Pentair writes "Common (Ordinary) Shares" (17 rows) and
        # Pinnacle West writes "Common Sock" (27 rows, typo for
        # "Common Stock"). Both are the issuer's common stock.
        self.assertTrue(f4.title_matches("Common (Ordinary) Shares", "PNR"))
        self.assertTrue(f4.title_matches("Common Sock", "PNW"))
        # A parenthetical that changes the security still excludes.
        self.assertFalse(f4.title_matches("Common Stock (phantom stock)", "AAPL"))

    def test_class_a_shares_counts_for_class_ticker(self):
        # Nebius Group titles its shares "Class A Shares" (55 rows
        # in the cache). Without the "shares" word in the classed
        # rule, NBIS measured ZERO owners in the full run (2026-11-22).
        self.assertTrue(f4.title_matches("Class A Shares", "NBIS"))
        self.assertTrue(f4.title_matches("Class A shares", "NBIS"))
        self.assertFalse(f4.title_matches("Class B Shares", "NBIS"))
        # Preference/depositary shares name a class and "shares" but
        # are not common stock.
        self.assertFalse(f4.title_matches("Class A Preference Shares", "NBIS"))
        self.assertFalse(f4.title_matches("Class A Depositary Shares", "NBIS"))
        self.assertFalse(f4.title_matches("American Depositary Shares", "AAPL"))
        # A class title still never counts for a plain ticker.
        self.assertFalse(f4.title_matches("Class A Shares", "AAPL"))


class TestGetRetries(unittest.TestCase):
    def test_retries_incomplete_read_and_remote_disconnect(self):
        # EDGAR truncates responses mid-download (IncompleteRead at
        # ~1,304 bytes) and drops connections (RemoteDisconnected).
        # Both are http.client errors, not URLError, and an earlier
        # _get let them escape unretried — failing ~100 tickers in
        # the G-M stretch of the full run (2026-11-22) at enumeration.
        import http.client
        import time
        import urllib.request
        from unittest import mock

        calls = {"n": 0}

        class Resp:
            headers = {}
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self):
                return b"ok"

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise http.client.IncompleteRead(b"x" * 1304, 4493)
            if calls["n"] == 2:
                raise http.client.RemoteDisconnected(
                    "Remote end closed connection without response")
            return Resp()

        with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
             mock.patch.object(f4, "_rate_wait", lambda: None), \
             mock.patch.object(time, "sleep", lambda s: None):
            self.assertEqual(f4._get("https://example.invalid/x"), b"ok")
        self.assertEqual(calls["n"], 3)

    def test_plain_accepts_class_title_when_it_is_the_traded_class(self):
        # META files only "Class A Common Stock" — that IS the traded class.
        self.assertTrue(f4.title_matches("Class A Common Stock", "META"))

    def test_rejects_non_common_titles(self):
        for title in ("Restricted Stock Units", "Stock Options",
                      "Common Stock Purchase Warrants", "Preferred Stock",
                      "Class A Common Stock Purchase Warrants",
                      "Common Stock Units"):
            with self.subTest(title=title):
                self.assertFalse(f4.title_matches(title, "AAPL"))

    def test_brown_forman_drops_stock(self):
        # Brown-Forman titles its shares "Class B Common" / "Class A
        # Common" (no "Stock"). Without this, BF-B measured zero holders.
        self.assertTrue(f4.title_matches("Class B Common", "BF-B"))
        self.assertFalse(f4.title_matches("Class A Common", "BF-B"))
        self.assertFalse(f4.title_matches("Class A Common", "BRK-B"))
        self.assertTrue(f4.title_matches("Class B Common Stock", "BF-B"))

    def test_alphabet_class_c_is_capital_stock(self):
        # Alphabet titles its Class C shares "Class C Capital Stock",
        # not "Class C Common Stock" (Pichai filing 0001193125-26-434831,
        # 2026-10-27). Without this, GOOG measured zero holders.
        self.assertTrue(f4.title_matches("Class C Capital Stock", "GOOG"))
        self.assertFalse(f4.title_matches("Class C Capital Stock", "GOOGL"))
        self.assertFalse(f4.title_matches("Class A Capital Stock", "GOOG"))
        # GSUs name the class but are units, not shares.
        self.assertFalse(f4.title_matches("Class C Google Stock Units", "GOOG"))
        self.assertFalse(f4.title_matches("Class C Google Stock Units", "GOOGL"))

    def test_class_ticker_must_match_its_class(self):
        self.assertTrue(f4.title_matches("Class A Common Stock", "GOOGL"))
        self.assertFalse(f4.title_matches("Class C Common Stock", "GOOGL"))
        self.assertTrue(f4.title_matches("Class C Common Stock", "GOOG"))
        self.assertFalse(f4.title_matches("Class A Common Stock", "GOOG"))
        self.assertTrue(f4.title_matches("Class B Common Stock", "BRK-B"))
        self.assertFalse(f4.title_matches("Class A Common Stock", "BRK-B"))
        self.assertTrue(f4.title_matches("Class A Common Stock", "FOXA"))
        self.assertFalse(f4.title_matches("Class B Common Stock", "FOXA"))
        self.assertTrue(f4.title_matches("Class B Common Stock", "FOX"))
        # A bare "Common Stock" title also counts for a class ticker
        # (the filer's unlettered spelling of the traded class); the
        # lenient rule keeps a wrongly-mapped ticker from losing all
        # its holdings. The wrong class letter still never counts.
        self.assertTrue(f4.title_matches("Common Stock", "GOOGL"))
        self.assertTrue(f4.title_matches("Common Stock", "BRK-B"))

    def test_shopify_subordinate_voting_shares(self):
        # Shopify titles its shares "Class A Subordinate Voting Shares".
        self.assertTrue(f4.title_matches("Class A Subordinate Voting Shares", "SHOP"))
        self.assertFalse(f4.title_matches("Class B Multiple Voting Shares", "SHOP"))

    def test_len_is_class_a_only(self):
        self.assertTrue(f4.title_matches("Class A Common Stock", "LEN"))
        self.assertFalse(f4.title_matches("Class B Common Stock", "LEN"))

    def test_meta_is_class_a_only(self):
        # Meta's traded class is Class A; Class B is founder-held.
        self.assertTrue(f4.title_matches("Class A Common Stock", "META"))
        self.assertFalse(f4.title_matches("Class B Common Stock", "META"))


class TestParseForm4(unittest.TestCase):
    def test_direct_only(self):
        parsed = f4.parse_form4_xml(
            _xml([("Common Stock", 25200, "D")]), "AAPL")
        self.assertEqual(parsed["total"], 25200)
        self.assertEqual(parsed["direct"], 25200)
        self.assertEqual(parsed["indirect"], 0)
        self.assertTrue(parsed["has_holding"])
        self.assertFalse(parsed["joint"])
        self.assertEqual(parsed["owners"], [{"cik": "1234567", "name": "Cook Timothy D"}])
        # The filing's own issuer, for the caller's issuer check.
        self.assertEqual(parsed["issuer_cik"], "320193")
        self.assertEqual(parsed["issuer_symbol"], "AAPL")

    def test_direct_plus_indirect_summed(self):
        parsed = f4.parse_form4_xml(
            _xml([("Common Stock", 100000, "D"), ("Common Stock", 5000, "I")]), "AAPL")
        self.assertEqual(parsed["direct"], 100000)
        self.assertEqual(parsed["indirect"], 5000)
        self.assertEqual(parsed["total"], 105000)

    def test_last_transaction_wins_per_bucket(self):
        # Three sales in one filing: only the last post-transaction
        # balance per bucket is the holding — never the sum of rows.
        parsed = f4.parse_form4_xml(_xml([
            ("Common Stock", 100000, "D"),
            ("Common Stock", 90000, "D"),
            ("Common Stock", 85000, "D"),
            ("Common Stock", 7000, "I"),
            ("Common Stock", 6500, "I"),
        ]), "AAPL")
        self.assertEqual(parsed["direct"], 85000)
        self.assertEqual(parsed["indirect"], 6500)
        self.assertEqual(parsed["total"], 91500)

    def test_two_indirect_trusts_are_summed(self):
        # Pichai's 2026-10-27 Alphabet filing holds Class C in two
        # separate annuity trusts, 555,732 shares each. Per-nature
        # last-wins would drop one trust; per-bucket lasts sum them.
        parsed = f4.parse_form4_xml(_xml([
            ("Class C Capital Stock", 1678737, "D"),
            ("Class C Capital Stock", 555732, "I",
             "Sundararajan Pichai 2026 Annuity Trust dtd 02/23/2026"),
            ("Class C Capital Stock", 555732, "I",
             "Anjali Pichai 2026 Annuity Trust dtd 02/18/2026"),
        ]), "GOOG")
        self.assertEqual(parsed["direct"], 1678737)
        self.assertEqual(parsed["indirect"], 1111464)
        self.assertEqual(parsed["total"], 2790201)

    def test_empty_bucket_does_not_add(self):
        # Zuckerberg's Sep 2026 filing: the CZI Holdings bucket ends at
        # 0 while the Biohub bucket ends at 1,220,703 — the total is
        # the sum of the buckets' last balances.
        parsed = f4.parse_form4_xml(_xml([
            ("Class A Common Stock", 600, "I", "By CZI Holdings, LLC"),
            ("Class A Common Stock", 0, "I", "By CZI Holdings, LLC"),
            ("Class A Common Stock", 1220703, "I",
             "By Chan Zuckerberg Biohub, Inc."),
        ]), "META")
        self.assertEqual(parsed["indirect"], 1220703)
        self.assertEqual(parsed["total"], 1220703)

    def test_genuine_zero_is_kept(self):
        parsed = f4.parse_form4_xml(
            _xml([("Common Stock", 0, "D")]), "AAPL")
        self.assertTrue(parsed["has_holding"])
        self.assertEqual(parsed["total"], 0)

    def test_derivatives_only_has_no_holding(self):
        parsed = f4.parse_form4_xml(_derivatives_only_xml(), "AAPL")
        self.assertFalse(parsed["has_holding"])
        self.assertIsNone(parsed["total"])

    def test_non_common_rows_ignored(self):
        parsed = f4.parse_form4_xml(_xml([
            ("Restricted Stock Units", 99999, "D"),
            ("Common Stock", 12000, "D"),
        ]), "AAPL")
        self.assertEqual(parsed["total"], 12000)

    def test_class_title_filtering_in_parse(self):
        parsed = f4.parse_form4_xml(_xml([
            ("Class A Common Stock", 1000, "D"),
            ("Class C Common Stock", 2000, "D"),
        ]), "GOOGL")
        # Only the Class A row matches GOOGL; the Class C row is ignored
        # (and it does not overwrite the Class A balance).
        self.assertEqual(parsed["total"], 1000)

    def test_shares_with_commas(self):
        parsed = f4.parse_form4_xml(
            _xml([("Common Stock", "1,234,567", "D")]), "AAPL")
        self.assertEqual(parsed["total"], 1234567)

    def test_joint_filing(self):
        parsed = f4.parse_form4_xml(
            _xml([("Common Stock", 50000, "D")],
                 owners=(("111", "Alpha Fund LP"), ("222", "Beta LLC"))),
            "AAPL")
        self.assertTrue(parsed["joint"])
        self.assertEqual(len(parsed["owners"]), 2)
        self.assertEqual(parsed["owners"][0]["cik"], "111")
        self.assertEqual(parsed["total"], 50000)

    def test_holding_row_without_transaction(self):
        xml = b"""<?xml version="1.0"?><ownershipDocument>
        <documentType>4</documentType>
        <issuer><issuerCik>0000320193</issuerCik><issuerName>Apple Inc.</issuerName>
        <issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer>
        <reportingOwner><reportingOwnerId>
        <rptOwnerCik>1234567</rptOwnerCik><rptOwnerName>Doe Jane</rptOwnerName>
        </reportingOwnerId></reportingOwner>
        <nonDerivativeTable><nonDerivativeHolding>
        <securityTitle><value>Common Stock</value></securityTitle>
        <postTransactionAmounts><sharesOwnedFollowingTransaction><value>4321</value>
        </sharesOwnedFollowingTransaction></postTransactionAmounts>
        <ownershipNature><directOrIndirectOwnership><value>D</value>
        </directOrIndirectOwnership></ownershipNature>
        </nonDerivativeHolding></nonDerivativeTable>
        </ownershipDocument>"""
        parsed = f4.parse_form4_xml(xml, "AAPL")
        self.assertTrue(parsed["has_holding"])
        self.assertEqual(parsed["total"], 4321)

    def test_unparseable_xml(self):
        parsed = f4.parse_form4_xml(b"not xml at all", "AAPL")
        self.assertFalse(parsed["has_holding"])
        self.assertTrue(parsed.get("parse_error"))


class TestEftsHits(unittest.TestCase):
    def _page(self, hits):
        return {"hits": {"total": {"value": len(hits)}, "hits": [
            {"_source": h} for h in hits]}}

    def test_issuer_first_hit_yields_the_owner(self):
        # One Microsoft filing lists [issuer 789019, owner 1576843]:
        # ciks[0] is NOT the owner. The expansion must yield Amy Hood,
        # not a phantom "Microsoft Corp" owner.
        page = self._page([{
            "ciks": ["0000789019", "0001576843"],
            "display_names": ["MICROSOFT CORP  (MSFT)  (CIK 0000789019)",
                              "Hood Amy  (CIK 0001576843)"],
            "adsh": "0001626431-17-000051", "file_date": "2017-06-27",
            "form": "4"}])
        hits = f4._efts_hits_from_page(page, "789019")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["owner_cik"], "1576843")
        self.assertEqual(hits[0]["owner_name"], "Hood Amy")
        self.assertEqual(hits[0]["adsh"], "0001626431-17-000051")

    def test_joint_hit_expands_to_each_reporting_owner(self):
        page = self._page([{
            "ciks": ["0001722201", "0001722204", "0001721789", "0001652044"],
            "display_names": ["GV 2016 GP, L.L.C.  (CIK 0001722201)",
                              "GV 2016 GP, L.P.  (CIK 0001722204)",
                              "GV 2016, L.P.  (CIK 0001721789)",
                              "Alphabet Inc.  (CIK 0001652044)"],
            "adsh": "0000899243-18-018327", "file_date": "2018-06-27",
            "form": "4"}])
        hits = f4._efts_hits_from_page(page, "1652044")
        # The issuer (Alphabet) is excluded; all three GV owners remain.
        self.assertEqual([h["owner_cik"] for h in hits],
                         ["1722201", "1722204", "1721789"])
        self.assertTrue(all(h["adsh"] == "0000899243-18-018327" for h in hits))

    def test_issuer_only_hit_is_dropped(self):
        page = self._page([{
            "ciks": ["0000789019"],
            "display_names": ["MICROSOFT CORP  (CIK 0000789019)"],
            "adsh": "0000789019-26-999999", "file_date": "2026-01-01",
            "form": "4"}])
        self.assertEqual(f4._efts_hits_from_page(page, "789019"), [])


class TestSpoofExclusion(unittest.TestCase):
    def test_lee_filing_is_excluded_not_measured(self):
        # Antonio Lee's fabricated Feb 2017 Alphabet Form 4 (4.5B
        # shares, ~76% of the class) must never reach the totals, even
        # though the filing itself is well-formed and names Alphabet
        # as issuer. Stub the networked enumeration/fetch.
        lee_hit = {"owner_cik": "1695879", "owner_name": "Lee Antonio",
                   "adsh": "0001695879-17-000002",
                   "file_date": "2017-02-02", "form": "4"}
        cook_hit = {"owner_cik": "1234567", "owner_name": "Cook Timothy D",
                    "adsh": "0000320193-26-000001",
                    "file_date": "2026-10-05", "form": "4"}
        lee_xml = _xml(
            [("Common Stock", 4492628992, "I",
              "To be completed at Vanguard Brokerage Services")],
            owners=(("1695879", "Lee Antonio"),))
        cook_xml = _xml([("Common Stock", 3237843, "D")])
        orig_enum, orig_fetch = f4.enumerate_filings, f4._fetch_many
        f4.enumerate_filings = lambda *a, **k: [lee_hit, cook_hit]
        f4._fetch_many = lambda issuer, ads, cache: {
            "0001695879-17-000002": (lee_xml, False, None),
            "0000320193-26-000001": (cook_xml, False, None)}
        try:
            entry, dg = f4.build_ticker("AAPL", "320193", 14532259000)
        finally:
            f4.enumerate_filings, f4._fetch_many = orig_enum, orig_fetch
        self.assertEqual(entry["owners_excluded_spoof"], 1)
        self.assertEqual(dg["excluded_spoof_owners"], ["1695879"])
        self.assertEqual(entry["owners_measured"], 1)
        self.assertEqual(entry["insiders_total_shares"], 3237843)
        self.assertNotIn("1695879", [t["cik"] for t in entry["top"]])

    def test_ynoface_entity_is_excluded_too(self):
        # The other half of the same fabrication: Lee's YNoFace
        # Holdings Inc (CIK 1584209) filed the Oct 2016 Bank of
        # America Form 4 claiming 4.2B BAC shares (60% of the class).
        self.assertIn("1584209", f4.EXCLUDED_OWNER_CIKS)
        hit = {"owner_cik": "1584209", "owner_name": "YNOFACE Holdings Inc",
               "adsh": "0001584209-16-000008",
               "file_date": "2016-10-19", "form": "4"}
        xml = _xml([("Common Stock", 4201596806, "D")],
                   owners=(("1584209", "YNOFACE Holdings Inc"),))
        orig_enum, orig_fetch = f4.enumerate_filings, f4._fetch_many
        f4.enumerate_filings = lambda *a, **k: [hit]
        f4._fetch_many = lambda issuer, ads, cache: {
            "0001584209-16-000008": (xml, False, None)}
        try:
            entry, dg = f4.build_ticker("AAPL", "320193", 14532259000)
        finally:
            f4.enumerate_filings, f4._fetch_many = orig_enum, orig_fetch
        self.assertEqual(entry["owners_excluded_spoof"], 1)
        self.assertEqual(entry["insiders_total_shares"], 0)
        self.assertEqual(entry["owners_measured"], 0)


class TestEnumerationUnion(unittest.TestCase):
    def test_second_enumeration_run_fills_a_shortfall(self):
        # BAC, 2026-11-22: one efts run returned 1,335 hits and missed
        # Berkshire's latest filing; a later run returned 1,635. The
        # builder unions two runs, so a filing present only in the
        # second run still reaches the totals.
        cook = {"owner_cik": "1234567", "owner_name": "Cook Timothy D",
                "adsh": "0000320193-26-000001",
                "file_date": "2026-10-05", "form": "4"}
        brk = {"owner_cik": "1067983", "owner_name": "BERKSHIRE HATHAWAY INC",
               "adsh": "0000950170-24-115415",
               "file_date": "2024-10-17", "form": "4"}
        calls = {"n": 0}

        def fake_enum(*a, **k):
            calls["n"] += 1
            return [cook] if calls["n"] == 1 else [cook, brk]

        cook_xml = _xml([("Common Stock", 3237843, "D")])
        brk_xml = _xml([("Common Stock", 766305462, "D")],
                       owners=(("1067983", "BERKSHIRE HATHAWAY INC"),))
        orig_enum, orig_fetch = f4.enumerate_filings, f4._fetch_many
        f4.enumerate_filings = fake_enum
        f4._fetch_many = lambda issuer, ads, cache: {
            "0000320193-26-000001": (cook_xml, False, None),
            "0000950170-24-115415": (brk_xml, False, None)}
        try:
            entry, dg = f4.build_ticker("AAPL", "320193", 14532259000)
        finally:
            f4.enumerate_filings, f4._fetch_many = orig_enum, orig_fetch
        self.assertEqual(calls["n"], 2)
        self.assertEqual(dg["efts_union_extra"], 1)
        self.assertEqual(entry["owners_measured"], 2)
        self.assertEqual(entry["insiders_total_shares"],
                         3237843 + 766305462)


class TestLatestPerOwner(unittest.TestCase):
    def test_latest_file_date_wins_and_amendment_supersedes(self):
        hits = [
            {"owner_cik": "1", "owner_name": "A", "adsh": "0000000001-20-000001",
             "file_date": "2020-01-10", "form": "4"},
            {"owner_cik": "1", "owner_name": "A", "adsh": "0000000001-20-000002",
             "file_date": "2020-03-10", "form": "4/A"},
            {"owner_cik": "1", "owner_name": "A", "adsh": "0000000001-20-000003",
             "file_date": "2020-03-10", "form": "4"},
            {"owner_cik": "2", "owner_name": "B", "adsh": "0000000002-19-000001",
             "file_date": "2019-06-01", "form": "4"},
        ]
        by_owner = f4.latest_per_owner(hits)
        # The 4/A (Mar 10) beats the Jan original; among the two Mar 10
        # filings the later accession wins.
        self.assertEqual(by_owner["1"][0]["adsh"], "0000000001-20-000003")
        self.assertEqual(by_owner["1"][1]["adsh"], "0000000001-20-000002")
        self.assertEqual(by_owner["1"][2]["adsh"], "0000000001-20-000001")
        self.assertEqual(len(by_owner["2"]), 1)

    def test_joint_filing_appears_under_each_owner(self):
        hits = [
            {"owner_cik": "1", "owner_name": "A", "adsh": "0000000001-26-000001",
             "file_date": "2026-01-10", "form": "4"},
            {"owner_cik": "2", "owner_name": "B", "adsh": "0000000001-26-000001",
             "file_date": "2026-01-10", "form": "4"},
        ]
        by_owner = f4.latest_per_owner(hits)
        self.assertEqual(by_owner["1"][0]["adsh"], by_owner["2"][0]["adsh"])


class TestDedupIndirectMirrors(unittest.TestCase):
    def _holders(self):
        # Lachlan Murdoch (FOX): 1,952 direct + 85,372,810 indirect
        # "By LGC Holdco, LLC". LGC Holdco: the same 85,372,810 direct.
        return [
            {"name": "MURDOCH LACHLAN K", "cik": "1242818", "shares": 85374762,
             "filing_date": "2025-09-12", "accession": "a1",
             "indirect_buckets": [{"title": "Class B Common Stock",
                                   "shares": 85372810,
                                   "nature": "By LGC Holdco, LLC"}]},
            {"name": "LGC Holdco, LLC", "cik": "2082634", "shares": 85372810,
             "filing_date": "2025-09-12", "accession": "a2",
             "indirect_buckets": []},
            {"name": "MURDOCH  KEITH  RUPERT", "cik": "999", "shares": 1100862,
             "filing_date": "2025-11-25", "accession": "a3",
             "indirect_buckets": []},
        ]

    def test_mirror_bucket_removed_once(self):
        holders = self._holders()
        notes, removed = f4.dedup_indirect_mirrors(holders)
        self.assertEqual(removed, 85372810)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["owner_cik"], "1242818")
        self.assertEqual(notes[0]["via_cik"], "2082634")
        self.assertEqual(holders[0]["shares"], 1952)
        self.assertEqual(holders[0]["shares_gross"], 85374762)
        self.assertEqual(holders[1]["shares"], 85372810)
        self.assertEqual(sum(h["shares"] for h in holders),
                         1952 + 85372810 + 1100862)

    def test_bucket_naming_a_non_filer_is_kept(self):
        # The LKM Family Trust files no Form 4 of its own: Lachlan's
        # indirect holding through it is the only record of the block.
        holders = [
            {"name": "MURDOCH LACHLAN K", "cik": "1242818", "shares": 1401865,
             "filing_date": "2026-09-16", "accession": "a1",
             "indirect_buckets": [{"title": "Class A Common Stock",
                                   "shares": 1401713,
                                   "nature": "By LKM Family Trust"}]},
        ]
        notes, removed = f4.dedup_indirect_mirrors(holders)
        self.assertEqual(removed, 0)
        self.assertEqual(notes, [])
        self.assertEqual(holders[0]["shares"], 1401865)

    def test_amount_mismatch_is_kept(self):
        # The named holder's total differs from the bucket: not the same
        # block (or not only that block), so nothing is removed.
        holders = self._holders()
        holders[1]["shares"] = 90000000
        notes, removed = f4.dedup_indirect_mirrors(holders)
        self.assertEqual(removed, 0)
        self.assertEqual(holders[0]["shares"], 85374762)

    def test_ambiguous_name_never_dedups(self):
        holders = self._holders()
        holders.append({"name": "LGC Holdco, LLC", "cik": "555",
                        "shares": 100, "filing_date": "2025-01-01",
                        "accession": "a4", "indirect_buckets": []})
        notes, removed = f4.dedup_indirect_mirrors(holders)
        self.assertEqual(removed, 0)


class TestRankHolders(unittest.TestCase):
    def test_ranked_by_shares_desc_cik_asc_tiebreak(self):
        holders = [
            {"name": "B", "cik": "200", "shares": 5000,
             "filing_date": "2026-01-01", "accession": "a1"},
            {"name": "A", "cik": "100", "shares": 5000,
             "filing_date": "2026-01-01", "accession": "a2"},
            {"name": "C", "cik": "300", "shares": 9000,
             "filing_date": "2026-01-01", "accession": "a3"},
        ]
        top = f4.rank_holders(holders, 100000, top_n=2)
        self.assertEqual([t["cik"] for t in top], ["300", "100"])
        self.assertAlmostEqual(top[0]["pct"], 0.09)
        self.assertAlmostEqual(top[1]["pct"], 0.05)

    def test_zero_holding_ranks_last_but_is_kept(self):
        holders = [
            {"name": "A", "cik": "100", "shares": 0,
             "filing_date": "2026-01-01", "accession": "a1"},
            {"name": "B", "cik": "200", "shares": 10,
             "filing_date": "2026-01-01", "accession": "a2"},
        ]
        top = f4.rank_holders(holders, 1000, top_n=5)
        self.assertEqual([t["cik"] for t in top], ["200", "100"])
        self.assertEqual(top[1]["pct"], 0.0)


class TestForm4Url(unittest.TestCase):
    def test_url_uses_issuer_cik_not_adsh_prefix(self):
        # Apple adsh 0001140361-26-044952, verified live 2026-11-22:
        # the filing is under /data/320193/ (issuer), not /data/1140361/.
        self.assertEqual(
            f4.form4_url("320193", "0001140361-26-044952"),
            "https://www.sec.gov/Archives/edgar/data/320193/"
            "000114036126044952/form4.xml")
        # Leading zeros on the issuer CIK are stripped.
        self.assertEqual(
            f4.form4_url("0000320193", "0001140361-26-044952"),
            "https://www.sec.gov/Archives/edgar/data/320193/"
            "000114036126044952/form4.xml")


class TestIssuerCikOverride(unittest.TestCase):
    """XOM's Form 4s live under the operating company (34088), not the
    listed holding company (2115436) — the override is Form 4-only and
    data/cik-map.json stays on the generated CIK."""

    def test_xom_override(self):
        self.assertEqual(f4.issuer_cik_for("XOM", "2115436"), "34088")

    def test_passthrough(self):
        self.assertEqual(f4.issuer_cik_for("AAPL", "320193"), "320193")
        self.assertEqual(f4.issuer_cik_for("MSFT", "789019"), "789019")

    def test_override_map_has_xom_only(self):
        self.assertEqual(f4.FORM4_CIK_OVERRIDES, {"XOM": "34088"})


if __name__ == "__main__":
    unittest.main()
