"""Phase 5: find new 10-Ks from today's S&P 500 members (D-036).

The research sample (Phases 1-4) is fixed: historical members, fiscal years 2021-2025. Live mode
adds new filings without touching it:
  1. today's S&P 500 list, read from Wikipedia (it includes each company's SEC ID, the CIK);
  2. each member's filing list from SEC, fetched fresh (D-016);
  3. the same rules as Phase 1 pick the 10-Ks: originals only, one per period, fiscal-year labels,
     and the prior 10-K to compare with (selection.py). Every current member counts as a member
     on every date, which is only true for today, but live mode only looks at the newest filings;
  4. only filings not already in the database are added, marked role 'live' (scored) or
     'live_comparison' (prior year only). Rows with role 'sample' or 'comparison' are never changed,
     so the research results can't move when the live data grows.
After that, the usual download, extraction and scoring steps pick up the new filings.
"""
from __future__ import annotations

import csv
import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path

import lxml.html
import pandas as pd
import requests

from .edgar_client import DownloadError, EdgarClient
from .selection import select_filings
from .submissions import fetch_company_filings
from .ticker_map import load_predecessors
from .universe import Membership, normalize_ticker

log = logging.getLogger(__name__)

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
MIN_MEMBERS, MAX_MEMBERS = 490, 520     # ~503 rows (a few companies have two share classes)

SCHEMA = """
CREATE TABLE IF NOT EXISTS live_members (
    snapshot_date  TEXT NOT NULL,     -- when the list was read
    sec_ticker     TEXT NOT NULL,
    cik            INTEGER,
    name           TEXT,
    sector         TEXT,
    sub_industry   TEXT,
    PRIMARY KEY (snapshot_date, sec_ticker)
);
"""


class MemberListError(Exception):
    """Wikipedia's list couldn't be read, or doesn't look like the S&P 500."""


def parse_member_table(page: bytes) -> list[dict]:
    """The rows of Wikipedia's "constituents" table: ticker, name, sector, sub-industry, CIK."""
    doc = lxml.html.fromstring(page)
    tables = doc.xpath('//table[@id="constituents"]')
    if not tables:
        raise MemberListError("No table with id 'constituents' on the Wikipedia page; its layout may have changed.")
    rows = tables[0].xpath(".//tr")
    headers = [th.text_content().strip() for th in rows[0].xpath("./th")]
    needed = ["Symbol", "Security", "GICS Sector", "GICS Sub-Industry", "CIK"]
    missing = [h for h in needed if h not in headers]
    if missing:
        raise MemberListError(f"Wikipedia's table is missing columns {missing}; its layout may have changed.")
    members = []
    for tr in rows[1:]:
        cells = [td.text_content().strip() for td in tr.xpath("./td")]
        if len(cells) != len(headers):
            continue
        row = dict(zip(headers, cells))
        members.append({"sec_ticker": normalize_ticker(row["Symbol"]), "name": row["Security"],
                        "sector": row["GICS Sector"], "sub_industry": row["GICS Sub-Industry"],
                        "cik": int(row["CIK"]) if row["CIK"].isdigit() else None})
    return members


def check_members(members: list[dict]) -> None:
    """Refuse a list that doesn't look like the S&P 500, instead of quietly tracking the wrong companies."""
    if not MIN_MEMBERS <= len(members) <= MAX_MEMBERS:
        raise MemberListError(f"Wikipedia's list has {len(members)} rows; expected {MIN_MEMBERS}-{MAX_MEMBERS}.")
    without_cik = [m["sec_ticker"] for m in members if m["cik"] is None]
    if len(without_cik) > 5:
        raise MemberListError(f"{len(without_cik)} rows have no CIK (e.g. {without_cik[:5]}); the table may have changed.")


