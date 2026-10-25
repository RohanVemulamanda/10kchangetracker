"""Check that each sample 10-K really comes from a large company (D-025).

Why: a ticker can be reused. After Paramount Global merged in 2025, SEC's ticker
file gave "PARA" to Banzai International, a small former blank-check company, so
Banzai's 10-Ks took Paramount's place in the sample. The Phase 1 check ("did this
company file a 10-K while in the index?") can't catch that: Banzai did file 10-Ks.

The cover page of every 10-K states the "public float": the market value of shares
held by outside investors, tagged for computers as dei:EntityPublicFloat. S&P 500
members are worth billions; a former blank-check company is worth millions. So a
sample 10-K with a public float under $1 billion, or none, gets listed for review.
"""
from __future__ import annotations

import csv
import gzip
import logging
import re
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

FLOAT_TAG = re.compile(rb"<ix:nonfraction\b([^>]*\bname=[\"']dei:EntityPublicFloat[\"'][^>]*)>(.*?)</ix:nonfraction>",
                       re.I | re.S)
ATTRIBUTE = re.compile(rb"\b(scale|format|sign)=[\"']([^\"']*)[\"']", re.I)
MIN_FLOAT = 1_000_000_000  # $1 billion


def parse_public_float(raw: bytes) -> float | None:
    """The largest public float on the cover page, in dollars. None if not tagged.

    The tagged text can be "434.37" with scale="9" (billions), "23,377" with
    scale="6" (millions), or "3,253,431,000,000" with scale="0".
    A filing can tag several values (one per registrant or share class); we take the largest.
    """
    values = []
    for attributes, inner in FLOAT_TAG.findall(raw):
        attrs = {k.lower(): v for k, v in ATTRIBUTE.findall(attributes)}
        text = re.sub(rb"<[^>]+>", b"", inner).decode("utf-8", "replace").strip()
        number_format = attrs.get(b"format", b"").lower().replace(b"-", b"")
        if b"numcommadecimal" in number_format:
            text = text.replace(".", "").replace(",", ".")  # European style "1.234,5"
        else:
            text = text.replace(",", "")
        try:
            number = float(re.sub(r"[^\d.]", "", text))
        except ValueError:
            continue  # e.g. "none" or "not applicable"
        scale = int(attrs.get(b"scale", b"0") or 0)
        value = number * 10 ** scale
        if value > 1e13 and number >= 1e6:
            # Over $10 trillion is impossible (Apple, the largest, is about $3 trillion). This is a
            # tagging mistake: the full dollar amount written out, but marked as millions (Zimmer Biomet 2021).
            value = number
        values.append(value)
    return max(values) if values else None


def check_filers(conn: sqlite3.Connection, raw_dir: Path, reports_dir: Path) -> dict:
    """Read the public float from every downloaded sample 10-K and list the suspicious ones."""
    rows = conn.execute(
        "SELECT f.accession_number, f.company_cik, f.fiscal_year, f.member_tickers, f.primary_path, "
        "f.company_name_at_filing, c.name_current FROM filings f LEFT JOIN companies c ON c.cik = f.company_cik "
        "WHERE f.selected = 1 AND f.role = 'sample' AND f.status = 'downloaded' ORDER BY f.company_cik, f.fiscal_year"
    ).fetchall()
    suspicious = []
    for r in rows:
        with gzip.open(raw_dir / r["primary_path"], "rb") as f:
            value = parse_public_float(f.read())
        if value is None or value < MIN_FLOAT:
            suspicious.append({
                "company_at_filing": r["company_name_at_filing"], "company_now": r["name_current"],
                "tickers": r["member_tickers"], "fiscal_year": r["fiscal_year"], "cik": r["company_cik"],
                "accession_number": r["accession_number"],
                "public_float_millions": round(value / 1e6, 1) if value is not None else "not tagged",
            })
    reports_dir.mkdir(parents=True, exist_ok=True)
    with open(reports_dir / "filer_size_check.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["company_at_filing", "company_now", "tickers", "fiscal_year", "cik",
                                               "accession_number", "public_float_millions"])
        writer.writeheader()
        writer.writerows(suspicious)
    log.info("Checked %d sample 10-Ks: %d have a public float under $1 billion or none tagged. "
             "See reports/filer_size_check.csv", len(rows), len(suspicious))
    return {"checked": len(rows), "suspicious": len(suspicious)}
