# Notes for Claude

Read [docs/HANDOFF.md](docs/HANDOFF.md) first. It says where the project stands, how Rohan likes to work, and what's next. Then read README.md and DECISIONS.md.

- Run Python inside the project's virtual environment: `source .venv/bin/activate`, then `python run.py ...`. The "NotOpenSSLWarning" is harmless.
- Run the tests with `python -m unittest discover -s tests -t tests` before every commit.
- Record every methodology choice in DECISIONS.md, and commit after each working step.
- After changing extraction rules, bump `EXTRACTOR_VERSION` in `src/tracker/extract.py`, re-run `python run.py extract`, and check every row of `reports/phase2_changes.csv`.
- Never commit `.env` (it holds Rohan's SEC contact email) or anything under `data/raw/`.
