"""Phase 3: the four similarity measures from Lazy Prices (D-030).

Each compares last year's section with this year's and gives a number from 0 to 1:
1 means identical, 0 means nothing in common. The change score is 1 - similarity.

  cosine     how often each word is used (word-count vectors). Small rewording barely moves it.
  jaccard    which distinct words appear at all (sets of words).
  min_edit   the fewest word insertions, deletions and substitutions that turn last year's
             words into this year's, divided by the longer document's length.
  simple     a "track changes" comparison of sentences: words in added and removed sentences,
             divided by the words in both documents.

Words and sentences come from textprep.py: lower case, numbers as "#", line breaks ignored.
"""
from __future__ import annotations

import difflib
import math
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from .textprep import split_sentences, words


def cosine(a: list[str], b: list[str]) -> float:
    """Cosine of the angle between the two word-count vectors."""
    if not a or not b:
        return 1.0 if a == b else 0.0
    count_a, count_b = Counter(a), Counter(b)
    dot = sum(n * count_b[w] for w, n in count_a.items())
    squares_a = sum(n * n for n in count_a.values())
    squares_b = sum(n * n for n in count_b.values())
    # One square root of a whole number, so identical documents give exactly 1.0
    return dot / math.sqrt(squares_a * squares_b)


def jaccard(a: list[str], b: list[str]) -> float:
    """Distinct words in both, divided by distinct words in either."""
    set_a, set_b = set(a), set(b)
    if not set_a and not set_b:
        return 1.0
    return len(set_a & set_b) / len(set_a | set_b)


def edit_distance(a: list[str], b: list[str]) -> int:
    """Fewest word insertions, deletions and substitutions to turn `a` into `b` (Levenshtein).

    The standard table method, one row at a time: row[j] is the distance between the first
    i words of `a` and the first j words of `b`. Each row is computed with numpy in one go,
    so two 10,000-word documents take about a second instead of minutes.
    """
    if len(a) < len(b):
        a, b = b, a                      # rows follow the longer document; each row is the shorter one
    if not b:
        return len(a)
    ids: dict[str, int] = {}
    a_ids = np.array([ids.setdefault(w, len(ids)) for w in a], dtype=np.int32)
    b_ids = np.array([ids.setdefault(w, len(ids)) for w in b], dtype=np.int32)
    columns = np.arange(len(b) + 1, dtype=np.int32)
    row = columns.copy()                 # distance from 0 words of `a` to the first j words of `b`
    for i, word in enumerate(a_ids, start=1):
        substitute = row[:-1] + (b_ids != word)    # match costs 0, substitution 1
        delete = row[1:] + 1
        best = np.minimum(substitute, delete)
        # Insertions run along the row: row[j] = min over k <= j of (best[k] + j - k).
        # Subtracting the column number turns that into a running minimum.
        best = np.concatenate(([i], best))
        row = np.minimum.accumulate(best - columns) + columns
    return int(row[-1])


def min_edit(a: list[str], b: list[str]) -> float:
    """1 - edit distance / length of the longer document."""
    longer = max(len(a), len(b))
    return 1.0 if longer == 0 else 1 - edit_distance(a, b) / longer


@dataclass
class SentenceDiff:
    """Which sentences were added, removed or kept, matched in order like "track changes"."""
    added: list[str] = field(default_factory=list)     # in this year's text only
    removed: list[str] = field(default_factory=list)   # in last year's text only
    kept: int = 0                                      # sentences in both
    words_added: int = 0
    words_removed: int = 0


def sentence_diff(prior_sentences: list[str], current_sentences: list[str]) -> SentenceDiff:
    """Line up the two years' sentences in order and list what changed.

    Sentences are compared by their words (textprep.words), so a sentence whose only change is
    a number or punctuation counts as kept. A sentence that moved counts as removed and added.
    autojunk=False: by default difflib ignores items that appear very often, which would make
    it skip common sentences in long documents.
    """
    prior_keys = [" ".join(words(s)) for s in prior_sentences]
    current_keys = [" ".join(words(s)) for s in current_sentences]
    matcher = difflib.SequenceMatcher(None, prior_keys, current_keys, autojunk=False)
    diff = SentenceDiff()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            diff.kept += i2 - i1
            continue
        diff.removed += prior_sentences[i1:i2]
        diff.added += current_sentences[j1:j2]
        diff.words_removed += sum(len(k.split()) for k in prior_keys[i1:i2])
        diff.words_added += sum(len(k.split()) for k in current_keys[j1:j2])
    return diff


def simple(diff: SentenceDiff, prior_words: int, current_words: int) -> float:
    """1 - (words in added and removed sentences) / (words in both documents)."""
    total = prior_words + current_words
    return 1.0 if total == 0 else 1 - (diff.words_added + diff.words_removed) / total


@dataclass
class Comparison:
    cosine: float
    jaccard: float
    min_edit: float
    simple: float
    prior_words: int
    current_words: int
    prior_sentences: int
    current_sentences: int
    diff: SentenceDiff


def compare(prior_text: str, current_text: str) -> Comparison:
    """All four measures for one pair of sections (scoring text, one paragraph per line)."""
    prior_sentences, current_sentences = split_sentences(prior_text), split_sentences(current_text)
    prior_words = [w for s in prior_sentences for w in words(s)]
    current_words = [w for s in current_sentences for w in words(s)]
    diff = sentence_diff(prior_sentences, current_sentences)
    return Comparison(
        cosine=cosine(prior_words, current_words),
        jaccard=jaccard(prior_words, current_words),
        min_edit=min_edit(prior_words, current_words),
        simple=simple(diff, len(prior_words), len(current_words)),
        prior_words=len(prior_words), current_words=len(current_words),
        prior_sentences=len(prior_sentences), current_sentences=len(current_sentences),
        diff=diff,
    )
