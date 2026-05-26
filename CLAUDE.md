# Project: Finance Tools Suite

## Overview
A suite of Python-based finance analysis tools that fetch market/economic data and post results to Discord via webhooks. Located at `d:\Deepseek-ollama\finance\ai-hedgefund\tools\`.

## Behavioral Guidelines

Behavioral guidelines to reduce common LLM coding mistakes. Tradeoff: these bias toward caution over speed — for trivial tasks, use judgment.

### 1. Think Before Coding
Don't assume. Don't hide confusion. Surface tradeoffs.
- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First
Minimum code that solves the problem. Nothing speculative.
- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.
- Ask: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes
Touch only what you must. Clean up only your own mess.
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.
- Test: every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution
Define success criteria. Loop until verified.
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"
- For multi-step tasks, state a brief numbered plan with a verify step for each.
- Strong success criteria enable independent looping; weak criteria ("make it work") require constant clarification.

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## Project Structure
```
d:\Deepseek-ollama\
├── CLAUDE.md                          ← this file
├── finance/ai-hedgefund/
│   ├── tools/                         ← all runnable scripts live here
│   │   ├── run-all.py                 ← master runner (executes all scripts sequentially)
│   │   ├── watchlist.json             ← shared ticker list (26 Purple list tickers)
│   │   ├── macro-calendar.py          ← 2026 economic event dates (FOMC, CPI, NFP, Retail Sales, ECI, etc.)
│   │   ├── econ-release-analysis.py   ← economic release impact analysis
│   │   ├── econometrics-report.py     ← FRED data reports (GDP, CPI, NFP, Retail Sales, Jobs Report)
│   │   ├── technicals-scanner.py      ← technical analysis on watchlist (uses Yahoo chart API)
│   │   ├── volatility-regime.py       ← VIX regime classification (uses Yahoo chart API)
│   │   ├── sector-rotation.py         ← sector + EW sector + subsector rotation (11 CW + 11 EW + 26 subsectors, RS vs SPY + RSP)
│   │   ├── rrg-scanner.py            ← Relative Rotation Graphs (daily+weekly, CW sectors vs SPY + EW sectors vs RSP + subsectors vs SPY)
│   │   ├── breadth-scanner.py        ← market breadth per sector (% above MAs, A/D, EW-CW divergence, thrust/collapse)
│   │   ├── bubble-scanner.py         ← Druckenmiller/AQR/PTJ bubble-riding trend planner (regime gate + entry archetypes A-G + exit ladder)
│   │   ├── bubble-backtest.py        ← single-date backtest harness for bubble-scanner (with per-entry diagnostics)
│   │   ├── bubble-sweep.py           ← date-range sweep harness for bubble-scanner
│   │   ├── gex-profile.py            ← SPX GEX profile (Perfiliev): nearest expiry + next OpEx, call/put walls (CBOE delayed JSON)
│   │   ├── gex-profile-equity.py     ← Per-ticker GEX profile (any optionable US equity/ETF) — CBOE delayed JSON
│   │   ├── volume-exhaustion-scanner.py ← Capitulation/Blowoff/Waning regime classifier (Wyckoff SC-AR-ST + Spring + multi-SC + OI %-change layer)
│   │   ├── volume-exhaustion-backtest.py ← Historical validation harness (19 test events: GFC, COVID, dot-com, 1974 oil-shock, etc.)
│   │   ├── oi-history.json           ← Daily OI snapshots per ticker (60d rolling window)
│   │   ├── shares-outstanding-cache.json ← 7-day-TTL cache of Yahoo quoteSummary float counts
│   │   ├── run-ticker.py             ← Per-ticker analysis runner (5 tools: fundamental-thesis + fundamentals-scanner + entry-analyzer + gex-profile-equity + volume-exhaustion-scanner)
│   │   ├── pyramid-scanner.py        ← add-to-winners decision tool (reads pyramid-positions.json)
│   │   ├── pyramid-positions.json    ← per-position state (entry, shares, adds, stop)
│   │   ├── entry-analyzer.py         ← multi-timeframe entry candidate scoring (D/W/M, 30wk SMA, Fib swing, multi-AVWAP)
│   │   ├── entry-candidates.json     ← list of tickers for entry-analyzer to score
│   │   ├── fx-models.py              ← FX econometric models (Alpha Vantage fallback for FX)
│   │   ├── econ-predictor.py          ← economic predictive model (FRED + equity data)
│   │   ├── sortino-optimizer.py       ← Sortino ratio portfolio optimizer (CW sectors + EW sectors + subsectors + watchlist, 1W/4W/3M)
│   │   ├── stock-discovery.py         ← dynamic stock discovery (cross-validates subsectors + EW + CW sectors)
│   │   ├── fundamentals-scanner.py    ← fundamental quality + valuation overlay for stock-discovery picks
│   │   ├── etf-holdings.json          ← top 15-20 holdings per subsector + EW + CW sector ETF (48 ETFs, update quarterly)
│   │   ├── earnings-whisper.py        ← earnings drift detection (has Alpha Vantage key)
│   │   └── ... (other tools not in run-all.py)
│   ├── skills/                        ← skill definitions
│   ├── memory/                        ← persistent memory
│   └── docs/
├── trading_gex/                       ← GEX trading tools (separate)
├── transcripts/
├── requirements.txt
└── various portfolio/IB scripts
```

## run-all.py — Master Runner
Executes 15 scripts sequentially with 5-min timeout each. Scripts with `uses_yf=True` get a 10s cooldown after running.

Current order:
1. macro-calendar.py (no yf)
2. econ-release-analysis.py (no yf)
3. econometrics-report.py (no yf)
4. technicals-scanner.py (yf)
5. volatility-regime.py (no yf)
6. sector-rotation.py (no yf)
7. rrg-scanner.py (no yf)
8. breadth-scanner.py (no yf)
9. bubble-scanner.py (no yf)
10. volume-exhaustion-scanner.py (no yf)
11. gex-profile.py (no yf)
12. fx-models.py (yf)
13. econ-predictor.py (no yf)
14. sortino-optimizer.py (no yf)
15. stock-discovery.py (no yf)
16. fundamentals-scanner.py (no yf)
17. early-trend-scanner.py (no yf)
18. late-trend-scanner.py (no yf)

## Discord Webhooks
Each script posts to its own Discord channel via webhook:

| Script | Webhook URL |
|--------|------------|
| macro-calendar.py | `https://discord.com/api/webhooks/1470302148775641252/Bgicj_L7b_HwvoZEo7wgrrk7EnDRvxQkyq0lh1pDntPFgJ5_Ltaj6UbbHbakzMjtRCEl` |
| econ-release-analysis.py | `https://discord.com/api/webhooks/1470442159751565419/4fJthzTsNqGNDoCBacARt88JeIhoL9LP-RUiCjT8LyBneCUQ3fQFeL3mbDN27CoCfPKe` |
| econometrics-report.py | `https://discord.com/api/webhooks/1471470640816197725/fO2N3HV360Pfs6WfAQOTIokJrjE60akxbkKa9cmj0Fs-jJvSJyXZLdotbCssmY3v30MV` |
| technicals-scanner.py | `https://discord.com/api/webhooks/1471470797687357557/sDi1EQwqIItykMRbV3_JEecRv-yitMyg8apus_ko8bMzKJZ2RNZbbQPKmn7VguraMN4G` |
| sector-rotation.py | `https://discord.com/api/webhooks/1470444998011916423/oME5DBVEBixjtSkJoYddSv4QG5EGQNSZMyKak5Zt8LehjQ_3b7jpj14t9U2JEhnPE9pI` |
| volatility-regime.py | `https://discord.com/api/webhooks/1470447471695102234/OdDlYvW9GeIE1v8Hmauq-jx13RQtyDS3KDoYMLNYkFZG1bCEzfYppLhg9Qpb9dzt_97P` |
| fx-models.py | `https://discord.com/api/webhooks/1471466040931258431/MFf5gibpTsLv3eAfwDSJafTyS9lLLCHxMvOZYdnhS85X8TARZpfHzug3OsOMhsIz-2mW` |
| econ-predictor.py | `https://discord.com/api/webhooks/1471466326710288559/oOh2ApQCZ__k9feKMzgzJvuDb3jESFDZvyY8mYObjoDU_RIRLKAhpZK3vzZC2ijeRFNj` |
| technicals-dashboard.py | `https://discord.com/api/webhooks/1470466815397335183/GZyX60SqadXRFM1OFTwAJz2l9p5GGheseUCKQ370jtE0pxJ3UHNWHQpbDWpDOAWd-CHK` |
| earnings-whisper.py | `https://discord.com/api/webhooks/1470313478052122634/ERcpnJvbOF9HwlXtu6-KlCJh-CNWxdVi480HGY8bv3S3ZpIGscJPUinF7cTCN5DKihfR` |
| rrg-scanner.py | `https://discord.com/api/webhooks/1471735980288512084/elHYE5X2rdUpudK_8K-5pdiSPGEfetkh0IYFO_TFTMeiBUarcgJ5nYgzvEreEry2E5fR` |
| sortino-optimizer.py | `https://discord.com/api/webhooks/1471847874877984880/GyBts1ebRF-dO-ZGp5Wz5AIVypIrCc9mjqn2LOERF9v4UTUEYwIM_oqoJgqSK-dyRmri` |
| stock-discovery.py | `https://discord.com/api/webhooks/1473040356659564565/g5-0D2rF-SsnUk_p-4uejtmUht56AkNY2E4pffKpnjXOCFIOlrQmugL_6BdQZzl-hatc` |
| breadth-scanner.py | `https://discord.com/api/webhooks/1473219539482447932/ldQgJErtPUj1aYnwgCj_HsMvt_BbuQRdzhdQ-9eXc4fvBx1R9ypYrAUzmIUbcb2_Mp2B` |
| fundamentals-scanner.py | `https://discord.com/api/webhooks/1475327530025222164/_IAvJ8JX2HWXRPDYER00UN5qj07DyoPNTZlk04TFV3SDrEaHcIxxe0-4J85LNgziGE39` |
| bubble-scanner.py | `https://discord.com/api/webhooks/1504380703645761536/NrBply5IJF3F8h8BB8qANuB1-8lLsPp4xEz_zywcj5205cS0ZzMJNacAsdTj3029RduR` |
| gex-profile.py | `https://discord.com/api/webhooks/1507392186222776422/HaApw51ljzILxhNqne8P5u_u5YwbSA5aF3qjQ1ieTtZatbx1MrooeLVzfOKg3OWtyNRr` |
| gex-profile-equity.py | `https://discord.com/api/webhooks/1508366696212205660/WvjfoSkPzWNbIhNjL0R5eHFatKPzbCUDOTDqAslSgnPIa0N8-0sGLLaLoFMiSIBxsnjt` |
| volume-exhaustion-scanner.py | `https://discord.com/api/webhooks/1508730602189488209/1OKp8ofZ3oN_8xUOfqgqNlIf7Nd26pdrB0_T8Y7HHRsmpM3E7ePApunw20JK6YD4h7IF` |

## Key Technical Patterns

### Discord Posting
- **Text**: `requests.post(WEBHOOK_URL, json={"content": message}, timeout=30)`
- **Images**: `requests.post(WEBHOOK_URL, files={"file": (filename, bytesio_buf, "image/png")})`
- All scripts use `send_discord(message)` pattern with module-level `DISCORD_WEBHOOK_URL`
- Discord message limit: 2000 chars. Split long messages.

### Data Fetching — USE Yahoo Chart API, NOT yfinance
**yfinance is rate-limited and unreliable.** Prefer the direct Yahoo chart API:
```python
def fetch_ohlcv(ticker: str, period: str = "1y") -> pd.DataFrame | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={period}&interval=1d"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    resp = requests.get(url, headers=headers, timeout=15)
    # Parse result["chart"]["result"][0] → timestamps + indicators.quote[0]
    # Return DataFrame with Open, High, Low, Close, Volume
```
- Use `ThreadPoolExecutor(max_workers=5)` for parallel fetching
- Range options: `1d`, `5d`, `1mo`, `3mo`, `6mo`, `1y`, `2y`, `5y`, `max`
- Interval options: `1d`, `1wk`, `1mo`
- Scripts already using this: `technicals-scanner.py`, `sector-rotation.py`, `volatility-regime.py`, `rrg-scanner.py`, `sortino-optimizer.py`, `econometrics-report.py`, `stock-discovery.py`

### FRED Data (Economic Series)
```python
url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
# No API key needed. Returns CSV with DATE, value columns.
```
Key series: GDP, CPIAUCSL (CPI), UNRATE, PAYEMS (NFP), RSAFS (Retail Sales), CES0500000003 (Avg Hourly Earnings), FEDFUNDS, T10Y2Y, etc.

### Alpha Vantage (FX Fallback)
- API key: `1SIVEVQAAYTRTLBV` (found in `earnings-whisper.py`)
- Used in `fx-models.py` when yfinance FX data fails
- `https://www.alphavantage.co/query?function=FX_DAILY&from_symbol=EUR&to_symbol=USD&outputsize=full&apikey=KEY`

### Path Convention
All scripts use project-relative paths:
```python
TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = TOOLS_DIR.parent.parent  # d:\Deepseek-ollama\finance\ai-hedgefund
```
**Never use** `~/.clawd/` or `Path.home() / "clawd"` — those are Linux-only and don't exist on this Windows machine.

### Chart Rendering
- Use `matplotlib` with `Agg` backend (headless, no GUI)
- `io.BytesIO()` for in-memory image buffer
- Dark theme preferred (`#1a1a2e` background)
- Post via Discord `files=` parameter

## Watchlist (watchlist.json)
Dual format — both `tickers` array and `stocks.holdings` dict:
```json
{
  "tickers": ["KRE", "WMT", "STEL", ...],
  "stocks": { "holdings": { "KRE": {"weight": 1}, ... } }
}
```
26 tickers from Purple list. Used by `technicals-scanner.py` and `earnings-whisper.py`.

## What Was Built (Session History)

### Completed
1. Added retail sales data extraction to `econometrics-report.py` (Report 4: RSAFS)
2. Added retail sales release dates to `macro-calendar.py`
3. Added wage growth (Average Hourly Earnings CES0500000003) to both files
4. Added ECI quarterly dates to `macro-calendar.py`
5. Created combined Jobs Report (Report 5) in `econometrics-report.py`: NFP + Unemployment + Wage Growth
6. Created `run-all.py` runner for 8 scripts
7. Fixed `fx-models.py`: clawdbot → webhook, added Alpha Vantage FX fallback
8. Fixed `econ-predictor.py`: updated webhook URL
9. Fixed `econometrics-report.py`: clawdbot → webhook, CLAWD → project-relative paths
10. Fixed `technicals-scanner.py`: clawdbot → webhook, CLAWD → project-relative paths, full rewrite to Yahoo chart API
11. Updated `watchlist.json` with 26 Purple list tickers
12. Added yfinance cooldown delays in `run-all.py`

