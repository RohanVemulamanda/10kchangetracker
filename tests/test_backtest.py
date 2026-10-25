"""Phase 4: factors, portfolios and statistics, on small made-up data with known answers (D-033)."""
import hashlib
import io
import math
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

import helpers  # noqa: F401
from tracker.backtest_stats import alphas, fama_macbeth, newey_west_cov, regress
from tracker.factors import FactorFileError, read_french_zip
from tracker.portfolios import (add_controls, assign_quintiles, entry_month, is_financial, monthly_scores,
                                portfolio_returns)

FRENCH_CSV = """This file was created using the 202608 CRSP database.

,Mkt-RF,SMB,RF
202606,   -1.07,    4.36,    0.29
202607,   -0.61,  -99.99,    0.33

 Annual Factors: January-December
,Mkt-RF,SMB,RF
2025,   17.00,    1.00,    4.00
"""


def month(text):
    return pd.Period(text, freq="M")


class Factors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "factors.zip"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("factors.csv", FRENCH_CSV)
        self.path.write_bytes(buffer.getvalue())
        self.sha = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def test_monthly_rows_as_decimals_and_missing_values(self):
        frame = read_french_zip(self.path, self.sha)
        self.assertEqual(list(frame.index), [month("2026-06"), month("2026-07")])   # annual rows left out
        self.assertAlmostEqual(frame.loc[month("2026-06"), "Mkt-RF"], -0.0107)
        self.assertTrue(math.isnan(frame.loc[month("2026-07"), "SMB"]))

    def test_wrong_version_is_an_error(self):
        with self.assertRaises(FactorFileError):
            read_french_zip(self.path, "0" * 64)


class Timing(unittest.TestCase):
    def test_score_counts_from_the_month_after_acceptance(self):
        accepted = pd.Series(["2023-01-31 18:05:00", "2023-02-01 09:00:00", "2023-12-15 16:30:00"])
        self.assertEqual(list(entry_month(accepted)), [month("2023-02"), month("2023-03"), month("2024-01")])

    def test_financials(self):
        self.assertEqual(list(is_financial(pd.Series(["6022", "5990", "6798", None]))), [True, False, True, False])


class MonthlyScores(unittest.TestCase):
    def test_latest_score_within_12_months(self):
        scores = pd.DataFrame({
            "company_cik": [1, 1, 2],
            "accession_number": ["1-old", "1-new", "2-a"],
            "entry_month": [month("2023-03"), month("2024-03"), month("2023-06")],
            "sim_cosine": [0.90, 0.95, 0.99]})
        months = pd.period_range("2023-02", "2024-06", freq="M")
        held = monthly_scores(scores, months, "sim_cosine")
        by = {(r.month, r.company_cik): r.accession_number for r in held.itertuples()}
        self.assertNotIn((month("2023-02"), 1), by)                 # not yet usable
        self.assertEqual(by[(month("2023-03"), 1)], "1-old")
        self.assertEqual(by[(month("2024-02"), 1)], "1-old")        # 12th month
        self.assertEqual(by[(month("2024-03"), 1)], "1-new")        # replaced
        self.assertEqual(by[(month("2024-05"), 2)], "2-a")          # 12th month for company 2
        self.assertNotIn((month("2024-06"), 2), by)                 # expired after 12 months


class Quintiles(unittest.TestCase):
    def setUp(self):
        # 10 companies in one month; company i has similarity 0.9 + i/100 and returns i%
        self.held = assign_quintiles(pd.DataFrame({
            "month": month("2024-01"), "company_cik": range(10), "accession_number": "x",
            "score": [0.9 + i / 100 for i in range(10)]}))
        self.returns = pd.DataFrame({"company_cik": range(10), "month": month("2024-01"),
                                     "ret": [i / 100 for i in range(10)], "me_start": [1.0] * 9 + [3.0]})

    def test_two_per_quintile_lowest_similarity_in_q1(self):
        q = dict(zip(self.held.company_cik, self.held.quintile))
        self.assertEqual([q[i] for i in range(10)], [1, 1, 2, 2, 3, 3, 4, 4, 5, 5])

    def test_equal_weighted(self):
        table = portfolio_returns(self.held, self.returns)
        row = table.loc[month("2024-01")]
        self.assertAlmostEqual(row["Q1"], 0.005)                    # (0% + 1%) / 2
        self.assertAlmostEqual(row["Q5"], 0.085)                    # (8% + 9%) / 2
        self.assertAlmostEqual(row["Q5-Q1"], 0.08)
        self.assertEqual((row["stocks"], row["missing"]), (10, 0))

    def test_value_weighted(self):
        row = portfolio_returns(self.held, self.returns, "value").loc[month("2024-01")]
        self.assertAlmostEqual(row["Q5"], (0.08 * 1 + 0.09 * 3) / 4)

    def test_missing_return_is_counted_and_left_out(self):
        returns = self.returns[self.returns.company_cik != 0]
        row = portfolio_returns(self.held, returns).loc[month("2024-01")]
        self.assertAlmostEqual(row["Q1"], 0.01)
        self.assertEqual((row["stocks"], row["missing"]), (9, 1))


