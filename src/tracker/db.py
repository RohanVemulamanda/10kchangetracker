"""The SQLite database: one file (data/tracker.db) holding every table for Phase 1.

Why SQLite: it tracks "what's done and what's left" for each filing, which is
what lets a stopped run resume. Big files (the filings themselves) stay on disk;
the database only stores their paths. See DECISIONS.md D-012.

Tables
------
membership        S&P 500 membership periods, one row per ticker per stint in the index
ticker_map        which SEC company (CIK) each ticker belongs to, and how we know
companies         one row per company: current name, SIC code, whether its filing list downloaded
filings           one row per 10-K we need: dates, role, download status, file paths
excluded_filings  10-K-type filings we deliberately left out, and why (amendments, duplicates...)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS membership (
    ticker      TEXT NOT NULL,   -- as written in the source list, e.g. BRK.B
    sec_ticker  TEXT NOT NULL,   -- SEC's style, e.g. BRK-B
    start_date  TEXT NOT NULL,   -- first day in the index (YYYY-MM-DD)
    end_date    TEXT,            -- first day NOT in the index; NULL = still in at data end
    PRIMARY KEY (sec_ticker, start_date)
);

CREATE TABLE IF NOT EXISTS ticker_map (
    sec_ticker  TEXT PRIMARY KEY,
    cik         INTEGER,         -- NULL means we could not map it (see the unmapped report)
    source      TEXT,            -- 'manual' or 'sec_current' or 'unmapped'
    sec_title   TEXT,            -- company name according to the source of the mapping
    note        TEXT             -- warnings, e.g. disagreement with Wikipedia's CIK
);

CREATE TABLE IF NOT EXISTS companies (
    cik                 INTEGER PRIMARY KEY,
    name_current        TEXT,
    sic_current         TEXT,
    sic_description     TEXT,
    fiscal_year_end     TEXT,    -- MMDD, e.g. 0928 for Apple
    tickers_current     TEXT,
    submissions_status  TEXT,    -- 'ok' or 'failed'
    submissions_error   TEXT,
    mapping_check       TEXT,    -- NULL if fine; otherwise why the ticker->CIK link looks wrong
    selection_notes     TEXT,    -- warnings from choosing filings (e.g. fiscal-year label clash)
    updated_at          TEXT
);

CREATE TABLE IF NOT EXISTS filings (
    accession_number    TEXT PRIMARY KEY,   -- SEC's unique filing ID, e.g. 0000320193-19-000119
    cik                 INTEGER NOT NULL,
    form                TEXT,
    filing_date         TEXT,
    report_date         TEXT,               -- end of the period the 10-K covers
    fiscal_year         INTEGER,            -- our own rule, see dates.py and D-004
    role                TEXT,               -- 'sample' (scored) or 'comparison' (prior year only)
    member_tickers      TEXT,               -- tickers in the S&P 500 on the filing date
    prior_accession     TEXT,               -- the 10-K this one will be compared to
    prior_gap_days      INTEGER,            -- days between the two period ends (~365 is normal)
    primary_document    TEXT,
    acceptance_api_raw  TEXT,               -- what the submissions API says (unreliable, D-008)
    selected            INTEGER DEFAULT 1,  -- 1 = needed under the current settings
    -- filled in when downloaded:
    acceptance_et       TEXT,               -- from the filing's own header, Eastern Time
    api_minus_header_minutes REAL,          -- 0 if the two acceptance times agree
    company_name_at_filing TEXT,
    sic_at_filing       TEXT,
    header_period       TEXT,
    documents_json      TEXT,               -- list of every document in the filing
    primary_path        TEXT,
    exhibit13_paths     TEXT,
    check_notes         TEXT,               -- automatic warnings about this filing
    status              TEXT DEFAULT 'pending',  -- 'pending', 'downloaded' or 'failed'
    error               TEXT,
    attempts            INTEGER DEFAULT 0,
    downloaded_at       TEXT
);

CREATE TABLE IF NOT EXISTS excluded_filings (
    accession_number  TEXT PRIMARY KEY,
    cik               INTEGER,
    form              TEXT,
    filing_date       TEXT,
    report_date       TEXT,
    reason            TEXT
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the database (creating it and its tables if needed)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # lets us read columns by name: row["cik"]
    conn.executescript(SCHEMA)
    return conn
