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

### D-025 Check that every sample 10-K comes from a large company (found in Phase 2)
- **Problem:** the first full extraction showed "Banzai International" under ticker PARA. PARA was Paramount Global's ticker from February 2022 (after ViacomCBS renamed) until its 2025 merger. Afterwards, SEC's current ticker file gave PARA to Banzai, a small former blank-check company, so Banzai's 10-Ks replaced Paramount's for fiscal 2021–2024.
- **Why Phase 1 missed it:** the reused-ticker check (D-009) only asks "did this company file a 10-K while the ticker was in the index?" Banzai did.
- **Fix:** PARA → Paramount Global (CIK 813828) added to `manual_cik_map.csv`. When a company no longer maps to any ticker, its filings now leave the sample.
- **New check (`python run.py check-filers`):** reads the public float from each sample 10-K's cover page (the market value of shares held by outside investors, tagged `dei:EntityPublicFloat`) and lists any under $1 billion or not tagged, in `reports/filer_size_check.csv`. S&P 500 members are worth billions; a mismatched small company stands out.
- **Expected false alarms:** a new spin-off's first 10-K often reports no float, because it wasn't trading yet on the measurement date.
- **Filer error found while building it:** Zimmer Biomet's 2021 float is tagged as millions but written in full dollars, making it $33 quadrillion. Values over $10 trillion are read without the scale.
- **Result (2026-10-25):** 10 of 2,494 sample 10-Ks were listed. The company name in every one of those filings matches the S&P 500 member for its ticker, so no other reused tickers were found.
  - 4 are new companies whose first 10-K was measured before they began trading: Constellation Energy FY2021, GE HealthCare FY2022, Smurfit Westrock FY2024, FedEx Freight FY2025.
  - 6 are large companies whose cover-page tag reads 0 or too small: Electronic Arts FY2021, Ares FY2025, Duke Energy FY2022, SolarEdge FY2022, Corteva FY2023–2024. Duke and Corteva file one 10-K for several legal entities, some of which report no float.
  - The float isn't used as data anywhere; Phase 4 market values will come from price data.

### D-026 Extraction version 1.1: fixes from the first full run
The first run (v1.0) extracted 99% of sample filings. The 39 flagged or missing ones came from 11 companies. We looked at a filing from each and fixed causes, not cases:
- **"Item 1.A." (Clorox, Rollins):** a period between number and letter. It counts only when a letter follows directly, so "Item 1. A Description..." is still Item 1.
- **"Part I. Item 1A." (Expedia):** the part number written in front of the item.
- **Bold run-in heading, "Risk Factors An investment in..." (US Bancorp EX-13):** each block now remembers its leading bold words.
- **Page range (US Bancorp):** the 10-K says Item 1A is "on pages 140 to 155" of the annual report, and the section is followed by a list of executives that no heading rule recognizes. When a 10-K gives a page range, we stop at the end of the last page.
- **Risk factors inside MD&A (Eastman 2020–2022):** Item 1A says "see Risk Factors in Item 7". Two bugs:
  - The MD&A's own contents line "Risk Factors 56" was taken as the heading. Contents lines (in a table, ending in a page number) are no longer starts.
  - The running page header "MANAGEMENT'S DISCUSSION AND ANALYSIS..." ended the section after one page. Page headers and footers can no longer end a section.
- **Headed parts (Synchrony):** no single "Risk Factors" heading. Its own cross-reference index gives Item 1A as pages 60–81 and 101–106: "Risk Factors Summary", "...Relating to Our Business" and "...Relating to Regulation". New fallback method `heading_parts` joins bold "Risk Factors ..." headed parts, each ending at its next contents entry. Used only when the other methods fail.
- **Line-by-line documents (ConocoPhillips 2020–2021):** every printed line is its own HTML element.
  - The "short leftover line" cleanup (D-021) had removed two real lines. It now only removes labels that start with a capital and don't end in punctuation, like "Parts I and II".
  - Lines are rejoined into paragraphs when the section's median line is under 80 characters.
- **Decorative lines** ("______", "* * *") are removed.
- **False overrun (ConocoPhillips):** a lowercase "properties." at the end of a list item looked like the "Properties" header. Headers must start with a capital.
- **Regression check:** re-extracting the 25 original sample filings changed only one, Wells Fargo, by 2 "words": the removed "* * *".

**Reviewed by hand and kept as is:** the `long` flags (over 50,000 words) for KKR (68,000–71,000), Ares (52,000–54,000) and Moderna 2020 (54,000). Each runs from the Item 1A header to the Item 1B header, ends on the company's real last risk factor, and has a steady length year to year. These firms really do write very long risk sections. The flag stays, so it remains visible.

