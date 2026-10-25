"""Phase 5: today's S&P 500 list, new filings, and the review list (D-036, D-037)."""
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401
from tracker import db
from tracker.extract import connect_sections
from tracker.live import MemberListError, check_members, live_rows, parse_member_table, review_reasons
from tracker.score import connect_changes

PAGE = b"""<html><body><table id="constituents">
<tr><th>Symbol</th><th>Security</th><th>GICS Sector</th><th>GICS Sub-Industry</th><th>Headquarters Location</th>
<th>Date added</th><th>CIK</th><th>Founded</th></tr>
<tr><td>BRK.B</td><td>Berkshire Hathaway</td><td>Financials</td><td>Multi-Sector Holdings</td><td>Omaha</td>
<td>2010-02-16</td><td>0001067983</td><td>1839</td></tr>
<tr><td>AAPL</td><td>Apple Inc.</td><td>Information Technology</td><td>Technology Hardware</td><td>Cupertino</td>
<td>1982-11-30</td><td>0000320193</td><td>1977</td></tr>
</table></body></html>"""


def tenk(accession, report_date, filing_date, form="10-K"):
    return {"accessionNumber": accession, "form": form, "reportDate": report_date, "filingDate": filing_date,
            "primaryDocument": "doc.htm", "acceptanceDateTime": filing_date + "T16:30:00.000Z"}


class MemberList(unittest.TestCase):
    def test_parse(self):
        members = parse_member_table(PAGE)
        self.assertEqual(members[0], {"sec_ticker": "BRK-B", "name": "Berkshire Hathaway", "sector": "Financials",
                                      "sub_industry": "Multi-Sector Holdings", "cik": 1067983})
        self.assertEqual(members[1]["cik"], 320193)

    def test_layout_change_is_an_error(self):
        with self.assertRaises(MemberListError):
            parse_member_table(b"<html><table id='other'><tr><th>x</th></tr></table></html>")
        with self.assertRaises(MemberListError):
            parse_member_table(PAGE.replace(b"<th>CIK</th>", b"<th>Central Index Key</th>"))

    def test_list_must_look_like_the_sp500(self):
        member = {"sec_ticker": "X", "cik": 1}
        with self.assertRaises(MemberListError):
            check_members([member] * 2)                                   # far too few
        check_members([member] * 503)
        with self.assertRaises(MemberListError):
            check_members([member] * 497 + [{"sec_ticker": "Y", "cik": None}] * 6)  # CIKs missing


class LiveRows(unittest.TestCase):
    FILINGS = [tenk("fy24", "2024-12-31", "2025-02-10"), tenk("fy25", "2025-12-31", "2026-02-09"),
               tenk("fy25a", "2025-12-31", "2026-03-01", form="10-K/A")]

    def test_new_filing_added_as_live_with_its_prior(self):
        new, relinked = live_rows(1, self.FILINGS, {"ACME"}, 2021, "2019-01-01", existing={"fy24": "sample"})
        self.assertEqual([(r["accession_number"], r["role"], r["prior_accession"], r["fiscal_year"]) for r in new],
                         [("fy25", "live", "fy24", 2025)])               # the amendment is left out (D-005)
        self.assertEqual(relinked, [])

    def test_research_rows_are_never_touched(self):
        new, relinked = live_rows(1, self.FILINGS, {"ACME"}, 2021, "2019-01-01",
                                  existing={"fy24": "sample", "fy25": "sample"})
        self.assertEqual((new, relinked), ([], []))

    def test_stored_live_rows_are_offered_for_relinking(self):
        """After a company is added to predecessors.csv, its live filing gets a prior year (D-018)."""
        new, relinked = live_rows(1, self.FILINGS, {"ACME"}, 2021, "2019-01-01",
                                  existing={"fy24": "live_comparison", "fy25": "live"})
        self.assertEqual(new, [])
        self.assertEqual([(r["accession_number"], r["prior_accession"]) for r in relinked], [("fy25", "fy24")])

    def test_new_member_gets_its_history_and_first_comparison(self):
        new, _ = live_rows(1, self.FILINGS, {"ACME"}, 2025, "2019-01-01", existing={})
        self.assertEqual({(r["accession_number"], r["role"]) for r in new},
                         {("fy25", "live"), ("fy24", "live_comparison")})


class ReviewReasons(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.conn = db.connect(root / "tracker.db")
        self.sconn = connect_sections(root / "sections.db")
        self.cconn = connect_changes(root / "changes.db")
        # 100 research pairs with cosine 0.900 ... 0.999, and three live filings
        for i in range(100):
            self.add(f"s{i}", "sample", "ok", 0.9 + i / 1000)
        self.add("ok", "live", "ok", 0.99)
        self.add("odd", "live", "ok", 0.50)
        self.add("bad", "live", "flagged", 0.99, extraction_flags="short")

    def tearDown(self):
        for c in (self.conn, self.sconn, self.cconn):
            c.close()
        self.tmp.cleanup()

    def add(self, acc, role, extraction, cosine, extraction_flags=None):
        self.conn.execute("INSERT INTO filings (accession_number, cik, role, selected) VALUES (?, 1, ?, 1)", (acc, role))
        self.sconn.execute("INSERT INTO sections (accession_number, section, status, flags) VALUES (?, 'item_1a', ?, ?)",
                           (acc, extraction, extraction_flags))
        self.cconn.execute("INSERT INTO changes (accession_number, section, version, status, sim_cosine, sim_jaccard) "
                           "VALUES (?, 'item_1a', 'main', 'ok', ?, 0.9)", (acc, cosine))

    def test_reasons(self):
        reasons = review_reasons(self.conn, self.sconn, self.cconn)
        self.assertEqual(set(reasons), {"ok", "odd", "bad"})              # live filings only
        self.assertEqual(reasons["ok"], [])
        self.assertIn("below the research sample's 1st percentile", reasons["odd"][0])
        self.assertEqual(reasons["bad"], ["extraction flagged (short)"])


if __name__ == "__main__":
    unittest.main()
