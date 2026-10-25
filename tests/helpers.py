"""Test helpers: a fake internet, so tests never contact SEC and run in under a second.

FakeSession stands in for `requests.Session`. You tell it which URLs return what,
and it records every request, so a test can check exactly what was (or wasn't) downloaded.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `import tracker` work when running `python -m unittest` from the project folder.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracker.edgar_client import EdgarClient  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"", headers: dict | None = None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


class FakeSession:
    """routes: url -> FakeResponse, or url -> list of FakeResponses (returned in order)."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.headers: dict = {}
        self.requested: list[str] = []

    def get(self, url, timeout=None):
        self.requested.append(url)
        route = self.routes.get(url)
        if route is None:
            return FakeResponse(404)
        if isinstance(route, list):
            return route.pop(0) if len(route) > 1 else route[0]
        if isinstance(route, BaseException):  # e.g. ConnectionError, or KeyboardInterrupt to fake Ctrl+C
            raise route
        return route


class FakeClock:
    """A clock that only moves when something 'sleeps'. Lets us test waiting without waiting."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(routes: dict, **kwargs) -> tuple[EdgarClient, FakeSession, FakeClock]:
    session = FakeSession(routes)
    clock = FakeClock()
    client = EdgarClient("Test Person test@test.edu", session=session, clock=clock.time, sleep=clock.sleep, **kwargs)
    return client, session, clock


def ok(content) -> FakeResponse:
    if isinstance(content, (dict, list)):
        content = json.dumps(content)
    if isinstance(content, str):
        content = content.encode("utf-8")
    return FakeResponse(200, content)


def submissions_columns(rows: list[dict]) -> dict:
    """Build SEC-style parallel lists from a list of filing dicts."""
    keys = ["accessionNumber", "filingDate", "reportDate", "acceptanceDateTime", "form", "primaryDocument"]
    return {k: [r.get(k, "") for r in rows] for k in keys}


def tenk(accession: str, filing_date: str, report_date: str, form: str = "10-K", primary: str = "doc.htm") -> dict:
    return {"accessionNumber": accession, "filingDate": filing_date, "reportDate": report_date,
            "acceptanceDateTime": f"{filing_date}T16:30:00.000Z", "form": form, "primaryDocument": primary}