### Completed (continued)
13. **RRG Scanner (`rrg-scanner.py`)** — Relative Rotation Graphs for S&P 500 sectors + subsectors
    - 37 ETFs (11 sectors + 26 subsectors) vs SPY
    - Daily (6mo, 1d) + Weekly (2y, 1wk) charts for both groups = 4 charts
    - Dark theme 4-quadrant scatter with trailing tails, quadrant classification
    - Modular `run_rrg()` function for any ticker group + benchmark
    - Added to `run-all.py` as script #7
14. **Subsector rotation in `sector-rotation.py`** — Added 26 subsector/thematic ETFs
    - Parallel fetching via ThreadPoolExecutor(5), reuses SPY data
    - Separate subsector table with top-5 inflows/outflows posted to same Discord channel
15. **Econometrics Report (`econometrics-report.py`)** — Replaced yfinance with Yahoo Chart API
    - `batch_download()` now uses parallel `fetch_close()` via Yahoo Chart API
    - 10y monthly index data for econ predictor also uses Yahoo Chart API
    - No longer flagged as `uses_yf` in `run-all.py`

16. **Sortino Optimizer (`sortino-optimizer.py`)** — Sortino ratio portfolio optimization
    - 3 groups: 11 sector ETFs, 26 subsector ETFs, 26 watchlist stocks (from watchlist.json)
    - 3 timeframes: 1W (5 days), 4W (20 days), 3M (63 days)
    - scipy SLSQP optimizer with 6 random starting points, long-only constraint
    - Risk-free rate from FRED FEDFUNDS series
    - Dark-theme grouped bar charts + monospace text tables
    - Sortino interpretation: <1.0 Risky | 1-2 Good | 2-3 Excellent | 3+ Elite
    - 6 Discord posts (text table + bar chart for each group)
    - Added to `run-all.py` as script #10

17. **Stock Discovery Scanner (`stock-discovery.py`)** — Dynamic stock discovery from hot subsectors
    - Cross-validates subsector selection across 3 independent methods:
      - Sector Rotation (1W RS vs SPY + momentum phase)
      - RRG Quadrant (JdK RS-Ratio/Momentum, Leading/Improving/Weakening/Lagging)
      - Sortino Ratio (4W risk-adjusted return)
    - Posts cross-validation report showing consensus (3/3 STRONG, 2/3 AGREE, 1/3 SPLIT)
    - Pulls ETF holdings from `etf-holdings.json` (48 ETFs: 26 subsectors + 11 EW + 11 CW sectors, 15-20 holdings each)
    - 5-module scoring system per constituent stock:
      - Module 1 (30%): Mansfield Relative Strength vs subsector ETF
      - Module 2 (25%): Momentum composite (weighted ROC + MA alignment + MACD direction)
      - Module 3 (25%): Volume characteristics (rel vol, up/down ratio, CMF, volume trend)
      - Module 4 (20%): Technical setup quality (ADX, RSI, Bollinger, distance from highs, ATR compression)
      - Module 5: Risk flags (LOW LIQ, BELOW 200MA, OVERBOUGHT, OVERSOLD, LOW RS) — no score impact
    - All scores percentile-ranked within each ETF's constituents
    - Output: Top 10 per ETF as monospace table + scatter chart (X=Momentum, Y=RS, size=Volume, color=Technical)
    - CLI override: `python stock-discovery.py SMH XRT` skips cross-validation
    - Added to `run-all.py` as script #11

18. **RSP (Equal-Weight S&P 500) comparison in `sector-rotation.py`**
    - Added RSP as second benchmark alongside SPY to remove mega-cap tech skew
    - Both benchmarks shown in header: `SPY: 1W=+X.X% | 4W=+X.X%  ||  RSP: 1W=+X.X% | 4W=+X.X%`
    - Tables show both `vSPY` and `vRSP` columns (RS vs cap-weighted and equal-weighted S&P 500)
    - SPY-RSP divergence analysis on rotation line (mega-cap driven / broad strength / balanced)
    - Per-sector SPY/RSP divergence alerts when vSPY and vRSP disagree by >1.5%
    - Subsector table also gets RSP columns
    - Benchmarks dict reused for subsector fetch (avoids re-fetching)

19. **Equal-Weight Sector ETFs (11 Invesco RSP* ETFs) across all tools**
    - Added 11 EW sector ETFs: RSPT, RSPF, RSPG, RSPH, RSPN, RSPS, RSPD, RSPU, RSPC, RSPM, RSPR
    - **`sector-rotation.py`**: 3rd section showing EW sectors + CW vs EW divergence table per sector (NARROW=mega-cap driven, BROAD=equal-weight stronger)
    - **`rrg-scanner.py`**: Separate RRG chart group "EW Sectors" vs RSP benchmark (daily+weekly), producing 6 charts total (CW sectors, EW sectors, subsectors × daily/weekly)
    - **`sortino-optimizer.py`**: 4th optimization group "EW Sectors" with Sortino ratios across 1W/4W/3M timeframes
    - **`stock-discovery.py`**: EW sector ETFs included in cross-validation universe alongside subsectors
    - **`etf-holdings.json`**: Added top 20 holdings for all 11 EW sector ETFs

20. **Cap-Weighted Sector ETFs added to Stock Discovery**
    - Added top 20 holdings for all 11 CW sector ETFs (XLK, XLF, XLE, XLV, XLI, XLP, XLY, XLU, XLC, XLB, XLRE) to `etf-holdings.json`
    - **`stock-discovery.py`**: CW sectors now included in cross-validation universe (48 ETFs total: 26 subsectors + 11 EW + 11 CW)
    - Fallback escalation: sectors with no/weak subsector coverage (XLP, XLU, XLE, XLF) auto-added when their EW counterpart is selected
    - Multi-ETF consensus detection: stocks appearing in 2+ ETF top-10 lists highlighted as consensus picks
    - BRK.B/MOG.A ticker sanitization (dot→hyphen for Yahoo API)
    - Scan list expanded from 5 to 7 max ETFs to accommodate escalation

21. **Market Breadth Scanner (`breadth-scanner.py`)**
    - Scans all 11 CW sector ETFs and their top 20 constituents (~220 tickers)
    - 4 breadth metrics per sector: % above MAs (SMA50, SMA200, EMA21), A/D ratio + new highs/lows, EW vs CW divergence, breadth thrust/collapse detection
    - Composite Breadth Health Score: STRONG (>0.70) / HEALTHY (0.50-0.70) / MIXED (0.30-0.50) / WEAK (<0.30)
    - Alerts: NARROW LEADERSHIP (CW > EW by >2%), DETERIORATING/IMPROVING (10-day trend), THRUST/COLLAPSE
    - 2 charts: breadth heatmap (sectors × metrics) + breadth momentum line chart (% above SMA50 over 3 months)
    - CLI override: `python breadth-scanner.py XLK XLP` to scan subset of sectors
    - Added to `run-all.py` as script #8 (after rrg-scanner, before fx-models)
    - Discord webhook: TBD
    - **Russell-3000 52-week breadth section** (added as a final block in the same run):
      - **Universe**: top 3000 US-listed common stocks by market cap, sourced from `rreichel3/US-Stock-Symbols` GitHub mirror (NASDAQ + NYSE full ticker JSONs with marketCap/sector/country metadata). Filtered to `country=US`, dropped names matching rights/warrants/units/preferreds/notes patterns, dropped tickers ending in `R`/`W` suffixes, $100M market-cap floor. Sorted by marketCap, deduped, capped at 3000. Result: ~2870 names. Cached to `russell-3000.json`, refreshed if file older than 7 days.
      - **Fetch**: Yahoo chart API meta-only (`range=1d&interval=1d`) — uses `regularMarketPrice`, `fiftyTwoWeekHigh`, `fiftyTwoWeekLow` from the meta block. One tiny request per ticker, ~125 tickers/sec sustained throughput with `requests.Session` connection-pooled `ThreadPoolExecutor(max_workers=20)`. Full universe scan ~25-35s.
      - **Classification**: NH if `price >= 52w_high × 0.999`, NL if `price <= 52w_low × 1.001` (0.1% slack to capture true tape highs/lows including intraday).
      - **Output**: headline counts + NH/NL ratio + regime label (`STRONG RISK-ON` ≥5, `RISK-ON` ≥2, `NEUTRAL` ≥0.5, `RISK-OFF` ≥0.2, `STRONG RISK-OFF` else; `EXTREME RISK-ON` when no NL); per-sector NH/NL/total breakdown; top 15 NH sorted by % from 52w low (strongest momentum names); top 15 NL sorted by drawdown from 52w high.
      - **`run-all.py` timeout bumped to 900s for `breadth-scanner.py` only** since the Russell scan adds ~30s on top of existing 3-5min sector breadth.

    **Worst-case stress test for 52w section**:
    1. **iShares CSV blocked** (returns HTML wrapper now) → sourced from rreichel3 GitHub mirror instead; falls back to local `russell-3000.json` cache; if cache missing too, posts an error but doesn't crash the main breadth output.
    2. **Yahoo rate-limits at 3000 calls** → mitigated by `requests.Session` + 20-worker pool; partial results posted with coverage stat (current run achieved 99.9%).
    3. **Tickers with dots** (BRK.B) → normalized to `BRK-B` per Yahoo convention before fetching.
    4. **Delisted/merged names in cached list** → silent skip; reflected in coverage % (e.g. "Scanned 2866/2869 (99.9%)").
    5. **Discord 2000-char limit** with 30+ name listings → format split into 3 chunks (header+sectors, top-NH table, top-NL table), each posted independently.
    6. **Yahoo's `fiftyTwoWeekHigh` includes today** → so an intraday tape new high counts correctly without needing a separate condition.
    7. **`∞` in NH/NL ratio crashes Windows CP1252 console** when running locally → swapped to ASCII `"inf"` literal.

22. **Stock Discovery output pipeline (`discovery-output.json`)**
    - `stock-discovery.py` now saves top 10 picks per ETF to `discovery-output.json`
    - Used by downstream scanners (trade-setup, early/late trend) to auto-read shortlist
    - Format: `{"timestamp": ..., "etfs_scanned": [...], "top_picks": {"ETF": [tickers]}}`

23. **Fundamentals Scanner (`fundamentals-scanner.py`)** — fundamental quality + valuation overlay for stock-discovery.py picks
    - Input: `discovery-output.json` (auto, < 24h old), CLI override (`python fundamentals-scanner.py NVDA AMAT`), `watchlist.json` fallback
    - Data: Yahoo quoteSummary API — `financialData`, `defaultKeyStatistics`, `earningsTrend` modules (no API key)
    - Metrics: EV/EBITDA, Trailing P/E, Forward P/E, EV/Sales, P/B, EV/Gross Profit, ROIC, WACC, ROIC-WACC Spread, Gross Margin, Op Margin, Rev Growth, Fwd EPS Growth
    - ROIC: `EBIT×(1-0.21) / (totalDebt + bookValue×shares)` | WACC: `4.5% + min(beta,3)×5.5%`
    - Scoring (percentile-ranked within ETF cohort): Valuation 40% + Quality 35% + Forward Outlook 25%
    - Sector overrides: XLF uses P/E+P/Book (no EV/EBITDA); XLRE weights P/Book heavily
    - Sector-specific extras: Tech(Rev Growth, FCF Yield), Financials(ROE, P/Book), Energy(FCF Yield, Div Yield), Industrials(Op Leverage), Staples(Div Yield), Utilities(Div Yield, Payout), REITs(P/Book, Div Yield)
    - Classification: 80-100 STRONG | 60-79 GOOD | 40-59 MIXED | <40 WEAK
    - Output: 3 Discord text messages per ETF (header+top5, full table, sector context) + scatter chart
    - Scatter: X=EV/EBITDA cheapness %ile, Y=ROIC-WACC spread, bubble size=Rev Growth, color=Fwd P/E attractiveness
    - Added to `run-all.py` as script #13 (after stock-discovery, before trade-setup)

