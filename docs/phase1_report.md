# Phase 0–1 report: setup and data collection

Completed 2026-10-24. Every methodology choice mentioned here is explained in [DECISIONS.md](../DECISIONS.md).

> **Correction found in Phase 2 (2026-10-25, D-025).** Ticker PARA was linked to the wrong company. After Paramount Global's 2025 merger, SEC's ticker file gave PARA to Banzai International, so Banzai's 10-Ks had replaced Paramount's for fiscal 2021–2024. The Phase 1 reused-ticker check didn't catch this. After the fix the sample is **2,494** 10-Ks (not 2,495). A new check now compares each 10-K's cover-page company size against S&P 500 scale, and it found no other cases. The figures below are the original Phase 1 numbers.

## 1. What we built

**Phase 0: project setup.** A clean project structure. All research settings live in one file (`config/settings.yaml`). Every run writes a log file. A SQLite database tracks every filing. `DECISIONS.md` records each choice and why. Everything is in git.

**Phase 1: data collection.** A pipeline (`python run.py all`) that:

1. Builds historical S&P 500 membership from a free source pinned to one exact version, so the list includes companies that later left the index (D-001).
2. Links each ticker to the SEC company that files its 10-Ks. That takes SEC's ticker file, 58 hand-checked fixes, a list of companies whose 10-Ks aren't on EDGAR, and 4 companies that moved to a new SEC ID (D-009, D-017, D-018).
3. Gets each company's filing list from SEC. It chooses original 10-Ks for fiscal years 2021–2025 filed while the company was in the index, plus each one's prior-year 10-K as its comparison (D-002 to D-007).
4. Downloads each filing's header, main document, and any EX-13. It follows SEC's rules (User-Agent, 5 requests per second), never downloads a file twice, and resumes after a stop (D-011 to D-014).
5. Prints a summary with counts, failures, and a gap list, and gives a hand spot-check tool.

### The data

| | Count |
|---|---|
| Tickers in the S&P 500 at some point since June 2021 | 615 |
| Companies (SEC filers) | 591 |
| **Sample 10-Ks** (fiscal 2021–2025, in the index on filing date) | **2,495** (497–503 per year) |
| Comparison-only 10-Ks (prior years) | 553 |
| Downloaded / failed | 3,048 / 0 |
| Excluded on purpose: amendments (10-K/A), transition reports (10-KT), duplicate periods | 163 / 2 / 3 |
| Sample 10-Ks accepted at or after 4:00 pm Eastern | 1,510 (61%) |
| Filings with an EX-13 exhibit | 48 |

Remaining gaps, all explained:
- 12 spin-offs, IPOs, and new merged companies have no prior 10-K, so their first year is unscored (D-019).
- 2 failed banks (Signature, First Republic) filed with the FDIC, so their 10-Ks aren't on EDGAR (D-017).

## 2. How we checked it was correct

1. **Membership history.** Our membership periods reproduce all 2,720 daily snapshots in the source exactly. They also match the source's own start/end-date file for all 1,209 tickers. The settings store a fingerprint of the source files, so anyone re-running gets identical data.
2. **Real SEC formats.** `python run.py check` tested the code against Apple's real filings before the long run. All checks passed.
3. **Trial run.** A three-company run (Apple, JPMorgan, Meta) produced exactly the filings the rules predict, including Meta's 2021 10-K dropping out because it was filed under the old ticker FB.
4. **Hand-mapped tickers.**
   - Each of the 58 cites a 10-K on sec.gov under that SEC ID, and a test checks every link points to the same ID.
   - After the run, all 58 passed the automatic check: the company filed a 10-K while in the index.
   - SEC's company names matched ours.
5. **Gap report caught a real error.** Four companies had moved to a new SEC ID (Exxon, BlackRock, Bunge, APA). Exxon's whole five years were missing. After the fix, the counts changed by exactly the predicted amount: +8 sample and +4 comparison filings.
6. **Acceptance times.** For all 3,048 filings, the API's acceptance time matched the filing header's.
7. **Hand spot-check: 10 of 10 matched EDGAR** on filing date, acceptance time, and period of report:

   | Company | Accession number |
   |---|---|
   | Darden Restaurants | 0000940944-24-000035 |
   | Xcel Energy | 0000072903-23-000007 |
   | Constellation Brands | 0000016918-22-000069 |
   | Regions Financial | 0001281761-26-000019 |
   | McCormick | 0000063754-23-000005 |
   | Ball Corp | 0001558370-25-001190 |
   | Amgen | 0000318154-24-000011 |
   | AutoZone | 0001558370-22-015239 |
   | MetLife | 0001099219-22-000014 |
   | Salesforce | 0001108524-24-000005 |

8. **Resuming and caching.** Two downloads that failed on SEC's temporary 503 errors succeeded on the next run. Re-runs downloaded only what was new: 12 filings after the predecessor fix.
9. **81 automated tests.** They cover every selection rule, retries, the stop on repeated 403s, resuming after a crash, and header parsing. They run without contacting SEC.

## 3. What to say in an interview

> "I rebuilt the data pipeline behind *Lazy Prices* from scratch on SEC EDGAR, for S&P 500 companies over fiscal 2021 to 2025. That's about 2,500 10-Ks, all after the paper's sample ended.
>
> To avoid survivorship bias, I used historical index membership, not today's list. I verified it reproduced every daily snapshot of the source. Then I hand-mapped 58 companies that SEC's ticker file couldn't link, like acquired and renamed firms, each backed by a filing on sec.gov.
>
> The checks caught real problems. Exxon's ticker now points to a new 2026 holding company with no history, so five years of Exxon filings were missing until I linked the old SEC ID. Two failed banks filed with the FDIC, not the SEC, so I documented that leaving them out slightly biases the test against finding the effect.
>
> I take acceptance times from each filing's header because the timing rule matters: 61% of 10-Ks arrive after the market close. And I hand-checked 10 random filings against EDGAR, and all 10 matched."

## Limitations to disclose

- **Free price data usually drops delisted stocks** (Phase 4). Fixing membership alone doesn't remove survivorship bias from returns.
- **S&P 500 firms are the most-watched stocks**, so a weak effect here wouldn't prove the effect is gone.
- **The membership list is volunteer-maintained.** We verified it's internally consistent, not against S&P's official records.
- **The two FDIC-filing banks are excluded** (D-017).

## Next: Phase 2

Extract Item 1A (Risk Factors) from each 10-K.
