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
- **Result (first full run, 2026-10-24):** the API time and the header time agreed for all 2,877 downloaded filings. The documented problem didn't appear in our sample. We keep using the header anyway: it is the official record, and checking cost little. The more important finding: 1,415 of 2,364 sample 10-Ks (60%) were accepted at or after 4:00 pm Eastern, so the after-close rule in Phase 4 affects most of the sample.

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
- **Why:** SQLite is good at tracking "what's done and what's left," which is how a stopped run resumes. Large HTML files don't belong inside a database.
- **Update (Phase 2):** the plan was Parquet for extracted text. We used a second SQLite file, `data/processed/sections.db`, instead: the same format as the rest of the project, simple resuming per filing, and it can be tested without extra libraries. Text can be exported to Parquet later if Phase 3 needs it.

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
- **Who:** Signature Bank (SBNY) and First Republic Bank (FRC). Both were banks with no holding company. A bank like that files its Exchange Act reports with its bank regulator (here, the FDIC) instead of the SEC, so EDGAR has none of their 10-Ks. SBNY is confirmed by its own press release. FRC was confirmed by hand on 2026-10-24: an EDGAR company search for "First Republic Bank" (10-K filers) returns only two mortgage pass-through trusts from 2000, not the bank.
- **Could affect results by:** Both banks failed in March–May 2023, so their late risk-factor sections probably changed a lot. Leaving them out removes likely "big changers" that then crashed. That **biases the test against finding the Lazy Prices effect**, though only slightly: it's 2 firms out of roughly 600. SVB Financial Group, the third failed bank, did have a holding company and is in the sample.

### First real run: ticker mapping results (2026-10-24)
- 615 tickers were in the index at some point since 2021-06-01. 553 mapped through SEC's ticker file, 2 through Wikipedia, and 60 could not be mapped automatically.
- Of the 60: 58 were mapped by hand in `manual_cik_map.csv`. Each row cites a 10-K on sec.gov filed under that CIK, and a unit test checks that every cited link's CIK matches the CIK column. The other 2 are the FDIC filers (D-017).
- The 58 were acquisitions (Twitter, Xilinx, Activision, ...), renames (FB→META, ANTM→ELV, VIAC→PARA, ...), and companies taken private or merged in 2024–2026 (Hess, Juniper, Discover, Walgreens, ...).
- After re-running, each hand mapping is checked automatically (D-009: a 10-K filed during membership), and the summary prints SEC's own company name next to ours for a by-eye check.
- **Result of the re-run:** all 58 passed the automatic check, and the names matched. One name looked odd at first: EQR now shows as "Vivmark Residential". Equity Residential and AvalonBay merged in August 2026 and the combined company took that name under EQR's ID, so the mapping is right.

### D-018 Companies that moved to a new SEC ID
- **Problem found by the gap report:** SEC's ticker file maps each ticker to the company's *current* SEC ID. When a company reorganizes under a new legal parent, the new parent gets a new ID, and the ticker points there. Every 10-K filed before the change sits under the old ID, so those years were missing.
  - **Exxon (XOM)** moved under a new Texas holding company in 2026. The new ID has filed no 10-K yet, so *all five* sample years were missing. It was flagged as `suspicious_mapping`.
  - **BlackRock (BLK, 2024), Bunge (BG, 2023), and APA/Apache (2021)** did the same. They were flagged as `no_prior_10k`, because the new ID's first 10-K had no earlier 10-K under the same ID.
- **Chose:** List old IDs in `data/reference/predecessors.csv`, with evidence. The pipeline treats the old and new IDs as one company: it includes the old ID's 10-Ks, compares the new ID's first 10-K with the old ID's last one, and keeps the new ID's filing if both filed for the same period. Each filing keeps the ID that actually filed it (needed for download links), plus `company_cik` for the company it belongs to.
- **Rule for what counts:** only a legal reorganization of the *same business* (a new holding company or a move to another country), where shareholders swap shares 1-for-1 and the 10-K continues. Spin-offs, IPOs, and mergers that create a different company are **not** linked. Their first 10-K has nothing comparable to compare with, so their first year is left unscored.
- **Could affect results by:** without this, about 10 sample 10-Ks from four large companies would be missing, and the four first-year comparisons would be lost.
- **Phase 5 note:** live updates must also look up the old ID when a ticker moves to a new one.

### D-019 Spin-offs, IPOs and new merged companies: first year unscored
- **Chose (option A):** a company's first-ever 10-K has no prior-year comparison, so it is not scored. Its later years are scored normally.
- **Considered (option B):** comparing the first 10-K with the parent's or merger partner's 10-K.
- **Why:** the change score measures how a company rewrote *its own* report. A parent's 10-K is a different company's document, so the score would mostly measure "different company," not "changed language." Option A is simple to explain and loses little.
- **Affected:** 12 of 2,495 sample filings (0.5%): Organon, Constellation Energy, GE HealthCare, Kenvue, Solventum, Veralto, GE Vernova, Smurfit Westrock, Amentum, Paramount Skydance, Qnity, FedEx Freight.

---

## Phase 2: extracting Item 1A (Risk Factors)

Designed against 26 real documents from the downloads (20 random filings plus JPMorgan, Wells Fargo, Citigroup, GE and Apple), and checked on all of them: 25 of 25 filings extracted, with the start and end confirmed by printing the text around each boundary.

