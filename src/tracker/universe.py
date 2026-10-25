"""Historical S&P 500 membership: which tickers were in the index on which dates.

Source: github.com/fja05680/sp500 (free, maintained by a volunteer; see DECISIONS.md D-001).
Its main file has one row per date on which the index changed, listing every member that day:

    date,tickers
    2019-01-18,"A,AAL,AAP,AAPL,..."

We turn those snapshots into membership periods, one per ticker per stint in the index:

    ticker  start_date  end_date
    AAL     2015-03-23  2024-09-23     <- end_date is the first day it was NOT in the index
    AAPL    1996-01-02  (blank)        <- still a member when the data ends

Why periods: our sample rule (D-002) asks "was this company in the index on the day
it filed?", and periods answer that with a simple date comparison.

Dates are kept as 'YYYY-MM-DD' text. Text in that format sorts the same way as the
dates themselves, so comparing two strings compares the dates.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests

log = logging.getLogger(__name__)


def normalize_ticker(ticker: str) -> str:
    """Write tickers the way SEC does: 'BRK.B' -> 'BRK-B'. Also trims spaces and upper-cases."""
    return ticker.strip().upper().replace(".", "-")


# ---------------------------------------------------------------- getting the source file

def source_file_path(settings: dict, filename: str, reference_dir: Path) -> Path:
    commit = settings["universe"]["source_commit"]
    safe_name = filename.replace(" ", "_").replace("&", "and").replace("(", "").replace(")", "")
    return reference_dir / "sources" / f"{commit[:7]}_{safe_name}"


def download_source_file(settings: dict, filename: str, reference_dir: Path) -> Path:
    """Download one file from the source repo at the pinned commit (skipped if we have it).

    Pinning to a commit means anyone re-running this gets exactly the same list,
    even after the volunteer updates the repo.
    """
    dest = source_file_path(settings, filename, reference_dir)
    if dest.exists():
        log.info("Using cached copy of %s", dest.name)
        return dest

    repo = settings["universe"]["source_repo"].removeprefix("https://github.com/").strip("/")
    commit = settings["universe"]["source_commit"]
    url = f"https://raw.githubusercontent.com/{repo}/{commit}/{quote(filename)}"
    log.info("Downloading %s", url)
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(response.content)
    return dest


def sha256_of(path: Path) -> str:
    """A fingerprint of the file. If even one character changes, this changes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- snapshots -> periods

def load_snapshots(csv_path: Path) -> list[tuple[str, list[str]]]:
    """Read the (date, tickers) rows. Checks dates are valid and in order."""
    snapshots = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            day = row["date"].strip()
            datetime.strptime(day, "%Y-%m-%d")  # raises an error if the date is malformed
            tickers = [t for t in row["tickers"].split(",") if t.strip()]
            if snapshots and day <= snapshots[-1][0]:
                raise ValueError(f"Dates out of order or repeated at {day}")
            snapshots.append((day, tickers))
    if not snapshots:
        raise ValueError(f"No rows found in {csv_path}")
    return snapshots


def build_periods(snapshots: list[tuple[str, list[str]]]) -> list[dict]:
    """Turn snapshots into membership periods.

    Walk through the snapshots in date order:
      - a ticker that appears and wasn't already open starts a period on that date;
      - an open ticker that is missing from a snapshot ends its period on that date.
    Tickers still present in the last snapshot have no end date.
    """
    open_periods: dict[str, tuple[str, str]] = {}  # sec_ticker -> (original ticker, start date)
    periods = []

    for day, tickers in snapshots:
        present = {}
        for t in tickers:
            present[normalize_ticker(t)] = t.strip()

        for sec_ticker, original in present.items():
            if sec_ticker not in open_periods:
                open_periods[sec_ticker] = (original, day)

        for sec_ticker in list(open_periods):
            if sec_ticker not in present:
                original, start = open_periods.pop(sec_ticker)
                periods.append({"ticker": original, "sec_ticker": sec_ticker, "start_date": start, "end_date": day})

    for sec_ticker, (original, start) in open_periods.items():
        periods.append({"ticker": original, "sec_ticker": sec_ticker, "start_date": start, "end_date": None})

    periods.sort(key=lambda p: (p["sec_ticker"], p["start_date"]))
    return periods