def fetch_current_members(conn: sqlite3.Connection, snapshot_dir: Path, user_agent: str) -> list[dict]:
    """Read today's list from Wikipedia, check it, and keep a copy (database and CSV) for the record."""
    response = requests.get(WIKIPEDIA_URL, headers={"User-Agent": user_agent}, timeout=30)
    response.raise_for_status()
    members = parse_member_table(response.content)
    check_members(members)
    today = date.today().isoformat()
    conn.executescript(SCHEMA)
    conn.execute("DELETE FROM live_members WHERE snapshot_date = ?", (today,))
    conn.executemany("INSERT INTO live_members (snapshot_date, sec_ticker, cik, name, sector, sub_industry) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     [(today, m["sec_ticker"], m["cik"], m["name"], m["sector"], m["sub_industry"]) for m in members])
    conn.commit()
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    with open(snapshot_dir / f"sp500_current_{today}.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["sec_ticker", "name", "sector", "sub_industry", "cik"])
        writer.writeheader()
        writer.writerows(members)
    log.info("Today's S&P 500 list: %d rows, %d companies", len(members), len({m["cik"] for m in members}))
    return members


LIVE_ROLES = {"sample": "live", "comparison": "live_comparison"}
LIVE_COLUMNS = ["accession_number", "cik", "company_cik", "form", "filing_date", "report_date", "fiscal_year", "role",
                "member_tickers", "prior_accession", "prior_gap_days", "primary_document", "acceptance_api_raw"]


def live_rows(cik: int, filings: list[dict], tickers: set[str], start_fiscal_year: int, earliest_needed: str,
              existing: set[str]) -> list[dict]:
    """The new filings to add for one company: chosen by Phase 1's rules, minus any already stored."""
    always_member = Membership([{"sec_ticker": t, "start_date": "1900-01-01", "end_date": None} for t in tickers])
    result = select_filings(cik, filings, tickers, always_member, start_fiscal_year, 9999, earliest_needed)
    rows = []
    for row in result.selected:
        if row["accession_number"] in existing:
            continue
        rows.append({**row, "role": LIVE_ROLES[row["role"]]})
    return rows


def find_live_filings(conn: sqlite3.Connection, client: EdgarClient, members: list[dict], raw_dir: Path,
                      reference_dir: Path, start_fiscal_year: int) -> dict:
    """Add every current member's 10-Ks that aren't in the database yet. Returns counts."""
    predecessors = load_predecessors(reference_dir / "predecessors.csv")
    earliest_needed = f"{start_fiscal_year - 2}-01-01"
    tickers_by_cik: dict[int, set[str]] = {}
    for m in members:
        if m["cik"] is not None:
            tickers_by_cik.setdefault(m["cik"], set()).add(m["sec_ticker"])
    insert = (f"INSERT INTO filings ({', '.join(LIVE_COLUMNS)}, selected) "
              f"VALUES ({', '.join(':' + c for c in LIVE_COLUMNS)}, 1)")
    counts = {"companies": len(tickers_by_cik), "failed_companies": 0, "live": 0, "live_comparison": 0}
    for i, (cik, tickers) in enumerate(sorted(tickers_by_cik.items()), start=1):
        try:
            company, filings = fetch_company_filings(client, cik, raw_dir, earliest_needed, refresh=True)
            for f in filings:
                f["_cik"] = cik
            for old_cik in predecessors.get(cik, []):
                _, old_filings = fetch_company_filings(client, old_cik, raw_dir, earliest_needed, refresh=True)
                for f in old_filings:
                    f["_cik"] = old_cik
                filings += old_filings
        except DownloadError as exc:
            log.error("Could not get the filing list for CIK %s: %s", cik, exc)
            counts["failed_companies"] += 1
            continue
        existing = {r[0] for r in conn.execute("SELECT accession_number FROM filings")}
        for row in live_rows(cik, filings, tickers, start_fiscal_year, earliest_needed, existing):
            conn.execute(insert, {**row, "member_tickers": ",".join(sorted(tickers))})
            counts[row["role"]] += 1
        conn.execute(
            "INSERT INTO companies (cik, name_current, sic_current, sic_description, fiscal_year_end, tickers_current, "
            "submissions_status, updated_at) VALUES (:cik, :name_current, :sic_current, :sic_description, "
            ":fiscal_year_end, :tickers_current, 'ok', :updated_at) ON CONFLICT(cik) DO UPDATE SET "
            "name_current=excluded.name_current, sic_current=excluded.sic_current, "
            "sic_description=excluded.sic_description, tickers_current=excluded.tickers_current, "
            "updated_at=excluded.updated_at",
            {**company, "updated_at": datetime.now().isoformat(timespec="seconds")})
        conn.commit()
        if i % 50 == 0 or i == len(tickers_by_cik):
            log.info("Progress: %d/%d companies; %d new filings to score so far", i, len(tickers_by_cik), counts["live"])
    return counts


# ------------------------------------------------------------------ review list

REVIEW_PERCENTILE = 0.01   # a change bigger than 99% of the research sample's gets a look first


def load_approved(reference_dir: Path) -> set[str]:
    """Live filings checked by hand and cleared for the dashboard: data/reference/live_approved.csv."""
    path = reference_dir / "live_approved.csv"
    if not path.exists():
        return set()
    with open(path, newline="", encoding="utf-8") as f:
        return {row["accession_number"] for row in csv.DictReader(f)}


def review_reasons(conn: sqlite3.Connection, sconn: sqlite3.Connection, cconn: sqlite3.Connection) -> dict[str, list[str]]:
    """Why each live filing needs a look before it goes on the dashboard (D-037). Empty = fine."""
    roles = dict(conn.execute("SELECT accession_number, role FROM filings WHERE selected = 1").fetchall())
    scores = pd.read_sql_query("SELECT accession_number, status, note, sim_cosine, sim_jaccard, flags FROM changes "
                               "WHERE version = 'main'", cconn)
    scores["role"] = scores.accession_number.map(roles)
    sample = scores[(scores.role == "sample") & (scores.status == "ok")]
    cutoffs = {m: sample[m].quantile(REVIEW_PERCENTILE) for m in ("sim_cosine", "sim_jaccard")}
    extraction = {r[0]: r[1:] for r in sconn.execute("SELECT accession_number, status, flags FROM sections WHERE section = 'item_1a'")}

    reasons: dict[str, list[str]] = {}
    for row in scores[scores.role == "live"].itertuples():
        why = []
        status, flags = extraction.get(row.accession_number, ("not_extracted", None))
        if status != "ok":
            why.append(f"extraction {status}" + (f" ({flags})" if flags else ""))
        if row.status != "ok":
            why.append(f"not scored: {row.note}")
        else:
            if row.flags:
                why.append(row.flags)
            for m, cutoff in cutoffs.items():
                if getattr(row, m) < cutoff:
                    why.append(f"{m[4:]} {getattr(row, m):.3f} is below the research sample's 1st percentile ({cutoff:.3f})")
        reasons[row.accession_number] = why
    return reasons
