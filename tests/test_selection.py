"""Tests for choosing filings. Each test is one situation that could make the sample wrong."""
import unittest

from helpers import tenk
from tracker.selection import mapping_problem, select_filings
from tracker.universe import Membership

ALWAYS_MEMBER = Membership([{"sec_ticker": "ACME", "start_date": "2000-01-01", "end_date": None}])


def choose(filings, membership=ALWAYS_MEMBER, tickers=("ACME",), start=2021, end=2023):
    return select_filings(1234, filings, set(tickers), membership, start, end, earliest_needed="2019-01-01")


def roles(result):
    return {r["accession_number"]: r["role"] for r in result.selected}


class FormsAndDuplicates(unittest.TestCase):
    def test_amendments_and_transition_reports_are_excluded_and_logged(self):
        result = choose([
            tenk("A21", "2022-02-20", "2021-12-31"),
            tenk("A21-AMEND", "2022-04-01", "2021-12-31", form="10-K/A"),
            tenk("T22", "2022-09-01", "2022-06-30", form="10-KT"),
        ])
        self.assertIn("A21", roles(result))
        self.assertNotIn("A21-AMEND", roles(result))
        reasons = {e["accession_number"]: e["reason"] for e in result.excluded}
        self.assertIn("10-K/A", reasons["A21-AMEND"])
        self.assertIn("10-KT", reasons["T22"])

    def test_other_forms_are_ignored_silently(self):
        result = choose([tenk("A21", "2022-02-20", "2021-12-31"), tenk("Q1", "2022-05-01", "2022-03-31", form="10-Q")])
        self.assertEqual(list(roles(result)), ["A21"])
        self.assertEqual(result.excluded, [])

    def test_duplicate_period_keeps_the_first_filed(self):
        result = choose([
            tenk("LATE", "2022-03-15", "2021-12-31"),
            tenk("FIRST", "2022-02-20", "2021-12-31"),
        ])
        self.assertIn("FIRST", roles(result))
        self.assertNotIn("LATE", roles(result))
        self.assertTrue(result.excluded[0]["reason"].startswith("duplicate period"))

    def test_missing_report_date_is_excluded(self):
        result = choose([tenk("X", "2022-02-20", "")])
        self.assertEqual(result.selected, [])
        self.assertEqual(result.excluded[0]["reason"], "missing report date")


class SampleAndComparison(unittest.TestCase):
    def test_fiscal_year_range_and_prior_year_comparison(self):
        filings = [tenk(f"A{y}", f"{y + 1}-02-20", f"{y}-12-31") for y in range(2019, 2025)]
        result = choose(filings)  # sample = FY2021-2023
        self.assertEqual(roles(result), {"A2020": "comparison", "A2021": "sample", "A2022": "sample", "A2023": "sample"})
        row = next(r for r in result.selected if r["accession_number"] == "A2022")
        self.assertEqual(row["prior_accession"], "A2021")
        self.assertEqual(row["prior_gap_days"], 365)
        self.assertEqual(row["fiscal_year"], 2022)

    def test_company_joining_mid_window_keeps_its_pre_membership_prior_year(self):
        # Joined the index on 2022-06-01. Its FY2021 10-K (filed Feb 2022) is from before it joined.
        joined = Membership([{"sec_ticker": "ACME", "start_date": "2022-06-01", "end_date": None}])
        filings = [tenk(f"A{y}", f"{y + 1}-02-20", f"{y}-12-31") for y in range(2020, 2024)]
        result = choose(filings, membership=joined)
        self.assertEqual(roles(result), {"A2021": "comparison", "A2022": "sample", "A2023": "sample"})

    def test_filing_after_removal_is_not_in_sample(self):
        removed = Membership([{"sec_ticker": "ACME", "start_date": "2000-01-01", "end_date": "2023-01-15"}])
        filings = [tenk(f"A{y}", f"{y + 1}-02-20", f"{y}-12-31") for y in range(2020, 2024)]
        result = choose(filings, membership=removed)
        self.assertEqual(roles(result), {"A2020": "comparison", "A2021": "sample"})

    def test_membership_is_checked_on_the_filing_date(self):
        # In the index only from 2022-02-21: one day AFTER the FY2021 10-K was filed.
        late = Membership([{"sec_ticker": "ACME", "start_date": "2022-02-21", "end_date": None}])
        result = choose([tenk("A2021", "2022-02-20", "2021-12-31")], membership=late)
        self.assertEqual(result.selected, [])

    def test_any_share_class_counts(self):
        both = Membership([{"sec_ticker": "ACME-A", "start_date": "2000-01-01", "end_date": "2022-01-01"},
                           {"sec_ticker": "ACME-B", "start_date": "2021-06-01", "end_date": None}])
        result = choose([tenk("A2021", "2022-02-20", "2021-12-31")], membership=both, tickers=("ACME-A", "ACME-B"))
        self.assertEqual(result.selected[0]["member_tickers"], "ACME-B")

    def test_first_ever_10k_has_no_prior(self):
        result = choose([tenk("IPO", "2022-03-01", "2021-12-31")])
        self.assertIsNone(result.selected[0]["prior_accession"])

    def test_skipped_year_gives_a_long_gap(self):
        result = choose([tenk("A2020", "2021-02-20", "2020-12-31"), tenk("A2022", "2023-02-20", "2022-12-31")])
        row = next(r for r in result.selected if r["accession_number"] == "A2022")
        self.assertEqual(row["prior_accession"], "A2020")
        self.assertEqual(row["prior_gap_days"], 730)

    def test_52_53_week_label_clash_keeps_both_and_warns(self):
        # Year ends on the Saturday nearest May 31: June 3, 2023 then June 1, 2024 then May 31, 2025.
        filings = [tenk("Y1", "2023-07-20", "2023-06-03"), tenk("Y2", "2024-07-20", "2024-06-01"),
                   tenk("Y3", "2025-07-20", "2025-05-31")]
        result = choose(filings, start=2021, end=2025)
        labels = {r["accession_number"]: r["fiscal_year"] for r in result.selected}
        self.assertEqual(labels, {"Y1": 2023, "Y2": 2024, "Y3": 2024})
        self.assertEqual(len(result.notes), 1)


class MappingCheck(unittest.TestCase):
    PERIODS = [("2015-01-01", "2023-06-01")]

    def test_fine_when_a_10k_was_filed_during_membership(self):
        self.assertIsNone(mapping_problem(["2022-02-20"], 700, self.PERIODS, "2021-06-01", "2026-10-24"))

    def test_flags_company_with_no_10k_during_membership(self):
        # e.g. a reused ticker now pointing to a company that only started filing in 2024
        msg = mapping_problem(["2024-03-01", "2025-03-01"], 730, self.PERIODS, "2021-06-01", "2026-10-24")
        self.assertIn("wrong company", msg)

    def test_short_stints_are_not_judged(self):
        self.assertIsNone(mapping_problem([], 200, self.PERIODS, "2021-06-01", "2026-10-24"))


if __name__ == "__main__":
    unittest.main()
