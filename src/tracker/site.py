"""Phase 5: build the dashboard, a static website in site/ (D-038).

  site/index.html, app.js, style.css   the page (copied from src/tracker/site_assets/)
  site/data/meta.json                  build date, counts, the research distribution
  site/data/companies.json             every company, for the search box
  site/data/season.json                the latest filing season's biggest changes
  site/data/c/<cik>.json               one company: every scored year, with its new and dropped sentences

No server is needed: the page loads these files as you click, so it can be hosted for free
on GitHub Pages. Which filings are shown:
  - the research sample (role 'sample'), scored;
  - live filings (role 'live') with nothing on the review list, or approved by hand (D-037).
Not published: the Loughran-McDonald counts (free for academic use only, D-032).
"""
from __future__ import annotations

import bisect
import difflib
import json
import statistics
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .live import load_approved, review_reasons
from .textprep import split_sentences, words
from .wordlists import new_and_dropped

ASSETS = Path(__file__).resolve().parent / "site_assets"
SEASON_TOP = 25
MEASURES = ("sim_cosine", "sim_jaccard", "sim_min_edit", "sim_simple")
EDIT_OVERLAP = 0.5       # a new and a dropped sentence sharing half their distinct words = one edited sentence
EDITS_SHOWN = 15         # per filing; the count is always shown, the rest are on EDGAR


def split_changes(added: list[str], removed: list[str], prior_keys: set[str] | None = None,
                  current_keys: set[str] | None = None) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """Sort a filing's changed sentences into (genuinely new, genuinely dropped, edited pairs).

    Moved sentences are left out first (D-030). Then a new sentence and a dropped one that share
    at least half their distinct words (Jaccard >= 0.5) are paired as one edited sentence. Pairs are
    made best match first, each sentence used once. Edited pairs keep the new sentence's order.
    """
    new, dropped = new_and_dropped(added, removed)
    # The diff lines sentences up in order, so a sentence that also sits elsewhere in the other year
    # (repeated, or moved past a repeat) can come out as added or removed. "New" means it appears
    # nowhere in last year's section; "dropped" means nowhere in this year's.
    if prior_keys is not None:
        new = [s for s in new if " ".join(words(s)) not in prior_keys]
    if current_keys is not None:
        dropped = [s for s in dropped if " ".join(words(s)) not in current_keys]
    new_words = [set(words(s)) for s in new]
    dropped_words = [set(words(s)) for s in dropped]
    candidates = []
    for i, a in enumerate(new_words):
        for j, b in enumerate(dropped_words):
            union = len(a | b)
            overlap = len(a & b) / union if union else 0
            if overlap >= EDIT_OVERLAP:
                candidates.append((-overlap, i, j))
    used_new, used_dropped, pairs = set(), set(), {}
    for _, i, j in sorted(candidates):
        if i not in used_new and j not in used_dropped:
            used_new.add(i)
            used_dropped.add(j)
            pairs[i] = j
    edits = [(dropped[pairs[i]], new[i]) for i in sorted(pairs)]
    return ([s for i, s in enumerate(new) if i not in used_new],
            [s for j, s in enumerate(dropped) if j not in used_dropped], edits)


def word_diff(old: str, new: str) -> list[list[str]]:
    """The edit as segments: ["=", "kept words"], ["-", "removed words"], ["+", "added words"]."""
    a, b = old.split(), new.split()
    segments = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            segments.append(["=", " ".join(a[i1:i2])])
            continue
        if i2 > i1:
            segments.append(["-", " ".join(a[i1:i2])])
        if j2 > j1:
            segments.append(["+", " ".join(b[j1:j2])])
    return segments


