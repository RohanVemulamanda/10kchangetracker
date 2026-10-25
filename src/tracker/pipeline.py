"""The Phase 1 steps, in order. run.py calls these.

  check         test the SEC connection on Apple (run this first)
  universe      build S&P 500 membership periods
  map-tickers   link tickers to SEC company IDs (CIKs)
  find-filings  get each company's filing list and choose the 10-Ks we need
  download      download the chosen filings (resumes where it left off)
  summary       write reports/phase1_summary.md
  spot-check    print 10 random downloaded filings with EDGAR links, to check by hand
  all           universe -> map-tickers -> find-filings -> download -> summary
"""
from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from datetime import date, datetime

from . import db
from .config import ConfigError, get_user_agent, load_settings, project_path
from .downloader import download_pending
from .edgar_client import DownloadError, EdgarClient, SecAccessDenied
from .header import api_minus_header_minutes, index_headers_url, parse_index_headers
from .log_setup import setup_logging
from .selection import mapping_problem, select_filings
from .submissions import fetch_company_filings
from .summary import write_summary
from .ticker_map import load_sec_ticker_map, run_ticker_mapping, sample_window_start
from .universe import Membership, build_universe, normalize_ticker, read_data_end_date, source_file_path

log = logging.getLogger(__name__)


def make_client(settings: dict) -> EdgarClient:
    sec = settings["sec"]
    return EdgarClient(
        user_agent=get_user_agent(),
        requests_per_second=sec["requests_per_second"],
        max_retries=sec["max_retries"],
        timeout_seconds=sec["timeout_seconds"],
        stop_after_consecutive_403=sec["stop_after_consecutive_403"],
    )


def paths(settings: dict) -> dict:
    return {name: project_path(value) for name, value in settings["paths"].items()}


# ------------------------------------------------------------------ check

def step_check(settings: dict, client: EdgarClient) -> bool:
    """Fetch Apple's data and print what we parse, so problems show up before a long run."""
    p = paths(settings)
    ok = True
    sec_map = load_sec_ticker_map(client, p["raw_dir"])
    apple = sec_map.get("AAPL")
    print(f"1. SEC ticker file: {len(sec_map):,} tickers. AAPL -> {apple}")
    if not apple or apple["cik"] != 320193:
        print("   PROBLEM: expected AAPL to map to CIK 320193")
        ok = False

    company, filings = fetch_company_filings(client, 320193, p["raw_dir"], earliest_needed="2019-01-01")
    tenks = [f for f in filings if f.get("form") == "10-K"]
    print(f"2. Submissions API: {company['name_current']}, SIC {company['sic_current']}, "
          f"{len(filings):,} filings since 2019, {len(tenks)} original 10-Ks")
    needed = ["accessionNumber", "filingDate", "reportDate", "acceptanceDateTime", "form", "primaryDocument"]
    missing = [k for k in needed if tenks and k not in tenks[0]]
    if not tenks or missing:
        print(f"   PROBLEM: no 10-Ks found or fields missing: {missing}")
        return False

    latest = max(tenks, key=lambda f: f["filingDate"])
    print(f"   Latest 10-K: {latest['accessionNumber']} filed {latest['filingDate']}, period {latest['reportDate']}, "
          f"main document {latest['primaryDocument']}")

    raw = client.get_cached(index_headers_url(320193, latest["accessionNumber"]),
                            p["raw_dir"] / "check" / f"{latest['accessionNumber']}-index-headers.html.gz")
    info = parse_index_headers(raw, 320193)
    diff = api_minus_header_minutes(latest.get("acceptanceDateTime"), info.acceptance_et)
    print(f"3. Header page: accepted {info.acceptance_et} Eastern; API says {latest.get('acceptanceDateTime')} "
          f"(difference {diff} min)")
    print(f"   Name at filing: {info.company_name}; SIC {info.sic_code}; period {info.period_of_report}; "
          f"{len(info.documents)} documents")
    if info.acceptance_et is None or not info.documents or info.period_of_report != latest["reportDate"]:
        print("   PROBLEM: header parsing did not find everything it should")
        ok = False
    if latest["primaryDocument"] not in {d["filename"] for d in info.documents}:
        print("   PROBLEM: main document not listed in the header's documents")
        ok = False
    print(f"\nRequests made: {client.requests_made}. " + ("All checks passed." if ok else "Some checks FAILED; see above."))
    return ok


# ------------------------------------------------------------------ find filings

def _ciks_for_run(conn: sqlite3.Connection, only_tickers: list[str] | None) -> tuple[list[int], dict[int, set[str]]]:
    tickers_by_cik: dict[int, set[str]] = defaultdict(set)
    for row in conn.execute("SELECT sec_ticker, cik FROM ticker_map WHERE cik IS NOT NULL"):
        tickers_by_cik[row["cik"]].add(row["sec_ticker"])
    if not tickers_by_cik:
        raise RuntimeError("No mapped tickers. Run `python run.py map-tickers` first.")

    ciks = sorted(tickers_by_cik)
    if only_tickers:
        wanted = {normalize_ticker(t) for t in only_tickers}
        ciks = [c for c in ciks if tickers_by_cik[c] & wanted]
        found = set().union(*(tickers_by_cik[c] for c in ciks)) if ciks else set()
        for t in sorted(wanted - found):
            log.warning("Ticker %s is not a mapped S&P member in the sample window; skipping it", t)
    return ciks, tickers_by_cik


