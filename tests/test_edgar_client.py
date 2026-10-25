import gzip
import tempfile
import unittest
from pathlib import Path

import requests

from helpers import FakeResponse, make_client, ok
from tracker.edgar_client import DownloadError, RateLimiter, SecAccessDenied

URL = "https://www.sec.gov/some/file.htm"


class RateLimit(unittest.TestCase):
    def test_requests_are_spaced_out(self):
        client, session, clock = make_client({URL: ok("x")}, requests_per_second=5)
        for _ in range(3):
            client.get(URL)
        # First request goes right away; each later one waits 0.2 s (5 per second).
        self.assertEqual(clock.sleeps, [0.2, 0.2])

    def test_no_wait_if_enough_time_passed(self):
        times = iter([0.0, 1.0, 1.0])  # second request comes a full second later
        sleeps = []
        limiter = RateLimiter(5, clock=lambda: next(times), sleep=sleeps.append)
        limiter.wait()
        limiter.wait()
        self.assertEqual(sleeps, [])


class Retries(unittest.TestCase):
    def test_retries_temporary_errors_then_succeeds(self):
        client, session, clock = make_client({URL: [FakeResponse(503), FakeResponse(429), ok("done")]})
        self.assertEqual(client.get(URL), b"done")
        self.assertEqual(len(session.requested), 3)
        self.assertIn(1, clock.sleeps)   # back-off after first failure
        self.assertIn(2, clock.sleeps)   # longer back-off after second

    def test_gives_up_after_max_retries(self):
        client, session, _ = make_client({URL: [FakeResponse(503)]}, max_retries=3)
        with self.assertRaises(DownloadError) as ctx:
            client.get(URL)
        self.assertEqual(ctx.exception.status, 503)
        self.assertEqual(len(session.requested), 3)

    def test_404_is_not_retried(self):
        client, session, _ = make_client({})
        with self.assertRaises(DownloadError) as ctx:
            client.get(URL)
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(len(session.requested), 1)

    def test_network_error_is_retried(self):
        client, session, _ = make_client({URL: requests.ConnectionError("reset")}, max_retries=2)
        with self.assertRaises(DownloadError):
            client.get(URL)
        self.assertEqual(len(session.requested), 2)


class Forbidden(unittest.TestCase):
    def test_repeated_403_stops_the_run(self):
        routes = {f"{URL}{i}": FakeResponse(403) for i in range(3)}
        client, _, _ = make_client(routes, stop_after_consecutive_403=3)
        for i in range(2):
            with self.assertRaises(DownloadError):
                client.get(f"{URL}{i}")
        with self.assertRaises(SecAccessDenied):
            client.get(f"{URL}2")

    def test_a_success_resets_the_403_count(self):
        routes = {URL + "a": FakeResponse(403), URL + "b": ok("fine"), URL + "c": FakeResponse(403)}
        client, _, _ = make_client(routes, stop_after_consecutive_403=2)
        with self.assertRaises(DownloadError):
            client.get(URL + "a")
        client.get(URL + "b")
        with self.assertRaises(DownloadError):  # only 1 in a row now, so no full stop
            client.get(URL + "c")

    def test_user_agent_is_sent(self):
        client, session, _ = make_client({})
        self.assertEqual(session.headers["User-Agent"], "Test Person test@test.edu")


class Cache(unittest.TestCase):
    def test_second_request_reads_from_disk(self):
        client, session, _ = make_client({URL: ok("hello")})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a" / "file.htm.gz"
            self.assertEqual(client.get_cached(URL, path), b"hello")
            self.assertEqual(client.get_cached(URL, path), b"hello")
            self.assertEqual(len(session.requested), 1)
            self.assertEqual(client.cache_hits, 1)
            with gzip.open(path) as f:  # really saved compressed
                self.assertEqual(f.read(), b"hello")
            self.assertFalse(path.with_name(path.name + ".part").exists())

    def test_half_written_file_is_ignored(self):
        client, session, _ = make_client({URL: ok("fresh")})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "file.htm.gz"
            path.with_name(path.name + ".part").write_bytes(b"partial junk")  # left by an interrupted run
            self.assertEqual(client.get_cached(URL, path), b"fresh")
            self.assertEqual(len(session.requested), 1)

    def test_damaged_cache_file_is_downloaded_again(self):
        client, session, _ = make_client({URL: ok("fresh")})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "file.htm.gz"
            path.write_bytes(b"not gzip at all")
            self.assertEqual(client.get_cached(URL, path), b"fresh")
            self.assertEqual(len(session.requested), 1)


if __name__ == "__main__":
    unittest.main()
