# Phase 2 report: Risk Factors (Item 1A) extraction

Completed 2026-10-25 with extractor version 1.3. Every methodology choice mentioned here is explained in [DECISIONS.md](../DECISIONS.md) (D-020 to D-027).

## 1. What we built

`python run.py extract` takes every downloaded 10-K and pulls out Item 1A, Risk Factors. For each filing it:

1. **Turns the HTML into paragraphs.** Text split across HTML tags is joined back together. Hidden text and the XBRL header are dropped. Each paragraph remembers if it was bold, italic, or part of a table.
2. **Finds the section.** It tries several methods in order and records which one worked (D-020):
   - `item`: from the "Item 1A" header to the next item header (Item 1B, 1C or 2). This is how most 10-Ks are laid out.
   - `heading`: from a "Risk Factors" heading to the next section title. This is for 10-Ks laid out like an annual report (GE, Citigroup, Honeywell).
   - `heading_exhibit13`: when Item 1A only says "see the Annual Report", it looks in the EX-13 exhibit (Wells Fargo, US Bancorp, BNY).
   - `heading_parts`: risk factors split into several headed parts (Synchrony).
3. **Cleans it.** It removes page numbers, repeating page headers and footers, "Table of Contents" links, and decorative lines (D-021).
4. **Saves two versions** (D-022): a display version with the original formatting, and a scoring version for Phase 3 (plain text, no data tables).
5. **Runs quality checks** (D-023):
   - It flags sections that are too short, too long, contain a later item's header, or are 3x longer or shorter than the prior year.
   - It lists every 1.5x year-to-year change for review.
   - It logs every filing whose result changes between code versions (D-027).

### The result

| | Count |
|---|---|
| Sample 10-Ks (the ones that get scored) | 2,494 |
| **Sample 10-Ks with Risk Factors extracted** | **2,494 (100%)** |
| All downloaded 10-Ks (sample + prior-year comparisons) | 3,046, all extracted |
| Found by `item` / `heading` / `heading_exhibit13` / `heading_parts` | 2,958 / 64 / 18 / 6 |
| Length | median about 10,400 words; 10th–90th percentile about 5,000–18,500 |
| Flagged | 5, all `long` (over 50,000 words): KKR, Ares, Moderna. Checked by hand; their risk sections really are that long |

## 2. How we checked it was correct

1. **Real 10-K tests.** Nine real 10-Ks, one for each layout we handle, are saved in the tests. For each one, the first and last sentence were checked by hand against the filing. 152 automated tests in all; they run without contacting SEC.
2. **Every flagged filing was looked at.** The first full run flagged or missed 39 filings from 11 companies. We fixed the cause in each case, not just the case itself (D-026).
3. **Every fallback-method result was checked.** That's the 88 filings not found by `item`. We read a filing from each company and found one error, Honeywell 2025 (D-027).
4. **Change log.** Before each new code version, we re-extracted 69 real filings saved locally and compared the results. After each full run, we checked every filing whose result changed:
   - Version 1.2 changed 21. All were checked. 20 were fixes, and one was a new error, fixed in 1.3.
   - Version 1.3 changed exactly the one filing we predicted.
5. **Big year-to-year changes.** All 26 sample filings that are more than 1.5x longer or shorter than the prior year were checked. Both years start right after the Item 1A header and stop at the next section. The changes are real: often a merger, spin-off or rewrite that year.
6. **Hand review.** 20 random sample filings (`python run.py review-extractions --seed 4689`): **20 of 20 correct** on start, end and cleanliness.
7. **Company-size check.** A check of each 10-K's cover page against S&P 500 company size caught one ticker linked to the wrong company in Phase 1 (PARA, D-025).

### Errors the checks caught

These are worth knowing because no single rule would have found them:
- **Honeywell 2021–2025.** Every year ran about 12,000 words into the financial discussion, nearly twice the real length. Nothing was flagged, because each year was wrong in the same way. The fallback review found it.
- **Entergy 2020** had been wrong since the first version (26,680 words instead of 16,647). It was only 1.75x the next year, under the 3x flag. That's why the 1.5x review list exists.
- **Quoted cross-references.** A sentence split by a page break left a line starting *Item 7 "Management's Discussion..."*, which looked like a header. This cut Colgate, Xylem, International Paper and GE Vernova short.
- **A ticker reused by a different company.** After Paramount's 2025 merger, its old ticker PARA was given to Banzai, so Banzai's 10-Ks had replaced Paramount's.

## 3. What to say in an interview

> "Next I extracted the Risk Factors section from all 3,000 10-Ks. Companies format these very differently. Most use a standard 'Item 1A' header, but some lay the 10-K out like an annual report or put the risk factors in an exhibit. So I built several methods, tried in order, and recorded which one worked for each filing. All 2,494 sample filings were extracted.
>
> The interesting part was checking it. I flagged sections that were too short, too long, or changed a lot from the prior year. I hand-checked 20 random extractions, and all 20 were right. I also logged every result that changed whenever I changed the code. That log caught a fix that broke other filings, and it found errors that had been there from the start. For example, Honeywell's section was nearly twice its real length in all five years. A length check can't catch that, because the company is consistent with itself. That matters because Phase 3 measures year-to-year change, so an extraction error would show up as a fake change in the company's language."

## Limitations to disclose

- **Split lines.** In about 6% of sections, sentences are split across lines, because the 10-K puts each printed line in its own HTML element. The words are all there. Phase 3 will split text into sentences in a way that ignores line breaks (D-027).
- **Risk factor summaries.** Since a 2020 SEC rule, many companies start Item 1A with a summary of their risk factors, and they added it in their FY2020 or FY2021 10-K. The summary is included in our text. In Phase 3, the year a summary first appears will look like a big change. We need to decide whether to remove summaries.
- **Rule-based extraction can still miss rare layouts.** The checks above found every error we know of. The hand review was 20 filings; it can show the error rate is low, not that it's zero.
- **Only Item 1A so far.** The brief also lists Item 7 (MD&A) and Item 3 (Legal Proceedings) for later.
