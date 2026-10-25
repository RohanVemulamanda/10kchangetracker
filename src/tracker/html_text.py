"""Turn a filing's HTML into a list of text blocks: one per paragraph or table row.

Why not just call get_text()? In real 10-Ks, one paragraph is often split across
many HTML tags for formatting, e.g. <span>Item 1A. Ris</span><span>k Factors</span>.
Splitting at every tag would break words apart and hide headers. So we only start
a new block at *block-level* tags (paragraphs, divs, list items, table rows) and
join everything inside a block, the way a browser displays it.

Also done here:
  - remove hidden content (display:none), which in 10-Ks is XBRL tagging data
    and empty spacer cells, never readable text
  - remember whether each block is bold or italic (risk-factor headings usually are)
  - remember page breaks, so page headers and footers can be found later
  - mark which table each row came from, and whether that table holds data
    (numbers) or is just used for layout (e.g. bullet points)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import lxml.html

# Tags that start a new paragraph. Everything else (span, font, a, b, ...) is inline.
BLOCK_TAGS = {
    "p", "div", "li", "ul", "ol", "dl", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6",
    "center", "blockquote", "pre", "section", "article", "header", "footer", "main",
    "body", "html", "caption", "address", "figure", "figcaption",
}
SKIP_TAGS = {"script", "style", "head", "title", "meta", "link", "noscript", "ix:header"}

BOLD_STYLE = re.compile(r"font-weight:(bold|bolder|[6-9]00)")
SPACE_CHARS = re.compile(r"[  -   　\t\r\n\f\v]")
INVISIBLE_CHARS = re.compile(r"[​‌‍⁠﻿­]")
MULTI_SPACE = re.compile(r" {2,}")


@dataclass
class Block:
    text: str
    bold: bool = False                 # 80%+ of the characters are bold (often a heading)
    italic: bool = False
    table_id: int | None = None        # which table the row came from (None = not in a table)
    data_table: bool = False           # that table mostly holds numbers or short labels
    page_break_before: bool = False    # a page break came just before this block


def normalize(text: str) -> str:
    """Make all kinds of spaces plain spaces, drop invisible characters, collapse runs."""
    text = INVISIBLE_CHARS.sub("", text)
    text = SPACE_CHARS.sub(" ", text)
    return MULTI_SPACE.sub(" ", text).strip()


class _BlockBuilder:
    def __init__(self):
        self.blocks: list[Block] = []
        self.pieces: list[tuple[str, bool, bool]] = []  # (text, bold, italic) of the block in progress
        self.page_break_pending = False
        self.table_stack: list[int] = []
        self.row_depth = 0
        self.tables_seen = 0

    # -- collecting text ------------------------------------------------------
    def add(self, text: str, bold: bool = False, italic: bool = False) -> None:
        if text:
            self.pieces.append((text, bold, italic))

    def flush(self) -> None:
        """Finish the block in progress (if it has any text)."""
        if not self.pieces:
            return
        text = normalize("".join(p[0] for p in self.pieces))
        if text:
            letters = [(len(p[0].strip()), p[1], p[2]) for p in self.pieces]
            total = sum(n for n, _, _ in letters) or 1
            bold_share = sum(n for n, b, _ in letters if b) / total
            italic_share = sum(n for n, _, i in letters if i) / total
            self.blocks.append(Block(
                text=text,
                bold=bold_share >= 0.8,
                italic=italic_share >= 0.8,
                table_id=self.table_stack[-1] if self.table_stack else None,
                page_break_before=self.page_break_pending,
            ))
            self.page_break_pending = False
        self.pieces = []

    def page_break(self) -> None:
        self.flush()
        self.page_break_pending = True

    # -- walking the HTML tree ------------------------------------------------
    def walk(self, el, bold: bool = False, italic: bool = False) -> None:
        if not isinstance(el.tag, str):  # comments and processing instructions
            return
        tag = el.tag.lower()
        style = (el.get("style") or "").lower().replace(" ", "")
        if tag in SKIP_TAGS or "display:none" in style:
            return

        bold = bold or tag in ("b", "strong") or bool(BOLD_STYLE.search(style))
        italic = italic or tag in ("i", "em") or "font-style:italic" in style
        in_row = self.row_depth > 0
        is_block = tag in BLOCK_TAGS and not in_row  # inside a table row, everything joins into one line

        if "page-break-before:always" in style or "break-before:page" in style:
            self.page_break()
        if tag == "table":
            self.flush()
            self.tables_seen += 1
            self.table_stack.append(self.tables_seen)
        elif tag == "tr":
            self.flush()
            self.row_depth += 1
        elif tag in ("td", "th"):
            self.add(" ")  # keep cells apart: "Item 1A." + "Risk Factors"
        elif tag == "br":
            self.add(" ") if in_row else self.flush()
        elif tag == "hr":
            self.page_break()
        elif is_block:
            self.flush()

        self.add(el.text or "", bold, italic)
        for child in el:
            self.walk(child, bold, italic)
            self.add(child.tail or "", bold, italic)  # text after the child belongs to this element

        if tag == "table":
            self.flush()
            self.table_stack.pop()
        elif tag == "tr":
            self.flush()
            self.row_depth -= 1
        elif is_block:
            self.flush()
        if "page-break-after:always" in style or "break-after:page" in style:
            self.page_break()


def mark_data_tables(blocks: list[Block]) -> None:
    """Decide, table by table, whether a table holds data or is only used for layout.

    Layout tables (bullet lists, two-column text) have long rows of words; we keep
    them as text. Data tables (financial figures, tables of contents, header rows
    like "ITEM 1A. | RISK FACTORS") have short rows or lots of digits.
    Rule: a table is text if its rows average 8+ words and under 15% of its
    letters-and-digits are digits.
    """
    rows_by_table: dict[int, list[Block]] = {}
    for b in blocks:
        if b.table_id is not None:
            rows_by_table.setdefault(b.table_id, []).append(b)
    for rows in rows_by_table.values():
        text = " ".join(r.text for r in rows)
        alnum = [c for c in text if c.isalnum()]
        digit_share = sum(c.isdigit() for c in alnum) / max(len(alnum), 1)
        words_per_row = len(text.split()) / len(rows)
        is_data = words_per_row < 8 or digit_share >= 0.15
        for r in rows:
            r.data_table = is_data


def html_to_blocks(raw: bytes) -> list[Block]:
    """The whole conversion: HTML bytes in, list of blocks out."""
    if b"<" not in raw[:5000]:  # a plain-text filing: each blank-line-separated paragraph is a block
        paragraphs = re.split(r"\n\s*\n", raw.decode("utf-8", "replace"))
        return [Block(normalize(p)) for p in paragraphs if normalize(p)]
    root = lxml.html.fromstring(raw)
    builder = _BlockBuilder()
    builder.walk(root)
    builder.flush()
    mark_data_tables(builder.blocks)
    return builder.blocks
