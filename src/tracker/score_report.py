"""Phase 3 reports: the scoring summary and lists for review.

  reports/phase3_summary.md     counts, spread of each measure, medians by year, agreement between measures
  reports/phase3_scores.csv     every scored pair, both versions, with company and year (for Excel)
  reports/phase3_summaries.csv  every risk factor summary found, with what was removed (D-029 review list)
  reports/phase3_review.html    pairs to check by hand: biggest, smallest, random, fallback-method extractions
"""
from __future__ import annotations

import html
import random
import sqlite3
from pathlib import Path

import pandas as pd

from .extract_report import PAGE_STYLE, _head, _tail, edgar_document_url
from .score import SCORER_VERSION

MEASURES = ["sim_cosine", "sim_jaccard", "sim_min_edit", "sim_simple"]


def load_scores(conn: sqlite3.Connection, cconn: sqlite3.Connection) -> pd.DataFrame:
    """Every row of the changes table, with company name, ticker, fiscal year and filing date."""
    changes = pd.read_sql_query("SELECT * FROM changes", cconn)
    filings = pd.read_sql_query(
        "SELECT f.accession_number, f.company_cik, f.fiscal_year, f.filing_date, f.member_tickers, "
        "f.prior_gap_days, c.name_current AS company FROM filings f LEFT JOIN companies c ON c.cik = f.company_cik "
        "WHERE f.selected = 1", conn)
    return changes.merge(filings, on="accession_number", how="left")


def describe(values: pd.Series) -> str:
    q = values.quantile([0.01, 0.10, 0.25, 0.50, 0.75, 0.90])
    return " | ".join(f"{v:.3f}" for v in [values.mean(), *q.values])


def write_phase3_summary(conn: sqlite3.Connection, cconn: sqlite3.Connection, reports_dir: Path) -> str:
    reports_dir.mkdir(parents=True, exist_ok=True)
    df = load_scores(conn, cconn)
    main = df[df.version == "main"]
    ok = df[df.status == "ok"]
    ok_main = ok[ok.version == "main"]

    out = ["# Phase 3 summary: Risk Factors change scores", "",
           f"Scorer version {SCORER_VERSION}. Similarity runs from 0 (nothing in common) to 1 (identical); "
           "change = 1 - similarity. Choices are in DECISIONS.md (D-028 to D-030).", "",
           "## Coverage", "",
           "| | Sample 10-Ks |", "|---|---|",
           f"| In the sample | {len(main):,} |",
           f"| Scored | {(main.status == 'ok').sum():,} |"]
    for note, n in main[main.status == "unscored"].note.value_counts().items():
        out.append(f"| Not scored: {note} | {n:,} |")
    out.append(f"| Errors | {(main.status == 'error').sum():,} |")

    out += ["", "## Spread of each measure", "",
            "Mean, then the 1st, 10th, 25th, 50th, 75th and 90th percentiles.", "",
            "| Version | Measure | Mean | p1 | p10 | p25 | p50 | p75 | p90 |", "|---|---|---|---|---|---|---|---|---|"]
    for version in ("main", "with_summary"):
        for m in MEASURES:
            out.append(f"| {version} | {m[4:]} | {describe(ok[ok.version == version][m])} |")

    out += ["", "## Median similarity by fiscal year (main version)", "",
            "| Fiscal year | Scored | " + " | ".join(m[4:] for m in MEASURES) + " |",
            "|---|---|" + "---|" * len(MEASURES)]
    for year, group in ok_main.groupby("fiscal_year"):
        out.append(f"| {year} | {len(group):,} | " + " | ".join(f"{group[m].median():.3f}" for m in MEASURES) + " |")

    out += ["", "## Do the measures agree? (rank correlation, main version)", "",
            "1 means two measures rank the filings in exactly the same order.", "",
            "| | " + " | ".join(m[4:] for m in MEASURES) + " |", "|---|" + "---|" * len(MEASURES)]
    corr = ok_main[MEASURES].rank().corr()   # rank correlation (Spearman): correlation of the ranks
    for m in MEASURES:
        out.append(f"| {m[4:]} | " + " | ".join(f"{corr.loc[m, n]:.2f}" for n in MEASURES) + " |")

    paired = ok_main.merge(ok[ok.version == "with_summary"], on="accession_number", suffixes=("", "_ws"))
    out += ["", "## Does removing summaries matter? (rank correlation, main vs with_summary)", "",
            "| Measure | Rank correlation | Filings whose score moved by more than 0.05 |", "|---|---|---|"]
    for m in MEASURES:
        moved = ((paired[m] - paired[m + "_ws"]).abs() > 0.05).sum()
        out.append(f"| {m[4:]} | {paired[m].rank().corr(paired[m + '_ws'].rank()):.3f} | {moved:,} |")

    summaries = pd.read_sql_query("SELECT * FROM risk_summaries", cconn)
    out += ["", "## Risk factor summaries (D-029)", "",
            f"Sections with a summary heading, among the filings scored (current or prior year): {len(summaries):,}", ""]
    for rule, n in summaries.rule.value_counts().items():
        out.append(f"- `{rule}`: {n:,}")
    out.append(f"- removed text containing a long paragraph (`long_line`, to check): {int(summaries.long_line.sum()):,}")

    out += ["", "## The 15 biggest changes (lowest cosine similarity, main version)", "",
            "| Company | Fiscal year | Cosine | Jaccard | Min edit | Simple | Words before -> after |",
            "|---|---|---|---|---|---|---|"]
    for _, r in ok_main.nsmallest(15, "sim_cosine").iterrows():
        out.append(f"| {r.company} | {r.fiscal_year} | {r.sim_cosine:.3f} | {r.sim_jaccard:.3f} | {r.sim_min_edit:.3f} | "
                   f"{r.sim_simple:.3f} | {r.prior_words:,} -> {r.current_words:,} |")

    text = "\n".join(out) + "\n"
    (reports_dir / "phase3_summary.md").write_text(text, encoding="utf-8")

    columns = ["company", "member_tickers", "fiscal_year", "filing_date", "accession_number", "prior_accession",
               "version", "status", "note", *MEASURES, "prior_words", "current_words", "sentences_added",
               "sentences_removed", "sentences_kept", "words_added", "words_removed"]
    df.sort_values(["company", "fiscal_year", "version"])[columns].to_csv(reports_dir / "phase3_scores.csv", index=False)
    summaries.to_csv(reports_dir / "phase3_summaries.csv", index=False)
    return text