def edgar_url(cik: int, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index.htm"


def change_percentile(cosine: float, research_cosines: list[float]) -> float:
    """Share of research-sample 10-Ks (0-100) that changed less than this one: lower similarity
    = more change. research_cosines must be sorted."""
    more_similar = len(research_cosines) - bisect.bisect_right(research_cosines, cosine)
    return round(100 * more_similar / len(research_cosines), 1)


def shown_filings(conn: sqlite3.Connection, sconn: sqlite3.Connection, cconn: sqlite3.Connection,
                  reference_dir: Path) -> list[dict]:
    """Every filing the dashboard shows, with its scores and filing details."""
    reasons = review_reasons(conn, sconn, cconn)
    approved = load_approved(reference_dir)
    filings = {r["accession_number"]: dict(r) for r in conn.execute(
        "SELECT accession_number, cik, company_cik, fiscal_year, filing_date, role, prior_accession "
        "FROM filings WHERE selected = 1 AND role IN ('sample', 'live')")}
    all_filings = {r[0]: r[1:] for r in conn.execute("SELECT accession_number, cik, fiscal_year FROM filings")}
    shown = []
    for row in cconn.execute("SELECT * FROM changes WHERE version = 'main' AND status = 'ok' AND section = 'item_1a'"):
        f = filings.get(row["accession_number"])
        if f is None:
            continue
        if f["role"] == "live" and reasons.get(f["accession_number"]) and f["accession_number"] not in approved:
            continue
        prior_cik, prior_fy = all_filings.get(f["prior_accession"], (None, None))
        shown.append({**f, **{m: row[m] for m in MEASURES}, "flags": row["flags"] or "",
                      "prior_fiscal_year": prior_fy, "prior_cik": prior_cik,
                      "prior_words": row["prior_words"], "current_words": row["current_words"],
                      "sentences_kept": row["sentences_kept"] or 0, "sentences_removed": row["sentences_removed"] or 0})
    return shown


def build_site(conn: sqlite3.Connection, sconn: sqlite3.Connection, cconn: sqlite3.Connection,
               reference_dir: Path, out_dir: Path) -> dict:
    """Write the whole site to out_dir (replacing what was there). Returns counts."""
    filings = shown_filings(conn, sconn, cconn, reference_dir)
    research = sorted(f["sim_cosine"] for f in filings if f["role"] == "sample")
    names = {r[0]: r[1:] for r in conn.execute("SELECT cik, name_current, sic_description FROM companies")}
    # Current members get Wikipedia's sector and readable name ("JPMorgan Chase", not "JPMORGAN CHASE & CO");
    # companies no longer in the index keep SEC's name (tidied up on the page).
    current = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT cik, sector, name FROM live_members WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM live_members)"
    )} if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'live_members'").fetchone() else {}
    sectors = {cik: sector for cik, (sector, _) in current.items()}
    for cik, (_, wiki_name) in current.items():
        sic_description = names.get(cik, (None, None))[1]
        names[cik] = (wiki_name, sic_description)
    cuts = {r[0]: (r[1], r[2]) for r in cconn.execute(
        "SELECT accession_number, start_line, end_line FROM risk_summaries WHERE end_line IS NOT NULL")}

    def section_keys(accession: str) -> set[str]:
        """Every sentence of a section as compared (summary removed), in comparable form."""
        row = sconn.execute("SELECT scoring_text FROM sections WHERE accession_number = ? AND section = 'item_1a'",
                            (accession,)).fetchone()
        lines = (row[0] if row and row[0] else "").split("\n")
        if accession in cuts:
            start, end = cuts[accession]
            lines = lines[:start] + lines[end:]
        return {" ".join(words(s)) for s in split_sentences("\n".join(lines))}

    summaries = {r[0]: r[1] for r in cconn.execute("SELECT accession_number, words_removed FROM risk_summaries "
                                                    "WHERE end_line IS NOT NULL")}

    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "data" / "c").mkdir(parents=True)
    for asset in ("index.html", "app.js", "style.css"):
        shutil.copy(ASSETS / asset, out_dir / asset)

    by_company: dict[int, list[dict]] = defaultdict(list)
    for f in filings:
        f["change_percentile"] = change_percentile(f["sim_cosine"], research)
        by_company[f["company_cik"]].append(f)

    companies = []
    for cik, items in by_company.items():
        items.sort(key=lambda f: (f["fiscal_year"], f["filing_date"]))
        name, sic_description = names.get(cik, (None, None))
        tickers = sorted({t for t in (conn.execute(
            "SELECT member_tickers FROM filings WHERE company_cik = ? AND role IN ('sample', 'live') "
            "ORDER BY filing_date DESC LIMIT 1", (cik,)).fetchone() or [""])[0].split(",") if t})
        years = []
        for f in items:
            added = [t for (t,) in cconn.execute("SELECT text FROM changed_sentences WHERE accession_number = ? "
                                                 "AND kind = 'added' ORDER BY position", (f["accession_number"],))]
            removed = [t for (t,) in cconn.execute("SELECT text FROM changed_sentences WHERE accession_number = ? "
                                                   "AND kind = 'removed' ORDER BY position", (f["accession_number"],))]
            new, dropped, edits = split_changes(added, removed, section_keys(f["prior_accession"]),
                                                section_keys(f["accession_number"]))
            years.append({
                "accession": f["accession_number"], "fiscal_year": f["fiscal_year"],
                "prior_fiscal_year": f["prior_fiscal_year"], "filing_date": f["filing_date"],
                "edgar": edgar_url(f["cik"], f["accession_number"]),
                "prior_edgar": edgar_url(f["prior_cik"], f["prior_accession"]) if f["prior_cik"] else None,
                "live": f["role"] == "live",
                "scores": {m[4:]: round(f[m], 4) for m in MEASURES},
                "change_percentile": f["change_percentile"],
                "words": [f["prior_words"], f["current_words"]],
                "kept": f["sentences_kept"], "moved": len(added) - len(new) - len(edits),
                "flags": f["flags"], "summary_removed": summaries.get(f["accession_number"]) is not None,
                "new": new, "dropped": dropped,
                "edits": {"count": len(edits), "shown": [word_diff(old, new_) for old, new_ in edits[:EDITS_SHOWN]]},
            })
        latest = years[-1]
        companies.append({"cik": cik, "name": name, "tickers": tickers,
                          "sector": sectors.get(cik) or sic_description,
                          "latest_year": latest["fiscal_year"], "latest_percentile": latest["change_percentile"]})
        (out_dir / "data" / "c" / f"{cik}.json").write_text(
            json.dumps({"cik": cik, "name": name, "tickers": tickers, "sector": sectors.get(cik) or sic_description,
                        "years": years}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    companies.sort(key=lambda c: (c["name"] or "").lower())

    # The latest filing season: 10-Ks filed in the most recent calendar year with filings
    season_year = max(f["filing_date"][:4] for f in filings)
    in_season = [f for f in filings if f["filing_date"][:4] == season_year]
    ranked = sorted((f for f in in_season if not f["flags"]), key=lambda f: f["sim_cosine"])[:SEASON_TOP]
    season = {
        "year": season_year, "filings": len(in_season),
        "flagged_left_out": sum(1 for f in in_season if f["flags"]),
        "top": [{"cik": f["company_cik"], "name": names.get(f["company_cik"], (None,))[0],
                 "fiscal_year": f["fiscal_year"], "filing_date": f["filing_date"],
                 "change_percentile": f["change_percentile"], "cosine": round(f["sim_cosine"], 4),
                 "words": [f["prior_words"], f["current_words"]]} for f in ranked],
    }
    meta = {
        "built": datetime.now().isoformat(timespec="minutes"),
        "companies": len(companies), "filings": len(filings),
        "research_filings": len(research), "live_filings": sum(1 for f in filings if f["role"] == "live"),
        "research_cosine_median": research[len(research) // 2],
        # The typical share of last year's sentences that reappear word for word (main version)
        "research_sentences_kept_median": statistics.median(
            f["sentences_kept"] / (f["sentences_kept"] + f["sentences_removed"])
            for f in filings if f["role"] == "sample" and f["sentences_kept"] + f["sentences_removed"]),
        "backtest": "pending",
    }
    for name, data in (("companies", companies), ("season", season), ("meta", meta)):
        (out_dir / "data" / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                                                       encoding="utf-8")
    return {"companies": len(companies), "filings": len(filings), "season": season_year}
