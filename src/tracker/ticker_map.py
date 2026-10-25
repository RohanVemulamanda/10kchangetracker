"""Link each S&P ticker to the SEC company ID (CIK) that files its 10-Ks.

Why this is tricky (DECISIONS.md D-009):
  - SEC's ticker file (company_tickers.json) only lists tickers in use TODAY.
  - Companies that were acquired, went bankrupt, or changed tickers (FB -> META)
    are missing from it under their old ticker.
  - A few old tickers now belong to a different company.

So we map in this order:
  1. data/reference/manual_cik_map.csv  hand-checked fixes; always wins
  2. data/reference/not_on_edgar.csv    companies whose 10-Ks aren't on EDGAR (D-017)
  3. SEC's current ticker file
  4. Wikipedia's current S&P list (has CIKs) as a fallback for current members
Anything left is written to reports/unmapped_tickers.csv for review. We never guess.

Separately, Wikipedia's CIKs for current members are compared with SEC's mapping.
Two independent sources agreeing is a cheap accuracy check.
"""
from __future__ import annotations

import csv
import json
import logging
import sqlite3
from datetime import date
from pathlib import Path

from .edgar_client import EdgarClient, save_gzip_atomic
from .universe import Membership, normalize_ticker

log = logging.getLogger(__name__)

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
MANUAL_MAP_COLUMNS = ["ticker", "cik", "company_name", "evidence"]


def sample_window_start(start_fiscal_year: int) -> str:
    """Earliest date a sample 10-K can be filed.

    Fiscal year Y covers periods ending June 1 of Y through May 31 of Y+1 (D-004),
    and a 10-K is filed after its period ends. So nothing in the sample is filed
    before June 1 of the first fiscal year.
    """
    return f"{start_fiscal_year}-06-01"


def load_sec_ticker_map(client: EdgarClient, raw_dir: Path, refresh: bool = False) -> dict[str, dict]:
    """Download SEC's current ticker -> CIK file.

    It looks like {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
    """
    path = raw_dir / "sec" / "company_tickers.json.gz"
    if refresh or not path.exists():
        data = client.get(SEC_TICKERS_URL)
        save_gzip_atomic(path, data)
    else:
        data = client.get_cached(SEC_TICKERS_URL, path)

    mapping: dict[str, dict] = {}
    for entry in json.loads(data).values():
        ticker = normalize_ticker(entry["ticker"])
        cik = int(entry["cik_str"])
        if ticker in mapping and mapping[ticker]["cik"] != cik:
            log.warning("SEC file lists %s under two CIKs (%s, %s); keeping the first", ticker, mapping[ticker]["cik"], cik)
            continue
        mapping.setdefault(ticker, {"cik": cik, "title": entry["title"]})
    return mapping


def load_manual_map(path: Path) -> dict[str, dict]:
    """Read hand-checked ticker -> CIK fixes. Columns: ticker, cik, company_name, evidence.

    Every row must say how it was checked (the evidence column), so each mapping
    can be defended later.
    """
    if not path.exists():
        return {}
    mapping = {}
    with open(path, newline="", encoding="utf-8") as f:
        for line_number, row in enumerate(csv.DictReader(f), start=2):
            ticker = normalize_ticker(row.get("ticker") or "")
            if not ticker:
                continue
            try:
                cik = int(row["cik"])
            except (TypeError, ValueError):
                raise ValueError(f"{path.name} line {line_number}: CIK {row.get('cik')!r} is not a number")
            if not (row.get("evidence") or "").strip():
                raise ValueError(f"{path.name} line {line_number}: {ticker} has no evidence; say how it was checked")
            mapping[ticker] = {"cik": cik, "title": row.get("company_name", ""), "evidence": row["evidence"]}
    return mapping


def load_not_on_edgar(path: Path) -> dict[str, dict]:
    """Read companies whose 10-Ks are not on EDGAR. Columns: ticker, company_name, reason, evidence.

    Example: a bank with no holding company files its reports with its bank regulator
    (here, the FDIC) instead of the SEC, so EDGAR has no 10-Ks for it (D-017).
    """
    if not path.exists():
        return {}
    entries = {}
    with open(path, newline="", encoding="utf-8") as f:
        for line_number, row in enumerate(csv.DictReader(f), start=2):
            ticker = normalize_ticker(row.get("ticker") or "")
            if not ticker:
                continue
            if not (row.get("reason") or "").strip() or not (row.get("evidence") or "").strip():
                raise ValueError(f"{path.name} line {line_number}: {ticker} needs both a reason and evidence")
            entries[ticker] = {"title": row.get("company_name", ""), "reason": row["reason"]}
    return entries