class Statistics(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.months = pd.period_range("2020-01", periods=60, freq="M")
        self.factors = pd.DataFrame({name: rng.normal(0, 0.04, 60) for name in
                                     ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"]}, index=self.months)
        self.factors["RF"] = 0.002

    def test_recovers_known_alpha_and_beta(self):
        y = 0.004 + 1.5 * self.factors["Mkt-RF"] - 0.5 * self.factors["SMB"]
        fit = regress(y, self.factors[["Mkt-RF", "SMB"]])
        np.testing.assert_allclose(fit.coef, [0.004, 1.5, -0.5], atol=1e-12)

    def test_mean_with_no_lags_matches_hand_formula(self):
        """With 0 lags and a constant only: se = sqrt(sum of squared deviations) / n."""
        y = pd.Series([0.01, 0.03, -0.02, 0.02], index=self.months[:4])
        fit = regress(y, None, lags=0)
        dev = y - y.mean()
        self.assertAlmostEqual(fit.coef[0], y.mean())
        self.assertAlmostEqual(fit.se[0], math.sqrt((dev ** 2).sum()) / 4)

    def test_newey_west_lag_term_by_hand(self):
        """Constant only, 1 lag: S = sum e_t^2 + 2 * (1/2) * sum e_t e_(t-1); var = S / n^2."""
        e = np.array([1.0, -2.0, 0.5, 1.5])
        X = np.ones((4, 1))
        expected = (np.sum(e ** 2) + 2 * 0.5 * np.sum(e[1:] * e[:-1])) / 16
        self.assertAlmostEqual(newey_west_cov(X, e, 1)[0, 0], expected)

    def test_alphas_excess_and_long_short(self):
        portfolio = 0.002 + 0.003 + 1.0 * self.factors["Mkt-RF"]    # RF + alpha + market
        result = alphas(portfolio, self.factors, excess=True)
        self.assertAlmostEqual(result["capm"]["estimate"], 0.003, places=10)
        self.assertAlmostEqual(result["ff5_mom"]["estimate"], 0.003, places=10)
        long_short = alphas(portfolio - 0.002, self.factors, excess=False)
        self.assertAlmostEqual(long_short["capm"]["estimate"], 0.003, places=10)

    def test_fama_macbeth_recovers_slope(self):
        rng = np.random.default_rng(1)
        rows = []
        for m in self.months:
            x = rng.uniform(0, 1, 50)
            rows.append(pd.DataFrame({"month": m, "x": x, "y": 0.01 + 0.5 * x}))
        result = fama_macbeth(pd.concat(rows), "y", ["x"])
        self.assertAlmostEqual(result["x"]["estimate"], 0.5, places=10)
        self.assertAlmostEqual(result["const"]["estimate"], 0.01, places=10)


class Controls(unittest.TestCase):
    def test_past_return_skips_last_month_and_needs_full_history(self):
        months = pd.period_range("2023-01", periods=14, freq="M")
        returns = pd.DataFrame({"company_cik": 1, "month": months, "ret": 0.01, "me_start": 100.0})
        returns.loc[12, "ret"] = 0.50          # 2024-01: a big month, which 2024-02 must skip (it's t-1)
        out = add_controls(returns).set_index("month")
        # 2024-01 (row 12): needs t-12..t-2 = 2023-01..2023-11, 11 months of 1%
        self.assertAlmostEqual(out.loc[month("2024-01"), "past_ret"], 1.01 ** 11 - 1)
        # 2024-02 (row 13): t-2 = 2023-12, still 1%; the 50% in 2024-01 is month t-1, skipped
        self.assertAlmostEqual(out.loc[month("2024-02"), "past_ret"], 1.01 ** 11 - 1)
        self.assertTrue(math.isnan(out.loc[month("2023-12"), "past_ret"]))   # only 10 months of history
        self.assertAlmostEqual(out.loc[month("2024-01"), "log_me"], math.log(100))

    def test_gap_in_months_blanks_past_return(self):
        months = list(pd.period_range("2023-01", periods=13, freq="M"))
        months[5] = month("2022-06")           # a company with a hole in its history
        returns = pd.DataFrame({"company_cik": 1, "month": sorted(months), "ret": 0.01, "me_start": 1.0})
        out = add_controls(returns)
        self.assertTrue(out["past_ret"].isna().all())


if __name__ == "__main__":
    unittest.main()