FILING_COLUMNS = ["accession_number", "cik", "form", "filing_date", "report_date", "fiscal_year", "role",
                  "member_tickers", "prior_accession", "prior_gap_days", "primary_document", "acceptance_api_raw"]


def step_find_filings(settings: dict, conn: sqlite3.Connection, client: EdgarClient,
                      only_tickers: list[str] | None = None) -> dict:
    p = paths(settings)
    sample = settings["sample"]
    membership = Membership.from_db(conn, read_data_end_date(p["reference_dir"]))
    if not membership.periods_by_ticker:
        raise RuntimeError("No membership data. Run `python run.py universe` first.")
    ciks, tickers_by_cik = _ciks_for_run(conn, only_tickers)

    start_fy, end_fy = sample["start_fiscal_year"], sample["end_fiscal_year"]
    earliest_needed = f"{start_fy - 2}-01-01"  # room for the prior-year comparison filings
    window_start, window_end = sample_window_start(start_fy), date.today().isoformat()
    refresh = settings["sec"]["refresh_submissions"]

    upsert_sql = (
        f"INSERT INTO filings ({', '.join(FILING_COLUMNS)}, selected) "
        f"VALUES ({', '.join(':' + c for c in FILING_COLUMNS)}, 1) "
        "ON CONFLICT(accession_number) DO UPDATE SET "
        + ", ".join(f"{c} = excluded.{c}" for c in FILING_COLUMNS[1:])
        + ", selected = 1"  # download status columns are deliberately left alone
    )

    stats = {"companies": len(ciks), "failed_companies": 0, "sample": 0, "comparison": 0, "excluded": 0, "mapping_problems": 0}
    log.info("Finding filings for %d companies (fiscal years %d-%d)", len(ciks), start_fy, end_fy)
    for i, cik in enumerate(ciks, start=1):
        now = datetime.now().isoformat(timespec="seconds")
        try:
            company, filings = fetch_company_filings(client, cik, p["raw_dir"], earliest_needed, refresh)
        except DownloadError as exc:
            log.error("Could not get the filing list for CIK %s: %s", cik, exc)
            conn.execute(
                "INSERT INTO companies (cik, submissions_status, submissions_error, updated_at) VALUES (?, 'failed', ?, ?) "
                "ON CONFLICT(cik) DO UPDATE SET submissions_status='failed', submissions_error=excluded.submissions_error, updated_at=excluded.updated_at",
                (cik, exc.message, now),
            )
            conn.commit()
            stats["failed_companies"] += 1
            continue

        tickers = tickers_by_cik[cik]
        result = select_filings(cik, filings, tickers, membership, start_fy, end_fy, earliest_needed, sample["form"])

        periods = [period for t in tickers for period in membership.periods_by_ticker.get(t, [])]
        member_days = membership.member_days(tickers, window_start, window_end)
        problem = mapping_problem(result.original_filing_dates, member_days, periods, window_start, window_end)
        if problem:
            log.warning("CIK %s (%s, tickers %s): %s", cik, company["name_current"], ",".join(sorted(tickers)), problem)
            stats["mapping_problems"] += 1
        for note in result.notes:
            log.warning("CIK %s: %s", cik, note)

        conn.execute(
            "INSERT INTO companies (cik, name_current, sic_current, sic_description, fiscal_year_end, tickers_current, "
            "submissions_status, submissions_error, mapping_check, selection_notes, updated_at) "
            "VALUES (:cik, :name_current, :sic_current, :sic_description, :fiscal_year_end, :tickers_current, 'ok', NULL, :mapping_check, :selection_notes, :updated_at) "
            "ON CONFLICT(cik) DO UPDATE SET name_current=excluded.name_current, sic_current=excluded.sic_current, "
            "sic_description=excluded.sic_description, fiscal_year_end=excluded.fiscal_year_end, tickers_current=excluded.tickers_current, "
            "submissions_status='ok', submissions_error=NULL, mapping_check=excluded.mapping_check, "
            "selection_notes=excluded.selection_notes, updated_at=excluded.updated_at",
            {**company, "mapping_check": problem, "selection_notes": "; ".join(result.notes) or None, "updated_at": now},
        )

        # Re-choose this company's filings from scratch under the current settings.
        conn.execute("UPDATE filings SET selected = 0 WHERE cik = ?", (cik,))
        for row in result.selected:
            existing = conn.execute("SELECT cik FROM filings WHERE accession_number = ?", (row["accession_number"],)).fetchone()
            if existing and existing["cik"] != cik:
                log.warning("Filing %s is listed under CIK %s and CIK %s (combined filing); keeping CIK %s",
                            row["accession_number"], existing["cik"], cik, cik)
            conn.execute(upsert_sql, row)
            stats[row["role"]] += 1
        conn.execute("DELETE FROM excluded_filings WHERE cik = ?", (cik,))
        conn.executemany(
            "INSERT OR REPLACE INTO excluded_filings (accession_number, cik, form, filing_date, report_date, reason) "
            "VALUES (:accession_number, :cik, :form, :filing_date, :report_date, :reason)",
            result.excluded,
        )
        stats["excluded"] += len(result.excluded)
        conn.commit()

        if i % 25 == 0 or i == len(ciks):
            log.info("Progress: %d/%d companies; %d sample and %d comparison filings so far",
                     i, len(ciks), stats["sample"], stats["comparison"])
    return stats


