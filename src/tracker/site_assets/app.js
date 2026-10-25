// 10-K Change Tracker: the dashboard page (D-038).
// Loads the small JSON files in data/ as needed. Text from filings is always inserted with
// textContent, never as HTML, so nothing in a 10-K can run as code on this page.
// Animations respect the visitor's "reduce motion" setting.
"use strict";

const state = { companies: [], meta: null, season: null, cache: {} };
const main = document.getElementById("main");
const SVG = "http://www.w3.org/2000/svg";
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---------------------------------------------------------------- helpers

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "style") node.style.cssText = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) if (child != null && child !== false) node.append(child);
  return node;
}

function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
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

const fmt = n => Math.round(n).toLocaleString("en-US");
const pct = p => (p >= 99.95 ? ">99.9" : p.toFixed(1)) + "%";
// SEC lists many names in capitals ("UNION PACIFIC CORP /DE/"): drop the state tag and use normal case,
// keeping short acronyms ("IBM", "AT&T", "CVS") as they are.
const LOWER_OK = new Set(["INC", "CO", "LTD", "THE", "AND", "OF", "PLC", "LLC", "CORP", "NEW", "LP"]);
function clean(name) {
  let n = (name || "").replace(/\s+[\/\\][A-Z]{2,3}[\/\\]?\s*$/, "").replace(/\s+/g, " ").trim();
  if (n && n === n.toUpperCase()) {
    n = n.split(" ").map(w => {
      const letters = w.replace(/[^A-Z]/g, "");
      if (/[&\d]/.test(w) || (letters.length <= 3 && !LOWER_OK.has(letters))) return w;
      return w.charAt(0) + w.slice(1).toLowerCase();
    }).join(" ");
  }
  return n;
}

// Shared gradients for the rings and the chart, defined once for the whole page.
function installGradients() {
  const defs = svgEl("svg", { width: 0, height: 0, "aria-hidden": "true", style: "position:absolute" });
  defs.innerHTML = `<defs>
    <linearGradient id="ring-gradient" x1="0" y1="0" x2="1" y2="1"><stop offset="0" style="stop-color:var(--accent-2)"/><stop offset="1" style="stop-color:var(--accent)"/></linearGradient>
    <linearGradient id="line-gradient" x1="0" y1="0" x2="1" y2="0"><stop offset="0" style="stop-color:var(--accent-2)"/><stop offset="1" style="stop-color:var(--accent)"/></linearGradient>
    <linearGradient id="area-gradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:var(--accent);stop-opacity:0.28"/><stop offset="1" style="stop-color:var(--accent);stop-opacity:0"/></linearGradient>
  </defs>`;
  document.body.prepend(defs);
}

// Count a number up from zero when it scrolls into view.
function countUp(node, target, format = fmt, duration = 1100) {
  if (reduceMotion) { node.textContent = format(target); return; }
  node.textContent = format(0);
  const start = performance.now();
  const step = now => {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    node.textContent = format(target * eased);
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// Fade sections in as they scroll into view; run `onShow` once when they appear.
const observer = "IntersectionObserver" in window ? new IntersectionObserver(entries => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    entry.target.classList.add("in");
    const show = entry.target._onShow;
    if (show) { entry.target._onShow = null; show(); }
    observer.unobserve(entry.target);
  }
}, { threshold: 0.12 }) : null;

function reveal(node, onShow, delay = 0) {
  node.classList.add("reveal");
  if (delay) node.style.transitionDelay = delay + "ms";
  node._onShow = onShow || null;
  if (observer && !reduceMotion) observer.observe(node);
  else { node.classList.add("in"); if (onShow) onShow(); }
  return node;
}

