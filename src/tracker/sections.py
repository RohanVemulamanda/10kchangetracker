"""Find a 10-K section (Item 1A, Risk Factors) in a list of text blocks, and clean it.

Two ways to find it, tried in order (DECISIONS.md D-020):

1. "item": the standard layout. Find every block that starts with "Item 1A"
   (written "ITEM 1A.", "Item 1A:", "Item 1(A)", "Item 1 (A) -", ...). For each one,
   the section runs until the next item header with a later number (1B, 1C, 2, ...).
   The table of contents also has "Item 1A", but there the next item comes one line
   later. So we keep the candidate with the most words.

2. "heading": for 10-Ks laid out like an annual report (GE, Citigroup, the
   annual-report exhibit of Wells Fargo). Find blocks that ARE the heading
   "Risk Factors", or start with it in capitals ("RISK FACTORS. The following...").
   The section ends at the next heading that comes after "Risk Factors" in the
   document's own table of contents, or at a standard 10-K section title
   ("Legal Proceedings", "Controls and Procedures", ...), whichever comes first.

Each result records which method found it, so results can later be re-run
without the fallback cases.
"""
from __future__ import annotations

import re

from dataclasses import dataclass, field

from .html_text import Block

# "Item 1A", "ITEM 1A.", "Item 1(A)", "Item 1 (B) -", "Item 7A", "Item 10" ...
ITEM_HEADER = re.compile(r"^item\s*(\d{1,2})\s*\(?\s*([a-d])?\s*\)?(?=$|[\s.:\-–—])", re.I)
# Only a LATER part ends a Part I item. ("Part I" itself is often a running page header.)
LATER_PART_HEADER = re.compile(r"^part\s+(ii|iii|iv|2|3|4)\b\W*$", re.I)
PAGE_NUMBER = re.compile(r"^(page\s*)?[\-–—]?\s*(\d{1,3}|[ivxlc]{1,7})\s*[\-–—]?$", re.I)
TABLE_OF_CONTENTS = re.compile(r"^(back to |return to )?(the )?table of contents\W*$", re.I)
REFERENCE_ONLY = re.compile(r"incorporated\s+(herein\s+)?by\s+reference|can be found|is included (in|under)|is contained in", re.I)
TRAILING_PAGES = re.compile(r"[\s.]*\d{1,3}(\s*[-–—]\s*\d{1,3})?(\s*,\s*\d{1,3}(\s*[-–—]\s*\d{1,3})?)*\s*$")
LEADING_ITEM = re.compile(r"^(item\s*)?\d{1,2}\s*\(?\s*[a-d]?\s*\)?\s*[.:\-–—]\s*", re.I)

# Standard 10-K section titles that can end a "heading"-method section. Compared after
# lower-casing and removing punctuation. "prefix" titles also match longer versions.
END_TITLES_EXACT = {
    "unresolved staff comments", "cybersecurity", "properties", "legal proceedings",
    "mine safety disclosures", "selected financial data", "controls and procedures",
    "quantitative and qualitative disclosures about market risk",
    "financial statements and supplementary data",
}
END_TITLES_PREFIX = (
    "market for registrants common equity", "managements discussion and analysis",
    "report of independent registered public accounting firm",
    "changes in and disagreements with accountants",
)

MIN_SECTION_WORDS = 300  # anything shorter is a table-of-contents entry or a cross-reference


@dataclass
class SectionSpec:
    name: str                 # e.g. "item_1a"
    item: tuple[int, str]     # e.g. (1, "a")
    title: str                # e.g. "risk factors"


ITEM_1A = SectionSpec("item_1a", (1, "a"), "risk factors")


@dataclass
class Found:
    method: str               # "item" or "heading"
    start: int                # index of the header block
    end: int                  # index of the block that ends the section (not included)
    start_offset: int = 0     # for run-in headings: where the text starts inside the header block
    header_text: str = ""
    end_text: str = ""
    words: int = 0
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- small helpers

def simplify(text: str) -> str:
    """Lower-case, drop punctuation, collapse spaces: "Management’s Discussion." -> "managements discussion"."""
    text = text.lower().replace("’", "").replace("'", "")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def title_of(text: str) -> str:
    """The title in a heading or contents line: drop "Item 1A." in front and page numbers behind."""
    text = LEADING_ITEM.sub("", text.strip())
    text = TRAILING_PAGES.sub("", text)
    return simplify(text)


def item_key(block_text: str) -> tuple[int, str] | None:
    m = ITEM_HEADER.match(block_text)
    if not m:
        return None
    return int(m.group(1)), (m.group(2) or "").lower()


