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

# "Item 1A", "ITEM 1A.", "Item 1(A)", "Item 1 (B) -", "Item 1.A." (Clorox, Rollins),
# "Part I. Item 1A." (Expedia), "Item 7A", "Item 10" ...
# The period in "1.A" only counts when a letter follows right away, so "Item 1. A ..." stays Item 1.
ITEM_HEADER = re.compile(
    r"^(?:part\s+[ivx]{1,3}\s*[.,:\-–—]?\s*)?item\s*(\d{1,2})(?:\.(?=[a-d]\b))?\s*\(?\s*([a-d])?\s*\)?(?=$|[\s.:\-–—])",
    re.I)
PAGE_RANGE = re.compile(r"pages?\s+(\d{1,3})\s*(?:to|through|-|–|—)\s*(\d{1,3})", re.I)
# Only a LATER part ends a Part I item. ("Part I" itself is often a running page header.)
LATER_PART_HEADER = re.compile(r"^part\s+(ii|iii|iv|2|3|4)\b\W*$", re.I)
PAGE_NUMBER = re.compile(r"^(page\s*)?[\-–—]?\s*(\d{1,3}|[ivxlc]{1,7})\s*[\-–—]?$", re.I)
TABLE_OF_CONTENTS = re.compile(r"^(back to |return to )?(the )?table of contents\W*$", re.I)
REFERENCE_ONLY = re.compile(r"incorporated\s+(herein\s+)?by\s+reference|can be found|is included (in|under)|is contained in", re.I)
TRAILING_PAGES = re.compile(r"[\s.]*\d{1,3}(\s*[-–—]\s*\d{1,3})?(\s*,\s*\d{1,3}(\s*[-–—]\s*\d{1,3})?)*\s*$")
# The item number in front of a title, removed by title_of():
#   - with the word "Item": "Item 1A. ", "ITEM 1.A ", "Part I. Item 1A ", "Item 1A " (no separator needed)
#   - without it: "1A. ", "7 - " (a separator is needed), or "1A " (number plus letter)
# A bare number with no separator ("30 Risk Factors") is NOT removed here: in Honeywell's
# contents that number is a page number. LEADING_PAGE handles those rows (v1.2, D-027).
# The letter must stand alone ("1A", "1(A)", "1.A"), so the "B" of "Item 1. Business" stays.
LEADING_ITEM = re.compile(
    r"^(?:(?:part\s+[ivx]{1,3}\s*[.,:\-–—]?\s*)?item\s*\d{1,2}\.?\s*\(?\s*(?:[a-d]\b)?\s*\)?\s*[.:\-–—]?\s*"
    r"|\d{1,2}\.?\s*\(?\s*(?:[a-d]\b)?\s*\)?\s*[.:\-–—]\s*"
    r"|\d{1,2}[a-d]\s+)", re.I)
