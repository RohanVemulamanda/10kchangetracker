"""Phase 3: find and remove the risk factor summary at the start of Item 1A (D-029).

Since 2020 the SEC asks for a short summary of the risk factors when they run over 15 pages.
Many companies put it at the top of Item 1A. It repeats the risk headings in shorter form,
so it would count that text twice, and the year it first appears looks like a big change.

What a summary looks like (Micron FY2025, simplified):

    Risk Factor Summary                                       <- start: a short "summary" heading
    Risks Related to Our Business, Operations, and Industry
    volatility in average selling prices of our products;
    ...
    Risks Related to Our Business, Operations, and Industry   <- end: the full section begins
    Volatility in average selling prices ... may adversely affect our business.

The start is a short heading (8 words or fewer) with "summary" and "risk" in it, within the
first 1,500 words. The end is the first of these, scanning down from the start:
  "repeat"       a line that repeats one of the summary's first 3 lines, or its first category
                 heading: the full section starts over where the summary started (Micron and
                 Crown Castle repeat their first category heading, Gallagher its first risk).
                 Lines are compared ignoring case, punctuation and plural endings ("Risk
                 relating to..." in Match's summary, "Risks relating to..." below it). Only these
                 lines count, because some summaries repeat a closing sentence after each group
                 (Alexandria).
  "refers_back"  "For a more complete discussion..." or "The risks summarized above...":
                 the last line of the summary (Qorvo).
  "intro"        "You should carefully consider...": the usual introduction to the full
                 section (GE HealthCare).
  "heading"      a bare "Risk Factors" heading: the full section's own title (M&T, AIG).
  "category"     a "Risks related to..." or "... Risks" heading that never appears again,
                 after at least 3 summary lines, in a summary that had no category headings of
                 its own (Autodesk). A list item ending in ; , or : is not a heading (Booking).
A summary is a list of short items, so a long paragraph (over 100 words) just before the end
is the full section's own introduction and is kept (Vistra: "Please carefully consider...").

If no end is found within 2,500 words, nothing is removed and the filing is listed for review.
Removed text that still contains a long paragraph is listed for review too (`long_line`): the
full section may have started earlier, with a reworded first heading (Gallagher 2023).
A heading with fewer than 3 lines under it is not treated as a summary (Williams has a bare
"Summary of Risk Factors" heading followed directly by the full section).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_WORDS_BEFORE_START = 1_500
MAX_SUMMARY_WORDS = 2_500   # the SEC asks for 2 pages at most; this leaves room
MIN_SUMMARY_LINES = 3
LONG_PARAGRAPH_WORDS = 100  # summary items are shorter than this

REFERS_BACK = re.compile(r"(for a more (complete|detailed)|the (risk|risk factor) (summarized|described|listed) above"
                         r"|the (above|foregoing) (summary|list))")
INTRO = re.compile(r"(you|investor|reader) should (carefully )?(consider|read|review)")
CATEGORY_HEADING = re.compile(
    r"^(risks? (related|relating|associated|specific|pertaining|regarding|concerning|arising) |.{0,80}\brisks\.?$)",
    re.IGNORECASE)


@dataclass
class Summary:
    start: int          # first line of the summary (its heading)
    end: int | None     # first line after it; None if no end was found (nothing removed)
    rule: str           # which rule found the end: repeat, refers_back, intro, heading, category, too_long
    long_line: bool = False  # the removed text has a long paragraph after its first 3 lines: check it


def comparable(line: str) -> str:
    """Lower case, letters and spaces only, plural "s" dropped from each word."""
    return " ".join(re.sub(r"s$", "", w) for w in re.sub(r"[^a-z ]", " ", line.lower()).split())


def is_category_heading(line: str) -> bool:
    """A category heading ("Risks Related to Our Business"); not a list item ending in ; , or :"""
    stripped = line.strip()
    if stripped.endswith((":", ";", ",")):
        return False
    return len(stripped.split()) <= 15 and CATEGORY_HEADING.match(stripped) is not None


def find_summary(lines: list[str]) -> Summary | None:
    """Find the risk factor summary in a section's lines. None if there isn't one."""
    start, words_before = None, 0
    for i, line in enumerate(lines):
        if len(line.split()) <= 8 and re.search("summary", line, re.I) and re.search("risk", line, re.I):
            start = i
            break
        words_before += len(line.split())
        if words_before > MAX_WORDS_BEFORE_START:
            return None
    if start is None:
        return None

    keys = [comparable(line) for line in lines]
    # Where the full section would start over: the summary's first 3 lines and its first category heading
    restart_points = {key for key in keys[start + 1:start + 1 + MIN_SUMMARY_LINES] if len(key.split()) >= 2}
    had_category = False
    summary_words = 0
    for j in range(start + 1, len(lines)):
        line, key = lines[j], keys[j]
        if j > start + MIN_SUMMARY_LINES and key in restart_points:
            return _checked(lines, start, j, "repeat")
        if REFERS_BACK.match(key):
            return _checked(lines, start, j + 1, "refers_back")
        if INTRO.match(key):
            return _checked(lines, start, j, "intro")
        if key == "risk factor" and j - start - 1 >= MIN_SUMMARY_LINES:
            return _checked(lines, start, j, "heading")
        if is_category_heading(line):
            lines_so_far = j - start - 1
            repeated_later = key in keys[j + 1:]
            if lines_so_far >= MIN_SUMMARY_LINES and not had_category and not repeated_later:
                return _checked(lines, start, j, "category")
            if not had_category:
                restart_points.add(key)
            had_category = True
        summary_words += len(line.split())
        if summary_words > MAX_SUMMARY_WORDS:
            break
    return Summary(start, None, "too_long")


def _checked(lines: list[str], start: int, end: int, rule: str) -> Summary | None:
    """Keep a long paragraph just before the end (the full section's introduction). Then
    check what's left: at least 3 lines under the heading, or it's just a heading."""
    if rule != "refers_back" and len(lines[end - 1].split()) > LONG_PARAGRAPH_WORDS and end - 1 > start + MIN_SUMMARY_LINES:
        end -= 1
    if end - start - 1 < MIN_SUMMARY_LINES:
        return None
    long_line = any(len(line.split()) > LONG_PARAGRAPH_WORDS for line in lines[start + 1 + MIN_SUMMARY_LINES:end])
    return Summary(start, end, rule, long_line)


def remove_summary(text: str, end_override: str | None = None) -> tuple[str, Summary | None]:
    """Return the section text without its summary, and what was found.
    If a summary heading was found but not its end, the text is returned unchanged.

    end_override: the start of the first line after the summary, checked by hand, for a filing
    the rules get wrong (data/reference/summary_overrides.csv). It must be found, or it's an error.
    """
    lines = text.split("\n")
    found = find_summary(lines)
    if end_override is not None:
        start = found.start if found else -1
        end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith(end_override)), None)
        if found is None or end is None:
            raise ValueError(f"summary override not found: {end_override!r}")
        found = Summary(found.start, end, "override")
    if found is None or found.end is None:
        return text, found
    return "\n".join(lines[:found.start] + lines[found.end:]), found
