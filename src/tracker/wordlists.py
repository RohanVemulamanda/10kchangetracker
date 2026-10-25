"""Phase 3: what kind of language changed, using the Loughran-McDonald word lists (D-032).

Loughran and McDonald built word lists for financial text: words that are negative ("loss",
"impairment"), uncertain ("may", "approximately"), or litigious ("lawsuit", "plaintiff") in a
10-K. For each scored pair we count these words in the sentences that are genuinely new this
year and in the ones that were genuinely dropped. A sentence that only moved (it is in both
"added" and "removed") is neither, so it isn't counted (D-030 note on reordering).

The dictionary is free for academic research. Commercial use needs a license from the authors.
It is downloaded by hand (see README) and pinned by its SHA-256 fingerprint, like the S&P list.
"""
from __future__ import annotations

import csv
import hashlib
import logging
import sqlite3
from pathlib import Path

from .textprep import words

log = logging.getLogger(__name__)

CATEGORIES = ("negative", "uncertainty", "litigious")

SCHEMA = """
-- Word-list counts in each pair's genuinely new and genuinely dropped sentences (main version).
CREATE TABLE IF NOT EXISTS change_words (
    accession_number  TEXT NOT NULL,
    section           TEXT NOT NULL,
    kind              TEXT NOT NULL,     -- 'new' (added, not moved) or 'dropped' (removed, not moved)
    sentences         INTEGER,
    words             INTEGER,
    negative          INTEGER,           -- Loughran-McDonald word counts (D-032)
    uncertainty       INTEGER,
    litigious         INTEGER,
    PRIMARY KEY (accession_number, section, kind)
);
"""


class WordListError(Exception):
    """The dictionary file is missing or isn't the pinned version."""


def load_word_lists(path: Path, sha256: str) -> dict[str, set[str]]:
    """Read the Master Dictionary into {category: set of lower-case words}.

    Each category column holds the year a word was added to that list, or minus the year it
    was removed ("-2020"). So a word is on a list only if its value is above zero.
    """
    if not path.exists():
        raise WordListError(f"Word list not found: {path}. See README, 'Running Phase 3', for the download.")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != sha256:
        raise WordListError(f"{path.name} is not the pinned version (SHA-256 {digest}, expected {sha256}).")
    lists: dict[str, set[str]] = {c: set() for c in CATEGORIES}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for category in CATEGORIES:
                if int(row[category.capitalize()]) > 0:
                    lists[category].add(row["Word"].lower())
    return lists


def dictionary_words(text: str) -> list[str]:
    """Our words (textprep.words), in the dictionary's form: the dictionary has no hyphens or
    apostrophes, so "third-party" counts as "third" and "party", and "company's" as "company"."""
    out = []
    for w in words(text):
        if w.endswith("'s"):
            w = w[:-2]
        out += [part for part in w.replace("'", "-").split("-") if part]
    return out


def count(sentences: list[str], lists: dict[str, set[str]]) -> dict:
    all_words = [w for s in sentences for w in dictionary_words(s)]
    result = {"sentences": len(sentences), "words": len(all_words)}
    for category in CATEGORIES:
        result[category] = sum(w in lists[category] for w in all_words)
    return result


def new_and_dropped(added: list[str], removed: list[str]) -> tuple[list[str], list[str]]:
    """Leave out sentences that only moved: an added sentence whose words match a removed one."""
    removed_keys = {" ".join(words(s)) for s in removed}
    added_keys = {" ".join(words(s)) for s in added}
    return ([s for s in added if " ".join(words(s)) not in removed_keys],
            [s for s in removed if " ".join(words(s)) not in added_keys])


def measure_change_words(cconn: sqlite3.Connection, lists: dict[str, set[str]], section: str = "item_1a") -> int:
    """Recount every scored pair from changed_sentences. Quick, so it's simply redone each run."""
    cconn.executescript(SCHEMA)
    cconn.execute("DELETE FROM change_words WHERE section = ?", (section,))
    sentences: dict[str, dict[str, list[str]]] = {}
    for accession, kind, text in cconn.execute(
            "SELECT accession_number, kind, text FROM changed_sentences WHERE section = ? ORDER BY accession_number, kind, position",
            (section,)):
        sentences.setdefault(accession, {"added": [], "removed": []})[kind].append(text)
    pairs = [r[0] for r in cconn.execute("SELECT accession_number FROM changes WHERE section = ? AND version = 'main' "
                                          "AND status = 'ok'", (section,))]
    for accession in pairs:
        both = sentences.get(accession, {"added": [], "removed": []})
        new, dropped = new_and_dropped(both["added"], both["removed"])
        for kind, items in (("new", new), ("dropped", dropped)):
            row = {"accession_number": accession, "section": section, "kind": kind, **count(items, lists)}
            cconn.execute("INSERT INTO change_words (accession_number, section, kind, sentences, words, negative, "
                          "uncertainty, litigious) VALUES (:accession_number, :section, :kind, :sentences, :words, "
                          ":negative, :uncertainty, :litigious)", row)
    cconn.commit()
    return len(pairs)
