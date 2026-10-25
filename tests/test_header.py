"""Header parsing. The fixture files are synthetic but follow EDGAR's layout.
`python run.py check` confirms the parser against a real filing."""
import unittest
from datetime import datetime

from helpers import FIXTURES
from tracker.header import api_minus_header_minutes, index_headers_url, parse_index_headers


class SingleFiler(unittest.TestCase):
    def setUp(self):
        self.info = parse_index_headers((FIXTURES / "index_headers_single_filer.html").read_bytes(), 320193)

    def test_acceptance_time_is_read_from_escaped_html(self):
        # Accepted 6:12 pm on Oct 30; officially "filed" Oct 31 because it came in after 5:30 pm.
        self.assertEqual(self.info.acceptance_et, datetime(2019, 10, 30, 18, 12, 36))
        self.assertEqual(self.info.filed_as_of, "2019-10-31")

    def test_period_name_and_sic(self):
        self.assertEqual(self.info.period_of_report, "2019-09-28")
        self.assertEqual(self.info.company_name, "Apple Inc.")
        self.assertEqual(self.info.sic_code, "3571")
        self.assertEqual(self.info.sic_description, "ELECTRONIC COMPUTERS")

    def test_document_list(self):
        types = [d["type"] for d in self.info.documents]
        self.assertEqual(types, ["10-K", "EX-4.1", "EX-13.1", "GRAPHIC"])
        self.assertEqual(self.info.documents[2]["filename"], "annualreport2019.htm")
        self.assertEqual(self.info.documents[2]["description"], "PORTIONS OF ANNUAL REPORT")
        self.assertIsNone(self.info.documents[3]["description"])


class MultiFiler(unittest.TestCase):
    RAW = (FIXTURES / "index_headers_multi_filer.txt").read_bytes()

    def test_picks_the_block_for_our_company(self):
        info = parse_index_headers(self.RAW, 22222)
        self.assertEqual(info.company_name, "EXAMPLE ENERGY HOLDINGS INC")
        self.assertEqual(info.sic_code, "4931")
        self.assertEqual(info.sic_description, "ELECTRIC & OTHER SERVICES COMBINED")

    def test_falls_back_to_first_block(self):
        info = parse_index_headers(self.RAW, 99999)
        self.assertEqual(info.company_name, "EXAMPLE SUBSIDIARY POWER CO")

    def test_unescaped_sgml_also_works(self):
        info = parse_index_headers(self.RAW, 22222)
        self.assertEqual(info.acceptance_et, datetime(2024, 2, 27, 16, 15, 2))
        self.assertEqual([d["filename"] for d in info.documents], ["exe-20231231.htm", "ex21.htm"])


class AcceptanceTimeComparison(unittest.TestCase):
    HEADER = datetime(2019, 10, 30, 18, 12, 36)  # Eastern daylight time = UTC-4

    def test_agreeing_times(self):
        self.assertEqual(api_minus_header_minutes("2019-10-30T22:12:36.000Z", self.HEADER), 0.0)

    def test_eastern_time_wrongly_labeled_utc(self):
        self.assertEqual(api_minus_header_minutes("2019-10-30T18:12:36.000Z", self.HEADER), -240.0)

    def test_winter_offset_is_five_hours(self):
        winter = datetime(2024, 2, 27, 16, 15, 2)
        self.assertEqual(api_minus_header_minutes("2024-02-27T21:15:02.000Z", winter), 0.0)

    def test_missing_values(self):
        self.assertIsNone(api_minus_header_minutes(None, self.HEADER))
        self.assertIsNone(api_minus_header_minutes("garbage", self.HEADER))
        self.assertIsNone(api_minus_header_minutes("2019-10-30T22:12:36.000Z", None))


class Urls(unittest.TestCase):
    def test_header_url(self):
        self.assertEqual(
            index_headers_url(320193, "0000320193-19-000119"),
            "https://www.sec.gov/Archives/edgar/data/320193/000032019319000119/0000320193-19-000119-index-headers.html",
        )


if __name__ == "__main__":
    unittest.main()