# ------------------------------------------------------------------ hand review page

REVIEW_SCRIPT = """
function collect() {
  const lines = [];
  document.querySelectorAll('.card[data-id]').forEach(card => {
    const id = card.dataset.id, name = card.dataset.name;
    const get = q => { const el = card.querySelector('input[name="' + id + '-' + q + '"]:checked'); return el ? el.value : '?'; };
    const note = card.querySelector('input[type=text]').value.trim();
    lines.push(name + ': changes real ' + get('real') + ', summary right ' + get('summary') + (note ? ' -- ' + note : ''));
  });
  const text = 'Phase 3 review (seed SEED)\\n' + lines.join('\\n');
  navigator.clipboard.writeText(text).then(() => { document.getElementById('msg').textContent = 'Copied. Paste it into the chat.'; },
    () => { document.getElementById('out').value = text; document.getElementById('out').style.display = 'block'; });
}
"""


def review_groups(scores: pd.DataFrame, sconn: sqlite3.Connection, measure: str, how_many: int, seed: int) -> list[tuple[str, pd.DataFrame]]:
    """The pairs to check by hand (D-030): biggest and smallest changes, a random set, and every
    pair where either year was found by a fallback extraction method (not `item`)."""
    ok = scores[(scores.version == "main") & (scores.status == "ok")].sort_values("accession_number")
    methods = dict(sconn.execute("SELECT accession_number, method FROM sections WHERE section = 'item_1a'").fetchall())
    fallback = ok[[methods.get(a) != "item" or methods.get(p) != "item"
                   for a, p in zip(ok.accession_number, ok.prior_accession)]]
    return [
        (f"The {how_many} biggest changes (lowest {measure[4:]})", ok.nsmallest(how_many, measure)),
        (f"The {how_many} smallest changes (highest {measure[4:]})", ok.nlargest(how_many, measure)),
        (f"{how_many} random pairs (seed {seed})", ok.sample(n=min(how_many, len(ok)), random_state=seed)),
        (f"Every pair with a fallback-method extraction ({len(fallback)})", fallback),
    ]


