"""HTML -> text blocks, on small made-up examples of each tricky pattern seen in real 10-Ks."""
import unittest

import helpers  # noqa: F401
from tracker.html_text import html_to_blocks, normalize


def texts(html: str) -> list[str]:
    return [b.text for b in html_to_blocks(html.encode())]


class JoiningText(unittest.TestCase):
    def test_header_split_across_spans_becomes_one_line(self):
        # Dominion's 10-K: <span>Item 1A. Ris</span><span>k Factors</span>
        self.assertEqual(texts("<div><span>Item 1A. Ris</span><span>k Factors</span></div><p>Body.</p>"),
                         ["Item 1A. Risk Factors", "Body."])

    def test_header_split_into_tiny_pieces(self):
        # Bank of America's contents: "Item 1" + "C" + "." in separate tags
        self.assertEqual(texts("<p><a>Item 1</a><span>C</span><span>.</span> Cybersecurity</p>"), ["Item 1C. Cybersecurity"])

    def test_table_row_is_one_line_with_cells_separated(self):
        blocks = html_to_blocks(b"<table><tr><td>Item 1A.</td><td><p>Risk Factors</p></td><td>12</td></tr></table>")
        self.assertEqual([b.text for b in blocks], ["Item 1A. Risk Factors 12"])
        self.assertTrue(blocks[0].data_table)

    def test_br_starts_a_new_line_outside_tables(self):
        self.assertEqual(texts("<p>First line<br>Second line</p>"), ["First line", "Second line"])

    def test_special_spaces_and_invisible_characters(self):
        self.assertEqual(normalize("Item 1A.​  Risk\tFactors"), "Item 1A. Risk Factors")


class PlainText(unittest.TestCase):
    def test_plain_text_filing_splits_on_blank_lines(self):
        self.assertEqual(texts("ITEM 1A. RISK FACTORS\n\nWe face   risks.\n \nITEM 1B."), ["ITEM 1A. RISK FACTORS", "We face risks.", "ITEM 1B."])


class HiddenContent(unittest.TestCase):
    def test_hidden_and_xbrl_header_removed(self):
        html = ("<body><div style='display: none'><ix:header>0000320193 false FY</ix:header></div>"
                "<table><tr><td style='display:none'>x</td><td>Visible text</td></tr></table></body>")
        self.assertEqual(texts(html), ["Visible text"])


class Formatting(unittest.TestCase):
    def test_bold_by_tag_or_style(self):
        blocks = html_to_blocks(b"<p><b>Heading</b></p><p style='font-weight:700'>Also</p><p>Plain <b>word</b> text here</p>")
        self.assertEqual([b.bold for b in blocks], [True, True, False])

    def test_page_breaks_are_remembered(self):
        html = "<p>Page one</p><div style='page-break-after: always'></div><p>Page two</p><hr><p>Page three</p>"
        blocks = html_to_blocks(html.encode())
        self.assertEqual([(b.text, b.page_break_before) for b in blocks],
                         [("Page one", False), ("Page two", True), ("Page three", True)])


class Tables(unittest.TestCase):
    def test_layout_table_with_bullets_is_text(self):
        row = "<tr><td>•</td><td>We may not be able to compete successfully with larger companies that have more money.</td></tr>"
        blocks = html_to_blocks(f"<table>{row * 3}</table>".encode())
        self.assertFalse(any(b.data_table for b in blocks))

    def test_financial_table_is_data(self):
        rows = "".join(f"<tr><td>Revenue {y}</td><td>{y * 3:,}</td><td>{y * 2:,}</td></tr>" for y in (2023, 2024, 2025))
        blocks = html_to_blocks(f"<table>{rows}</table>".encode())
        self.assertTrue(all(b.data_table for b in blocks))


if __name__ == "__main__":
    unittest.main()
