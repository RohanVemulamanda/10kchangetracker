"""Phase 2: extract Item 1A (Risk Factors) from every downloaded 10-K.

For each filing, try in this order and keep the first that finds 300+ words (D-020):
  1. "item":              Item 1A in the main 10-K document
  2. "item_exhibit13":    if the main document's Item 1A only points elsewhere
     "heading_exhibit13"  ("...can be found in the Annual Report..."), look in the
                          EX-13 exhibit: by Item 1A header, then by "Risk Factors" heading
  3. "heading":           a "Risk Factors" heading in the main document
  4. the EX-13 methods, if not tried yet

Results go to data/processed/sections.db, one row per filing and section.
The run resumes: filings already extracted by the current code version are skipped.
"""
from __future__ import annotations

import gzip
import json
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from .html_text import Block, html_to_blocks
from .sections import (ITEM_1A, MIN_SECTION_WORDS, SectionSpec, find_by_heading, find_by_item, is_reference_only,
                       overrun_hits, page_furniture, scoring_text, section_blocks)

log = logging.getLogger(__name__)

# Bump this whenever the extraction rules change. Rows made by an older version get redone.
EXTRACTOR_VERSION = "1.0"

# Quality-check thresholds (D-021)
MIN_WORDS_OK = 1_000
MAX_WORDS_OK = 50_000
MAX_LENGTH_RATIO = 3.0   # vs the same company's prior-year extraction

SCHEMA = """
CREATE TABLE IF NOT EXISTS sections (
    accession_number  TEXT NOT NULL,
    section           TEXT NOT NULL,     -- 'item_1a' (later also 'item_7', 'item_3')
    status            TEXT NOT NULL,     -- 'ok', 'flagged', 'not_found' or 'error'
    method            TEXT,              -- which rule found it (see module docstring)
    source_document   TEXT,              -- file it came from, relative to data/raw
    header_text       TEXT,              -- the line where the section starts
    end_text          TEXT,              -- the line where it stops (not included)
    words             INTEGER,           -- words in the scoring version
    paragraphs        INTEGER,
    removed_blocks    INTEGER,           -- page numbers, headers and footers taken out
    flags             TEXT,              -- quality-check flags, comma-separated
    notes             TEXT,
    display_json      TEXT,              -- paragraphs as written: [{"t": text, "b": bold, "i": italic, "table": 0/1}]
    scoring_text      TEXT,              -- cleaned prose for Phase 3, one paragraph per line
    extractor_version TEXT,
    extracted_at      TEXT,
    seconds           REAL,
    error             TEXT,
    PRIMARY KEY (accession_number, section)
);
"""


