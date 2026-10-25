// 10-K Change Tracker: the dashboard page (D-038).
// Loads the small JSON files in data/ as needed. Text from filings is always inserted with
// textContent, never as HTML, so nothing in a 10-K can run as code on this page.
"use strict";

const state = { companies: [], meta: null, season: null, cache: {} };
const main = document.getElementById("main");

// ---------------------------------------------------------------- helpers

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) if (child != null) node.append(child);
  return node;
}

async function getJSON(path) {
  if (!state.cache[path]) {
    state.cache[path] = fetch(path).then(r => {
      if (!r.ok) throw new Error(path + ": " + r.status);
      return r.json();
    });
  }
  return state.cache[path];
}

const fmt = n => n.toLocaleString("en-US");
const pct = p => (p >= 99.95 ? ">99.9" : p.toFixed(1)) + "%";

function percentileBar(p) {
  return el("span", { class: "bar", "aria-hidden": "true" }, el("span", { style: `width:${Math.max(2, p)}%` }));
}

function flagPill(flags) {
  if (!flags) return null;
  return el("span", { class: "pill warn", title: "The company switched between “we” and “the Company”. "
    + "Every sentence about it is reworded, so the score overstates the change in its risks." }, "we ↔ the Company");
}

// ---------------------------------------------------------------- search

const input = document.getElementById("q");
const list = document.getElementById("suggestions");
let active = -1;

function matches(query) {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const starts = [], contains = [];
  for (const c of state.companies) {
    const name = (c.name || "").toLowerCase();
    const tick = c.tickers.map(t => t.toLowerCase());
    if (tick.includes(q) || name.startsWith(q)) starts.push(c);
    else if (name.includes(q) || tick.some(t => t.startsWith(q))) contains.push(c);
  }
  return starts.concat(contains).slice(0, 10);
}

function showSuggestions() {
  const found = matches(input.value);
  list.replaceChildren(...found.map((c, i) => el("li", {
    role: "option", "aria-selected": String(i === active),
    onmousedown: e => { e.preventDefault(); go(c.cik); },
  }, el("span", { text: c.name }), el("span", { class: "tick", text: c.tickers.join(", ") }))));
  list.hidden = found.length === 0;
  return found;
}

input.addEventListener("input", () => { active = -1; showSuggestions(); });
input.addEventListener("keydown", e => {
  const found = matches(input.value);
  if (e.key === "ArrowDown") { active = Math.min(active + 1, found.length - 1); showSuggestions(); e.preventDefault(); }
  else if (e.key === "ArrowUp") { active = Math.max(active - 1, 0); showSuggestions(); e.preventDefault(); }
  else if (e.key === "Enter" && found.length) { go(found[Math.max(active, 0)].cik); }
  else if (e.key === "Escape") { list.hidden = true; }
});
input.addEventListener("blur", () => { list.hidden = true; });

function go(cik, year) {
  list.hidden = true;
  input.value = "";
  location.hash = year ? `c=${cik}&y=${year}` : `c=${cik}`;
}

// ---------------------------------------------------------------- home page

function howToRead() {
  return el("div", { class: "card" },
    el("h3", { text: "How to read this" }),
    el("p", { text: "Each year, a company's 10-K Risk Factors are compared with the year before. The score is how much "
      + "of the text changed, from the cosine similarity of the two years' words (1 = identical). It's shown as a rank: "
      + "“changed more than 90%” means only 10% of S&P 500 10-Ks from 2021–2025 changed more." }),
    el("p", { text: "Most 10-Ks barely change from year to year. The research this is based on (Lazy Prices) found "
      + "that companies that change theirs a lot did worse afterwards. Whether that still holds is being tested: the "
      + "backtest results will appear here when they're ready." }),
    el("p", { class: "note", text: "Risk factor summaries are left out of the comparison, and numbers are ignored "
      + "(so “2024” → “2025” isn't a change). New sentences that only moved within the section aren't listed as new." }));
}

