"""Extraction on real 10-Ks, one per layout we have to handle.

The expected first and last sentences were checked by hand: for each filing we printed
the lines around the start and the end of the section and confirmed that the section
starts right after the Item 1A / Risk Factors header and stops right before the next
section's header. Word counts are allowed to move a little (5%) so small cleanup
changes don't break the tests; a wrong start or end would move them far more.

The files are public SEC filings, stored compressed in tests/fixtures/filings/.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from helpers import FIXTURES
from tracker.extract import extract_filing

FILINGS = FIXTURES / "filings"


def run(primary: str, exhibit13: list[str] | None = None) -> dict:
    filing = {"accession_number": "test", "primary_path": primary,
              "exhibit13_paths": json.dumps(exhibit13) if exhibit13 else None}
    return extract_filing(filing, FILINGS)


class RealFilings(unittest.TestCase):
    def check(self, row, method, words, first, last, end_starts, not_in=()):
        self.assertEqual(row["status"], "ok", row.get("notes"))
        self.assertEqual(row["method"], method)
        self.assertAlmostEqual(row["words"], words, delta=words * 0.05)
        lines = row["scoring_text"].split("\n")
        self.assertTrue(lines[0].startswith(first), lines[0][:120])
        self.assertTrue(lines[-1].endswith(last), lines[-1][-120:])
        self.assertTrue(row["end_text"].startswith(end_starts), row["end_text"])
        for junk in not_in:
            self.assertNotIn(junk, row["scoring_text"])

    def test_apple_standard_layout(self):
        self.check(run("320193/000032019325000079/aapl-20250927.htm.gz"), "item", 9682,
                   "The following summarizes factors that could have a material adverse effect on the Company's business",
                   "material adverse impact on investor confidence and employee retention.",
                   "Item 1B. Unresolved Staff Comments", not_in=["Apple Inc. | 2025 Form 10-K"])

    def test_ice_parenthesized_item_numbers(self):
        self.check(run("1571949/000157194923000006/ice-20221231.htm.gz"), "item", 18269,
                   "The risks and uncertainties described below are those that we currently believe",
                   "which could have a material adverse effect on our business and operations.",
                   "ITEM 1 (B). UNRESOLVED STAFF COMMENTS")

    def test_ge_annual_report_layout_with_run_in_heading(self):
        self.check(run("40545/000004054526000008/ge-20251231.htm.gz"), "heading", 8935,
                   "The following discussion of the material factors, events and uncertainties",
                   "See Note 24 for further information about legal proceedings and other loss contingencies.",
                   "LEGAL PROCEEDINGS.", not_in=["2025 FORM 10-K"])

    def test_wells_fargo_risk_factors_in_annual_report_exhibit(self):
        folder = "72971/000007297126000133/"
        row = run(folder + "wfc-20251231_d2.htm.gz", [folder + "wfc-20251231.htm.gz"])
        self.check(row, "heading_exhibit13", 14746,
                   "An investment in the Company involves risk, including the possibility that the value",
                   "elsewhere in this Report that could adversely affect our financial results and condition.",
                   "Controls and Procedures", not_in=["Risk Factors (continued)", "Wells Fargo & Company 6"])
        self.assertTrue(row["source_document"].endswith("wfc-20251231.htm.gz"))
        self.assertIn("refers elsewhere", row["notes"])

    def test_wells_fargo_without_the_exhibit_is_not_found(self):
        row = run("72971/000007297126000133/wfc-20251231_d2.htm.gz")
        self.assertEqual(row["status"], "not_found")

    def test_dominion_header_split_across_tags(self):
        self.check(run("715957/000095017023003287/d-20221231.htm.gz"), "item", 9328,
                   "The Companies' businesses are influenced by many factors that are difficult to predict",
                   "which may cause a decrease in the Companies' results of operations and cash flows.",
                   "Item 1B. Unresolved Staff Comments")

    def test_citigroup_ends_at_next_title_in_its_contents(self):
        self.check(run("831001/000083100126000011/c-20251231.htm.gz"), "heading", 12082,
                   "The following discussion presents what management currently believes could be the material risks",
                   "management time and attention and other resources.", "SUSTAINABILITY")

    # Version 1.2 cases (D-027)

    def test_honeywell_contents_with_page_numbers_first(self):
        # Contents rows read "30 Risk Factors", "40 Quantitative and Qualitative Disclosures about Market Risks".
        self.check(run("773840/000077384026000013/hon-20251231.htm.gz"), "heading", 8441,
                   "Our business, operating results, cash flows, and financial condition are subject to the material risks",
                   "results of operations, cash flows, liquidity, and financial condition.",
                   "QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISKS",
                   not_in=["LIQUIDITY AND CAPITAL RESOURCES", "INFORMATION ABOUT OUR EXECUTIVE OFFICERS"])

    def test_colgate_cross_reference_after_page_break_is_not_a_header(self):
        # Page 11 ends mid-sentence; page 12 starts: Part II, Item 7 "Management's Discussion...".
        row = run("21665/000002166522000003/cl-20211231.htm.gz")
        self.check(row, "item", 7978,
                   "In addition to the risks described elsewhere in this report, set forth below is a summary",
                   "could adversely impact our business, results of operations, cash flows and financial condition.",
                   "ITEM 1B. UNRESOLVED STAFF COMMENTS")
        self.assertIn('Part II, Item 7 "Management\'s Discussion', row["scoring_text"])

    def test_entergy_ends_at_last_page_headed_item_1a(self):
        # No "Item 1A" or "Item 1B" header; every risk-factor page is headed "Part I Item 1A & 1B".
        self.check(run("65984/000006598421000096/etr-20201231.htm.gz"), "heading", 16647,
                   'See "RISK FACTOR SUMMARY" in Part I Item 1 for a summary of Entergy\'s',
                   "subject to prior payment of distributions on its preferred securities.",
                   "(end of the last page headed", not_in=["Part I Item 1A & 1B", "MANAGEMENT'S FINANCIAL DISCUSSION"])

    def test_display_version_keeps_original_punctuation(self):
        row = run("320193/000032019325000079/aapl-20250927.htm.gz")
        first = json.loads(row["display_json"])[0]["t"]
        self.assertIn("Company’s", first)       # curly apostrophe, as written
        self.assertIn("Company's", row["scoring_text"].split("\n")[0])  # plain apostrophe for scoring


if __name__ == "__main__":
    unittest.main()
