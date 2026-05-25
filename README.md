# AI Hedgefund

**An institutional-grade investment automation stack built with Claude Code, a $35 Raspberry Pi, and free APIs.**

Built by [Nick Nemeth](https://x.com/nicknemo17) — investor, hedgefund consultant, and author of [Mispriced Assets](https://mispricedassets.substack.com) on Substack.

---

## What This Is

This is the full source code for a system that automates ~90% of my daily investment workflow. It runs 27 automated jobs on a Raspberry Pi 5, monitors every position in my portfolio, scans for breaking news, tracks insider buying, detects regime changes, runs econometric models, and gives me deep financial research on demand — all for about $3-7/day.

A Bloomberg Terminal costs $24,000/year. This costs less than a coffee.

The system was built almost entirely through conversation with Claude Code over the course of a few weeks. I am not a software engineer. I am an investor who learned to talk to AI effectively.

---

## Architecture

Three-tier cost architecture that keeps spending predictable:

| Tier | What | Cost | Examples |
|------|------|------|----------|
| **1 — Free** | Direct API calls (yfinance, FRED, EDGAR) | $0.00 | Market snapshots, news scanning, price monitoring |
| **2 — Low** | Light Claude reasoning | ~$0.05/call | Substack evaluation, morning synthesis |
| **3 — Deep** | Dexter research agent + Financial Datasets API | ~$0.15-0.50/call | Multi-step financial analysis, thesis validation |

The key insight: **most of what an investor does daily is data retrieval, not analysis. Don't pay AI to fetch a stock price.**

---

## What's Running

### Pre-Market (6:00-6:30 AM PST weekdays)
- `macro-calendar.py` — 108 economic events with model-based predictions
- `earnings-whisper.py` — upcoming earnings + drift tracking
- `options-implied-move.py` — expected vs actual earnings moves
- `morning-briefing.sh` — full portfolio P&L + crypto + earnings schedule
- `estimate-revisions.py` — weekly analyst estimate change tracker

### Market Hours
- `technicals-scanner.py` — RSI, MACD, Bollinger, anchored VWAP, crossover detection
- `market-snapshot.py` — hourly SPY/QQQ/IWM/VIX dashboard
- `news-alert.py` — breaking news for all holdings
- `econ-release-analysis.py` — real-time FRED polling with pre-computed model predictions
- `trump-pump-monitor.sh` — market-moving tweet detection

### Post-Close (4:15-4:55 PM EST weekdays)
- `portfolio-tracker.sh` — full P&L breakdown
- `thesis-monitor.sh` — conditional AI analysis (only fires on triggers)
- `regime-dashboard.py` — cross-asset regime classification (VIX, credit, yields)
- `volatility-regime.py` — IV/RV gap, VIX percentile ranking
- `relative-strength.py` — holdings ranked vs SPY (Friday)
- `sector-rotation.py` — 11 sector ETF flow analysis (Friday)
- `econometrics-report.py` — EWM correlations + FRED predictor + FX models (Friday)

### Event-Driven
- `edgar-monitor.py` — schedule-driven SEC filing detection + deep AI earnings analysis
- `insider-clusters.py` — cluster detection algorithm for insider buying patterns
- `discord-research-handler.py` — role-gated `!research` commands via Dexter

### Feeds
- `crypto-feed.sh` — BTC/ETH/SOL prices
- `tweet-feed.sh` / `tweet-curated.sh` — priority Twitter accounts
- `substack-feed.sh` — curated Substack articles

---

## Discord Channel Routing

Every output routes to the right channel. No noise. No overlap.

| Channel | Purpose |
|---------|---------|
| `#market-dashboard` | State of the world — snapshots, macro calendar, regime alerts |
| `#trade-alerts` | **Only** actionable signals — technicals, thesis triggers, insider clusters |
| `#research` | Context — morning briefing, P&L, earnings, news, deep research |
| `#sec-filings` | EDGAR filings + AI deep analysis |
| `#econometrics` | Correlation matrices, factor exposure, economic models |
| `#tweet-feed` | Priority Twitter posts |
| `#substack-feed` | Curated articles |
| `#crypto` | Crypto prices |

---

## The Econometrics

The `econometrics-report.py` runs once per week (3.6 seconds) and produces:

1. **EWM Correlation Matrix** — exponentially-weighted correlations between indexes and macro variables. Recent data weighted more than old. Shows what's driving the market *right now*.

2. **Economic Predictor** — 18 FRED series correlated with 1-month and 3-month forward equity returns, with t-statistics. "When CPI comes in hot, what happens to QQQ?"

3. **FX Models** — carry, momentum, mean-reversion, and equity beta for major currency pairs.

Model coefficients save to a JSON state file that the macro calendar and econ release scripts load — so when CPI actually drops at 8:30 AM, the predictions are pre-computed and instant.

---

## Philosophy

The tools will get commoditized. Someone will package this into a SaaS for $50/month. What won't be commoditized: **the person deciding what to feed the model.** The investment views. The thesis construction. The ability to look at a FRED print and know — from experience — whether it matters.

The AI is the leverage. You are still the edge.

**Man on the model.**

---

## About Me

I'm Nick Nemeth. I'm an investor and hedgefund consultant. I write about markets on [Mispriced Assets](https://mispricedassets.substack.com), and I build tools that give me an edge. Michael Burry restacked Part 1 of my Substack series about this system, which was pretty surreal for a guy writing from his apartment.

I built all of this with Claude Code — not because I'm a programmer, but because I'm an investor and consultant who refuses to process information slower than the market moves. Every script in this repo started as a conversation. "Build me something that does X." Iterate. Ship. Move on.

If you're an investor who's curious about AI tooling, or a builder who's curious about markets, I hope this inspires you to make something. Take what you want, build what you need, skip what you don't.

But don't sit this out.

---

## Contact

- Substack: [mispricedassets.substack.com](https://mispricedassets.substack.com)
- X/Twitter: [@NickNemo17](https://x.com/nicknemo17)
- Email: contact@example.com

---

*Built with [Claude Code](https://claude.ai/claude-code) by Anthropic.*

*"How many developers worked on this?" — I am Legion, we are many. It's just me and a mass of AI subagents running on a $35 Raspberry Pi in my apartment. We don't sleep. We don't take PTO. We just parse SEC filings at 4 AM and argue about VIX percentiles.*
