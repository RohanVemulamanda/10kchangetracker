"""Phase 2 reports: the extraction summary, a list of flagged cases, and a review page.

  reports/phase2_summary.md    success rate, methods, word counts, flags
  reports/phase2_flagged.csv   every flagged or not-found filing, with EDGAR links
  reports/phase2_review.html   20 random extractions to check by hand, plus flagged cases
"""
from __future__ import annotations

import csv
import html
import json
import random
import sqlite3
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path


def edgar_document_url(source_document: str) -> str:
    """'filings/320193/000032019325000079/aapl-20250927.htm.gz' -> the document on sec.gov."""
    parts = source_document.split("/")
    cik, folder, name = parts[1], parts[2], parts[3].removesuffix(".gz")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{name}"


def edgar_index_url(cik: int, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index.htm"


def load_rows(conn: sqlite3.Connection, sconn: sqlite3.Connection, section: str = "item_1a") -> list[dict]:
    """Every selected, downloaded filing, joined with its extraction result (if any)."""
    filings = {r["accession_number"]: dict(r) for r in conn.execute(
        "SELECT f.accession_number, f.cik, f.company_cik, f.fiscal_year, f.role, f.member_tickers, f.filing_date, "
        "f.prior_accession, c.name_current FROM filings f LEFT JOIN companies c ON c.cik = f.company_cik "
        "WHERE f.selected = 1 AND f.status = 'downloaded'")}
    rows = []
    results = {r["accession_number"]: dict(r) for r in sconn.execute(
        "SELECT accession_number, status, method, source_document, header_text, end_text, words, paragraphs, "
        "removed_blocks, flags, notes, extractor_version, error FROM sections WHERE section = ?", (section,))}
    for acc, f in filings.items():
        rows.append({**f, **results.get(acc, {"status": "not_extracted"})})
    return rows


def pct(values: list[int], p: float) -> int:
    values = sorted(values)
    return values[min(len(values) - 1, int(p * len(values)))] if values else 0


def write_phase2_summary(conn: sqlite3.Connection, sconn: sqlite3.Connection, reports_dir: Path) -> str:
    reports_dir.mkdir(parents=True, exist_ok=True)
    rows = load_rows(conn, sconn)
    sample = [r for r in rows if r["role"] == "sample"]
    out = ["# Phase 2 summary: Item 1A (Risk Factors) extraction",
           f"Generated {datetime.now():%Y-%m-%d %H:%M}.\n"]

    def block(title: str, subset: list[dict]) -> None:
        status = Counter(r["status"] for r in subset)
        found = status["ok"] + status["flagged"]
        out.append(f"## {title}: {len(subset)} filings")
        out.append(f"- **Extracted: {found} ({found / max(len(subset), 1):.1%})**, of which "
                   f"{status['ok']} passed every check and {status['flagged']} are flagged for review")
        out.append(f"- Not found: {status['not_found']}; errors: {status['error']}; not yet run: {status['not_extracted']}")
        out.append("")

    block("All downloaded filings", rows)
    block("Sample filings only (the ones that get scored)", sample)

    extracted = [r for r in rows if r["status"] in ("ok", "flagged")]
    out.append("## How each section was found")
    for method, n in Counter(r["method"] for r in extracted).most_common():
        out.append(f"- {method}: {n}")
    out.append("")

    out.append("## By fiscal year (sample filings)")
    out.append("| Fiscal year | Filings | Extracted | Flagged | Not found |")
    out.append("|---|---|---|---|---|")
    for fy in sorted({r["fiscal_year"] for r in sample}):
        s = [r for r in sample if r["fiscal_year"] == fy]
        c = Counter(r["status"] for r in s)
        out.append(f"| {fy} | {len(s)} | {c['ok'] + c['flagged']} | {c['flagged']} | {c['not_found'] + c['error']} |")
    out.append("")

    words = [r["words"] for r in extracted if r.get("words")]
    if words:
        out.append("## Length (words in the scoring version)")
        out.append(f"- Median {statistics.median(words):,.0f}; 10th percentile {pct(words, 0.1):,}; "
                   f"90th percentile {pct(words, 0.9):,}; shortest {min(words):,}; longest {max(words):,}")
        removed = [r["removed_blocks"] for r in extracted if r.get("removed_blocks") is not None]
        out.append(f"- Page numbers, headers and footers removed per section: median {statistics.median(removed):.0f}")
        out.append("")

    out.append("## Quality flags")
    flag_counts = Counter(f for r in rows for f in (r.get("flags") or "").split(",") if f)
    explanations = {
        "short": "fewer than 1,000 words",
        "long": "more than 50,000 words",
        "overrun": "a later item's header appears inside the text (grabbed too much)",
        "length_jump": "more than 3x longer or shorter than the prior year",
        "not_found": "no section found",
    }
    for flag, n in flag_counts.most_common():
        out.append(f"- {flag} ({explanations.get(flag, '')}): {n}")
    if not flag_counts:
        out.append("- None")
    out.append("\nEvery flagged filing is listed in reports/phase2_flagged.csv.")

    with open(reports_dir / "phase2_flagged.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["company", "tickers", "fiscal_year", "role", "accession_number", "status", "flags",
                         "method", "words", "notes", "edgar_link"])
        for r in sorted(rows, key=lambda r: (r.get("name_current") or "", r["fiscal_year"] or 0)):
            if r["status"] in ("flagged", "not_found", "error"):
                link = edgar_document_url(r["source_document"]) if r.get("source_document") else edgar_index_url(r["cik"], r["accession_number"])
                writer.writerow([r.get("name_current"), r.get("member_tickers"), r["fiscal_year"], r["role"],
                                 r["accession_number"], r["status"], r.get("flags"), r.get("method"), r.get("words"),
                                 (r.get("notes") or r.get("error") or "")[:300], link])

    text = "\n".join(out) + "\n"
    (reports_dir / "phase2_summary.md").write_text(text, encoding="utf-8")
    return text


