"""Phase 3: score how much each sample 10-K's Risk Factors changed from the prior year.

For every sample filing with a prior-year 10-K (D-019: first-ever 10-Ks stay unscored), both
sections are compared twice (D-029):
  "main"           risk factor summaries removed
  "with_summary"   the sections exactly as extracted (a robustness check)
Each comparison gives the four similarity measures (D-030), plus counts of added, removed and
kept sentences. For the main version the added and removed sentences themselves are saved too,
for the "what changed" analysis and the dashboard.

Results go to data/processed/changes.db. The run resumes: a pair already scored by the current
SCORER_VERSION from the same two texts is skipped. If either text changes (for example after
a new extraction), that pair is scored again.
"""
from __future__ import annotations

import csv
import hashlib
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from .risk_summary import OverrideNotFound, Summary, remove_summary
from .similarity import compare
from .textprep import words

log = logging.getLogger(__name__)

# Bump this whenever the scoring rules change. Rows made by an older version get redone.
SCORER_VERSION = "1.1"   # 1.1: a bare "Summary" heading starts a summary; overrides match whole lines (D-029)

VERSIONS = ("main", "with_summary")

# A "voice switch" (D-031): the company changed how it refers to itself, between "we / our" and
# "the Company / its / Deere's". Every sentence about the company is reworded, so the pair looks
# like a big change although the risks are the same. Flagged, not changed: Phase 4 tests results
# with and without these pairs. One year uses first-person words for under 1.5% of all words,
# the other for 3% or more (in our data a clean gap: the 8 switches move from about 0-1.2% to
# 4-6%; the next-largest shifts, mostly mergers, stay above 1.5% in both years).
FIRST_PERSON = {"we", "our", "us", "ours"}
VOICE_LOW_SHARE = 0.015
VOICE_HIGH_SHARE = 0.03

SCHEMA = """
CREATE TABLE IF NOT EXISTS changes (
    accession_number   TEXT NOT NULL,     -- the sample 10-K
    section            TEXT NOT NULL,     -- 'item_1a'
    version            TEXT NOT NULL,     -- 'main' (summaries removed) or 'with_summary' (D-029)
    prior_accession    TEXT,              -- the prior-year 10-K it was compared with
    status             TEXT NOT NULL,     -- 'ok', 'unscored' (no prior year or no section) or 'error'
    note               TEXT,
    sim_cosine         REAL,              -- similarities: 1 = identical, 0 = nothing in common (D-030)
    sim_jaccard        REAL,
    sim_min_edit       REAL,
    sim_simple         REAL,
    prior_words        INTEGER,           -- words compared (after summary removal for 'main')
    current_words      INTEGER,
    prior_sentences    INTEGER,
    current_sentences  INTEGER,
    sentences_added    INTEGER,
    sentences_removed  INTEGER,
    sentences_kept     INTEGER,
    words_added        INTEGER,           -- words in added sentences
    words_removed      INTEGER,           -- words in removed sentences
    flags              TEXT,              -- 'voice_switch' (D-031); set after every pair is scored
    input_hash         TEXT,              -- fingerprint of the two texts; a change means "score again"
    scorer_version     TEXT,
    scored_at          TEXT,
    seconds            REAL,
    PRIMARY KEY (accession_number, section, version)
);

-- The sentences added and removed in each pair (main version only).
CREATE TABLE IF NOT EXISTS changed_sentences (
    accession_number  TEXT NOT NULL,
    section           TEXT NOT NULL,
    kind              TEXT NOT NULL,     -- 'added' (in this year's text) or 'removed' (in last year's)
    position          INTEGER NOT NULL,  -- order within its kind
    text              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS changed_sentences_filing ON changed_sentences (accession_number, section);

-- What summary removal found in each section that was scored (current or prior year).
CREATE TABLE IF NOT EXISTS risk_summaries (
    accession_number  TEXT NOT NULL,
    section           TEXT NOT NULL,
    rule              TEXT,              -- how its end was found; 'too_long' = not found, nothing removed
    start_line        INTEGER,
    end_line          INTEGER,
    words_removed     INTEGER,
    long_line         INTEGER,           -- 1 = removed text has a long paragraph: check it
    heading           TEXT,              -- the summary's heading line
    first_kept_line   TEXT,              -- the first line after the summary
    PRIMARY KEY (accession_number, section)
);
"""

CHANGE_COLUMNS = ["accession_number", "section", "version", "prior_accession", "status", "note",
                  "sim_cosine", "sim_jaccard", "sim_min_edit", "sim_simple", "prior_words", "current_words",
                  "prior_sentences", "current_sentences", "sentences_added", "sentences_removed",
                  "sentences_kept", "words_added", "words_removed", "flags", "input_hash", "scorer_version",
                  "scored_at", "seconds"]


