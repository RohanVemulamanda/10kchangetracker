# 10-K Change Tracker

Do companies that change the wording of their 10-K filings underperform afterward? The paper *Lazy Prices* (Cohen, Malloy & Nguyen, *Journal of Finance*, 2020) found that they did in 1995–2014. This project tests whether that still holds on recent data, measures *what kind* of language changed, and will become a live dashboard.

Every methodology choice is explained in **[DECISIONS.md](DECISIONS.md)**.

## Status

| Phase | What | Status |
|---|---|---|
| 0 | Project setup | Done |
| 1 | Download 10-Ks for historical S&P 500 members | Built and tested on fake data; **first real run pending** |
| 2 | Extract Item 1A (Risk Factors) | Not started |
| 3 | Change scores | Not started |
| 4 | Backtest | Not started |
| 5 | Live tool and dashboard | Not started |

## Setup (one time)

You need Python 3.10 or newer and git.

**Mac (Terminal):**
```bash
git clone https://github.com/RohanVemulamanda/10kchangetracker.git
cd 10kchangetracker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

**Windows (PowerShell):**
```powershell
git clone https://github.com/RohanVemulamanda/10kchangetracker.git
cd 10kchangetracker
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Then open `.env` in a text editor and put in your real name and email. SEC requires them on every request. `.env` is never uploaded to GitHub.

Each time you open a new terminal, activate the environment again (`source .venv/bin/activate`, or `.venv\Scripts\Activate.ps1` on Windows).

## Running Phase 1

Run these in order. On Windows, use `py` instead of `python` if `python` isn't found.

```bash
python run.py check                          # 1. test the SEC connection on Apple (a few seconds)
python run.py all --tickers AAPL,JPM,META    # 2. trial run on three companies (about a minute)
python run.py all                            # 3. full run (estimate: 30-60 minutes, 1-3 GB of disk)
```

- **The full run is safe to stop** (Ctrl+C) **and restart.** It resumes where it left off and never downloads a file twice.
- Each run writes a log file to `logs/` and a summary to `reports/phase1_summary.md`.
- `python run.py summary` prints the summary again at any time.
- `python run.py spot-check` prints 10 random filings with EDGAR links for checking by hand.

In the trial run, META will show `FB` as an unmapped ticker. That's expected: it shows the old-ticker problem described in DECISIONS.md D-009.

## Checking Phase 1 is correct

1. **Hand-check 10 random filings.** Run `python run.py spot-check`. It prints 10 random downloaded filings with what we stored, plus a link to each one's EDGAR page. Open each link and compare the filing date, "Accepted" time, and "Period of Report" with our values.
2. **Counts per fiscal year** in the summary should be about 500.
3. **Run `python run.py all` a second time.** The log should say `SEC requests this run: 0`, because everything comes from the cache.
4. **Stop the full run partway through and restart it.** It should pick up where it stopped.
5. **Read `reports/gaps.csv`** and explain each type of gap.
6. **Run the tests:** `pytest` (or `python -m unittest discover -s tests -t tests`).

## Fixing unmapped tickers

`reports/unmapped_tickers.csv` lists tickers we couldn't link to an SEC company, longest-serving first. For each one:

1. Search EDGAR by company name, e.g. `https://www.sec.gov/cgi-bin/browse-edgar?company=facebook&type=10-K`, and note its CIK.
2. Confirm it filed 10-Ks during the membership dates shown in the report.
3. Add a row to `data/reference/manual_cik_map.csv` saying how you checked:
   ```
   ticker,cik,company_name,evidence
   FB,1326801,Meta Platforms (formerly Facebook),"EDGAR: 10-Ks under this CIK during FB's membership; ticker became META on 2022-06-09"
   ```
4. Re-run `python run.py all`. Only the newly mapped companies get downloaded.

## Project layout

```
config/settings.yaml     every research setting (years, universe, rate limits)
run.py                   command-line entry point: python run.py --help
src/tracker/             the code, one file per job:
  edgar_client.py          all SEC requests: User-Agent, rate limit, retries, cache
  universe.py              S&P 500 membership periods
  ticker_map.py            ticker -> SEC company ID (CIK)
  submissions.py           each company's filing list from SEC
  selection.py             which 10-Ks we need (pure logic, heavily tested)
  header.py                acceptance time and document list from each filing's header
  downloader.py            downloads with resume
  summary.py               the end-of-run report
  pipeline.py              runs the steps in order
tests/                   unit tests (never contact SEC)
data/reference/          membership periods and hand-checked fixes (committed):
  manual_cik_map.csv       tickers SEC's file can't map, with evidence
  not_on_edgar.csv         companies whose 10-Ks aren't on EDGAR
  predecessors.csv         companies that moved to a new SEC ID
data/raw/                downloaded filings (not committed)
data/tracker.db          SQLite database (not committed)
reports/                 summaries and gap lists
DECISIONS.md             methodology choices and why
```

## Data sources

- **SEC EDGAR:** company ticker file, submissions API, and filing archives. Free; 10 requests per second maximum; User-Agent required.
- **S&P 500 membership:** [github.com/fja05680/sp500](https://github.com/fja05680/sp500), pinned to one version (see DECISIONS.md D-001).
