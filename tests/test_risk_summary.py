"""Phase 3: finding and removing the risk factor summary (D-029).

Each test is a shortened version of a real Item 1A from our filings.
"""
import unittest

import helpers  # noqa: F401
from tracker.risk_summary import comparable, find_summary, remove_summary

LONG = " ".join(["word"] * 150)  # a full-length risk factor paragraph


def lines(text: str) -> list[str]:
    return text.strip("\n").split("\n")


class FindSummary(unittest.TestCase):
    def test_repeat_of_first_category_heading(self):
        """Micron FY2025: the full section starts over with the summary's first heading."""
        text = lines(f"""
In addition to the factors discussed elsewhere in this Annual Report, this section discusses risks.
Risk Factor Summary
Risks Related to Our Business, Operations, and Industry
volatility in average selling prices of our products;
a range of factors that may adversely affect our gross margins;
Risks Related to Intellectual Property and Litigation
protecting our intellectual property;
Risks Related to Our Business, Operations, and Industry
Volatility in average selling prices for our products may adversely affect our business.
{LONG}
""")
        found = find_summary(text)
        self.assertEqual((found.start, found.end, found.rule), (1, 7, "repeat"))

    def test_repeat_ignores_plural_endings(self):
        """Match FY2025: "Risk relating to..." in the summary, "Risks relating to..." below it.
        Its intro paragraph is split over 3 lines, so the heading is only a restart point
        because it's the summary's first category heading."""
        text = lines(f"""
Risk Factor Summary
Our business is subject to a number of risks, including risks that may prevent us from achieving our
business objectives or may adversely affect our business, financial condition, and results of operations. These
risks are discussed more fully below and include, but are not limited to:
Risk relating to our business
If we fail to retain existing users or add new users, our revenue may be harmed.
The industry for social connection apps is competitive.
Risks relating to our business
If we fail to retain existing users or add new users, or if our users do not convert to paying users, our
{LONG}
""")
        found = find_summary(text)
        self.assertEqual((found.end, found.rule), (7, "repeat"))

    def test_refers_back_line_is_the_last_summary_line(self):
        """Qorvo FY2022."""
        text = lines(f"""
Risk Factors Summary
The following is a summary of the principal risks that could adversely affect our business.
We depend on several large customers for a substantial portion of our revenue.
We depend heavily on third parties.
For a more complete discussion of the material risks facing our business, see below.
Risks Related to Our Business and Industry
Our operating results fluctuate on a quarterly and annual basis.
{LONG}
""")
        found = find_summary(text)
        self.assertEqual((found.end, found.rule), (5, "refers_back"))

    def test_intro_to_the_full_section(self):
        """GE HealthCare FY2024."""
        text = lines(f"""
SUMMARY OF RISK FACTORS.
An investment in our company is subject to a number of risks.
We operate in highly competitive markets.
Global geopolitical instability may affect us.
You should carefully consider the following risks and other information in this Annual Report.
INDUSTRY AND ECONOMIC RISKS.
{LONG}
""")
        found = find_summary(text)
        self.assertEqual((found.end, found.rule), (4, "intro"))

    def test_bare_risk_factors_heading(self):
        """M&T FY2021 and AIG FY2023: the full section has its own "Risk Factors" title."""
        text = lines(f"""
Risk Factors Summary
Risks Relating to the Merger with People's United
M&T is expected to incur significant costs related to the merger.
Combining M&T and People's United may be more difficult than expected.
Risk Factors
M&T and its subsidiaries face a number of potential risks.
{LONG}
""")
        found = find_summary(text)
        self.assertEqual((found.end, found.rule), (4, "heading"))

    def test_first_category_heading_when_summary_has_none(self):
        """Autodesk FY2023: a plain list, then the full section's first category heading."""
        text = lines(f"""
Summary of Risk Factors
Our business is subject to numerous risks and uncertainties.
Global economic and political conditions.
Costs and challenges associated with strategic acquisitions and investments.
Our debt service obligations.
Risks Relating to Our Business and Strategy
Our strategy to develop and introduce new products and services exposes us to risks.
{LONG}
""")
        found = find_summary(text)
        self.assertEqual((found.end, found.rule), (5, "category"))

    def test_list_item_ending_in_semicolon_is_not_a_heading(self):
        """Booking FY2020: "Risks associated with the restructuring of our business;" is a list item."""
        text = lines(f"""
Risk Factors Summary
The adverse impact of the COVID-19 pandemic on our business;
Adverse changes in general market conditions for travel services;
The effects of competition;
Risks associated with the restructuring of our business;
Any write-downs or impairments of goodwill;
Risks Related to the COVID-19 Pandemic
The COVID-19 pandemic has had a significant impact on our business.
{LONG}
""")
        found = find_summary(text)
        self.assertEqual((found.end, found.rule), (6, "category"))

    def test_long_paragraph_before_the_end_is_kept(self):
        """Vistra FY2023: "Please carefully consider..." is the full section's introduction."""
        text = lines(f"""
Summary of Risk Factors
Market, Financial and Economic Risks
Our revenues are affected by price fluctuations.
We may not pay any dividends on our common stock in the future.
Please carefully consider the following discussion of significant factors. {LONG}
Market, Financial and Economic Risks
Our revenues generally are affected by price fluctuations.
""")
        found = find_summary(text)
        self.assertEqual((found.end, found.rule, found.long_line), (4, "repeat", False))

    def test_repeated_closing_sentence_is_not_a_restart(self):
        """Alexandria: each group of the summary ends with the same sentence. Only the summary's
        first lines and first category heading count as restart points."""
        closing = "The realization of any of the above risks could significantly and adversely affect us."
        text = lines(f"""
Risk factors summary
An investment in our securities involves various risks.
Risks related to operating factors
We may be unable to identify and complete acquisitions.
{closing}
Risks related to market and industry factors
We may be unable to lease space.
{closing}
Operating factors
We may be unable to identify and complete acquisitions, investments, or development projects.
{LONG}
""")
        found = find_summary(text)
        self.assertEqual((found.end, found.rule), (None, "too_long"))

    def test_bare_heading_is_not_a_summary(self):
        """Williams FY2024: a "Summary of Risk Factors" heading with the full section right under it."""
        text = lines(f"""
Summary of Risk Factors
You should carefully consider the following risk factors.
Risks Related to Business
{LONG}
""")
        self.assertIsNone(find_summary(text))

    def test_no_summary(self):
        self.assertIsNone(find_summary(lines(f"Risks Related to Our Business\n{LONG}\n{LONG}")))

    def test_summary_heading_must_be_near_the_start(self):
        text = [LONG] * 11 + ["Risk Factor Summary", "a;", "b;", "c;", "Risks Related to Taxes", LONG]
        self.assertIsNone(find_summary(text))

    def test_no_end_within_2500_words_removes_nothing(self):
        # 400 different items (identical lines would look like the full section starting over)
        text = ["Risk Factor Summary"] + [f"Item {chr(97 + i % 26)}{chr(97 + i // 26)} about one risk to our business;"
                                          for i in range(400)]
        found = find_summary(text)
        self.assertEqual((found.end, found.rule), (None, "too_long"))
        self.assertEqual(remove_summary("\n".join(text))[0], "\n".join(text))


