import tempfile
import unittest
from pathlib import Path

from helpers import make_client, ok
from tracker.ticker_map import (SEC_TICKERS_URL, load_manual_map, load_not_on_edgar, load_predecessors,
                                load_sec_ticker_map, map_tickers)

SEC_MAP = {"AAPL": {"cik": 320193, "title": "Apple Inc."}, "META": {"cik": 1326801, "title": "Meta Platforms"}}


class MappingOrder(unittest.TestCase):
    def test_manual_beats_sec_beats_wikipedia(self):
        manual = {"FB": {"cik": 1326801, "title": "Meta Platforms (formerly Facebook)", "evidence": "x"}}
        rows = {r["sec_ticker"]: r for r in map_tickers({"AAPL", "FB", "NEWCO", "GONE"}, SEC_MAP, manual, {"NEWCO": 999})}
        self.assertEqual((rows["FB"]["cik"], rows["FB"]["source"]), (1326801, "manual"))
        self.assertEqual((rows["AAPL"]["cik"], rows["AAPL"]["source"]), (320193, "sec_current"))
        self.assertEqual((rows["NEWCO"]["cik"], rows["NEWCO"]["source"]), (999, "wikipedia_current"))
        self.assertEqual((rows["GONE"]["cik"], rows["GONE"]["source"]), (None, "unmapped"))

    def test_disagreement_with_wikipedia_is_noted(self):
        rows = map_tickers({"AAPL"}, SEC_MAP, {}, {"AAPL": 111})
        self.assertIn("Wikipedia says CIK 111", rows[0]["note"])


class SecTickerFile(unittest.TestCase):
    def test_parses_sec_format(self):
        data = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
                "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"}}
        client, _, _ = make_client({SEC_TICKERS_URL: ok(data)})
        with tempfile.TemporaryDirectory() as tmp:
            mapping = load_sec_ticker_map(client, Path(tmp))
        self.assertEqual(mapping["BRK-B"]["cik"], 1067983)
        self.assertEqual(mapping["AAPL"]["title"], "Apple Inc.")


class ManualFile(unittest.TestCase):
    def test_reads_rows_and_normalizes_tickers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual.csv"
            path.write_text("ticker,cik,company_name,evidence\nbf.b,14693,Brown-Forman,checked on EDGAR\n", encoding="utf-8")
            self.assertEqual(load_manual_map(path)["BF-B"]["cik"], 14693)

    def test_bad_cik_is_an_error_not_a_guess(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual.csv"
            path.write_text("ticker,cik,company_name,evidence\nXYZ,abc,Some Co,\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_manual_map(path)

    def test_missing_file_means_no_fixes(self):
        self.assertEqual(load_manual_map(Path("does/not/exist.csv")), {})

    def test_every_row_needs_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual.csv"
            path.write_text("ticker,cik,company_name,evidence\nXYZ,123,Some Co,\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_manual_map(path)


class NotOnEdgar(unittest.TestCase):
    def test_listed_company_is_excluded_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "not_on_edgar.csv"
            path.write_text('ticker,company_name,reason,evidence\nSBNY,Signature Bank,"files with the FDIC","press release"\n',
                            encoding="utf-8")
            entries = load_not_on_edgar(path)
        rows = {r["sec_ticker"]: r for r in map_tickers({"SBNY", "AAPL"}, SEC_MAP, {}, {}, entries)}
        self.assertEqual((rows["SBNY"]["cik"], rows["SBNY"]["source"]), (None, "not_on_edgar"))
        self.assertIn("FDIC", rows["SBNY"]["note"])
        self.assertEqual(rows["AAPL"]["source"], "sec_current")

    def test_reason_and_evidence_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "not_on_edgar.csv"
            path.write_text("ticker,company_name,reason,evidence\nSBNY,Signature Bank,,\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_not_on_edgar(path)


class Predecessors(unittest.TestCase):
    def test_reads_links_and_rejects_bad_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "predecessors.csv"
            header = "successor_cik,predecessor_cik,company_name,event,evidence\n"
            path.write_text(header + "200,100,Acme,new holding company,8-K12B link\n", encoding="utf-8")
            self.assertEqual(load_predecessors(path), {200: [100]})
            path.write_text(header + "200,100,Acme,new holding company,\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_predecessors(path)
            path.write_text(header + "200,200,Acme,oops,evidence\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_predecessors(path)


class ProjectMappingFiles(unittest.TestCase):
    """Checks on the real hand-made files in data/reference/."""
    REF = Path(__file__).resolve().parents[1] / "data" / "reference"

    def test_predecessor_evidence_links_point_to_one_of_the_two_ids(self):
        import csv
        import re
        with open(self.REF / "predecessors.csv", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                ids = {int(row["successor_cik"]), int(row["predecessor_cik"])}
                for url_cik in re.findall(r"edgar/data/0*(\d+)/", row["evidence"]):
                    self.assertIn(int(url_cik), ids, f"{row['company_name']}: link points to an unrelated CIK")
        self.assertTrue(load_predecessors(self.REF / "predecessors.csv"))

    def test_files_load_and_evidence_links_match_the_cik(self):
        import re
        manual = load_manual_map(self.REF / "manual_cik_map.csv")
        load_not_on_edgar(self.REF / "not_on_edgar.csv")
        for ticker, row in manual.items():
            for url_cik in re.findall(r"edgar/data/0*(\d+)/", row["evidence"]):
                self.assertEqual(int(url_cik), row["cik"], f"{ticker}: evidence link points to a different CIK")


if __name__ == "__main__":
    unittest.main()
