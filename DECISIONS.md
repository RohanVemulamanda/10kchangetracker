# Methodology decisions

Every choice that could change the results is recorded here: what we chose, what else we considered, why, and how it could affect the results. Settings live in `config/settings.yaml`; the D-numbers match the comments there.

---

## Phase 0–1: data collection

### D-001 Universe: historical S&P 500 membership
- **Chose:** Companies that were in the S&P 500 at the time, using the free list at [fja05680/sp500](https://github.com/fja05680/sp500), pinned to commit `a2430f2` (updated 2026-09-07; data through 2026-08-18). The settings file stores a fingerprint (SHA-256) of the exact files, and the code refuses to run on anything different.
- **Considered:** (a) Today's S&P 500 list: simple, but it only includes survivors. (b) Every company that files a 10-K: closest to the original paper, but several thousand filings a year, messier small-company filings, and free price data is weakest for small and delisted stocks.
- **Why:** Using today's list creates survivorship bias. Companies that failed or were removed would be missing, and those are often the ones whose 10-Ks changed most. A historical list fixes this on the membership side. The full universe only makes sense with CRSP data from WRDS.
- **Could affect results by:**
  - The list is maintained by a volunteer and isn't verified against S&P's official records. Its base file (1996–2019) came from a book author; changes since 2019 come from Wikipedia plus the maintainer's checks.
  - It uses tickers only, so we have to map tickers to companies ourselves (D-009).
  - Membership after 2026-08-18 is assumed unchanged.
  - **Check done:** our membership periods reproduce all 2,720 daily snapshots in the source exactly, and match the source repo's own start/end-date file for all 1,209 tickers.

### D-002 Sample rule: in the index on the filing date
- **Chose:** A 10-K is in the sample if the company (any of its tickers) was an S&P 500 member on the day it was filed.
- **Considered:** Members at the start of the calendar year; members at any time during the year.
- **Why:** The filing date is when investors could act on the 10-K, and membership on that date was public information at the time. So this rule introduces no look-ahead.
- **Could affect results by:** Companies right around an index addition or removal can drift in or out of the sample by a few days. That's a small effect.

### D-003 Build period: fiscal years 2021–2025
- **Chose:** Score 10-Ks for fiscal years 2021–2025 first. With their FY2020 comparison filings, that's six years of filings and five years of scores. We extend to 10+ years once everything works.
- **Why:** The original paper's sample ended in 2014. Everything here comes after it, so it's a true out-of-sample test. Building the pipeline on these years doesn't bias the backtest, because we won't look at any returns until Phase 4. **Before Phase 4, we'll lock in which years are held out.**
- **Limit on extending:** Item 1A (Risk Factors) has been required in 10-Ks since fiscal years ending around December 2005, so extending further back than about 2006 isn't possible for risk factors.

### D-004 Fiscal year labels: the Compustat rule
- **Chose:** A year ending June–December gets that calendar year as its label. A year ending January–May counts as the previous year.
- **Why:** Companies label years inconsistently. Walmart calls its year ending January 2025 "fiscal 2025". Target calls its year ending February 2025 "fiscal 2024". One rule for everyone makes year-over-year matching consistent.
- **Edge case handled:** Companies with 52/53-week years ending near May 31 / June 1 can get the same label twice in a row. We keep both filings and flag them, rather than wrongly dropping one as a duplicate. Comparisons link each filing to the one right before it, not to a label.

### D-005 Forms: original 10-Ks only
- **Chose:** Form `10-K` only. Excluded: `10-K/A` (amendments) and `10-KT` (transition reports covering a partial year after a fiscal-year change). Every exclusion is logged in the `excluded_filings` table.
- **Why:** Amendments are often partial (just one exhibit or one section) and are filed later, so including them would mix in a different kind of document filed at a different time. Transition reports cover a short year, which would distort year-over-year comparisons.
- **Could affect results by:** If an amendment replaced the whole 10-K, we keep the original instead. That's rare.

### D-006 Duplicates: keep the first filed
- **Chose:** If a company has two original 10-Ks for the same period end, keep the earliest one.
- **Why:** The first filing is what the market saw first. Keeping it avoids a later re-filing contaminating the timing.

### D-007 The comparison filing is always downloaded
- **Chose:** For each sample 10-K, we also download the company's previous 10-K, even if the company wasn't in the index when it was filed.
- **Why:** A company that joins in 2023 has its 2023 10-K compared with its 2022 10-K. Without the earlier one, every new member's first year in the index would be lost, which would bias the sample toward long-time members.
- **Flagged, not fixed:** A prior 10-K whose period ended outside 300–430 days earlier (a skipped year or a fiscal-year change) is listed in `reports/gaps.csv`. Phase 3 decides how to treat these cases.

### D-008 Acceptance time: from the filing's own header
- **Chose:** Read the acceptance time from each filing's header page (`...-index-headers.html`), not from the submissions API's `acceptanceDateTime` field. Both are stored, and the difference between them is recorded.
- **Why:** The API field is labeled UTC, but other developers have documented it being off by hours for some filers ([edgartools PR #1502](https://github.com/dgunning/edgartools/pull/1502)). Phase 4 decides whether a filing counts on the same trading day or the next one, so a wrong time means look-ahead bias.
- **Cost:** One extra request per filing.

### D-009 Ticker → company (CIK) mapping
- **Chose:** In this order: (1) hand-checked fixes in `data/reference/manual_cik_map.csv`, (2) SEC's current ticker file, (3) Wikipedia's current S&P list (which includes CIKs). Anything still unmapped is reported, never guessed.
- **Why:** SEC's ticker file only covers tickers in use today. Acquired, bankrupt, and renamed companies (FB → META) are missing under their old tickers, and some old tickers now belong to different companies.
- **Checks:**
  - Wikipedia's CIKs for current members are compared with SEC's; any disagreement is flagged.
  - A company in the index for a year or more must have filed at least one 10-K during that time. If the linked CIK didn't, the link is flagged as probably wrong (this catches reused tickers).
- **Could affect results by:** Every unmapped ticker is a company missing from the sample. Removed companies are over-represented among the unmapped, so leaving them out would bring survivorship bias back. **They have to be resolved before Phase 4.**

### D-010 Companies with two share classes count once
- **Chose:** One 10-K per company, even when two of its share classes are both in the index (GOOG/GOOGL, FOX/FOXA, NWS/NWSA).
- **Why:** It's one document. Counting it twice would double that company's weight.
- **Open for Phase 4:** Decide which share class's returns to use.

### D-011 What we download for each filing
- **Chose:** The header page, the main 10-K document, and any EX-13 exhibit.
- **Considered:** The full submission text file (complete, but tens of MB per filing, and we'd have to split it ourselves); the main document only (smallest, but misses exhibits).
- **Why:** Some companies put their annual report, sometimes including the risk factors, in EX-13. This is the smallest download that covers that case. The header's full document list is saved, so we can fetch other exhibits later without guessing.

### D-012 Storage: SQLite plus compressed files
- **Chose:** One SQLite database (`data/tracker.db`) for filing details and download status. The raw files are saved gzip-compressed under `data/raw/`.
- **Why:** SQLite is good at tracking "what's done and what's left," which is how a stopped run resumes. Large HTML files don't belong inside a database. Parquet will be used for extracted text in Phase 2.

### D-013 Our own downloader instead of a library
- **Chose:** A downloader written with `requests` (about 170 lines).
- **Considered:** `edgartools`, an open-source library that does much of this.
- **Why:** Every step can be explained line by line. Writing it ourselves is also how we found and handled the acceptance-time problem (D-008).

### D-014 Request rate and failure handling
- **Chose:** 5 requests per second (half SEC's cap of 10). Temporary errors (429, 5xx, timeouts) are retried with waits of 1, 2, 4, 8... seconds. A 404 is not retried. The run stops completely after 3 "403 Forbidden" responses in a row. A failed filing is retried on later runs, up to 3 attempts in total.
- **Why:** These are SEC's fair-access rules. Stopping on repeated 403s avoids getting blocked for longer.

### D-015 Industry codes as of the filing date
- **Chose:** Store the SIC industry code from each filing's header (as of that filing), as well as the company's current code.
- **Why:** Companies sometimes change industry codes. The Phase 4 splits (by industry, with and without financials) should use the code that applied at the time.

### D-016 Cached filing lists aren't refreshed by default
- **Chose:** Company filing lists are downloaded once and reused. Set `refresh_submissions: true` to fetch them again.
- **Why:** This is fine for historical work. Phase 5 (live updates) will need to refresh.

### D-017 Companies whose 10-Ks aren't on EDGAR
- **Chose:** List them in `data/reference/not_on_edgar.csv` with a reason and evidence. Report them separately from unmapped tickers, and exclude them from the sample.
- **Who:** Signature Bank (SBNY) and First Republic Bank (FRC). Both were banks with no holding company. A bank like that files its Exchange Act reports with its bank regulator (here, the FDIC) instead of the SEC, so EDGAR has none of their 10-Ks. SBNY is confirmed by its own press release; FRC is to be confirmed by hand on EDGAR.
- **Could affect results by:** Both banks failed in March–May 2023, so their late risk-factor sections probably changed a lot. Leaving them out removes likely "big changers" that then crashed. That **biases the test against finding the Lazy Prices effect**, though only slightly: it's 2 firms out of roughly 600. SVB Financial Group, the third failed bank, did have a holding company and is in the sample.

### First real run: ticker mapping results (2026-10-24)
- 615 tickers were in the index at some point since 2021-06-01. 553 mapped through SEC's ticker file, 2 through Wikipedia, and 60 could not be mapped automatically.
- Of the 60: 58 were mapped by hand in `manual_cik_map.csv`. Each row cites a 10-K on sec.gov filed under that CIK, and a unit test checks that every cited link's CIK matches the CIK column. The other 2 are the FDIC filers (D-017).
- The 58 were acquisitions (Twitter, Xilinx, Activision, ...), renames (FB→META, ANTM→ELV, VIAC→PARA, ...), and companies taken private or merged in 2024–2026 (Hess, Juniper, Discover, Walgreens, ...).
- After re-running, each hand mapping is checked automatically (D-009: a 10-K filed during membership), and the summary prints SEC's own company name next to ours for a by-eye check.

---

## Known limitations (to disclose)

1. **Free price data drops delisted stocks.** Fixing membership doesn't fully fix survivorship bias. If a company went bankrupt, its 10-K may be in our data while its final price crash is missing. This needs WRDS/CRSP, or a clear disclosure. (Phase 4)
2. **The S&P 500 is a hard test for this idea.** The paper used all U.S. firms, and its explanation is that investors don't pay attention. S&P 500 firms get more attention than almost any other stocks. A weaker effect here would not prove the effect is gone.
3. **Statistical power.** About 500 firms means quintiles of about 100, and most 10-Ks arrive in February–March. Results will be noisier than the paper's.
4. **The membership list is unverified** beyond our own consistency checks (D-001).
5. **Combined filings.** A few groups (often utilities) file one 10-K covering a parent and its subsidiaries. We key it to the CIK of the index member.

## Open items before Phase 4
- [x] Resolve every ticker in `reports/unmapped_tickers.csv` (58 mapped by hand, 2 not on EDGAR)
- [ ] Re-run and confirm all 58 hand mappings pass the automatic check and the names match
- [ ] Confirm by hand that First Republic Bank has no 10-Ks on EDGAR
- [ ] Review the `suspicious_mapping` rows in `reports/gaps.csv`
- [ ] Lock in the held-out time period
- [ ] Decide which share class to use for two-class companies (D-010)