def write_score_review_page(conn: sqlite3.Connection, sconn: sqlite3.Connection, cconn: sqlite3.Connection,
                            reports_dir: Path, how_many: int = 20, seed: int | None = None,
                            measure: str = "sim_cosine") -> tuple[Path, int]:
    esc = html.escape
    seed = seed if seed is not None else random.randrange(10_000)
    scores = load_scores(conn, cconn)
    info = {r["accession_number"]: dict(r) for r in sconn.execute(
        "SELECT accession_number, method, source_document, scoring_text FROM sections WHERE section = 'item_1a'")}
    summaries = {r["accession_number"]: dict(r) for r in cconn.execute("SELECT * FROM risk_summaries")}
    years = dict(conn.execute("SELECT accession_number, fiscal_year FROM filings").fetchall())

    def summary_note(acc: str) -> str:
        s = summaries.get(acc)
        if s is None:
            return "no summary"
        if s["end_line"] is None:
            return f"summary heading found, end not found: nothing removed ({esc(s['heading'])})"
        warn = " <span class='tag warn'>long paragraph removed: check</span>" if s["long_line"] else ""
        return (f"<span class='tag'>{s['rule']}</span> removed {s['words_removed']:,} words, from "
                f"<em>{esc(s['heading'])}</em> to just before <em>{esc((s['first_kept_line'] or '')[:120])}</em>{warn}")

    def edges(acc: str) -> str:
        text = info[acc]["scoring_text"] or ""
        lines = text.split("\n")
        s = summaries.get(acc)
        if s and s["end_line"] is not None:
            lines = lines[:s["start_line"]] + lines[s["end_line"]:]
        lines = [line for line in lines if line.strip()] or [""]
        return (f"<div class='edge'><div class='label'>Starts</div>{esc(_head(lines[0], 300))}</div>"
                f"<div class='edge'><div class='label'>Ends</div>{esc(_tail(lines[-1], 300))}</div>")

    parts = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>"
             "<meta name='viewport' content='width=device-width, initial-scale=1'>"
             f"<title>Phase 3 Review</title><style>{PAGE_STYLE}"
             ".cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:800px){.cols{grid-template-columns:1fr}}"
             ".chg p{margin:4px 0;font-size:13px}.add{border-left:3px solid var(--ok);padding-left:8px}"
             ".rem{border-left:3px solid var(--warn);padding-left:8px}</style></head><body>",
             "<header><h1>Risk Factors change scores: hand review</h1>"
             f"<p>Re-create this exact page with <code>python run.py review-scores --seed {seed}</code>.</p></header><main>",
             "<div class='howto'><strong>For each pair:</strong><ol>"
             "<li><strong>Changes real:</strong> read the removed and added sentences. Do they look like real rewording "
             "of the risk factors? Signs of an extraction error: text from another section (financial tables, MD&amp;A, "
             "the list of executives), or a whole block that's missing in one year only.</li>"
             "<li><strong>Starts / Ends:</strong> both years should start at the first risk-factor text and end on the last risk factor.</li>"
             "<li><strong>Summary right:</strong> if a summary was removed, the first kept line should be where the full "
             "section begins. Answer n/a if neither year had one.</li></ol>"
             "When done, click <em>Copy my answers</em> at the bottom and paste into the chat.</div>"]
    card_number = 0
    for title, group in review_groups(scores, sconn, measure, how_many, seed):
        parts.append(f"<h2 style='margin-top:36px'>{esc(title)}</h2>")
        for _, r in group.iterrows():
            card_number += 1
            acc, prior = r.accession_number, r.prior_accession
            added = [t for (t,) in cconn.execute("SELECT text FROM changed_sentences WHERE accession_number = ? AND kind = 'added' "
                                                 "ORDER BY position LIMIT 8", (acc,))]
            removed = [t for (t,) in cconn.execute("SELECT text FROM changed_sentences WHERE accession_number = ? AND kind = 'removed' "
                                                   "ORDER BY position LIMIT 8", (acc,))]
            name = f"{card_number}. {r.company} ({r.member_tickers}) FY{years.get(prior)} -> FY{r.fiscal_year}"
            rid = f"{card_number}-{acc}"
            radios = "".join(
                f"<span>{label}: " + " ".join(f"<label><input type='radio' name='{rid}-{q}' value='{v}'> {v}</label>" for v in values) + "</span>"
                for q, label, values in (("real", "Changes real", ("yes", "NO")), ("summary", "Summary right", ("yes", "NO", "n/a"))))
            year_cols = "".join(
                f"<div><h3>FY{years.get(a)} <span class='tag'>{esc(info[a]['method'] or '')}</span> "
                f"<a href='{edgar_document_url(info[a]['source_document'])}' target='_blank' rel='noopener'>EDGAR</a></h3>"
                f"<p class='meta'>{summary_note(a)}</p>{edges(a)}</div>" for a in (prior, acc))
            parts.append(
                f"<div class='card' data-id='{rid}' data-name='{esc(name)}'><h2>{esc(name)}</h2>"
                f"<div class='meta'>cosine {r.sim_cosine:.3f} &middot; Jaccard {r.sim_jaccard:.3f} &middot; "
                f"min edit {r.sim_min_edit:.3f} &middot; simple {r.sim_simple:.3f} &middot; "
                f"{int(r.prior_words):,} -> {int(r.current_words):,} words &middot; "
                f"{int(r.sentences_removed)} sentences removed, {int(r.sentences_added)} added, {int(r.sentences_kept)} kept</div>"
                f"<div class='cols'>{year_cols}</div>"
                f"<div class='cols chg'><div><div class='label'>First removed sentences</div>"
                + "".join(f"<p class='rem'>{esc(_head(t, 300))}</p>" for t in removed)
                + "</div><div><div class='label'>First added sentences</div>"
                + "".join(f"<p class='add'>{esc(_head(t, 300))}</p>" for t in added)
                + f"</div></div><div class='q'>{radios}<input type='text' placeholder='Notes (optional)'></div></div>")
    parts.append("</main><div id='bar'><button onclick='collect()'>Copy my answers</button><span id='msg'></span></div>"
                 "<textarea id='out' style='display:none;width:100%;height:160px'></textarea>"
                 f"<script>{REVIEW_SCRIPT.replace('SEED', str(seed))}</script></body></html>")
    path = reports_dir / "phase3_review.html"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(parts), encoding="utf-8")
    return path, seed