24. **Bubble Scanner (`bubble-scanner.py`)** — Druckenmiller/AQR/PTJ bubble-riding trend planner
    - **Stage 0 Regime Gate**: VIX level (LOW/NORMAL/ELEVATED/EXTREME) + breadth proxy (% of 11 CW sectors > SMA50 & SMA200). GATE OPEN when breadth STRONG/HEALTHY AND vol LOW/NORMAL.
    - **Stage 1 Qualifier** on all 48 ETFs in `etf-holdings.json`:
      - C1: 1Y return > +100%
      - C2: > 2σ stretch from 200-day SMA
      - C3: Annualized 3M return > 12M return (accelerating)
      - C4: Regime gate
      - **Rule change vs original spec**: C1 alone is sufficient for FULL BUBBLE classification (the +100% 1Y return is the load-bearing condition; C2/C3 are nice-to-haves). `bubble_days()` uses the same C1-only rule.
    - **Stage 2 Tradeable Universe**: ETF holdings ∩ watchlist (if non-empty) ∪ ETF itself.
    - **Stage 3 Entry Archetypes** — bubble-tuned versions of the spec:
      - **A — Tight-Flag Breakout**: 5/7/10-day base where range < 2.5× ATR(14), close > base high, vol > 1.5× avg, ADX > 25, RS line at 60-day high. Replaces the original 30-day consolidation window which never qualified in volatile bubble names.
      - **B — Boring Pullback (loosened)**: price within **1× ATR** of EMA21 or SMA50 (was 1% — too tight for $400+ stocks), RSI cooled to 40-55 from prior > 65, bullish reversal candle, volume confirm.
      - **C — Failed Breakdown / Spring**: intraday break below support, close back above, RSI rebound < 40 → > 50, vol > 1.5× avg.
      - **D — RS Leadership**: parent bubble-days ≥ 3 (was 20 — too slow), 13w return + RS 26w positive, price > all major MAs, weekly RSI > 55 rising, ADX > 25.
      - **E — Inside-Day / NR7 Breakout** (new): yesterday was inside day OR NR7 (smallest range of last 7), today close > yesterday's high, vol > 1.2× avg. Captures micro-coil continuations in volatile names.
      - **F — SMA50 Reclaim** (new): price closes back above SMA50 after ≥ 8 of last 10 sessions below; still above SMA200; vol gate is loose (≥ 1.0× avg, but reports "light vol" if below 1.2×). Catches recovery rallies that don't form a tight base.
      - **G — Higher-Low / Higher-High** (new): scipy argrelextrema detects swing points; today's swing low > prior swing low AND close > most recent swing high. Trend-resumption catch.
    - **Stage 4 Exit Ladder** (graduated): Flashing Yellow / Solid Yellow / Orange / Red.
      - Bearish weekly RSI divergence (Orange) now **suppressed when price is making a new 20-day high** — in parabolic moves RSI gets pinned and the raw rule fires every day during the strongest part of the trend.
      - Other Orange triggers: daily close < EMA21, up/down vol ratio < 0.8 over 10d, 2σ down day on > 2× vol.
      - Red triggers: close below 10-day pivot low, weekly close < 10wk MA, 3 lower highs after parabolic, gap below SMA50 on volume.
    - **Stage 5 Vol-Adjusted Sizing**: `base × target_vol(50%) / annualized_vol_60d`. Base = 5% (FULL BUBBLE), 3% (EMERGING). Per-name cap 25%. No per-theme cap (bubble theses concentrate by design).
    - **Stage 6 Output**: 6-section Discord post chunked under 2000 chars.
    - **Backtest harness**: `bubble-backtest.py TICKER YYYY-MM-DD` for single date + per-condition diagnostics. `bubble-sweep.py TICKER START END` for date-range sweep.
    - Validated on MU and NVDA Mar-Apr 2026 (Entry E caught MU at $441 → $462; Entry F caught NVDA's $184 SMA50 reclaim → $202).
    - Added to `run-all.py` as script #9 (after `breadth-scanner.py`, before `fx-models.py`).

25. **Pyramid Scanner (`pyramid-scanner.py`)** — Probe-then-commit position builder
    - Reads `pyramid-positions.json` (manually maintained). Schema includes `initial_shares` (the stab), `target_shares` (intended final size), `entry_price`, `parent_etf`, `current_stop`, `adds[]`.
    - **Philosophy (revised from classic pyramid)**: take small *stab* first (10-20% of target) to test thesis, observe the tape, then commit big with *Main Add* (brings position to 70% of target), then optional *Final Top-Up* (to 100%). This inverts the classic O'Neil ladder (front-loaded) — the main commitment happens AFTER thesis confirmation, not at initial entry. Especially suited for high-beta / bottom-fishing names where probing protects against being wrong on a full-size initial.
    - **Signal integration** (no daily-run ordering dependency — all signals re-derived inline):
      - `bubble-scanner.detect_entries` for continuation triggers (Entry A Tight-Flag, E NR7, F SMA50 Reclaim)
      - `bubble-scanner.compute_regime` for vol/breadth gate
      - `bubble-scanner.qualify_bubble` for parent ETF bubble state
      - `bubble-scanner.detect_exits` for TRIM warnings
      - `trade-setup.assess_pullback_quality` for pullback health (Module 8)
      - Inlined: sector breadth (% of parent ETF holdings > MAs), sector momentum (1W vs 4W RS), RRG quadrant (Leading/Improving/Weakening/Lagging), earnings proximity (Yahoo quoteSummary).
    - **Add Quality Score (0-100)** composite of 8 components: Regime 20% / Parent state 15% / RRG 15% / Breadth 15% / Pullback 15% / Sector momentum 10% / Earnings 5% / Position context 5%. Normalized as `30 + signed_components` clamped to [0, 100].
    - **Two-phase add structure** (replaces old 3-tier gain-based ladder):
      - **Main Add** — eligible when position is 5-30% of target (stab done). Brings position to 70% of target. Triggers: any of Entry A / E / F. Quality bar ≥ 50. Stop after add: `entry_price` (breakeven on stab).
      - **Final Top-Up** — eligible at 30-90% of target. Brings to 100%. Triggers: Entry A or E only. Quality bar ≥ 60. Stop after add: last add's price (lock in main-add gains).
    - **Hard rule: red-day → next-day 15-min ORB execution.** Tool runs after today's close. If today was a red day (open > close), the recommendation becomes a *next-day plan*: tomorrow, watch the first 15-min bar (9:30-9:45 ET). At 10:00 ET, the user adds **only if** the second 15-min bar (9:45-10:00) closes above OR_HIGH × 1.001 (0.1% buffer to filter noise pokes), AND the pre-market gap vs today's close is ≤ +2%. The buy goes in at ~10:00 ET. This shifts confirmation from inferred-from-daily-bar to real-time intraday, eliminates falling-knife adds, and disciplines execution timing.
    - **STRONG ADD** (quality ≥ 70) → full computed size. **ADD** (50 ≤ quality < 70) → linearly scaled size: `scale = clamp((quality - bar)/20 + 0.5, 0.4, 1.0)`. No cliff at the bar.
    - **Vol-adjusted sizing**: main add size × `min(1.0, 0.50/annualized_vol_60d)`. An 80%-vol name gets 0.625× nominal size.
    - **Timeout rule**: if no add fires for 30 sessions since last action AND position still in profit, raise quality bar +10 and flag TIMEOUT. Prevents permanent stall on names that never give the textbook setup.
    - **Hard blockers**: Red/Orange exit ladder → TRIM; earnings within 5d → BLOCKED; vol regime ELEVATED/EXTREME → BLOCKED; Final phase + any Flashing Yellow → BLOCKED (de-risking phase).
    - Never auto-adds — `--confirm-add TICKER` is the explicit write step that appends the add record and tightens the stop.
    - **Post-hoc validation**: `python pyramid-scanner.py --validate-orb TICKER [DATE]` pulls 15-min Yahoo data, reports whether the ORB rule fired, the actual 10:00 entry price, the pre-market gap, and what happened by EOD. Useful for confirming what the user *would* have done and for backtesting the rule.
    - CLI: `python pyramid-scanner.py` (scan all), `--init TICKER STAB_SHARES TARGET_SHARES PRICE DATE PARENT_ETF` (add new position), `--confirm-add TICKER` (record latest add), `--validate-orb TICKER [DATE]` (post-hoc ORB check).
    - **NOT added to `run-all.py`** — position-state-dependent tool; runs on-demand.

    **Worst-case stress test (per the new CLAUDE.md convention)** — failure modes considered before coding:
    1. **No red day in optimal window** — parabolic stock never gives a red day. *Mitigation*: 30-session timeout raises bar +10 and allows add.
    2. **Red day on a real downtrend** — every day red during breakdown. *Mitigation*: exit-ladder check runs first; Red/Orange tier → TRIM regardless of red-day rule. Bounce check (close > low + 0.5×ATR) filters falling-knife days.
    3. **Gain-% tier discriminator unreliable with small stab** — *Mitigation*: replaced gain-based bands with `shares_done/target_shares` ratio. Stab/main/final phases are accumulation-based, not price-based.
    4. **High-vol name + 70% target add = blowup risk** — *Mitigation*: vol-adjusted sizing factor `min(1.0, 0.50/asset_vol)` shrinks main add proportionally on volatile names.
    5. **Intraday run uses incomplete "today" bar** — *Mitigation*: tool refuses to evaluate red-day rule if running during market hours (before 16:00 ET on today's session); user is told to re-run after close. Eliminates the ambiguous "is iloc[-1] today or yesterday?" problem entirely.
    8. **ORB rule has a known ~50% false-breakout rate on raw OR breakouts** — *Mitigation*: require the *second* 15-min bar (closing 10:00 ET) to close above OR_HIGH × 1.001, not just the first bar to push through. Cuts most pokes.
    9. **Gap-up open invalidates ORB signal** — stock that gaps +5% pre-market is already extended; the ORB just confirms what already happened. *Mitigation*: explicit pre-market gap check ≤ +2% as a precondition. Validation tool also flags it.
    6. **Post-earnings gap, no clean red day** — *Mitigation*: existing 5-day forward earnings block applies. Future enhancement: also block when earnings within last 5d AND post-earnings gain > 5% (still digesting).
    7. **Score right at the bar produces full size (cliff)** — *Mitigation*: linear scaling `scale = clamp((quality - bar)/20 + 0.5, 0.4, 1.0)`. At bar → 0.5× size; at bar+20 → 1.0×. Eliminates cliff behavior.

26. **Entry Analyzer (`entry-analyzer.py`)** — Multi-timeframe entry candidate scoring
    - For pre-entry decisions on tickers you do NOT yet own (distinct from pyramid-scanner which is for adding to existing positions). Run on demand, not in `run-all.py`.
    - **Inputs** (priority order): CLI args, `entry-candidates.json` `{"tickers": [...]}`, interactive prompt.
    - **Data per ticker**: daily 2y, weekly (resampled from 5y daily), monthly (direct Yahoo `interval=1mo` 10y; falls back to monthly-resample if < 13 bars).
    - **Scoring philosophy** — tiered weights with explicit user-driven priorities:
      - **PRIMARY (heaviest weight) — entry quality**:
        - Pullback: HEALTHY +20 / ACCEPTABLE +10 / QUESTIONABLE -10 / UNHEALTHY -20
        - RSI band: 40-60 +10, >75 -25, >70 -15, oversold +5
        - Entry classification: PULLBACK_ENTRY +25, BREAKOUT_WATCH +10, IN_NO_MANS_LAND -10, EXTENDED -25, BROKEN_DOWN -30
        - Chasing penalty: EXTENDED + at-highs + RSI > 65 → -35; EXTENDED + at-highs alone → -20
        - R/R: ≥3:1 +20, ≥2:1 +10, ≥1.5:1 -5, <1.5 -15
      - **SECONDARY — Fibonacci & AVWAP**:
        - **Fibonacci computed from a VALIDATE-AND-RETRY swing search** (UPGRADED) — walks candidate pivot pairs backward and selects the first swing whose Fib levels are confirmed by sub-pivot reversals within the swing's price-action window. Decision rules:
          - sub-pivot match rate ≥ 0.60 → accept immediately (high confidence; even parabolic moves with few sub-pivots pass)
          - match rate 0.50–0.59 AND at least one Fib line has ≥2 reversal touches → borderline; compare up to 2 such candidates, pick higher match rate
          - match rate < 0.50 → reject, keep walking back (up to 5 total candidates per TF)
          - Adaptive threshold for "near a Fib level": `max(1% × swing_high, 0.5×ATR)` so volatile names aren't penalized
          - Falls back to weekly (≥15%) then monthly (≥25%) if all daily candidates fail
        - **Important vs unverified levels**: `important_levels` = Fib lines with ≥2 reversal touches (these earn `★` markers in the chart/report and full type-weight in the first-phase clustering scorer). Other levels are still drawn but tagged `FibX (unverified)` and weighted at half-type-weight (1 pt instead of 2 pt in cluster scoring).
        - **Flag `FIB-UNVALIDATED`** surfaces in the summary table when no Fib level achieved ≥2 reversal touches — the swing is being used but no S/R was empirically confirmed.
        - Breakout above key Fib levels (23.6/38.2/50/61.8/100% of swing) on volume: +8 per level, +3 volume bonus, cap +18. Breakdown below: -8 per level, cap -15. Holding above key level (within 2%) +6; below as resistance -4.
        - AVWAP: within 1×ATR of supportive AVWAP +10; further but supportive +5; no supportive AVWAP -10.
      - **CONFLUENCE-ONLY — Moving averages**:
        - Standalone MAs (EMA21, SMA50, SMA200, 30wk) score **ZERO** by design.
        - MA scores +3 only when within 2% of a Fibonacci key level OR the best AVWAP. Capped at +10 total.
        - Captures real institutional levels (price clustering at fib + MA + AVWAP simultaneously) while refusing to reward "above the 50-day" in isolation.
      - **Standalone — Volume**: rel today vs 20d avg, up/down 20d ratio, CMF-20; ±4 each, capped at +12/-10. LOW LIQUIDITY (avg20 < 100K) → -5.
      - **NOT SCORED**: Daily/Weekly/Monthly trend labels and standalone 30wk SMA position. Shown in report for context but contribute zero — prevents the score from being pumped by "stock has been going up" alone.
    - **Score math** (worst-case #7 mitigation): raw signed sum is **clamped to ±50** *before* anchoring at base 50 → always ∈ [0, 100]. Classification: 80+ PRIME, 60-79 GOOD, 40-59 MIXED, <40 AVOID.
    - **Flags surfaced in summary table** so the four key worst-case mitigations are visible at a glance:
      - `🚨 CONFLICT` — timeframe disagreement
      - `⚠ NO-AVWAP` — all 5 AVWAP anchors above price (broken structure)
      - `⛔ CHASE` — chasing penalty active
      - `📈 CEILING` — raw signed sum ≥ +60 (score saturated; not "perfect", just maxed)
    - **Output**: per-ticker text report (full component breakdown so the user can audit) + 3-panel chart (daily 1y with 30wk SMA + best AVWAP + Fib levels; weekly 3y; monthly 5y) posted to Discord; plus side-by-side summary table with Flags column.
    - **Discord webhook**: dedicated channel `1505424654259458159`.
    - **Reuses**: `bs.fetch_ohlcv/sma/ema/rsi/atr`; `ts.assess_pullback_quality/find_support_resistance/calc_entry_zone/calc_stop_loss/calc_targets/calc_risk_reward/calc_mtf_alignment/get_last_earnings_date`. **Does NOT reuse `ts.calc_fibonacci`** — entry-analyzer uses its own `latest_swing_fib()` based on scipy.argrelextrema, since the trade-setup version uses a fixed 90-day window.

    **Worst-case stress test** — failure modes considered before coding, mitigations implemented:
    1. **Recent IPO < 150 trading days** → no 30wk SMA. *Mitigation*: 30wk-direct component scores 0 (and 30wk can still contribute via MA-confluence path).
    2. **Monthly fetch < 13 bars**. *Mitigation*: fall back to monthly-resample of weekly_raw; otherwise "INSUFFICIENT" (and since trends aren't scored, no impact on score).
    3. **No swing ≥ 10% on daily (chop)**. *Mitigation* (UPGRADED): hedge-fund-standard multi-TF fallback — `best_swing_fib()` tries daily → weekly (≥15%) → monthly (≥25%). Returns the first qualifying swing annotated with `timeframe`. Levels are still plotted on the daily chart; the report and chart legend tag higher-TF fibs with `[W]` or `[M]`. Breakout scoring de-rates by 0.85× (weekly) or 0.70× (monthly). Only when all three TFs fail does the Fibonacci component score 0 with "no swing on any TF".

    **First-Phase Entry Recommendation table** — turns the diagnostic score into an actionable per-ticker recommendation:
    - Builds a level catalogue below price (Fib levels from the multi-TF orchestrator, all 5 AVWAP anchors, EMA21/SMA50/SMA200/30wk MAs, horizontal S/R from `ts.find_support_resistance`).
    - Deduplicates levels at the same price; parses trade-setup's `type` field so Fib/AVWAP/MA labels are normalized. Skips trade-setup's own Fib levels (already in the multi-TF set).
    - Clusters levels within `max(1.5% × price, 0.5×ATR)` of each other; scores clusters by `2 × distinct types + 1 × level count + triple-confluence bonus − too-deep penalty`.
    - Sizing: base stab 10-28% by distinct-type count, adjusted ±3 for RSI (<45 or >70) and ±3 for R/R, capped 12% on LOW-LIQ, capped 20% on BROKEN-DN + GOOD/PRIME composite. Final clamp [10, 30].
    - Two stops: **tight** = `cluster_low − 0.5×ATR` (with SMA200 snap, 1.5% floor, no ceiling cap — `WIDE-STOP` flag instead). **Worst-case** = next deeper cluster score ≥ 4, else Fib 100%, else `entry − 2×ATR`.
    - Actions: BUY-LIMIT (cluster < 5% below) / WAIT (5-15% below) / STRATEGY (extended/ATH or > 15% below — text only, no price) / INSUFFICIENT_STRUCTURE (only 1 level) / AVOID (composite class AVOID).
    - Output: side-by-side table after the existing summary + per-ticker `FIRST-PHASE RECOMMENDATION:` block in the text report.

    **Additional worst-case mitigations for first-phase recommender**:
    10. **No levels below price** (extended bubble at ATH). *Mitigation*: emit STRATEGY action with text "watch for low-vol pullback to EMA21/SMA50 ~$X" — no price target since the level is in the future.
    11. **Single level total** (thin structure). *Mitigation*: emit INSUFFICIENT_STRUCTURE rather than guessing at a 1-level entry.
    12. **Cluster within 1% of current price** (no buffer). *Mitigation*: tight stop = `entry − 1×ATR` instead of `cluster_low − 0.5×ATR`.
    13. **Tight stop falls below SMA200 in uptrend**. *Mitigation*: snap to `SMA200 + 0.25×ATR` to preserve structural line.
    14. **Tight stop risk < 1.5%**. *Mitigation*: floor at `entry × 0.985`.
    15. **Tight stop risk > 6%**. *Mitigation*: surface `WIDE-STOP` flag but show the real stop — user decides.
    16. **No deeper cluster exists for worst-case stop**. *Mitigation*: fall through to Fib 100% retracement, then `entry − 2×ATR` with note "ATR-based, no deeper support".
    17. **BROKEN_DOWN with strong cluster (e.g. GTLB)**. *Mitigation*: stick to composite score; if GOOD/PRIME, recommend the cluster but cap stab at 20% with `BROKEN-DN` flag.


    4. **All 5 AVWAP anchors above price** (deep downtrend). *Mitigation*: best-picker tries below-price + rising first; falls back to closest-below; if still none, AVWAP component = -10 and `NO-AVWAP` flag surfaces.
    5. **Low liquidity** (avg 20d vol < 100K). *Mitigation*: LOW LIQUIDITY warning + skip up/dn + CMF; volume = -5.
    6. **Yahoo rate-limit mid-batch**. *Mitigation*: each ticker fetched independently; DATA_ERROR per ticker; run continues.
    7. **Composite hits ceiling 100 trivially**. *Mitigation*: signed sum clamped to ±50 *before* base 50; `CEILING` flag fires when clamp is active.
    8. **Strong stock + EXTENDED + at-highs scores PRIME**. *Mitigation*: -35 chasing penalty + -25 entry-class + RSI penalty stacks; `CHASE` flag surfaces.
    9. **Timeframe conflict masked**. *Mitigation*: `CONFLICT` flag in summary when any frame UPTREND while another DOWN.

27. **GEX Profile (`gex-profile.py`)** — SPX Gamma Exposure profile (Perfiliev method)
    - **Data**: CBOE delayed-quotes JSON `https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json` (free, EOD-delayed ~15min, no key). Returns full SPX chain with `gamma`, `open_interest`, `iv`, `delta` etc. per contract across ~30k contracts / ~50 expiries.
    - **Formula**: `GEX = gamma × OI × 100 × spot² × 0.01`. Put GEX flipped negative (dealer-positioning convention — calls positive, puts negative on the chart).
    - **Spot**: `data.current_price` from CBOE payload; falls back to Yahoo `^GSPC` close if missing/zero.
    - **Symbol parsing**: regex `^SPX[W]?(\d{2})(\d{2})(\d{2})([CP])(\d{8})$` → expiry / type / strike. Unparseable rows skipped silently.
    - **Filter**: `OI ≥ 10` AND `gamma > 0` (removes deep ITM/OTM noise where gamma=0).
    - **Two panels**:
      - **Left** = nearest expiry `>= today` (typically 0DTE on M/W/F when SPX has weeklies, else next session).
      - **Right** = next monthly OpEx: expiry within `today + [10, 45]` days with the **highest total OI** (this picks the real OpEx rather than thin LEAPS or front-week weeklies). Falls back to first expiry past day 10 if the window is empty.
      - Hard-coded de-dup: if `nearest == opex`, push opex to next available expiry.
    - **Strike clipping**: keep strikes with `|GEX| ≥ 1% × max|GEX|` ∪ spot ± 5% band. Keeps the chart readable without cutting the spot region.
    - **Chart**: 2-panel matplotlib, dark theme (`#1a1a2e`), green call bars (`#a8e6a8`), pink put bars (`#e6a8d3`), cyan spot line (`#00d9ff`). Y-axis auto-formats to B/M.
    - **Text report**: net GEX per panel + top 3 call walls (resistance) + top 3 put walls (support) for each, formatted as monospace block.
    - **MenthorQ-style named-levels block** (third Discord post): standardized industry taxonomy.
      - **Full chain**: `Call Resistance` (max +call_gex strike), `Put Support` (max |put_gex| strike), `HVL` (full-chain Zero-Gamma Level).
      - **0DTE only**: `Call Resistance 0DTE / Gamma Wall 0DTE`, `Put Support 0DTE`, `HVL 0DTE` — same metrics restricted to today's expiry.
      - **GEX 1-5**: top 5 strikes by |net GEX| across full chain, ranked. Each tagged CALL+ or PUT- depending on net sign.
      - **Regime block**: `spot − HVL` for both full chain and 0DTE, labeled LONG GAMMA (pin/dampen) when ≥ 0, SHORT GAMMA (vol expansion) when < 0. Surfaces 0DTE-vs-longer-dated regime divergence (common case where today's expiry is pinning while structural positioning is short-gamma).
      - Excludes `1D Max / 1D Min` (those are IV-derived expected-move boundaries, not GEX — out of scope for this script).
    - **HVL annotation on 0DTE + OpEx panels**: yellow dashed vertical line at the per-expiry Zero-Gamma Level (computed on the unclipped chain so the line is exact even when strike-clip drops thin strikes from the bars).
    - **Evolution chart (second image)**: tracks max call wall (green), max put wall (pink), and **Zero-Gamma Level / ZGL** (yellow) across **today + next 10 expiries** (11 total). Bubble size encodes magnitude per point, normalized to the global max across all three series. Per-point strike labels and a horizontal cyan dashed spot line. Falls back gracefully if < 11 expiries available; skips entirely if < 2.
    - **Zero-Gamma Level (ZGL) — the institutional canonical "net" line**: per expiry, walk strikes low → high accumulating net GEX (`call_gex + put_gex_signed`). ZGL = strike where cumulative crosses zero (linearly interpolated). Below ZGL dealers are net short gamma (vol-expansion regime); above ZGL net long (pinning / mean-reversion). This is the headline number that SqueezeMetrics / SpotGamma / MenthorQ publish daily and the metric Perfiliev's original post is built around. Bubble magnitude = peak |cumulative| across the strike grid (proxy for total dealer gamma intensity).
    - **Why not `max |net|`?** Initial implementation picked the strike with largest absolute net GEX. In a bull regime call OI dominates everywhere, so `net ≈ +call_gex` and `|net|.idxmax` collapses onto the call wall — yellow line tracks green and adds zero information. ZGL is structurally distinct from both walls and is the actually-actionable line. (Tried `intersection-only` and `max +net` as intermediate fixes; both still degenerate to the call wall in call-dominated tape.)
    - **Discord webhook**: `1507392186222776422/HaApw51ljzILxhNqne8P5u_u5YwbSA5aF3qjQ1ieTtZatbx1MrooeLVzfOKg3OWtyNRr`.
    - Added to `run-all.py` as script #10 (after `bubble-scanner.py`, before `fx-models.py`). No yf cooldown.

    **Worst-case stress test**:
    1. **CBOE blocks the request** — User-Agent set; 30s timeout. Fetch fail posts a single error line to Discord instead of crashing.
    2. **Gamma/OI null on illiquid strikes** — Filtered (`OI < 10` or `gamma <= 0` skipped) before aggregation.
    3. **Symbol parses to a new contract format** — Regex match; unmatched rows skipped without raising.
    4. **No expiry `>= today`** (holiday / stale fetch) — `pick_expiries` returns `(None, None)` → script posts a single-line failure and exits cleanly.
    5. **Spot missing from CBOE payload** — Falls back to Yahoo `^GSPC`; raises only if both fail.
    6. **OpEx picker selects a heavy LEAPS expiry** — Restricted to `today + [10, 45]` day window with max OI; LEAPS outside the window are ignored.
    7. **Strike range too wide → unreadable chart** — Clipped to `|GEX| ≥ 1% × max|GEX|` ∪ spot ± 5% band.
    8. **Discord 2000-char limit** — `send_discord_text` chunks at line boundaries before posting.

28. **GEX Profile — Equity Edition (`gex-profile-equity.py`)** — Per-ticker fork of `gex-profile.py` for any optionable US equity/ETF.
    - **Data**: same CBOE delayed-quotes endpoint, no underscore prefix for stocks: `https://cdn.cboe.com/api/global/delayed_quotes/options/{TICKER}.json`. Free, ~15-min delayed, no key. Works for SPY/QQQ (1000s of contracts) down to thin names like EXLS/G (~20-90 contracts).
    - **CLI**: `python gex-profile-equity.py AAPL TSLA EXLS G` — one or more tickers. `$` prefix stripped automatically. `--min-oi N` overrides the OI floor.
    - **Generalized symbol regex**: `^{ticker}[W]?(\d{2})(\d{2})(\d{2})([CP])(\d{8})$` built per ticker (escapes ticker for regex safety).
    - **Spot fallback**: Yahoo chart API for `{ticker}` (not `^GSPC`) when CBOE payload lacks `current_price`.
    - **Thin-chain auto-relax**: if `--min-oi 10` leaves < 15 contracts, auto-retry with `min_oi=1`. Lets thin names produce *some* profile rather than nothing.
    - **Wider spot band**: clip keeps `|GEX| ≥ 1% × max` ∪ spot ± **20%** (vs SPX ±5%) — equity chains are sparser, narrow bands cut everything.
    - **Strike formatting**: dynamic `.0f` for strikes ≥ $100, `.2f` for < $100, so $17.50 stays readable alongside $185.
    - **0DTE block conditional**: only labeled "0DTE" when nearest expiry == today (rare for equities — most only have weekly Fridays). Otherwise labeled "NEAREST EXPIRY ONLY" to keep the panel meaningful.
    - **OpEx panel skipped** when only one future expiry exists; renders single-panel chart instead of empty right panel.
    - **Evolution chart skipped** when < 2 future expiries (would be a single dot).
    - **Per-ticker loop in `main()`**: each ticker is independent — one failure doesn't halt the batch; errors caught, traceback to stderr, single error line posted to Discord, continue.
    - **Discord webhook**: dedicated channel `1508366696212205660/WvjfoSkPzWNbIhNjL0R5eHFatKPzbCUDOTDqAslSgnPIa0N8-0sGLLaLoFMiSIBxsnjt` (separate from SPX gex channel so per-ticker streams don't drown out index profile).
    - **NOT added to `run-all.py`** — on-demand per-ticker tool; invoked via `run-ticker.py` or directly.

    **Worst-case stress test**:
    1. **Ticker not optionable** (e.g. micro-cap, recently IPO'd) — CBOE returns empty `options[]`; script posts "no parseable contracts for {T}" and continues.
    2. **Symbol prefix collision** (e.g. ticker `SPX` matching SPX index format) — regex anchors on `^{ticker}` exactly via `re.escape`, no collision.
    3. **All contracts below OI=10** — thin-chain fallback re-parses at OI=1; if still empty, posts "no parseable contracts" and continues.
    4. **Only one future expiry** — OpEx panel skipped, single-panel chart rendered with same legend.
    5. **CBOE spot missing/zero** — Yahoo `{ticker}` fallback. If both fail, raises clean exception caught by per-ticker error handler.
    6. **Strike < $1** (e.g. penny biotechs) — `.2f` formatter still renders; bar width logic uses `max(..., 0.5)` floor so bars don't vanish.
    7. **Discord webhook rate-limit on multi-ticker batch** — per-ticker posts go through `send_discord_text/image` which has 30s/60s timeouts; failures logged to stderr, batch continues.

29. **Share Buyback section in `fundamental-thesis.py`** — Capital-return analysis (Damodaran total-shareholder-yield framework).
    - **New extractor `extract_buybacks(qs, m)`** pulls quarterly + annual cashflow data; computes:
      - **Buybacks TTM** = sum of last 4Q `repurchaseOfStock` (sign-flipped to positive $ spent). Falls back to `commonStockRepurchased` if primary field is missing/null.
      - **Issuance TTM** = sum of last 4Q `issuanceOfStock` (positive cash inflow).
      - **Net buyback TTM** = buybacks − issuance (catches net-issuers masquerading as buyback companies).
      - **SBC-adjusted buyback** = buybacks − SBC TTM (the *real* per-share accretion; if SBC > buybacks, this goes negative).
      - **Buyback yield %** = buyback / market cap × 100.
      - **Net buyback yield %** = net_buyback / market cap × 100 (can be negative for net dilution).
      - **SBC-adj yield %** = SBC-adjusted / market cap (negative when SBC outpaces repo).
      - **Total shareholder yield %** = buyback yield + div yield (Damodaran).
      - **Consistency** = count of last 4 quarters that had any buyback.
      - **Annual YoY trend** = (annual_repo[0] / annual_repo[1] − 1) × 100, when 2+ annual statements available.
    - **Rendered as new "── CAPITAL RETURN — BUYBACKS & DIVIDENDS ──" section** in `render_report`, placed between BALANCE SHEET and the sector pack. Shows TTM dollars + 3 yield variants + consistency + annual history.
    - **Bull/bear thesis signals added in `build_thesis`**:
      - **Bull**: net buyback yield ≥ 5% ("aggressive shareholder return"); total shareholder yield ≥ 8% ("high cash return").
      - **Bear**: net buyback yield ≤ −3% ("net dilution"); SBC-adj yield < −2% when gross buybacks are non-zero ("buybacks fail to offset SBC dilution" — the Druckenmiller/Scion concern).
    - **Wiring**: `extract_buybacks` called in `process_ticker` after `extract_quarterly`; passed to `build_thesis` and `render_report` as keyword arg `buybacks=` so callers without the data don't break.

    **Worst-case stress test**:
    1. **Yahoo returns no cashflow** — extractor returns dict with `None`/`0` values; render shows "No cashflow data available" or "n/a" for individual yields. No crash.
    2. **`repurchaseOfStock` missing, `commonStockRepurchased` present** — extractor checks the alternate field name when the primary returns all-None.
    3. **Net issuer (issuance > repo TTM)** — net buyback yield goes negative; bear flag fires at ≤ −3%; rendered with `+`/`−` sign so direction is clear.
    4. **Missing/zero market cap** (rare; new IPOs without market cap reported) — yield calcs return `None`; rendered as "n/a" rather than ZeroDivisionError.
    5. **< 4 quarters of cashflow data** — `cf_q[:4]` slice handles short lists; consistency reports `0-3/4` honestly.
    6. **No annual cashflow available** — `annual_yoy_pct` is `None`; annual history line is suppressed.
    7. **SBC TTM > Buybacks TTM** — `sbc_adj_buyback_ttm` goes negative; surfaces as a bear flag rather than being silently positive; the "(SBC TTM: ... — subtract from gross buybacks)" note in the report makes the drag explicit.

30. **Ticker Analysis Runner (`run-ticker.py`)** — One-shot runner for all per-ticker tools.
    - **Purpose**: run the five ticker-specific tools on the same list of tickers in one command. Mirrors `run-all.py` but for ticker-scoped (vs market-scoped) analysis.
    - **Scripts invoked sequentially**:
      1. `fundamental-thesis.py` — per-ticker thesis with sector pack, bull/bear, buybacks
      2. `fundamentals-scanner.py` — quality + valuation overlay (cohort scoring)
      3. `entry-analyzer.py` — multi-timeframe entry scoring (PRIME/GOOD/MIXED/AVOID + first-phase plan)
      4. `gex-profile-equity.py` — per-ticker GEX profile (CBOE delayed options chain)
      5. `volume-exhaustion-scanner.py` — Capitulation/Blowoff/Waning regime classifier + OI %-change layer
    - **CLI**: `python run-ticker.py EXLS G` or `python run-ticker.py $AAPL $TSLA` — `$` prefix stripped, uppercased, dedup-on-the-fly.
    - **Each subprocess gets `PYTHONIOENCODING=utf-8` injected** to prevent Windows cp1252 crashes on unicode arrows/checkmarks in tool output (we hit this earlier with fundamentals-scanner's `→`).
    - **Per-script timeout 300s**, captured output (last 8 lines on success, last 8 lines of stderr on failure printed for diagnostics).
    - **Per-script independence**: one failure doesn't halt the run; runner reports `OK`/`FAIL`/`TIMEOUT`/`SKIP` per script and a final tally.
    - **Output**: posts to each tool's existing Discord webhook (4 separate channels). Local stdout shows progress + tail of each tool's output.
    - **NOT added to `run-all.py`** — ticker-scoped on-demand tool; runs when you want to drill into specific names.

    **Worst-case stress test**:
    1. **Ticker not optionable** (e.g. illiquid micro-cap) — `gex-profile-equity` fails or skips; other 3 tools succeed. Runner reports `FAIL GEX Profile` but exits non-zero only on the GEX line, batch continues.
    2. **cp1252 encoding crash on unicode output** — `PYTHONIOENCODING=utf-8` in subprocess env; `subprocess.run(..., encoding="utf-8", errors="replace")` on capture too.
    3. **One script hangs** (e.g. SEC EDGAR rate-limit) — 300s timeout kills it; reported as `TIMEOUT`; next script still runs.
    4. **`$AAPL` style input** — `lstrip("$").upper().strip()` normalization before forwarding.
    5. **Network flake mid-batch** — captured `result.stderr`, last 8 lines surfaced; runner continues.
    6. **Script missing from tools/** — `script_path.exists()` check; logs `SKIP` and moves on (lets the runner survive partial installs).
    7. **No tickers passed** — prints usage and `sys.exit(1)` immediately; doesn't run any subprocesses.

31. **Volume Exhaustion Scanner (`volume-exhaustion-scanner.py`)** — Capitulation / Blowoff / Waning regime classifier with Wyckoff SC→AR→ST sequence + Spring detector + multi-SC tracking + Open Interest %-change layer. Classical volume analysis (Wyckoff, VSA, O'Neil, Granville, Lo & Wang turnover) operationalized as a three-regime tape-reader.
    - **Universe modes**:
      - No CLI args → daily scan: `watchlist.json ∪ discovery-output.json` (drops ETFs, caps at 100)
      - CLI args (with or without `$` prefix) → scan only those tickers (used by `run-ticker.py`)
    - **Module 1 — Regime classifier** (per ticker): `DOWNTREND` (drawdown ≥20% from 1y high AND < SMA200), `EXTENDED_UPTREND` (close > 1.30× SMA200 OR > SMA200 + 2σ OR +50% in 60d), `STEADY_UPTREND` (above SMA200, SMA50 > SMA200, not extended), `CHOP` else. Each regime gates which signals are eligible.
    - **Module 2 — Volume swell detection**: spike if vol ≥ 1.5× **180-day median** baseline (median is robust to crash-period contamination that breaks rolling means) OR ≥ 90th-pct of trailing 60d. Wide-range bar if range ≥ 1.5× ATR(14). Reversal candle: hammer / engulfing / "close in upper half" (bullish) or shooting-star / engulfing / parabolic-close / "close in lower half" (bearish) — looser than textbook hammer/engulfing to catch real index climactic bars like SPY Oct 10 2008 and Mar 23 2020 (which had large bodies, not the strict 2:1 lower-shadow-to-body ratio).
    - **Module 3 — Turnover (Lo & Wang)**: volume / `sharesOutstanding`, percentile-ranked over 60d, 10-day regression slope. `sharesOutstanding` cached 7 days in `shares-outstanding-cache.json` (float doesn't move daily).
    - **Module 4 — Waning rally** (Granville / VSA "no demand on rally"): c1 price up ≥5% in 30d, c2 vol slope < 0, c3 up/dn ratio deteriorating last-10 vs prior-10, c4 CMF-20 slope < 0. Tiered: c1+c2 (core 2/4) → WATCH; c1+c2 + (c3 OR c4) → WARNING. Fires in STEADY_UPTREND or EXTENDED_UPTREND (pre-blowoff distribution often happens during parabolic phases too).
    - **Module 5 — Wyckoff SC → AR → ST sequence**: scans the trailing **180 sessions** for ALL SC candidates (was 30; widened so late-bear bottoms can reference the original SC months earlier), evaluates each independently, picks the best-staged one. AR window is market-cap aware: **5 sessions for non-mega-cap** (cap < $500B), **10 sessions for mega-cap** (cap ≥ $500B). ST window is **universal 30 sessions for all caps**. Confidence tiers:
      - `CAPITULATION_BOTTOM_CONFIRMED` — SC + AR + ST present
      - `CAPITULATION_BOTTOM_FORMING` — SC + AR present
      - `CAPITULATION_WATCH` — SC only
      - `CAPITULATION_FAILED` — close < SC_low after AR (failed structure)
      - **Spring detector** (`detect_spring`) — break of 60-session support → reversal back above with ≥5% bounce. When any SC has FAILED but a Spring is currently forming below the failed-SC low, upgrades the signal to `CAPITULATION_BOTTOM_FORMING` with `pattern: SPRING_AFTER_FAILED`. This is the key Stage 2 addition that catches Mar-2009-style bottoms where the original SC happened in Oct 2008 but the actual low formed 5 months later on lighter volume.
    - **Module 6 — Open Interest %-change layer (the user's explicit ask)**: per-ticker CBOE delayed JSON (`https://cdn.cboe.com/api/global/delayed_quotes/options/{TICKER}.json`, same source as `gex-profile-equity.py`). Aggregates total call OI, put OI, put/call OI ratio, top-5 strikes per side. Persists daily snapshots to `oi-history.json` (60d rolling, deduped by date for re-run idempotency). Metrics computed from history: 1d/5d/20d % change in total OI, side-split (call vs put) 5d % change, P/C ratio delta vs 20d avg, derived flags (INCREASING / DECREASING / FLAT at ±10%, `call_oi_surge` and `put_oi_surge` at +25% 5d). **Annotation only — never auto-upgrades signal confidence for any ticker (mega-cap or not).** Shows as a second-line tag in each signal row: `OI: increasing (+12% 5d, 7 snap)  PUT_SURGE +X% 5d (panic hedging)` etc. Graceful: `NO_OPTIONS_DATA` flag when CBOE returns no chain.
    - **Module 7 — Composite signal**: 7 named signals across 3 regimes, plus `NEUTRAL` (suppressed from output). 4 stress-test flags (`MEGA_CAP`, `MECHANICAL_FLOW`, `SPLIT_SUSPECT`, `BROAD_FLOW`, `NO_OPTIONS_DATA`) annotate but don't promote/demote tier.
    - **Output**: Discord post with 3 sections (CAPITULATION / BLOWOFF / WANING), per-ticker dark-theme chart with Wyckoff annotations (SC star, AR diamond, ST square, Spring plus-marker, FAILED X-mark, SC_low horizontal line). Top 5 charts per category.
    - **Backtest harness** (`volume-exhaustion-backtest.py`): runs the full pipeline "as of" historical dates by truncating Yahoo's full-history pull (using `period1=0&period2=now` for true max history). 19 test cases across GFC, COVID, dot-com, 1974 oil-shock (IBM since ^GSPC volume only goes back to 1985), 9/11 panic, WMT 2015 drawdown, dot-com peaks. Validated at **17/19 = 89% pass rate**.
    - **Stage 1 → Stage 2 calibration journey**:
      - Stage 1 used textbook strict thresholds (vol ≥ 2.5× 20d avg, range ≥ 2× ATR, strict hammer/engulfing geometry, 30d SC lookback). Resulted in 4/19 pass — most failures were "real climactic bars didn't fit textbook patterns" (SPY Oct 10 2008 was a +5.9% green bar but body was large, not a hammer; SPY Mar 23 2020 had vol 1.87× 20d avg because crash days had already inflated the baseline).
      - Stage 2 fixes: 1.5× threshold on a 180d-median baseline (robust to inflation), 1.5× ATR for wide range, looser reversal (upper-half-close OR hammer OR engulfing for bullish; symmetric for bearish), widened SC lookback 30→180, multi-SC tracking with best-stage-wins selection, Spring fallback pattern, market-cap-aware AR window. Result: 17/19 pass.
    - **Discord webhook**: `1508730602189488209/1OKp8ofZ3oN_8xUOfqgqNlIf7Nd26pdrB0_T8Y7HHRsmpM3E7ePApunw20JK6YD4h7IF`.
    - **Added to `run-all.py` as script #10** (after `bubble-scanner.py`, before `gex-profile.py`). No yf cooldown.
    - **Added to `run-ticker.py` as 5th tool** alongside `gex-profile-equity.py` (both CBOE-based per-ticker tools).

    **Worst-case stress test** (8 scenarios considered before coding, mitigations implemented):
    1. **Low-VIX bull tape may generate spurious WANING signals.** User decision: **do NOT include a VIX suppression gate in v1.** Observe forward returns first; the four-condition AND (and the new 2/4 c1+c2 mandatory tier for WATCH) is already restrictive. Revisit if forward-return analysis shows noise.
    2. **Single SC candle marked as bottom prematurely; price keeps dropping** (the classic "failed first SC" problem). *Mitigation*: tiered confidence with market-cap-aware AR window (5d non-mega / 10d mega) but **universal 30-session ST window for all caps**. Single SC = WATCH only; needs AR within window for FORMING; needs ST within 30 for CONFIRMED; close < SC_low → FAILED.
    3. **Mega-cap options OI dominated by institutional hedging — OI surge reflects macro hedge funds rolling protection, not retail FOMO.** *Mitigation*: per user, **OI never auto-upgrades signal confidence for ANY ticker**. The `oi_pct_change_*` metrics display as informational context but tier promotion comes only from price/volume structure. Mega-caps get a `MEGA_CAP` tag so user can interpret OI context accordingly.
    4. **Small-cap or recently-listed name with no options chain.** *Mitigation*: graceful `NO_OPTIONS_DATA` flag. Signal still emits on equity-volume + turnover alone.
    5. **Stock split mid-window inflates/deflates volume series.** *Mitigation*: Yahoo chart API returns split-adjusted volume by default. Day-over-day vol ratio ≥ 5× without commensurate range expansion → `SPLIT_SUSPECT` flag, skip classification.
    6. **Index reconstitution day creates mechanical volume surge.** *Mitigation*: hardcoded Russell/S&P quarterly rebal dates; spike day within ±2 sessions → `MECHANICAL_FLOW` flag, suppress signal.
    7. **Wyckoff Failed ST: SC + AR completes, then price breaks SC_low.** *Mitigation*: explicit `CAPITULATION_FAILED` state; once price closes below SC_low after AR, signal flips from "potential bottom" to "trend continuation confirmed, avoid".
    8. **Idiosyncratic vs broad-market move not distinguished.** *Mitigation*: `idiosyncratic_score = ticker_vol_zscore - SPY_vol_zscore` on the candidate SC day; require ≥ 1.0 for SC to count. Broad de-risking days get `BROAD_FLOW` tag and don't trigger capitulation signals.

    **Known limitations (2 pattern gaps from backtest)**:
    - **Parabolic blowoff with rising volume** (e.g. ^IXIC Feb-Mar 2000) — the scanner detects waning (vol declining) but parabolic tops show vol *rising* into the peak (FOMO buying). Distinct pattern that needs a separate detector (extended uptrend + 30d gain very high + rising vol + distribution candles). Out of scope for v2.
    - **Downside thrust in established downtrend** (e.g. ^IXIC Apr 14 2000, -9.67% panic continuation) — wide-range bearish bar in DOWNTREND with huge vol but no reversal candle. Real pattern (trend acceleration) but doesn't fit the three-regime taxonomy. Would need a `DOWNSIDE_THRUST` warning tier.

## CI/CD — GitHub Actions
Automated daily run via GitHub Actions. Workflow file: `.github/workflows/finance-tools.yml`

- **Schedule**: Every weekday at 4:30 PM ET (auto DST via dual-cron + timezone guard)
- **What runs**: `python run-all.py` (all 13 scripts sequentially, skips missing ones)
- **Runner**: `ubuntu-latest` with Python 3.11
- **Dependencies**: `finance/ai-hedgefund/tools/requirements-ci.txt` (minimal — no streamlit/langchain)
- **Timeout**: 60 minutes total
- **Manual trigger**: GitHub Actions tab → "Finance Tools Daily Run" → "Run workflow"
- **Free tier**: ~330 min/month usage vs 2000 min/month limit

## Known Issues
- FRED series DGORDER and MANEMP sometimes timeout.
- yfinance rate limiting is aggressive — always prefer Yahoo chart API for new scripts.
- `sortino-optimizer.py` requires `scipy` (added to requirements-ci.txt).

## Environment
- **OS**: Windows 11 Home
- **Python**: venv at `d:\Deepseek-ollama\venv\`
- **Platform**: win32 — use forward slashes or `Path()` for paths, never hardcode Linux paths
- **Timezone**: All time displays use `America/New_York` (ET)

## Conventions
- **Worst-case stress test for every new approach** — when proposing or implementing a new technique (entry logic, scoring, position sizing, etc.), produce a report of 5-7 worst-case scenarios where the technique fails or produces wrong output. For each: (a) the failure mode, (b) when it happens / sample, (c) the mitigation applied (or accepted limit). Apply this *before* coding so the implementation already accounts for the edge cases. Goes in the corresponding "What Was Built" section so future readers know the failure modes.
- All scripts are standalone — run with `python script.py` from the tools directory
- Each script has its own `DISCORD_WEBHOOK_URL` constant and `send_discord()` function
- Use `Path(__file__).resolve().parent` for `TOOLS_DIR`
- Discord messages use monospace formatting with backticks for data tables
- Error handling: print to stderr, continue execution where possible
- No interactive input — all scripts run headless

---

## Swing Trading Workflow — Systematic Process

This suite supports a **top-down sector rotation swing trading** strategy. The workflow has 4 stages, each mapped to specific tools.

### Stage 1: Identify Hot Sectors
**Goal**: Which of the 11 S&P 500 sectors have the strongest momentum and money flow?

| Tool | What It Tells You |
|------|------------------|
| `sector-rotation.py` | 1W/4W returns, relative strength vs SPY + RSP (equal-weight), momentum phase (ACCELERATING/DECELERATING), rotation score (RISK-ON/OFF), SPY-RSP divergence alerts |
| `rrg-scanner.py` | RRG quadrant (Leading/Weakening/Lagging/Improving) with trailing tails showing trajectory, daily + weekly. Separate charts for CW sectors (vs SPY), EW sectors (vs RSP), and subsectors (vs SPY) |
| `sortino-optimizer.py` | Risk-adjusted optimal weights for CW sectors, EW sectors, subsectors, and watchlist (1W/4W/3M Sortino ratios) |
| `volatility-regime.py` | VIX regime context — are we in a low-vol complacent environment (trend-following works) or elevated/extreme (mean-reversion, defensive)? |
| `breadth-scanner.py` | Breadth health per sector (% above MAs, A/D ratio, EW-CW divergence, thrust/collapse). Confirms if sector strength is broad-based or narrow. |

**Decision**: Select 2-3 sectors in the Leading or Improving RRG quadrant with ACCELERATING momentum, positive relative strength, and STRONG/HEALTHY breadth.

### Stage 2: Drill Into Subsectors
**Goal**: Within the hot sectors, which subsectors/themes are leading?

| Tool | What It Tells You |
|------|------------------|
| `sector-rotation.py` | 26 subsector ETFs — same metrics as sectors, top-5 inflows/outflows |
| `rrg-scanner.py` | Subsector RRG quadrants (daily + weekly) — which subsectors are Leading within the hot sector? |
| `sortino-optimizer.py` | Subsector optimal weights across 3 timeframes |

**Decision**: Narrow to 1-2 subsectors with the strongest combination of RS, momentum, and risk-adjusted returns.

### Stage 3: Find Individual Stocks
**Goal**: Within the 1-2 selected subsectors, which individual stocks have the best setup?

| Tool | What It Tells You |
|------|------------------|
| `stock-discovery.py` | Cross-validates subsector picks (sector-rot + RRG + Sortino), pulls ETF holdings, ranks all constituents by RS/Momentum/Volume/Technical composite. Top 10 per subsector. |
| `fundamentals-scanner.py` | Business quality check on stock-discovery picks: EV/EBITDA, Fwd P/E, P/B, EV/Sales, EV/Gross Profit, ROIC vs WACC spread, Gross Margin, Op Margin, forward EPS/Revenue growth. Scored 0-100 per cohort; ranks top 5 per ETF by fundamental thesis. |
| `technicals-scanner.py` | Full technicals (MAs, RSI, MACD, BBands, VWAP, volume) on watchlist stocks |
| `earnings-whisper.py` | Earnings drift detection for upcoming reports |
| `early-trend-scanner.py` (planned) | Divergences, Wyckoff springs, candlestick patterns, MA compression |
| `late-trend-scanner.py` (planned) | Distribution/accumulation, trend exhaustion, failed breakouts |

### Stage 4: Macro/Risk Context
**Goal**: Should I be taking risk at all? What's the macro backdrop?

| Tool | What It Tells You |
|------|------------------|
| `macro-calendar.py` | Upcoming economic events that could move markets (FOMC, CPI, NFP, etc.) |
| `econ-release-analysis.py` | Impact analysis when releases drop (HOTTER/COOLER → sector pass-through) |
| `econometrics-report.py` | Correlation matrix, economic predictor, FX models, retail sales, jobs report |
| `econ-predictor.py` | Which FRED indicators are predicting equity returns (1M/3M forward) |
| `fx-models.py` | FX directional signals (carry, momentum, mean reversion) — dollar strength/weakness affects sector rotation |

---

## Gap Analysis — What's Missing

### ~~CRITICAL GAP: Dynamic Stock Discovery (Stage 3)~~ — RESOLVED

Resolved by `stock-discovery.py` (completed). Cross-validates subsector picks across sector-rotation, RRG, and Sortino methods, then scans all ETF constituents with 5-module ranking system.

### SECONDARY GAPS

| Gap | Why It Matters | Priority |
|-----|---------------|----------|
| ~~**Market Breadth**~~ | ~~Resolved by `breadth-scanner.py`. Scans all 11 sectors × 20 constituents with 4 breadth metrics + composite health score.~~ | ~~DONE~~ |
| **Pullback Quality** | Swing entries work best buying healthy pullbacks in uptrending stocks (orderly, declining volume, holds key MA). Need to distinguish from unhealthy pullbacks (high volume breakdown). **Planned for `trade-setup.py` Module 8** — auto-reads `discovery-output.json`. | High |
| **Institutional Accumulation** | Volume alone doesn't tell you if smart money is buying or retail is chasing. CMF, OBV detect institutional footprints. **Planned for `trade-setup.py` Module 8** (accumulation signs sub-metric). | Medium |
| **Multi-Timeframe Alignment** | Weekly uptrend + daily pullback to support is the highest-probability swing entry. **Planned for `trade-setup.py` Module 6** (weekly + daily alignment check). | Medium |
| **Modernize Legacy Tools** | `insider-clusters.py` (insider buying clusters), `estimate-revisions.py` (analyst estimate changes), `options-implied-move.py` (expected earnings moves) are all functional but use legacy clawdbot output — need webhook conversion. | Low |

---

## PLANNED SCANNERS — Implementation Plans

### 1. ~~Dynamic Stock Discovery Scanner (`stock-discovery.py`)~~ — COMPLETED

See "What Was Built" section #17 for details. Implementation uses `etf-holdings.json` (Option B) with cross-validation across sector-rotation, RRG, and Sortino methods.

---

### 2. ~~Market Breadth Scanner (`breadth-scanner.py`)~~ — COMPLETED

See "What Was Built" section #21 for details. Scans all 11 sectors with 4 breadth metrics + composite health score.

### 3. Trade Setup Scanner — Entry, Stop Loss & Targets (`trade-setup.py`)

**Purpose**: For each stock surfaced by stock-discovery.py, compute precise entry zones, stop loss levels, and profit targets with explicit risk/reward ratios. Also evaluates **pullback quality** — distinguishing healthy pullbacks (orderly, declining volume, holds key MA) from unhealthy ones (high volume breakdown). This is the final step before pulling the trigger — turning "this stock looks good" into "buy at $X, stop at $Y, target $Z for 3:1 R/R."

**Input**:
- **Default**: Auto-reads `discovery-output.json` (saved by stock-discovery.py) to get the shortlist of top-ranked stocks per ETF
- **CLI override**: `python trade-setup.py NVDA AMAT CL` — pass tickers directly
- **Fallback**: If no discovery output exists and no CLI args, reads `watchlist.json`

**Data Requirements**:
- OHLCV data: 1 year daily + 2 years weekly (multi-timeframe)
- Yahoo Chart API: `range=1y&interval=1d` and `range=2y&interval=1wk`
- Parallel fetch with ThreadPoolExecutor(max_workers=5)

**Analysis Modules**:

#### Module 1: Support & Resistance Level Detection
- **Horizontal S/R**: Identify price levels where price has reversed 2+ times
  - Use `scipy.signal.argrelextrema` to find swing highs/lows (order=10)
  - Cluster nearby levels within 1.5% tolerance (merge close levels)
  - Score each level by: number of touches, recency, volume at level
- **Moving Average Support**: SMA(20), SMA(50), SMA(200), EMA(21)
  - Which MAs are currently acting as support (price bounced off them recently)?
  - Distance from each MA as % of price
- **VWAP Levels**:
  - Rolling 20-day VWAP
  - Anchored VWAP from: (a) last earnings, (b) last 52-week low, (c) last significant swing low
  - These act as institutional cost-basis levels
- **Round Numbers**: Nearest round numbers ($50, $100, $150, etc.) — psychological S/R
- **Fibonacci Retracement**: From last major swing (high-to-low or low-to-high)
  - Key levels: 38.2%, 50%, 61.8%
  - Only compute if there's a clear 15%+ swing in last 3 months
- **Output**: Ordered list of support levels below price, resistance levels above price, each with type and strength score

#### Module 2: Entry Zone Calculation
- **Pullback Entry (preferred for swing trading)**:
  - Identify the "entry zone" = area between the nearest 2 support levels below current price
  - Ideal zone: price pulling back to EMA(21) or SMA(50) in an uptrend
  - Tighter zone if supports cluster (multiple supports within 2% = strong demand zone)
  - Entry trigger: Bullish reversal candle (hammer, engulfing) within the zone + volume confirmation
- **Breakout Entry (for stocks at resistance)**:
  - Entry above resistance level + confirmation (close above, not just wick)
  - Volume requirement: >150% of 20-day avg on breakout day
  - Avoid buying extended breakouts (>3% above breakout level without pullback)
- **Entry Classification**:
  - `PULLBACK_ENTRY`: Price within 2% of support zone, uptrend intact → preferred
  - `BREAKOUT_WATCH`: Price at resistance, waiting for breakout → aggressive
  - `IN_NO_MANS_LAND`: Between support and resistance, no clear entry → wait
  - `EXTENDED`: >5% above nearest support, >3% above recent breakout → don't chase
  - `BROKEN_DOWN`: Below all supports → avoid unless accumulation signals

#### Module 3: Stop Loss Placement
Three stop loss methods, report all three and recommend the tightest that's still "safe":

- **Structure Stop**: Below the nearest swing low or support level
  - Place stop 0.5% below the level (avoid getting stopped on exact touch)
  - Must be a real structural level (not arbitrary)
  - Risk: distance from entry to structure stop as % of price

- **ATR Stop**: Entry price minus N × ATR(14)
  - Conservative: 2.0 × ATR (wider, fewer false stops)
  - Moderate: 1.5 × ATR (balanced)
  - Aggressive: 1.0 × ATR (tight, higher chance of stop-out)
  - Adaptive: Use the ATR multiple that lands closest to a structural level

- **Moving Average Stop**: Below the key MA supporting the trend
  - In strong uptrend: stop below EMA(21) (tight, for momentum trades)
  - In moderate uptrend: stop below SMA(50) (standard swing stop)
  - In slow uptrend: stop below SMA(200) (wide, for position trades)

- **Recommended Stop**: Choose the method that gives 3-7% risk from entry
  - <3% risk: stop likely too tight, widen it
  - 3-5% risk: ideal for swing trades
  - 5-7% risk: acceptable if structure demands it
  - >7% risk: too wide — either wait for better entry or skip the trade

#### Module 4: Profit Target Calculation
Multiple target levels for scaling out:

- **Resistance Targets**: Next 2-3 resistance levels above entry
  - T1 = nearest resistance (partial profit, move stop to breakeven)
  - T2 = next resistance (take more profit)
  - T3 = major resistance / measured move target

- **Measured Move Target**:
  - For pullback entries: Prior swing (low to high) projected from pullback low
  - For breakouts: Height of consolidation range projected above breakout

- **ATR-Based Targets**:
  - T1 = Entry + 2 × ATR(14) — conservative (1-2 week move)
  - T2 = Entry + 3.5 × ATR(14) — moderate (2-4 week move)
  - T3 = Entry + 5 × ATR(14) — aggressive (4+ week move)

- **Fibonacci Extension Targets** (from the same swing used for retracement):
  - 100% extension, 127.2% extension, 161.8% extension

#### Module 5: Risk/Reward Assessment
- **R/R Ratio per target**: (Target - Entry) / (Entry - Stop)
  - T1 R/R, T2 R/R, T3 R/R
  - Minimum acceptable: 2:1 for T1
  - Ideal: T1 ≥ 2:1, T2 ≥ 3:1
  - If T1 R/R < 1.5:1 → "POOR R/R — SKIP or wait for better entry"

- **Position Size Suggestion** (based on account risk):
  - Default: risk 1% of account per trade
  - `Shares = (Account × 0.01) / (Entry - Stop)`
  - Report for $25K, $50K, $100K account sizes

- **Win Rate Required**: Breakeven win rate = 1 / (1 + R/R)
  - R/R 2:1 → need 33% win rate to break even
  - R/R 3:1 → need 25% win rate to break even

#### Module 6: Multi-Timeframe Alignment Check
- **Weekly Trend**: Is the weekly chart in an uptrend? (Price > SMA(40wk), SMA(10wk) > SMA(40wk))
- **Daily Setup**: Is the daily pulling back within the weekly uptrend?
- **Alignment Score**:
  - STRONG ALIGNMENT: Weekly uptrend + Daily pullback to support → highest probability
  - PARTIAL ALIGNMENT: Weekly uptrend + Daily extended (or consolidating) → wait for pullback
  - MISALIGNED: Weekly downtrend or sideways + Daily uptick → counter-trend, higher risk
  - AVOID: Weekly downtrend + Daily downtrend → don't buy

#### Module 7: Earnings Proximity Check
- Check if stock reports earnings within the next 14 days
- If within 5 days: **"EARNINGS RISK — Do not hold through earnings as swing trade"**
- If within 14 days: **"EARNINGS APPROACHING — Plan exit before report or accept binary risk"**
- If no earnings soon: **"CLEAR — No earnings catalyst risk"**
- Data source: Alpha Vantage EARNINGS_CALENDAR (same as earnings-whisper.py)

#### Module 8: Pullback Quality Assessment
- **Purpose**: Distinguish healthy pullbacks (high-probability entry) from unhealthy ones (breakdown risk). This is the key missing piece from the secondary gaps — "Pullback Quality" and "Institutional Accumulation" are both addressed here.
- **Healthy Pullback Criteria** (score each 0-20, total 0-100):
  - **Orderly decline**: Price retraces in a controlled staircase pattern, not a sharp waterfall. Measure: max single-day drop during pullback < 1.5× ATR(14). (20 pts)
  - **Declining volume**: Volume should shrink as price pulls back (sellers drying up). Measure: avg volume during pullback < 80% of avg volume during prior advance. (20 pts)
  - **Holds key MA**: Price tests but doesn't break EMA(21) or SMA(50). Measure: low of pullback stays above the supporting MA minus 0.5%. (20 pts)
  - **Shallow retracement**: Pullback retraces <50% of the prior swing. Ideal: 38.2% Fibonacci. Measure: actual retracement % vs prior swing high-to-low. (20 pts)
  - **Accumulation signs**: Chaikin Money Flow (CMF-20) stays positive during pullback, or On-Balance Volume (OBV) holds flat/rising even as price drops — indicates institutions holding, not selling. (20 pts)
- **Pullback Classification**:
  - `HEALTHY` (80-100): Orderly, low volume, holds MA, shallow, accumulation — **ideal entry**
  - `ACCEPTABLE` (60-79): Most criteria met, minor concerns — **entry with tighter stop**
  - `QUESTIONABLE` (40-59): Mixed signals, some breakdown risk — **wait for confirmation**
  - `UNHEALTHY` (0-39): High volume, breaks MA, deep retracement, distribution — **avoid**
- **Significance Explanation** (included in output for each stock):
  - For entry point: Explain WHY this level matters (e.g., "Entry at $139.80 — EMA(21) support, price bounced here 3× in 6 weeks, confluent with Fibonacci 38.2% retracement of the $128→$148 swing")
  - For stop loss: Explain WHY this level is structurally significant (e.g., "Stop at $135.50 — below the SMA(50) at $136.20 which has held as support since November, also below the last swing low at $136.40. Breaking this level invalidates the uptrend thesis.")
  - For targets: Explain the reasoning (e.g., "T1 at $148.50 — prior swing high tested 3× but never broken, high-probability resistance. T2 at $153.20 — Fibonacci 127.2% extension of the $128→$148 swing")
- **Ideal R/R Guidance** (included in output):
  - Minimum R/R for HEALTHY pullback: 2:1 (T1)
  - Minimum R/R for ACCEPTABLE pullback: 2.5:1 (need extra margin for uncertainty)
  - QUESTIONABLE pullback: 3:1 minimum or skip
  - UNHEALTHY pullback: Skip regardless of R/R

**Output Format**:
```
══════════════════════════════════════════
TRADE SETUP SCANNER — Entry, Stop & Targets
══════════════════════════════════════════

NVDA — PULLBACK ENTRY ✅ | Weekly: UPTREND | R/R: 3.2:1
══════════════════════════════════════════

PRICE ACTION:
  Current: $142.50 | 52wk High: $156.80 (-9.1%) | 52wk Low: $89.20 (+59.7%)
  Trend: Above all major MAs | ADX: 32 (trending)

SUPPORT LEVELS (below price):
  S1: $139.80  EMA(21) — dynamic support, price bounced here 3x in 6wk   ★★★
  S2: $136.20  Horizontal — 4 touches, cluster with SMA(50)              ★★★★
  S3: $128.50  SMA(200) + anchored VWAP from Oct low                     ★★★★★
  S4: $125.00  Round number + Fibonacci 61.8% retracement                ★★★

RESISTANCE LEVELS (above price):
  R1: $148.50  Horizontal — prior swing high, 3 touches                  ★★★
  R2: $153.20  Fibonacci 127.2% extension                                ★★
  R3: $156.80  52-week high                                              ★★★★

──────────────────────────────────────────
TRADE PLAN:
  ENTRY ZONE:    $139.00 — $141.00  (pullback to EMA(21) zone)
  STOP LOSS:     $135.50  (below S2 cluster at $136.20, -3.5% risk)
                 Method: Structure stop (0.5% below S2)
                 ATR stop: $135.80 (1.5 × ATR = $4.20) — confirms structure stop

  TARGET 1:      $148.50  (R1, prior swing high)       +5.6%   R/R 1.9:1
  TARGET 2:      $153.20  (R2, Fib extension)           +9.1%   R/R 3.2:1 ← PRIMARY
  TARGET 3:      $156.80  (R3, 52-week high)            +11.8%  R/R 4.2:1

  SCALING PLAN:
    → At T1 ($148.50): Sell 1/3, move stop to breakeven ($140.00)
    → At T2 ($153.20): Sell 1/3, trail stop to T1 ($148.50)
    → At T3 ($156.80): Sell final 1/3

──────────────────────────────────────────
POSITION SIZING (1% account risk):
  $25K account:  55 shares ($7,810)  | Max loss: $250
  $50K account:  111 shares ($15,820) | Max loss: $500
  $100K account: 222 shares ($31,640) | Max loss: $1,000

MULTI-TIMEFRAME: ✅ STRONG ALIGNMENT
  Weekly: Uptrend (price > 40wk SMA, 10wk > 40wk, rising)
  Daily:  Pulling back to EMA(21) within weekly uptrend

EARNINGS: ⚠️ Reports in 18 days (Mar 5 AMC) — CLEAR for swing entry
──────────────────────────────────────────

[TICKER 2] — BREAKOUT WATCH 👀 | Weekly: UPTREND | R/R: 2.8:1
══════════════════════════════════════════
[Same format...]

[TICKER 3] — EXTENDED ⛔ | R/R: 1.1:1
══════════════════════════════════════════
  Current: $88.50 — 7.2% above nearest support ($82.50)
  RECOMMENDATION: WAIT — Don't chase. Set alert at $84.00 for pullback entry.
  If pullback to $84.00: Entry $84, Stop $80.50, T1 $92 → R/R 2.3:1
[...]
```

**Visual Output** (per stock with valid trade setup):
- **Main chart**: 6-month daily price with:
  - Horizontal S/R lines (color-coded by strength: green=strong, yellow=moderate, gray=weak)
  - Entry zone shaded in blue
  - Stop loss as red dashed line
  - Targets as green dashed lines (T1, T2, T3)
  - Key MAs: EMA(21) blue, SMA(50) orange, SMA(200) red
- **Subplot 1**: Volume bars with 20-day average overlay
- **Subplot 2**: RSI(14) with 50 midline
- **Inset**: Weekly chart thumbnail (2 years) showing higher timeframe trend
- Dark theme (#1a1a2e background)

**Discord Webhook**: TBD (new channel for trade setups)

**Integration with run-all.py**: Add as script #13, no yf cooldown. Runs after stock-discovery.py and uses its output.

**Error Handling**:
- Skip tickers with insufficient data (<200 days)
- Skip tickers with no valid entry zone (report as "NO SETUP")
- Graceful degradation: If Fibonacci or measured move can't be computed, use ATR targets only
- If entry zone is too far from current price (>10%), report as "WAIT FOR PULLBACK" with alert level

---

### 4. Early Trend Change Detection Scanner (`early-trend-scanner.py`)

**Purpose**: Detect early signs of trend reversals before they become obvious, using multi-factor divergence analysis, volume patterns, Wyckoff methodology, and candlestick patterns at key levels.

**Input**: `watchlist.json` tickers (26 Purple list stocks)

**Data Requirements**:
- OHLCV data: 6 months daily (for indicators + volume analysis)
- Yahoo Chart API: `range=6mo&interval=1d`
- Parallel fetch with ThreadPoolExecutor(max_workers=5)

**Detection Modules**:

#### Module 1: Price-RSI Divergence
- **Bullish divergence**: Price makes lower low, RSI makes higher low
- **Bearish divergence**: Price makes higher high, RSI makes lower high
- **Implementation**:
  - Calculate 14-period RSI using standard formula
  - Identify swing highs/lows using scipy.signal.argrelextrema (order=5)
  - Compare last 2-3 swing points for divergence
  - Strength metric: RSI delta vs price delta (normalized)
- **Output**: Signal strength 0-100, divergence type, price points, RSI values

#### Module 2: Price-MACD Divergence
- **Bullish divergence**: Price lower low, MACD histogram higher low
- **Bearish divergence**: Price higher high, MACD histogram lower high
- **Implementation**:
  - MACD(12,26,9) — fast EMA, slow EMA, signal line
  - Use MACD histogram (MACD line - signal line)
  - Identify swing points (same method as RSI)
  - Compare histogram values at corresponding price swings
- **Output**: Signal strength, divergence type, MACD histogram deltas

#### Module 3: Volume Divergence
- **Declining volume on trend continuation**: Weakening momentum
- **Implementation**:
  - Calculate 20-day average volume
  - Current volume < 60% of 20-day avg = red flag
  - Track volume trend over last 10 days (linear regression slope)
  - Compare volume on up days vs down days (last 20 days)
  - Volume-price correlation (last 30 days) — should be positive in uptrend
- **Criteria**:
  - Low volume: < 60% of 20-day avg for 3+ of last 5 days
  - Declining volume: negative slope on 10-day volume trend
  - Volume divergence: price rising + volume falling (or vice versa)
- **Output**: Volume status, avg volume, current volume %, trend slope

#### Module 4: Wyckoff Springs & Upthrusts
- **Spring (bullish)**: Price briefly breaks support, then reverses sharply up on high volume
- **Upthrust (bearish)**: Price briefly breaks resistance, then reverses down on high volume
- **Implementation**:
  - Identify support/resistance: 20-day rolling min/max, round numbers, prior swing points
  - Detect false breakouts:
    - Intraday break (low < support OR high > resistance)
    - Close back inside range (close > support for spring, close < resistance for upthrust)
    - Volume spike: > 150% of 20-day avg volume
    - Reversal confirmation: next 1-3 days move opposite direction
  - Context check: Must occur after consolidation (ATR compression < 80% of 60-day avg ATR)
- **Output**: Pattern type, breach level, reversal strength, volume confirmation

#### Module 5: Moving Average Compression
- **Concept**: When multiple MAs converge, volatility contraction precedes expansion
- **Implementation**:
  - Calculate MA(10), MA(20), MA(50), MA(200)
  - Measure compression: stdev([MA10, MA20, MA50]) / Close price
  - Compare to historical compression (60-day percentile)
  - Additional: Bollinger Band width (20,2) percentile
  - Direction bias: Price position relative to MAs, MA slope alignment
- **Thresholds**:
  - High compression: < 15th percentile of 60-day compression values
  - Extreme compression: < 5th percentile
- **Output**: Compression percentile, Bollinger width percentile, bias direction

#### Module 6: Candlestick Reversal Patterns at Key Levels
- **Key levels**: Support/resistance from 20/50/200 MA, prior swing points, round numbers
- **Patterns to detect**:
  - Bullish: Hammer, Inverted Hammer, Bullish Engulfing, Morning Star, Piercing Line
  - Bearish: Shooting Star, Hanging Man, Bearish Engulfing, Evening Star, Dark Cloud Cover
- **Validation criteria**:
  - Pattern occurs within 1% of key level
  - Volume > 120% of 20-day avg (shows conviction)
  - Follow-through: next candle confirms direction
- **Implementation**:
  - Pattern recognition functions for each type
  - Level proximity check (distance to nearest MA/support/resistance)
  - Volume filter
  - Confirmation check (next 1-2 days)
- **Output**: Pattern name, location (which level), volume %, follow-through status

#### Module 7: Low Implied Volatility (IV) Detection
- **Concept**: Low IV often precedes large moves (volatility expansion)
- **Implementation**:
  - Use **IBKR (Interactive Brokers) API** to fetch option data
  - Calculate 30-day Implied Volatility (IV) from at-the-money options
  - Compare current IV to 60-day IV percentile
  - Compare IV to Historical Volatility (HV) — IV/HV ratio
- **IBKR API Integration**:
  ```python
  from ib_insync import IB, Stock, Option
  ib = IB()
  ib.connect('127.0.0.1', 7497, clientId=1)  # TWS/Gateway

  contract = Stock(ticker, 'SMART', 'USD')
  ib.qualifyContracts(contract)
  ticker_data = ib.reqTickers(contract)[0]

  # Get option chain for IV calculation
  chains = ib.reqSecDefOptParams(contract.symbol, '', contract.secType, contract.conId)
  # Calculate 30-day IV from ATM options
  ```
- **Thresholds**:
  - Low IV: < 20th percentile of 60-day IV range
  - Very Low IV: < 10th percentile
  - IV/HV ratio < 0.8: Options pricing in less volatility than realized
- **Output**: Current IV %, IV percentile, IV/HV ratio, interpretation

**Signal Detection Logic**:
- Each module independently detects patterns (no scoring)
- Report ALL stocks that meet ANY module criteria
- List specific reasons (which modules triggered) for each stock

**Output Format**:
1. **Discord text summary** (all stocks with signals):
   ```
   ══════════════════════════════════════════
   EARLY TREND CHANGE SIGNALS — [BULLISH/BEARISH]
   ══════════════════════════════════════════

   [TICKER 1] — BULLISH Setup Detected
   ─────────────────────────────────────────
   REASONS:
   ✓ RSI Divergence: Price lower low at $XX.XX (Jan 15), RSI higher low (32 → 38)
   ✓ Volume Declining: 48% of 20-day avg for 4 of last 5 days
   ✓ Wyckoff Spring: Broke support at $XX.XX on Jan 12, reversed on 180% volume
   ✓ Low IV: 18.5% (12th percentile), IV/HV = 0.72 — expansion likely

   [TICKER 2] — BEARISH Setup Detected
   ─────────────────────────────────────────
   REASONS:
   ✓ MACD Divergence: Price higher high at $XX.XX, MACD histogram lower high
   ✓ MA Compression: 8th percentile (extreme), BBW at 5th percentile
   ✓ Candlestick: Shooting Star at $XX.XX (200-day MA), volume 145%
   ✓ Low IV: 22.1% (18th percentile), IV/HV = 0.79 — coiled spring

   [Continue for all detected signals...]
   ```

2. **Visual chart** (for stocks with 2+ signals):
   - Price + volume subplot
   - Overlays: MA(20,50,200), support/resistance lines
   - Markers: Divergence points, Wyckoff events, candlestick patterns
   - RSI subplot with divergence lines
   - MACD histogram subplot
   - IV percentile indicator (bottom subplot)
   - Dark theme, 6-month window

**Discord Webhook**: TBD (new channel for early trend signals)

**Integration with run-all.py**: Add as script #11, no yf cooldown (uses Yahoo Chart API)

**Error Handling**:
- Skip tickers with insufficient data (<120 days)
- Graceful degradation: If one module fails, continue with others
- Log all errors to stderr with ticker context


---

## TODO

### Russell 3000 Weekly New Highs / Breadth Scanner (UI built, needs live data)
- **What**: A browser-based scanner that takes a user-defined lookback period (in days) and scans Russell 3000 stocks to find the strongest advancers, ranks them by sector/sub-sector breadth (advancers vs decliners per GICS cluster), and generates an AI narrative about the macro/sector story implied by the breadth configuration.
- **Status**: Frontend UI complete (dark terminal aesthetic, sector breadth bars, adv/dec ratio, top advancers/decliners table, AI narrative via Claude API). Currently uses simulated price moves.
- **Next step**: Build the Python data-fetch layer using the Yahoo Chart API (already used in other scripts) to pull actual N-day % changes for Russell 3000 constituents, classify each ticker by GICS sector/sub-sector, and export a JSON file the UI can consume.
- **Russell 3000 constituent list**: Source from a static CSV or ETF holdings (IWV/VTHR), updated quarterly.
- **Output JSON schema**: `[{t, n, s, ss, cap, pct, isNewHigh}, ...]` — ticker, name, sector, sub-sector, cap tier, % change over N days, new high flag.
- **Integration**: Could eventually be added to `run-all.py` as a weekly Friday-close script posting sector breadth summary to a new Discord channel.


## Dependencies (add to requirements-ci.txt if missing)
- `scipy` — for signal processing (argrelextrema)
- `numpy` — array operations
- `pandas` — data manipulation
- `matplotlib` — charting
- `requests` — API calls
- `ib_insync` — IBKR API integration for IV data

## IBKR API Setup
- **Requirement**: Interactive Brokers TWS (Trader Workstation) or IB Gateway running locally
- **Connection**: localhost:7497 (TWS paper) or localhost:4001 (Gateway)
- **API Permissions**: Enable in TWS/Gateway settings → API → Settings → "Enable ActiveX and Socket Clients"
- **Data Subscriptions**: Requires market data subscription for option chains
- **Fallback**: If IBKR unavailable, skip IV module (graceful degradation)
- **Alternative**: Can use `yfinance` option data as backup (less reliable):
  ```python
  ticker = yf.Ticker("AAPL")
  options = ticker.option_chain(ticker.options[0])  # nearest expiry
  # Calculate IV from puts/calls
  ```

## Testing Strategy
- Test on known atleast 10-20 historical reversals (e.g., TSLA Nov 2021 peak, NVDA Oct 2022 bottom), and provide me with report on how each of the testing went, which trends were caught, etc.
- Validate divergence detection accuracy
- Ensure Wyckoff pattern recognition aligns with manual chart analysis
- Volume thresholds tuning based on sample results
- Verify IBKR API connection and IV data accuracy
- Test graceful degradation when IBKR unavailable

---

## Trend Entry & Exit Planner — Bubble-Riding Strategy

A separate strategy from the top-down sector-rotation swing-trading framework above. This planner is for momentum/bubble markets where a small theme of stocks or a sector ETF is driving disproportionate returns. The exit philosophy is "ride → de-risk → exit on break, don't fade early." Implemented as `bubble-scanner.py` (planned).

### The 12 Bubble Notes (Druckenmiller playbook)

1. Bubbles don't ring a bell at the top; it's a yellow flag, not a sell-ticket.
2. Shorting a bubble call is an expensive mistake, base rates favor trend.
3. Asymmetry is brutal, and a valuation thesis without tape is premature (1997).
4. Signal is for sizing, not shorting.
5. Bubble signals calibrate risk budgets — it does NOT generate a trade.
6. Time is a bear's best friend: stats improve with time.
7. The asymmetry that destroys early shorts inverts in 6–12m window.
8. Exit on the tape, not valuation.
9. Scale, don't flip: binary positioning gets punished in these tapes.
10. Reduce gross as conditions deteriorate.
11. The win is in the de-risking sequence, not calling the top.
12. Bottom line: Ride → De-risk → exit on break. Don't fade early.

### Methodology Provenance

- Druckenmiller / Soros reflexivity (the 12 notes above)
- AQR trend-following with macro regime overlay
- Paul Tudor Jones tape reading

No CJ / stat-arb / RenTech-style signals in this planner. All exits are price-action driven; no valuation triggers (P/E, P/S, EV/EBITDA) anywhere.

### Stage 1: Bubble Qualifier (sectors / ETFs only)

Applied to the 48 ETFs in `etf-holdings.json` (subsectors + EW sectors + CW sectors). Not applied to individual stocks. Four conditions, evaluated independently; each candidate's output reports which are met.

| # | Condition | Threshold |
|---|---|---|
| C1 | 12-month total return | > +100% |
| C2 | Price stretch from trend | > 2σ above 200-day SMA |
| C3 | Accelerating momentum | (close_now / close_63d_ago)^4 > (close_now / close_252d_ago) |
| C4 | Regime gate | breadth STRONG or HEALTHY AND vol regime LOW or NORMAL |

C4 uses status fields from `breadth-scanner.py` and `volatility-regime.py` rather than recomputing breadth or VIX.

Classification by count:
- **4/4 met** → `FULL BUBBLE` (full size active)
- **3/4 met** → `EMERGING BUBBLE` (reduced size)
- **2/4 met** → `WATCHLIST` (track only, no entry)
- **0–1/4 met** → `REJECT`

Output line example:
```
SMH    [C1✓ C2✓ C3✓ C4✓]  FULL BUBBLE   1Y=+182%  stretch=2.8σ  3M_ann=+241% > 12M=+182%
XLK    [C1✓ C2✓ C3✗ C4✓]  EMERGING      1Y=+108%  stretch=2.1σ  3M_ann=+95%  < 12M=+108%
```

### Stage 2: Tradeable Universe Resolution

Once a sector qualifies as `FULL BUBBLE` or `EMERGING`, the tradeable universe for that theme is:
1. Constituents of that ETF from `etf-holdings.json` (15–20 holdings per ETF)
2. ∩ `watchlist.json` (purple list, 26 tickers) — if intersection is non-empty, prioritize these
3. ∪ the ETF itself (always tradeable as a fallback / theme proxy)

Entries and exits are evaluated at the stock level for stocks in bubble sectors.

### Stage 3: Entry Types (4 archetypes, long-only)

Candidate passes if any one fires. Entry type is logged so exits can be calibrated by entry context.

**Entry A — New-Leg Breakout (Soros, mid-bubble)**
- Stock's parent sector in BUBBLE state ≥ 20 trading days
- Last 10–30 sessions form consolidation: high-to-low range < 12%
- Daily close above 20-day high
- Volume > 1.5× 20-day avg on breakout day
- RS line vs parent sector ETF at new 60-day high
- ADX(14) > 25

**Entry B — Boring Pullback (Druckenmiller)**
- Pre-condition: price > 50 SMA, 50 SMA > 200 SMA, both rising
- Daily close within 1% of 21 EMA, OR within 1.5% of 50 SMA after price had been > 5% above it
- Pullback respected the MA: no daily close below MA × 0.99
- Daily RSI(14) cooled to 40–55 from prior > 65 reading
- Bullish reversal candle at the MA (hammer / engulfing / inside-day high break)
- Volume on bounce day > 20-day avg

**Entry C — Failed Breakdown / Wyckoff Spring (PTJ)**
- Stock in bubble-sector universe
- Price breaks intraday below identified support (recent swing low / 21 EMA / round number)
- Closes back above support same day or within 2 sessions
- Volume on reversal day > 1.5× 20-day avg
- RSI(14) rebounds from < 40 to > 50 within 3 sessions

**Entry D — RS Leadership Confirmation (AQR + Druckenmiller, initial entry)**
- Stock's parent sector in BUBBLE state ≥ 20 days
- 13-week return ranks in top decile of universe
- RS vs parent sector ETF positive over trailing 26 weeks
- Price > all of {10-week MA, 21 EMA, 50 SMA, 200 SMA}
- Weekly RSI > 55 and rising; no bearish weekly RSI divergence
- ADX(14) > 25

### Stage 4: Exit Ladder (graduated, price-action only)

#### Flashing Yellow — Early Warning (ANY 1 of 6)
Trim 10% (alert action — pay attention, tighten attention to chart).
- Weekly RSI(14) peaked > 70 and declined for 2 consecutive weeks
- Anchored VWAP from acceleration start broken on a daily close
- 5-day ROC < 20-day ROC for 3 consecutive sessions
- Distance from 21 EMA at > 95th percentile of trailing year
- Parabolic warning: 5+ recent sessions where daily range > 2× ATR(14)
- Time-decay: position held > 180 calendar days (auto-trim)

#### Solid Yellow — Momentum Decay (ANY 2 of 6)
Trim additional 25% (now at ~65% of original size after flashing trim).
Same 6 triggers as flashing yellow, but two or more co-occurring.

#### Orange — Distribution (ANY 1 of 6)
Trim additional 25%.
- Bearish weekly RSI divergence: price makes new 8-week high, RSI doesn't
- Daily close below 21 EMA, OR a gap-down open below 21 EMA on volume > avg
- Failed retest of 21 EMA within 5 sessions of losing it
- Up-volume / down-volume ratio drops below 0.8 over trailing 10 sessions
- Sector breadth degrades from STRONG/HEALTHY to MIXED (via `breadth-scanner.py`)
- 2-σ down day on volume > 2× avg

#### Red — Trend Broken (ANY 1, full exit)
Exit remaining position.
- Lower low: daily close below the most recent 10-day pivot low
- Weekly close below the 10-week MA
- Sector breadth degrades to WEAK (via `breadth-scanner.py`)
- 3 consecutive lower highs following a parabolic phase
- Gap below 50 SMA on volume > 1.5× avg
- Volatility regime shifts to ELEVATED or EXTREME (via `volatility-regime.py`)

#### Trailing Stop (always active, hard rule)
Fires regardless of tier state.
- Initial: entry price − 1.5 × ATR(14)
- After +10% gain: tighten to entry (breakeven)
- After +25% gain: tighten to entry + 0.5 × initial ATR (lock in)
- After flashing/solid yellow triggered: tighten to current price − 1.0 × ATR(14)

### Stage 5: Position Sizing (vol-adjusted, AQR risk-parity)

```
asset_annualized_vol = stdev(daily_returns_60d) × √252
position_pct = base_size × (target_vol / asset_annualized_vol)
```

Parameters:
- `target_vol = 50%` (aggressive, bubble-asset scale)
- `base_size = 5%` for FULL BUBBLE; `3%` for EMERGING
- Entry-D continuation adds: +2% per re-signal
- **Per-name cap: 25%**
- **No per-theme cap** (intentional: narrow-breadth bubbles concentrate in a few names by design)

Example sizing at `target_vol = 50%`:

| Asset | Annualized vol | Base size | Vol-adjusted size |
|---|---|---|---|
| AVGO | 35% | 5% | 7.14% (capped at 25%) |
| NVDA | 50% | 5% | 5.0% |
| TSLA | 70% | 5% | 3.57% |
| MSTR | 120% | 5% | 2.08% |

### Stage 6: Output Format (Discord post)

Six sections per run:
1. **Header**: regime gate status (breadth + vol) — GATE OPEN / CLOSED + reason
2. **FULL BUBBLES** (4/4 met): table with flags + key stats
3. **EMERGING** (3/4 met): table with flags + the missing condition called out
4. **WATCHLIST** (2/4 met): name + flags only
5. **Entry signals today**: stocks in bubble universe with Entry A/B/C/D firing, type tagged, vol-adjusted size suggested
6. **Exit signals today**: stocks triggering Flashing Yellow / Solid Yellow / Orange / Red, with which specific triggers fired

### Integration

- New script: `tools/bubble-scanner.py`
- Inserted into `run-all.py` after `breadth-scanner.py` and `volatility-regime.py`, before `fx-models.py`
- Discord webhook: `https://discord.com/api/webhooks/1504380703645761536/NrBply5IJF3F8h8BB8qANuB1-8lLsPp4xEz_zywcj5205cS0ZzMJNacAsdTj3029RduR`
- No persistent state file in v1 (no `bubble-positions.json` yet); script outputs "what's actionable today" independently each run

### Future: Bottom Fishing Planner (out of scope, placeholder)

A separate planner to be designed later for catching reversals at the other end of the cycle: oversold sectors/stocks with capitulation signals, Wyckoff accumulation patterns, smart-money reentry. Not in scope of this Trend Entry/Exit Planner.
