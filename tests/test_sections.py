"""Finding and cleaning the Risk Factors section, on small made-up documents."""
import unittest

import helpers  # noqa: F401
from tracker.html_text import Block
from tracker.sections import (find_by_heading, find_by_item, is_item_header, is_reference_only, overrun_hits,
                              page_furniture, scoring_text, section_blocks)

RISK_TEXT = " ".join(["Our business could be harmed by competition and changing market conditions."] * 40)  # 440 words


def doc(*items) -> list[Block]:
    """Build blocks from strings, or (text, {options}) pairs."""
    blocks = []
    for item in items:
        if isinstance(item, tuple):
            blocks.append(Block(item[0], **item[1]))
        else:
            blocks.append(Block(item))
    return blocks


def words_of(blocks, found):
    kept, _ = section_blocks(blocks, found)
    return scoring_text(kept)


class ItemMethod(unittest.TestCase):
    def test_skips_table_of_contents_and_takes_the_real_section(self):
        blocks = doc(("Item 1A. Risk Factors 12", {"table_id": 1, "data_table": True}),
                     ("Item 1B. Unresolved Staff Comments 20", {"table_id": 1, "data_table": True}),
                     "Item 1. Business", "We make widgets.",
                     "Item 1A. Risk Factors", RISK_TEXT,
                     "Item 1B. Unresolved Staff Comments", "None.")
        found = find_by_item(blocks)
        self.assertEqual((found.method, found.start, found.end), ("item", 4, 6))
        self.assertEqual(words_of(blocks, found), RISK_TEXT)

    def test_item_1c_cybersecurity_ends_the_section(self):
        blocks = doc("Item 1A. Risk Factors", RISK_TEXT, "Item 1C. Cybersecurity", "We have a security program.")
        self.assertEqual(find_by_item(blocks).end_text, "Item 1C. Cybersecurity")

    def test_header_formats(self):
        for header in ["ITEM 1A.", "Item 1A:", "Item 1A —", "ITEM 1(A). RISK FACTORS", "Item 1 (A) - Risk Factors", "Item 1A"]:
            self.assertEqual(is_item_header(header), (1, "a"), header)
        self.assertEqual(is_item_header("ITEM 1 (B). UNRESOLVED STAFF COMMENTS"), (1, "b"))
        self.assertEqual(is_item_header("Item 10. Directors"), (10, ""))

    def test_sentence_mentioning_an_item_is_not_a_header(self):
        long_sentence = "Item 1A of this report describes the risks that could affect our results, " * 3
        self.assertIsNone(is_item_header(long_sentence))
        self.assertIsNone(is_item_header("See Item 1A. Risk Factors."))

    def test_running_part_i_header_does_not_end_but_part_ii_does(self):
        blocks = doc("Item 1A. Risk Factors", RISK_TEXT, ("Part I", {"page_break_before": True}), RISK_TEXT,
                     "PART II", "Item 5. Market for Registrant's Common Equity")
        found = find_by_item(blocks)
        self.assertEqual(found.end, 4)
        self.assertGreater(found.words, 800)

    def test_reference_only_item(self):
        blocks = doc("ITEM 1A. RISK FACTORS",
                     "Information in response to this Item 1A can be found in the 2025 Annual Report under \"Risk Factors.\"",
                     "ITEM 1B. UNRESOLVED STAFF COMMENTS")
        found = find_by_item(blocks)
        self.assertTrue(is_reference_only(blocks, found))


class HeadingMethod(unittest.TestCase):
    def test_run_in_capitals_heading_like_ge(self):
        blocks = doc("Risk Factors 24", "Legal Proceedings 31",
                     "RISK FACTORS. The following discussion of material risks. " + RISK_TEXT,
                     "STRATEGIC RISKS. Strategic risk relates to our plans. " + RISK_TEXT,
                     "LEGAL PROCEEDINGS. Refer to Note 24.")
        found = find_by_heading(blocks)
        self.assertEqual((found.start, found.end), (2, 4))
        text = words_of(blocks, found)
        self.assertTrue(text.startswith("The following discussion of material risks."))
        self.assertIn("STRATEGIC RISKS.", text)

    def test_section_ends_at_next_title_in_contents_like_citigroup(self):
        blocks = doc(("RISK FACTORS 49", {"table_id": 1, "data_table": True}),
                     ("SUSTAINABILITY 62", {"table_id": 1, "data_table": True}),
                     "RISK FACTORS", RISK_TEXT, "SUSTAINABILITY", "Our climate goals... " * 50)
        found = find_by_heading(blocks)
        self.assertEqual(found.end_text, "SUSTAINABILITY")
        self.assertEqual(words_of(blocks, found), RISK_TEXT)

    def test_sentence_starting_with_risk_factors_is_not_a_heading(self):
        blocks = doc("Risk factors that could affect us include competition. " + RISK_TEXT)
        self.assertIsNone(find_by_heading(blocks))


class Cleaning(unittest.TestCase):
    def test_page_footers_removed_but_repeated_content_kept(self):
        blocks = doc("Item 1A. Risk Factors")
        for n in range(1, 6):  # five pages; a bullet repeats mid-page, like JPMorgan's "reputational harm"
            blocks += doc(RISK_TEXT, RISK_TEXT, "• reputational harm.", RISK_TEXT, RISK_TEXT,
                          f"Acme Corp | 2025 Form 10-K | {n}", str(n),
                          ("Risk Factors (continued)", {"page_break_before": True}))
        blocks += doc("Item 1B. Unresolved Staff Comments")
        found = find_by_item(blocks)
        kept, removed = section_blocks(blocks, found, page_furniture(blocks))
        kept_text = [b.text for b in kept]
        self.assertEqual(kept_text.count("• reputational harm."), 5)        # real content, repeated: kept
        self.assertFalse(any("Form 10-K" in t for t in kept_text))          # footers: removed
        self.assertNotIn("Risk Factors (continued)", kept_text)              # running headers: removed
        self.assertFalse(any(t.isdigit() for t in kept_text))               # page numbers: removed
        self.assertEqual(removed, 15)

    def test_short_heading_repeated_but_not_at_page_breaks_is_kept(self):
        blocks = doc("INTELLECTUAL PROPERTY", "x " * 50, "Item 1A. Risk Factors", "INTELLECTUAL PROPERTY", RISK_TEXT,
                     "INTELLECTUAL PROPERTY", RISK_TEXT, "Item 1B. Unresolved Staff Comments")
        kept, _ = section_blocks(blocks, find_by_item(blocks))
        self.assertEqual([b.text for b in kept].count("INTELLECTUAL PROPERTY"), 2)

    def test_short_leftover_at_end_of_section_is_removed(self):
        blocks = doc("Item 1A. Risk Factors", RISK_TEXT, "31", ("Parts I and II", {"page_break_before": True}),
                     "Item 1B. Unresolved Staff Comments")
        kept, _ = section_blocks(blocks, find_by_item(blocks))
        self.assertEqual([b.text for b in kept], [RISK_TEXT])

    def test_scoring_text_drops_data_tables_and_simplifies_punctuation(self):
        kept = doc("• We rely on “key” suppliers — and that’s a risk.",
                   ("Revenue 2025 1,234 2024 1,100", {"table_id": 3, "data_table": True}))
        self.assertEqual(scoring_text(kept), "We rely on \"key\" suppliers - and that's a risk.")

    def test_overrun_detection(self):
        kept = doc(RISK_TEXT, "Item 2. Properties", "We lease offices.")
        self.assertEqual(overrun_hits(kept), ["Item 2. Properties"])


if __name__ == "__main__":
    unittest.main()