# ------------------------------------------------------------------ spot check

def step_spot_check(conn: sqlite3.Connection, how_many: int = 10, seed: int | None = None) -> None:
    """Print random downloaded sample filings with links, for checking by hand against EDGAR."""
    import random

    rows = [dict(r) for r in conn.execute(
        "SELECT f.accession_number, f.cik, f.filing_date, f.report_date, f.acceptance_et, f.fiscal_year, "
        "f.member_tickers, c.name_current FROM filings f LEFT JOIN companies c ON c.cik = f.cik "
        "WHERE f.selected = 1 AND f.role = 'sample' AND f.status = 'downloaded' ORDER BY f.accession_number")]
    if not rows:
        print("No downloaded sample filings yet.")
        return
    seed = seed if seed is not None else random.randrange(10_000)
    picks = random.Random(seed).sample(rows, min(how_many, len(rows)))
    print(f"{len(picks)} random filings (seed {seed}; run `spot-check --seed {seed}` to get the same ones again)\n")
    for r in picks:
        acc = r["accession_number"]
        print(f"{r['name_current']} ({r['member_tickers']}), fiscal year {r['fiscal_year']}")
        print(f"  ours:  filed {r['filing_date']} | accepted {r['acceptance_et']} ET | period {r['report_date']}")
        print(f"  EDGAR: https://www.sec.gov/Archives/edgar/data/{r['cik']}/{acc.replace('-', '')}/{acc}-index.htm\n")


# ------------------------------------------------------------------ run a command

def run(command: str, tickers: list[str] | None = None, seed: int | None = None) -> int:
    settings = load_settings()
    p = paths(settings)
    log_path = setup_logging(command.replace("-", "_"), p["logs_dir"])
    log.info("Command: %s%s. Log file: %s", command, f" (tickers: {','.join(tickers)})" if tickers else "", log_path)
    conn = db.connect(p["db"])
    try:
        needs_sec = command in {"check", "map-tickers", "find-filings", "download", "all"}
        client = make_client(settings) if needs_sec else None

        if command == "check":
            return 0 if step_check(settings, client) else 1
        if command == "spot-check":
            step_spot_check(conn, seed=seed)
            return 0

        if command in {"universe", "all"}:
            build_universe(settings, conn, p["reference_dir"])
        if command in {"map-tickers", "all"}:
            current_list = source_file_path(settings, settings["universe"]["current_file"], p["reference_dir"])
            if not current_list.exists():
                raise RuntimeError("Run `python run.py universe` first.")
            run_ticker_mapping(settings, conn, client, p["reference_dir"], p["raw_dir"], p["reports_dir"], current_list)
        if command in {"find-filings", "all"}:
            stats = step_find_filings(settings, conn, client, tickers)
            log.info("Find-filings done: %s", json.dumps(stats))
        if command in {"download", "all"}:
            ciks = _ciks_for_run(conn, tickers)[0] if tickers else None
            counts = download_pending(conn, client, p["raw_dir"], settings["sec"]["max_download_attempts"],
                                      settings["download"]["exhibit_13"], ciks)
            log.info("Download done: %d downloaded, %d failed (of %d attempted)",
                     counts["downloaded"], counts["failed"], counts["attempted"])
        if client is not None:
            log.info("SEC requests this run: %d (plus %d files read from cache)", client.requests_made, client.cache_hits)
        if command in {"summary", "all"} or (command in {"find-filings", "download"}):
            text = write_summary(conn, settings, p["reports_dir"], p["reference_dir"])
            print("\n" + text)
        return 0
    except ConfigError as exc:
        log.error("Settings problem: %s", exc)
        return 1
    except SecAccessDenied as exc:
        log.error(str(exc))
        return 2
    except (RuntimeError, DownloadError) as exc:
        log.error(str(exc))
        return 1
    except KeyboardInterrupt:
        log.warning("Stopped by you. Progress is saved; run the same command again to continue.")
        return 130
    except Exception:
        log.exception("Unexpected error (full details are in the log file: %s)", log_path)
        return 1
    finally:
        conn.close()