class RemoveSummary(unittest.TestCase):
    def test_keeps_text_before_and_after(self):
        text = "Intro line.\nRisk Factor Summary\na;\nb;\nc;\nRisk Factors\nFull text."
        cleaned, found = remove_summary(text)
        self.assertEqual(cleaned, "Intro line.\nRisk Factors\nFull text.")
        self.assertEqual(found.rule, "heading")

    def test_end_override(self):
        """A hand-checked end (Gallagher 2023) replaces the rules' end."""
        text = "Risk Factor Summary\na;\nb;\nc;\nd;\nRisks Relating to our Business Generally\nFull.\nb;\nMore."
        cleaned, found = remove_summary(text, end_override="Risks Relating to our Business Generally")
        self.assertEqual(cleaned, "Risks Relating to our Business Generally\nFull.\nb;\nMore.")
        self.assertEqual(found.rule, "override")

    def test_end_override_that_is_not_found_is_an_error(self):
        with self.assertRaises(ValueError):
            remove_summary("Risk Factor Summary\na;\nb;\nc;\nRisk Factors\nFull.", end_override="Nowhere")


class Comparable(unittest.TestCase):
    def test_ignores_case_punctuation_and_plurals(self):
        self.assertEqual(comparable("Risks Relating to Our Business:"), comparable("risk relating to our business"))


if __name__ == "__main__":
    unittest.main()