# A contents row with its page number first: "30 Risk Factors" (Honeywell 2025).
LEADING_PAGE = re.compile(r"^\d{1,3}\s+(?=[A-Za-z])")

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
    "quantitative and qualitative disclosure",  # also "...Disclosures about Market Risks" (Honeywell 2025)
)
# Not item titles, but sections that often follow Risk Factors. Whole-heading match only,
# so a risk factor that merely mentions executive officers can't end the section.
END_TITLES_OTHER = {
    "information about our executive officers", "information about executive officers",
    "executive officers of the registrant", "executive officers of the company",
}

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

    Two kinds of lines look like headers but aren't (v1.2, D-027):
      - a title in quotation marks after the item number is a cross-reference:
        'Part II, Item 7 “Management’s Discussion...”' (Colgate 2021, the second half
        of a sentence split by a page break)
      - with "Part I" in front, a title must follow: "Part I. Item 1A. Risk Factors"
        (Expedia) is a header, but the running page header "Part I Item 1A & 1B"
        (Entergy) is not
    """
    m = ITEM_HEADER.match(text)
    if m is None:
        return None
    key = int(m.group(1)), (m.group(2) or "").lower()
    after = text[m.end():]
    if re.match(r"^\s*[.,:\-–—]?\s*[“\"‘']", after):
        return None
    if text.lower().startswith("part") and not re.match(r"^\s*[.,:\-–—]?\s*[A-Z]", after):
        return None
    if len(text) <= 150:
        return key
    rest = after.lstrip(" .:-–—")
    first_words = rest.split()[:6]
    if first_words and sum(w[:1].isupper() for w in first_words) >= max(2, len(first_words) - 1):
        return key
    return None


def heading_match(block: Block, title: str) -> int | None:
    """Is this block the heading `title`? Returns where the section text starts inside the block.

    Matches a standalone heading ("Risk Factors", "Item 1A. Risk Factors", "RISK FACTORS 49"),
    a run-in heading in capitals ("RISK FACTORS. The following discussion...", GE), or a
    bold run-in heading ("**Risk Factors** An investment in the Company...", US Bancorp).
    Returns None if it isn't a match.
    """
    if title_of(block.text) == title:
        return len(block.text)  # the whole block is the heading
    upper = title.upper()
    m = re.match(r"^\s*" + re.escape(upper).replace(r"\ ", r"\s+") + r"\s*[.:—–-]\s+", block.text)
    if m:
        return m.end()
    if block.lead_bold and title_of(block.lead_bold) == title and block.text.startswith(block.lead_bold):
        return len(block.lead_bold)
    return None


def _is_end(title: str, extra_titles: set[str]) -> bool:
    return title in END_TITLES_EXACT or title in extra_titles or title.startswith(END_TITLES_PREFIX)


def is_end_title(block: Block, extra_titles: set[str]) -> bool:
    if re.match(r"^\s*[“\"‘']", block.text):
        # A title in quotation marks is a cross-reference, not a heading: Morgan Stanley 2025 has
        # a line starting “Quantitative and Qualitative Disclosures about Risk—Legal...” herein.
        return False
    whole = title_of(block.text)
    if _is_end(whole, extra_titles) or whole in END_TITLES_OTHER:
        return True
    # run-in end headings: in capitals ("LEGAL PROCEEDINGS. Refer to Note 24...") or in bold
    m = re.match(r"^([A-Z][A-Z ,&’'\-]{3,80})[.:—–]\s", block.text)
    if m and _is_end(simplify(m.group(1)), extra_titles):
        return True
    return bool(block.lead_bold) and _is_end(title_of(block.lead_bold), extra_titles)


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

def is_contents_row(block: Block) -> bool:
    """A table row with the page number first: "30 Risk Factors" (Honeywell 2025)."""
    return block.table_id is not None and bool(LEADING_PAGE.match(block.text))


def contents_title(block: Block) -> str:
    """The title in a contents line, with the page number removed from either end."""
    text = LEADING_PAGE.sub("", block.text) if is_contents_row(block) else block.text
    return title_of(text)


def titles_after_in_contents(blocks: list[Block], title: str) -> set[str]:
    """In each table of contents, the title listed right after `title`.

    Contents lines look like "Risk Factors 24", "Risk Factors" then "24", or, in
    Honeywell's 2025 10-K, "30 Risk Factors". The next line that isn't a page number is
    the next section, which is where ours ends.
    """
    found = set()
    for i, b in enumerate(blocks):
        if contents_title(b) != title:
            continue
        has_page = (bool(TRAILING_PAGES.search(b.text)) or is_contents_row(b)
                    or (i + 1 < len(blocks) and PAGE_NUMBER.match(blocks[i + 1].text)))
        if not has_page:
            continue
        for nxt in blocks[i + 1:i + 6]:
            if PAGE_NUMBER.match(nxt.text):
                continue
            t = contents_title(nxt)
            if t and t != title and 1 <= len(t.split()) <= 8:
                found.add(t)
            break
    return found


def find_end(blocks: list[Block], start: int, stop: int, next_titles: set[str], furniture: set[str],
             spec: SectionSpec = ITEM_1A) -> int:
    """The first block after `start` (and before `stop`) that begins another section.

    Running page headers never count: Eastman prints "MANAGEMENT'S DISCUSSION AND ANALYSIS..."
    at the top of every MD&A page, which would otherwise end its Risk Factors after one page.
    """
    for j in range(start + 1, stop):
        b = blocks[j]
        if masked(b.text) in furniture:
            continue
        if is_end_title(b, next_titles) or is_item_header(b.text) not in (None, spec.item):
            return j
    return stop


def names_item(text: str, item: tuple[int, str]) -> bool:
    """Does this line mention the item anywhere? "Part I Item 1A & 1B" names Item 1A."""
    number, letter = item
    letter_part = rf"\.?\s*\(?\s*{letter}\b" if letter else r"\b(?!\s*\(?\s*[a-d]\b)"
    return bool(re.search(rf"\bitem\s*{number}{letter_part}", text, re.I))


def cut_at_item_pages(blocks: list[Block], found: Found, furniture: set[str], spec: SectionSpec = ITEM_1A) -> bool:
    """Stop at the end of the last page whose running header names the item.

    Entergy's 2020 10-K has no "Item 1A" or "Item 1B" header, only "RISK FACTORS", and
    what follows is a subsidiary's "Management's Financial Discussion and Analysis",
    whose title is also a running header (so it can't end the section). But every
    risk-factor page is headed "Part I Item 1A & 1B". So the section ends at the first
    page break after the last page with that header. Needs 2+ copies of such a header
    inside the section. Only shortens a section, never lengthens one. Returns True if cut.
    """
    marked = [j for j in range(found.start + 1, found.end)
              if masked(blocks[j].text) in furniture and names_item(blocks[j].text, spec.item)]
    if len(marked) < 2:
        return False
    for j in range(marked[-1] + 1, found.end):
        if blocks[j].page_break_before or PAGE_NUMBER.match(blocks[j].text):
            found.end = j
            found.end_text = f"(end of the last page headed “{blocks[marked[-1]].text[:60]}”)"
            return True
    return False


def find_by_heading(blocks: list[Block], spec: SectionSpec = ITEM_1A, furniture: set[str] | None = None) -> Found | None:
    furniture = page_furniture(blocks) if furniture is None else furniture
    next_titles = titles_after_in_contents(blocks, spec.title)
    best: Found | None = None
    for i, b in enumerate(blocks):
        offset = heading_match(b, spec.title)
        if offset is None:
            continue
        if b.table_id is not None and (re.search(r"\d\s*$", b.text) or is_contents_row(b)):
            continue  # a contents line ("Risk Factors 56", "30 Risk Factors"), not the heading itself
        end = find_end(blocks, i, len(blocks), next_titles, furniture, spec)
        found = Found("heading", i, end, offset, b.text[:200],
                      blocks[end].text[:200] if end < len(blocks) else "(end of document)")
        cut_at_item_pages(blocks, found, furniture, spec)
        found.words = content_words(blocks, i, found.end, offset)
        if best is None or found.words > best.words:
            best = found
    if best is not None and next_titles:
        best.notes.append("contents lists next: " + "; ".join(sorted(next_titles))[:200])
    return best


# ---------------------------------------------------------------- method 3: headed parts

def find_by_heading_parts(blocks: list[Block], spec: SectionSpec = ITEM_1A,
                          furniture: set[str] | None = None) -> list[Found]:
    """Risk factors split into several headed parts, with no single "Risk Factors" heading.

    Synchrony's 10-K has "Risk Factors Summary", "Risk Factors Relating to Our Business"
    and, 40 pages later, "Risk Factors Relating to Regulation". Its own cross-reference
    index says Item 1A is exactly those pages. Each part is a bold or all-capitals heading
    of 10 words or fewer that starts with "Risk Factors ..." (contents rows don't count).
    Each part ends at the next contents entry after it, a standard section title, an item
    header, or the next part. Parts under 100 words are dropped. Only used when the
    other two methods find nothing.
    """
    furniture = page_furniture(blocks) if furniture is None else furniture
    prefix = spec.title + " "
    starts = [i for i, b in enumerate(blocks)
              if not b.data_table and (b.bold or b.text.isupper()) and len(b.text.split()) <= 10
              and title_of(b.text).startswith(prefix) and masked(b.text) not in furniture]
    parts = []
    for n, i in enumerate(starts):
        stop = starts[n + 1] if n + 1 < len(starts) else len(blocks)
        end = find_end(blocks, i, stop, titles_after_in_contents(blocks, title_of(blocks[i].text)), furniture, spec)
        found = Found("heading_parts", i, end, len(blocks[i].text), blocks[i].text[:200],
                      blocks[end].text[:200] if end < len(blocks) else "(end of document)")
        found.words = content_words(blocks, i + 1, end)
        if found.words >= 100:
            parts.append(found)
    return parts


def cut_at_page(blocks: list[Block], found: Found, last_page: int) -> bool:
    """Stop the section at the end of `last_page` (the page number printed at the bottom).

    Used when a 10-K says where Item 1A is ("...in the Annual Report on pages 140 to 155...").
    US Bancorp's risk factors are followed by a list of executives, which no heading rule
    would recognize as the next section. Returns True if the section was shortened.
    """
    for j in range(found.start + 1, found.end):
        text = blocks[j].text
        if PAGE_NUMBER.match(text) and text.strip(" -–—").lower().removeprefix("page").strip() == str(last_page):
            if j + 1 < found.end:
                found.end = j + 1
                found.end_text = f"(end of page {last_page}, as stated in the 10-K)"
                found.words = content_words(blocks, found.start, found.end, found.start_offset)
                return True
            return False
    return False


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
        if (PAGE_NUMBER.match(b.text) or TABLE_OF_CONTENTS.match(b.text) or masked(b.text) in furniture
                or not re.search(r"[A-Za-z0-9]", b.text)):  # decorative lines: "______", "* * *"
            removed += 1
        else:
            kept.append((i, b))
    while kept and kept[-1][0] in near and kept[-1][0] != found.start and is_leftover_label(kept[-1][1].text):
        kept.pop()
        removed += 1
    return [b for _, b in kept], removed


def is_leftover_label(text: str) -> bool:
    """A short label like "Parts I and II": 6 words or fewer, starts with a capital or digit,
    no sentence punctuation at the end. A sentence fragment ("increase for us in the future.")
    never qualifies, so text from documents that break paragraphs into lines is safe."""
    return len(text.split()) <= 6 and text[:1].isupper() and not re.search(r"[.!?,;:)”\"]$", text)


def reflow_lines(kept: list[Block]) -> tuple[list[Block], bool]:
    """Rejoin paragraphs in documents that put each printed line in its own HTML element.

    ConocoPhillips's 10-K arrives as "You should carefully" / "consider the following risk
    factors" / ... Only applied when the section's lines are short (median under 80
    characters); normal 10-Ks have paragraphs of several hundred characters. A line joins
    the one before it when the one before doesn't end a sentence, both have the same
    bold-ness (so headings stay separate), neither is a table row, and the line isn't a new bullet.
    Returns the blocks and whether anything was rejoined.
    """
    prose = [len(b.text) for b in kept if not b.data_table]
    if not prose or sorted(prose)[len(prose) // 2] >= 80:
        return kept, False
    out: list[Block] = []
    for b in kept:
        prev = out[-1] if out else None
        if (prev is not None and not prev.data_table and not b.data_table and prev.bold == b.bold
                and not re.search(r"[.!?:;”\"]$", prev.text) and not re.match(r"^[•●○■□◦▪▫➢➤►✓·]", b.text)):
            out[-1] = Block(prev.text + " " + b.text, prev.bold, prev.italic, prev.table_id, prev.data_table)
        else:
            out.append(b)
    return out, True


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
        elif simplify(b.text) in END_TITLES_EXACT - {"cybersecurity"} and b.text[:1].isupper():
            # A heading starts with a capital: "Properties". A lowercase "properties." is
            # just the last word of a list item (ConocoPhillips), not a header.
            hits.append(b.text[:80])
    return hits
