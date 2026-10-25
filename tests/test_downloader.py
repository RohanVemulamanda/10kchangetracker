"""Downloading and resuming, end to end, against a fake SEC."""
import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURES, FakeResponse, make_client, ok
from tracker import db
from tracker.downloader import download_pending
from tracker.edgar_client import SecAccessDenied
from tracker.header import document_url, index_headers_url

APPLE_HEADER = (FIXTURES / "index_headers_single_filer.html").read_bytes()
ACC = "0000320193-19-000119"
BIG_DOC = "<html>" + "Risk factors text. " * 2000 + "</html>"


def add_filing(conn, accession, cik=320193, primary="a10-k20199282019.htm", report_date="2019-09-28"):
    conn.execute(
        "INSERT INTO filings (accession_number, cik, form, filing_date, report_date, fiscal_year, role, "
        "primary_document, acceptance_api_raw, selected, status) "
        "VALUES (?, ?, '10-K', '2019-10-31', ?, 2019, 'sample', ?, '2019-10-30T18:12:36.000Z', 1, 'pending')",
        (accession, cik, report_date, primary),
    )
    conn.commit()


def apple_routes():
    return {
        index_headers_url(320193, ACC): ok(APPLE_HEADER),
        document_url(320193, ACC, "a10-k20199282019.htm"): ok(BIG_DOC),
        document_url(320193, ACC, "annualreport2019.htm"): ok("<html>annual report</html>"),
    }


class DownloadOne(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name) / "raw"
        self.conn = db.connect(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def row(self, accession=ACC):
        return dict(self.conn.execute("SELECT * FROM filings WHERE accession_number = ?", (accession,)).fetchone())

    def test_successful_download_fills_every_field(self):
        add_filing(self.conn, ACC)
        client, session, _ = make_client(apple_routes())
        counts = download_pending(self.conn, client, self.raw, max_attempts=3)
        self.assertEqual(counts["downloaded"], 1)
        r = self.row()
        self.assertEqual(r["status"], "downloaded")
        self.assertEqual(r["acceptance_et"], "2019-10-30 18:12:36")
        self.assertEqual(r["api_minus_header_minutes"], -240.0)  # API time was Eastern mislabeled as UTC
        self.assertEqual(r["company_name_at_filing"], "Apple Inc.")
        self.assertEqual(r["sic_at_filing"], "3571")
        self.assertIn("annualreport2019.htm", r["exhibit13_paths"])
        self.assertTrue((self.raw / r["primary_path"]).exists())
        self.assertIsNone(r["check_notes"])
        self.assertEqual(len(session.requested), 3)  # header, main document, EX-13

    def test_failure_is_recorded_and_retried_up_to_the_limit(self):
        add_filing(self.conn, ACC)
        routes = apple_routes()
        routes[document_url(320193, ACC, "a10-k20199282019.htm")] = FakeResponse(404)
        client, _, _ = make_client(routes)
        for _ in range(4):  # four runs, but max_attempts = 2
            download_pending(self.conn, client, self.raw, max_attempts=2)
        r = self.row()
        self.assertEqual((r["status"], r["error"], r["attempts"]), ("failed", "HTTP 404", 2))

    def test_resume_after_crash_does_not_redownload(self):
        second = "0000320193-20-000096"
        add_filing(self.conn, ACC)
        add_filing(self.conn, second, primary="aapl-20200926.htm", report_date="2020-09-26")
        routes = apple_routes()
        routes[index_headers_url(320193, second)] = ok(APPLE_HEADER.replace(b"20190928", b"20200926"))
        routes[document_url(320193, second, "aapl-20200926.htm")] = KeyboardInterrupt()  # simulates pressing Ctrl+C
        routes[document_url(320193, second, "annualreport2019.htm")] = ok("<html>ex13</html>")
        client, session, _ = make_client(routes)

        with self.assertRaises(KeyboardInterrupt):
            download_pending(self.conn, client, self.raw, max_attempts=3)
        self.assertEqual(self.row(ACC)["status"], "downloaded")  # first filing was saved
        self.assertEqual(self.row(second)["status"], "pending")

        routes[document_url(320193, second, "aapl-20200926.htm")] = ok(BIG_DOC)
        before = len(session.requested)
        download_pending(self.conn, client, self.raw, max_attempts=3)
        new_requests = session.requested[before:]
        # Only the missing pieces of the second filing: its main document and EX-13.
        # Its header (already cached) and the whole first filing are not fetched again.
        self.assertEqual(new_requests, [document_url(320193, second, "aapl-20200926.htm"),
                                        document_url(320193, second, "annualreport2019.htm")])
        self.assertEqual(self.row(second)["status"], "downloaded")

    def test_sec_refusal_stops_the_run(self):
        add_filing(self.conn, ACC)
        add_filing(self.conn, "0000320193-20-000096")
        client, _, _ = make_client({}, stop_after_consecutive_403=1)
        client.session.routes = {index_headers_url(320193, ACC): FakeResponse(403)}
        with self.assertRaises(SecAccessDenied):
            download_pending(self.conn, client, self.raw, max_attempts=3)

    def test_missing_file_is_noticed_and_downloaded_again(self):
        add_filing(self.conn, ACC)
        client, session, _ = make_client(apple_routes())
        download_pending(self.conn, client, self.raw, max_attempts=3)
        (self.raw / self.row()["primary_path"]).unlink()  # someone deleted it
        counts = download_pending(self.conn, client, self.raw, max_attempts=3)
        self.assertEqual(counts["reset_missing_files"], 1)
        self.assertEqual(self.row()["status"], "downloaded")

    def test_small_main_document_and_period_mismatch_are_flagged(self):
        add_filing(self.conn, ACC, report_date="2019-09-30")
        routes = apple_routes()
        routes[document_url(320193, ACC, "a10-k20199282019.htm")] = ok("<html>See Exhibit 13.</html>")
        client, _, _ = make_client(routes)
        download_pending(self.conn, client, self.raw, max_attempts=3)
        notes = self.row()["check_notes"]
        self.assertIn("main document is only", notes)
        self.assertIn("header period 2019-09-28 differs", notes)

    def test_unselected_filings_are_skipped(self):
        add_filing(self.conn, ACC)
        self.conn.execute("UPDATE filings SET selected = 0")
        client, session, _ = make_client(apple_routes())
        self.assertEqual(download_pending(self.conn, client, self.raw, max_attempts=3)["attempted"], 0)
        self.assertEqual(session.requested, [])


if __name__ == "__main__":
    unittest.main()