def load_wikipedia_ciks(current_list_csv: Path) -> dict[str, int]:
    """Read CIKs from the current S&P list (sp500.csv, scraped from Wikipedia by the source repo)."""
    ciks = {}
    with open(current_list_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("Symbol") and (row.get("CIK") or "").strip().isdigit():
                ciks[normalize_ticker(row["Symbol"])] = int(row["CIK"])
    return ciks


def map_tickers(
    tickers: set[str],
    sec_map: dict[str, dict],
    manual_map: dict[str, dict],
    wikipedia_ciks: dict[str, int],
    not_on_edgar: dict[str, dict] | None = None,
) -> list[dict]:
    """Decide the CIK for each ticker and record where the answer came from."""
    not_on_edgar = not_on_edgar or {}
    rows = []
    for ticker in sorted(tickers):
        notes = []
        if ticker in manual_map:
            cik, source, title = manual_map[ticker]["cik"], "manual", manual_map[ticker]["title"]
        elif ticker in not_on_edgar:
            cik, source, title = None, "not_on_edgar", not_on_edgar[ticker]["title"]
            notes.append(not_on_edgar[ticker]["reason"])
        elif ticker in sec_map:
            cik, source, title = sec_map[ticker]["cik"], "sec_current", sec_map[ticker]["title"]
        elif ticker in wikipedia_ciks:
            cik, source, title = wikipedia_ciks[ticker], "wikipedia_current", ""
            notes.append("not in SEC ticker file; using Wikipedia's CIK")
        else:
            cik, source, title = None, "unmapped", ""

        wiki_cik = wikipedia_ciks.get(ticker)
        if cik is not None and wiki_cik is not None and wiki_cik != cik:
            notes.append(f"Wikipedia says CIK {wiki_cik}")

        rows.append({"sec_ticker": ticker, "cik": cik, "source": source, "sec_title": title, "note": "; ".join(notes) or None})
    return rows


def run_ticker_mapping(
    settings: dict,
    conn: sqlite3.Connection,
    client: EdgarClient,
    reference_dir: Path,
    raw_dir: Path,
    reports_dir: Path,
    current_list_csv: Path,
) -> dict:
    """Map every ticker that was in the index during the sample window, save, and report."""
    membership = Membership.from_db(conn)
    window_start = sample_window_start(settings["sample"]["start_fiscal_year"])
    window_end = date.today().isoformat()
    tickers = membership.tickers_active_between(window_start, window_end)
    log.info("%d tickers were in the S&P 500 at some point between %s and %s", len(tickers), window_start, window_end)

    sec_map = load_sec_ticker_map(client, raw_dir, refresh=settings["sec"]["refresh_submissions"])
    manual_map = load_manual_map(reference_dir / "manual_cik_map.csv")
    not_on_edgar = load_not_on_edgar(reference_dir / "not_on_edgar.csv")
    wikipedia_ciks = load_wikipedia_ciks(current_list_csv)
    rows = map_tickers(tickers, sec_map, manual_map, wikipedia_ciks, not_on_edgar)

    conn.execute("DELETE FROM ticker_map")
    conn.executemany(
        "INSERT INTO ticker_map (sec_ticker, cik, source, sec_title, note) VALUES (:sec_ticker, :cik, :source, :sec_title, :note)",
        rows,
    )
    conn.commit()

    # Report the unmapped ones, most important (longest in the index) first.
    unmapped = []
    for row in rows:
        if row["source"] == "unmapped":
            days = membership.member_days({row["sec_ticker"]}, window_start, window_end)
            periods = [f"{s} to {e or 'present'}" for s, e in membership.periods_by_ticker[row["sec_ticker"]]]
            unmapped.append({"ticker": row["sec_ticker"], "member_days_in_window": days, "membership_periods": "; ".join(periods)})
    unmapped.sort(key=lambda r: -r["member_days_in_window"])

    reports_dir.mkdir(parents=True, exist_ok=True)
    with open(reports_dir / "unmapped_tickers.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["ticker", "member_days_in_window", "membership_periods"])
        writer.writeheader()
        writer.writerows(unmapped)

    by_source: dict[str, int] = {}
    for row in rows:
        by_source[row["source"]] = by_source.get(row["source"], 0) + 1
    disagreements = [r for r in rows if r["note"] and "Wikipedia says" in r["note"]]
    for r in disagreements:
        log.warning("CIK disagreement for %s: mapped to %s, %s", r["sec_ticker"], r["cik"], r["note"])

    log.info("Ticker mapping: %s", ", ".join(f"{k}={v}" for k, v in sorted(by_source.items())))
    if unmapped:
        log.warning("%d tickers could not be mapped. See reports/unmapped_tickers.csv", len(unmapped))
    return {"tickers": len(rows), "by_source": by_source, "unmapped": len(unmapped), "wikipedia_disagreements": len(disagreements)}
