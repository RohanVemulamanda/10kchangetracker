"""Get a company's list of filings from SEC's submissions API.

URL: https://data.sec.gov/submissions/CIK##########.json  (CIK padded to 10 digits)

The response has company details (name, SIC code, fiscal year end) plus filings
stored as parallel lists, one list per field:

    "filings": {
      "recent": {"accessionNumber": [...], "form": [...], "filingDate": [...], ...},
      "files":  [{"name": "CIK0000320193-submissions-001.json",
                  "filingFrom": "1994-01-26", "filingTo": "2014-07-21", ...}]
    }

Trap (problem 4 from the plan): "recent" only holds the newest filings. Big
companies file many insider-trading forms, so an older 10-K can sit on one of the
extra pages listed under "files". We fetch every extra page whose date range
reaches back into the period we need. Skipping them would silently drop old years.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .edgar_client import EdgarClient, save_gzip_atomic

log = logging.getLogger(__name__)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
EXTRA_PAGE_URL = "https://data.sec.gov/submissions/{name}"


def columns_to_rows(columns: dict) -> list[dict]:
    """Turn parallel lists into one dictionary per filing.

    {"form": ["10-K", "8-K"], "filingDate": ["2024-11-01", "2024-10-31"]}
    becomes
    [{"form": "10-K", "filingDate": "2024-11-01"}, {"form": "8-K", "filingDate": "2024-10-31"}]
    """
    n = len(columns.get("accessionNumber", []))
    keys = [k for k, v in columns.items() if isinstance(v, list) and len(v) == n]
    return [{k: columns[k][i] for k in keys} for i in range(n)]


def _get(client: EdgarClient, url: str, path: Path, refresh: bool) -> bytes:
    if refresh:
        data = client.get(url)
        save_gzip_atomic(path, data)
        return data
    return client.get_cached(url, path)


def fetch_company_filings(
    client: EdgarClient, cik: int, raw_dir: Path, earliest_needed: str, refresh: bool = False
) -> tuple[dict, list[dict]]:
    """Return (company details, list of filings) for one company.

    earliest_needed: 'YYYY-MM-DD'. Extra pages that end before this date are skipped,
    because nothing on them can matter for our sample.
    """
    folder = raw_dir / "submissions"
    main = json.loads(_get(client, SUBMISSIONS_URL.format(cik=cik), folder / f"CIK{cik:010d}.json.gz", refresh))

    company = {
        "cik": cik,
        "name_current": main.get("name"),
        "sic_current": main.get("sic"),
        "sic_description": main.get("sicDescription"),
        "fiscal_year_end": main.get("fiscalYearEnd"),
        "tickers_current": ",".join(main.get("tickers") or []),
    }

    filings_block = main.get("filings", {})
    rows = columns_to_rows(filings_block.get("recent", {}))

    for page in filings_block.get("files", []):
        if (page.get("filingTo") or "9999-12-31") < earliest_needed:
            continue
        log.debug("CIK %s: reading extra page %s", cik, page["name"])
        page_json = json.loads(_get(client, EXTRA_PAGE_URL.format(name=page["name"]), folder / (page["name"] + ".gz"), refresh))
        # Extra pages hold the same parallel lists, at the top level.
        columns = page_json.get("filings", {}).get("recent", page_json)
        rows.extend(columns_to_rows(columns))

    seen, unique = set(), []
    for row in rows:
        if row.get("accessionNumber") and row["accessionNumber"] not in seen:
            seen.add(row["accessionNumber"])
            unique.append(row)
    return company, unique