// A circular gauge that fills to `p` percent.
function ring(p, label, size) {
  const r = 30, c = 2 * Math.PI * r;
  const svg = svgEl("svg", { viewBox: "0 0 74 74", "aria-hidden": "true" });
  svg.append(svgEl("circle", { cx: 37, cy: 37, r, fill: "none", class: "track", "stroke-width": 7 }));
  const value = svgEl("circle", { cx: 37, cy: 37, r, fill: "none", class: "value", "stroke-width": 7,
                                  "stroke-dasharray": c, "stroke-dashoffset": c });
  svg.append(value);
  const node = el("div", { class: "ring", style: size ? `--size:${size}px` : null }, svg, label);
  node._fill = () => { value.style.strokeDashoffset = String(c * (1 - p / 100)); };
  return node;
}

// How much the section grew or shrank: last year's length and this year's, as two bars.
function lengthChange(before, after) {
  const max = Math.max(before, after, 1);
  const change = (after - before) / Math.max(before, 1) * 100;
  const was = el("span", { class: "was" }), now = el("span", { class: "now" });
  const node = el("div", { class: "len", title: `${fmt(before)} → ${fmt(after)} words` },
    el("div", { class: "len-bars", "aria-hidden": "true" }, el("div", {}, was), el("div", {}, now)),
    el("span", { class: "len-val " + (change >= 0 ? "up" : "down"),
                 text: (change >= 0 ? "+" : "−") + Math.abs(change).toFixed(0) + "%" }));
  node._fill = () => { was.style.width = (before / max * 100) + "%"; now.style.width = (after / max * 100) + "%"; };
  return node;
}

function voiceChip(flags) {
  if (!flags) return null;
  return el("span", { class: "chip warn", title: "The company switched between “we” and “the Company”. "
    + "Every sentence about it is reworded, so the score overstates the change in its risks." }, "we ↔ the Company");
}

const icons = {
  compare: '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M4 6h7M4 12h7M4 18h7M15 6h5M15 12h5M15 18h5" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/></svg>',
  rank: '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M5 20V12M12 20V5M19 20v-9" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" fill="none"/></svg>',
  read: '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M4 5h6a3 3 0 0 1 3 3v11a2 2 0 0 0-2-2H4zM20 5h-6a3 3 0 0 0-3 3v11a2 2 0 0 1 2-2h7z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" fill="none"/></svg>',
};
function icon(name) {
  const node = el("div", { class: "icon", "aria-hidden": "true" });
  node.innerHTML = icons[name];   // fixed markup from this file, never data
  return node;
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
  return starts.concat(contains).slice(0, 8);
}

function showSuggestions() {
  const found = matches(input.value);
  list.replaceChildren(...found.map((c, i) => el("li", {
    role: "option", "aria-selected": String(i === active),
    onmousedown: e => { e.preventDefault(); go(c.cik); },
  }, el("span", { text: clean(c.name) }), el("span", { class: "tick", text: c.tickers.join(", ") }))));
  list.hidden = found.length === 0;
  return found;
}

input.addEventListener("input", () => { active = -1; showSuggestions(); });
input.addEventListener("keydown", e => {
  const found = matches(input.value);
  if (e.key === "ArrowDown") { active = Math.min(active + 1, found.length - 1); showSuggestions(); e.preventDefault(); }
  else if (e.key === "ArrowUp") { active = Math.max(active - 1, 0); showSuggestions(); e.preventDefault(); }
  else if (e.key === "Enter" && found.length) { go(found[Math.max(active, 0)].cik); }
  else if (e.key === "Escape") { list.hidden = true; input.blur(); }
});
input.addEventListener("blur", () => { list.hidden = true; });
document.addEventListener("keydown", e => {
  if (e.key === "/" && document.activeElement !== input) { e.preventDefault(); input.focus(); }
});

function go(cik, year) {
  list.hidden = true;
  input.value = "";
  input.blur();
  location.hash = year ? `c=${cik}&y=${year}` : `c=${cik}`;
}

// ---------------------------------------------------------------- home page

