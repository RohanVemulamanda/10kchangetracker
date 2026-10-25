"""Phase 4: monthly portfolios sorted by how much each company's 10-K changed (D-033).

Every month:
  1. each company's usable score: its most recent 10-K that was accepted before the month
     started (it counts from the month after acceptance) and at most 12 months ago;
  2. companies sorted by that score into 5 equal groups: Q1 = lowest similarity ("changers"),
     Q5 = highest ("non-changers");
  3. each group's return that month, equal-weighted or weighted by market value at the start
     of the month. Q5 - Q1 is the strategy: buy non-changers, sell changers.

Stock returns come in as a plain table, whatever the source (CRSP or another):
  company_cik, month (pandas Period), ret (the month's total return, with dividends and any
  delisting return, as a decimal), me_start (market value at the start of the month).
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

QUINTILES = 5
MAX_SCORE_AGE_MONTHS = 12


def load_scores(conn: sqlite3.Connection, cconn: sqlite3.Connection, version: str = "main") -> pd.DataFrame:
    """Every scored sample filing: company, acceptance time, industry code, the four measures and flags."""
    scores = pd.read_sql_query(
        "SELECT accession_number, sim_cosine, sim_jaccard, sim_min_edit, sim_simple, flags FROM changes "
        "WHERE version = ? AND status = 'ok' AND section = 'item_1a'", cconn, params=(version,))
    filings = pd.read_sql_query(
        "SELECT accession_number, company_cik, fiscal_year, acceptance_et, sic_at_filing FROM filings "
        "WHERE selected = 1 AND role = 'sample'", conn)
    scores = scores.merge(filings, on="accession_number", how="inner")
    scores["flags"] = scores["flags"].fillna("")
    scores["entry_month"] = entry_month(scores["acceptance_et"])
    return scores


def entry_month(acceptance_et: pd.Series) -> pd.Series:
    """The month a filing's score can first be used: the month after it was accepted (D-033).
    Acceptance times are Eastern Time, read from each filing's own header (D-008)."""
    return pd.to_datetime(acceptance_et.str[:19]).dt.to_period("M") + 1


def is_financial(sic: pd.Series) -> pd.Series:
    """SIC codes 6000-6999: banks, insurers, brokers and real estate (D-015, D-033)."""
    codes = pd.to_numeric(sic, errors="coerce")
    return (codes >= 6000) & (codes <= 6999)


def monthly_scores(scores: pd.DataFrame, months: pd.PeriodIndex, measure: str) -> pd.DataFrame:
    """For each month, each company's usable score. One row per company and month:
    month, company_cik, accession_number, score."""
    rows = []
    ordered = scores.sort_values(["company_cik", "entry_month"])
    for month in months:
        usable = ordered[(ordered.entry_month <= month) & (ordered.entry_month > month - MAX_SCORE_AGE_MONTHS)]
        latest = usable.groupby("company_cik").tail(1)          # the most recent filing wins
        rows.append(pd.DataFrame({"month": month, "company_cik": latest.company_cik.to_numpy(),
                                  "accession_number": latest.accession_number.to_numpy(),
                                  "score": latest[measure].to_numpy()}))
    return pd.concat(rows, ignore_index=True)


def assign_quintiles(held: pd.DataFrame) -> pd.DataFrame:
    """Add a "quintile" column, 1 (lowest similarity) to 5, within each month. Ties are broken by
    company ID so the result is the same every run."""
    held = held.sort_values(["month", "score", "company_cik"]).copy()
    held["quintile"] = held.groupby("month")["score"].transform(
        lambda s: pd.qcut(np.arange(len(s)), QUINTILES, labels=False) + 1)
    return held


def portfolio_returns(held: pd.DataFrame, returns: pd.DataFrame, weighting: str = "equal") -> pd.DataFrame:
    """Each quintile's return per month, plus "Q5-Q1" and how many stocks each month had.

    The sort uses every company with a usable score. A company with no return that month
    (no price data, or delisted in an earlier month) is left out of that month's average;
    `missing` counts them, so gaps in the price data are visible, not hidden.
    """
    merged = held.merge(returns[["company_cik", "month", "ret", "me_start"]], on=["company_cik", "month"], how="left")
    merged["has_return"] = merged["ret"].notna()
    if weighting == "value":
        merged["has_return"] &= merged["me_start"].notna() & (merged["me_start"] > 0)
    usable = merged[merged.has_return].copy()
    if weighting == "equal":
        usable["weight"] = 1.0
    elif weighting == "value":
        usable["weight"] = usable["me_start"]
    else:
        raise ValueError(f"unknown weighting {weighting!r}")
    usable["weighted"] = usable["ret"] * usable["weight"]
    sums = usable.groupby(["month", "quintile"])[["weighted", "weight"]].sum()
    table = (sums["weighted"] / sums["weight"]).unstack("quintile")
    table.columns = [f"Q{int(q)}" for q in table.columns]
    table["Q5-Q1"] = table[f"Q{QUINTILES}"] - table["Q1"]
    table["stocks"] = usable.groupby("month").size()
    table["missing"] = (~merged.has_return).groupby(merged["month"]).sum()
    return table


def add_controls(returns: pd.DataFrame) -> pd.DataFrame:
    """Controls for the Fama-MacBeth regression (D-033): log market value at the start of the month,
    and the return over months t-12 to t-2 (the usual momentum measure: it skips the latest month)."""
    out = returns.sort_values(["company_cik", "month"]).copy()
    out["log_me"] = np.log(out["me_start"].where(out["me_start"] > 0))
    growth = 1 + out["ret"]

    def past_return(g: pd.Series) -> pd.Series:
        # product of the 11 monthly returns from t-12 to t-2; needs all 11 months
        return g.shift(2).rolling(11, min_periods=11).apply(np.prod, raw=True) - 1

    out["past_ret"] = growth.groupby(out["company_cik"]).transform(past_return)
    # rolling() counts rows, not calendar months: blank it where a company's months have gaps
    gap = out.groupby("company_cik")["month"].transform(lambda m: (m - m.shift(12)).apply(
        lambda d: d.n if pd.notna(d) else np.nan))
    out.loc[gap != 12, "past_ret"] = np.nan
    return out
