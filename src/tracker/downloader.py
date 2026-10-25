"""Download the documents for each selected filing, and record the result in the database.

For each filing we fetch:
  1. the header page    -> trustworthy acceptance time, name/SIC at filing, list of documents
  2. the main document  -> the 10-K itself
  3. any EX-13 exhibit  -> where some companies put their annual report (D-011)

Files are saved under data/raw/filings/<CIK>/<accession>/ as gzip files.

Resuming: every filing has a status ('pending', 'downloaded', 'failed') saved after
each filing. A restarted run only works on what isn't done. And because every file
goes through the cache, even a filing interrupted halfway doesn't re-download the
parts it already has.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from .edgar_client import DownloadError, EdgarClient, SecAccessDenied
from .header import api_minus_header_minutes, document_url, index_headers_url, parse_index_headers

log = logging.getLogger(__name__)

SMALL_MAIN_DOCUMENT_BYTES = 20_000  # a real 10-K is usually hundreds of KB


def filing_folder(raw_dir: Path, cik: int, accession: str) -> Path:
    return raw_dir / "filings" / str(cik) / accession.replace("-", "")


def download_one(client: EdgarClient, filing: dict, raw_dir: Path, download_exhibit_13: bool = True) -> dict:
    """Download one filing's files. Returns the database fields to update.

    Raises DownloadError if the header or main document can't be fetched.
    """
    cik, accession = filing["cik"], filing["accession_number"]
    folder = filing_folder(raw_dir, cik, accession)
    notes = []

    header_raw = client.get_cached(index_headers_url(cik, accession), folder / "index-headers.html.gz")
    info = parse_index_headers(header_raw, cik)
    if info.acceptance_et is None:
        notes.append("no acceptance time found in header")

    primary = filing.get("primary_document")
    if not primary:
        primary = next((d["filename"] for d in info.documents if d["type"] == filing["form"]), None)
        if not primary:
            raise DownloadError(index_headers_url(cik, accession), None, "could not identify the main 10-K document")
        notes.append("main document name taken from header (API had none)")

    primary_path = folder / (primary + ".gz")
    primary_bytes = client.get_cached(document_url(cik, accession, primary), primary_path)
    if len(primary_bytes) < SMALL_MAIN_DOCUMENT_BYTES:
        notes.append(f"main document is only {len(primary_bytes):,} bytes; may point to an exhibit")

    exhibit_paths = []
    if download_exhibit_13:
        for doc in info.documents:
            if (doc["type"] or "").upper().startswith("EX-13"):
                path = folder / (doc["filename"] + ".gz")
                client.get_cached(document_url(cik, accession, doc["filename"]), path)
                exhibit_paths.append(path.relative_to(raw_dir).as_posix())

    if info.period_of_report and info.period_of_report != filing.get("report_date"):
        notes.append(f"header period {info.period_of_report} differs from API report date {filing.get('report_date')}")

    return {
        "acceptance_et": info.acceptance_et.strftime("%Y-%m-%d %H:%M:%S") if info.acceptance_et else None,
        "api_minus_header_minutes": api_minus_header_minutes(filing.get("acceptance_api_raw"), info.acceptance_et),
        "company_name_at_filing": info.company_name,
        "sic_at_filing": info.sic_code,
        "header_period": info.period_of_report,
        "documents_json": json.dumps(info.documents),
        "primary_path": primary_path.relative_to(raw_dir).as_posix(),  # stored relative to data/raw
        "exhibit13_paths": json.dumps(exhibit_paths) if exhibit_paths else None,
        "check_notes": "; ".join(notes) or None,
    }


def _update(conn: sqlite3.Connection, accession: str, fields: dict) -> None:
    assignments = ", ".join(f"{name} = :{name}" for name in fields)
    conn.execute(f"UPDATE filings SET {assignments} WHERE accession_number = :accession", {**fields, "accession": accession})


def download_pending(
    conn: sqlite3.Connection,
    client: EdgarClient,
    raw_dir: Path,
    max_attempts: int,
    download_exhibit_13: bool = True,
    ciks: list[int] | None = None,
) -> dict:
    """Download every selected filing that isn't done yet. Returns counts for the summary."""
    # 1. Trust, but verify: a filing marked 'downloaded' whose file is missing goes back to 'pending'.
    reset = 0
    for row in conn.execute("SELECT accession_number, primary_path FROM filings WHERE status = 'downloaded' AND selected = 1").fetchall():
        if not row["primary_path"] or not (raw_dir / row["primary_path"]).exists():
            _update(conn, row["accession_number"], {"status": "pending"})
            reset += 1
    if reset:
        log.warning("%d filings were marked downloaded but their files are missing; they will be downloaded again", reset)
    conn.commit()

    # 2. The work list.
    sql = "SELECT * FROM filings WHERE selected = 1 AND (status = 'pending' OR (status = 'failed' AND attempts < ?))"
    params: list = [max_attempts]
    if ciks is not None:
        sql += f" AND company_cik IN ({','.join('?' * len(ciks))})"  # includes filings by a company's old IDs
        params += ciks
    todo = [dict(r) for r in conn.execute(sql + " ORDER BY cik, report_date", params).fetchall()]
    log.info("%d filings to download", len(todo))

    counts = {"attempted": len(todo), "downloaded": 0, "failed": 0, "reset_missing_files": reset}
    started = time.monotonic()
    for i, filing in enumerate(todo, start=1):
        accession = filing["accession_number"]
        try:
            fields = download_one(client, filing, raw_dir, download_exhibit_13)
            fields.update(status="downloaded", error=None, downloaded_at=datetime.now().isoformat(timespec="seconds"))
            counts["downloaded"] += 1
        except SecAccessDenied:
            conn.commit()
            raise  # stop the whole run; the message explains what to do
        except DownloadError as exc:
            log.error("Failed %s (CIK %s): %s", accession, filing["cik"], exc)
            fields = {"status": "failed", "error": exc.message}
            counts["failed"] += 1
        except Exception as exc:  # a bug or a very unusual file: record it, keep going
            log.exception("Unexpected error on %s (CIK %s)", accession, filing["cik"])
            fields = {"status": "failed", "error": f"unexpected error: {exc!r}"}
            counts["failed"] += 1
        fields["attempts"] = (filing["attempts"] or 0) + 1
        _update(conn, accession, fields)
        conn.commit()  # save after every filing, so a crash loses at most one

        if i % 25 == 0 or i == len(todo):
            elapsed = time.monotonic() - started
            remaining_min = elapsed / i * (len(todo) - i) / 60
            log.info("Progress: %d/%d (%d failed), about %.0f min left", i, len(todo), counts["failed"], remaining_min)
    return counts