function renderHome() {
  document.title = "10-K Change Tracker";
  const s = state.season, m = state.meta;
  const top3 = s.top.slice(0, 3), rest = s.top.slice(3);

  const kpi = (label, value, format, sub) => {
    const v = el("div", { class: "v", text: "0" });
    const node = el("div", { class: "kpi" }, el("div", { class: "k", text: label }), v, el("div", { class: "s", text: sub }));
    return reveal(node, () => countUp(v, value, format));
  };

  const hero = el("section", { class: "hero" },
    el("span", { class: "eyebrow" }, el("span", { class: "dot" }), `${s.year} filing season · live`),
    el("h1", {}, "Who rewrote their ", el("span", { class: "gradient-text", text: "risk factors" }), "?"),
    el("p", { class: "lede", text: "Every year, S&P 500 companies file a 10-K with a section on what could go wrong. "
      + "Most copy last year's almost word for word. This tracks the ones that don't, and shows exactly what they changed." }),
    el("div", { class: "kpis" },
      kpi("Companies tracked", m.companies, fmt, "S&P 500 members, 2021 to today"),
      kpi("10-Ks compared", m.filings, fmt, "each against its prior year"),
      kpi("Typical 10-K keeps", m.research_cosine_median * 100, v => v.toFixed(1) + "%", "of last year's wording (cosine)"),
      kpi(`Filed in ${s.year}`, s.filings, fmt, "so far this season")));

  const podium = el("div", { class: "podium" }, ...top3.map((f, i) => {
    const r = ring(f.change_percentile, el("span", { class: "label", text: pct(f.change_percentile).replace(">", "") }));
    const card = el("article", { class: "podium-card", tabindex: "0", role: "link",
        "aria-label": `${clean(f.name)}, fiscal ${f.fiscal_year}: changed more than ${pct(f.change_percentile)} of 10-Ks`,
        onclick: () => go(f.cik, f.fiscal_year), onkeydown: e => { if (e.key === "Enter") go(f.cik, f.fiscal_year); },
        onpointermove: e => {
          const b = card.getBoundingClientRect();
          card.style.setProperty("--mx", `${e.clientX - b.left}px`);
          card.style.setProperty("--my", `${e.clientY - b.top}px`);
        } },
      el("div", { class: "podium-top" }, el("span", { class: "rank", text: String(i + 1) }), r),
      el("div", {}, el("h3", { text: clean(f.name) }),
        el("div", { class: "meta", text: `FY${f.fiscal_year} · filed ${f.filing_date}` })),
      el("div", { class: "meta num", text: `${fmt(f.words[0])} → ${fmt(f.words[1])} words` }));
    return reveal(card, () => r._fill(), i * 90);
  }));

  const bars = [];
  const rows = rest.map((f, i) => {
    const bar = lengthChange(f.words[0], f.words[1]);
    bars.push(bar);
    return el("li", { tabindex: "0", onclick: () => go(f.cik, f.fiscal_year),
        onkeydown: e => { if (e.key === "Enter") go(f.cik, f.fiscal_year); } },
      el("span", { class: "pos", text: String(i + 4) }),
      el("div", { class: "who" }, el("strong", { text: clean(f.name) }), el("span", { text: `FY${f.fiscal_year} · filed ${f.filing_date}` })),
      el("span", { class: "pctl", text: pct(f.change_percentile) }),
      bar,
      el("span", { class: "words", text: `${fmt(f.words[0])} → ${fmt(f.words[1])} words` }));
  });
  const listCard = el("div", { class: "card" },
    el("div", { class: "ranked-head", "aria-hidden": "true" }, el("span"), el("span", { text: "Company" }),
      el("span", { text: "Changed more than" }), el("span", { text: "Length, last year → this year" }), el("span")),
    el("ol", { class: "ranked" }, ...rows));
  reveal(listCard, () => bars.forEach((b, i) => setTimeout(() => b._fill(), i * 45)));

  const steps = el("div", { class: "steps" },
    ...[["compare", "Compared with last year", "Each 10-K's Risk Factors are matched against the same company's previous 10-K, word for word. Summaries and numbers are left out, so “2024” → “2025” isn't a change."],
        ["rank", "Ranked against everyone", "“Changed more than 90%” means only 10% of S&P 500 10-Ks from fiscal 2021–2025 were rewritten more."],
        ["read", "Read what changed", "Each company page lists the genuinely new risk language, what was dropped, and the sentences that were edited, with the changed words marked."]]
      .map(([ic, h, p], i) => reveal(el("div", { class: "step" }, icon(ic), el("h3", { text: h }), el("p", { text: p })), null, i * 80)));

  const page = el("div", { class: "page" },
    el("div", { class: "wrap" },
      hero,
      el("div", { class: "section-head" }, el("div", {}, el("h2", { text: `Biggest rewrites of ${s.year}` }),
        el("p", { text: `The ${s.top.length} 10-Ks whose Risk Factors changed most from the year before.` }))),
      podium,
      el("div", { style: "height:18px" }),
      listCard,
      s.flagged_left_out ? el("p", { class: "note", text: `${s.flagged_left_out} filing(s) left out because the company only `
        + "switched between “we” and “the Company”; they're still on their company pages." }) : null,
      el("div", { class: "section-head" }, el("div", {}, el("h2", { text: "How it works" }),
        el("p", { text: "Based on the research paper Lazy Prices (Cohen, Malloy & Nguyen, 2020). Backtest results: coming soon." }))),
      steps));
  main.replaceChildren(page);
  main.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

// ---------------------------------------------------------------- company page

function chart(years, selected, onPick) {
  const W = 640, H = 240, L = 44, R = 18, T = 20, B = 36;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img",
    "aria-label": "How much the Risk Factors changed each year, as a rank among S&P 500 10-Ks" });
  const x = i => years.length === 1 ? (L + W - R) / 2 : L + i * (W - L - R) / (years.length - 1);
  const y = p => T + (100 - p) * (H - T - B) / 100;
  for (const p of [0, 25, 50, 75, 100]) {
    svg.append(svgEl("line", { x1: L, x2: W - R, y1: y(p), y2: y(p), class: "grid" }));
    const t = svgEl("text", { x: L - 10, y: y(p) + 4, "text-anchor": "end" });
    t.textContent = p + "%";
    svg.append(t);
  }
  const pts = years.map((d, i) => [x(i), y(d.change_percentile)]);
  if (pts.length > 1) {
    svg.append(svgEl("path", { class: "area",
      d: `M${pts[0][0]},${y(0)} ` + pts.map(([a, b]) => `L${a},${b}`).join(" ") + ` L${pts[pts.length - 1][0]},${y(0)} Z` }));
  }
  const line = svgEl("polyline", { class: "line", points: pts.map(p => p.join(",")).join(" ") });
  svg.append(line);
  const tip = el("div", { class: "tooltip", role: "status" });
  const wrap = el("div", { class: "chart-wrap" }, svg, tip);
  years.forEach((d, i) => {
    const label = svgEl("text", { x: x(i), y: H - 12, "text-anchor": "middle" });
    label.textContent = "FY" + d.fiscal_year;
    svg.append(label);
    if (d === selected) svg.append(svgEl("circle", { cx: pts[i][0], cy: pts[i][1], r: 16, class: "halo" }));
    const dot = svgEl("circle", { cx: pts[i][0], cy: pts[i][1], r: 7, class: "dot" + (d === selected ? " sel" : ""),
      tabindex: "0", role: "button", "aria-label": `FY${d.fiscal_year}: changed more than ${pct(d.change_percentile)}` });
    dot.style.transitionDelay = (reduceMotion ? 0 : 500 + i * 110) + "ms";
    const show = () => {
      tip.textContent = `FY${d.fiscal_year} · changed more than ${pct(d.change_percentile)}`;
      tip.style.left = (pts[i][0] / W * 100) + "%";
      tip.style.top = (pts[i][1] / H * 100) + "%";
      tip.classList.add("show");
    };
    dot.addEventListener("mouseenter", show);
    dot.addEventListener("focus", show);
    dot.addEventListener("mouseleave", () => tip.classList.remove("show"));
    dot.addEventListener("blur", () => tip.classList.remove("show"));
    dot.addEventListener("click", () => onPick(d));
    dot.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(d); } });
    svg.append(dot);
  });
  wrap._draw = (animate) => {
    if (animate && !reduceMotion) {
      const length = line.getTotalLength ? line.getTotalLength() : 1000;
      line.style.strokeDasharray = length;
      line.style.strokeDashoffset = length;
      line.getBoundingClientRect();
      requestAnimationFrame(() => { line.style.strokeDashoffset = "0"; svg.classList.add("drawn"); });
    } else {
      svg.classList.add("drawn");
    }
  };
  return wrap;
}

