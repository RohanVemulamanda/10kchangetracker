# Phase 3 report: Risk Factors change scores

Completed 2026-10-25 with scorer version 1.1. Every methodology choice mentioned here is explained in [DECISIONS.md](../DECISIONS.md) (D-028 to D-032).

## 1. What we built

`python run.py score` compares each sample 10-K's Risk Factors (Item 1A) with the same company's prior-year 10-K. For each pair it:

1. **Prepares the text** (D-028). Lines are joined, so the line breaks Phase 2 left in about 6% of sections can't change a score. Sentences are found from punctuation, with care for "U.S.", "Inc." and similar. Words are lower-cased, and every number becomes "#", so "fiscal 2024" → "fiscal 2025" isn't a change.
2. **Removes the risk factor summary** (D-029). Since 2020, many companies start Item 1A with a summary that repeats their risk headings. Rules find where it ends; six hand-checked overrides cover the cases the rules get wrong. Every pair is scored twice: summary removed (the main score) and kept (a robustness check).
3. **Computes the four *Lazy Prices* similarity measures** (D-030), each from 0 (nothing in common) to 1 (identical):
   - **Cosine:** how often each word is used.
   - **Jaccard:** which distinct words appear.
   - **Minimum edit:** the fewest word changes to turn one year into the other.
   - **Simple:** a "track changes" count of words in added and removed sentences.
4. **Saves what changed:** every added and removed sentence, for the dashboard.
5. **Flags companies that switched between "we" and "the Company"** (D-031). The scores are kept as they are.
6. **Counts negative, uncertain and litigious words** (Loughran–McDonald lists) in the genuinely new and genuinely dropped sentences (D-032).

Results are in `data/processed/changes.db`. `reports/phase3_summary.md` has the numbers, and `reports/phase3_scores.csv` has every score, for Excel.

### The result

| | Count |
|---|---|
| Sample 10-Ks | 2,494 |
| **Scored** | **2,482** |
| Not scored: first-ever 10-K, nothing to compare with (D-019) | 12 |
| Errors | 0 |
| Summaries removed (sections) | 468 (8 more found but their end couldn't be, so left in) |
| Flagged `voice_switch` | 8 |

| Measure (main score) | Median | 10% most changed are below |
|---|---|---|
| Cosine | 0.998 | 0.995 |
| Jaccard | 0.896 | 0.808 |
| Minimum edit | 0.790 | 0.530 |
| Simple | 0.671 | 0.408 |

Most 10-Ks barely change from one year to the next, which is the starting point of the paper.

## 2. How we checked it was correct

1. **Tests with answers worked out by hand.** On a two-sentence example, each measure matches a calculation done on paper. Identical text scores 1, unrelated text 0. The fast edit-distance code matches the textbook version on 300 random cases. 220 automated tests in all.
2. **The D-027 promise is tested.** The same text with different line breaks gives exactly the same sentences, words and scores (tested on Vertex's real line-by-line text).
3. **Summary rules built on all 480 sections that have one.** Each rule was added for a real case and then run on every section, and every filing whose result changed was looked at. Two tempting rules were rejected because they broke other filings (Alexandria; a rule that cut 90 summaries short, Regeneron after 6 lines).
4. **Review of the full run.** Claude checked:
   - the 20 biggest and 20 smallest changes
   - 20 random pairs
   - all 69 pairs with a fallback extraction method

   For each one: where both years start and end, the summary removal, and the changed sentences. This review found the missed "Summary" headings, CVS 2021, Discover and the voice switches, which were all fixed or flagged, then everything was re-scored. Rohan skimmed the review page and saw nothing wrong, but didn't answer it card by card (see Limitations).
5. **Plausibility.** The biggest changes are real events, such as mergers (Paramount, Omnicom, Interpublic, Union Pacific), separations (Keurig Dr Pepper, Kimberly-Clark) and rewrites (GE Vernova, Occidental). The smallest are genuinely near-identical (Caterpillar FY2025 differs by one word).

### Things the checks found

These are worth knowing because each one would have looked like a result:
- **"We" vs. "the Company."** The biggest changes by cosine were mostly companies changing how they refer to themselves (BorgWarner, Deere, Applied Materials), not their risks. 8 pairs are flagged so Phase 4 can test with and without them.
- **Reordering.** A company that only reorders its risk factors gets a low minimum-edit and simple score, but cosine and Jaccard don't move. 9.4% of "added" sentences are moved ones. That's how the measures are defined, so Phase 4 should report all four, and the word counts leave moved sentences out.
- **Summaries headed just "Summary"** (JPMorgan, CVS, Amgen...) were missed by the first rule. For some companies the summary appears or disappears in one year, which would have been a fake change.
- **A company renaming itself.** JPMorgan Chase became "JPMorganChase" in FY2024, so every sentence with its name counts as changed. It's one filing; noted, not fixed.

### What changed, in words

In every year, genuinely new sentences use a little more negative and litigious language than the sentences they replaced (negative: 4.1–4.4% of words in new text against 3.9–4.3% in dropped text). Uncertainty is about the same.

## 3. What to say in an interview

> "To measure how much a 10-K changed, I compared each company's Risk Factors with the prior year's using the four similarity measures from *Lazy Prices*: cosine, Jaccard, minimum edit distance and a sentence-level 'track changes' measure. Most 10-Ks are almost identical year to year, which is the paper's starting point.
>
> The interesting part was what the top of the 'biggest change' list turned out to be. It wasn't companies disclosing new risks. It was companies switching from 'we' to 'the Company' in their writing. A purely mechanical score treats that as a huge change. I flagged those cases rather than deleting them, so the backtest can show whether they matter.
>
> I also handled a regulatory change: since 2020 the SEC asks for a risk factor summary, and the year a company adds one looks like a big change even though nothing happened. I removed summaries for the main score and kept a second score with them, so I can show that choice doesn't drive the results. Finally, I looked at the words in the new sentences: new risk language is slightly more negative and litigious than what it replaces."

## Limitations to disclose

- **The hand review wasn't done independently.** Claude checked every card on the review page. Rohan skimmed it but didn't answer card by card. Phase 2's 20-of-20 check was a fully independent human check; this one isn't.
- **The measure definitions haven't been checked against the paper's text** (no PDF in the project). In particular, how the paper scales minimum edit and simple similarity to 0–1 may differ from ours.
- **Common words are kept** ("the", "and"), as we believe the paper does. That keeps cosine in a narrow range (0.98–1.00) and makes it sensitive to the "we" vs. "the Company" switches. It still ranks filings much like the other measures (rank correlation 0.81 with Jaccard).
- **Summaries the rules don't find stay in.** Examples: Alexandria and Kenvue (the end can't be found), Synchrony (built into its layout) and Entergy (in Item 1, outside the section). All are the same every year, so they can't create a jump.
- **Small Phase 2 leftovers:** General Mills FY2023 lost the last 4 words of its section; Constellation Brands keeps a page header at the end of every year.
- **Loughran–McDonald lists are free for academic research only.** Check the license before a public dashboard (Phase 5).