class Membership:
    """Answers questions like 'was AAPL in the S&P 500 on 2023-11-03?'."""

    def __init__(self, periods: list[dict], data_end_date: str | None = None):
        self.periods_by_ticker: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
        for p in periods:
            self.periods_by_ticker[p["sec_ticker"]].append((p["start_date"], p["end_date"]))
        self.data_end_date = data_end_date

    @classmethod
    def from_db(cls, conn: sqlite3.Connection, data_end_date: str | None = None) -> "Membership":
        rows = conn.execute("SELECT ticker, sec_ticker, start_date, end_date FROM membership").fetchall()
        return cls([dict(r) for r in rows], data_end_date)

    def is_member(self, sec_ticker: str, on_date: str) -> bool:
        """True if the ticker was in the index on that date.

        The start date counts as a member day; the end date does not (it is the first
        day out). A period with no end date counts as still a member. That includes
        dates after the data ends, which is an assumption flagged in the summary.
        """
        for start, end in self.periods_by_ticker.get(sec_ticker, []):
            if start <= on_date and (end is None or on_date < end):
                return True
        return False

    def tickers_active_between(self, window_start: str, window_end: str) -> set[str]:
        """Every ticker that was a member for at least one day in [window_start, window_end]."""
        active = set()
        for ticker, periods in self.periods_by_ticker.items():
            for start, end in periods:
                if start <= window_end and (end is None or end > window_start):
                    active.add(ticker)
        return active

    def member_days(self, sec_tickers: set[str], window_start: str, window_end: str) -> int:
        """How many days in the window the company (any of its tickers) was a member.

        Companies like Alphabet have two tickers in the index (GOOG and GOOGL) at once,
        so we merge overlapping periods first to avoid counting the same day twice.
        """
        clipped = []
        for t in sec_tickers:
            for start, end in self.periods_by_ticker.get(t, []):
                s = max(start, window_start)
                e = min(end or window_end, window_end)
                if s < e:
                    clipped.append((s, e))
        clipped.sort()
        total, current_start, current_end = 0, None, None
        for s, e in clipped:
            if current_end is None or s > current_end:
                if current_end is not None:
                    total += _days(current_start, current_end)
                current_start, current_end = s, e
            else:
                current_end = max(current_end, e)
        if current_end is not None:
            total += _days(current_start, current_end)
        return total


def _days(start: str, end: str) -> int:
    return (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days


# ---------------------------------------------------------------- the whole step

def build_universe(settings: dict, conn: sqlite3.Connection, reference_dir: Path) -> dict:
    """Download the source list, build membership periods, save them, and return stats."""
    historical = download_source_file(settings, settings["universe"]["historical_file"], reference_dir)
    current = download_source_file(settings, settings["universe"]["current_file"], reference_dir)
    for path, key in [(historical, "historical_file_sha256"), (current, "current_file_sha256")]:
        expected = settings["universe"].get(key)
        actual = sha256_of(path)
        if expected and actual != expected:
            raise RuntimeError(
                f"{path.name} does not match the fingerprint in settings.yaml ({key}). "
                f"Expected {expected}, got {actual}. Delete the file and run again; if it still "
                "doesn't match, the source changed and the new version needs checking before use."
            )

    snapshots = load_snapshots(historical)
    sizes = [len(t) for _, t in snapshots]
    for day, tickers in snapshots:
        if not 480 <= len(tickers) <= 520:
            log.warning("Snapshot %s has %d tickers (expected about 500)", day, len(tickers))

    periods = build_periods(snapshots)
    data_end_date = snapshots[-1][0]

    conn.execute("DELETE FROM membership")
    conn.executemany(
        "INSERT INTO membership (ticker, sec_ticker, start_date, end_date) VALUES (:ticker, :sec_ticker, :start_date, :end_date)",
        periods,
    )
    conn.commit()

    # A small, readable copy for git, so changes to the universe show up in the history.
    intervals_csv = reference_dir / "sp500_membership_periods.csv"
    with open(intervals_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["ticker", "sec_ticker", "start_date", "end_date"])
        writer.writeheader()
        writer.writerows(periods)

    metadata = {
        "source_repo": settings["universe"]["source_repo"],
        "source_commit": settings["universe"]["source_commit"],
        "historical_file": settings["universe"]["historical_file"],
        "historical_file_sha256": sha256_of(historical),
        "current_file_sha256": sha256_of(current),
        "first_date": snapshots[0][0],
        "data_end_date": data_end_date,
        "snapshot_rows": len(snapshots),
        "periods": len(periods),
        "unique_tickers": len({p["sec_ticker"] for p in periods}),
    }
    with open(reference_dir / "universe_source.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    log.info(
        "Universe built: %d snapshot rows from %s to %s, %d tickers, %d membership periods. "
        "Members per snapshot: min %d, max %d.",
        len(snapshots), snapshots[0][0], data_end_date, metadata["unique_tickers"], len(periods), min(sizes), max(sizes),
    )
    return metadata


def read_data_end_date(reference_dir: Path) -> str | None:
    path = reference_dir / "universe_source.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("data_end_date")