function sentenceItems(items, kind) {
  return items.map((t, i) => {
    const li = el("li", { text: t });
    li.style.animationDelay = Math.min(i, 12) * 35 + "ms";
    return li;
  });
}

function editItems(edits) {
  return edits.shown.map((segments, i) => {
    const li = el("li", {}, ...segments.map(([op, text]) =>
      op === "=" ? document.createTextNode(` ${text} `) : el(op === "+" ? "ins" : "del", { text })));
    li.style.animationDelay = Math.min(i, 12) * 35 + "ms";
    return li;
  });
}

function changesPanel(d) {
  const kinds = [
    ["new", "New risk language", d.new.length],
    ["dropped", "Dropped", d.dropped.length],
    ["edited", "Edited", d.edits.count],
  ];
  const indicator = el("span", { class: "tab-indicator", "aria-hidden": "true" });
  const body = el("div", { role: "tabpanel" });
  const tabs = el("div", { class: "tabs", role: "tablist", "aria-label": "What changed" }, indicator);
  const buttons = kinds.map(([kind, label, count]) => el("button", { class: "tab", role: "tab", "data-kind": kind,
      "aria-selected": "false", type: "button", onclick: () => select(kind) },
    label, el("span", { class: "count", text: fmt(count) })));
  tabs.append(...buttons);

  function select(kind) {
    buttons.forEach(b => b.setAttribute("aria-selected", String(b.dataset.kind === kind)));
    const btn = buttons.find(b => b.dataset.kind === kind);
    indicator.style.left = btn.offsetLeft + "px";
    indicator.style.width = btn.offsetWidth + "px";
    if (kind === "edited") {
      const more = d.edits.count - d.edits.shown.length;
      body.replaceChildren(d.edits.count
        ? el("ol", { class: "sentences edited" }, ...editItems(d.edits)) : el("div", { class: "empty", text: "No sentences were edited." }),
        more > 0 ? el("p", { class: "note", text: `Showing the first ${d.edits.shown.length} edits. ${fmt(more)} more are in the filings on EDGAR.` }) : null);
    } else {
      const items = kind === "new" ? d.new : d.dropped;
      body.replaceChildren(items.length ? el("ol", { class: `sentences ${kind}` }, ...sentenceItems(items, kind))
        : el("div", { class: "empty", text: kind === "new" ? "No genuinely new sentences." : "Nothing was dropped." }));
    }
  }
  const panel = el("div", {}, tabs, body);
  panel._init = () => select(d.new.length || !d.edits.count ? "new" : "edited");
  return panel;
}

