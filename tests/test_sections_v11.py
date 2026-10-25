"""Version 1.1 fixes, each found in the full run (D-026). One test per real case."""
import unittest

import helpers  # noqa: F401
from tracker.html_text import Block, html_to_blocks
from tracker.sections import (cut_at_page, find_by_heading, find_by_heading_parts, find_by_item, is_item_header,
                              is_leftover_label, reflow_lines, section_blocks)

RISK_TEXT = " ".join(["Our business could be harmed by competition and changing market conditions."] * 40)


def doc(*items):
    return [Block(i[0], **i[1]) if isinstance(i, tuple) else Block(i) for i in items]


class HeaderFormats(unittest.TestCase):
    def test_period_between_number_and_letter(self):  # Clorox, Rollins
        self.assertEqual(is_item_header("ITEM 1.A. RISK FACTORS"), (1, "a"))
        self.assertEqual(is_item_header("Item 1.B. Unresolved Staff Comments"), (1, "b"))
        self.assertEqual(is_item_header("Item 1. Business"), (1, ""))
        self.assertEqual(is_item_header("Item 1. A Description of Our Business"), (1, ""))

    def test_part_number_in_front(self):  # Expedia
        self.assertEqual(is_item_header("Part I. Item 1A. Risk Factors"), (1, "a"))
        self.assertEqual(is_item_header("Part I. Item 1B. Unresolved Staff Comments"), (1, "b"))


class Headings(unittest.TestCase):
    def test_bold_run_in_heading(self):  # US Bancorp
        blocks = html_to_blocks(("<p><b>Risk Factors</b> An investment in the Company involves risk. " + RISK_TEXT +
                                 "</p><p>Controls and Procedures</p>").encode())
        found = find_by_heading(blocks)
        kept, _ = section_blocks(blocks, found)
        self.assertTrue(kept[0].text.startswith("An investment in the Company involves risk."))

    def test_contents_line_is_not_a_start(self):  # Eastman: "Risk Factors 56" in the MD&A contents
        blocks = doc(("Risk Factors 56", {"table_id": 4, "data_table": True}), "Overview", RISK_TEXT * 3,
                     "RISK FACTORS", RISK_TEXT, "ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK")
        self.assertEqual(find_by_heading(blocks).start, 3)

    def test_running_page_header_does_not_end_the_section(self):  # Eastman's MD&A page header
        header = "MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS"
        blocks = doc("RISK FACTORS", RISK_TEXT)
        for n in range(3):
            blocks += doc(RISK_TEXT, str(40 + n), (header, {"page_break_before": True}))
        blocks += doc(RISK_TEXT, "ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK")
        found = find_by_heading(blocks)
        self.assertTrue(found.end_text.startswith("ITEM 7A"))


class HeadedParts(unittest.TestCase):
    def test_parts_joined(self):  # Synchrony
        blocks = doc(("Risk Factors Relating To Our Business 62", {"table_id": 1, "data_table": True}),
                     ("Risk Management 82", {"table_id": 1, "data_table": True}),
                     ("Risk Factors Relating to Regulation 101", {"table_id": 1, "data_table": True}),
                     ("Consolidated Financial Statements 107", {"table_id": 1, "data_table": True}),
                     ("Risk Factors Relating to Our Business", {"bold": True}), RISK_TEXT,
                     ("Risk Management", {"bold": True}), "We manage risk carefully. " * 60,
                     ("Risk Factors Relating to Regulation", {"bold": True}), RISK_TEXT,
                     ("Consolidated Financial Statements", {"bold": True}), "Numbers.")
        parts = find_by_heading_parts(blocks)
        self.assertEqual([p.header_text for p in parts], ["Risk Factors Relating to Our Business",
                                                           "Risk Factors Relating to Regulation"])
        self.assertEqual([p.end_text for p in parts], ["Risk Management", "Consolidated Financial Statements"])


class PageRange(unittest.TestCase):
    def test_stop_at_end_of_last_stated_page(self):  # US Bancorp: "pages 140 to 155"
        blocks = doc("Risk Factors", RISK_TEXT, "154", RISK_TEXT, "155", "Managing Committee", "Andrew Cecere")
        found = find_by_heading(blocks)
        self.assertTrue(cut_at_page(blocks, found, 155))
        kept, _ = section_blocks(blocks, found)
        self.assertEqual([b.text for b in kept], [RISK_TEXT, RISK_TEXT])


class Cleaning(unittest.TestCase):
    def test_sentence_fragment_at_end_is_kept(self):  # ConocoPhillips
        self.assertFalse(is_leftover_label("increase for us in the future."))
        self.assertFalse(is_leftover_label("adequate coverage may"))
        self.assertTrue(is_leftover_label("Parts I and II"))

    def test_decorative_lines_removed(self):  # Synchrony "______", Wells Fargo "* * *"
        blocks = doc("Item 1A. Risk Factors", "_______________", RISK_TEXT, "* * *", "Item 1B. Unresolved Staff Comments")
        kept, _ = section_blocks(blocks, find_by_item(blocks))
        self.assertEqual([b.text for b in kept], [RISK_TEXT])

    def test_lines_rejoined_in_line_by_line_documents(self):  # ConocoPhillips
        kept = doc(("Risks Related to Our Industry", {"bold": True}), "You should carefully", "consider the following",
                   "risk factors.", "Our results", "may vary.", "• first bullet", "• second bullet")
        out, changed = reflow_lines(kept)
        self.assertTrue(changed)
        self.assertEqual([b.text for b in out], ["Risks Related to Our Industry",
                                                 "You should carefully consider the following risk factors.",
                                                 "Our results may vary.", "• first bullet", "• second bullet"])

    def test_normal_paragraphs_are_left_alone(self):
        out, changed = reflow_lines(doc(RISK_TEXT, RISK_TEXT))
        self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
