"""Every request to SEC goes through this one file.

Keeping it in one place means the SEC rules are enforced everywhere:
  1. A User-Agent header with your name and email (SEC requires it).
  2. A rate limit: at most N requests per second (we use 5; SEC's cap is 10).
  3. Retries with growing waits for temporary errors (429 "too many requests", 5xx, timeouts).
  4. A full stop after repeated 403 "forbidden" answers, instead of hammering a server
     that is refusing us.
  5. A cache: every downloaded file is saved (gzip-compressed). Asking for the same
     file again reads it from disk, so nothing is ever downloaded twice.
"""
from __future__ import annotations

import gzip
import logging
import os
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)


class DownloadError(Exception):
    """One file could not be downloaded. The run continues; the failure is recorded."""

    def __init__(self, url: str, status: int | None, message: str):
        super().__init__(f"{message} ({url})")
        self.url = url
        self.status = status
        self.message = message


class SecAccessDenied(Exception):
    """SEC refused several requests in a row (HTTP 403). The whole run stops.

    Usual causes: the User-Agent is missing or looks fake, or we were temporarily
    blocked for going too fast. Waiting 10+ minutes usually clears a block.
    """


class RateLimiter:
    """Makes sure requests are spaced at least 1/N seconds apart.

    `clock` and `sleep` can be swapped for fake versions in tests, so tests run instantly.
    """

    def __init__(self, requests_per_second: float, clock=time.monotonic, sleep=time.sleep):
        self.min_interval = 1.0 / requests_per_second
        self.clock = clock
        self.sleep = sleep
        self.last_request_time: float | None = None

    def wait(self) -> None:
        if self.last_request_time is not None:
            elapsed = self.clock() - self.last_request_time
            if elapsed < self.min_interval:
                self.sleep(self.min_interval - elapsed)
        self.last_request_time = self.clock()


def save_gzip_atomic(path: Path, data: bytes) -> None:
    """Save bytes as a gzip file without ever leaving a half-written file behind.

    We write to 'name.part' first and rename it only when the write is complete.
    If the script is killed mid-write, only the .part file is left, and the next
    run ignores it. That is what makes the cache safe to resume from.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".part")
    with gzip.open(temp_path, "wb") as f:
        f.write(data)
    os.replace(temp_path, path)  # the rename is all-or-nothing


def read_gzip(path: Path) -> bytes:
    with gzip.open(path, "rb") as f:
        return f.read()


class EdgarClient:
    RETRYABLE_STATUS = {429, 500, 502, 503, 504}

    def __init__(
        self,
        user_agent: str,
        requests_per_second: float = 5,
        max_retries: int = 5,
        timeout_seconds: float = 30,
        stop_after_consecutive_403: int = 3,
        session=None,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
        self.limiter = RateLimiter(requests_per_second, clock=clock, sleep=sleep)
        self.max_retries = max_retries
        self.timeout = timeout_seconds
        self.stop_after_403 = stop_after_consecutive_403
        self.sleep = sleep
        self.consecutive_403 = 0
        # Counters for the end-of-run summary.
        self.requests_made = 0
        self.cache_hits = 0

    def get(self, url: str) -> bytes:
        """Download one URL and return its bytes. Raises DownloadError if it fails for good."""
        for attempt in range(1, self.max_retries + 1):
            self.limiter.wait()
            self.requests_made += 1
            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:  # timeout, connection reset, etc.
                log.warning("Attempt %d/%d failed for %s: %s", attempt, self.max_retries, url, exc)
                if attempt == self.max_retries:
                    raise DownloadError(url, None, f"network error: {exc}") from exc
                self._back_off(attempt)
                continue

            status = response.status_code
            if status == 200:
                self.consecutive_403 = 0
                return response.content

            if status == 403:
                # Retrying the same URL won't help: SEC is refusing us. Count it, and stop
                # the whole run if it keeps happening.
                self.consecutive_403 += 1
                if self.consecutive_403 >= self.stop_after_403:
                    raise SecAccessDenied(
                        f"SEC returned 403 Forbidden {self.consecutive_403} times in a row. "
                        "Check SEC_USER_NAME / SEC_USER_EMAIL in .env. If they are right, you may "
                        "be temporarily blocked: wait at least 10 minutes before running again."
                    )
                raise DownloadError(url, 403, "HTTP 403 Forbidden")

            if status in self.RETRYABLE_STATUS and attempt < self.max_retries:
                log.warning("HTTP %d on attempt %d/%d for %s; retrying", status, attempt, self.max_retries, url)
                self._back_off(attempt, retry_after=response.headers.get("Retry-After"))
                continue

            # 404 (file doesn't exist) and anything else: give up on this file.
            raise DownloadError(url, status, f"HTTP {status}")

        raise DownloadError(url, None, "gave up after retries")  # not normally reached

    def get_cached(self, url: str, cache_path: Path) -> bytes:
        """Return the file from the cache if we have it; otherwise download it and cache it."""
        if cache_path.exists():
            try:
                data = read_gzip(cache_path)
                self.cache_hits += 1
                return data
            except (OSError, EOFError) as exc:  # damaged file on disk: fetch it again
                log.warning("Cached file %s is damaged (%s); downloading again", cache_path, exc)
        data = self.get(url)
        save_gzip_atomic(cache_path, data)
        return data

    def _back_off(self, attempt: int, retry_after: str | None = None) -> None:
        """Wait before retrying: 1s, 2s, 4s, 8s... or what the server asked for (max 60s)."""
        wait = 2 ** (attempt - 1)
        if retry_after and retry_after.isdigit():
            wait = max(wait, int(retry_after))
        self.sleep(min(wait, 60))
