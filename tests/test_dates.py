import unittest
from datetime import date

import helpers  # noqa: F401  (sets up the import path)
from tracker.dates import days_between, fiscal_year_from_period_end, parse_iso_date


class FiscalYearRule(unittest.TestCase):
    def test_december_year_end_is_same_year(self):
        self.assertEqual(fiscal_year_from_period_end(date(2024, 12, 31)), 2024)

    def test_apple_september_year_end(self):
        self.assertEqual(fiscal_year_from_period_end(date(2024, 9, 28)), 2024)

    def test_retailers_january_year_end_is_prior_year(self):
        # Walmart (year ending Jan 31, 2025) and Target (ending Feb 1, 2025) both become 2024,
        # even though the companies themselves label them differently.
        self.assertEqual(fiscal_year_from_period_end(date(2025, 1, 31)), 2024)
        self.assertEqual(fiscal_year_from_period_end(date(2025, 2, 1)), 2024)

    def test_may_june_cutoff(self):
        self.assertEqual(fiscal_year_from_period_end(date(2024, 5, 31)), 2023)
        self.assertEqual(fiscal_year_from_period_end(date(2024, 6, 1)), 2024)


class DateHelpers(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_iso_date("2024-09-28"), date(2024, 9, 28))
        self.assertIsNone(parse_iso_date(""))
        self.assertIsNone(parse_iso_date(None))

    def test_days_between(self):
        self.assertEqual(days_between("2023-09-30", "2024-09-28"), 364)


if __name__ == "__main__":
    unittest.main()
