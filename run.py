"""Command-line entry point for the 10-K Change Tracker.

Examples:
    python run.py check                              test the SEC connection first
    python run.py all --tickers AAPL,JPM,META        small trial run on three companies
    python run.py all                                the full Phase 1 run
    python run.py summary                            re-print the summary report

Run `python run.py --help` to see every command.
"""
import argparse
import sys
from pathlib import Path

# Let Python find our code in the src/ folder without installing anything.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from tracker import pipeline  # noqa: E402  (must come after the line above)

COMMANDS = {
    "check": "Test the SEC connection on Apple. Run this first.",
    "universe": "Build S&P 500 membership history from the pinned source file.",
    "map-tickers": "Link each ticker to its SEC company ID (CIK).",
    "find-filings": "Get each company's filing list and choose the 10-Ks we need.",
    "download": "Download the chosen filings. Safe to stop and restart.",
    "summary": "Write and print reports/phase1_summary.md.",
    "all": "universe -> map-tickers -> find-filings -> download -> summary",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="10-K Change Tracker: Phase 1 data collection")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in COMMANDS.items():
        sub = subcommands.add_parser(name, help=help_text)
        if name in {"find-filings", "download", "all"}:
            sub.add_argument("--tickers", help="Only these tickers, comma-separated (for trial runs), e.g. AAPL,JPM,META")
    args = parser.parse_args()
    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()] if getattr(args, "tickers", None) else None
    return pipeline.run(args.command, tickers)


if __name__ == "__main__":
    sys.exit(main())
