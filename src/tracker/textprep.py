"""Phase 3: turn a section's scoring text into sentences and words (D-028).

The scoring text from Phase 2 has one paragraph per line. In about 6% of sections the
10-K put each printed line in its own HTML element, so a sentence can be split across
lines (D-027). To make sure that can't change a score, line breaks are ignored here:
all lines are joined into one stream of text, and sentences are found from punctuation only.

  join_lines("...the risks and\\nuncertainties...")  ->  "...the risks and uncertainties..."
  split_sentences(text)   ->  ["Our success depends on X.", "We invest in Y.", ...]
  words(sentence)         ->  ["our", "success", "depends", "on", "x"]   (numbers become "#")
"""
from __future__ import annotations

import re

# A word ending in a period that usually doesn't end a sentence ("Inc. reported...").
# Compared in lower case, without the final period.
ABBREVIATIONS = {
    "inc", "corp", "co", "ltd", "llc", "plc", "no", "nos", "mr", "mrs", "ms", "dr", "jr", "sr", "st",
    "vs", "etc", "approx", "e.g", "i.e", "u.s", "u.k", "u.n", "n.a", "l.p", "s.a", "n.v", "a.g",
    "fig", "sec", "art", "dept", "gov", "govt", "jan", "feb", "mar", "apr", "jun", "jul", "aug",
    "sep", "sept", "oct", "nov", "dec",
}

# After an abbreviation, these words still start a new sentence: "...outside the U.S. We..."
# Each is a common sentence opener that never continues a name ("U.S. Government", "Mr. Smith").
SENTENCE_OPENERS = {
    "The", "We", "Our", "In", "As", "These", "This", "If", "For", "Any", "There", "It", "Its",
    "Such", "Additionally", "However", "Further", "Furthermore", "Moreover", "Also", "While",
    "Although", "Accordingly", "Because",
}

# A possible sentence end: . ! or ? (maybe followed by a closing quote or bracket), then a space,
# then a capital letter or digit (maybe after an opening quote or bracket).
POSSIBLE_END = re.compile(r"[.!?][\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9])")

# A word: letters, possibly joined by an apostrophe or hyphen ("company's", "third-party").
# A number: digits, possibly with , or . inside ("1,500", "2.5"). Every number becomes "#".
TOKEN = re.compile(r"[a-z]+(?:['-][a-z]+)*|\d+(?:[.,]\d+)*")
NUMBER_PLACEHOLDER = "#"


def join_lines(text: str) -> str:
    """Join the lines of a section into one string, so line breaks can't matter.

    A line that ends in a hyphen right after a letter, followed by a lower-case letter,
    is joined without a space ("third-\\nparty" -> "third-party"). In our data every such
    case is a real hyphenated word, so the hyphen is kept. All other line breaks become a space.
    """
    text = re.sub(r"(?<=[A-Za-z])-\n(?=[a-z])", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def _ends_sentence(text: str, period_at: int, next_word: str) -> bool:
    """Is the period at `period_at` a real sentence end? False after an abbreviation or an
    initial ("J. Smith"), unless the next word is a common sentence opener."""
    if text[period_at] != ".":
        return True  # ! and ? always end a sentence
    before = text[:period_at].rsplit(" ", 1)[-1].lstrip("\"'([").lower()
    is_abbreviation = before in ABBREVIATIONS or re.fullmatch(r"[a-z]", before) is not None
    return not is_abbreviation or next_word in SENTENCE_OPENERS


def split_sentences(text: str) -> list[str]:
    """Split a section into sentences, ignoring line breaks.

    A heading without a final period joins the sentence after it ("Risks Related to Our
    Business Our success depends on..."). That's a known, accepted cost of ignoring line
    breaks; it only affects the sentence-level measure, and it happens the same way every year.
    """
    text = join_lines(text)
    sentences, start = [], 0
    for match in POSSIBLE_END.finditer(text):
        next_word = re.match(r"[\"'(\[]?(\w+)", text[match.end():])
        if _ends_sentence(text, match.start(), next_word.group(1) if next_word else ""):
            sentences.append(text[start:match.end()].strip())
            start = match.end()
    if text[start:].strip():
        sentences.append(text[start:].strip())
    return sentences


def words(text: str) -> list[str]:
    """Lower-case words, with every number replaced by "#" so "fiscal 2024" -> "fiscal 2025"
    isn't counted as a change (D-028). Punctuation is dropped."""
    return [NUMBER_PLACEHOLDER if token[0].isdigit() else token for token in TOKEN.findall(text.lower())]
