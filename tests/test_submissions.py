import tempfile
import unittest
from pathlib import Path

from helpers import make_client, ok, submissions_columns, tenk
from tracker.submissions import EXTRA_PAGE_URL, SUBMISSIONS_URL, columns_to_rows, fetch_company_filings

CIK = 1234
MAIN_URL = SUBMISSIONS_URL.format(cik=CIK)


def main_json(recent_rows, files):
    return {
        "cik": str(CIK), "name": "ACME CORP", "sic": "3571", "sicDescription": "Electronic Computers",
        "fiscalYearEnd": "1231", "tickers": ["ACME"],
        "filings": {"recent": submissions_columns(recent_rows), "files": files},
    }


class ColumnsToRows(unittest.TestCase):
    def test_parallel_lists_become_rows(self):
        rows = columns_to_rows({"accessionNumber": ["a", "b"], "form": ["10-K", "8-K"], "notAList": 5})
        self.assertEqual(rows, [{"accessionNumber": "a", "form": "10-K"}, {"accessionNumber": "b", "form": "8-K"}])


class ExtraPages(unittest.TestCase):
    def test_old_10k_on_extra_page_is_found_and_irrelevant_pages_skipped(self):
        recent = [tenk("NEW", "2024-02-20", "2023-12-31")]
        page_recent = {"name": "CIK0000001234-submissions-001.json", "filingFrom": "2015-01-01", "filingTo": "2021-06-30"}
        page_old = {"name": "CIK0000001234-submissions-002.json", "filingFrom": "1995-01-01", "filingTo": "2014-12-31"}
        routes = {
            MAIN_URL: ok(main_json(recent, [page_recent, page_old])),
            EXTRA_PAGE_URL.format(name=page_recent["name"]): ok(submissions_columns([tenk("OLD", "2021-02-20", "2020-12-31")])),
        }
        client, session, _ = make_client(routes)
        with tempfile.TemporaryDirectory() as tmp:
            company, filings = fetch_company_filings(client, CIK, Path(tmp), earliest_needed="2019-01-01")
        self.assertEqual({f["accessionNumber"] for f in filings}, {"NEW", "OLD"})
        self.assertEqual(company["name_current"], "ACME CORP")
        self.assertEqual(company["tickers_current"], "ACME")
        # The 1995-2014 page was never requested.
        self.assertEqual(len(session.requested), 2)

    def test_second_run_uses_cache(self):
        routes = {MAIN_URL: ok(main_json([tenk("NEW", "2024-02-20", "2023-12-31")], []))}
        client, session, _ = make_client(routes)
        with tempfile.TemporaryDirectory() as tmp:
            fetch_company_filings(client, CIK, Path(tmp), "2019-01-01")
            fetch_company_filings(client, CIK, Path(tmp), "2019-01-01")
            self.assertEqual(len(session.requested), 1)
            fetch_company_filings(client, CIK, Path(tmp), "2019-01-01", refresh=True)
            self.assertEqual(len(session.requested), 2)


if __name__ == "__main__":
    unittest.main()
