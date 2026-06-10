# Why Would Commodities Sell Off When US Inflation Rises?

*Validated against `sector-cycle-backtest.py` — total-return performance across six Fed cycles (1988→2023).*

## First, the premise needs sharpening

Commodities are the textbook *inflation hedge* — naively they should **rise** with inflation, and in the backtest they often do. So "commodities sell off when inflation rises" isn't universally true. It's true in a specific window and a specific regime. The two things that decide it are **(1) timing relative to the Fed**, and **(2) whether the inflation is supply- or demand-driven**.

The cleanest framing: commodities don't sell off *because of inflation*. They sell off because of **what the Fed does about inflation**, and whether the price spike was backed by real demand or not.

## The Fed-reaction channel (why the sell-off happens at all)

Rising US inflation → Fed hikes → four forces that hit commodities harder than any other asset:

1. **Demand destruction via policy** — commodities are the most cyclical, demand-elastic asset. When the Fed deliberately engineers a slowdown to kill inflation, the marginal barrel/ton of industrial demand falls hardest.
2. **Stronger USD** — hikes raise real rates → dollar strengthens → commodities (USD-priced) fall mechanically.
3. **Carry/opportunity cost** — higher rates raise the cost of holding inventory and the opportunity cost of a zero-yield asset (this is the *gold* channel specifically).
4. **Forward discounting** — commodities price future growth; if the tape expects a Fed-induced recession, cyclicals roll over *ahead* of it.

The timing split is visible directly in the **2021-23 inflation-shock cycle**:

| Window | Crude | GSCI | Copper |
|---|---|---|---|
| PRICING-IN (pre-liftoff) | **+49%** | **+41%** | +10% |
| HIKING | **−16%** | **−14%** | **−15%** |
| PLATEAU | **−25%** | **−23%** | −8% |

Commodities *led* as inflation built (pricing-in), then got crushed the moment the Fed actually started hiking. The sell-off is the **policy response**, not the inflation itself. By the time CPI was screaming, crude had already topped.

## Supply vs demand — the core distinction

The backtest gives a near-perfect natural experiment: two hiking cycles, both with rising inflation, opposite commodity outcomes.

**2004-06 — DEMAND-driven (China industrialization, real global boom):**

| Window | Copper | Crude | GSCI |
|---|---|---|---|
| PRICING-IN | +57% | +18% | +20% |
| HIKING | **+185%** | **+95%** | **+65%** |
| PLATEAU | +184% | +117% | +86% |

**2021-23 — SUPPLY-driven (COVID chains + war shock):**

| Window | Copper | Crude | GSCI |
|---|---|---|---|
| PRICING-IN | +10% | +49% | +41% |
| HIKING | **−15%** | **−16%** | **−14%** |
| PLATEAU | −8% | −25% | −23% |

Same setup (Fed hiking into high inflation), inverted result. The difference is the *source*:

- **Demand-pull inflation** (overheating real economy / secular demand boom): commodities are the **beneficiary**, not the victim — they're literally *what is being demanded*. The Fed is hiking into a durable real boom, and rate hikes can't break structural demand. Commodities rise *through* the entire hiking cycle. In 2004-06 the Fed hiked 17 times and copper still tripled.

- **Supply-push inflation** (embargo / war / supply-chain shock): the price spike **is the disease**, and it's self-correcting through three mechanisms that all point down — (a) high prices destroy their own demand (price elasticity — $5 gas means less driving), (b) supply eventually responds, and (c) the Fed hikes into *already-weakening* real demand. So the relative price gain mean-reverts hard.

**The rule:** if the commodity *is* the reason for inflation (supply shock), it sells off once the shock fades and the Fed leans on demand. If the commodity is rising *because* real global demand is overheating (demand-pull), it keeps rising and the hikes don't stop it.

## Gold is the exception — a rate play, not a growth play

Gold/miners decouple from industrial commodities:

- 1994 PRICING-IN: gold miners **+80%**, then HIKING **−24%** — pure real-rate sensitivity, no growth content.
- 2021-23: while crude went −25% in PLATEAU, **gold went +34%** — once real rates peaked and a recession/safe-haven bid emerged, gold rallied while cyclical commodities bled.

Gold sells off on *rising real rates* (carry channel); industrial commodities sell off on *demand destruction* (growth channel). Don't lump them.

## Verdict

The thesis holds, with a qualifier: **commodities sell off when rising inflation is supply-driven and the Fed is hiking** — because that inflation is self-limiting and the policy response attacks the demand side. When inflation is **demand-driven** (a real growth boom), commodities are the thing in demand and they rally straight through the hiking cycle (2004-06 is the textbook case). The mechanism is the Fed's reaction function plus the dollar, not inflation as a price level — and the source of the inflation flips the sign of the entire trade.

## Caveat on the tooling

The backtest measures *total-return windows*, not the contemporaneous CPI path, so "the Fed reacting to inflation" is inferred from the cycle labels rather than measured against monthly prints. The regime tags (`SUPPLY/CHINA-demand` vs `INFLATION-driven, supply shock`) are hand-classified in `sector-cycle-backtest.py`, not derived from data. The directional evidence is unambiguous, but to make it airtight, overlay actual CPI/core-PCE and a demand-vs-supply inflation decomposition (e.g. the SF Fed's supply-driven PCE series) on each window.
