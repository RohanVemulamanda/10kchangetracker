"""Phase 3 text preparation: joining lines, splitting sentences, words (D-028)."""
import unittest

import helpers  # noqa: F401
from tracker.textprep import join_lines, split_sentences, words

# Vertex FY2025: each printed line is its own element, so sentences run across lines (D-027).
VERTEX_LINES = (
    "Investing in our common stock involves a high degree of risk, and you should carefully consider the risks and\n"
    "uncertainties described below in addition to the other information included or incorporated by reference in this Annual\n"
    "Report on Form 10-K. If any of the following risks or uncertainties occur, our business, financial condition or results of\n"
    "operations would likely suffer, possibly materially. In that case, the trading price of our common stock could decline."
)
VERTEX_PARAGRAPH = VERTEX_LINES.replace("\n", " ")


class JoinLines(unittest.TestCase):
    def test_line_breaks_become_spaces(self):
        self.assertEqual(join_lines("the risks and\nuncertainties"), "the risks and uncertainties")

    def test_hyphen_at_line_end_is_kept_without_a_space(self):
        # In our data every hyphen at a line end is part of a real hyphenated word.
        self.assertEqual(join_lines("on third-\nparty platforms"), "on third-party platforms")

    def test_hyphen_before_a_capital_is_a_normal_break(self):
        self.assertEqual(join_lines("U.S.-\nBased"), "U.S.- Based")


class SplitSentences(unittest.TestCase):
    def test_line_breaks_do_not_change_sentences(self):
        """The D-027 promise: the same text with different line breaks gives the same sentences."""
        self.assertEqual(split_sentences(VERTEX_LINES), split_sentences(VERTEX_PARAGRAPH))
        self.assertEqual(len(split_sentences(VERTEX_LINES)), 3)

    def test_basic_split(self):
        self.assertEqual(split_sentences("We make chips. Demand may fall! Will costs rise? Yes."),
                         ["We make chips.", "Demand may fall!", "Will costs rise?", "Yes."])

    def test_abbreviations_do_not_end_sentences(self):
        text = "We sell to the U.S. Government and Acme Inc. Some sales are to No. 5 customers."
        self.assertEqual(split_sentences(text), [text])

    def test_abbreviation_then_sentence_opener_does_end_a_sentence(self):
        self.assertEqual(split_sentences("Most sales are outside the U.S. We face currency risk."),
                         ["Most sales are outside the U.S.", "We face currency risk."])

    def test_initials_do_not_end_sentences(self):
        text = "We compete with J. Smith Holdings in Europe."
        self.assertEqual(split_sentences(text), [text])

    def test_decimal_numbers_do_not_end_sentences(self):
        self.assertEqual(split_sentences("We owe $1.5 billion. Rates may rise."), ["We owe $1.5 billion.", "Rates may rise."])

    def test_closing_quote_stays_with_its_sentence(self):
        self.assertEqual(split_sentences('See "Risk Factors." The following applies.'),
                         ['See "Risk Factors."', "The following applies."])

    def test_heading_without_period_joins_the_next_sentence(self):
        """The accepted cost of ignoring line breaks (D-028)."""
        self.assertEqual(split_sentences("Risks Related to Our Business\nOur success depends on new medicines."),
                         ["Risks Related to Our Business Our success depends on new medicines."])

    def test_empty_text(self):
        self.assertEqual(split_sentences(""), [])


class Words(unittest.TestCase):
    def test_lower_case_and_no_punctuation(self):
        self.assertEqual(words("Our Company's third-party suppliers, (mostly) abroad."),
                         ["our", "company's", "third-party", "suppliers", "mostly", "abroad"])

    def test_numbers_become_a_placeholder(self):
        """A year rolling over isn't a change in wording (D-028)."""
        self.assertEqual(words("In fiscal 2024 we spent $1,500.5 million"), words("In fiscal 2025 we spent $2,100 million"))
        self.assertEqual(words("fiscal 2024"), ["fiscal", "#"])

    def test_line_breaks_do_not_change_words(self):
        self.assertEqual(words(join_lines(VERTEX_LINES)), words(VERTEX_PARAGRAPH))


if __name__ == "__main__":
    unittest.main()
