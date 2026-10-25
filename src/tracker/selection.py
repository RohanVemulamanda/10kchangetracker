"""Decide which of a company's filings we need. Pure logic, no downloading, so it's easy to test.

Rules (each one is in DECISIONS.md):
  D-005  Only original 10-Ks. 10-K/A (amendments) and 10-KT (transition reports
         covering a partial year) are excluded and logged.
  D-006  Two original 10-Ks for the same period end: keep the first one filed.
  D-004  Fiscal year comes from the period end date, using the Compustat rule.
  D-002  A 10-K is in the SAMPLE if its fiscal year is in our range AND the company
         (any of its tickers) was in the S&P 500 on the filing date.
  D-007  For every sample 10-K, the company's previous 10-K is also kept, as its
         COMPARISON, even if the company wasn't in the index back then. Without it,
         every company's first year in the index could never be scored.
  D-018  A company that reorganized under a new SEC ID (e.g. a new holding company)
         is one chain: filings from its old ID are included, each tagged with the ID
         that filed it ("_cik"). If both IDs filed a 10-K for the same period, the
         current ID's filing wins.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .dates import days_between, fiscal_year_from_period_end, parse_iso_date
from .universe import Membership


@dataclass
class SelectionResult:
    selected: list[dict] = field(default_factory=list)   # rows for the filings table
    excluded: list[dict] = field(default_factory=list)   # rows for excluded_filings
    notes: list[str] = field(default_factory=list)       # company-level warnings
    original_filing_dates: list[str] = field(default_factory=list)  # every kept 10-K's filing date


def select_filings(
    cik: int,
    filings: list[dict],
    company_tickers: set[str],
    membership: Membership,
    start_fiscal_year: int,
    end_fiscal_year: int,
    earliest_needed: str,
    form: str = "10-K",
) -> SelectionResult:
    result = SelectionResult()

    # Step 1: keep original 10-Ks; log the other 10-K variants we skip.
    originals = []
    for f in filings:
        form_name = (f.get("form") or "").strip()
        if not form_name.startswith("10-K") or (f.get("filingDate") or "") < earliest_needed:
            continue
        if form_name != form:
            result.excluded.append(_excluded(cik, f, f"form {form_name}, not an original {form}"))
        elif not f.get("reportDate"):
            result.excluded.append(_excluded(cik, f, "missing report date"))
        else:
            originals.append(f)

    # Step 2: one 10-K per period. Sort by period end, then filing date, so the
    # earliest filing for each period comes first and is the one we keep. In a
    # reorganized company's chain, the current ID's filing sorts first for its period.
    originals.sort(key=lambda f: (f["reportDate"], 0 if f.get("_cik", cik) == cik else 1,
                                  f["filingDate"], f["accessionNumber"]))
    kept: list[dict] = []
    for f in originals:
        if kept and kept[-1]["reportDate"] == f["reportDate"]:
            result.excluded.append(_excluded(cik, f, f"duplicate period; kept {kept[-1]['accessionNumber']}"))
        else:
            kept.append(f)
    result.original_filing_dates = [f["filingDate"] for f in kept]

    # Step 3: fiscal years. Flag two filings getting the same label. That happens to
    # companies with 52/53-week years ending right around May 31 / June 1. We keep
    # both: they really are different years, so dropping one would be wrong.
    fiscal_year = {}
    first_with_label: dict[int, str] = {}
    for f in kept:
        fy = fiscal_year_from_period_end(parse_iso_date(f["reportDate"]))
        fiscal_year[f["accessionNumber"]] = fy
        if fy in first_with_label:
            result.notes.append(
                f"two 10-Ks get fiscal-year label {fy} ({first_with_label[fy]} and {f['accessionNumber']}); "
                "period ends sit near the May/June cutoff"
            )
        first_with_label.setdefault(fy, f["accessionNumber"])

    # Step 4: sample filings = right fiscal year AND an index member on the filing date.
    selected: dict[str, dict] = {}
    for i, f in enumerate(kept):
        fy = fiscal_year[f["accessionNumber"]]
        if not start_fiscal_year <= fy <= end_fiscal_year:
            continue
        members = sorted(t for t in company_tickers if membership.is_member(t, f["filingDate"]))
        if not members:
            continue
        prior = kept[i - 1] if i > 0 else None
        selected[f["accessionNumber"]] = _row(cik, f, fy, "sample", members, prior)

    # Step 5: add each sample filing's prior 10-K as a comparison (unless it's already a sample).
    by_accession = {f["accessionNumber"]: f for f in kept}
    for row in list(selected.values()):
        prior_acc = row["prior_accession"]
        if row["role"] == "sample" and prior_acc and prior_acc not in selected:
            prior = by_accession[prior_acc]
            selected[prior_acc] = _row(cik, prior, fiscal_year[prior_acc], "comparison", [], None)

    result.selected = sorted(selected.values(), key=lambda r: r["report_date"])
    return result


def _row(cik: int, f: dict, fy: int, role: str, members: list[str], prior: dict | None) -> dict:
    return {
        "accession_number": f["accessionNumber"],
        "cik": f.get("_cik", cik),   # the ID that actually filed it
        "company_cik": cik,          # the company (chain) it belongs to
        "form": f["form"],
        "filing_date": f["filingDate"],
        "report_date": f["reportDate"],
        "fiscal_year": fy,
        "role": role,
        "member_tickers": ",".join(members) or None,
        "prior_accession": prior["accessionNumber"] if prior else None,
        "prior_gap_days": days_between(prior["reportDate"], f["reportDate"]) if prior else None,
        "primary_document": f.get("primaryDocument") or None,
        "acceptance_api_raw": f.get("acceptanceDateTime") or None,
    }


def _excluded(cik: int, f: dict, reason: str) -> dict:
    return {
        "accession_number": f.get("accessionNumber"),
        "cik": f.get("_cik", cik),
        "form": f.get("form"),
        "filing_date": f.get("filingDate"),
        "report_date": f.get("reportDate") or None,
        "reason": reason,
    }


def mapping_problem(original_filing_dates: list[str], member_days: int, periods: list[tuple[str, str | None]],
                    window_start: str, window_end: str) -> str | None:
    """Spot a ticker linked to the wrong company (for example, a reused ticker).

    A company in the index for a year or more has to file at least one 10-K during
    that time. If the CIK we linked has none, the link is probably wrong.
    Returns a warning message, or None if the link looks fine.
    """
    if member_days < 365:
        return None  # too short a stint to expect a 10-K; can't judge
    for filed in original_filing_dates:
        if not window_start <= filed <= window_end:
            continue
        for start, end in periods:
            if start <= filed and (end is None or filed < end):
                return None
    return f"no 10-K filed while in the index ({member_days} member days in window); ticker may be linked to the wrong company"
