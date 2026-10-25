"""Phase 4: the statistics for the backtest (D-033).

  regress()        least-squares regression with Newey-West standard errors
  alphas()         a portfolio's alpha under several risk models (raw, CAPM, FF3, FF5 + momentum)
  fama_macbeth()   a cross-sectional regression every month, averaged over the months

Written with numpy only, so each step can be read and checked by hand.

Newey-West standard errors: monthly portfolio returns can be correlated with their own recent
past, and their volatility changes over time. Ordinary standard errors assume neither, and
would overstate how sure we are. Newey-West corrects for both, using a set number of lags
(3 months here, fixed in D-033).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

NEWEY_WEST_LAGS = 3

# The risk models, from simplest to the main one (D-033). "raw" is just the average return.
RISK_MODELS = {
    "raw": [],
    "capm": ["Mkt-RF"],
    "ff3": ["Mkt-RF", "SMB", "HML"],
    "ff5_mom": ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"],
}


@dataclass
class Fit:
    names: list[str]          # "const" first, then the factors
    coef: np.ndarray
    se: np.ndarray
    months: int

    @property
    def t(self) -> np.ndarray:
        return self.coef / self.se

    def row(self, name: str) -> dict:
        i = self.names.index(name)
        return {"estimate": float(self.coef[i]), "se": float(self.se[i]), "t": float(self.t[i]),
                "ci_low": float(self.coef[i] - 1.96 * self.se[i]), "ci_high": float(self.coef[i] + 1.96 * self.se[i]),
                "months": self.months}


def newey_west_cov(X: np.ndarray, residuals: np.ndarray, lags: int) -> np.ndarray:
    """Newey-West covariance of the coefficients: (X'X)^-1 S (X'X)^-1, where S adds up the
    products x_t e_t e_s x_s' for months up to `lags` apart, with weights 1 - lag/(lags+1)."""
    scores = X * residuals[:, None]                # one row per month: x_t * e_t
    S = scores.T @ scores
    for lag in range(1, lags + 1):
        weight = 1 - lag / (lags + 1)
        gamma = scores[lag:].T @ scores[:-lag]
        S += weight * (gamma + gamma.T)
    bread = np.linalg.inv(X.T @ X)
    return bread @ S @ bread


def regress(y: pd.Series, factors: pd.DataFrame | None = None, lags: int = NEWEY_WEST_LAGS) -> Fit:
    """Regress y on a constant (and the factors, if given), months matched by index."""
    data = y.to_frame("y") if factors is None or factors.empty else y.to_frame("y").join(factors, how="inner")
    data = data.dropna()
    X = np.column_stack([np.ones(len(data))] + [data[c].to_numpy() for c in data.columns[1:]])
    yv = data["y"].to_numpy()
    coef, *_ = np.linalg.lstsq(X, yv, rcond=None)
    residuals = yv - X @ coef
    se = np.sqrt(np.diag(newey_west_cov(X, residuals, lags)))
    return Fit(["const"] + list(data.columns[1:]), coef, se, len(data))


def alphas(portfolio: pd.Series, factors: pd.DataFrame, excess: bool) -> dict[str, dict]:
    """The portfolio's alpha (the constant) under each risk model.

    excess=True for a long-only portfolio: its return minus the risk-free rate is regressed.
    A long-short portfolio (Q5 - Q1) costs nothing to hold, so it's regressed as is.
    """
    y = portfolio - factors["RF"].reindex(portfolio.index) if excess else portfolio
    return {model: regress(y, factors[columns] if columns else None).row("const")
            for model, columns in RISK_MODELS.items()}


def fama_macbeth(panel: pd.DataFrame, y: str, xs: list[str], lags: int = NEWEY_WEST_LAGS) -> dict[str, dict]:
    """Each month, regress y on xs across companies. Then average each coefficient over the months;
    its standard error comes from how much it varies from month to month (Newey-West on that series).
    `panel` has one row per company and month, with a "month" column."""
    monthly = []
    for month, group in panel.dropna(subset=[y] + xs).groupby("month"):
        if len(group) <= len(xs) + 1:
            continue
        X = np.column_stack([np.ones(len(group))] + [group[x].to_numpy() for x in xs])
        coef, *_ = np.linalg.lstsq(X, group[y].to_numpy(), rcond=None)
        monthly.append(pd.Series(coef, index=["const"] + xs, name=month))
    coefs = pd.DataFrame(monthly)
    return {name: regress(coefs[name], None, lags).row("const") for name in coefs.columns}