def connect_sections(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def load_blocks(raw_dir: Path, relative_path: str) -> list[Block]:
    with gzip.open(raw_dir / relative_path, "rb") as f:
        return html_to_blocks(f.read())


def extract_filing(filing: dict, raw_dir: Path, spec: SectionSpec = ITEM_1A) -> dict:
    """Extract one section from one filing. Returns the row to save."""
    started = time.monotonic()
    notes: list[str] = []
    documents = [("main", filing["primary_path"])]
    documents += [("exhibit13", p) for p in json.loads(filing["exhibit13_paths"] or "[]")]
    blocks_by_doc = {path: load_blocks(raw_dir, path) for _, path in documents}
    main_path = filing["primary_path"]

    attempts: list[tuple[str, str, str]] = []  # (method name, document path, "item" or "heading")
    main_item = find_by_item(blocks_by_doc[main_path], spec)
    if main_item is not None and main_item.words >= MIN_SECTION_WORDS:
        attempts.append(("item", main_path, "item"))
    else:
        if main_item is not None and is_reference_only(blocks_by_doc[main_path], main_item):
            notes.append("Item 1A in the main document refers elsewhere: "
                         + " ".join(b.text for b in blocks_by_doc[main_path][main_item.start + 1:main_item.end])[:300])
            attempts += [("item_exhibit13", p, "item") for kind, p in documents if kind == "exhibit13"]
            attempts += [("heading_exhibit13", p, "heading") for kind, p in documents if kind == "exhibit13"]
        attempts.append(("heading", main_path, "heading"))
        for kind, p in documents:
            if kind == "exhibit13":
                for name, how in (("item_exhibit13", "item"), ("heading_exhibit13", "heading")):
                    if (name, p, how) not in attempts:
                        attempts.append((name, p, how))

    chosen = None
    for method, path, how in attempts:
        blocks = blocks_by_doc[path]
        found = find_by_item(blocks, spec) if how == "item" else find_by_heading(blocks, spec)
        if found is not None and found.words >= MIN_SECTION_WORDS:
            chosen = (method, path, found)
            break

    row = {
        "accession_number": filing["accession_number"], "section": spec.name,
        "extractor_version": EXTRACTOR_VERSION, "extracted_at": datetime.now().isoformat(timespec="seconds"),
        "error": None,
    }
    if chosen is None:
        tried = ", ".join(f"{m} in {Path(p).name}" for m, p, _ in attempts) or "item in main document"
        row.update(status="not_found", notes="; ".join(notes + [f"tried: {tried}"]),
                   flags="not_found", seconds=round(time.monotonic() - started, 2))
        return row

    method, path, found = chosen
    blocks = blocks_by_doc[path]
    kept, removed = section_blocks(blocks, found, page_furniture(blocks))
    text = scoring_text(kept)
    words = len(text.split())
    flags = []
    if words < MIN_WORDS_OK:
        flags.append("short")
    if words > MAX_WORDS_OK:
        flags.append("long")
    over = overrun_hits(kept, spec)
    if over:
        flags.append("overrun")
        notes.append("later headers inside the section: " + " | ".join(over[:3]))
    notes += found.notes
    row.update(
        status="flagged" if flags else "ok",
        method=method,
        source_document=path,
        header_text=found.header_text,
        end_text=found.end_text,
        words=words,
        paragraphs=len(kept),
        removed_blocks=removed,
        flags=",".join(flags) or None,
        notes="; ".join(notes) or None,
        display_json=json.dumps([{"t": b.text, "b": int(b.bold), "i": int(b.italic), "table": int(b.data_table)}
                                 for b in kept], ensure_ascii=False),
        scoring_text=text,
        seconds=round(time.monotonic() - started, 2),
    )
    return row


ROW_COLUMNS = ["accession_number", "section", "status", "method", "source_document", "header_text", "end_text",
               "words", "paragraphs", "removed_blocks", "flags", "notes", "display_json", "scoring_text",
               "extractor_version", "extracted_at", "seconds", "error"]


def save_row(sconn: sqlite3.Connection, row: dict) -> None:
    values = {c: row.get(c) for c in ROW_COLUMNS}
    sconn.execute(f"INSERT OR REPLACE INTO sections ({', '.join(ROW_COLUMNS)}) "
                  f"VALUES ({', '.join(':' + c for c in ROW_COLUMNS)})", values)


def flag_length_jumps(conn: sqlite3.Connection, sconn: sqlite3.Connection, spec: SectionSpec = ITEM_1A) -> int:
    """Flag sections more than 3x longer or shorter than the company's prior-year section.

    Usually an extraction error (grabbed too much, or stopped early); sometimes a real
    rewrite. Either way it deserves a look. Returns how many were flagged.
    """
    words = {r["accession_number"]: r["words"] for r in sconn.execute(
        "SELECT accession_number, words FROM sections WHERE section = ? AND words > 0", (spec.name,))}
    flagged = 0
    for f in conn.execute("SELECT accession_number, prior_accession FROM filings WHERE selected = 1 AND prior_accession IS NOT NULL"):
        now, before = words.get(f["accession_number"]), words.get(f["prior_accession"])
        if not now or not before:
            continue
        ratio = now / before
        row = sconn.execute("SELECT flags, notes FROM sections WHERE accession_number = ? AND section = ?",
                            (f["accession_number"], spec.name)).fetchone()
        flags = set(filter(None, (row["flags"] or "").split(",")))
        flags.discard("length_jump")
        if ratio > MAX_LENGTH_RATIO or ratio < 1 / MAX_LENGTH_RATIO:
            flags.add("length_jump")
            flagged += 1
        sconn.execute("UPDATE sections SET flags = ?, status = CASE WHEN status IN ('ok','flagged') THEN ? ELSE status END "
                      "WHERE accession_number = ? AND section = ?",
                      (",".join(sorted(flags)) or None, "flagged" if flags else "ok", f["accession_number"], spec.name))
    sconn.commit()
    return flagged


def run_extraction(conn: sqlite3.Connection, sconn: sqlite3.Connection, raw_dir: Path,
                   ciks: list[int] | None = None, force: bool = False, spec: SectionSpec = ITEM_1A) -> dict:
    """Extract the section from every downloaded filing that isn't done yet."""
    sql = ("SELECT accession_number, company_cik, primary_path, exhibit13_paths FROM filings "
           "WHERE selected = 1 AND status = 'downloaded'")
    params: list = []
    if ciks is not None:
        sql += f" AND company_cik IN ({','.join('?' * len(ciks))})"
        params += ciks
    filings = [dict(r) for r in conn.execute(sql + " ORDER BY company_cik, report_date", params)]

    done = {r["accession_number"] for r in sconn.execute(
        "SELECT accession_number FROM sections WHERE section = ? AND extractor_version = ? AND status != 'error'",
        (spec.name, EXTRACTOR_VERSION))}
    todo = filings if force else [f for f in filings if f["accession_number"] not in done]
    log.info("%d downloaded filings; %d to extract (%s)", len(filings), len(todo),
             "all, --force" if force else f"{len(filings) - len(todo)} already done with version {EXTRACTOR_VERSION}")

    counts = {"attempted": len(todo), "ok": 0, "flagged": 0, "not_found": 0, "error": 0}
    started = time.monotonic()
    for i, filing in enumerate(todo, start=1):
        try:
            row = extract_filing(filing, raw_dir, spec)
        except Exception as exc:  # one strange file must not stop the run; record it instead
            log.exception("Extraction failed for %s", filing["accession_number"])
            row = {"accession_number": filing["accession_number"], "section": spec.name, "status": "error",
                   "error": repr(exc)[:500], "extractor_version": EXTRACTOR_VERSION,
                   "extracted_at": datetime.now().isoformat(timespec="seconds")}
        save_row(sconn, row)
        sconn.commit()
        counts[row["status"]] += 1
        if row["status"] == "not_found":
            log.warning("Not found: %s (%s)", filing["accession_number"], row.get("notes", "")[:150])
        if i % 100 == 0 or i == len(todo):
            elapsed = time.monotonic() - started
            log.info("Progress: %d/%d (%d flagged, %d not found, %d errors), about %.0f min left", i, len(todo),
                     counts["flagged"], counts["not_found"], counts["error"], elapsed / i * (len(todo) - i) / 60)
    counts["length_jumps"] = flag_length_jumps(conn, sconn, spec)
    return counts