def is_item_header(text: str) -> tuple[int, str] | None:
    """The item number if this block is an item header.

    Short blocks starting with "Item ..." count. A long block counts only if the
    title follows right away ("Item 1A. Risk Factors. The following..."), so a
    paragraph that merely starts by mentioning an item doesn't.
    """
    key = item_key(text)
    if key is None:
        return None
    if len(text) <= 150:
        return key
    rest = ITEM_HEADER.sub("", text, count=1).lstrip(" .:-–—")
    first_words = rest.split()[:6]
    if first_words and sum(w[:1].isupper() for w in first_words) >= max(2, len(first_words) - 1):
        return key
    return None


def heading_match(block: Block, title: str) -> int | None:
    """Is this block the heading `title`? Returns where the section text starts inside the block.

    Matches a standalone heading ("Risk Factors", "Item 1A. Risk Factors", "RISK FACTORS 49"),
    or a run-in heading in capitals ("RISK FACTORS. The following discussion...").
    Returns None if it isn't a match.
    """
    if title_of(block.text) == title:
        return len(block.text)  # the whole block is the heading
    upper = title.upper()
    m = re.match(r"^\s*" + re.escape(upper).replace(r"\ ", r"\s+") + r"\s*[.:—–-]\s+", block.text)
    if m:
        return m.end()
    return None


def is_end_title(block: Block, extra_titles: set[str]) -> bool:
    t = title_of(block.text)
    if t in END_TITLES_EXACT or t in extra_titles or t.startswith(END_TITLES_PREFIX):
        return True
    # run-in end headings in capitals, e.g. "LEGAL PROCEEDINGS. Refer to Note 24..."
    m = re.match(r"^([A-Z][A-Z ,&’'\-]{3,80})[.:—–]\s", block.text)
    if m:
        t = simplify(m.group(1))
        return t in END_TITLES_EXACT or t in extra_titles or t.startswith(END_TITLES_PREFIX)
    return False


def content_words(blocks: list[Block], start: int, end: int, start_offset: int = 0) -> int:
    words = 0
    for i in range(start, end):
        b = blocks[i]
        if b.data_table:
            continue
        text = b.text[start_offset:] if i == start else b.text
        words += len(text.split())
    return words


# ---------------------------------------------------------------- method 1: item headers

def find_by_item(blocks: list[Block], spec: SectionSpec = ITEM_1A) -> Found | None:
    headers = [(i, is_item_header(b.text)) for i, b in enumerate(blocks)]
    headers = [(i, k) for i, k in headers if k is not None]
    best: Found | None = None
    for n, (i, key) in enumerate(headers):
        if key != spec.item:
            continue
        end = len(blocks)
        for j, later_key in headers[n + 1:]:
            if later_key > spec.item:
                end = j
                break
        if spec.item[0] <= 4:  # Part I items (1-4) also end at "PART II"
            for j in range(i + 1, end):
                if LATER_PART_HEADER.match(blocks[j].text):
                    end = j
                    break
        found = Found("item", i, end, len(blocks[i].text), blocks[i].text[:200],
                      blocks[end].text[:200] if end < len(blocks) else "(end of document)")
        found.words = content_words(blocks, i + 1, end)
        if best is None or found.words > best.words:
            best = found
    return best


def is_reference_only(blocks: list[Block], found: Found) -> bool:
    """A short Item 1A that only points elsewhere ("...can be found in the Annual Report...")."""
    if found.words >= MIN_SECTION_WORDS:
        return False
    text = " ".join(b.text for b in blocks[found.start + 1:found.end])
    return bool(REFERENCE_ONLY.search(text))


# ---------------------------------------------------------------- method 2: "Risk Factors" heading

def titles_after_in_contents(blocks: list[Block], title: str) -> set[str]:
    """In each table of contents, the title listed right after `title`.

    Contents lines look like "Risk Factors 24" (or "Risk Factors" then "24"). The next
    line that isn't a page number is the next section, which is where ours ends.
    """
    found = set()
    for i, b in enumerate(blocks):
        if title_of(b.text) != title:
            continue
        has_page = bool(TRAILING_PAGES.search(b.text)) or (i + 1 < len(blocks) and PAGE_NUMBER.match(blocks[i + 1].text))
        if not has_page:
            continue
        for nxt in blocks[i + 1:i + 6]:
            if PAGE_NUMBER.match(nxt.text):
                continue
            t = title_of(nxt.text)
            if t and t != title and 1 <= len(t.split()) <= 8:
                found.add(t)
            break
    return found


def find_by_heading(blocks: list[Block], spec: SectionSpec = ITEM_1A) -> Found | None:
    next_titles = titles_after_in_contents(blocks, spec.title)
    best: Found | None = None
    for i, b in enumerate(blocks):
        offset = heading_match(b, spec.title)
        if offset is None:
            continue
        end = len(blocks)
        for j in range(i + 1, len(blocks)):
            if is_end_title(blocks[j], next_titles) or is_item_header(blocks[j].text) not in (None, spec.item):
                end = j
                break
        found = Found("heading", i, end, offset, b.text[:200],
                      blocks[end].text[:200] if end < len(blocks) else "(end of document)")
        found.words = content_words(blocks, i, end, offset)
        if best is None or found.words > best.words:
            best = found
    if best is not None and next_titles:
        best.notes.append("contents lists next: " + "; ".join(sorted(next_titles))[:200])
    return best


