"""Phase 4: the Fama-French risk factors, from Kenneth French's data library (D-035).

A risk factor is the return of a simple long-short strategy that captures one kind of risk:
  Mkt-RF  the stock market minus the risk-free rate
  SMB     small companies minus big ones
  HML     cheap ("value") companies minus expensive ones, by book-to-market
  RMW     profitable companies minus unprofitable ones
  CMA     companies that invest conservatively minus aggressively
  Mom     past winners minus past losers (momentum)
  RF      the risk-free rate (1-month Treasury bills)
If non-changers beat changers only because they load more on these factors, the alpha is zero.

The files are downloaded by hand (see README) and pinned by SHA-256, like the S&P list.
Each is a zip holding one CSV: a few lines of notes, then a header row starting with ",",
then monthly rows ("202608,   2.56, ..."), then annual rows. Values are in percent.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from pathlib import Path

import pandas as pd


class FactorFileError(Exception):
    """A factor file is missing or isn't the pinned version."""


def read_french_zip(path: Path, sha256: str) -> pd.DataFrame:
    """The monthly rows of one Kenneth French zip file, as decimals (0.0256, not 2.56),
    indexed by month (a pandas Period, e.g. 2026-08). -99.99 and -999 mean missing."""
    if not path.exists():
        raise FactorFileError(f"Factor file not found: {path}. See README, 'Running Phase 4', for the download.")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256:
        raise FactorFileError(f"{path.name} is not the pinned version (SHA-256 {digest}, expected {sha256}).")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        text = archive.read(archive.namelist()[0]).decode("latin-1")

    lines = text.splitlines()
    header_at = next(i for i, line in enumerate(lines) if line.startswith(","))
    columns = [c.strip() for c in lines[header_at].split(",")[1:]]
    rows = []
    for line in lines[header_at + 1:]:
        if not re.match(r"^\s*\d{6}\s*,", line):
            break                                  # the monthly block ends where the annual one starts
        month, *values = [v.strip() for v in line.split(",")]
        rows.append([pd.Period(f"{month[:4]}-{month[4:]}", freq="M")] + [float(v) for v in values])
    frame = pd.DataFrame(rows, columns=["month"] + columns).set_index("month")
    frame = frame.mask(frame.isin([-99.99, -999.0]))
    return frame / 100


def load_factors(five_factor_path: Path, five_factor_sha256: str, momentum_path: Path, momentum_sha256: str) -> pd.DataFrame:
    """Monthly Mkt-RF, SMB, HML, RMW, CMA, RF and Mom, for the months both files cover."""
    five = read_french_zip(five_factor_path, five_factor_sha256)
    momentum = read_french_zip(momentum_path, momentum_sha256)
    momentum.columns = [c.strip() for c in momentum.columns]
    return five.join(momentum[["Mom"]], how="inner")
