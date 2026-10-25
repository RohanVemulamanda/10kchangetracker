"""Phase 3 reports: the scoring summary and lists for review.

  reports/phase3_summary.md     counts, spread of each measure, medians by year, agreement between measures
  reports/phase3_scores.csv     every scored pair, both versions, with company and year (for Excel)
  reports/phase3_summaries.csv  every risk factor summary found, with what was removed (D-029 review list)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .score import SCORER_VERSION

MEASURES = ["sim_cosine", "sim_jaccard", "sim_min_edit", "sim_simple"]


def load_scores(conn: sqlite3.Connection, cconn: sqlite3.Connection) -> pd.DataFrame:
    """Every row of the changes table, with company name, ticker, fiscal year and filing date."""
    changes = pd.read_sql_query("SELECT * FROM changes", cconn)
    filings = pd.read_sql_query(
        "SELECT f.accession_number, f.company_cik, f.fiscal_year, f.filing_date, f.member_tickers, "
        "f.prior_gap_days, c.name_current AS company FROM filings f LEFT JOIN companies c ON c.cik = f.company_cik "
        "WHERE f.selected = 1", conn)
    return changes.merge(filings, on="accession_number", how="left")


def describe(values: pd.Series) -> str:
    q = values.quantile([0.01, 0.10, 0.25, 0.50, 0.75, 0.90])
    return " | ".join(f"{v:.3f}" for v in [values.mean(), *q.values])


def write_phase3_summary(conn: sqlite3.Connection, cconn: sqlite3.Connection, reports_dir: Path) -> str:
    reports_dir.mkdir(parents=True, exist_ok=True)
    df = load_scores(conn, cconn)
    main = df[df.version == "main"]
    ok = df[df.status == "ok"]
    ok_main = ok[ok.version == "main"]

    out = ["# Phase 3 summary: Risk Factors change scores", "",
           f"Scorer version {SCORER_VERSION}. Similarity runs from 0 (nothing in common) to 1 (identical); "
           "change = 1 - similarity. Choices are in DECISIONS.md (D-028 to D-030).", "",
           "## Coverage", "",
           "| | Sample 10-Ks |", "|---|---|",
           f"| In the sample | {len(main):,} |",
           f"| Scored | {(main.status == 'ok').sum():,} |"]
    for note, n in main[main.status == "unscored"].note.value_counts().items():
        out.append(f"| Not scored: {note} | {n:,} |")
    out.append(f"| Errors | {(main.status == 'error').sum():,} |")

    out += ["", "## Spread of each measure", "",
            "Mean, then the 1st, 10th, 25th, 50th, 75th and 90th percentiles.", "",
            "| Version | Measure | Mean | p1 | p10 | p25 | p50 | p75 | p90 |", "|---|---|---|---|---|---|---|---|---|"]
    for version in ("main", "with_summary"):
        for m in MEASURES:
            out.append(f"| {version} | {m[4:]} | {describe(ok[ok.version == version][m])} |")

    out += ["", "## Median similarity by fiscal year (main version)", "",
            "| Fiscal year | Scored | " + " | ".join(m[4:] for m in MEASURES) + " |",
            "|---|---|" + "---|" * len(MEASURES)]
    for year, group in ok_main.groupby("fiscal_year"):
        out.append(f"| {year} | {len(group):,} | " + " | ".join(f"{group[m].median():.3f}" for m in MEASURES) + " |")

    out += ["", "## Do the measures agree? (rank correlation, main version)", "",
            "1 means two measures rank the filings in exactly the same order.", "",
            "| | " + " | ".join(m[4:] for m in MEASURES) + " |", "|---|" + "---|" * len(MEASURES)]
    corr = ok_main[MEASURES].rank().corr()   # rank correlation (Spearman): correlation of the ranks
    for m in MEASURES:
        out.append(f"| {m[4:]} | " + " | ".join(f"{corr.loc[m, n]:.2f}" for n in MEASURES) + " |")

    paired = ok_main.merge(ok[ok.version == "with_summary"], on="accession_number", suffixes=("", "_ws"))
    out += ["", "## Does removing summaries matter? (rank correlation, main vs with_summary)", "",
            "| Measure | Rank correlation | Filings whose score moved by more than 0.05 |", "|---|---|---|"]
    for m in MEASURES:
        moved = ((paired[m] - paired[m + "_ws"]).abs() > 0.05).sum()
        out.append(f"| {m[4:]} | {paired[m].rank().corr(paired[m + '_ws'].rank()):.3f} | {moved:,} |")

    summaries = pd.read_sql_query("SELECT * FROM risk_summaries", cconn)
    out += ["", "## Risk factor summaries (D-029)", "",
            f"Sections with a summary heading, among the filings scored (current or prior year): {len(summaries):,}", ""]
    for rule, n in summaries.rule.value_counts().items():
        out.append(f"- `{rule}`: {n:,}")
    out.append(f"- removed text containing a long paragraph (`long_line`, to check): {int(summaries.long_line.sum()):,}")

    out += ["", "## The 15 biggest changes (lowest cosine similarity, main version)", "",
            "| Company | Fiscal year | Cosine | Jaccard | Min edit | Simple | Words before -> after |",
            "|---|---|---|---|---|---|---|"]
    for _, r in ok_main.nsmallest(15, "sim_cosine").iterrows():
        out.append(f"| {r.company} | {r.fiscal_year} | {r.sim_cosine:.3f} | {r.sim_jaccard:.3f} | {r.sim_min_edit:.3f} | "
                   f"{r.sim_simple:.3f} | {r.prior_words:,} -> {r.current_words:,} |")

    text = "\n".join(out) + "\n"
    (reports_dir / "phase3_summary.md").write_text(text, encoding="utf-8")

    columns = ["company", "member_tickers", "fiscal_year", "filing_date", "accession_number", "prior_accession",
               "version", "status", "note", *MEASURES, "prior_words", "current_words", "sentences_added",
               "sentences_removed", "sentences_kept", "words_added", "words_removed"]
    df.sort_values(["company", "fiscal_year", "version"])[columns].to_csv(reports_dir / "phase3_scores.csv", index=False)
    summaries.to_csv(reports_dir / "phase3_summaries.csv", index=False)
    return text