function yearDetail(company, d) {
  const tiles = el("div", { class: "tiles" },
    ...[["Cosine", d.scores.cosine.toFixed(3)], ["Jaccard", d.scores.jaccard.toFixed(3)],
        ["Min edit", d.scores.min_edit.toFixed(3)], ["Simple", d.scores.simple.toFixed(3)],
        ["Words", `${fmt(d.words[0])} → ${fmt(d.words[1])}`], ["Unchanged", fmt(d.kept)]]
      .map(([k, v]) => el("div", { class: k === "Words" ? "tile words" : "tile" },
        el("div", { class: "k", text: k }), el("div", { class: "v", text: v }))));
  const panel = changesPanel(d);
  const card = el("section", { class: "card", id: "year" },
    el("div", { class: "section-head", style: "margin-top:0" },
      el("div", {}, el("h2", { text: `FY${d.fiscal_year} vs FY${d.prior_fiscal_year}` }),
        el("p", {}, `Filed ${d.filing_date} · `,
          el("a", { href: d.edgar, target: "_blank", rel: "noopener", text: `FY${d.fiscal_year} filing` }),
          d.prior_edgar ? " · " : null,
          d.prior_edgar ? el("a", { href: d.prior_edgar, target: "_blank", rel: "noopener", text: `FY${d.prior_fiscal_year} filing` }) : null)),
      el("div", { class: "chips" },
        el("span", { class: "chip accent", text: `Changed more than ${pct(d.change_percentile)}` }),
        d.live ? el("span", { class: "chip new", text: "New filing" }) : null,
        voiceChip(d.flags),
        d.summary_removed ? el("span", { class: "chip", text: "Risk summary left out" }) : null)),
    tiles,
    el("div", { style: "height:18px" }),
    panel,
    el("p", { class: "note", text: `“New” and “Dropped” have no close match in the other year; a sentence reworded but `
      + `sharing at least half its words is under “Edited”. ${fmt(d.moved)} sentences only moved and aren't listed.` }));
  card._init = () => panel._init();
  return card;
}