# ---------------------------------------------------------------- review page

PAGE_STYLE = """
:root { --navy:#13294b; --ink:#1d2433; --muted:#5b6475; --line:#d9dee8; --bg:#f6f7fa; --card:#fff; --ok:#1f7a4d; --warn:#a25a00; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
header { background:var(--navy); color:#fff; padding:20px 24px; }
header h1 { margin:0 0 4px; font-size:20px; }
header p { margin:0; opacity:.85; }
main { max-width:980px; margin:0 auto; padding:20px 16px 80px; }
.howto { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:14px 18px; margin-bottom:18px; }
.howto ol { margin:6px 0 0; padding-left:20px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:16px 18px; margin:14px 0; }
.card h2 { font-size:17px; margin:0 0 4px; }
.meta { color:var(--muted); font-size:13px; margin-bottom:10px; }
.meta a { color:var(--navy); }
.tag { display:inline-block; font-size:12px; padding:1px 8px; border-radius:10px; background:#e8ecf4; margin-right:4px; }
.tag.warn { background:#fdf0dc; color:var(--warn); }
.edge { border-left:3px solid var(--navy); padding:6px 12px; margin:8px 0; background:#fafbfd; }
.edge .label { font-size:12px; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.03em; }
.boundary { font-size:13px; color:var(--muted); margin:2px 0; }
details { margin-top:8px; }
details .full p { margin:0 0 8px; }
details .full p.b { font-weight:600; }
.q { display:flex; flex-wrap:wrap; gap:14px; margin-top:12px; font-size:14px; }
.q label { cursor:pointer; }
.q input[type=text] { flex:1 1 260px; padding:5px 8px; border:1px solid var(--line); border-radius:5px; }
#bar { position:fixed; bottom:0; left:0; right:0; background:var(--card); border-top:1px solid var(--line); padding:10px 16px; display:flex; gap:12px; align-items:center; justify-content:center; }
button { background:var(--navy); color:#fff; border:0; border-radius:6px; padding:8px 16px; font-size:14px; cursor:pointer; }
table { width:100%; border-collapse:collapse; font-size:13px; background:var(--card); }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
@media (max-width:600px) { header, main { padding-left:12px; padding-right:12px; } }
"""

PAGE_SCRIPT = """
function collect() {
  const lines = [];
  document.querySelectorAll('.card[data-id]').forEach(card => {
    const id = card.dataset.id, name = card.dataset.name;
    const get = q => { const el = card.querySelector('input[name="' + id + '-' + q + '"]:checked'); return el ? el.value : '?'; };
    const note = card.querySelector('input[type=text]').value.trim();
    lines.push(name + ': start ' + get('start') + ', end ' + get('end') + ', clean ' + get('clean') + (note ? ' -- ' + note : ''));
  });
  const text = 'Phase 2 review (seed SEED)\\n' + lines.join('\\n');
  navigator.clipboard.writeText(text).then(() => { document.getElementById('msg').textContent = 'Copied. Paste it into the chat.'; },
    () => { document.getElementById('out').value = text; document.getElementById('out').style.display = 'block'; });
}
"""


def _paragraphs(display_json: str) -> list[dict]:
    return [p for p in json.loads(display_json or "[]") if not p.get("table")]


def _head(text: str, limit: int = 600) -> str:
    """The start of a paragraph, cut at a word boundary."""
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def _tail(text: str, limit: int = 600) -> str:
    """The end of a paragraph, cut at a word boundary."""
    return text if len(text) <= limit else "… " + text[-limit:].split(" ", 1)[-1]