# ---------------------------------------------------------------- cleaning

def masked(text: str) -> str:
    """Hide digits so "Wells Fargo 63" and "Wells Fargo 64" count as the same page footer."""
    return re.sub(r"\d", "#", text.lower())


def page_boundaries(blocks: list[Block]) -> set[int]:
    """Positions within 2 blocks of a page break or a page number."""
    near = set()
    for i, b in enumerate(blocks):
        if b.page_break_before or PAGE_NUMBER.match(b.text):
            near.update(range(i - 2, i + 3))
    return near


def page_furniture(blocks: list[Block]) -> set[str]:
    """Running page headers and footers in this document ("Wells Fargo & Company 63").

    A short line (100 characters or fewer, digits ignored) counts as page furniture if:
      - it appears 3+ times and at least 90% of its copies sit next to a page break
        or page number. Tested on the sample filings: every real header and footer
        met this (e.g. 244 of 244 copies), while repeated real content didn't (a
        bullet repeated 7 times sat at a page boundary once); or
      - it is outside any table, contains a page number that changes from copy to
        copy, and appears 5+ times ("Apple Inc. | 2025 Form 10-K | 12"), which
        catches footers in documents without page-break markers.
    """
    near = page_boundaries(blocks)
    positions: dict[str, list[int]] = {}
    texts: dict[str, set[str]] = {}
    for i, b in enumerate(blocks):
        if len(b.text) <= 100:
            key = masked(b.text)
            positions.setdefault(key, []).append(i)
            texts.setdefault(key, set()).add(b.text)
    furniture = set()
    for key, idx in positions.items():
        share_near = sum(i in near for i in idx) / len(idx)
        if len(idx) >= 3 and share_near >= 0.9:
            furniture.add(key)
        elif ("#" in key and len(idx) >= 5 and len(texts[key]) >= 0.8 * len(idx)
              and all(blocks[i].table_id is None for i in idx)):
            furniture.add(key)
    return furniture


def section_blocks(blocks: list[Block], found: Found, furniture: set[str] | None = None) -> tuple[list[Block], int]:
    """The blocks of the section, with page numbers, page headers and footers removed.

    Removed:
      - page numbers ("23", "- 23 -", "Page 23", "xii") and "Table of Contents" links
      - running page headers and footers (see page_furniture)
      - short leftover lines (6 words or fewer) at the very end of the section that sit
        at a page boundary, e.g. "Parts I and II" just before "Item 1B"
    Returns the kept blocks and how many were removed.
    """
    if furniture is None:
        furniture = page_furniture(blocks)
    near = page_boundaries(blocks)
    first = blocks[found.start]
    lead_text = first.text[found.start_offset:].strip(" .:—–-")

    kept: list[tuple[int, Block]] = []
    if lead_text:
        kept.append((found.start, Block(lead_text, first.bold, first.italic, first.table_id, first.data_table)))
    removed = 0
    for i in range(found.start + 1, found.end):
        b = blocks[i]
        if PAGE_NUMBER.match(b.text) or TABLE_OF_CONTENTS.match(b.text) or masked(b.text) in furniture:
            removed += 1
        else:
            kept.append((i, b))
    while kept and kept[-1][0] in near and len(kept[-1][1].text.split()) <= 6 and kept[-1][0] != found.start:
        kept.pop()
        removed += 1
    return [b for _, b in kept], removed


SCORING_REPLACEMENTS = [
    (re.compile(r"[“”″]"), '"'), (re.compile(r"[‘’′]"), "'"),
    (re.compile(r"[–—―]"), "-"), (re.compile(r"…"), "..."),
    (re.compile(r"^[•●○■□◦▪▫➢➤►✓\-–*·]+\s*"), ""),  # bullet characters at the start of a paragraph
]


def scoring_text(kept: list[Block]) -> str:
    """The version used for change scores: prose only (no data tables), plain punctuation.

    Lower-casing and splitting into words are left to Phase 3, where those choices belong.
    """
    lines = []
    for b in kept:
        if b.data_table:
            continue
        text = b.text
        for pattern, replacement in SCORING_REPLACEMENTS:
            text = pattern.sub(replacement, text)
        text = text.strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def overrun_hits(kept: list[Block], spec: SectionSpec = ITEM_1A) -> list[str]:
    """Signs we grabbed too much: a later item's header, or a standard section title, inside the text."""
    hits = []
    for b in kept:
        key = is_item_header(b.text)
        if key is not None and key > spec.item and not b.data_table:
            hits.append(b.text[:80])
        elif simplify(b.text) in END_TITLES_EXACT - {"cybersecurity"}:
            hits.append(b.text[:80])
    return hits