async function renderCompany(cik, wantYear) {
  main.replaceChildren(el("div", { class: "wrap" }, el("div", { class: "skeleton" })));
  let company;
  try {
    company = await getJSON(`data/c/${cik}.json`);
  } catch (e) {
    main.replaceChildren(el("div", { class: "wrap page" }, el("div", { class: "hero" },
      el("h1", { text: "Company not found" }), el("p", {}, el("a", { href: "#", text: "Back to the start" })))));
    return;
  }
  const name = clean(company.name);
  document.title = `${name} – 10-K Change Tracker`;
  const years = company.years;
  let selected = years.find(d => String(d.fiscal_year) === String(wantYear)) || years[years.length - 1];

  const chartCard = el("div", { class: "card" });
  const gaugeCard = el("div", { class: "card gauge-card" });
  const yearButtons = el("div", { class: "years", role: "group", "aria-label": "Choose a year" });
  const tableBody = el("tbody");
  const detailSlot = el("div");

  const pick = (d, scroll = true) => {
    selected = d;
    history.replaceState(null, "", `#c=${cik}&y=${d.fiscal_year}`);
    draw(false);
    if (scroll) document.getElementById("year").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
  };

  function draw(first) {
    const c = chart(years, selected, pick);
    chartCard.replaceChildren(el("h3", { text: "How much the Risk Factors changed, year by year" }),
      el("p", { class: "sub", text: "Rank among all S&P 500 10-Ks from fiscal 2021–2025. Higher = more rewritten. Click a point." }), c);
    if (first) reveal(chartCard, () => c._draw(true)); else c._draw(false);

    const r = ring(selected.change_percentile,
      el("span", { class: "label", text: pct(selected.change_percentile).replace(">", "") }), 150);
    gaugeCard.replaceChildren(el("h3", { text: `FY${selected.fiscal_year}` }), r,
      el("p", { class: "sub", text: `${name}'s FY${selected.fiscal_year} Risk Factors changed more than `
        + `${pct(selected.change_percentile)} of S&P 500 10-Ks from fiscal 2021–2025.` }));
    if (first) reveal(gaugeCard, () => r._fill(), 120); else requestAnimationFrame(() => r._fill());

    yearButtons.replaceChildren(...years.map(d => el("button", { class: "year-btn", type: "button",
      "aria-pressed": String(d === selected), onclick: () => pick(d, false), text: "FY" + d.fiscal_year })));

    tableBody.replaceChildren(...years.slice().reverse().map(d => el("tr", {
        class: d === selected ? "selected" : null, tabindex: "0",
        onclick: () => pick(d), onkeydown: e => { if (e.key === "Enter") pick(d); } },
      el("td", {}, el("strong", { text: "FY" + d.fiscal_year }), " ", voiceChip(d.flags)),
      el("td", {}, el("span", { class: "num", text: pct(d.change_percentile) })),
      el("td", { class: "r", text: d.scores.cosine.toFixed(3) }),
      el("td", { class: "r", text: d.scores.jaccard.toFixed(3) }),
      el("td", { class: "r", text: d.scores.min_edit.toFixed(3) }),
      el("td", { class: "r", text: fmt(d.new.length) }),
      el("td", { class: "r", text: fmt(d.dropped.length) }),
      el("td", { class: "r", text: fmt(d.edits.count) }))));

    const detail = yearDetail(company, selected);
    detailSlot.replaceChildren(detail);
    detail._init();
  }

  const page = el("div", { class: "page" }, el("div", { class: "wrap" },
    el("a", { class: "back", href: "#" }, "← Biggest rewrites"),
    el("section", { class: "company-hero" },
      el("h1", { text: name }),
      el("div", { class: "chips" },
        ...company.tickers.map(t => el("span", { class: "chip accent", text: t })),
        company.sector ? el("span", { class: "chip", text: company.sector }) : null,
        el("span", { class: "chip", text: `${years.length} year${years.length === 1 ? "" : "s"} compared` }))),
    el("div", { class: "split" }, chartCard, gaugeCard),
    el("div", { class: "section-head" }, el("div", {}, el("h2", { text: "What changed" }),
      el("p", { text: "Pick a year to see its new, dropped and edited sentences." }))),
    yearButtons,
    detailSlot,
    el("div", { class: "section-head" }, el("div", {}, el("h2", { text: "All years" }),
      el("p", { text: "The four similarity measures from Lazy Prices; 1 = identical to the year before." }))),
    reveal(el("div", { class: "card table-scroll" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", { text: "Year" }), el("th", { text: "Changed more than" }),
        el("th", { class: "r", text: "Cosine" }), el("th", { class: "r", text: "Jaccard" }),
        el("th", { class: "r", text: "Min edit" }), el("th", { class: "r", text: "New" }),
        el("th", { class: "r", text: "Dropped" }), el("th", { class: "r", text: "Edited" }))), tableBody)))));
  main.replaceChildren(page);
  draw(true);
  main.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

// ---------------------------------------------------------------- start

function route() {
  const params = new URLSearchParams(location.hash.slice(1));
  if (params.get("c")) renderCompany(params.get("c"), params.get("y"));
  else renderHome();
}

(async function start() {
  installGradients();
  try {
    [state.companies, state.season, state.meta] = await Promise.all(
      [getJSON("data/companies.json"), getJSON("data/season.json"), getJSON("data/meta.json")]);
  } catch (e) {
    main.replaceChildren(el("div", { class: "wrap" }, el("div", { class: "card", style: "margin-top:48px" },
      el("p", { text: "The data couldn't be loaded. If you opened index.html directly from your disk, "
        + "run `python run.py preview-site` instead (browsers block local files)." }))));
    return;
  }
  document.getElementById("built").textContent =
    `${fmt(state.meta.companies)} companies · ${fmt(state.meta.filings)} filings · updated ${state.meta.built.replace("T", " ")}`;
  window.addEventListener("hashchange", route);
  route();
})();
