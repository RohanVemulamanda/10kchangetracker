"""The whole Phase 1 flow (find filings -> download -> summary) on a small fake world.

Three companies:
  ACME   (CIK 1) in the index the whole time
  NEWCO  (CIK 2) joined the index on 2022-06-01
  META   (CIK 3) was "FB" until 2022-06-09. FB is deliberately left unmapped, to show
         how a missing ticker mapping drops filings and shows up in the gap report.
"""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from helpers import make_client, ok, submissions_columns, tenk
from tracker import db
from tracker.downloader import download_pending
from tracker.header import document_url, index_headers_url
from tracker.pipeline import step_find_filings, step_spot_check
from tracker.submissions import SUBMISSIONS_URL
from tracker.summary import write_summary

BIG_DOC = "<html>" + "Risk factor text. " * 2000 + "</html>"


def header_for(cik: int, accession: str, period: str, name: str) -> str:
    return (
        f"<SEC-HEADER>\n<ACCEPTANCE-DATETIME>{period.replace('-', '')[:4]}0220163000\n"
        f"CONFORMED SUBMISSION TYPE:\t10-K\nCONFORMED PERIOD OF REPORT:\t{period.replace('-', '')}\n"
        f"FILER:\n\tCOMPANY DATA:\n\t\tCOMPANY CONFORMED NAME:\t{name}\n\t\tCENTRAL INDEX KEY:\t{cik:010d}\n"
        f"\t\tSTANDARD INDUSTRIAL CLASSIFICATION:\tSERVICES [7372]\n</SEC-HEADER>\n"
        f"<DOCUMENT>\n<TYPE>10-K\n<SEQUENCE>1\n<FILENAME>doc.htm\n</DOCUMENT>\n"
    )


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.settings = {
            "paths": {"db": str(root / "t.db"), "raw_dir": str(root / "raw"), "reference_dir": str(root / "ref"),
                      "reports_dir": str(root / "reports"), "logs_dir": str(root / "logs")},
            "sample": {"start_fiscal_year": 2021, "end_fiscal_year": 2023, "form": "10-K",
                       "prior_year_min_days": 300, "prior_year_max_days": 430},
            "sec": {"refresh_submissions": False},
        }
        self.reports = root / "reports"
        self.conn = db.connect(root / "t.db")
        self.conn.executemany(
            "INSERT INTO membership (ticker, sec_ticker, start_date, end_date) VALUES (?, ?, ?, ?)",
            [("ACME", "ACME", "2000-01-01", None), ("NEWCO", "NEWCO", "2022-06-01", None),
             ("FB", "FB", "2013-12-23", "2022-06-09"), ("META", "META", "2022-06-09", None)],
        )
        self.conn.executemany(
            "INSERT INTO ticker_map (sec_ticker, cik, source) VALUES (?, ?, ?)",
            [("ACME", 1, "sec_current"), ("NEWCO", 2, "sec_current"), ("META", 3, "sec_current"), ("FB", None, "unmapped")],
        )
        self.conn.execute("INSERT INTO membership VALUES ('BANK', 'BANK', '2010-01-01', '2023-03-15')")
        self.conn.execute("INSERT INTO ticker_map (sec_ticker, cik, source, sec_title, note) "
                          "VALUES ('BANK', NULL, 'not_on_edgar', 'Some Bank', 'files with the FDIC')")
        self.conn.commit()

        routes = {}
        for cik, name in [(1, "ACME CORP"), (2, "NEWCO INC"), (3, "META PLATFORMS")]:
            filings = []
            for year in range(2019, 2025):
                acc = f"{cik:010d}-{str(year + 1)[2:]}-000001"
                filings.append(tenk(acc, f"{year + 1}-02-20", f"{year}-12-31"))
                routes[index_headers_url(cik, acc)] = ok(header_for(cik, acc, f"{year}-12-31", name))
                routes[document_url(cik, acc, "doc.htm")] = ok(BIG_DOC)
            main = {"name": name, "sic": "7372", "tickers": [], "filings": {"recent": submissions_columns(filings), "files": []}}
            routes[SUBMISSIONS_URL.format(cik=cik)] = ok(main)
        self.client, self.session, _ = make_client(routes)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_full_flow(self):
        stats = step_find_filings(self.settings, self.conn, self.client)
        roles = {(r["cik"], r["fiscal_year"]): r["role"] for r in
                 self.conn.execute("SELECT cik, fiscal_year, role FROM filings WHERE selected = 1")}

        # ACME: FY2021-2023 sampled, FY2020 downloaded as the comparison.
        self.assertEqual({fy: roles.get((1, fy)) for fy in range(2020, 2024)},
                         {2020: "comparison", 2021: "sample", 2022: "sample", 2023: "sample"})
        # NEWCO joined mid-2022: FY2022-2023 sampled; FY2021 (filed before joining) is its comparison.
        self.assertEqual({fy: roles.get((2, fy)) for fy in range(2020, 2024)},
                         {2020: None, 2021: "comparison", 2022: "sample", 2023: "sample"})
        # META: the FY2021 10-K was filed in Feb 2022 under ticker FB, which is unmapped, so it drops
        # out of the sample. It is still downloaded, but only as the comparison for FY2022.
        self.assertEqual(roles.get((3, 2021)), "comparison")
        self.assertEqual(stats["sample"], 3 + 2 + 2)

        counts = download_pending(self.conn, self.client, Path(self.settings["paths"]["raw_dir"]), max_attempts=3)
        self.assertEqual((counts["downloaded"], counts["failed"]), (stats["sample"] + stats["comparison"], 0))

        requests_before = len(self.session.requested)
        step_find_filings(self.settings, self.conn, self.client)          # second run:
        download_pending(self.conn, self.client, Path(self.settings["paths"]["raw_dir"]), max_attempts=3)
        self.assertEqual(len(self.session.requested), requests_before)    # nothing downloaded again

        text = write_summary(self.conn, self.settings, self.reports, Path(self.settings["paths"]["reference_dir"]))
        self.assertIn("**Unmapped tickers: 1**", text)       # FB only; BANK is counted separately
        self.assertIn("**Not on EDGAR: 1**", text)
        self.assertIn("FB", text)
        self.assertIn("| 2022 | 3 |", text)  # three companies sampled in FY2022
        gaps = (self.reports / "gaps.csv").read_text(encoding="utf-8")
        self.assertIn("unmapped_ticker", gaps)

        printed = io.StringIO()
        with redirect_stdout(printed):
            step_spot_check(self.conn, how_many=3, seed=7)
        self.assertEqual(printed.getvalue().count("https://www.sec.gov/Archives/edgar/data/"), 3)

    def test_company_that_loses_its_ticker_leaves_the_sample(self):
        # Like PARA: first mapped to the wrong company (CIK 2), then corrected to CIK 3.
        step_find_filings(self.settings, self.conn, self.client)
        self.assertGreater(self.conn.execute("SELECT COUNT(*) FROM filings WHERE selected = 1 AND company_cik = 2").fetchone()[0], 0)
        self.conn.execute("UPDATE ticker_map SET cik = 3 WHERE sec_ticker = 'NEWCO'")
        self.conn.commit()
        stats = step_find_filings(self.settings, self.conn, self.client)
        self.assertGreater(stats["dropped_unmapped"], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM filings WHERE selected = 1 AND company_cik = 2").fetchone()[0], 0)

    def test_company_that_changed_sec_id(self):
        # OILCO moved under a new holding company (CIK 50) that hasn't filed a 10-K yet.
        # Every 10-K so far was filed under the old ID (CIK 40). This is Exxon's situation in 2026.
        ref = Path(self.settings["paths"]["reference_dir"])
        ref.mkdir(parents=True, exist_ok=True)
        (ref / "predecessors.csv").write_text(
            "successor_cik,predecessor_cik,company_name,event,evidence\n50,40,Oilco,new holding company,8-K12B\n",
            encoding="utf-8")
        self.conn.execute("INSERT INTO membership VALUES ('OIL', 'OIL', '2000-01-01', NULL)")
        self.conn.execute("INSERT INTO ticker_map (sec_ticker, cik, source) VALUES ('OIL', 50, 'sec_current')")
        self.conn.commit()
        routes = self.session.routes
        routes[SUBMISSIONS_URL.format(cik=50)] = ok({"name": "OILCO HOLDINGS", "tickers": ["OIL"],
                                                     "filings": {"recent": submissions_columns([]), "files": []}})
        old = []
        for year in range(2019, 2025):
            acc = f"{40:010d}-{str(year + 1)[2:]}-000001"
            old.append(tenk(acc, f"{year + 1}-02-20", f"{year}-12-31"))
            routes[index_headers_url(40, acc)] = ok(header_for(40, acc, f"{year}-12-31", "OILCO"))
            routes[document_url(40, acc, "doc.htm")] = ok(BIG_DOC)
        routes[SUBMISSIONS_URL.format(cik=40)] = ok({"name": "OILCO", "filings": {"recent": submissions_columns(old), "files": []}})

        step_find_filings(self.settings, self.conn, self.client, only_tickers=["OIL"])
        rows = self.conn.execute("SELECT cik, fiscal_year, role FROM filings WHERE selected = 1 AND company_cik = 50").fetchall()
        self.assertEqual(sorted((r["fiscal_year"], r["role"], r["cik"]) for r in rows),
                         [(2020, "comparison", 40), (2021, "sample", 40), (2022, "sample", 40), (2023, "sample", 40)])
        self.assertIsNone(self.conn.execute("SELECT mapping_check FROM companies WHERE cik = 50").fetchone()[0])

        # A trial run limited to this company must still download the old ID's filings.
        counts = download_pending(self.conn, self.client, Path(self.settings["paths"]["raw_dir"]), max_attempts=3, ciks=[50])
        self.assertEqual((counts["downloaded"], counts["failed"]), (4, 0))

        text = write_summary(self.conn, self.settings, self.reports, ref)
        self.assertIn("Oilco: CIK 40 -> 50", text)
        self.assertIn("4 filings from the old ID", text)
        self.assertNotIn("member_but_no_sample_10k", (self.reports / "gaps.csv").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
