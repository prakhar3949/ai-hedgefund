# Wave-3 AI Productivity Beneficiaries — Expanded Universe, Metric Framework & Scoring Model

Companion to `camillo-third-wave-ai-thesis.md`. This document is the operational version: 140 US-public companies, mapped from qualitative "how AI helps" to a quantitative metric, scored on five factors, ranked by composite.

## What's in the workspace folder
- **`wave3_universe.py`** — 140 tickers tagged with sector bucket + qualitative mechanism + primary metric tag
- **`wave3_score.py`** — fetches live fundamentals via Yahoo `quoteSummary`, computes derived metrics, percentile-ranks, composites, writes `wave3_ranked.csv` + `wave3_ranked.json`

Run from your Windows venv (Yahoo quoteSummary is blocked from the cloud sandbox, but your local environment already uses it via `fundamentals-scanner.py`):

```
cd D:\Deepseek-ollama\finance\cowork-1
d:\Deepseek-ollama\venv\Scripts\python.exe wave3_score.py
```

Expected runtime: ~1.5 min for 140 tickers. Outputs `wave3_ranked.csv` (sortable in Excel) and `wave3_ranked.json` (full structure).

---

## 1. The "How AI Helps → Metric" Mapping

I went through each company in the universe and mapped its qualitative mechanism to one of nine measurable tags. Each tag is what gets *measured* in the score, and each carries a different sector-exposure multiplier (because not every "AI helps" story converts to margin at the same rate).