function renderHome() {
  document.title = "10-K Change Tracker";
  const s = state.season;
  const rows = s.top.map((f, i) => el("tr", { class: "clickable", tabindex: "0",
      onclick: () => go(f.cik, f.fiscal_year), onkeydown: e => { if (e.key === "Enter") go(f.cik, f.fiscal_year); } },
    el("td", { class: "num", text: String(i + 1) }),
    el("td", {}, el("strong", { text: f.name })),
    el("td", { text: "FY" + f.fiscal_year }),
    el("td", { text: f.filing_date }),
    el("td", {}, percentileBar(f.change_percentile), el("span", { text: pct(f.change_percentile) })),
    el("td", { class: "num", text: `${fmt(f.words[0])} → ${fmt(f.words[1])}` })));
  main.replaceChildren(
    el("h1", { text: `Biggest rewrites of ${s.year}` }),
    el("p", { class: "sub", text: `The ${s.top.length} 10-Ks filed in ${s.year} whose Risk Factors changed most from the year before, `
      + `out of ${fmt(s.filings)} filed so far.` }),
    el("div", { class: "card table-scroll" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", { class: "num", text: "#" }), el("th", { text: "Company" }),
        el("th", { text: "Year" }), el("th", { text: "Filed" }), el("th", { text: "Changed more than" }),
        el("th", { class: "num", text: "Words (before → after)" }))),
      el("tbody", {}, ...rows))),
    s.flagged_left_out ? el("p", { class: "note", text: `${s.flagged_left_out} filing(s) left out of this list because the company `
      + "only switched between “we” and “the Company”; they're still on their company pages." }) : null,
    howToRead());
  main.focus();
}

// ---------------------------------------------------------------- company page

function chart(years, selected, onPick) {
  const W = 640, H = 210, L = 46, R = 16, T = 14, B = 34;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "chart");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "How much the Risk Factors changed each year, as a rank among S&P 500 10-Ks");
  const x = i => years.length === 1 ? (L + W - R) / 2 : L + i * (W - L - R) / (years.length - 1);
  const y = p => T + (100 - p) * (H - T - B) / 100;
  const add = (tag, attrs, text) => {
    const n = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text != null) n.textContent = text;
    svg.append(n);
    return n;
  };
  for (const p of [0, 50, 90, 100]) {
    add("line", { x1: L, x2: W - R, y1: y(p), y2: y(p), class: "grid" });
    add("text", { x: L - 8, y: y(p) + 4, "text-anchor": "end" }, p + "%");
  }
  add("polyline", { class: "line", points: years.map((d, i) => `${x(i)},${y(d.change_percentile)}`).join(" ") });
  years.forEach((d, i) => {
    add("text", { x: x(i), y: H - 10, "text-anchor": "middle" }, "FY" + d.fiscal_year);
    const dot = add("circle", { cx: x(i), cy: y(d.change_percentile), r: 7, class: "dot" + (d === selected ? " sel" : ""),
      tabindex: "0", "aria-label": `FY${d.fiscal_year}: changed more than ${pct(d.change_percentile)}` });
    add("title", {}, `FY${d.fiscal_year}: changed more than ${pct(d.change_percentile)} of 10-Ks`);
    dot.addEventListener("click", () => onPick(d));
    dot.addEventListener("keydown", e => { if (e.key === "Enter") onPick(d); });
  });
  return svg;
}

function sentenceList(cls, title, items, empty) {
  return el("div", { class: cls },
    el("h3", { class: cls, text: `${title} (${fmt(items.length)})` }),
    items.length ? el("ol", {}, ...items.map(t => el("li", { text: t }))) : el("p", { class: "note", text: empty }));
}

function renderYear(company, d) {
  const box = el("div", { class: "card", id: "year" },
    el("h2", { text: `FY${d.fiscal_year} vs FY${d.prior_fiscal_year}`, style: "margin-top:0" }),
    el("div", {},
      d.live ? el("span", { class: "pill", text: "new filing" }) : null,
      flagPill(d.flags),
      d.summary_removed ? el("span", { class: "pill", text: "risk summary left out" }) : null),
    el("div", { class: "stats" },
      ...[["Changed more than", pct(d.change_percentile)], ["Cosine", d.scores.cosine.toFixed(3)],
          ["Jaccard", d.scores.jaccard.toFixed(3)], ["Min edit", d.scores.min_edit.toFixed(3)],
          ["Simple", d.scores.simple.toFixed(3)], ["Words", `${fmt(d.words[0])} → ${fmt(d.words[1])}`]]
        .map(([k, v]) => el("div", { class: "stat" }, el("div", { class: "k", text: k }), el("div", { class: "v", text: v })))),
    el("p", { class: "note" },
      `Filed ${d.filing_date}. ${fmt(d.kept)} sentences unchanged; ${fmt(d.moved)} only moved (not listed). `,
      el("a", { href: d.edgar, target: "_blank", rel: "noopener", text: `FY${d.fiscal_year} filing` }),
      d.prior_edgar ? " · " : null,
      d.prior_edgar ? el("a", { href: d.prior_edgar, target: "_blank", rel: "noopener", text: `FY${d.prior_fiscal_year} filing` }) : null,
      " (SEC EDGAR)"),
    el("div", { class: "diff" },
      sentenceList("old", "Dropped", d.dropped, "No sentences were dropped."),
      sentenceList("new", "New", d.new, "No new sentences.")));
  const old = document.getElementById("year");
  if (old) old.replaceWith(box); else main.append(box);
}

