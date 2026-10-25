# Picking up this project in a new session

Read this first. Then read README.md and DECISIONS.md.

## Where things stand (2026-10-25)

- **Phase 0–1 (data collection): done.** 2,494 sample 10-Ks (fiscal 2021–2025, S&P 500 members on the filing date) plus 552 prior-year comparisons, all downloaded. See [phase1_report.md](phase1_report.md).
- **Phase 2 (Item 1A extraction): done.** Extractor version 1.3 extracts all 2,494 sample filings. See [phase2_report.md](phase2_report.md).
- **Phase 3 (change scores): not started.** Next step: write the plan and ask Rohan the open questions before building anything.

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

## Things to know before Phase 3

- Extracted sections are in `data/processed/sections.db`, table `sections`. Use `scoring_text` (one paragraph per line) and `display_json`.
- The `section_changes` table and `reports/phase2_changes.csv` log every result that changes between extractor versions. Check that list after every re-run.
- Open items are at the bottom of DECISIONS.md. For Phase 3:
  - Sentence splitting must ignore line breaks (D-027).
  - Decide whether to remove risk factor summaries.
  - Spin-offs and new companies have no prior year, so their first year is unscored (D-019).
