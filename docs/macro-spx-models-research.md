# Macro SPX Fair-Value Models — Research Dossier (v2)

**Session 1 deliverable.** Multi-session project. Banks deliberately excluded — they don't publish reproducible models. Sources are NBER, FRBNY, Federal Reserve Board, BIS, IMF, ECB, OECD, academic journals (JoF, RFS, JFE, JFQA, Management Science), Duke/Yale/Chicago/MIT working papers, and SSRN/arXiv.

The plan: catalogue every academic-quality SPX-fair-value framework, pick a shortlist to implement (Session 2), backtest them on a level playing field (Session 3), then train a deep-RL ensemble that learns regime-conditional weights (Session 4).

---

## 0. Why v1 was wrong

1. **Stale data**: v1 hit the datahub Shiller mirror which stops updating in 2023. Use Shiller's `ie_data.xls` (he updates it quarterly), McCracken's FRED-MD (monthly auto-update), and FRED for live macro.
2. **Too narrow methodology**: v1 used a single OLS on three regressors. The literature has ~6 distinct families of equity-fair-value models — we need representatives from each before declaring a winner.
3. **No OOS discipline**: v1 reported in-sample R² as if it were forecast accuracy. The whole academic question (Welch-Goyal 2008) is: *does anything beat the historical mean OOS?* That has to be the benchmark.

---

## 1. The six families of macro equity-valuation models

### Family A — Single-ratio comparison (the "Calvasina family")

The simplest. Compute one yield-like ratio for stocks, compare to one yield-like ratio for bonds. Anchor SPX to whatever multiple that comparison says is "fair."

