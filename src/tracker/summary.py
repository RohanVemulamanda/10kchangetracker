"""The end-of-run report: what we have, what failed, and where the gaps are.

Writes:
  reports/phase1_summary.md      the readable summary (also printed to the screen)
  reports/gaps.csv               one row per gap, so each can be looked at
  reports/download_failures.csv  filings that failed, with the error
"""
from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from .ticker_map import sample_window_start
from .universe import Membership


def _simplify_reason(reason: str) -> str:
    """'duplicate period; kept 0000...' -> 'duplicate period' so reasons can be counted."""
    return reason.split(";")[0].strip()


def write_summary(conn: sqlite3.Connection, settings: dict, reports_dir: Path, reference_dir: Path) -> str:
    reports_dir.mkdir(parents=True, exist_ok=True)
    sample = settings["sample"]
    start_fy, end_fy = sample["start_fiscal_year"], sample["end_fiscal_year"]
    window_start, window_end = sample_window_start(start_fy), date.today().isoformat()

    meta_path = reference_dir / "universe_source.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    data_end = meta.get("data_end_date")
    membership = Membership.from_db(conn, data_end)

    out: list[str] = []
    gaps: list[dict] = []
    add = out.append

    add("# Phase 1 summary")
    add(f"Generated {datetime.now():%Y-%m-%d %H:%M}. Sample: fiscal years {start_fy}-{end_fy}, "
        f"companies in the S&P 500 on the filing date.\n")

    # ---------------------------------------------------------------- universe
    add("## Universe")
    if meta:
        add(f"- Membership source: {meta['source_repo']} at commit `{meta['source_commit'][:7]}`; "
            f"data runs {meta['first_date']} to **{data_end}**")
    mapping = {r["source"]: r["n"] for r in conn.execute("SELECT source, COUNT(*) AS n FROM ticker_map GROUP BY source")}
    total_tickers = sum(mapping.values())
    add(f"- Tickers in the index at some point since {window_start}: {total_tickers}")
    for source, n in sorted(mapping.items()):
        add(f"  - {source}: {n}")
    unmapped = [r["sec_ticker"] for r in conn.execute("SELECT sec_ticker FROM ticker_map WHERE cik IS NULL")]
    unmapped_days = sorted(((membership.member_days({t}, window_start, window_end), t) for t in unmapped), reverse=True)
    if unmapped:
        top = ", ".join(f"{t} ({d}d)" for d, t in unmapped_days[:15])
        add(f"- **Unmapped tickers: {len(unmapped)}** (most member-days first): {top}"
            + (" ..." if len(unmapped) > 15 else ""))
        add("  - These companies are missing from the sample until they're added to "
            "data/reference/manual_cik_map.csv. Full list: reports/unmapped_tickers.csv")
    for d, t in unmapped_days:
        gaps.append({"gap_type": "unmapped_ticker", "cik": None, "company": None, "ticker": t,
                     "accession_number": None, "fiscal_year": None, "detail": f"{d} member days in window"})
    disagreements = conn.execute("SELECT sec_ticker, cik, note FROM ticker_map WHERE note LIKE '%Wikipedia says%'").fetchall()
    add(f"- SEC vs Wikipedia CIK disagreements (current members): {len(disagreements)}")
    for r in disagreements:
        add(f"  - {r['sec_ticker']}: mapped to {r['cik']}; {r['note']}")
    add("")

    # ---------------------------------------------------------------- companies
    add("## Companies")
    status = {r["submissions_status"]: r["n"] for r in conn.execute(
        "SELECT submissions_status, COUNT(*) AS n FROM companies GROUP BY submissions_status")}
    add(f"- Filing lists downloaded: {status.get('ok', 0)}; failed: {status.get('failed', 0)}")
    for r in conn.execute("SELECT cik, submissions_error FROM companies WHERE submissions_status = 'failed'"):
        gaps.append({"gap_type": "filing_list_failed", "cik": r["cik"], "company": None, "ticker": None,
                     "accession_number": None, "fiscal_year": None, "detail": r["submissions_error"]})
    problems = conn.execute("SELECT cik, name_current, mapping_check FROM companies WHERE mapping_check IS NOT NULL").fetchall()
    add(f"- Ticker-to-company links that look wrong: {len(problems)}")
    for r in problems:
        add(f"  - CIK {r['cik']} {r['name_current']}: {r['mapping_check']}")
        gaps.append({"gap_type": "suspicious_mapping", "cik": r["cik"], "company": r["name_current"], "ticker": None,
                     "accession_number": None, "fiscal_year": None, "detail": r["mapping_check"]})

    tickers_by_cik: dict[int, set[str]] = defaultdict(set)
    for r in conn.execute("SELECT sec_ticker, cik FROM ticker_map WHERE cik IS NOT NULL"):
        tickers_by_cik[r["cik"]].add(r["sec_ticker"])
    sample_counts = {r["cik"]: r["n"] for r in conn.execute(
        "SELECT cik, COUNT(*) AS n FROM filings WHERE selected = 1 AND role = 'sample' GROUP BY cik")}
    no_sample = []
    for r in conn.execute("SELECT cik, name_current FROM companies WHERE submissions_status = 'ok'"):
        days = membership.member_days(tickers_by_cik.get(r["cik"], set()), window_start, window_end)
        if days >= 365 and sample_counts.get(r["cik"], 0) == 0:
            no_sample.append(r)
            gaps.append({"gap_type": "member_but_no_sample_10k", "cik": r["cik"], "company": r["name_current"],
                         "ticker": ",".join(sorted(tickers_by_cik[r["cik"]])), "accession_number": None,
                         "fiscal_year": None, "detail": f"{days} member days in window"})
    add(f"- Companies in the index a year or more with no sample 10-K: {len(no_sample)}")
    for r in no_sample[:20]:
        add(f"  - CIK {r['cik']} {r['name_current']}")
    notes = conn.execute("SELECT cik, name_current, selection_notes FROM companies WHERE selection_notes IS NOT NULL").fetchall()
    if notes:
        add(f"- Fiscal-year label clashes (both filings kept): {len(notes)}")
        for r in notes:
            add(f"  - CIK {r['cik']} {r['name_current']}: {r['selection_notes']}")
    add("")

    # ---------------------------------------------------------------- filings
    add("## Filings")
    add("| Fiscal year | Sample | Comparison only | Downloaded | Failed | Pending |")
    add("|---|---|---|---|---|---|")
    totals = Counter()
    for r in conn.execute(
        "SELECT fiscal_year, SUM(role='sample') AS s, SUM(role='comparison') AS c, SUM(status='downloaded') AS d, "
        "SUM(status='failed') AS f, SUM(status='pending') AS p FROM filings WHERE selected = 1 "
        "GROUP BY fiscal_year ORDER BY fiscal_year"
    ):
        add(f"| {r['fiscal_year']} | {r['s']} | {r['c']} | {r['d']} | {r['f']} | {r['p']} |")
        totals.update({"s": r["s"], "c": r["c"], "d": r["d"], "f": r["f"], "p": r["p"]})
    add(f"| **Total** | {totals['s']} | {totals['c']} | {totals['d']} | {totals['f']} | {totals['p']} |")
    add("\nExpect roughly 500 sample filings per complete fiscal year.\n")

    excluded = Counter(_simplify_reason(r["reason"]) for r in conn.execute("SELECT reason FROM excluded_filings"))
    add("Excluded on purpose:")
    for reason, n in excluded.most_common():
        add(f"- {reason}: {n}")
    if data_end:
        late = conn.execute("SELECT COUNT(*) FROM filings WHERE selected = 1 AND role = 'sample' AND filing_date > ?",
                            (data_end,)).fetchone()[0]
        add(f"- Sample filings dated after the membership data ends ({data_end}): {late} "
            "(membership assumed unchanged since then)")
    add("")

    # ---------------------------------------------------------------- downloads
    add("## Download failures")
    failures = conn.execute(
        "SELECT f.accession_number, f.cik, c.name_current, f.fiscal_year, f.error, f.attempts FROM filings f "
        "LEFT JOIN companies c ON c.cik = f.cik WHERE f.selected = 1 AND f.status = 'failed'").fetchall()
    if failures:
        for error, n in Counter(r["error"] for r in failures).most_common(10):
            add(f"- {error}: {n}")
    else:
        add("- None")
    with open(reports_dir / "download_failures.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["accession_number", "cik", "company", "fiscal_year", "error", "attempts"])
        writer.writerows([tuple(r) for r in failures])
    add("")

    # ---------------------------------------------------------------- gaps in the comparison chain
    lo, hi = sample["prior_year_min_days"], sample["prior_year_max_days"]
    for r in conn.execute(
        "SELECT f.accession_number, f.cik, c.name_current, f.fiscal_year, f.prior_gap_days, f.member_tickers FROM filings f "
        "LEFT JOIN companies c ON c.cik = f.cik WHERE f.selected = 1 AND f.role = 'sample' "
        "AND (f.prior_accession IS NULL OR f.prior_gap_days < ? OR f.prior_gap_days > ?)", (lo, hi)
    ):
        kind = "no_prior_10k" if r["prior_gap_days"] is None else "irregular_prior_gap"
        detail = "no earlier 10-K found (new company, spin-off, or IPO?)" if kind == "no_prior_10k" \
            else f"prior period ended {r['prior_gap_days']} days earlier (normal: {lo}-{hi})"
        gaps.append({"gap_type": kind, "cik": r["cik"], "company": r["name_current"], "ticker": r["member_tickers"],
                     "accession_number": r["accession_number"], "fiscal_year": r["fiscal_year"], "detail": detail})
    gap_counts = Counter(g["gap_type"] for g in gaps)
    add("## Gaps (details in reports/gaps.csv)")
    for kind, n in sorted(gap_counts.items()):
        add(f"- {kind}: {n}")
    if not gaps:
        add("- None")
    with open(reports_dir / "gaps.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["gap_type", "cik", "company", "ticker", "accession_number", "fiscal_year", "detail"])
        writer.writeheader()
        writer.writerows(gaps)
    add("")

    # ---------------------------------------------------------------- data checks
    add("## Data checks (downloaded filings)")
    diffs = [r[0] for r in conn.execute(
        "SELECT api_minus_header_minutes FROM filings WHERE selected = 1 AND status = 'downloaded'")]
    known = [d for d in diffs if d is not None]
    agree = sum(1 for d in known if abs(d) < 1)
    eastern_labeled_utc = sum(1 for d in known if 230 <= abs(d) <= 310)
    add(f"- Acceptance time, API vs filing header: {agree} agree, {eastern_labeled_utc} off by 4-5 hours, "
        f"{len(known) - agree - eastern_labeled_utc} off by some other amount, {len(diffs) - len(known)} not comparable")
    after_close = conn.execute(
        "SELECT COUNT(*) FROM filings WHERE selected = 1 AND role = 'sample' AND status = 'downloaded' "
        "AND substr(acceptance_et, 12) >= '16:00:00'").fetchone()[0]
    add(f"- Sample 10-Ks accepted at or after 4:00 pm Eastern (count from next trading day in Phase 4): {after_close}")
    for label, pattern in [("Header period differs from API report date", "%header period%"),
                           ("Main document suspiciously small", "%main document is only%"),
                           ("Main document name missing from API", "%taken from header%")]:
        n = conn.execute("SELECT COUNT(*) FROM filings WHERE selected = 1 AND check_notes LIKE ?", (pattern,)).fetchone()[0]
        add(f"- {label}: {n}")
    ex13 = conn.execute("SELECT COUNT(*) FROM filings WHERE selected = 1 AND exhibit13_paths IS NOT NULL").fetchone()[0]
    add(f"- Filings with an EX-13 exhibit downloaded: {ex13}")

    text = "\n".join(out) + "\n"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "phase1_summary.md").write_text(text, encoding="utf-8")
    return text
