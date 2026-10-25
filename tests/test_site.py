"""Phase 5: the dashboard's data files (D-038)."""
import json
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401
from tracker import db
from tracker.extract import connect_sections
from tracker.score import connect_changes
from tracker.site import build_site, change_percentile


class Percentile(unittest.TestCase):
    def test_share_of_research_filings_that_changed_less(self):
        research = sorted([0.90, 0.95, 0.98, 0.99, 1.00])
        self.assertEqual(change_percentile(0.90, research), 80.0)   # 4 of 5 are more similar (changed less)
        self.assertEqual(change_percentile(1.00, research), 0.0)
        self.assertEqual(change_percentile(0.80, research), 100.0)


class BuildSite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.reference = self.root / "reference"
        self.reference.mkdir()
        self.conn = db.connect(self.root / "tracker.db")
        self.sconn = connect_sections(self.root / "sections.db")
        self.cconn = connect_changes(self.root / "changes.db")
        self.conn.execute("INSERT INTO companies (cik, name_current, sic_description) VALUES (1, 'ACME CORP', 'Widgets')")
        self.add("p20", 2020, "2021-02-01", "comparison", None, None)
        self.add("s21", 2021, "2022-02-01", "sample", "p20", 0.99)
        self.add("s22", 2022, "2023-02-01", "sample", "s21", 0.95, flags="voice_switch")
        self.add("l25", 2025, "2026-02-01", "live", "s22", 0.30)          # extreme: on the review list
        self.cconn.executemany("INSERT INTO changed_sentences (accession_number, section, kind, position, text) "
                               "VALUES ('s21', 'item_1a', ?, ?, ?)",
                               [("added", 0, "A brand new risk."), ("added", 1, "Moved sentence."),
                                ("removed", 0, "Moved sentence."), ("removed", 1, "An old risk.")])
        self.cconn.commit()

    def tearDown(self):
        for c in (self.conn, self.sconn, self.cconn):
            c.close()
        self.tmp.cleanup()

    def add(self, acc, fy, filed, role, prior, cosine, flags=None):
        self.conn.execute("INSERT INTO filings (accession_number, cik, company_cik, fiscal_year, filing_date, role, "
                          "prior_accession, member_tickers, selected) VALUES (?, 1, 1, ?, ?, ?, ?, 'ACME', 1)",
                          (acc, fy, filed, role, prior))
        self.conn.commit()
        self.sconn.execute("INSERT INTO sections (accession_number, section, status) VALUES (?, 'item_1a', 'ok')", (acc,))
        self.sconn.commit()
        if cosine is not None:
            self.cconn.execute(
                "INSERT INTO changes (accession_number, section, version, status, sim_cosine, sim_jaccard, sim_min_edit, "
                "sim_simple, prior_words, current_words, sentences_kept, flags) "
                "VALUES (?, 'item_1a', 'main', 'ok', ?, 0.9, 0.8, 0.7, 100, 110, 5, ?)", (acc, cosine, flags))
            self.cconn.commit()

    def build(self):
        out = self.root / "site"
        build_site(self.conn, self.sconn, self.cconn, self.reference, out)
        read = lambda name: json.loads((out / "data" / name).read_text())
        return out, read

    def test_files_and_company_page(self):
        out, read = self.build()
        for name in ("index.html", "app.js", "style.css"):
            self.assertTrue((out / name).exists(), name)
        company = read("c/1.json")
        self.assertEqual([y["fiscal_year"] for y in company["years"]], [2021, 2022])   # the extreme live one is held back
        fy21 = company["years"][0]
        self.assertEqual((fy21["new"], fy21["dropped"], fy21["moved"]), (["A brand new risk."], ["An old risk."], 1))
        self.assertEqual(fy21["prior_fiscal_year"], 2020)
        self.assertEqual(read("companies.json")[0]["name"], "ACME CORP")

    def test_approved_live_filing_is_shown(self):
        (self.reference / "live_approved.csv").write_text("accession_number,note\nl25,checked: real rewrite\n")
        _, read = self.build()
        years = read("c/1.json")["years"]
        self.assertEqual(years[-1]["fiscal_year"], 2025)
        self.assertTrue(years[-1]["live"])

    def test_season_leaves_out_flagged_filings(self):
        self.conn.execute("UPDATE filings SET filing_date = '2023-03-01' WHERE accession_number = 's21'")
        self.conn.commit()
        _, read = self.build()
        season = read("season.json")
        self.assertEqual(season["year"], "2023")
        self.assertEqual([f["fiscal_year"] for f in season["top"]], [2021])              # FY2022 is a voice switch
        self.assertEqual(season["flagged_left_out"], 1)


if __name__ == "__main__":
    unittest.main()
