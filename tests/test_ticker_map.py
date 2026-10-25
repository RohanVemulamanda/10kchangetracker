import tempfile
import unittest
from pathlib import Path

from helpers import make_client, ok
from tracker.ticker_map import SEC_TICKERS_URL, load_manual_map, load_sec_ticker_map, map_tickers

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


if __name__ == "__main__":
    unittest.main()
