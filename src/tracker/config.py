"""Load project settings.

Settings live in two places:
  - config/settings.yaml  research choices (years, universe, rate limits). Committed to git.
  - .env                  your name and email for the SEC User-Agent. NOT committed.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv

# The project folder = two levels up from this file (src/tracker/config.py).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ConfigError(Exception):
    """Raised when a setting is missing or clearly wrong."""


def load_settings(path: Path | None = None) -> dict:
    """Read config/settings.yaml into a plain dictionary."""
    path = path or PROJECT_ROOT / "config" / "settings.yaml"
    with open(path, encoding="utf-8") as f:
        settings = yaml.safe_load(f)

    sample = settings["sample"]
    if sample["start_fiscal_year"] > sample["end_fiscal_year"]:
        raise ConfigError("start_fiscal_year must not be after end_fiscal_year")
    if not 0 < settings["sec"]["requests_per_second"] <= 10:
        raise ConfigError("requests_per_second must be between 0 and 10 (SEC's limit is 10)")
    return settings


def project_path(relative: str) -> Path:
    """Turn a path from settings.yaml (relative to the project) into a full path."""
    return PROJECT_ROOT / relative


def get_user_agent() -> str:
    """Build the User-Agent string SEC requires: 'Your Name you@email.com'.

    Reads SEC_USER_NAME and SEC_USER_EMAIL from the .env file.
    Refuses to continue if they are missing or still the placeholder values,
    because SEC blocks requests that don't identify a real person.
    """
    load_dotenv(PROJECT_ROOT / ".env")
    name = os.getenv("SEC_USER_NAME", "").strip()
    email = os.getenv("SEC_USER_EMAIL", "").strip()

    if not name or not email:
        raise ConfigError(
            "Missing SEC_USER_NAME or SEC_USER_EMAIL. Copy .env.example to .env "
            "and fill in your real name and email."
        )
    if not EMAIL_PATTERN.match(email):
        raise ConfigError(f"SEC_USER_EMAIL does not look like an email address: {email!r}")
    if email.lower().endswith("@example.com") or name == "Your Name":
        raise ConfigError(".env still has the placeholder name/email. Put your real ones in.")
    return f"{name} {email}"
