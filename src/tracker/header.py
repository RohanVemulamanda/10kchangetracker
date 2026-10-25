"""Read a filing's own header page: the trustworthy acceptance time and the list of documents.

URL: https://www.sec.gov/Archives/edgar/data/<CIK>/<accession without dashes>/<accession>-index-headers.html

The page shows the filing's SGML header, roughly:

    <ACCEPTANCE-DATETIME>20191030181236        <- YYYYMMDDHHMMSS, Eastern Time
    CONFORMED SUBMISSION TYPE:  10-K
    CONFORMED PERIOD OF REPORT: 20190928
    FILED AS OF DATE:           20191031
    FILER:
        COMPANY DATA:
            COMPANY CONFORMED NAME:             Apple Inc.
            CENTRAL INDEX KEY:                  0000320193
            STANDARD INDUSTRIAL CLASSIFICATION: ELECTRONIC COMPUTERS [3571]

followed by one block per document:

    <DOCUMENT>
    <TYPE>10-K
    <SEQUENCE>1
    <FILENAME>a10-k20199282019.htm
    <DESCRIPTION>10-K

Why we read this instead of the submissions API's "acceptanceDateTime" (D-008): that
field is labeled UTC but has been documented to be off by hours for some filers. Phase 4
needs the exact time to apply the after-market-close rule, so we use the header.

Bonus: the header gives the company's name and SIC industry code AS OF THE FILING,
not today's (D-015).
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")


@dataclass
class HeaderInfo:
    acceptance_et: datetime | None = None      # naive datetime, Eastern Time
    period_of_report: str | None = None        # 'YYYY-MM-DD'
    filed_as_of: str | None = None             # 'YYYY-MM-DD'
    company_name: str | None = None
    sic_code: str | None = None
    sic_description: str | None = None
    documents: list[dict] = field(default_factory=list)


def index_headers_url(cik: int, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index-headers.html"


def document_url(cik: int, accession: str, filename: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{filename}"


def _first(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None


def _yyyymmdd_to_iso(value: str | None) -> str | None:
    if not value or not re.fullmatch(r"\d{8}", value):
        return None
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def parse_index_headers(raw: bytes, cik: int) -> HeaderInfo:
    """Pull the fields we need out of the header page.

    The page is HTML, so the SGML tags appear as &lt;TYPE&gt; in the raw file.
    html.unescape turns them back into <TYPE>. We never strip tags, and each
    pattern stops at a line break or a '<', so leftover HTML can't sneak into a value.
    """
    text = html.unescape(raw.decode("utf-8", errors="replace"))
    info = HeaderInfo()

    stamp = _first(r"<ACCEPTANCE-DATETIME>\s*(\d{14})", text)
    if stamp:
        info.acceptance_et = datetime.strptime(stamp, "%Y%m%d%H%M%S")
    info.period_of_report = _yyyymmdd_to_iso(_first(r"CONFORMED PERIOD OF REPORT:\s*(\d{8})", text))
    info.filed_as_of = _yyyymmdd_to_iso(_first(r"FILED AS OF DATE:\s*(\d{8})", text))

    # Header section = everything before the first document.
    header_text = text.split("<DOCUMENT>")[0]

    # A filing can list several filers (e.g. a utility and its subsidiaries in one
    # combined 10-K). Use the block whose CIK is ours; fall back to the first one.
    filer_blocks = header_text.split("FILER:")[1:]
    chosen = None
    for block in filer_blocks:
        block_cik = _first(r"CENTRAL INDEX KEY:\s*(\d+)", block)
        if block_cik and int(block_cik) == cik:
            chosen = block
            break
    if chosen is None and filer_blocks:
        chosen = filer_blocks[0]
    if chosen:
        info.company_name = _first(r"COMPANY CONFORMED NAME:\s*([^\n<]+)", chosen)
        sic = re.search(r"STANDARD INDUSTRIAL CLASSIFICATION:\s*([^\n<\[]*)\[(\d{4})\]", chosen)
        if sic:
            info.sic_description = sic.group(1).strip() or None
            info.sic_code = sic.group(2)

    for chunk in text.split("<DOCUMENT>")[1:]:
        doc = {
            "type": _first(r"<TYPE>\s*([^\s<]+)", chunk),
            "sequence": _first(r"<SEQUENCE>\s*([^\s<]+)", chunk),
            "filename": _first(r"<FILENAME>\s*([^\s<]+)", chunk),
            "description": _first(r"<DESCRIPTION>\s*([^\n<]+)", chunk),
        }
        if doc["filename"]:
            info.documents.append(doc)
    return info


def api_minus_header_minutes(api_raw: str | None, header_et: datetime | None) -> float | None:
    """How far the API's acceptance time is from the header's, in minutes.

    The API value looks like '2019-10-30T22:12:36.000Z' (labeled UTC). We convert
    the header's Eastern time to UTC and subtract. 0 means they agree.
    About -240 or -300 means the API time was really Eastern time with a UTC label.
    """
    if not api_raw or header_et is None:
        return None
    try:
        api_time = datetime.fromisoformat(api_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if api_time.tzinfo is None:
        api_time = api_time.replace(tzinfo=timezone.utc)
    header_utc = header_et.replace(tzinfo=EASTERN).astimezone(timezone.utc)
    return round((api_time - header_utc).total_seconds() / 60, 1)