def connect_changes(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(changes)")}
    if "flags" not in columns:  # databases made before the flag existed
        conn.execute("ALTER TABLE changes ADD COLUMN flags TEXT")
    return conn


def load_overrides(reference_dir: Path) -> dict[str, str]:
    """Hand-checked summary ends: accession number -> first line after the summary (D-029)."""
    path = reference_dir / "summary_overrides.csv"
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {row["accession_number"]: row["first_line_after_summary"] for row in csv.DictReader(f)}


def fingerprint(*texts: str | None) -> str:
    digest = hashlib.sha1()
    for text in texts:
        digest.update((text or "").encode("utf-8") + b"\x00")
    return digest.hexdigest()


def summary_row(accession: str, section: str, text: str, found: Summary | None) -> dict | None:
    """What was removed from one section, for the risk_summaries table. None if no summary."""
    if found is None:
        return None
    lines = text.split("\n")
    removed = lines[found.start:found.end] if found.end is not None else []
    return {
        "accession_number": accession, "section": section, "rule": found.rule,
        "start_line": found.start, "end_line": found.end,
        "words_removed": sum(len(line.split()) for line in removed), "long_line": int(found.long_line),
        "heading": lines[found.start],
        "first_kept_line": lines[found.end] if found.end is not None and found.end < len(lines) else None,
    }


def score_pair(accession: str, prior_accession: str, prior_text: str, current_text: str,
               overrides: dict[str, str], section: str = "item_1a") -> tuple[list[dict], list[dict], list[dict]]:
    """Score one pair both ways. Returns (change rows, changed sentence rows, summary rows)."""
    texts = {"with_summary": (prior_text, current_text)}
    summaries = []
    cleaned = []
    for acc, text in ((prior_accession, prior_text), (accession, current_text)):
        without, found = remove_summary(text, overrides.get(acc))
        cleaned.append(without)
        row = summary_row(acc, section, text, found)
        if row:
            summaries.append(row)
    texts["main"] = (cleaned[0], cleaned[1])

    changes, sentences = [], []
    for version in VERSIONS:
        started = time.monotonic()
        before, after = texts[version]
        result = compare(before, after)
        changes.append({
            "accession_number": accession, "section": section, "version": version,
            "prior_accession": prior_accession, "status": "ok", "note": None,
            "sim_cosine": result.cosine, "sim_jaccard": result.jaccard,
            "sim_min_edit": result.min_edit, "sim_simple": result.simple,
            "prior_words": result.prior_words, "current_words": result.current_words,
            "prior_sentences": result.prior_sentences, "current_sentences": result.current_sentences,
            "sentences_added": len(result.diff.added), "sentences_removed": len(result.diff.removed),
            "sentences_kept": result.diff.kept,
            "words_added": result.diff.words_added, "words_removed": result.diff.words_removed,
            "seconds": round(time.monotonic() - started, 2),
        })
        if version == "main":
            for kind, items in (("added", result.diff.added), ("removed", result.diff.removed)):
                sentences += [{"accession_number": accession, "section": section, "kind": kind,
                               "position": i, "text": s} for i, s in enumerate(items)]
    return changes, sentences, summaries


def save_pair(cconn: sqlite3.Connection, accession: str, section: str, changes: list[dict],
              sentences: list[dict], summaries: list[dict], input_hash: str) -> None:
    """Replace everything stored for this pair."""
    now = datetime.now().isoformat(timespec="seconds")
    cconn.execute("DELETE FROM changes WHERE accession_number = ? AND section = ?", (accession, section))
    cconn.execute("DELETE FROM changed_sentences WHERE accession_number = ? AND section = ?", (accession, section))
    for row in changes:
        values = {c: row.get(c) for c in CHANGE_COLUMNS}
        values.update(input_hash=input_hash, scorer_version=SCORER_VERSION, scored_at=now)
        cconn.execute(f"INSERT INTO changes ({', '.join(CHANGE_COLUMNS)}) "
                      f"VALUES ({', '.join(':' + c for c in CHANGE_COLUMNS)})", values)
    cconn.executemany("INSERT INTO changed_sentences (accession_number, section, kind, position, text) "
                      "VALUES (:accession_number, :section, :kind, :position, :text)", sentences)
    for row in summaries:
        cconn.execute("INSERT OR REPLACE INTO risk_summaries (accession_number, section, rule, start_line, end_line, "
                      "words_removed, long_line, heading, first_kept_line) VALUES (:accession_number, :section, :rule, "
                      ":start_line, :end_line, :words_removed, :long_line, :heading, :first_kept_line)", row)


def unscored_rows(accession: str, prior_accession: str | None, section: str, note: str) -> list[dict]:
    return [{"accession_number": accession, "section": section, "version": version,
             "prior_accession": prior_accession, "status": "unscored", "note": note} for version in VERSIONS]


def run_scoring(conn: sqlite3.Connection, sconn: sqlite3.Connection, cconn: sqlite3.Connection,
                reference_dir: Path, ciks: list[int] | None = None, force: bool = False,
                section: str = "item_1a") -> dict:
    """Score every sample filing that isn't scored yet (or whose texts changed)."""
    sql = "SELECT accession_number, prior_accession FROM filings WHERE selected = 1 AND role = 'sample'"
    params: list = []
    if ciks is not None:
        sql += f" AND company_cik IN ({','.join('?' * len(ciks))})"
        params += ciks
    filings = [dict(r) for r in conn.execute(sql + " ORDER BY company_cik, report_date", params)]
    overrides = load_overrides(reference_dir)

    def section_text(accession: str | None) -> str | None:
        if accession is None:
            return None
        row = sconn.execute("SELECT status, scoring_text FROM sections WHERE accession_number = ? AND section = ?",
                            (accession, section)).fetchone()
        return row["scoring_text"] if row and row["status"] in ("ok", "flagged") else None

    done = {(r["accession_number"], r["input_hash"]) for r in cconn.execute(
        "SELECT accession_number, input_hash FROM changes WHERE section = ? AND version = 'main' "
        "AND scorer_version = ? AND status != 'error'", (section, SCORER_VERSION))}
    counts = {"filings": len(filings), "scored": 0, "skipped": 0, "unscored": 0, "error": 0}
    started = time.monotonic()
    for i, f in enumerate(filings, start=1):
        accession, prior = f["accession_number"], f["prior_accession"]
        current_text, prior_text = section_text(accession), section_text(prior)
        input_hash = fingerprint(prior_text, current_text, overrides.get(prior), overrides.get(accession))
        if not force and (accession, input_hash) in done:
            counts["skipped"] += 1
            continue
        if prior is None:
            note = "first 10-K: no prior year to compare with (D-019)"
        elif current_text is None or prior_text is None:
            note = "Risk Factors section not extracted for " + ("this year" if current_text is None else "the prior year")
        else:
            note = None
        try:
            if note:
                save_pair(cconn, accession, section, unscored_rows(accession, prior, section, note), [], [], input_hash)
                counts["unscored"] += 1
            else:
                changes, sentences, summaries = score_pair(accession, prior, prior_text, current_text, overrides, section)
                save_pair(cconn, accession, section, changes, sentences, summaries, input_hash)
                counts["scored"] += 1
        except OverrideNotFound as exc:  # a hand-checked summary end no longer matches: stop, so it gets fixed
            raise RuntimeError(f"{accession}: {exc}. Check data/reference/summary_overrides.csv.") from exc
        except Exception as exc:  # one strange pair must not stop the run; record it instead
            log.exception("Scoring failed for %s", accession)
            error_rows = unscored_rows(accession, prior, section, repr(exc)[:500])
            for row in error_rows:
                row["status"] = "error"
            save_pair(cconn, accession, section, error_rows, [], [], input_hash)
            counts["error"] += 1
        cconn.commit()
        if i % 100 == 0 or i == len(filings):
            elapsed = time.monotonic() - started
            log.info("Progress: %d/%d (%d scored, %d already done), about %.0f min left", i, len(filings),
                     counts["scored"], counts["skipped"], elapsed / i * (len(filings) - i) / 60)
    counts["voice_switches"] = flag_voice_switches(sconn, cconn, section)
    return counts


def first_person_share(text: str) -> float:
    """Share of all words that are "we", "our", "us" or "ours"."""
    all_words = words(text)
    return sum(w in FIRST_PERSON for w in all_words) / len(all_words) if all_words else 0.0


def is_voice_switch(prior_text: str, current_text: str) -> bool:
    shares = sorted((first_person_share(prior_text), first_person_share(current_text)))
    return shares[0] < VOICE_LOW_SHARE and shares[1] >= VOICE_HIGH_SHARE


def flag_voice_switches(sconn: sqlite3.Connection, cconn: sqlite3.Connection, section: str = "item_1a") -> int:
    """Set the voice_switch flag on every scored pair (both versions). Returns how many were flagged."""
    texts = dict(sconn.execute("SELECT accession_number, scoring_text FROM sections WHERE section = ?", (section,)).fetchall())
    flagged = 0
    pairs = cconn.execute("SELECT accession_number, prior_accession FROM changes WHERE section = ? AND version = 'main' "
                          "AND status = 'ok'", (section,)).fetchall()
    for accession, prior in pairs:
        switch = is_voice_switch(texts[prior], texts[accession])
        flagged += switch
        cconn.execute("UPDATE changes SET flags = ? WHERE accession_number = ? AND section = ?",
                      ("voice_switch" if switch else None, accession, section))
    cconn.commit()
    return flagged
