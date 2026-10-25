"""Small date helpers, kept separate so the rules are easy to find and test."""
from __future__ import annotations

from datetime import date


def parse_iso_date(text: str | None) -> date | None:
    """'2024-09-28' -> date(2024, 9, 28). Empty or missing -> None."""
    if not text:
        return None
    return date.fromisoformat(text[:10])


def fiscal_year_from_period_end(period_end: date) -> int:
    """Label a fiscal year by when it ends, using the standard Compustat rule.

    If the year ends in June or later, it is that calendar year.
    If it ends in January through May, it counts as the PREVIOUS calendar year,
    because most of the year happened in the previous calendar year.

    Why we need our own rule: companies label years inconsistently.
    Walmart calls its year ending January 2025 "fiscal 2025".
    Target calls its year ending February 2025 "fiscal 2024".
    Under this rule both are 2024. See DECISIONS.md D-004.
    """
    return period_end.year if period_end.month >= 6 else period_end.year - 1


def days_between(earlier: str, later: str) -> int:
    """Number of days from one ISO date to another."""
    return (parse_iso_date(later) - parse_iso_date(earlier)).days
