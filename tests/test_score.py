"""The Phase 3 run: scoring pairs both ways, unscored cases, resuming, overrides, reports."""
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401
from tracker import db
from tracker.extract import connect_sections
from tracker.score import connect_changes, run_scoring
from tracker.score_report import write_phase3_summary, write_score_review_page

BODY = ("Risks Related to Our Business\n"
        "Demand for our products may fall. Our costs could rise sharply in fiscal 2024.\n"
        "Competition is intense. We depend on a few large customers.\n")
SUMMARY = ("Risk Factor Summary\n"
           "demand for our products may fall;\n"
           "competition is intense;\n"
           "we depend on a few large customers.\n")


class Scoring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.reference = root / "reference"
        self.reference.mkdir()
        self.reports = root / "reports"
        self.conn = db.connect(root / "tracker.db")
        self.sconn = connect_sections(root / "sections.db")
        self.cconn = connect_changes(root / "changes.db")
        self.conn.execute("INSERT INTO companies (cik, name_current) VALUES (1, 'ACME CORP'), (2, 'NEWCO')")
        # ACME: FY2020 (comparison only) -> FY2021 adds a summary -> FY2022 unchanged except a number
        self.add("a20", 1, 2020, BODY, role="comparison")
        self.add("a21", 1, 2021, SUMMARY + BODY, prior="a20")
        self.add("a22", 1, 2022, SUMMARY + BODY.replace("2024", "2025"), prior="a21")
        # NEWCO: a spin-off's first 10-K, no prior year (D-019)
        self.add("n21", 2, 2021, BODY)

    def tearDown(self):
        for c in (self.conn, self.sconn, self.cconn):
            c.close()
        self.tmp.cleanup()

    def add(self, acc, cik, fy, text, prior=None, role="sample"):
        self.conn.execute("INSERT INTO filings (accession_number, cik, company_cik, fiscal_year, role, selected, status, "
                          "prior_accession) VALUES (?, ?, ?, ?, ?, 1, 'downloaded', ?)", (acc, cik, cik, fy, role, prior))
        self.conn.commit()
        self.sconn.execute("INSERT INTO sections (accession_number, section, status, method, source_document, scoring_text) "
                           "VALUES (?, 'item_1a', 'ok', ?, ?, ?)",
                           (acc, "heading" if acc == "a20" else "item", f"filings/{cik}/{acc}/doc.htm.gz", text))
        self.sconn.commit()

    def run_scoring(self, **kwargs):
        return run_scoring(self.conn, self.sconn, self.cconn, self.reference, **kwargs)

    def score(self, acc, version="main"):
        return dict(self.cconn.execute("SELECT * FROM changes WHERE accession_number = ? AND version = ?",
                                       (acc, version)).fetchone())

    def test_summary_added_changes_only_the_with_summary_score(self):
        """The year a summary appears: removed (main) it's identical; kept, it looks changed (D-029)."""
        self.run_scoring()
        self.assertEqual(self.score("a21")["sim_jaccard"], 1.0)
        self.assertEqual(self.score("a21")["sim_simple"], 1.0)
        self.assertLess(self.score("a21", "with_summary")["sim_simple"], 1.0)

    def test_changed_number_is_not_a_change(self):
        self.run_scoring()
        row = self.score("a22")
        self.assertEqual((row["sim_cosine"], row["sim_min_edit"], row["sentences_added"]), (1.0, 1.0, 0))

    def test_first_10k_is_unscored(self):
        counts = self.run_scoring()
        self.assertEqual(counts["unscored"], 1)
        self.assertEqual(self.score("n21")["status"], "unscored")
        self.assertIn("D-019", self.score("n21")["note"])

    def test_comparison_filings_are_not_scored_themselves(self):
        self.run_scoring()
        self.assertIsNone(self.cconn.execute("SELECT 1 FROM changes WHERE accession_number = 'a20'").fetchone())

    def test_summaries_are_recorded(self):
        self.run_scoring()
        rows = {r["accession_number"]: dict(r) for r in self.cconn.execute("SELECT * FROM risk_summaries")}
        self.assertEqual(set(rows), {"a21", "a22"})
        self.assertEqual(rows["a21"]["first_kept_line"], "Risks Related to Our Business")

    def test_changed_sentences_saved_for_main_version(self):
        self.add("b20", 1, 2020, "Old risk one. Shared risk two.", role="comparison")
        self.conn.execute("UPDATE filings SET prior_accession = 'b20' WHERE accession_number = 'a21'")
        self.conn.commit()
        self.run_scoring()
        kinds = self.cconn.execute("SELECT kind, COUNT(*) FROM changed_sentences WHERE accession_number = 'a21' "
                                   "GROUP BY kind").fetchall()
        # BODY has 4 sentences (the heading joins the first, D-028); none were in b20
        self.assertEqual(dict(kinds), {"added": 4, "removed": 2})

    def test_second_run_skips_and_changed_text_is_redone(self):
        self.run_scoring()
        self.assertEqual(self.run_scoring()["scored"], 0)
        self.sconn.execute("UPDATE sections SET scoring_text = ? WHERE accession_number = 'a22'", (BODY + "A new risk.",))
        self.sconn.commit()
        counts = self.run_scoring()
        self.assertEqual(counts["scored"], 1)
        self.assertEqual(self.score("a22")["sentences_added"], 1)

    def test_override_that_does_not_match_stops_the_run(self):
        (self.reference / "summary_overrides.csv").write_text(
            "accession_number,company,fiscal_year,first_line_after_summary,evidence\n"
            "a21,ACME,2021,No such line,test\n")
        with self.assertRaises(RuntimeError):
            self.run_scoring()

    def test_override_sets_the_end(self):
        (self.reference / "summary_overrides.csv").write_text(
            "accession_number,company,fiscal_year,first_line_after_summary,evidence\n"
            "a21,ACME,2021,competition is intense;,test\n")
        self.run_scoring()
        row = dict(self.cconn.execute("SELECT * FROM risk_summaries WHERE accession_number = 'a21'").fetchone())
        self.assertEqual((row["rule"], row["end_line"]), ("override", 2))

    def test_reports_are_written(self):
        self.run_scoring()
        text = write_phase3_summary(self.conn, self.cconn, self.reports)
        self.assertIn("| Scored | 2 |", text)
        for name in ("phase3_summary.md", "phase3_scores.csv", "phase3_summaries.csv"):
            self.assertTrue((self.reports / name).exists(), name)

    def test_review_page(self):
        self.run_scoring()
        path, seed = write_score_review_page(self.conn, self.sconn, self.cconn, self.reports, how_many=1, seed=5)
        page = path.read_text()
        self.assertEqual(seed, 5)
        self.assertIn("ACME CORP (None) FY2020 -&gt; FY2021", page)   # a21 compares with a20 (heading method)
        self.assertIn("Every pair with a fallback-method extraction (1)", page)
        self.assertIn("removed 19 words", page)                        # the 4-line summary in a21
        self.assertIn("We depend on a few large customers.</div>", page)  # "Ends" skips the blank last line


if __name__ == "__main__":
    unittest.main()
