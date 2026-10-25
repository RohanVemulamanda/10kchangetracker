"""Version 1.2 fixes (D-027). One test per real case; the full filings are in test_real_filings."""
import unittest

import helpers  # noqa: F401
from tracker.html_text import Block
from tracker.sections import (cut_at_item_pages, find_by_heading, find_by_item, is_item_header, names_item,
                              page_furniture, title_of, titles_after_in_contents)

RISK_TEXT = " ".join(["Our business could be harmed by competition and changing market conditions."] * 40)


def doc(*items):
    return [Block(i[0], **i[1]) if isinstance(i, tuple) else Block(i) for i in items]


class NotHeaders(unittest.TestCase):
    def test_quoted_title_is_a_cross_reference(self):  # Colgate 2021, after a page break
        self.assertIsNone(is_item_header("Part II, Item 7 “Management’s Discussion and Analysis – Executive Overview.”"))
        self.assertIsNone(is_item_header('Item 7, "Management\'s Discussion and Analysis"'))

    def test_part_prefix_needs_a_title(self):  # Entergy's running page header
        self.assertIsNone(is_item_header("Part I Item 1A & 1B"))
        self.assertIsNone(is_item_header("Part I Item 1A and 1B"))
        self.assertIsNone(is_item_header("Part I Item 1"))
        self.assertEqual(is_item_header("Part I. Item 1A. Risk Factors"), (1, "a"))  # Expedia still works

    def test_ordinary_headers_unchanged(self):
        self.assertEqual(is_item_header("Item 1A. Risk Factors"), (1, "a"))
        self.assertEqual(is_item_header("ITEM 1.A. RISK FACTORS"), (1, "a"))
        self.assertEqual(is_item_header("Item 1B."), (1, "b"))

    def test_cross_reference_does_not_end_item_1a(self):
        blocks = doc("Item 1A. Risk Factors", RISK_TEXT, "11",
                     "Part II, Item 7 “Management’s Discussion and Analysis.”", RISK_TEXT,
                     "Item 1B. Unresolved Staff Comments")
        self.assertEqual(find_by_item(blocks).end, 5)


class Titles(unittest.TestCase):
    def test_item_numbers_removed(self):
        self.assertEqual(title_of("Item 1. Business"), "business")  # the "B" isn't taken as "Item 1B"
        self.assertEqual(title_of("ITEM 1A RISK FACTORS"), "risk factors")
        self.assertEqual(title_of("1A. Risk Factors"), "risk factors")

    def test_bare_page_number_in_front_is_kept(self):  # Honeywell's contents: a page number, not an item
        self.assertEqual(title_of("30 Risk Factors"), "30 risk factors")

    def test_contents_with_page_numbers_first(self):  # Honeywell 2025
        rows = [("30 Risk Factors", {"table_id": 1, "data_table": True}),
                ("40 Quantitative and Qualitative Disclosures about Market Risks", {"table_id": 1, "data_table": True}),
                ("40 Liquidity and Capital Resources", {"table_id": 1, "data_table": True})]
        self.assertEqual(titles_after_in_contents(doc(*rows), "risk factors"),
                         {"quantitative and qualitative disclosures about market risks"})


class Ends(unittest.TestCase):
    def test_plural_market_risks_ends_the_section(self):  # Honeywell 2025
        blocks = doc("RISK FACTORS", RISK_TEXT, "QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISKS", RISK_TEXT)
        self.assertEqual(find_by_heading(blocks).end, 2)

    def test_executive_officers_ends_the_section(self):
        blocks = doc("RISK FACTORS", RISK_TEXT, "INFORMATION ABOUT OUR EXECUTIVE OFFICERS", "Jane Doe, 55, CEO")
        self.assertEqual(find_by_heading(blocks).end, 2)

    def test_mentioning_executive_officers_does_not_end_it(self):
        blocks = doc("RISK FACTORS", RISK_TEXT, "Information about our executive officers is important to us.",
                     RISK_TEXT, "Legal Proceedings")
        self.assertEqual(find_by_heading(blocks).end, 4)

    def test_names_item(self):
        self.assertTrue(names_item("Part I Item 1A & 1B", (1, "a")))
        self.assertTrue(names_item("Item 1(a) Risk Factors", (1, "a")))
        self.assertFalse(names_item("Part I Item 1", (1, "a")))
        self.assertFalse(names_item("Item 7A", (7, "")))
        self.assertTrue(names_item("Item 7 MD&A", (7, "")))

    def test_stops_after_last_page_headed_item_1a(self):  # Entergy 2020
        blocks = doc("Part I Item 1", ("RISK FACTORS", {"bold": True}), RISK_TEXT)
        for page in range(3):
            blocks += doc(str(100 + page), ("Part I Item 1A & 1B", {"page_break_before": True}), RISK_TEXT)
        blocks += doc("103", ("Entergy Arkansas, LLC", {"page_break_before": True}), "Results of operations...",
                      "104", ("Entergy Arkansas, LLC", {"page_break_before": True}), "More results...",
                      "105", ("Entergy Arkansas, LLC", {"page_break_before": True}), "Report of Independent Registered Public Accounting Firm")
        found = find_by_heading(blocks, furniture=page_furniture(blocks))
        self.assertEqual(blocks[found.end].text, "103")  # the page number after the last risk-factor page
        self.assertTrue(found.end_text.startswith("(end of the last page headed"))

    def test_no_cut_when_the_section_ends_on_the_last_headed_page(self):
        blocks = doc(("RISK FACTORS", {"bold": True}), RISK_TEXT)
        for page in range(3):
            blocks += doc(str(100 + page), ("Item 1A. Risk Factors (continued)", {"page_break_before": True}), RISK_TEXT)
        blocks += doc("Legal Proceedings", "None.", "103")
        found = find_by_heading(blocks, furniture=page_furniture(blocks))
        self.assertEqual(found.end_text, "Legal Proceedings")
        self.assertFalse(cut_at_item_pages(blocks, found, page_furniture(blocks)))


if __name__ == "__main__":
    unittest.main()
