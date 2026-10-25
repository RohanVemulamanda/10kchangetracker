"""Logging: every run writes a log file, so errors are recorded instead of lost.

- The console shows normal progress (INFO and above).
- The log file in logs/ keeps everything, including DEBUG details and full error tracebacks.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path


def setup_logging(run_name: str, logs_dir: Path) -> Path:
    """Send log messages to the console and to logs/<run_name>_<timestamp>.log.

    Returns the path of the log file so we can tell the user where it is.
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"{run_name}_{stamp}.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for handler in list(root.handlers):  # avoid duplicate lines if called twice
        root.removeHandler(handler)

    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
    root.addHandler(console_handler)

    # The HTTP library is very chatty at DEBUG level; keep only its warnings.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return log_path
