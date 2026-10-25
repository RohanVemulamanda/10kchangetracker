import gzip
import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURES
from tracker import db
from tracker.cover import check_filers, parse_public_float


def tag(text: str, **attrs) -> bytes:
    extra = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    return f'<ix:nonFraction name="dei:EntityPublicFloat" unitRef="usd" {extra}>{text}</ix:nonFraction>'.encode()


class ParseFloat(unittest.TestCase):
    def test_scales(self):
        self.assertEqual(parse_public_float(tag("434.37", scale="9")), 434.37e9)
        self.assertEqual(parse_public_float(tag("23,377", scale="6")), 23_377e6)
        self.assertEqual(parse_public_float(tag("3,253,431,000,000", scale="0")), 3_253_431_000_000)
        self.assertEqual(parse_public_float(tag("5,090,724,127")), 5_090_724_127)

    def test_takes_the_largest_and_ignores_text(self):
        raw = tag("1.5", scale="9") + tag("12.0", scale="9") + tag("none", scale="9")
        self.assertEqual(parse_public_float(raw), 12e9)

    def test_impossible_value_from_a_tagging_mistake(self):
        # Zimmer Biomet 2021: full dollar amount written out, but tagged as millions
        self.assertEqual(parse_public_float(tag("33,533,707,317", scale="6")), 33_533_707_317)

    def test_not_tagged(self):
        self.assertIsNone(parse_public_float(b"<html><p>No cover page facts</p></html>"))

    def test_real_filing(self):
        with gzip.open(FIXTURES / "filings/320193/000032019325000079/aapl-20250927.htm.gz") as f:
            self.assertAlmostEqual(parse_public_float(f.read()), 3.253431e12, delta=1e9)


class CheckFilers(unittest.TestCase):
    def test_small_company_is_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conn = db.connect(root / "t.db")
            for acc, cik, content in [("BIG", 1, tag("250.0", scale="9")), ("SMALL", 2, tag("212,750,000", scale="0"))]:
                path = root / "raw" / f"{acc}.htm.gz"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(gzip.compress(content))
                conn.execute("INSERT INTO filings (accession_number, cik, company_cik, fiscal_year, role, selected, status, "
                             "primary_path, member_tickers) VALUES (?, ?, ?, 2023, 'sample', 1, 'downloaded', ?, 'TKR')",
                             (acc, cik, cik, f"{acc}.htm.gz"))
            conn.commit()
            counts = check_filers(conn, root / "raw", root / "reports")
            report = (root / "reports" / "filer_size_check.csv").read_text(encoding="utf-8")
            conn.close()
        self.assertEqual(counts, {"checked": 2, "suspicious": 1})
        self.assertIn("SMALL", report)
        self.assertIn("212.8", report)
        self.assertNotIn("BIG", report)


if __name__ == "__main__":
    unittest.main()
