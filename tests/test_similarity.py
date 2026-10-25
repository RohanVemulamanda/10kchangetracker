"""Phase 3: the four similarity measures (D-030), checked against answers worked out by hand."""
import math
import random
import unittest

import helpers  # noqa: F401
from tracker.similarity import compare, cosine, edit_distance, jaccard, min_edit, sentence_diff

PRIOR = "The cat sat. The dog ran."
CURRENT = "The cat sat. A bird flew away."


class HandCalculated(unittest.TestCase):
    """prior words:   the cat sat the dog ran          (6 words)
    current words: the cat sat a bird flew away     (7 words)"""

    def setUp(self):
        self.result = compare(PRIOR, CURRENT)

    def test_cosine(self):
        # counts: prior the=2 cat sat dog ran=1; current the cat sat a bird flew away=1
        # dot = 2*1 + 1 + 1 = 4; lengths sqrt(8) and sqrt(7)
        self.assertAlmostEqual(self.result.cosine, 4 / math.sqrt(8 * 7))

    def test_jaccard(self):
        # shared {the, cat, sat} = 3; either = 5 + 7 - 3 = 9
        self.assertAlmostEqual(self.result.jaccard, 3 / 9)

    def test_min_edit(self):
        # the->a, dog->bird, ran->flew, insert away: 4 edits; longer document 7 words
        self.assertAlmostEqual(self.result.min_edit, 1 - 4 / 7)

    def test_simple(self):
        # kept "The cat sat."; removed "The dog ran." (3 words); added "A bird flew away." (4 words)
        self.assertAlmostEqual(self.result.simple, 1 - (3 + 4) / (6 + 7))
        self.assertEqual(self.result.diff.removed, ["The dog ran."])
        self.assertEqual(self.result.diff.added, ["A bird flew away."])
        self.assertEqual(self.result.diff.kept, 1)

    def test_counts(self):
        self.assertEqual((self.result.prior_words, self.result.current_words), (6, 7))
        self.assertEqual((self.result.prior_sentences, self.result.current_sentences), (2, 2))


class Extremes(unittest.TestCase):
    def test_identical_text_scores_one(self):
        result = compare(PRIOR, PRIOR)
        self.assertEqual((result.cosine, result.jaccard, result.min_edit, result.simple), (1.0, 1.0, 1.0, 1.0))

    def test_nothing_in_common_scores_zero(self):
        result = compare("Apples grow slowly.", "Rates rose sharply today.")
        self.assertEqual((result.cosine, result.jaccard, result.min_edit, result.simple), (0.0, 0.0, 0.0, 0.0))

    def test_line_breaks_do_not_change_any_score(self):
        """The D-027 promise: the same words with different line breaks are identical."""
        one_line = "Our success depends on our ability to develop new medicines. Product development is uncertain."
        split = "Our success depends on our ability\nto develop new medicines. Product\ndevelopment is uncertain."
        result = compare(one_line, split)
        self.assertEqual((result.cosine, result.jaccard, result.min_edit, result.simple), (1.0, 1.0, 1.0, 1.0))

    def test_changed_numbers_do_not_count(self):
        result = compare("In fiscal 2024 sales were $5.1 billion.", "In fiscal 2025 sales were $6.3 billion.")
        self.assertEqual((result.cosine, result.jaccard, result.min_edit, result.simple), (1.0, 1.0, 1.0, 1.0))

    def test_empty_documents(self):
        self.assertEqual(cosine([], []), 1.0)
        self.assertEqual(cosine(["a"], []), 0.0)
        self.assertEqual(jaccard([], []), 1.0)
        self.assertEqual(min_edit([], []), 1.0)
        self.assertEqual(min_edit(["a", "b"], []), 0.0)


class EditDistance(unittest.TestCase):
    @staticmethod
    def slow(a, b):
        """The textbook version, one cell at a time."""
        previous = list(range(len(b) + 1))
        for i, x in enumerate(a, start=1):
            current = [i]
            for j, y in enumerate(b, start=1):
                current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
            previous = current
        return previous[-1]

    def test_known_answers(self):
        self.assertEqual(edit_distance(list("kitten"), list("sitting")), 3)
        self.assertEqual(edit_distance(["a", "b", "c"], ["a", "b", "c"]), 0)
        self.assertEqual(edit_distance([], ["a", "b"]), 2)

    def test_matches_textbook_version_on_random_cases(self):
        rng = random.Random(0)
        for _ in range(300):
            a = [rng.choice("abcd") for _ in range(rng.randint(0, 12))]
            b = [rng.choice("abcd") for _ in range(rng.randint(0, 12))]
            self.assertEqual(edit_distance(a, b), self.slow(a, b), (a, b))


class SentenceDiff(unittest.TestCase):
    def test_moved_sentence_counts_as_removed_and_added(self):
        diff = sentence_diff(["A one.", "B two.", "C three."], ["B two.", "C three.", "A one."])
        self.assertEqual((diff.removed, diff.added, diff.kept), (["A one."], ["A one."], 2))

    def test_common_sentences_in_long_documents_are_still_matched(self):
        """difflib's default "autojunk" would skip a sentence that repeats often in a long document."""
        prior = [f"Risk number {chr(97 + i % 26)}{chr(97 + i // 26)} applies." for i in range(300)]
        prior = [s if i % 10 else "This could harm our business." for i, s in enumerate(prior)]
        current = prior[:150] + ["A new risk appears."] + prior[150:]
        diff = sentence_diff(prior, current)
        self.assertEqual((diff.added, diff.removed, diff.kept), (["A new risk appears."], [], 300))


if __name__ == "__main__":
    unittest.main()