| Model | Formula | Key reference |
|---|---|---|
| **Fed Model** (Yardeni 1998 / Asness 2003 critique) | `Fair E/P = 10Y_yield` → `Fair_P/E = 1/10Y` | [Asness 2003 "Fight the Fed Model"](https://business.columbia.edu/sites/default/files-efs/pubfiles/3038/inflation_stock_market.pdf) |
| **Yardeni Model** | `Fair E/P = Baa_yield × adj_factor` (uses corporate yield, not Treasury) | [Wikipedia Fed Model](https://en.wikipedia.org/wiki/Fed_model) |
| **Shiller CAPE** | `CAPE = P / 10yr_real_EPS_avg`; compare to historical mean | [Jivraj & Shiller, NBER w20651](https://www.nber.org/system/files/working_papers/w20651/w20651.pdf) |
| **Excess CAPE Yield (ECY)** — Shiller Dec 2020 | `ECY = 1/CAPE − real_10Y_yield`. Real 10Y from 10Y nominal − 10Y inflation expectation (TIPS or survey) | [Fortune 2021 explainer](https://fortune.com/2021/01/25/stock-market-value-metric-robert-shiller/) |
| **IJTSRD linear** (baseline) | `SPX = a + b1·rate + b2·unemployment` | [IJTSRD 27819](https://www.ijtsrd.com/papers/ijtsrd27819.pdf) |
| **Federal Reserve FSR equity-premium metric** | `Equity_premium = forward_E/P − real_10Y_yield`; compare to historical percentile | [Fed FSR Apr 2025 §1](https://www.federalreserve.gov/publications/April-2025-financial-stability-report-Asset-Valuations.htm) |

**What they share**: P/E (or E/P) is the dependent. The only macro variable is one yield (nominal 10Y, real 10Y, or Baa). Bond yields enter linearly, no decomposition.

**Asness critique**: The Fed Model is mostly a *nominal* artifact — when inflation falls, both 10Y nominal yields and required real equity returns fall together, so they co-move. Use the CAPE-adjusted version (ECY) or compare to real yields, not nominal. This is why we keep Excess CAPE Yield and discard naive Fed Model except as a straw man.

---

### Family B — Predictor zoo (Welch-Goyal era)

Take a long list of empirical predictors, run univariate OLS on each, then either (a) report individually, (b) combine forecasts. The academic benchmark for "does anything predict equity returns?"

**Welch & Goyal (2008)** — core paper, JF / NBER 11468.

Canonical 14–15 predictors, monthly. We'll implement the maintained database that Welch hosts at UCLA (he updates it; latest vintage 2023+):

| # | Variable | Description |
|---|---|---|
| 1 | DP | log(D/P), trailing dividend-price ratio |
| 2 | DY | log(D/Y), dividend yield (D at t / P at t−1) |
| 3 | EP | log(E/P), trailing earnings-price |
| 4 | DE | log(D/E), payout ratio |
| 5 | BM | book-to-market ratio (Dow Jones for early, SPX later) |
| 6 | NTIS | net equity issuance as fraction of market cap |
| 7 | TBL | Treasury bill (3-month) |
| 8 | LTY | long-term Treasury yield |
| 9 | LTR | long-term bond return |
| 10 | TMS | term spread (LTY − TBL) |
| 11 | DFY | default-yield spread (Baa − Aaa) |
| 12 | DFR | default-return spread (LT corp − LT govt return) |
| 13 | INFL | CPI inflation |
| 14 | SVAR | stock variance (sum of sq. daily returns in month) |
| 15 | IK | Cochrane investment-capital ratio (quarterly, interpolated) |

**Headline result**: *Individually*, almost none beat historical mean OOS post-1965. In-sample looks great; OOS looks terrible. This is the academic null hypothesis — your fancy model has to clear this bar.

**Rapach, Strauss, Zhou (2010, RFS)** — important sequel.
- Take same Welch-Goyal predictors.
- *Combine* the 15 individual forecasts (simple average, or weighted by past performance).
- The combination **does** beat historical mean OOS. Forecast-combination is the cheapest win in equity-premium prediction.

This is the Session 4 RL ensemble's parent idea — but instead of equal-weight averaging, learn weights conditionally.

---

### Family C — Intrinsic / Discounted-cash-flow

`Price = Σ CF_t / (1+r)^t`. Solve for the discount rate (implied ERP) given today's price + analyst forecasts, or solve for price given assumed inputs.

| Model | Distinctive feature |
|---|---|
| **IMF GFSR model-implied fair value** | Three-stage Gordon DDM. Inputs: 12m fwd EPS (IBES), LR earnings growth `g`, 10Y nominal, implied ERP, ACM term premium. Output: model-implied fair P/E. Compare to actual. [IMF GFSR Apr 2026 Ch 1](https://www.imf.org/-/media/files/publications/gfsr/2026/april/english/ch1.pdf), [IMF GFSR Oct 2025](https://www.imf.org/-/media/files/publications/gfsr/2025/october/english/ch1.pdf) |
| **ECB three-stage DDM** | Inputs: bottom-up analyst dividend forecasts (next 5y), medium-term growth (5-10y), long-term GDP growth from SPF survey. Decomposes price into div-growth + risk-free + ERP. [ECB EB 5/2017](https://www.ecb.europa.eu/pub/pdf/other/ebbox201705_02.en.pdf), [ECB WP 2787](https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp2787~04133e65f9.en.pdf) |
| **Damodaran implied ERP** | Includes **buybacks + dividends** in cash flow (more accurate post-2000). Solves: `Price = Σ (E×payout)/(1+rf+ERP)^t` for ERP. Updates monthly + start-of-year, methodology unchanged since 1990s. Post-May-2025 nets out Aa1 default spread from rf. Implied ERP at May 2025 = 4.33%. [Damodaran arXiv 1903.07737](https://arxiv.org/pdf/1903.07737), [Data Update 2 for 2025](https://aswathdamodaran.substack.com/p/data-update-2-for-2025-the-party) |
| **ACM term-premium decomposition** | Splits 10Y nominal into expected rate + term premium. Useful when you want to put `r_expected_short` and `term_premium` as separate model inputs. [Adrian-Crump-Moench 2013 JFE](https://github.com/arnab13061989/Term-Premium), [NY Fed data](https://www.newyorkfed.org/research/data_indicators/term-premia-tabs) |

**Common**: Forward-EPS-driven. Need analyst-consensus forecasts (we can use S&P's published forward EPS or IBES via WRDS — for our purposes, S&P + a manual override is fine).

**Common trap**: Analyst 12m fwd EPS bias is **+10% optimism** on average (decays over the forecast horizon). Backtests must apply a haircut or use realized — not consensus — for fairness.

---

### Family D — Structural / consumption-based (asset-pricing theory)

Derived from first principles: representative agent with preferences, consumption process, equilibrium pricing.

| Model | Mechanism |
|---|---|
| **Campbell-Cochrane habit** (JPE 1999) | Time-varying risk aversion via habit `H_t`. Surplus consumption ratio `S_t = (C_t − H_t)/C_t` is the state variable. When `S_t` is low (recession), risk aversion spikes → equity premium spikes → price/dividend falls. Explains procyclical P/D, countercyclical vol, long-horizon predictability. [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=151749) |
| **Bansal-Yaron long-run risks** (JF 2004) | Small predictable component in consumption growth `x_t` + time-varying consumption volatility `σ²_t` + Epstein-Zin preferences (separates risk aversion from EIS). News about LR growth = big revisions to P/D. [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4992679), [NBER w8059](https://www.nber.org/papers/w8059) |
| **Lettau-Ludvigson CAY** (JoF 2001) | Cointegration residual of `log C − log A − log Y` (consumption, asset wealth, labor income). When CAY is high, expected returns are high. Better OOS predictor than D/P at quarterly horizon. [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=169791) |
| **Pastor-Veronesi uncertainty model** | Stock value increases in uncertainty about long-run growth. Explained NASDAQ peak ('99-'00) without invoking bubble. State variable: posterior variance over `g`. [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=559231) |

**Common**: Get to a closed-form (or simulation-based) `P/D = f(state)` map. Not naturally OOS-tested at monthly frequency — these are evaluated by moment-matching (P/D mean, P/D vol, equity premium, risk-free rate vol).

**For our project**: Structural models are heavy lifts to estimate but produce *steady-state* fair-value benchmarks. Best used as **regime anchors** (long-run P/E this model says is fair given current macro state) rather than month-ahead forecasts.

---

### Family E — Macro-factor / large dimensional

Reduce a wide macro panel to a small number of factors, regress equity returns on factors.

| Model | Setup |
|---|---|
| **Chen-Roll-Ross** (J. Business 1986) | 5 macro innovations: industrial production (MP), unexpected inflation (UI), change in expected inflation (DEI), default spread innovation (UPR), term spread innovation (UTS). Tests whether these are *priced risk factors*. [SSRN/SciRP ref](https://www.scirp.org/reference/referencespapers?referenceid=2945461) |
| **FRED-MD factors** (McCracken & Ng 2016, JBES) | 134-series monthly panel, organized in 8 groups: output/income, labor, housing, consumption-orders-inventories, money-credit, interest-FX, prices, stock-market. Each series tagged with transform code (1–7) for stationarity. Standard PCA → 4-8 factors explain ~50% variance. [FRED-MD paper](https://files.stlouisfed.org/files/htdocs/fred-databases/fredmd.pdf), [FRED-MD updates](https://research.stlouisfed.org/econ/mccracken/fred-databases/) |
| **NY Fed adaptive macro indices** (Çakmaklı & van Dijk, FRBNY SR475) | 100-var subset of FRED-MD. PCA factors with **time-varying loadings**: each variable's contribution to a factor is reweighted by its rolling forecasting performance. Beats Welch-Goyal OOS. [FRBNY SR475](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr475.pdf) |
| **BIS financial-conditions augmented** (WP 1272, WP 606) | Adds NFCI (Chicago Fed national financial conditions), credit spreads, term premium, market vol as separate channels to a baseline rate-CPI model. [BIS WP 1272](https://www.bis.org/publ/work1272.pdf), [BIS WP 606](https://www.bis.org/publ/work606.pdf) |

**Common**: Many macro inputs → small factor set → return forecast. The "kitchen sink with discipline" approach. Stock & Watson 2002 (JBES) is the methodological parent.

---

### Family F — Modern ML / deep learning

Same problem (predict return / explain price), modern flexible function approximators.

| Model | Method |
|---|---|
| **Gu, Kelly, Xiu** (RFS 2020 / Management Science) | "Empirical Asset Pricing via Machine Learning." Compares OLS, PLS, ridge, lasso, elastic net, GLM, random forest, gradient boosting, neural nets (1-5 layers). 94 firm-level chars + 8 macro vars. Best: neural nets and trees. Doubles Sharpe of OLS-based strategies. [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3159577), [Replication](https://www.tidy-finance.org/blog/gu-kelly-xiu-replication/) |
| **Chen, Pelger, Zhu** (Management Science 2024) | "Deep Learning in Asset Pricing." Three networks: feedforward (nonlinearity) + LSTM (state) + GAN (find missing factors). Imposes no-arbitrage constraint inside the loss function — model has to fit SDF, not just predict returns. [arXiv 1904.00745](https://arxiv.org/pdf/1904.00745), [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3350138) |
| **MDPI two-state regime model** (Mathematics 2025) | Welch-Goyal predictors but with NBER recession dummy gating the coefficients. Tech indicators dominate in recessions; macro dominates in expansions. [MDPI](https://www.mdpi.com/2227-7390/13/2/257) |
| **arXiv 2509.10483 — Equity Premium Prediction** (2025) | Bayesian model averaging across W-G + technical indicators, regime-conditional. [arXiv](https://arxiv.org/pdf/2509.10483) |

**Common**: All accept that the function from macro state → return is nonlinear and regime-dependent. All sacrifice interpretability for OOS Sharpe. Replication-friendly: Gu-Kelly-Xiu is the gold standard for "is ML actually better here?" — and the answer is *yes, but not enormously*.

---

### Family G — Behavioral / monetary-feedback

Closely related to (D), but with explicit market-Fed two-way feedback.

| Model | Mechanism |
|---|---|
| **Cieslak & Vissing-Jorgensen "Fed Put"** (RFS 2021, NBER w26894) | Low SPX returns predict accommodative Fed policy. Fed Funds target change is forecasted by *stock returns*, not just macro releases. Implies a feedback channel where equity prices anticipate their own put. Important for sizing the "cuts" coefficient in our model. [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3563962), [NBER PDF](https://www.nber.org/system/files/working_papers/w26894/w26894.pdf) |
| **Cochrane "Discount Rates"** (AFA 2011 presidential, JoF) | All variation in P/D historically is *discount-rate* variation, not cash-flow expectations variation. Implies any fair-value model that holds the discount rate static is wrong. The discount rate IS the state variable. [SSRN/NBER w16972](https://www.nber.org/papers/w16972) |

**Implication**: Our backtesting must explicitly test whether changes in fair-value forecasts come from EPS news or discount-rate news. Cochrane says it'll all be discount-rate. If our models attribute the wrong share, we're miscalibrated.

---

## 2. Reinforcement learning for the ensemble (Family H — Session 4)

We won't use RL to predict returns directly — RL on equity-premium prediction overfits trivially with only ~420 monthly obs. Instead RL **selects weights** over the 10-12 models from Families A-G that we'll implement in Session 2.

Papers we'll borrow from:

| Paper | Relevance |
|---|---|
| [arXiv 2010.04404 — Deep RL for Asset Allocation in US Equities](https://arxiv.org/pdf/2010.04404) (Imperial College, 2020) | Baseline PPO portfolio agent on SPX sector ETFs. Useful as scaffold. |
| [arXiv 2511.11481 — Risk-Aware DRL Dynamic Portfolio Opt](https://arxiv.org/pdf/2511.11481) (Nov 2025) | Sharpe-ratio reward + explicit drawdown penalty in PPO. We adopt the reward shape. |
| [arXiv 2511.17963 — Hybrid LSTM + PPO Portfolio Optimization](https://arxiv.org/pdf/2511.17963) (Nov 2025) | LSTM encodes macro state before PPO actor — good fit for our regime-dependent ensemble. |
| [arXiv 2502.02619 — Regret-Optimized DRL with Future-Looking Rewards](https://arxiv.org/pdf/2502.02619) (Feb 2025) | Replaces standard reward with "regret vs. best possible action" — reduces overfit. Worth A/B-testing against vanilla PPO. |
| [PLOS One — Explainable DRL Portfolio Policy](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0315528) | Post-hoc SHAP-on-PPO to show which state features drive weight changes. Critical for trust. |

**Our RL agent design (working spec for Session 4):**

```
State (∈ R^15):
  - VIX percentile (60m rolling)
  - 10Y level
  - 10Y − 3M slope
  - CPI YoY
  - PCE YoY
  - NFCI level
  - NBER recession probability (Chauvet-Piger real-time)
  - Realized 12m SPX vol
  - 12m SPX return
  - CAPE percentile vs 30y rolling
  - Excess CAPE Yield level
  - Dispersion across model forecasts (sd of the 10 fair-value estimates)
  - Per-model 12m rolling MAE (3 features for top-3 by recent fit)

Action (∈ Δ^10, sums to 1):
  - Softmax weight over the 10 fair-value models implemented in Session 2

Reward (R_t):
  - −0.5 × (ensemble_fair_value_t  −  SPX_t+12m)^2  (squared error vs realized SPX 12m forward)
  - −0.1 × ‖action‖²_2  (weight concentration penalty — keeps the agent from collapsing to a single model)
  - +0.05 × Sharpe(long_short_overlay_t)  (Sharpe of a Calvasina-style overlay: long when ensemble_fair < SPX × 0.9, short when > × 1.1)

Algorithm: PPO (stable-baselines3), Dirichlet output policy
Walk-forward training: refit every 24 months, 1990-01 → 2015-12 training, 2016-01 → live OOS
Seeds: 10 independent runs; report mean ± sd of OOS metrics

Sanity benchmarks (must beat all 3 OOS to ship):
  1. Equal-weight average of the 10 models
  2. Single best-OOS model (the leader from Session 3)
  3. Welch-Goyal historical-mean null

Overfit guards:
  - Replay buffer capped at 60 months (no full history)
  - L2 on policy net weights
  - Early stop on validation regret
  - Train on 10 random NBER-balanced subsamples; ensemble the 10 policies
```

**Why PPO specifically:** continuous action (weight vector), on-policy (handles non-stationary reward), well-tuned for small datasets compared to off-policy alternatives like SAC/DDPG that need replay buffers we can't realistically populate from 35 years of monthly obs.

---

## 3. What's universal across models

Every academic SPX fair-value framework has these five things. Our shared data layer (Session 2) must provide them:

| Universal input | Source we'll use |
|---|---|
| Some form of earnings (TTM, fwd 12m, CAPE 10y) | Shiller `ie_data.xls` (TTM, CAPE), S&P Indices forward EPS |
| Risk-free rate | FRED `DGS3MO`, `DGS10` |
| Inflation | FRED `CPIAUCSL`, `PCEPI`, `T10YIE` (10y breakeven) |
| Some discount-rate proxy (term premium, credit spread, vol) | NY Fed ACM term premium, FRED `BAA10Y`, FRED `VIXCLS` |
| Sample length ≥ 30y | All sources go back to at least 1962 (1990 if you need NFCI/TIPS) |

---

## 4. What's unique per model (matters for the shared data layer)

| Model | Unique input | Cost to obtain |
|---|---|---|
| CAPE / ECY | 10y trailing real earnings average | Free — Shiller |
| Welch-Goyal | NTIS (net equity issuance) | Free — Welch's UCLA site |
| Lettau-Ludvigson CAY | consumption, labor income (cointegration) | Free — FRED `PCE`, `W875RX1` |
| IMF/ECB DDM | analyst forward EPS, LR growth `g`, SPF survey | S&P forward EPS free; SPF free via Philly Fed |
| Damodaran ERP | dividends + buybacks aggregate | Damodaran's monthly CSV (free) |
| FRBNY adaptive | 100-variable FRED-MD subset | Free — McCracken's monthly update |
| Chen-Roll-Ross | industrial production, unexpected inflation | Free — FRED `INDPRO`, `T10YIE` |
| BIS | NFCI, ACM term premium | Free — Chicago Fed, NY Fed |
| Pastor-Veronesi | uncertainty proxy (cross-sectional EPS dispersion) | I/B/E/S behind paywall; proxy with realized EPS forecast revision std-dev |
| Gu-Kelly-Xiu | 94 firm chars + 8 macro vars | Firm chars via CRSP/Compustat (we use Yahoo/quoteSummary as approximation) |
| Habit (Campbell-Cochrane) / LRR (Bansal-Yaron) | real consumption growth | Free — FRED `PCEC96` |
| Cieslak-VJ Fed put | FOMC meeting calendar + Fed funds futures | Free — Fed website + CME pricing |

Everything we need is free. WRDS / CRSP / I/B/E/S are out of scope.

---

## 5. The implementation shortlist (Session 2 — 10 models)

Selected to span all 6 families, prioritising those with public replication code and free data.

| # | Model | Family | Why it's in |
|---|---|---|---|
| 1 | **Welch-Goyal 8 univariate** | B | Academic OOS null — gate every other model passes |
| 2 | **Rapach-Strauss-Zhou combination** | B | Equal-weight combination of W-G 8 — first thing to beat the null |
| 3 | **Shiller CAPE** | A | Long-horizon valuation anchor |
| 4 | **Shiller Excess CAPE Yield** | A | Real-yield-adjusted equity premium proxy — what Damodaran/Fed use |
| 5 | **IMF/ECB three-stage DDM** | C | Forward-EPS intrinsic value (institutional standard) |
| 6 | **Damodaran implied ERP** | C | Solves for ERP backwards from current price; mean-reversion target |
| 7 | **Chen-Roll-Ross 5-factor** | E | Classic macro-factor model; reproducible since 1986 |
| 8 | **FRBNY adaptive macro factors** | E | Modern factor-model winner OOS |
| 9 | **Lettau-Ludvigson CAY** | D | Best non-valuation predictor at quarterly horizon |
| 10 | **Gu-Kelly-Xiu neural net (lite)** | F | Modern ML benchmark; we'll do a small 2-layer NN on W-G + FRED-MD subset, not the full firm-char version |

**Excluded from implementation (still referenced for theory):**
- Campbell-Cochrane habit, Bansal-Yaron LRR: structural models, no monthly forecast output without simulation. Use to *interpret* CAPE swings (regime anchors).
- Pastor-Veronesi: needs cross-sectional EPS dispersion at firm level (we'd need I/B/E/S).
- Cieslak-VJ Fed put: behavioral channel, not a fair-value model per se. We'll use the *Fed-put indicator* as a state feature for the RL ensemble.
- Cochrane "Discount Rates": philosophy, not an implementable model — but informs how we *decompose* the residual when our forecasts miss.
- Chen-Pelger-Zhu deep SDF: massive replication; out of scope for v1 ensemble.

---

## 6. Shared data layer (Session 2 — design)

```
tools/spx_models/
├── data/
│   ├── fetch_shiller.py         # ie_data.xls → SPX, EPS_TTM, CAPE, CPI
│   ├── fetch_fred.py            # FRED CSV: DGS3MO, DGS10, FEDFUNDS, CPIAUCSL, PCEPI,
│   │                            #   BAA10Y, T10YIE, VIXCLS, USREC, NFCI, INDPRO,
│   │                            #   PCEC96, W875RX1, PAYEMS, ...
│   ├── fetch_fred_md.py         # McCracken's monthly CSV + transform per tcode
│   ├── fetch_acm.py             # NY Fed term-premium series
│   ├── fetch_welch_goyal.py     # Welch UCLA xlsx (updated annually)
│   ├── fetch_damodaran.py       # Damodaran monthly ERP CSV
│   ├── fetch_sp_fwd_eps.py      # S&P Indices forward EPS or yfinance proxy
│   └── panel.py                 # build_panel() → monthly multi-index DataFrame
├── models/
│   ├── cape.py
│   ├── excess_cape_yield.py
│   ├── welch_goyal_univariate.py
│   ├── rapach_combination.py
│   ├── chen_roll_ross.py
│   ├── frbny_adaptive.py
│   ├── ddm_three_stage.py
│   ├── damodaran_implied_erp.py
│   ├── cay.py
│   └── gkx_nn.py
├── backtest.py                  # walk-forward harness (Session 3)
├── leaderboard.py               # produce comparison table (Session 3)
└── rl_ensemble.py               # PPO agent (Session 4)
```

Every model exposes the same interface:

```python
def predict(state: pd.Series, horizon: int = 12) -> ModelOutput:
    return ModelOutput(
        spx_fair=float,           # SPX fair value at horizon
        components={...},         # dict of contributing factors for attribution
        confidence_band=(lo, hi), # 5/95 pct (or NaN if model doesn't produce one)
    )
```

This is what makes the ensemble possible.

---

## 7. Backtest plan (Session 3)

For each of the 10 models:

1. **In-sample fit (1962-01 / 1990-01 → present)**:
   - R², coefficient signs, Hodrick-corrected t-stats (NOT plain OLS t-stats; predictors are AR(1) ρ > 0.95)
   - Residual diagnostics: ADF for stationarity, LB for autocorrelation

2. **Walk-forward OOS (1990-01 → present)**:
   - Expanding window training, refit monthly
   - Predict SPX 1m, 12m, 60m ahead
   - Log: prediction, realized, error, error/SPX

3. **Metrics (all OOS)**:
   - MAE / RMSE (absolute and % of SPX)
   - Directional hit rate: did SPX mean-revert to fair value within horizon
   - Diebold-Mariano vs historical-mean benchmark
   - **Information ratio of an overlay**: long SPX-fair-value × 1.0 when SPX < fair × 0.9, short when > × 1.1 (Calvasina-style "is the market on or off fair value")
   - **Regime split**: expansion vs recession (NBER), low vs high vol (VIX > 25)

4. **Output**:
   - `data/spx-model-leaderboard.parquet` — one row per model × horizon × regime
   - Discord post: leaderboard table + best-3 models + decision on which 5-7 enter the RL ensemble

---

## 8. Risk register / known traps

Worst-case stress test for the project, per CLAUDE.md convention.

| # | Trap | Sample / when | Mitigation |
|---|---|---|---|
| 1 | **EPS reporting lag** — Shiller's TTM EPS reported with quarter lag; using same-month value = look-ahead | All TTM-based models (CAPE, Fed Model) | Lag EPS by 4 months in backtest |
| 2 | **SPX survivor bias in back-extended series** — modern SPX = current constituents only | Pre-1957 in particular | Use Cowles/Shiller original series; don't synthesize SPX before 1957 |
| 3 | **CAPE accounting regime break** (Siegel) — mark-to-market, stock-option expensing changed post-2001 | CAPE comparisons across 2001 boundary | Report results with and without GAAP/IFRS adjustment |
| 4 | **Forward-EPS optimism bias** — analyst 12m fwd EPS biased +10% on average, decays | DDM, Fed model, IMF | Apply −10% haircut OR use realized EPS (more honest in backtest) |
| 5 | **Persistence-induced t-stat bias** — most predictors AR(1) ρ > 0.95 | Welch-Goyal univariate, especially DP/DY/EP | Hodrick (1992) or Newey-West with lag = T^{1/4} |
| 6 | **NBER recession date revisions** — dates revised retrospectively, real-time recession probability is harder | Regime-switching and RL state | Use ALFRED vintage data OR Chauvet-Piger real-time recession probability |
| 7 | **RL overfit on 420 monthly obs** | Session 4 | Replay buffer cap, walk-forward refit, ensemble seeds, L2 reg, NBER-balanced subsamples |
| 8 | **Data-mining bias** — implementing 10 models, selecting best on backtest = guaranteed overfit | Session 3 → 4 transition | Reserve 2020-01 → present as locked OOS; never train on it |
| 9 | **Calvasina-style P/E-anchored models can't catch regime breaks** — "fair P/E" mean-reverts to historical only if the discount rate process is stationary | Post-2008 has rejected stationarity multiple times | Report fair-value relative to *rolling* historical, not full-sample |
| 10 | **Discount-rate vs cash-flow decomposition** (Cochrane) — your model attributes price changes wrong | All Family A & C models | Decompose fair-value errors into ΔE and Δr components; report both |

---

## 9. Roadmap

| Session | Deliverable | Output files | Status |
|---|---|---|---|
| **Session 1** | Research dossier (this file) | `docs/macro-spx-models-research.md` | ✅ |
| **Session 2a** | Shared data layer (multpl + Yahoo SPX) + 4 multpl-only models | `tools/spx_models/data/{fetch_multpl,fetch_yahoo,panel}.py`, models: CAPE, ECY, Fed, W-G lite | ✅ |
| **Session 2b** | Yahoo-macro fallback (FRED blocked from this env) + 3 more models | adds `fetch_yahoo_macro.py`, IJTSRD, W-G expanded (10 predictors), Rapach combination | ✅ |
| **Session 2c** | FRED-dependent models (run when FRED reachable) | Chen-Roll-Ross, FRBNY adaptive factors, CAY, DDM, Damodaran ERP, GKX-lite NN | ⏸ blocked on FRED egress |
| **Session 3** | Walk-forward backtest harness + leaderboard | `tools/spx_models/backtest.py`, `data/spx-model-leaderboard.parquet`, Discord post | pending |
| **Session 4** | PPO RL ensemble + final report | `tools/spx_models/rl_ensemble.py`, `data/rl-ensemble-policy.zip`, Discord post | pending |

Each session ends with a Discord post summarizing what was added + the decision the user has to make next.

### Session 2b changes vs original plan

- **FRED outage**: `fred.stlouisfed.org` is unreachable from this sandbox (TCP read timeouts on every series; verified via both `curl` and Python `requests`). All FRED-dependent inputs (BAA/AAA default spreads, T10YIE, NFCI, USREC, INDPRO, PCEC96, UNRATE, FEDFUNDS, etc.) are unavailable until network egress is opened or a proxy/VPN is configured. The `fetch_fred.py` module remains in the tree and will work the moment connectivity returns.
- **Yahoo-macro fallback**: We added `fetch_yahoo_macro.py` covering `^TNX, ^IRX, ^FVX, ^TYX, ^VIX` via the Yahoo chart API (which does work). Caveats:
  - Yahoo's `range=max&interval=1mo` returns sparse quarterly samples for these rate symbols; `range=40y&interval=1mo` drops the most-recent ~24 monthly bars. We work around both bugs by fetching `range=40y&interval=1d` and resampling to month-start.
  - Yahoo's rate history begins 1986-06 (vs FRED's 1962), so W-G expanded and IJTSRD are estimated on a post-1990 sample (1990-02 onwards once VIX availability is enforced).
- **IJTSRD spec change**: The IJTSRD paper regresses SPX *level* on rate + unemployment. On 30+ years of data that just fits the trend and extrapolates absurdly. We use forward 12m log-return on rate + log(VIX) instead (standard W-G framing). Unemployment is substituted with VIX as a stress/regime proxy (corr ~0.45 since 1990) — defensible because the model is meant as a deliberately weak baseline, and both `b1` and `b2` come back with t-stats < 1 anyway, confirming the IJTSRD setup is not a strong predictor.
- **Welch-Goyal 10 of 15**: We implement DP, DY, EP, DE, BM, TBL, LTY, TMS, INFL, SVAR. Drop NTIS (net equity issuance — needs WRDS), DFY (Baa-Aaa — needs FRED), DFR / LTR (corporate vs. govt bond returns — needs FRED), and IK (Cochrane investment-capital from BEA NIPA). The 10 we have span all the channels that matter for the dispersion result: valuation (DP/DY/EP/DE/BM), short rate (TBL), long rate (LTY), slope (TMS), inflation (INFL), volatility (SVAR). Adding DFY/DFR/NTIS later changes the Rapach combination weights but should not invalidate the equal-weight headline.
- **Rapach combination variants**: We report equal-weight mean (headline, RSZ recommendation), median, trimmed mean (drop 1 high / 1 low), and an in-sample DMSPE proxy. A proper recursive DMSPE evaluation requires walk-forward and lives in Session 3.

### Live numbers (Session 2b, May 2026)

```
Current SPX: 7,355  EPS_TTM=$239.98  10Y=4.42%  CPI YoY=3.81%

PER-MODEL FAIR VALUE (12m horizon, in-sample):
  CAPE mean-reversion                      6,195   -15.8%
  Excess CAPE Yield                        6,999    -4.8%
  Fed Model (naive 1/10Y)                  5,429   -26.2%
  IJTSRD linear (10Y + VIX)                8,012    +8.9%
  Welch-Goyal lite (4 predictors)          8,479   +15.3%
  Welch-Goyal expanded (10 predictors)     8,831   +20.1%
  Rapach combination (equal-weight mean)   8,831   +20.1%

FAMILY MEAN [single_ratio]:   6,208   -15.6%   (n=3)
FAMILY MEAN [predictor_zoo]:  8,538   +16.1%   (n=4)

Cross-predictor dispersion (W-G expanded): 21.9% of mean.
This is the gap the RL ensemble in Session 4 has to learn to weight.
```

The bimodal result — single-ratio models saying `-16%`, predictor-zoo models saying `+16%` — is the headline disagreement and is exactly what motivated the multi-model approach in the first place.

---

## Sources (complete)

### NBER working papers
- [w10483 — Welch & Goyal, Comprehensive Look at Equity Premium Prediction](https://www.nber.org/papers/w10483)
- [w11468 — Welch & Goyal, predecessor version](https://www.nber.org/system/files/working_papers/w11468/w11468.pdf)
- [w14571 — Forecasting Stock Market Returns (Rapach)](https://www.nber.org/system/files/working_papers/w14571/w14571.pdf)
- [w16972 — Cochrane, Discount Rates (AFA Presidential)](https://www.nber.org/papers/w16972)
- [w20651 — Jivraj & Shiller, CAPE update](https://www.nber.org/system/files/working_papers/w20651/w20651.pdf)
- [w25398 — Gu, Kelly, Xiu, Empirical Asset Pricing via ML](https://www.nber.org/papers/w25398)
- [w26894 — Cieslak & Vissing-Jorgensen, Economics of the Fed Put](https://www.nber.org/system/files/working_papers/w26894/w26894.pdf)
- [w27283 — Bordalo et al., Expectations of Fundamentals & Stock Puzzles](https://www.nber.org/system/files/working_papers/w27283/revisions/w27283.rev0.pdf)
- [w8059 — Bansal & Yaron, Long-Run Risks](https://www.nber.org/papers/w8059)
- [w10581 — Pastor & Veronesi, Was there a NASDAQ Bubble](https://www.nber.org/papers/w10581)

### Federal Reserve System
- [FRBNY SR475 — Çakmaklı & van Dijk, Adaptive Macro Indices](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr475.pdf)
- [FRBNY ACM Term Premia data](https://www.newyorkfed.org/research/data_indicators/term-premia-tabs)
- [FRBNY Liberty Street — Treasury Term Premia 1961-Present](https://libertystreeteconomics.newyorkfed.org/2014/05/treasury-term-premia-1961-present/)
- [Federal Reserve FSR Apr 2025 — Asset Valuations](https://www.federalreserve.gov/publications/April-2025-financial-stability-report-Asset-Valuations.htm)
- [Federal Reserve FEDS — Robustness of Long-Maturity Term Premium Estimates](https://www.federalreserve.gov/econres/notes/feds-notes/robustness-of-long-maturity-term-premium-estimates-20170403.html)
- [FRB FEDS 2011-47 — Habit Formation Asset Pricing](https://www.federalreserve.gov/pubs/feds/2011/201147/index.html)
- [St. Louis Fed — FRED-MD Database (McCracken-Ng)](https://files.stlouisfed.org/files/htdocs/fred-databases/fredmd.pdf)
- [St. Louis Fed — FRED-QD Database](https://www.stlouisfed.org/publications/review/2021/01/14/fred-qd-a-quarterly-database-for-macroeconomic-research)

### IMF
- [GFSR April 2026 Chapter 1](https://www.imf.org/-/media/files/publications/gfsr/2026/april/english/ch1.pdf)
- [GFSR October 2025 Chapter 1](https://www.imf.org/-/media/files/publications/gfsr/2025/october/english/ch1.pdf)
- [GFSR Press Briefing Spring 2025](https://www.imf.org/en/news/articles/2025/04/22/tr-04222024-gfsr-press-briefing)

### BIS
- [WP 1272 — Financial Conditions and the Macroeconomy](https://www.bis.org/publ/work1272.pdf)
- [WP 606 — Market Volatility, Monetary Policy, Term Premium](https://www.bis.org/publ/work606.pdf)
- [WP 1326 — Monetary Policy and Private Equity](https://www.bis.org/publ/work1326.pdf)
- [BIS Conf Paper — Equity Prices & Monetary Policy US](https://www.bis.org/publ/confp05o.pdf)
- [BIS Q.R. — Term Premia Models and Stylised Facts](https://www.bis.org/publ/qtrpdf/r_qt1809h.pdf)

### ECB
- [Economic Bulletin Box 5/2017 — Equity Price DDM Decomposition](https://www.ecb.europa.eu/pub/pdf/other/ebbox201705_02.en.pdf)
- [WP 2787 — Dividend Discount Model Impact](https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp2787~04133e65f9.en.pdf)
- [WP 2369 — Price-Dividend Ratio & Long-Run Stock Returns](https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp2369~7afcf6a5c4.en.pdf)
- [Occasional Paper 254 — Cost of Equity of Euro Area Banks](https://www.ecb.europa.eu/pub/pdf/scpops/ecb.op254~664ed99e11.en.pdf)
- [Economic Bulletin Box 2024 — US Equity Prices Resilience](https://www.ecb.europa.eu/press/economic-bulletin/focus/2025/html/ecb.ebbox202408_01~d2c7bd5eba.en.html)
- [Banco de España DO 2207 — Measuring ERP with DDM](https://www.bde.es/f/webbde/SES/Secciones/Publicaciones/PublicacionesSeriadas/DocumentosOcasionales/22/Files/do2207e.pdf)

### Academic journals (free PDF available)
- [Cochrane "Discount Rates" Presidential Address — JoF 2011](https://www.johnhcochrane.com/news-op-eds-all/discount-rates)
- [Bansal-Yaron — JoF 2004 (Duke mirror)](https://people.duke.edu/~rb7/bio/bansal_yaron.pdf)
- [Gu-Kelly-Xiu — RFS 2020](https://academic.oup.com/rfs/article/33/5/2223/5758276)
- [Chen-Pelger-Zhu — Management Science 2024](https://pubsonline.informs.org/doi/10.1287/mnsc.2023.4695) ([arXiv 1904.00745](https://arxiv.org/pdf/1904.00745))
- [Lettau-Ludvigson CAY — JoF 2001](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00347)
- [Pastor-Veronesi Nasdaq Bubble — JFE 2006](https://www.sciencedirect.com/science/article/abs/pii/S0304405X05002163)
- [Chen-Roll-Ross — J. Business 1986](https://ideas.repec.org/a/ucp/jnlbus/v59y1986i3p383-403.html)
- [Asness "Fight the Fed Model" — Columbia/AQR](https://business.columbia.edu/sites/default/files-efs/pubfiles/3038/inflation_stock_market.pdf)
- [Rapach-Strauss-Zhou — RFS 2010 (working paper)](https://efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2017-Athens/papers/EFMA2017_0371_fullpaper.pdf)

### Recent ML / DRL papers
- [MDPI Mathematics 2025 — Out-of-Sample ERP Predictability](https://www.mdpi.com/2227-7390/13/2/257)
- [arXiv 2509.10483 — Equity Premium Prediction](https://arxiv.org/pdf/2509.10483)
- [arXiv 2010.04404 — DRL for Asset Allocation in US Equities](https://arxiv.org/pdf/2010.04404)
- [arXiv 2511.11481 — Risk-Aware DRL Dynamic Portfolio Optimization](https://arxiv.org/html/2511.11481v1)
- [arXiv 2511.17963 — Hybrid LSTM + PPO Portfolio Opt](https://arxiv.org/pdf/2511.17963)
- [arXiv 2502.02619 — Regret-Optimized DRL](https://arxiv.org/pdf/2502.02619)
- [PLOS One — Explainable DRL Portfolio](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0315528)

### IJTSRD (baseline straw man)
- [IJTSRD 27819 — Stock Index Linear Regression](https://www.ijtsrd.com/papers/ijtsrd27819.pdf)
- [IJTSRD 70489 — Stock Prediction](https://www.ijtsrd.com/papers/ijtsrd70489.pdf)

### Data sources (for Session 2 plumbing)
- [Shiller `ie_data.xls`](http://www.econ.yale.edu/~shiller/data.htm) — quarterly-updated
- [Welch's UCLA Goyal-Welch predictor dataset](https://docs.google.com/spreadsheets/d/1g4LOaRj4TvwJr9RIaA_nwL_B-cnzVChWHX-tWzwZHHM) — annually-updated
- [Damodaran monthly data (NYU Stern)](https://pages.stern.nyu.edu/~adamodar/) — monthly
- [McCracken FRED-MD](https://research.stlouisfed.org/econ/mccracken/fred-databases/) — monthly auto-update
- [NY Fed ACM Term Premia](https://www.newyorkfed.org/research/data_indicators/term-premia-tabs) — monthly auto-update
- [Philly Fed SPF (long-run growth)](https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/survey-of-professional-forecasters) — quarterly
- [Chicago Fed NFCI](https://www.chicagofed.org/research/data/nfci/current-data) — weekly
- [FRED CSV endpoint](https://fred.stlouisfed.org/graph/fredgraph.csv?id=SERIES_ID) — any series, no API key