def write_review_page(conn: sqlite3.Connection, sconn: sqlite3.Connection, reports_dir: Path,
                      how_many: int = 20, seed: int | None = None) -> tuple[Path, int]:
    rows = [r for r in load_rows(conn, sconn) if r["role"] == "sample" and r["status"] in ("ok", "flagged")]
    rows.sort(key=lambda r: r["accession_number"])
    seed = seed if seed is not None else random.randrange(10_000)
    picks = random.Random(seed).sample(rows, min(how_many, len(rows)))
    esc = html.escape

    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
             f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
             f"<title>Phase 2 Review</title><style>{PAGE_STYLE}</style></head><body>",
             f"<header><h1>Risk Factors extraction: hand review</h1>"
             f"<p>{len(picks)} random sample filings (seed {seed}). Re-create this exact page with "
             f"<code>python run.py review-extractions --seed {seed}</code>.</p></header><main>",
             "<div class='howto'><strong>For each filing:</strong><ol>"
             "<li>Click <em>Open on EDGAR</em>. Press Cmd+F (Ctrl+F on Windows) and search for the first few words of <em>First paragraph</em>.</li>"
             "<li><strong>Start:</strong> the line just above it should be the Item 1A / Risk Factors header (shown below as <em>Starts after</em>).</li>"
             "<li><strong>End:</strong> search for <em>Last paragraph</em>. The next heading after it should be the one shown as <em>Stops before</em> (usually Item 1B, 1C or 2).</li>"
             "<li><strong>Clean:</strong> open <em>Full text</em> and skim: no page numbers, repeated page headers, or table-of-contents lines.</li>"
             "</ol>When done, click <em>Copy my answers</em> at the bottom and paste into the chat.</div>"]

    for n, r in enumerate(picks, start=1):
        paras = _paragraphs(sconn.execute("SELECT display_json FROM sections WHERE accession_number = ? AND section = 'item_1a'",
                                          (r["accession_number"],)).fetchone()[0])
        name = f"{n}. {r.get('name_current')} ({r.get('member_tickers')}) FY{r['fiscal_year']}"
        flags = "".join(f"<span class='tag warn'>{esc(f)}</span>" for f in (r.get("flags") or "").split(",") if f)
        full = "".join(f"<p class='{'b' if p['b'] else ''}'>{esc(p['t'])}</p>" for p in paras)
        rid = r["accession_number"]
        radios = "".join(
            f"<span>{label}: <label><input type='radio' name='{rid}-{q}' value='yes'> yes</label> "
            f"<label><input type='radio' name='{rid}-{q}' value='NO'> no</label></span>"
            for q, label in (("start", "Start right"), ("end", "End right"), ("clean", "Clean")))
        parts.append(
            f"<div class='card' data-id='{rid}' data-name='{esc(name)}'><h2>{esc(name)}</h2>"
            f"<div class='meta'><span class='tag'>{esc(r.get('method') or '')}</span>{flags} "
            f"{r.get('words') or 0:,} words &middot; {r.get('paragraphs') or 0} paragraphs &middot; "
            f"<a href='{edgar_document_url(r['source_document'])}' target='_blank' rel='noopener'>Open on EDGAR</a> &middot; "
            f"<a href='{edgar_index_url(r['cik'], rid)}' target='_blank' rel='noopener'>filing index</a></div>"
            f"<p class='boundary'><strong>Starts after:</strong> {esc(r.get('header_text') or '')[:160]}</p>"
            f"<div class='edge'><div class='label'>First paragraph</div>{esc(_head(paras[0]['t'])) if paras else ''}</div>"
            f"<div class='edge'><div class='label'>Last paragraph</div>{esc(_tail(paras[-1]['t'])) if paras else ''}</div>"
            f"<p class='boundary'><strong>Stops before:</strong> {esc(r.get('end_text') or '')[:160]}</p>"
            f"<details><summary>Full text</summary><div class='full'>{full}</div></details>"
            f"<div class='q'>{radios}<input type='text' placeholder='Notes (optional)'></div></div>")

    flagged = [r for r in load_rows(conn, sconn) if r["status"] in ("flagged", "not_found", "error")]
    parts.append(f"<h2 style='margin-top:36px'>All flagged or missing ({len(flagged)})</h2>"
                 "<p class='meta'>Not part of the random check. These are reviewed separately; the full list is in reports/phase2_flagged.csv.</p>"
                 "<table><tr><th>Company</th><th>FY</th><th>Status</th><th>Flags</th><th>Words</th><th>Link</th></tr>")
    for r in sorted(flagged, key=lambda r: (r.get("name_current") or "", r["fiscal_year"] or 0))[:500]:
        link = edgar_document_url(r["source_document"]) if r.get("source_document") else edgar_index_url(r["cik"], r["accession_number"])
        parts.append(f"<tr><td>{esc(r.get('name_current') or '')}</td><td>{r['fiscal_year']}</td><td>{r['status']}</td>"
                     f"<td>{esc(r.get('flags') or '')}</td><td>{r.get('words') or ''}</td>"
                     f"<td><a href='{link}' target='_blank' rel='noopener'>EDGAR</a></td></tr>")
    parts.append("</table></main>"
                 "<div id='bar'><button onclick='collect()'>Copy my answers</button><span id='msg'></span></div>"
                 "<textarea id='out' style='display:none;width:100%;height:160px'></textarea>"
                 f"<script>{PAGE_SCRIPT.replace('SEED', str(seed))}</script></body></html>")
    path = reports_dir / "phase2_review.html"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(parts), encoding="utf-8")
    return path, seed