async function renderCompany(cik, wantYear) {
  main.replaceChildren(el("p", { class: "loading", text: "Loading…" }));
  let company;
  try {
    company = await getJSON(`data/c/${cik}.json`);
  } catch (e) {
    main.replaceChildren(el("h1", { text: "Company not found" }), el("p", {}, el("a", { href: "#", text: "Back to the start" })));
    return;
  }
  document.title = `${company.name} – 10-K Change Tracker`;
  const years = company.years;
  let selected = years.find(d => String(d.fiscal_year) === String(wantYear)) || years[years.length - 1];
  const chartBox = el("div", { class: "card" });
  const tableBody = el("tbody");
  const pick = d => {
    selected = d;
    history.replaceState(null, "", `#c=${cik}&y=${d.fiscal_year}`);
    draw();
    document.getElementById("year").scrollIntoView({ behavior: "smooth", block: "start" });
  };
  function draw() {
    chartBox.replaceChildren(el("h3", { text: "How much the Risk Factors changed each year" }), chart(years, selected, pick),
      el("p", { class: "note", text: "Rank among all S&P 500 10-Ks from fiscal 2021–2025: higher = more rewritten. Click a year for what changed." }));
    tableBody.replaceChildren(...years.slice().reverse().map(d => el("tr", {
        class: "clickable" + (d === selected ? " selected" : ""), tabindex: "0",
        onclick: () => pick(d), onkeydown: e => { if (e.key === "Enter") pick(d); } },
      el("td", {}, el("strong", { text: "FY" + d.fiscal_year }), " ", flagPill(d.flags)),
      el("td", {}, percentileBar(d.change_percentile), el("span", { text: pct(d.change_percentile) })),
      el("td", { class: "num", text: d.scores.cosine.toFixed(3) }),
      el("td", { class: "num", text: d.scores.jaccard.toFixed(3) }),
      el("td", { class: "num", text: d.scores.min_edit.toFixed(3) }),
      el("td", { class: "num", text: fmt(d.new.length) }),
      el("td", { class: "num", text: fmt(d.dropped.length) }))));
    renderYear(company, selected);
  }
  main.replaceChildren(
    el("p", {}, el("a", { href: "#", text: "← Biggest rewrites" })),
    el("h1", { text: company.name }),
    el("p", { class: "sub", text: [company.tickers.join(", "), company.sector].filter(Boolean).join(" · ") }),
    chartBox,
    el("div", { class: "card table-scroll" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", { text: "Year" }), el("th", { text: "Changed more than" }),
        el("th", { class: "num", text: "Cosine" }), el("th", { class: "num", text: "Jaccard" }),
        el("th", { class: "num", text: "Min edit" }), el("th", { class: "num", text: "New sentences" }),
        el("th", { class: "num", text: "Dropped" }))), tableBody)));
  draw();
  main.focus();
}

// ---------------------------------------------------------------- start

function route() {
  const params = new URLSearchParams(location.hash.slice(1));
  if (params.get("c")) renderCompany(params.get("c"), params.get("y"));
  else renderHome();
}

(async function start() {
  try {
    [state.companies, state.season, state.meta] = await Promise.all(
      [getJSON("data/companies.json"), getJSON("data/season.json"), getJSON("data/meta.json")]);
  } catch (e) {
    main.replaceChildren(el("p", { text: "The data couldn't be loaded. If you opened index.html directly from your disk, "
      + "run `python run.py preview-site` instead (browsers block local files)." }));
    return;
  }
  document.getElementById("built").textContent =
    `${fmt(state.meta.companies)} companies, ${fmt(state.meta.filings)} filings. Updated ${state.meta.built.replace("T", " ")}.`;
  window.addEventListener("hashchange", route);
  route();
})();
