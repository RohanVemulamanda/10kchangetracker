# Phase 5 report: live updates and the dashboard

Built 2026-10-25. Choices are explained in [DECISIONS.md](../DECISIONS.md) (D-036 to D-038). **Not published yet:** the site is built locally and waits for Rohan's go-ahead.

## 1. What we built

**`python run.py update`:** keeps the tracker current (D-036).
1. Reads today's S&P 500 list from Wikipedia. The list includes each company's SEC ID, so no ticker matching is needed. A list that doesn't look like the S&P 500 (fewer than 490 or more than 520 rows, or missing IDs) is refused.
2. Fetches each member's filing list fresh from SEC and picks 10-Ks with the Phase 1 rules.
3. Adds only filings that aren't stored yet, marked `live`, then downloads, extracts and scores them with the Phase 2–3 rules.
4. Writes `reports/live_review.csv`: new filings that need a look before they reach the dashboard (D-037):
   - extraction problems
   - first-ever 10-Ks
   - voice switches
   - changes more extreme than 99% of the research sample

**`python run.py build-site`:** builds the dashboard as a static website in `site/` (D-038):
- **Home page:** "Biggest rewrites" of the latest filing season, with voice switches left out of the ranking and labelled.
- **A page per company:** a chart of how much its Risk Factors changed each year, shown as a rank against all S&P 500 10-Ks from fiscal 2021–2025; the four scores; links to both filings on EDGAR; and three lists:
  - **new risk language:** sentences with no close match the year before
  - **dropped sentences**
  - **edited sentences,** with the changed words marked
- A search box for companies and tickers, a "how to read this" note, and a backtest section marked "pending".

`python run.py preview-site` shows it at http://localhost:8000.

## 2. How we checked it

1. **The research sample can't move.** Before and after both live updates, the counts and a fingerprint of all 4,988 research scores were identical. Live rows have their own role (`live`), the Phase 3 report and Phase 4 read only `sample`, and live mode never edits a research row (tested).
2. **Every review item was checked by hand.** The first update found 174 new filings from 82 companies (all downloaded, none failed to extract), and 18 went on the review list:
   - **5 Ares/KKR filings:** the known "long" flag.
   - **3 extreme changes, all real:** Flex's heavy rewrite, Ciena cutting its risk factors to a third, and EchoStar's DISH merger.
   - **10 first-ever 10-Ks:** IPOs, spin-offs and mergers.

   Two of those first-ever 10-Ks weren't really new. **Marvell** and **Ferguson** had moved to a new legal parent, the case D-018 covers. Both were added to `predecessors.csv` with evidence, and the second update linked and scored them.
3. **Tests:** parsing Wikipedia's table (including a changed layout, which must fail loudly), which filings are added or relinked, the review rules, the site data (held-back and approved filings, the season ranking), the new/dropped/edited split and the word marking. 251 tests in all.
4. **The site:** the page code passes a syntax check; every file is served with the right type from a local server; the data spot-checks are sensible (Apple: big changes in fiscal 2021 and 2025, quiet years between).

### Something the build turned up

62% of "new" sentences were light edits of a dropped sentence (often one or two words). Listing them as new and dropped hid the genuinely new language and made the site 144 MB. Showing edits as their own list made the pages more useful and the site 60 MB.

## 3. What to say in an interview

> "The last part turns the research into a tool. A command checks SEC for new 10-Ks from today's S&P 500 members and runs them through the same extraction and scoring rules. New filings are kept apart from the research sample, so the backtest results can't change as data arrives; I verified that with a fingerprint of every research score before and after each update. Anything unusual (a failed extraction, an extreme change, a company's first 10-K) goes on a review list before it reaches the dashboard. That check caught two companies, Marvell and Ferguson, that had only moved to a new legal parent, which would otherwise have looked like brand-new companies.
>
> The dashboard is a static website. For each company it shows how much the Risk Factors changed each year, ranked against all S&P 500 filings, and the actual new, dropped and edited sentences. Separating edits from genuinely new text mattered: almost two thirds of 'new' sentences were small rewordings."

## Limitations to disclose

- **Not published yet**, and not yet looked at in a browser by a person.
- **Updates run by hand.** The dashboard is only as current as the last `update` run.
- **Today's S&P 500 list comes from Wikipedia** and is checked only for plausibility (row count and IDs), not against S&P's official list.
- **The review list needs a person.** New filings with problems stay off the dashboard until checked, so the dashboard can lag after an update.
- **The rank is against fiscal 2021–2025 filings.** If 10-K writing changes over time, the rank of future filings drifts in meaning.
- **The Loughran–McDonald counts are not shown** (license, D-032), and the backtest section is pending until Phase 4 has price data.
