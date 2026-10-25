"""Phase 3: Loughran-McDonald word counts in new and dropped sentences (D-032)."""
import hashlib
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401
from tracker.wordlists import (WordListError, count, dictionary_words, load_word_lists, measure_change_words,
                               new_and_dropped)
from tracker.score import connect_changes

# The real file's layout: each category column holds the year a word was added, or minus the
# year it was removed.
DICTIONARY = """Word,Seq_num,Negative,Positive,Uncertainty,Litigious,Source
LOSS,1,2009,0,0,0,x
LOSSES,2,2009,0,0,0,x
BREAKING,3,-2020,0,0,0,x
MAY,4,0,0,2009,0,x
LAWSUIT,5,0,0,0,2009,x
PARTY,6,0,0,0,2011,x
GOOD,7,0,2009,0,0,x
"""


class WordLists(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "lm.csv"
        self.path.write_text(DICTIONARY)
        self.sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.lists = load_word_lists(self.path, self.sha)

    def tearDown(self):
        self.tmp.cleanup()

    def test_removed_words_are_not_on_the_list(self):
        self.assertEqual(self.lists["negative"], {"loss", "losses"})   # BREAKING was removed in 2020
        self.assertEqual(self.lists["uncertainty"], {"may"})
        self.assertEqual(self.lists["litigious"], {"lawsuit", "party"})

    def test_wrong_version_or_missing_file_is_an_error(self):
        with self.assertRaises(WordListError):
            load_word_lists(self.path, "0" * 64)
        with self.assertRaises(WordListError):
            load_word_lists(self.path.with_name("missing.csv"), self.sha)

    def test_hyphens_and_possessives(self):
        self.assertEqual(dictionary_words("A third-party lawsuit's losses"), ["a", "third", "party", "lawsuit", "losses"])

    def test_count(self):
        result = count(["We may face a lawsuit.", "Losses may grow, breaking records."], self.lists)
        self.assertEqual(result, {"sentences": 2, "words": 10, "negative": 1, "uncertainty": 2, "litigious": 1})

    def test_moved_sentences_are_neither_new_nor_dropped(self):
        new, dropped = new_and_dropped(["Moved one.", "Brand new risk."], ["Old risk.", "Moved one."])
        self.assertEqual((new, dropped), (["Brand new risk."], ["Old risk."]))

    def test_moved_ignores_numbers_and_punctuation(self):
        new, dropped = new_and_dropped(["In 2025, sales fell."], ["In 2024 sales fell."])
        self.assertEqual((new, dropped), ([], []))

    def test_measure_change_words(self):
        cconn = connect_changes(Path(self.tmp.name) / "changes.db")
        cconn.execute("INSERT INTO changes (accession_number, section, version, status) VALUES ('a', 'item_1a', 'main', 'ok')")
        rows = [("added", 0, "A lawsuit may cause losses."), ("added", 1, "Moved one."),
                ("removed", 0, "Moved one."), ("removed", 1, "Old loss.")]
        cconn.executemany("INSERT INTO changed_sentences (accession_number, section, kind, position, text) "
                          "VALUES ('a', 'item_1a', ?, ?, ?)", rows)
        self.assertEqual(measure_change_words(cconn, self.lists), 1)
        got = {r["kind"]: dict(r) for r in cconn.execute("SELECT * FROM change_words")}
        self.assertEqual((got["new"]["sentences"], got["new"]["negative"], got["new"]["uncertainty"],
                          got["new"]["litigious"]), (1, 1, 1, 1))
        self.assertEqual((got["dropped"]["sentences"], got["dropped"]["words"], got["dropped"]["negative"]), (1, 2, 1))
        measure_change_words(cconn, self.lists)   # redone each run: no duplicates
        self.assertEqual(cconn.execute("SELECT COUNT(*) FROM change_words").fetchone()[0], 2)
        cconn.close()


if __name__ == "__main__":
    unittest.main()