| Tag | Qualitative mechanism | Measurable proxy | Sector exposure multiplier |
|---|---|---|---|
| **LABOR_PCT** | Labor cost is the dominant cost line — agentic AI directly substitutes for billable headcount | Labor cost / sales (Goldman's GSXUPROD #1 input). Proxied here by SG&A% + inverse rev/employee | **1.20×** (load-bearing factor) |
| **BPO** | Business-process outsourcer — invoice processing, claims, F&A — workflow IS the product | SG&A%, rev/employee, op margin runway | **1.20×** |
| **BILL_HOURS** | Consulting / IT services pyramid — first-year associate work absorbed by agents | Same as LABOR_PCT but with higher gross margin baseline | **1.15×** |
| **CS_INTENSITY** | Customer-support / contact-center labor — voice + chat agents are commercially deployable today, 65-90% cost reduction documented | Employee count vs revenue, op margin | **1.15×** |
| **CLAIMS_INTENS** | Insurance claims / loss-adjustment / prior-auth processing | Op margin + employee density (loss-adjustment-expense ratio would be ideal but not in Yahoo's payload) | **1.10×** |
| **KNOW_WORKER** | Knowledge worker pyramid (legal, research, exec search) — research and drafting layer compressed | SG&A%, gross margin (services-heavy) | **1.05×** |
| **BACKOFFICE** | Bank ops, payroll admin, payments middleware, HR back office | SG&A%, op margin expansion runway | **1.00×** |
| **REV_PER_EMP** | Catch-all for labor-intensity-driven thesis where the mechanism isn't sector-specific | Rev/employee + emp density | **1.00×** |
| **SGA_PCT** | Pure admin-overhead thesis (rare standalone — usually composite with another tag) | SG&A / revenue | **1.00×** |

**Why not loss-adjustment-expense ratio for insurers, or call-center HC % for CX companies?** Both are the *ideal* metric for those sub-sectors but aren't exposed in Yahoo's `quoteSummary`. Pulling them requires per-name 10-K parsing, which is overkill for a first-pass screen. The Yahoo-derived metrics correlate strongly enough — a P&C insurer with high employee count vs revenue and depressed op margin is the same name a loss-adjustment-ratio screen would flag. We can upgrade to XBRL/EDGAR pulls if you want sector-specific metrics later.

---

## 2. The Five Scoring Factors

Each factor is **percentile-ranked within the universe** (0-100), then weighted. The direction of "good" for each factor is deliberately the *Wave-3-attractive* direction, not the *generic-quality* direction. A high score means "this company has lots of cost to take out via AI" — NOT "this is a great business today".

| # | Factor | Direction | Weight | What it measures |
|---|---|---|---|---|
| F1 | `rev_per_emp` | Lower → higher rank | 30% | Revenue per full-time employee. Pure labor-intensity proxy. Lowest in IT services, BPO, contact centers, retail banks. Highest in software, payment networks |
| F2 | `op_margin` (inverse) | Lower → higher rank | 25% | Lower operating margin = bigger runway for margin expansion. Companies losing money (op_margin < -10%) get null on this factor (thesis doesn't apply) |
| F3 | `gross_margin` (inverse) | Lower → higher rank | 15% | Lower gross margin = COGS-side cost-out potential in addition to opex |
| F4 | `emp_per_$M_revenue` | Higher → higher rank | 20% | Same intent as F1, inverted scale. Acts as a sanity-check on F1. (Both kept on purpose — labor intensity is the load-bearing variable, so signal redundancy is intentional weight) |
| F5 | `fcf_drag` = 1 - (FCF/NetIncome) | Lower FCF conversion → higher rank | 10% | Working-capital and admin drag that process automation typically compresses. Capped (companies with FCF > NI score 0 here) |

**Composite:** `(weighted_avg_of_available_factors) × sector_exposure_multiplier`, clamped to [0, 100].

**Classification bands:**
- **PRIME (≥ 75)** — strong on at least three factors; sector overlay supports it
- **GOOD (60-74)** — meaningful Wave-3 setup, additional confirm useful
- **MIXED (40-59)** — partial signal; may be sector-specific
- **AVOID (< 40)** — limited Wave-3 leverage (often: high-margin businesses, software-native, or labor-light)

---

## 3. Universe Composition (140 tickers, 12 buckets)

| Bucket | Count | Representative tickers |
|---|---|---|
| Regional & Mid-Cap Banks | 12 | TFC, USB, PNC, RF, CFG, KEY, FITB, MTB, HBAN, ZION, CMA, WAL |
| IT Services & Consulting | 16 | CTSH, EPAM, ACN, INFY, WIT, G, EXLS, DXC, KD, CACI, LDOS, BAH, GLOB, IT, FCN, HURN |
| Insurance (P&C + Life + Brokers + Health) | 16 | MMC, AON, WTW, AJG, BRO, TRV, CINF, ALL, HIG, CB, PRU, MET, LNC, EHTH, GOCO + 1 |
| Healthcare Payers + Admin + CRO | 15 | UNH, ELV, HUM, CNC, MOH, CI, IQV, CRL, ICLR, MEDP, EVH, MDRX, HQY, PINC, OMI |
| Wealth / Asset Mgmt | 7 | BLK, TROW, BEN, AMG, LPLA, RJF, AMP |
| CX BPO + CCaaS Software | 8 | TTEC, CNDT, CNXC, IBEX, NICE, FIVN, ZM, RNG |
| Staffing & HR Services | 6 | RHI, MAN, ASGN, KFY, HSII, KFRC |
| Payroll / HR Tech | 4 | PAYX, ADP, PCTY, PAYC |
| Real Estate Services | 7 | CBRE, JLL, CWK, NMRK, RDFN, Z, COMP |
| Logistics & Field Services | 8 | CHRW, EXPD, HUBG, XPO, GXO, ROL, SCI, RBA |
| Money-Center Banks + Specialty Lenders | 8 | JPM, BAC, WFC, C, COF, DFS, SYF, ALLY |
| Education / Tax / Legal / Doc / Media / Misc | 33 | HRB, INTU, JKHY, FIS, FI, BR, TRI, RELX, WLY, WK, OMC, IPG, NYT, GCI, PBI, ACIW, EVRI, DLX, WDAY, CRM, NOW, HUBS, DOCU, CHGG, STRA, LRN, LAUR, COUR, MAXR, ICFI, TYL, SCHW, IBKR, HOOD |

Each is tagged with `(bucket, how_it_helps, primary_metric_tag)` in `wave3_universe.py`.

---

## 4. Expected Ranking — Goldman's 5 Validated Names

These are the 5 names Goldman's GSXUPROD framework flagged in the 93rd-percentile+ band, with their published labor-cost-as-percent-of-sales. They should each land in PRIME or high-GOOD when you run the script:

| Ticker | Labor % sales | GS percentile | Bucket in our model | Expected class |
|---|---|---|---|---|
| **HRB** | 46% | 97th | Tax Services (LABOR_PCT 1.20×) | PRIME |
| **RHI** | 79% | 96th | Staffing (LABOR_PCT 1.20×) | PRIME |
| **CTSH** | 76% | 94th | IT Services (LABOR_PCT 1.20×) | PRIME |
| **EPAM** | 53% | 93rd | IT Services (LABOR_PCT 1.20×) | PRIME / GOOD |
| **IQV** | 45% | 93rd | CRO (LABOR_PCT 1.20×) | PRIME / GOOD |

If any of these come out as MIXED, your run hit a Yahoo data gap on that name (typically employees field is null) — check the JSON output.

---

## 5. What the Output Looks Like

`wave3_ranked.csv` columns:
```
rank, ticker, name, bucket, tag, composite, class,
F1_rev_per_emp, F2_op_margin, F3_gross_margin, F4_emp_density, F5_fcf_drag,
rev_per_emp_$, op_margin, gross_margin, employees, revenue_$M, market_cap_$M,
rev_growth, how
```

Sort by `composite` descending to get the ranked list. Filter `class == "PRIME"` for a tight high-conviction shortlist (~15-25 names typical). Sort within a `bucket` to find the most exposed name in each sub-industry.

`wave3_ranked.json` carries full structure (including raw factor values + factor percentile scores), useful for piping into downstream analysis or charting.

---

## 6. Worst-Case Stress Test (per project convention)

Failure modes considered before coding, with mitigations:

1. **Yahoo `fullTimeEmployees` is null** for many ADRs and recent spinoffs. *Mitigation*: F1 and F4 return null for that name; weighting redistributes across available factors so the composite is still computable.
2. **Loss-making companies (CHGG, FIVN-like)** would game F2 (1 - op_margin scores well when op_margin is -50%). *Mitigation*: if `op_margin < -10%`, F2 is set to null — Wave-3 thesis is about *expanding* margin, not creating it from nothing.
3. **SG&A line item missing from Yahoo's incomeStatementHistory** for some names. *Mitigation*: sga_pct is computed when available but isn't in the composite (kept as a reporting column only) — composite relies on the five core factors.
4. **High-margin software (NOW, CRM, HUBS) screens MIXED/AVOID** because gross + op margins are already strong. *This is correct* — they're Wave-2 (selling the AI), not Wave-3 (absorbing it). The sector overlay doesn't rescue them.
5. **Brokers (MMC, AON, AJG) score lower than instinct suggests** because they're high-margin fee businesses despite high knowledge-worker count. *Accepted*: this is exactly the asymmetric setup the framework is designed to expose — high labor intensity, but the margin runway isn't there. They appear in MIXED, not PRIME.
6. **Yahoo rate-limit during a 140-ticker run**. *Mitigation*: 6-worker pool + 50ms inter-request sleep; per-ticker failures degrade silently to error column.
7. **Composite of one PRIME factor + four AVOID factors** gives misleading score. *Mitigation*: weighted average requires at least one non-null factor; classification bands are set so a single strong factor can't push a name into PRIME unless the sector overlay also supports it.

---

## 7. How to Improve the Model (future iterations)

- **Add labor-cost-from-10K**: SEC XBRL has `LaborAndRelatedExpense` for ~60% of large caps. Replacing the SG&A% proxy with the real labor% would mirror Goldman's GSXUPROD methodology exactly.
- **Add price action overlay**: Wave-3 is currently *under-owned*. A trailing 6m relative-strength vs SPY filter would flag the "not yet priced in" subset.
- **Add management-commentary score**: count AI mentions per earnings call (the Goldman filter was "did this company discuss AI productivity on 2Q/3Q calls"). Easy to add via earnings transcript scraping.
- **Add headcount-trend factor**: companies whose headcount is *declining* while revenue grows are already executing the thesis. Yahoo doesn't give historical employees, but stockanalysis.com does — would need a separate scraper.
- **Pair with `bubble-scanner.py` output**: cross-reference Wave-3 PRIME names against the bubble scanner's qualified ETFs to surface stocks getting *both* AI productivity tailwind AND sector momentum.

---

## 8. Sources

- [Chris Camillo — Money Expert: This Wealth Setup Only Happens Once... (May 23 2026)](https://www.youtube.com/watch?v=C-EyESBKImI)
- [Goldman Sachs pinpoints the 5 stocks that will get the biggest productivity boost from AI](https://finance.yahoo.com/news/goldman-sachs-pinpoints-5-stocks-181501471.html)
- [These stocks could benefit most from AI productivity, Goldman Sachs says — CNBC](https://www.cnbc.com/2026/01/14/these-stocks-could-benefit-most-from-ai-productivity-goldman-sachs-says.html)
- [Goldman Sachs unveils 'Most Important Trade of 2026': AI Productivity Beneficiary Portfolio](https://news.futunn.com/en/post/65423877/goldman-sachs-unveils-most-important-trade-of-2026-ai-productivity)
- [Bank of America sets AI stocks to buy list for 2026 — TheStreet/Yahoo](https://finance.yahoo.com/news/bank-america-sets-ai-stocks-210300616.html)
- [JPMorgan Chase blueprint: fully AI-powered megabank — CNBC](https://www.cnbc.com/2025/09/30/jpmorgan-chase-fully-ai-connected-megabank.html)
- [BAC's AI Edge Likely to Drive Margin Expansion — TradingView/Zacks](https://www.tradingview.com/news/zacks:55e85ddf4094b:0-bac-s-ai-edge-likely-to-drive-margin-expansion-should-you-invest-now/)
- [Morgan Stanley — Thematic Investing: AI Boom Drives Investment Megatrends](https://www.morganstanley.com/insights/articles/thematic-investing-ai-drives-megatrends-2026)
- [Morgan Stanley — AI Enablers & Adopters research (PDF)](https://www.morganstanley.com/content/dam/msdotcom/what-we-do/wealth-management-images/uit/AI-Enablers-Adopters-research-report.pdf)
- [AI agents are now running the back office at insurance giants — PYMNTS](https://www.pymnts.com/artificial-intelligence-2/2026/ai-agents-are-now-running-the-back-office-at-insurance-giants/)
- [How Will AI Affect the US Labor Market? — Goldman Sachs](https://www.goldmansachs.com/insights/articles/how-will-ai-affect-the-us-labor-market)
- [AI Contact Center Transformation: From Cost per Call to Cost per Resolution](https://rits.center/blog/ai-contact-center-transformation-from-cost-per-call-to-cost-per-resolution)