### D-020 How the section is found
- **Text first:** each 10-K's HTML is turned into blocks, one per paragraph or table row. Text inside a paragraph is joined even when split across formatting tags. Without this, Dominion's header reads "Item 1A. Ris" / "k Factors" and is missed. Hidden content (`display:none`) is removed; in 10-Ks it is only XBRL tagging data and empty spacer cells.
- **Method 1, `item` (standard layout):** every block that starts with an Item 1A header is a candidate ("ITEM 1A.", "Item 1A:", "Item 1(A)", "Item 1 (A) -"). Each candidate's section runs to the next header with a later item number (1B, 1C, 2, ...) or "PART II". We keep the candidate with the most words, which skips the table-of-contents entry. Item 1C (Cybersecurity, required since late 2023) is handled like any later item. "Part I" doesn't end the section, because some 10-Ks (JPMorgan) print it as a running header on every page.
- **If Item 1A only points elsewhere** ("...can be found in the Annual Report..."), we look in the EX-13 exhibit (Wells Fargo).
- **Method 2, `heading` (annual-report layout, the fallback chosen as option A):** a block that is the heading "Risk Factors", or starts with it in capitals ("RISK FACTORS. The following..." in GE). The section ends at whichever comes first: the next title after "Risk Factors" in the document's own table of contents (Citigroup: "Sustainability"), or a standard 10-K section title ("Legal Proceedings", "Controls and Procedures", ...).
- **Order:** item in the main document, then EX-13 if the main document refers there, then heading in the main document, then the EX-13 methods. The first that finds 300+ words wins.
- **Recorded:** every result stores its method, source document, start header and end header. Phase 4 can re-run results with only `item`-method filings as a robustness check.
- **Library:** the plan said BeautifulSoup. We used `lxml` directly, which BeautifulSoup itself uses underneath: it parsed the sample files about 5x faster (0.1–0.7 seconds per filing versus 0.3–3.9), so a full run takes minutes instead of over an hour.

### D-021 Cleaning: page numbers, page headers and footers
- **Removed:** page numbers ("23", "- 23 -", "Page 23"), "Table of Contents" links, and running page headers and footers.
- **Rule for headers and footers:** a short line (100 characters or fewer, digits ignored) that appears 3+ times, with at least 90% of its copies within two lines of a page break or page number.
  - On the samples, every real header and footer met this: Goldman Sachs 244 of 244 copies, Bank of America 45 of 45, Wells Fargo "Risk Factors (continued)" 6 of 6.
  - Repeated real content didn't: a JPMorgan bullet repeated 7 times sat at a page boundary once, and an ICE sub-heading 2 of 3 times.
  - An earlier, simpler rule ("any short line repeated 3+ times") wrongly removed both, which is why position is part of the rule.
- **Also removed:** short footers containing a changing page number that appear 5+ times outside tables ("Apple Inc. | 2025 Form 10-K | 12"), for documents without page-break markers; and a short leftover line at the very end of the section at a page boundary (JPMorgan's "Parts I and II").
- **Known limitation:** a short real line that sits next to a page break in nearly every copy would be removed. We saw none in the samples.

### D-022 Two versions of the text
- **Display version:** paragraphs as written, with bold and italic marked and data tables included (flagged as tables), for the dashboard and for headings of individual risk factors.
- **Scoring version:** prose only (data tables dropped), curly quotes and dashes made plain, bullet characters removed, one paragraph per line. Lower-casing and word-splitting are Phase 3 choices.
- **Kept in both:** risk-factor sub-headings, because they are part of what the company wrote.

### D-023 Quality checks
Each extraction is `ok`, `flagged`, `not_found`, or `error`. Flags:
- `short`: under 1,000 words. S&P 500 risk sections are usually 4,000–28,000; the samples' shortest was 4,148.
- `long`: over 50,000 words.
- `overrun`: a later item's header appears inside the text, a sign we grabbed too much.
- `length_jump`: more than 3x longer or shorter than the same company's prior-year extraction. Usually an extraction error, sometimes a real rewrite; each one gets looked at.

Flagged filings are kept, not dropped, and are listed in `reports/phase2_flagged.csv`.

### D-024 Re-running after fixes
Each result stores the version of the extraction code (`EXTRACTOR_VERSION`). Changing the rules means bumping the version. The next run then redoes every filing, so all results always come from the same rules.

---

## Known limitations (to disclose)

1. **Free price data drops delisted stocks.** Fixing membership doesn't fully fix survivorship bias. If a company went bankrupt, its 10-K may be in our data while its final price crash is missing. This needs WRDS/CRSP, or a clear disclosure. (Phase 4)
2. **The S&P 500 is a hard test for this idea.** The paper used all U.S. firms, and its explanation is that investors don't pay attention. S&P 500 firms get more attention than almost any other stocks. A weaker effect here would not prove the effect is gone.
3. **Statistical power.** About 500 firms means quintiles of about 100, and most 10-Ks arrive in February–March. Results will be noisier than the paper's.
4. **The membership list is unverified** beyond our own consistency checks (D-001).
5. **Combined filings.** A few groups (often utilities) file one 10-K covering a parent and its subsidiaries. We key it to the CIK of the index member.

## Open items before Phase 4
- [x] Resolve every ticker in `reports/unmapped_tickers.csv` (58 mapped by hand, 2 not on EDGAR)
- [x] Re-run and confirm all 58 hand mappings pass the automatic check and the names match
- [x] Confirm by hand that First Republic Bank has no 10-Ks on EDGAR
- [x] Review the `suspicious_mapping` rows in `reports/gaps.csv` (Exxon: fixed by D-018)
- [x] Re-run with `predecessors.csv` and confirm Exxon, BlackRock, Bunge and APA are complete (+8 sample, +4 comparison filings, as predicted)
- [x] Decide how to treat spin-offs and mergers with no prior 10-K: first year left unscored (D-019)
- [ ] Phase 2: hand-review 20 random extractions and every flagged case
- [ ] Lock in the held-out time period
- [ ] Decide which share class to use for two-class companies (D-010)