### D-027 Extraction versions 1.2 and 1.3: two v1.1 regressions, older errors, and a change log
The v1.1 run extracted every sample filing (2,494 of 2,494). Checking it turned up four problems.

**Two cases v1.1 broke** (both from the "Part I. Item 1A." rule added for Expedia):
- **Colgate 2021 stopped too early (2,702 words instead of 7,978).** A sentence split by a page break left a line starting *Part II, Item 7 "Management's Discussion..."*, which was read as the Item 7 header. Fix: a title in quotation marks after the item number means a cross-reference, not a header.
- **Entergy 2020 grabbed too much (70,938 words).** Its running page header "Part I Item 1A & 1B" was read as a start. Fix: with "Part I" in front, a header must be followed by a title ("Part I. Item 1A. Risk Factors" still counts).

**One error that v1.0 had too, which no check caught:** Entergy 2020 has no "Item 1A" or "Item 1B" header, only "RISK FACTORS". The section ran on into a subsidiary's financial discussion (26,680 words in v1.0). That was only 1.75x its 2021 length, under the 3x flag. Fix: every risk-factor page is headed "Part I Item 1A & 1B", so a heading-method section now stops at the end of the last page whose running header names Item 1A (needs 2+ such headers; it can only shorten a section). Result: 16,647 words, and the first and last paragraphs match 2021's exactly.

**Honeywell 2025 grabbed too much (14,427 words instead of 8,441).** It ran past the risk factors into liquidity, accounting estimates and the executive officers list. There were two causes:
- Its contents rows put the page number first ("30 Risk Factors"), so the "next title in the contents" rule found nothing. Contents rows like that are now read.
- The next header says "...About Market **Risks**" (plural). "Quantitative and qualitative disclosure..." now matches any ending.

"Information About Our Executive Officers" (and similar) also ends a heading-method section now, but only as a whole heading.

A small cleanup: a bare number in front of a title is no longer removed unless a separator follows ("7. Management's..."), as in v1.0. v1.1 had removed any 1–2 digit number, which made "30 Risk Factors" look like a heading.

**Two new safeguards:**
- **Change log.** When a filing is extracted again and its result differs, the old and new results are saved to the `section_changes` table, and `reports/phase2_changes.csv` lists every change made by the current version. The v1.1 regressions were found by luck, in the flagged list. From now on every change is listed and can be checked.
- **Length review list.** `reports/phase2_length_changes.csv` lists sample filings that are more than 1.5x longer or shorter than the prior year. They're not flagged, since real rewrites do this (for example, the 2020 rule that added risk-factor summaries). But it's where an overrun like Entergy 2020's would show up.

**Regression check before release:** 69 local real filings were re-extracted.
- 57 (the samples, flagged and fallback sets) were compared with v1.1. Only Honeywell 2025 changed, as intended.
- All 12 Entergy and Colgate filings were compared with v1.0. Eleven match exactly. Entergy 2020 changed, as intended.
- Three of these filings were added to the real-filing tests (Honeywell 2025, Colgate 2021, Entergy 2020).

