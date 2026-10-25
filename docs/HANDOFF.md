# Picking up this project in a new session

Read this first. Then read README.md and DECISIONS.md.

## Where things stand (2026-10-25)

- **Phase 0–1 (data collection): done.** 2,494 sample 10-Ks (fiscal 2021–2025, S&P 500 members on the filing date) plus 552 prior-year comparisons, all downloaded. See [phase1_report.md](phase1_report.md).
- **Phase 2 (Item 1A extraction): done.** Extractor version 1.3 extracts all 2,494 sample filings. See [phase2_report.md](phase2_report.md).
- **Phase 3 (change scores): done.** Scorer version 1.1 scores 2,482 of 2,494 sample 10-Ks on four similarity measures, with risk summaries removed (main) and kept (robustness), plus Loughran–McDonald word counts. See [phase3_report.md](phase3_report.md).
- **Phase 4 (backtest): paused, waiting for WRDS access** (Rohan requested it 2026-10-25). Done so far:
  - the test design, fixed in advance and committed before any returns were seen (D-033);
  - pinned Fama–French factors (D-035);
  - the portfolio and statistics code, tested on made-up data.

  **When the WRDS file arrives:**
  1. Look at the real CRSP tables first. The new "CIZ" format (`crsp.msf_v2`) may be needed, because the old `crsp.msf` may have stopped at the end of 2024.
  2. Link SEC company IDs to CRSP stock IDs through Compustat (`comp.company.cik` → `crsp.ccmxpf_lnkhist`).
  3. Build the returns table described in `src/tracker/portfolios.py`, including delisting returns.
  4. Run the main test exactly as D-033 says, then the robustness checks, then the hold-out once.
  5. Report everything, whatever it shows.

  If WRDS is refused, Rohan picks between a paid source and Yahoo (D-034).
- **Phase 5 (live tool and dashboard): next.** Being planned while Phase 4 waits for data.

## How Rohan works

- He is a finance student, new to programming. Use plain words and short sentences. Explain each step.
- The rules from his project brief:
  - Before each phase, explain the plan, point out tricky parts, and ask questions.
  - When there's a real choice, show the options and trade-offs, and let him decide.
  - Keep code simple, modular and well commented. Avoid clever shortcuts.
  - After each phase, give a summary of what was built, how it was checked, and a short interview explanation.
  - Always flag anything that could make the results wrong.
  - Update DECISIONS.md and the README as you go. Commit after each working step.
  - Store data in SQLite or Parquet, not loose CSVs.
  - Accuracy and clear reasoning matter more than speed.
- He runs the pipeline on his Mac (`~/10kchangetracker`, Python 3.9 virtual environment). The "NotOpenSSLWarning" it prints is harmless.

## Things to know before Phase 4

- Scores are in `data/processed/changes.db`:
  - `changes`: one row per sample filing and version (`main` or `with_summary`), with `sim_cosine`, `sim_jaccard`, `sim_min_edit`, `sim_simple` (1 = identical) and `flags`.
  - `changed_sentences`: the added and removed sentences.
  - `change_words`: word-list counts in new and dropped text.
  - `risk_summaries`: what summary removal did.
- Use the `main` version for the main results. Use `with_summary` and each of the four measures as robustness checks; they disagree when a company only reorders its risk factors (D-030).
- 8 pairs are flagged `voice_switch` (D-031): run the results with and without them.
- Rohan skimmed the Phase 3 review page but didn't answer it card by card (D-030). Say so when presenting results.
- Open items at the bottom of DECISIONS.md. For Phase 4:
  - Lock in the held-out period before looking at any returns (D-003).
  - Free price data drops delisted stocks (known limitation 1).
  - Price data must follow ticker changes (EQR → Vivmark), and two share classes need one choice (D-010).
  - The paper's PDF still hasn't been checked against our measure definitions.
- The Loughran–McDonald dictionary is downloaded by hand (README, "Running Phase 3"); a new machine needs it before `python run.py score` counts words.

## Notes kept from Phase 2

- Extracted sections are in `data/processed/sections.db`, table `sections`. Use `scoring_text` (one paragraph per line) and `display_json`.
- The `section_changes` table and `reports/phase2_changes.csv` log every result that changes between extractor versions. Check that list after every re-run.
- Open items are at the bottom of DECISIONS.md. For Phase 3:
  - Sentence splitting must ignore line breaks (D-027).
  - Decide whether to remove risk factor summaries.
  - Spin-offs and new companies have no prior year, so their first year is unscored (D-019).
