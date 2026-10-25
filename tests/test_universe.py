import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401
from tracker.universe import Membership, build_periods, load_snapshots, normalize_ticker

# A tiny made-up index history:
#   2020-01-02: AAA, BBB, CCC
#   2020-03-01: BBB replaced by DDD
#   2021-01-04: BBB comes back, CCC leaves
SNAPSHOTS = [
    ("2020-01-02", ["AAA", "BBB", "CCC"]),
    ("2020-03-01", ["AAA", "CCC", "DDD"]),
    ("2021-01-04", ["AAA", "BBB", "DDD"]),
]


class BuildPeriods(unittest.TestCase):
    def setUp(self):
        self.periods = build_periods(SNAPSHOTS)
        self.by_ticker = {}
        for p in self.periods:
            self.by_ticker.setdefault(p["sec_ticker"], []).append((p["start_date"], p["end_date"]))

    def test_never_removed_has_no_end(self):
        self.assertEqual(self.by_ticker["AAA"], [("2020-01-02", None)])

    def test_ticker_that_leaves_and_returns_gets_two_periods(self):
        self.assertEqual(self.by_ticker["BBB"], [("2020-01-02", "2020-03-01"), ("2021-01-04", None)])

    def test_removed_ticker_ends_on_first_day_out(self):
        self.assertEqual(self.by_ticker["CCC"], [("2020-01-02", "2021-01-04")])

    def test_rebuilding_snapshots_from_periods(self):
        m = Membership(self.periods)
        for day, tickers in SNAPSHOTS:
            members = {t for t in ["AAA", "BBB", "CCC", "DDD"] if m.is_member(t, day)}
            self.assertEqual(members, set(tickers), day)


class MembershipQueries(unittest.TestCase):
    def setUp(self):
        self.m = Membership(build_periods(SNAPSHOTS))

    def test_start_day_counts_end_day_does_not(self):
        self.assertTrue(self.m.is_member("DDD", "2020-03-01"))
        self.assertTrue(self.m.is_member("BBB", "2020-02-29"))
        self.assertFalse(self.m.is_member("BBB", "2020-03-01"))

    def test_unknown_ticker(self):
        self.assertFalse(self.m.is_member("ZZZ", "2020-06-01"))

    def test_tickers_active_between(self):
        self.assertEqual(self.m.tickers_active_between("2020-06-01", "2020-12-31"), {"AAA", "CCC", "DDD"})

    def test_member_days_does_not_double_count_two_share_classes(self):
        # Two tickers for one company, both members the whole time (like GOOG and GOOGL).
        m = Membership([
            {"sec_ticker": "GOOG", "start_date": "2020-01-01", "end_date": None},
            {"sec_ticker": "GOOGL", "start_date": "2020-01-01", "end_date": None},
        ])
        self.assertEqual(m.member_days({"GOOG", "GOOGL"}, "2021-01-01", "2022-01-01"), 365)

    def test_member_days_clips_to_window(self):
        self.assertEqual(self.m.member_days({"BBB"}, "2020-02-01", "2020-04-01"), 29)  # Feb 1 to Mar 1, 2020


class Tickers(unittest.TestCase):
    def test_share_class_dot_becomes_dash(self):
        self.assertEqual(normalize_ticker(" brk.b "), "BRK-B")


class LoadSnapshots(unittest.TestCase):
    def test_reads_source_format_and_rejects_out_of_order_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.csv"
            good.write_text('date,tickers\n2020-01-02,"AAA,BBB"\n2020-03-01,"AAA"\n', encoding="utf-8")
            self.assertEqual(load_snapshots(good), [("2020-01-02", ["AAA", "BBB"]), ("2020-03-01", ["AAA"])])

            bad = Path(tmp) / "bad.csv"
            bad.write_text('date,tickers\n2020-03-01,"AAA"\n2020-01-02,"AAA"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_snapshots(bad)


if __name__ == "__main__":
    unittest.main()
