# Macro Thesis Tracker — Monthly Filling Guide

**Purpose**: keep `macro_thesis_tracker.xlsx` current with predictable monthly effort. Pull this doc up at the start of each refresh cycle and follow the chronology.

**State of the workbook**:
- **402 cells** auto-fill from FRED + Yahoo via `macro_tracker_fill.py`
- **~320 cells** require manual entry (sources below have no programmatic feed)
- **70 cells** are typically "data unavailable" (future months FRED hasn't published yet, or pre-2025 hyperscaler quarters)
- **Thesis Dashboard** (sheet 4) is structurally complete but its 10 thesis legs and 8 key ratios are human-curated each month

---

## Section 1 — Monthly refresh timeline

Data sources publish at known points in the month. Run the auto-fill + manual entry workflow **incrementally** as releases drop, not in one end-of-month scramble.

| When | What | Source | Action |
|---|---|---|---|
| **1st Thursday** | Challenger Job Cuts (prev month) | challengergray.com PR | Add Total + AI-tagged to `manual_overrides.json`, re-run filler |
| **1st Friday** | BLS Jobs Report (prev month) | FRED (auto) | Re-run `python macro_tracker_fill.py` — picks up nominal AHE → Real Wage Growth |
| **~10th** | JOLTS (2-month lag) | FRED (auto) | Re-run filler |
| **2nd Wednesday** | CPI release (prev month) | FRED (auto) | Re-run filler — updates Core CPI, CPI Food/Energy, Supercore, Real Wage Growth |
| **Last Friday** | PCE release (prev month) | FRED (auto) | Re-run filler — last monthly auto-fill of the cycle |
| **Hyperscaler earnings** (varies) | MSFT/GOOG/AMZN/META quarterly | Yahoo timeseries (auto) | Re-run filler after each major print |
| **Hyperscaler earnings** (varies) | NVDA/AMD segment data | Press release | Manual entry into `manual_overrides.json` |
| **Monthly when new pricing** | API price changes | Anthropic/OpenAI/Google pricing pages | Manual entry |
| **End of month** | Sweep remaining manuals + Thesis Dashboard | (see Sections 3-4) | Final re-run + dashboard update |

The auto-fill script is **idempotent** — safe to re-run after every release. Each run takes ~30-60 seconds.

---

## Section 2 — Auto-fill pass (5 minutes)

```bash
cd d:\AI-finance\ai-hedgefund\cowork-1
python macro_tracker_fill.py
```

**Expected output (as of the latest baseline)**:
```
Auto-filled:        402
Manual-needed:      ~320  (edit manual_overrides.json)
Data unavailable:   ~70   (future months not yet published)
FRED series cached: 27
Yahoo tickers:      4
```

**If you see numbers materially off from these**:
- `Auto-filled` much lower → FRED or Yahoo endpoint may be down; re-run in an hour
- `Data unavailable` higher than ~70 → FRED revised down available history; check stderr for series-specific errors
- Stack trace → `manual_overrides.json` may be malformed; restore from git or re-scaffold by deleting it and re-running

**Important**: close `macro_thesis_tracker.xlsx` in Excel before running. The script refuses to save if the file is locked.

---

## Section 3 — Manual entry guide

All manual entries go into `cowork-1/manual_overrides.json` keyed by exact metric label (matching column A in the workbook). Then re-run `python macro_tracker_fill.py` to push them into the cells.

**Critical**: the metric label in the JSON must match column A *exactly* — capitalization, parens, hyphens. If a key has a typo, the value silently doesn't apply.

---

### Priority 1 — API Pricing (85 cells, monthly cadence)

**Rows in workbook**: 28-32 (Monthly Metrics sheet)

| Row | Metric | Provider | Page |
|---|---|---|---|
| 28 | Anthropic API Price - Frontier (per 1M input tokens) | Anthropic | https://docs.anthropic.com/en/docs/about-claude/pricing |
| 29 | Anthropic API Price - Frontier (per 1M output tokens) | Anthropic | same |
| 30 | OpenAI API Price - Frontier (per 1M input tokens) | OpenAI | https://openai.com/api/pricing/ |
| 31 | OpenAI API Price - Frontier (per 1M output tokens) | OpenAI | same |
| 32 | Google Gemini API - Frontier (per 1M input tokens) | Google | https://ai.google.dev/pricing |

**"Frontier" definition**: the most expensive/capable flagship model offered for general API use at the time. As of current — Anthropic: Opus 4.7 / OpenAI: GPT-5 or o3 / Google: Gemini 2.x Pro. **When a new flagship launches mid-month**, use the new price starting that month forward; keep the prior model's price for prior months.

**Backfilling history (Wayback Machine workflow)**:
1. Go to `https://web.archive.org/web/{YYYYMMDD}/{pricing_url}` — pick a mid-month date like 15th
2. Example: `https://web.archive.org/web/20250115/https://docs.anthropic.com/en/docs/about-claude/pricing`
3. If no snapshot exists for that day, Wayback picks the nearest one
4. Note the input/output token price for the flagship of that period
5. Repeat for each month in the workbook

**JSON format**:
```json
"Anthropic API Price - Frontier (per 1M input tokens)": {
  "Jan-25": 3.00,
  "Feb-25": 3.00,
  "Mar-25": 3.00,
  ...
}
```

Values are in USD. No `$` sign in the JSON — the workbook formats the column.

---

### Priority 2 — Challenger Job Cuts (34 cells, monthly cadence)

**Rows in workbook**: 24, 25 (Monthly Metrics)

| Row | Metric | What to capture |
|---|---|---|
| 24 | Challenger Job Cuts (Total) | Top-line total cuts for the month, in 000s |
| 25 | Challenger Job Cuts (AI/Tech-Related) | "AI" reason from the cuts-by-reason breakdown |

**Source**: https://www.challengergray.com/blog/ → search for "Job Cuts Report"

**Cadence**: released first Thursday of each month, covers the prior month's data.

**Where to find the numbers in each report**:
1. **Total cuts** — first paragraph of the PR usually says "Employers announced X cuts in [month]"
2. **AI-tagged cuts** — there's a "Job Cuts by Reason" table; "Artificial Intelligence" became its own reason category in 2023. Pull that row's monthly value.
3. **Tech-related** — if AI isn't broken out for a month, fall back to "Technological Updates" reason category as a proxy and note this in the cell comment

**JSON format** (values in 000s, so 50,000 cuts = `50`):
```json
"Challenger Job Cuts (Total)": {
  "Jan-25": 49.795,
  "Feb-25": 172.017,
  ...
},
"Challenger Job Cuts (AI/Tech-Related)": {
  "Jan-25": 0.0,
  "Feb-25": 0.062,
  ...
}
```

**Tip**: Challenger sometimes embeds numbers only in the PDF, not the HTML. Open the PDF and search for the month name. Their numbers are reported in absolute count (e.g. "50,432") — convert to thousands for the JSON.

---

### Priority 3 — AI Company ARR / Valuations (50 cells, quarterly cadence)

**Rows in workbook**: 36-40 (Quarterly Metrics)

| Row | Metric | Frequency to update |
|---|---|---|
| 36 | OpenAI ARR (est.) | Quarterly (leaks usually at quarter-end) |
| 37 | OpenAI Gross Margin (est.) | When leaked (irregular) |
| 38 | Anthropic ARR (est.) | Quarterly |
| 39 | Anthropic Valuation (Last Round) | When a round closes |
| 40 | OpenAI Valuation (Last Round) | When a round closes |

**Primary sources**:
- **The Information** (theinformation.com) — most reliable for OpenAI/Anthropic ARR leaks
- **Bloomberg** (bloomberg.com/technology) — funding round announcements
- **Reuters** — funding round confirmations
- **Crunchbase** (crunchbase.com) — search company name → "Funding Rounds" tab → last announced round's post-money valuation
- **PitchBook** if you have institutional access

**What to record**:
- **ARR**: latest reported run-rate at end of the quarter, in $B (e.g. `12.0` for $12B ARR). If multiple conflicting leaks, use the most recent / most-cited source.
- **Gross margin**: rarely leaked precisely. If a report says "burns $5B on $10B revenue", that's 50% gross margin. If unavailable, leave `null`.
- **Last-round valuation**: post-money in $B. Update the quarter the round CLOSED, then carry forward until a new round.

**Important caveat to acknowledge in your notes**: these are *third-party estimates* leaked to press, not audited numbers. Treat as directional, not precise. Worth noting in the workbook column A's row or in the Thesis Dashboard notes.

**JSON format**:
```json
"OpenAI ARR (est.)": {
  "Q1-25": 8.5,
  "Q2-25": 10.5,
  "Q3-25": 12.0,
  ...
}
```

---

### Lower-priority backlog (not in monthly cycle, but documented for completeness)

These metrics have entries in `manual_overrides.json` and will accept values if you ever fill them in, but the user has deprioritized them:

| Group | Rows | Source | Why deprioritized |
|---|---|---|---|
| PJM Wholesale Electricity | Monthly row 13 | dataminer2.pjm.com (registration required) | Auth flow + manual export each month |
| WARN Act filings | Monthly row 26 | State DOL websites, varies by state | Fragmented across 50 states |
| NVDA/AMD segment | Quarterly rows 26, 28 | NVDA / AMD earnings press releases | Predictable URLs each quarter — could automate later |
| TSMC advanced-nodes % | Quarterly row 29 | TSMC monthly revenue report | Press release parsing |
| S&P 500 sector margins | Quarterly rows 31-34 | factset.com/earningsinsight (free weekly PDF) | PDF parsing required |
| ChatGPT subscribers | Monthly row 33 | Press reports | Sporadic and contested numbers |

**Quick wins among these if you want to expand scope later**: NVDA segment data is the most thesis-load-bearing of the deprioritized set (drives "AI capex continues rising"). NVDA publishes 4 numbers per quarter in a predictable press release. Manually filling 10 quarters × 1 ticker × 2 metrics = ~20 cells is a one-hour task.

---

## Section 4 — Thesis Dashboard maintenance protocol

Sheet 4 (`Thesis Dashboard`). After running the monthly auto-fill + manual entries, walk through each of the 10 thesis legs and update its status. This is the part the workbook is FOR — the data sheets are inputs; this is the synthesis.

For each leg below, the format is:
- **Read**: which cells in the data sheets to look at
- **Status arrow rule**: when to mark ▲ (intact), ▬ (mixed), ▼ (weakening), or `FALSIFIED`
- **Notes column**: what to write

### Leg 1 — Oil stays elevated ($85-90)

- **Read**: Monthly Metrics row 10 (WTI Avg) and row 11 (Brent Avg) — last 3 months
- **Status arrow**:
  - ▲ if 3-month avg WTI > $85
  - ▬ if $70-85
  - ▼ if < $70
- **FALSIFIED**: WTI sustained below $70 for 3+ consecutive months
- **Notes**: write the actual 3-month avg, e.g. "WTI Mar-26 avg: $91 — ▲ intact"

### Leg 2 — Core inflation stays sticky

- **Read**: Monthly Metrics row 6 (Core CPI YoY), row 5 (Core PCE YoY), row 7 (Supercore CPI YoY) — last 3 months
- **Status arrow**:
  - ▲ if Supercore > 3.5% for 2+ recent months
  - ▬ if 3.0-3.5%
  - ▼ if < 3.0% trending down
- **FALSIFIED**: Supercore < 3.0% YoY for 2+ consecutive months
- **Notes**: record latest 3 readings of all three series so the trajectory is visible

### Leg 3 — Productivity boom NOT yet here

- **Primary signal**: Quarterly Metrics **row 7 (ULC minus Productivity YoY %)** — the precomputed disinflationary-offset spread. This single number captures the thesis:
  - **Positive (e.g. > +0.5)** → ULC growing faster than productivity → labor costs leak into prices → thesis ▲ intact
  - **Near zero (-0.5 to +0.5)** → balanced → ▬
  - **Negative (e.g. < -0.5)** → productivity absorbing wage growth → disinflationary pressure → thesis ▼ weakening
- **Supporting cells**: row 5 (Nonfarm Productivity YoY), row 6 (Unit Labor Costs YoY) — read these to understand WHY the spread moved
- **Status arrow** (this thesis is bearish-on-productivity-boom, so signals INVERT):
  - ▲ (thesis intact) if spread > +0.5 (e.g. Q1-25: +1.07 → ULC stickier than productivity gains)
  - ▬ if spread between -0.5 and +0.5
  - ▼ (thesis weakening) if spread < -0.5 sustained AND productivity rising
- **FALSIFIED**: spread < -1.0 for 2+ consecutive quarters WITH productivity > 3%. Per Q1-26 reading (spread -1.71, productivity 2.92%), the falsification trigger is one strong-productivity quarter away — watch Q2-26 closely.
- **Notes**: write the spread first ("Q1-26 spread: -1.71"), then the two components for context. The spread is the disinflationary offset that the headline inflation prints miss.

### Leg 4 — Big tech leads AI layoffs

- **Read**:
  - Monthly Metrics row 24 (Challenger Total), row 25 (Challenger AI-tagged)
  - Quarterly Metrics row 12 (Employment - Information Sector)
- **Status arrow**:
  - ▲ if AI-tagged cuts > 5,000 in any recent month AND Info Sector employment declining QoQ
  - ▬ if AI-tagged cuts present but Info Sector flat
  - ▼ if no meaningful AI-tagged announcements
- **FALSIFIED**: no AI-related layoff announcements through mid-2026
- **Notes**: track which companies announced; this is qualitative

### Leg 5 — Small/mid cos wait on AI adoption

- **Read**: Monthly Metrics row 21 (JOLTS Job Openings), row 22 (JOLTS Quits Rate) — small-biz hiring not directly tracked in this workbook
- **Status arrow**:
  - ▲ if openings still elevated (above 7M) AND quits rate stable (>2%) — implies small biz still hiring
  - ▼ if openings cratering (<6M) AND quits rate <2% — small biz tightening
- **FALSIFIED**: NFIB hiring plans + survey data show >40% small biz AI adoption with active workforce cuts (not auto-tracked — manual research needed quarterly)
- **Notes**: add a quarterly note from NFIB if checked externally

### Leg 6 — AI capex continues rising

- **Read**: Quarterly Metrics row 24 (Combined Hyperscaler Capex), rows 16-23 (individual capex + capex/revenue %)
- **Status arrow**:
  - ▲ if Combined Capex QoQ increasing for 2+ consecutive quarters
  - ▬ if flat
  - ▼ if QoQ declining 1 quarter
- **FALSIFIED**: Combined hyperscaler capex declines QoQ for 2+ consecutive quarters
- **Notes**: include the QoQ delta. As of latest data, Combined was $129.75B in Q1-26, up from $118.63B in Q4-25 → ▲

### Leg 7 — AI pricing must keep falling

- **Read**: Monthly Metrics rows 28-32 (the 5 API pricing rows)
- **Status arrow**:
  - ▲ (thesis intact) if frontier input price has declined ≥20% over the last 6 months
  - ▬ if prices flat
  - ▼ (thesis weakening) if prices rising or flat for 6+ months
- **FALSIFIED**: API prices plateau or rise for 6+ months across all three providers
- **Notes**: index the price to Jan-25 baseline so trajectory is obvious (compute `current_price / Jan-25_price`)

### Leg 8 — AI cos need public markets

- **Read**: Quarterly Metrics rows 36-40 (OpenAI/Anthropic ARR + valuations)
- **Status arrow** (largely qualitative):
  - ▲ if no AI co has filed S-1 AND last private rounds at flat/down valuations
  - ▬ if rumors of IPO but no filing
  - ▼ if AI co files S-1 or last round was at flat valuation despite ARR growth
- **FALSIFIED**: major AI co achieves operating profitability while staying private (= no need to IPO for liquidity)
- **Notes**: track which cos are in "burning" vs "self-funding" mode based on ARR/valuation/round leaks

### Leg 9 — Electricity becomes bottleneck

- **Read**: Monthly Metrics row 13 (PJM Wholesale Electricity) — currently manual/blank
- **Status arrow**:
  - ▲ if PJM prices > $50/MWh sustained
  - ▬ if $35-50
  - ▼ if < $35
- **FALSIFIED**: wholesale electricity falls below 2024 baseline levels near data center hubs
- **Notes**: cross-reference utility interconnection queue news if available

### Leg 10 — Eventual disinflation wave (2-4 yr)

- **Read**: ULC-minus-Productivity spread (row 7 quarterly — the key signal), individual Productivity (row 5) + ULC (row 6) for context, AI adoption proxies, all inflation metrics
- **Status arrow** (long-horizon, mostly stays ▬):
  - ▲ if both productivity rising AND ULC falling
  - ▬ if mixed (default state until 2027+)
  - ▼ if inflation accelerating despite all the productivity signals
- **FALSIFIED**: inflation accelerates while productivity rises and AI adoption rises — thesis-internal contradiction
- **Notes**: this is a long-dated thesis; just note quarterly directional shift in productivity vs inflation

### Key Ratios block (bottom of dashboard, rows ~17-24)

8 computed ratios. **Recommended approach**: type values manually each month rather than wire up Excel formulas across sheets — cross-sheet formulas in Excel get brittle when row positions shift after edits to the data sheets. The dashboard is small enough that manual is fine.

Each ratio's `Current Value` column should hold the *latest* reading:

| Ratio | How to compute (from data sheets) |
|---|---|
| Hyperscaler Capex / Revenue | Look at most recent quarter's Capex/Revenue % rows (17, 19, 21, 23) — average the four values |
| NVDA DC Rev Growth (QoQ) | Quarterly row 27 (already computed as QoQ %) |
| AI API Price Index (Normalized) | (Latest Anthropic input price) / (Jan-25 Anthropic input price) — both in row 28 |
| Job Openings / Unemployment | Monthly row 21 (JOLTS Openings) / Quarterly row 10 (U-3) × civilian labor force — approximation; just track openings level |
| Supercore CPI Trend (3m avg) | Mean of last 3 cells in row 7 (Monthly Metrics Supercore) |
| AI Layoff Intensity | Monthly row 25 (AI-tagged) / Monthly row 24 (Total) — latest month |
| Unit Labor Cost vs Productivity | Quarterly **row 7** (ULC minus Productivity, YoY %) — direct lookup, no math needed |
| Electricity Cost Pressure | Monthly row 13 latest / row 13 same-month-prior-year − 1, ×100 |

Then in the `Status` column, write OK/WATCH/ALERT based on the threshold column already populated in the workbook.

---

## Section 5 — Verification checklist

After each monthly run, spot-check these:

1. **Real Wage Growth identity**: pick any month in Monthly Metrics row 17 (Real AHE YoY). Value should approximately equal (Nominal AHE YoY from BLS) minus (CPI YoY from row 6 Core CPI ± a small delta because Real AHE uses headline CPI, not Core). If wildly off, the derivation logic broke.

2. **ULC-minus-Productivity identity**: Quarterly Metrics row 7 should exactly equal row 6 minus row 5 (within rounding) for every column. Spot-check Q1-26: row 6 (ULC) 1.21% − row 5 (Productivity) 2.92% = -1.71% → must match row 7's printed value. If off, the derived-spread calc broke.

3. **Combined Hyperscaler Capex sum**: row 24 (Quarterly Metrics) should approximately equal row 16 + row 18 + row 20 + row 22 for the same quarter (the four individual hyperscaler capex rows). Within a $1B rounding tolerance.

4. **No surprise gaps**: scan column D (Q1-24 / Jan-25) — if FRED-sourced cells are now blank where they were previously filled, FRED revised down available history; check stderr of last run.

5. **Thesis-leg coherence**: e.g., if oil is ▼ AND core inflation is ▼, but you've left "sticky inflation" status as ▲, that's an inconsistency — review.

6. **Recent print sanity**: WTI / Brent values for the latest month should be in a plausible range ($50-110). If you see $200 or $20, something's wrong — likely a FRED date-shift issue.

---

## Section 6 — Failure-mode reference

What can go wrong, what you'll see, what to do:

| Failure mode | Symptom | Fix |
|---|---|---|
| Workbook open in Excel | `ERROR: cannot save ... appears to be open in Excel` | Close in Excel, re-run |
| FRED revises history | Old cells change values | Expected; reflects BEA/BLS revisions ~3 months after release |
| Yahoo timeseries returns < 5 quarters | Pre-2025 hyperscaler capex stays blank | Manual override via `manual_overrides.json`; long-term fix = SEC EDGAR XBRL |
| Manual override key typo | Cell stays blank despite editing JSON | Compare key string against workbook column A label exactly (case, spaces, hyphens) |
| FRED endpoint down | `FRED fetch failed for {id}: ...` to stderr, many `data_unavailable` | Re-run in an hour; FRED is typically reliable |
| `manual_overrides.json` corrupted | JSON decode error on startup | Restore from git, or delete the file (filler will re-scaffold with all-null) |
| Workbook sheet renamed | `ERROR: expected sheets 'Monthly Metrics' and 'Quarterly Metrics'` | Restore sheet names — they're load-bearing |

---

## Section 7 — Quick reference: monthly time budget

Realistic per-month effort:

| Step | Time |
|---|---|
| Run filler 4-5 times across the month (after each major release) | ~5 min total |
| API pricing entry (after checking pricing pages) | 5-10 min |
| Challenger entry (one report) | 5 min |
| AI ARR/valuation entry (when leaked) | 5-15 min |
| Thesis Dashboard walkthrough (10 legs + 8 ratios) | 20-30 min |
| **Total** | **~45-60 min/month** |

Front-loaded the first month (backfilling 17 months of API pricing from Wayback Machine adds ~2-3 hours one-time).