**What the v1.2 full run changed (21 filings, every one checked):**
- **Fixes we expected:** Colgate 2021, Entergy 2020 and Honeywell 2025.
- **Fixes we didn't know we needed:**
  - Honeywell 2021–2024 had the same contents layout. Every year had run about 12,000 words into the financial discussion; they're now 6,000–7,400, in line with 2020's 5,961.
  - Xylem 2022, International Paper 2025 and GE Vernova 2024 had stopped early at a quoted cross-reference, like Colgate.
  - US Bancorp 2025 had run to the end of the document, including the list of executives. It now stops at "Managing Committee", the next contents entry, as 2024 does (2024's text is unchanged).
- **The section header line no longer counted as text:** Entergy 2021–2022 and ResMed 2020–2025 each lost 4 words. In v1.1 a page header had become the start, so the real header line ("ITEM 1A RISK FACTORS") was included. All eight now match v1.0 exactly.
- **One new error, fixed in v1.3:** Morgan Stanley 2025 fell from 10,574 to 5,905 words. The broader "Quantitative and qualitative disclosure..." end title matched a quoted cross-reference split by a page break. A title in quotation marks can no longer end a section. All six Morgan Stanley years now match v1.0.
- **GE Vernova:** 2024 (25,920 words, pages 11–31, its first 10-K after the spin-off) and 2025 (10,249 words, pages 11–20) are both right. The 2025 risk factors were rewritten and shortened.

**The 27 year-to-year length changes over 1.5x, every one checked:**
- For each pair we compared the first and last 300 characters of both years. All but Morgan Stanley start right after the Item 1A header and stop at the Item 1B header, ending on a real last risk factor.
- Many have a visible reason in the text itself, such as a deal that year: Interpublic (the merger), Paramount (Skydance), Exelon (the separation plan), Waters (the BDS acquisition), Keurig Dr Pepper (the planned separation) and Healthpeak (the "Combined Company"). Others look like rewrites (Vertex, Occidental, KKR, Starbucks).
- 26 are real changes in the text. The other, Morgan Stanley 2025, was the v1.2 error above.

**Known issue, not fixed:** in about 6% of sections, some sentences are split across lines, because the 10-K puts each printed line in its own HTML element and the lines are too long for the v1.1 rejoining rule (Vertex 2025, for example). Word counts and the words themselves are unaffected. **Decision:** the saved text keeps the 10-K's line breaks. Phase 3 will split text into sentences in a way that ignores line breaks, so this can't affect change scores. (The other option, a new rejoining rule now, could wrongly join headings to paragraphs and would need another run and review.)

---

## Phase 3: change scores

Choices made 2026-10-25. Rohan approved the recommended option for each question in the Phase 3 plan.

### D-028 Text preparation: sentences and words
- **Line breaks are ignored.** All lines of a section are joined into one stream of text, and sentences are found from punctuation only. This keeps the D-027 promise: in the 6% of sections where a sentence is split across lines, the split can't change any score. A test checks that Vertex's line-by-line text gives exactly the same sentences and words as the same text written as one paragraph.
- **Sentence ends:** `.` `!` or `?` followed by a space and a capital letter or digit. Not after a common abbreviation ("Inc.", "No.", "U.S.") or an initial ("J. Smith"), unless the next word is a common sentence opener ("...outside the U.S. We face..."). In our data, "U.S." comes before a capitalised word about 13,000 times. Most of these are names ("U.S. Government" 1,724, "U.S. Department" 1,269), which is why a plain "period + capital" rule isn't enough.
- **Accepted cost:** a heading without a final period joins the sentence after it ("Risks Related to Our Business Our success depends on..."). This only affects the sentence-level measure, and it happens the same way every year. The other option, treating a line break as a sentence end when the line has no final punctuation, would split Vertex's sentences in the middle, which is the problem D-027 is about.
- **Hyphen at a line end:** joined without a space ("third-\nparty" → "third-party"). All 206 cases in the data are real hyphenated words.
- **Words:** lower case, punctuation dropped, "company's" and "third-party" kept as one word.
- **Numbers become one placeholder ("#").** Otherwise every 10-K looks a little changed just because "fiscal 2024" became "fiscal 2025". A new sentence containing a number still counts as new. The cost is that a changed number in an otherwise identical sentence isn't counted.
- **No stop-word removal and no stemming** ("risks" stays "risks"). There are fewer choices to defend, and as far as we know this matches the paper. **Not yet checked against the paper's text** (no PDF in the project); see the open items.

### D-029 Risk factor summaries: removed for the main score, kept for a robustness score
- **Why:** since 2020 the SEC asks for a summary of the risk factors (at most 2 pages) when they run over 15 pages. Many companies put it at the top of Item 1A. It repeats the risk headings, so that text would count twice. The year a company adds one, the section looks changed although nothing in the business did. Every pair is scored twice: the **main score with summaries removed**, and a **robustness score with them kept**, so Phase 4 can show the choice doesn't drive the results.
- **How it's found** (`src/tracker/risk_summary.py`): the start is a short heading containing "summary" and "risk", or a bare "Summary" heading, in the first 1,500 words. The end is the first of:
  - the full section starting over with one of the summary's first 3 lines or its first category heading (Micron, Crown Castle, Gallagher);
  - "For a more complete discussion..." / "the risks summarized above" (the summary's last line);
  - "You should carefully consider..." (the full section's introduction);
  - a bare "Risk Factors" title;
  - a "Risks related to..." heading that never appears again, in a summary that had no category headings of its own (Autodesk).

  Lines are compared ignoring case, punctuation and plural endings. A long paragraph (over 100 words) just before the end is the full section's introduction and is kept.
- **How the rules were built:** a summary heading appears in 431 of the 3,046 sections (11% of FY2020 sections, about 19% by FY2024–2025, so not a one-time 2020–2021 effect). Each rule was added for a real case, then run on all 431, and every filing whose result changed was looked at. Rules we tried and rejected:
  - "Any short line repeated from the summary." Alexandria repeats a closing sentence after each group, so this cut its summary short.
  - "Any category heading that never appears again." This cut 90 summaries short, Regeneron after 6 lines, because many companies word their category headings differently in the summary and in the full section.
- **Result (version 1.1, all 3,046 sections):** a summary heading appears in 480. The rules find the end for 469; overrides set it for 6 (3 of them where the rules found none). For the other 8 (Alexandria FY2020–2025, Kenvue FY2023–2024) the summary and the full section use different headings, so nothing is removed. Both companies have the summary every year, so it can't create a first-appearance jump; they are listed for review.
- **Hand-checked overrides:** `data/reference/summary_overrides.csv` gives the whole first line after the summary, with evidence, for filings the rules get wrong and no general rule fixes without breaking others. An override that isn't found stops the run.
  - Gallagher FY2023 starts its full section with a reworded first risk, so the rules stop about 530 words late. FY2022 has the same layout and is one line off.
  - CVS FY2021 starts its full section with a heading that isn't in its summary ("Risks Related to COVID-19"), so the rules would remove about 1,000 words of real COVID-19 risk factors.
  - Discover FY2020–2022: the full section starts at a heading no rule recognises, so nothing would be removed. FY2023–2024 are found by the rules, so without the overrides the FY2023 score would show a fake change.
  - The match must be the whole line: Discover's summary bullet "The COVID-19 Pandemic: The pandemic has..." starts with the same words as its heading "The COVID-19 Pandemic".
- **Update, scorer version 1.1 (found in the review of the first full run):** 69 sections have a summary under a bare "Summary" heading (JPMorgan, CVS, Amgen, BNY, ICE, Viatris, Northern Trust, PNC, Dentsply, Discover), which the first rule skipped because it required "risk" in the heading. Most companies have it every year, but for some it appears or disappears (Northern Trust from FY2022, PNC until FY2022, Dentsply until FY2023), which would show as a fake change. Every newly found summary was checked: the existing end rules handle all but CVS FY2021 and Discover FY2020–2022, which got overrides. Headings like "Overview" (Alexandria, Prudential, Digital Realty) are not treated as summaries.
- **Not removed, by design:** Synchrony's summary is one of the "Risk Factors ..." parts that `heading_parts` joins (D-026), with no separate summary heading, and Entergy's summary is in Item 1, outside the section. Both are the same every year.
- **Known small error:** in some filings the full section's short introduction or its first category heading is removed along with the summary (one line). It happens the same way every year for a company, so its effect on change scores is small.
- **Could affect results by:** a summary we don't detect (no "summary" heading, or one outside the first 1,500 words) stays in. If a company adds one, its main score shows a fake change in that year. The robustness score shows how much this matters overall.

### D-030 Four similarity measures
- **Chose:** all four measures from *Lazy Prices*, each from 0 (nothing in common) to 1 (identical), with change = 1 − similarity. Cosine is the main measure; Phase 4 checks whether results hold on all four. Code: `src/tracker/similarity.py`.
  - **Cosine:** cosine of the angle between the two word-count vectors.
  - **Jaccard:** distinct words in both years ÷ distinct words in either.
  - **Minimum edit:** 1 − (fewest word insertions, deletions and substitutions to turn last year's words into this year's) ÷ (words in the longer year). Dividing by the longer length keeps it between 0 and 1.
  - **Simple:** the two years' sentences are lined up in order, like Word's "track changes". 1 − (words in added and removed sentences) ÷ (words in both years). A sentence whose only change is a number or punctuation counts as kept; a sentence that moved counts as removed and added.
- **Considered:** cosine and Jaccard only. Less code, but nothing to check the main result against.
- **How it was checked:** tests with answers worked out by hand on a two-sentence example, identical text (all 1) and unrelated text (all 0). The fast edit-distance code matches the textbook version on 300 random cases. Timing: 0.3–0.6 seconds for a typical pair, 16 seconds for KKR (70,000 words).
- **Note on the exact formulas:** these follow our understanding of the paper. In particular, how the paper scales minimum edit and simple similarity to 0–1 hasn't been checked against its text yet (open item).
- **Early warning to check on the full run:** with common words kept, cosine is 0.999 for Apple and Micron FY2024 and 1.000 for KKR, because counts of "the", "and", "of" dominate the vectors. If cosine barely varies across companies, it may hardly separate them, and this choice (D-028) should be revisited.
- **Result of the full run (2026-10-25):** cosine does sit in a narrow range (1st percentile 0.980, median 0.998), but it ranks filings much like the other measures (rank correlation 0.81 with Jaccard, 0.68 with minimum edit). Phase 4 sorts filings by rank, so the narrow range alone isn't a problem. Kept as is. Its sensitivity to common words does show up in one way, the voice switches in D-031.

- **Found in the review: reordering.** Minimum edit and simple compare the two years in order; cosine and Jaccard ignore order. So a company that reorders its risk factors gets a very low minimum-edit score while Jaccard stays high. KLA FY2021: Jaccard 0.934, minimum edit 0.138, and 189 of its 266 "added" sentences are exact copies of "removed" ones. Across all pairs, 9.4% of added sentences are moves, not new text. This is how the measures are defined (and, as far as we know, how the paper's work too), so it isn't changed. It is why the measures sometimes disagree, and Phase 4 should report results for each. The "what changed" step must count only genuinely new sentences, not moved ones.

- **Hand review (2026-10-25):** the review page (`python run.py review-scores --seed 2026`) has the 20 biggest and 20 smallest changes, 20 random pairs, and all 69 pairs with a fallback-method extraction. Claude checked every card: where each year starts and ends, the summary removal, and the changed sentences. No scoring errors were found. The findings are the summary and reordering notes above, and two small Phase 2 leftovers (known limitations). Rohan skimmed the page and saw nothing wrong, but didn't answer card by card. **So unlike Phase 2's 20-of-20 check, this review wasn't done independently by a person.**

### D-031 Companies that switch between "we" and "the Company": flagged, not changed
- **Found in the full run:** the biggest changes by cosine were mostly companies changing how they refer to themselves, not their risks. BorgWarner switched to "the Company... its" in FY2021 and back to "we... our" in FY2022; Deere, Applied Materials, Dentsply, IDEX, APA and Williams did similar. Every sentence about the company is reworded, so the pair looks heavily changed.
- **Considered:**
  - (A) Keep as is: the edits are real, and as far as we know the paper would count them.
  - (B) Treat all self-references ("we", "our", "the Company", "Deere's"...) as one word: removes the effect, but needs each company's name forms and an ambiguous word like "its", which risks new errors and moves away from the paper.
  - (C) Keep the scores and flag these pairs.
- **Chose (C), Rohan's decision.** Scores aren't changed. A `voice_switch` flag in the `changes` table lets Phase 4 run results with and without these pairs. It is the same "flag, don't drop" approach as Phase 2.
- **Rule:** one year uses first-person words ("we", "our", "us", "ours") for under 1.5% of all words, the other year for 3% or more. In the data there is a clean gap. The 8 switches move from about 0–1.2% to 4–6%. The next-largest shifts (Paramount, Interpublic, Union Pacific, Kimberly-Clark, mostly mergers) stay above 1.5% in both years and aren't flagged; they are real content changes.
  - A first rough rule ("the share moved by more than 1 point") caught 23 pairs, including those mergers. That's why the rule looks at whether one year almost never uses "we".
- **Result:** 8 of 2,482 pairs flagged; all 8 are among the 15 biggest changes by cosine. Without them, the top of the list is mergers, spin-offs and rewrites (Paramount 2024, GE Vernova 2025, Union Pacific 2025, Occidental 2025, Kimberly-Clark 2025, Omnicom 2024).
- **Not caught:** a company renaming itself. JPMorgan Chase became "JPMorganChase" in FY2024, so every sentence with the name counts as changed (cosine 0.931, simple 0.115). It is one filing; noted here rather than handled with another rule.

### D-032 What kind of language changed: Loughran–McDonald word lists
- **Chose:** count words from three Loughran–McDonald lists (negative, uncertainty, litigious) in each pair's **genuinely new** sentences (added, and not just moved from elsewhere) and **genuinely dropped** ones. Stored in the `change_words` table. Code: `src/tracker/wordlists.py`.
- **Why these lists:** they were built for 10-Ks; general-purpose sentiment lists misread finance words ("liability", "tax" are neutral in a 10-K). They're the standard in this literature, including the follow-up work on *Lazy Prices*.
- **Source, pinned:** the Master Dictionary, March 2026 release (10-Ks 1993–2025), from https://sraf.nd.edu/loughranmcdonald-master-dictionary/, SHA-256 in `config/settings.yaml`. The run refuses a different file. It's downloaded by hand into `data/reference/sources/lm/` (not committed). Without the file, scoring still runs and only this step is skipped.
- **License:** free for academic research; commercial use needs a license from the authors. **This matters for Phase 5:** a public dashboard could count as commercial use.
- **Reading the file:** each category column holds the year a word was added, or minus the year it was removed ("-2020"). Only words with a value above zero count. That leaves 2,345 negative, 297 uncertainty and 903 litigious words; 10 negative and 2 litigious words removed by the authors are excluded.
- **Matching:** the dictionary has no hyphens or apostrophes, so "third-party" counts as "third" and "party", and "company's" as "company".
- **Moved sentences are excluded** (D-030 note on reordering). Otherwise a company that reorders its risk factors would show lots of "new" negative words.
- **First result (all years):** new text is a little more negative and litigious than the text it replaces, in every year. Negative: 4.08–4.43% of words in new sentences, against 3.94–4.25% in dropped ones. Uncertainty is about the same (around 3%). Phase 4 can test whether this matters for returns.
- **Not done:** the other lists (positive, modal, constraining). Positive words are known to be unreliable in 10-Ks (often negated: "not profitable"). The others can be added the same way if Phase 4 needs them.

---

## Phase 4: backtest

Choices made 2026-10-25, **before any stock returns were downloaded or looked at.** Rohan approved the recommended option for each question in the Phase 4 plan. This section is the test design written down in advance. Any later change to it must be recorded here as a change, with the reason, and the results under the original design must still be reported.

### D-033 Test design, fixed in advance
- **Main measure:** cosine similarity, `main` version (risk summaries removed), the paper's main measure.
- **When a score can be used:** from the first trading day of the month after the month the 10-K was accepted (the paper's rule). A filing accepted after the close on the last day of a month is still public before the next month opens, so there's no look-ahead. A score is used for 12 months, or until the company's next score replaces it.
- **Who is in the portfolios each month:** every company with a usable score. Companies stay in for those 12 months even if they leave the S&P 500, because dropping companies that fall out of the index would remove exactly the stocks that did badly. A company leaves when it's delisted, with its final (delisting) return included.
- **Portfolios:** each month, sort companies by cosine similarity into 5 equal groups (quintiles). Q1 = lowest similarity ("changers"), Q5 = highest ("non-changers"). Equal-weighted. Hold for one month, then re-sort.
- **The main number:** the monthly return of Q5 − Q1 (buy non-changers, sell changers), adjusted for risk with the Fama–French 5 factors plus momentum (the alpha), with Newey–West standard errors (3 lags). Shown alongside: the raw return, and the market-only (CAPM) and Fama–French 3-factor alphas.
- **Second test:** each month, regress every stock's return on its similarity rank (scaled 0 to 1), controlling for company size and past 12-month return (Fama–MacBeth). Book-to-market is left out unless we get accounting data (WRDS).
- **Periods:**
  - **Main test: portfolio months March 2022 – February 2026 (48 months).** March 2022 is the first month most companies have a score (438; about 494 from August 2022).
  - **Hold-out: March 2026 to the latest complete month.** March 2026 is when nearly all fiscal-2025 scores take effect (450 companies). It's run once, only after the main results are final, and reported whatever it shows.
  - **Why split by calendar month, not fiscal year:** about 88 companies with June–December year-ends file their fiscal-2025 10-Ks from September 2025 to February 2026, so their scores enter inside the main period. What has to stay untouched is the hold-out *returns*, which a calendar split guarantees.
  - **The hold-out is short:** about 7 months as of October 2026. It can confirm the direction of the result, not establish it on its own.
- **Robustness checks (all reported, whatever they show):**
  - the other three measures (Jaccard, minimum edit, simple)
  - the `with_summary` version
  - without the 8 `voice_switch` pairs (D-031)
  - value-weighted (by market value at the start of each month)
  - without financial companies (SIC codes 6000–6999, from each filing, D-015)
  - "next trading day after acceptance" timing (D-008) instead of the next month
- **How we'll read the main result:** with 48 months, a long-short spread with a typical volatility of 1.5–2.5% a month has a standard error of roughly 0.2–0.35% a month. So only an alpha of about 0.45–0.7% a month or more would be clearly different from zero (t > 2). Agreed in advance:
  - alpha > 0 with t > 2: **consistent with *Lazy Prices*** on recent S&P 500 data;
  - the 95% confidence interval includes zero: **inconclusive.** It doesn't show the effect is gone (known limitations 2 and 3);
  - the interval's upper end is below 0.25% a month: **evidence against a meaningful effect** in this sample. The 0.25% cut-off is our choice of the smallest economically interesting effect (3% a year); it's not from the paper.
- **Not decided yet:** the price data source (D-034), which depends on whether Rohan has WRDS access.

### D-034 Stock prices: waiting for WRDS
- **Plan:** CRSP monthly stock files through WRDS. They are the research standard, include delisting returns (the final return when a company is acquired or goes bankrupt), and are the data the paper used. Rohan requested WRDS access on 2026-10-25; approval takes a few days.
- **If access is refused:** the choice is between a paid end-of-day data service that keeps delisted stocks, and free Yahoo data with delisted companies' final returns filled in by hand (about 60 sample companies were acquired or delisted). Rohan decides then.
- **Code doesn't depend on the source:** the portfolio code (`src/tracker/portfolios.py`) takes a plain table of company, month, total return and starting market value, built from whichever source is used.

### D-035 Risk factors: Kenneth French data library
- **Chose:** the Fama–French 5 factors (2x3) and the momentum factor, monthly, from Kenneth French's free data library. They're the standard factors and are built from CRSP, so they match the main price source.
- **Pinned:** the files built from the August 2026 CRSP database (monthly data July 1963 – August 2026), SHA-256 in `config/settings.yaml`. French revises past values slightly with each update, so pinning keeps results reproducible. The files are downloaded by hand into `data/reference/sources/ff/` (not committed).
- **Effect on the hold-out:** with factors through August 2026, the hold-out has 6 months (March–August 2026) until the next update. These files contain only market-wide factor returns, nothing about our portfolios, so having them before the main results doesn't affect the "decided in advance" rule (D-033).
- **Statistics code** (`src/tracker/backtest_stats.py`) is written with numpy only: least-squares alphas with Newey–West standard errors (3 lags) and Fama–MacBeth regressions. It's checked against hand calculations in the tests.

---

## Phase 5: live tool and dashboard

Choices made 2026-10-25. Rohan approved the recommended option for each question in the Phase 5 plan: a shareable website (GitHub Pages), public but without the Loughran–McDonald counts, updates run by hand, and today's S&P 500 list from Wikipedia.

### D-036 Live updates: new filings never change the research sample
- **Command:** `python run.py update`. It reads today's S&P 500 list from Wikipedia, fetches each member's filing list fresh from SEC, adds new 10-Ks, then downloads, extracts and scores them with exactly the Phase 1–3 rules.
- **Today's list:** Wikipedia's table, which includes each company's SEC ID (CIK), so no ticker matching is needed. A list with fewer than 490 or more than 520 rows, or more than 5 rows without a CIK, is refused (the page layout may have changed). Each day's list is kept in the `live_members` table and as a CSV in `data/reference/sources/live/`.
- **Which filings:** the Phase 1 rules (`select_filings`: originals only, one per period, fiscal-year labels, prior-year link). Every current member counts as a member on every date, which is only right for today. That's fine because live mode only adds filings not already stored, and those are the newest ones. A company new to the index brings its 10-Ks from fiscal 2021 on, so it has a history on the dashboard.
- **Kept apart from the research:** new rows get role `live` (scored) or `live_comparison` (prior year only). Rows with role `sample` or `comparison` are never changed, and Phase 3's report and Phase 4 read only `sample`. So the research results, including the Phase 4 test fixed in advance, can't move as live data grows.
- **Ticker moves (D-018):** the live code uses `predecessors.csv` like Phase 1, so a company that moved to a new SEC ID keeps its prior-year filing.

### D-037 New filings are checked before they reach the dashboard
- A live filing goes on `reports/live_review.csv`, and stays off the dashboard, if:
  - its extraction isn't `ok` (flagged, not found or an error);
  - it couldn't be scored;
  - it's a voice switch (D-031);
  - its cosine or Jaccard similarity is below the research sample's 1st percentile. Changes that extreme are where extraction errors showed up in Phases 2–3.
- **After checking one by hand,** add it to `data/reference/live_approved.csv` (accession number and a note); it then appears on the dashboard. A filing with real problems stays off until the rules are fixed.
- **Why:** Phase 2's rules were tested on the research sample. A new layout can break them, and a broken extraction looks exactly like a big change: the thing the dashboard highlights.
- **First live update (2026-10-25):** 174 new filings from 82 companies, mostly companies that joined the index after the research period (with their history from fiscal 2021) and fiscal 2026 10-Ks. The research sample was checked before and after: the same counts, and the same fingerprint of all 4,988 research scores. 18 went on the review list:
  - **Ares and KKR (5):** the known "long" flag (D-026). Approved.
  - **Flex 2025, Ciena 2025, EchoStar 2023:** extreme changes, all real (a heavy rewrite, a cut to a third, and the DISH merger). The boundaries were checked; approved.
  - **10 first-ever 10-Ks:** 8 are real IPOs, spin-offs or mergers (Coinbase, Robinhood, Reddit, AppLovin, Sandisk, TKO, Apollo, CRH, which used Form 20-F before). Approved as unscored.
  - **Marvell (2021) and Ferguson (2024)** were moves to a new legal parent (Bermuda → Delaware and Jersey → Delaware), the D-018 case. Both were added to `predecessors.csv` with evidence.
- **Relinking:** live mode may update the prior-year link of a stored **live** row (never a research row), so a company added to `predecessors.csv` later gets its comparison. That's how Marvell and Ferguson get scored.

### D-038 The dashboard: a static website
- **Chose (Rohan's decision):** a static website built by `python run.py build-site` into `site/`, to be hosted on GitHub Pages: free, with no server to keep running, and shareable by link. The alternative, a Streamlit app, would only run on Rohan's Mac.
- **What it shows:**
  - **"Biggest rewrites" of the latest filing season,** ranked by cosine similarity. `voice_switch` filings (D-031) are left out of the ranking and labelled.
  - **One page per company:** each year's change as a rank ("changed more than X% of S&P 500 10-Ks from fiscal 2021–2025"), the four scores, and the new and dropped sentences, with moved sentences left out (D-030). Links go to both filings on EDGAR.
  - **A "how to read this" note,** and a backtest section marked pending until Phase 4 is done.
- **Why a rank, not the raw score:** cosine sits between 0.98 and 1.00 for nearly every filing (D-030), and "0.9847" means nothing to a reader. The rank is computed against the research sample only, so it doesn't drift as live filings arrive.
- **Not published:** the Loughran–McDonald counts (free for academic research only, D-032). Live filings on the review list (D-037) are held back until approved.
- **Built safely:** no outside libraries; all text from filings is inserted as plain text, never as HTML, so nothing in a 10-K can run as code on the page. Data is split into one file per company (loaded when clicked), so the page stays fast.
- **New, dropped and edited sentences:** 62% of "new" sentences turned out to be light edits of a dropped one. A new and a dropped sentence sharing at least half their distinct words are shown as one **edited** sentence, with the changed words marked (best match first, each sentence used once). The count is always shown; the first 15 edits are listed. "New risk language" and "Dropped" list everything without a close match. This also cut the site from 144 MB to 60 MB (largest company file 0.8 MB).
- **Design (redone 2026-10-25 at Rohan's request: "more layered, nicer, with animations"):**
  - a frosted top bar, a hero with slowly drifting coloured light, and glass-style cards with depth;
  - count-up stats, a podium for the top 3 with animated rank rings, and a list showing how much each section grew or shrank;
  - a company chart that draws itself, with hover tooltips; a rank gauge; tabs for new, dropped and edited sentences.
  - Every animation switches off for visitors whose system asks to reduce motion, and both light and dark themes are supported.
  - The page now loads one font (Inter) from Google Fonts, with a system fallback. That's the only outside request.
  - Current members show Wikipedia's company name ("JPMorgan Chase"); former members keep SEC's name, shown in normal case.
- **Publishing:** the built site goes on a separate `gh-pages` branch, not `main`. **Nothing is published until Rohan has looked at it locally and says so.**

---

## Known limitations (to disclose)

0. **(Phase 2, found in the Phase 3 review)** Constellation Brands' sections end with a leftover page header ("PART I OTHER KEY INFORMATION Table of Contents") that the D-021 cleaning missed. It's in every year, so it barely affects change scores.
0. **(Phase 2, found in the Phase 3 review)** General Mills FY2023's extraction stops 4 words early. The section's last sentence was split by a line break, leaving a line starting "Item 8 of this report.", which was read as the next section's header. It's the last sentence, so nothing else is lost.

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
- [x] PARA fix re-run (sample 2,495 -> 2,494: Banzai's 4 years out, Paramount's 3 in) and filer-size check reviewed
- [x] Phase 2: re-run with extraction v1.1 (2,494 of 2,494 sample filings extracted; problems fixed in v1.2, D-027)
- [x] Phase 2: re-run with extraction v1.2 and review every change in `reports/phase2_changes.csv` (21 changes; one error, fixed in v1.3)
- [x] Phase 2: review `reports/phase2_length_changes.csv` (27 cases; 26 real, Morgan Stanley fixed in v1.3)
- [x] Phase 2: re-run with v1.3; exactly one change, as predicted (Morgan Stanley 2025, back to 10,574 words)
- [x] Phase 2: hand-review 20 random extractions (seed 4689: 20 of 20 correct on start, end and cleanliness) and every remaining flagged case (5 `long`, all real)
- [x] Phase 3: sentence splitting must ignore line breaks (D-027 known issue): done, D-028
- [x] Phase 3: decide whether to remove risk factor summaries: removed for the main score, kept for a robustness score (D-029)
- [ ] Phase 3: check the similarity definitions and text preparation against the *Lazy Prices* paper itself (no PDF in the project yet)
- [ ] Phase 5: Loughran–McDonald lists are free for academic research only; check the license before any public or commercial dashboard (D-032)
- [ ] Phase 4: price data must follow ticker changes (e.g. Equity Residential became Vivmark Residential after its 2026 merger with AvalonBay; the ticker is expected to change from EQR)
- [x] Lock in the held-out time period: portfolio months from March 2026 (D-033)
- [ ] Decide which share class to use for two-class companies (D-010)
