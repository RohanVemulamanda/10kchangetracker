"""The Phase 2 run: saving, resuming, errors, quality flags, and the reports."""
import gzip
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401
from tracker import db, extract
from tracker.extract import connect_sections, run_extraction
from tracker.extract_report import write_phase2_summary, write_review_page

SENTENCE = "Our results could suffer if demand for our products falls or our costs rise sharply. "


def tenk_html(risk_words: int, reference_only: bool = False) -> bytes:
    body = ("Information in response to this Item 1A can be found in the Annual Report under Risk Factors."
            if reference_only else SENTENCE * (risk_words // 15))
    return (f"<html><body><p>Item 1. Business</p><p>We make things.</p><p>Item 1A. Risk Factors</p>"
            f"<p>{body}</p><p>Item 1B. Unresolved Staff Comments</p><p>None.</p></body></html>").encode()


def annual_report_html(risk_words: int) -> bytes:
    return (f"<html><body><p>Risk Factors</p><p>{SENTENCE * (risk_words // 15)}</p>"
            f"<p>Controls and Procedures</p><p>We maintain controls.</p></body></html>").encode()


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.raw = root / "raw"
        self.reports = root / "reports"
        self.conn = db.connect(root / "tracker.db")
        self.sconn = connect_sections(root / "sections.db")
        self.conn.execute("INSERT INTO companies (cik, name_current) VALUES (1, 'ACME CORP'), (2, 'BANKCO'), (3, 'ODDCO')")

    def tearDown(self):
        self.conn.close()
        self.sconn.close()
        self.tmp.cleanup()

    def add(self, acc, cik, fy, docs: dict, prior=None, role="sample", ex13=None):
        for name, content in docs.items():
            path = self.raw / "filings" / str(cik) / acc.replace("-", "") / (name + ".gz")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(gzip.compress(content))
        folder = f"filings/{cik}/{acc.replace('-', '')}/"
        main = next(iter(docs))
        self.conn.execute(
            "INSERT INTO filings (accession_number, cik, company_cik, fiscal_year, role, member_tickers, selected, status, "
            "primary_path, exhibit13_paths, prior_accession) VALUES (?,?,?,?,?,?,1,'downloaded',?,?,?)",
            (acc, cik, cik, fy, role, "TKR", folder + main + ".gz",
             json.dumps([folder + e + ".gz" for e in ex13]) if ex13 else None, prior))
        self.conn.commit()

    def status(self, acc):
        return dict(self.sconn.execute("SELECT * FROM sections WHERE accession_number = ?", (acc,)).fetchone())

    def test_run_flags_resumes_and_reports(self):
        self.add("A-21", 1, 2021, {"a21.htm": tenk_html(3000)}, role="comparison")
        self.add("A-22", 1, 2022, {"a22.htm": tenk_html(3100)}, prior="A-21")
        self.add("A-23", 1, 2023, {"a23.htm": tenk_html(12000)}, prior="A-22")                # 4x longer: length_jump
        self.add("B-22", 2, 2022, {"b22.htm": tenk_html(0, reference_only=True), "ex13.htm": annual_report_html(2500)},
                 ex13=["ex13.htm"])                                                          # found in the EX-13
        self.add("C-22", 3, 2022, {"c22.htm": tenk_html(600)})                                # short
        self.add("D-22", 3, 2022, {"d22.htm": b"<html><body><p>No risk section here.</p></body></html>"})

        counts = run_extraction(self.conn, self.sconn, self.raw)
        self.assertEqual(counts["attempted"], 6)
        self.assertEqual(self.status("A-22")["status"], "ok")
        self.assertEqual(self.status("A-23")["flags"], "length_jump")
        self.assertEqual((self.status("B-22")["method"], self.status("B-22")["status"]), ("heading_exhibit13", "ok"))
        self.assertEqual(self.status("C-22")["flags"], "short")
        self.assertEqual(self.status("D-22")["status"], "not_found")

        # Second run: nothing to redo.
        self.assertEqual(run_extraction(self.conn, self.sconn, self.raw)["attempted"], 0)
        # New code version: everything is redone.
        with mock.patch.object(extract, "EXTRACTOR_VERSION", "9.9"):
            self.assertEqual(run_extraction(self.conn, self.sconn, self.raw)["attempted"], 6)

        summary = write_phase2_summary(self.conn, self.sconn, self.reports)
        self.assertIn("## Sample filings only (the ones that get scored): 5 filings", summary)
        self.assertIn("- heading_exhibit13: 1", summary)
        flagged_csv = (self.reports / "phase2_flagged.csv").read_text(encoding="utf-8")
        self.assertEqual(flagged_csv.count("\n"), 4)  # header + A-23, C-22, D-22

        path, seed = write_review_page(self.conn, self.sconn, self.reports, how_many=3, seed=11)
        page = path.read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"class='card' data-id=", page)), 3)
        self.assertIn("--seed 11", page)
        self.assertIn("https://www.sec.gov/Archives/edgar/data/", page)

    def test_broken_file_is_recorded_and_the_run_continues(self):
        self.add("A-22", 1, 2022, {"a22.htm": tenk_html(3000)})
        self.add("E-22", 1, 2022, {"e22.htm": b""})
        (self.raw / "filings/1/E22/e22.htm.gz").write_bytes(b"not gzip")
        counts = run_extraction(self.conn, self.sconn, self.raw)
        self.assertEqual((counts["ok"], counts["error"]), (1, 1))
        self.assertIn("BadGzipFile", self.status("E-22")["error"])
        # Errors are retried on the next run.
        self.assertEqual(run_extraction(self.conn, self.sconn, self.raw)["attempted"], 1)


if __name__ == "__main__":
    unittest.main()
