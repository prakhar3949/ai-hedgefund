# Humanoid Robot Supply Chain — Key Takeaways

*Source: McKinsey Industrials Practice, "Turning humanoid supply chain constraints into billion-dollar wins," April 2026.*

## Bottom line

1. **The supply chain — not the AI — is the constraint** that will set the pace of humanoid scale-up. Cost compression from today's $30K–$150K BOM toward the <$20K target depends on the maturity of the component supplier base.
2. **Bottlenecks cluster around actuators and force/tactile sensing**, not compute or batteries. EV adjacency makes batteries and power electronics cheap; precision gearboxes, planetary roller screws, and 6-axis force/torque sensors do not benefit from any high-volume adjacent industry.
3. **China holds structural advantage** in the cost-/scale-dominated layers (rare-earth magnets 90%, bearings 40%, motors 35%, power electronics 30%). The US/EU keep the frontier-AI and high-assurance edge. The world is more likely to **bifurcate** than have a single winner.
4. **The industry is in a premodular phase** — OEMs are vertically integrating because no supplier platform exists yet. The "engine-maker for humanoids" role is wide open, with Schaeffler, Bosch, Magna, Qualcomm, Nvidia, Jabil, SoftBank/ABB all actively positioning over the past 18 months.
5. **Inflection trigger** = predictable multi-year volumes + stable architectures + standardized interfaces. None yet, but the partnership/M&A wave (Apptronik–Jabil, SoftBank–ABB $5.4B, Hyundai–Samsung SDI, Bosch–Neura) shows adjacent industries are not waiting.

## The five BOM domains (% of total cost, performance differentiation)

| Domain | % of BOM | Differentiation | Notes |
|---|---|---|---|
| **Actuators** (rotary + linear) | 40–60% | **HIGH** | Biggest cost, biggest moat. Tesla Optimus = 28 body actuators + 50 hand actuators. |
| **Sensing & perception** | 10–20% | HIGH | Camera/LiDAR scaled; force/tactile not. |
| **Compute & control** | 10–15% | Medium | Off-the-shelf parts exist; integration & safety are the bottleneck. |
| **Structural** | 5–10% | Low | Prototype-grade CNC today; ripe to industrialize once geometry freezes. |
| **Battery modules** | 5–10% | Low | Pack architecture + thermal matters; cells are commodity. |

## Bottleneck risk buckets

**LOW RISK — Scaled supply, minor adaptation**: BLDC/PMSM motors, power electronics, standard bearings, camera modules, LiDAR/radar, battery cells. EV/consumer-electronics spillover already dominant.

**MEDIUM RISK — Scaled supply, major adaptation**: Encoders, real-time control electronics, IMUs, vision hardware. Underlying capacity is fine; humanoid-specific qualification + packaging is the work.

**HIGH RISK — Structural bottlenecks (THE OPPORTUNITY ZONE)**:
1. **Precision motion** — Harmonic/strain-wave drives, planetary roller screws, robotics-grade linear guides, rare-earth permanent magnets (NdFeB).
2. **Force & tactile sensing** — 6-axis force/torque sensors, linear-force sensors, tactile sensors. The most fragmented category — no dominant architecture.
3. **Compute & control as a platform** — not capacity-bound, but no humanoid "ECU" exists. Tesla is the only OEM with an in-house compute stack (FSD adapted for Optimus).

## China's structural advantage

- **90% of permanent magnet processing**, ~70% of rare-earth mining
- 40% precision bearings, 35% motors, 30% power electronics
- 295K new industrial robot installs in 2024 (54% of global), 2.03M operational stock
- ~7,700 humanoid patents in last 5 years vs ~1,560 US, ~1,100 Japan
- Without Chinese suppliers, Tesla Optimus Gen 2 BOM would jump from ~$46K → ~$131K (3×)
- Unitree G1 already listed at ~$13.5K; Optimus expected $20K–$30K at scale

**Offsetting constraints**: US private AI investment ~$109B (2024) vs China ~$9.3B — 12× gap at the frontier-AI layer. US export controls on advanced compute. Export markets may accept Chinese hardware but restrict software/data.

## Strategic shift: from vertical integration to subsystem platforms

Through 2035, McKinsey expects:
- Structural, battery, compute → shift to **vendor-led / external sourcing** soonest
- High-precision actuators, harmonic drives, force sensing → **OEM-led codevelopment longest**
- A layered structure emerges: Tier-1 suppliers in compute & batteries (like automotive), selective consolidation in sensing, OEMs retaining motion architecture

**Investable framing**: the winners will not be component suppliers — they'll be the firms that define **integrated subsystem platforms** (actuator modules, compute+control stacks, sensing suites).

---

## Named suppliers in the report — public/private, ticker, revenue

Revenues are most recent annual figures (FY2024 or trailing 12 months as of early-mid 2025), approximate. Sorted by category.

### Battery cells & systems

| Company | Role | Ticker | US-listed? | Revenue (~ latest) |
|---|---|---|---|---|
| **CATL** | EV/humanoid battery cells (Contemporary Amperex) | SHE: 300750 / HKEX: 3300 | No (no US listing) | ~$53B |
| **LG Energy Solution** | Confirmed supplier to Boston Dynamics Atlas | KRX: 373220 | No | ~$24B |
| **Samsung SDI** | Solid-state batteries unveiled for humanoids at InterBattery 2026; MOU with Hyundai | KRX: 006400 | No | ~$15B |
| **Panasonic Holdings** | Mentioned among global cell leaders | TYO: 6752 | **Yes — OTC: PCRFY (ADR)** | ~$60B |

### Precision motion — gearboxes, screws, bearings

| Company | Role | Ticker | US-listed? | Revenue |
|---|---|---|---|---|
| **Harmonic Drive Systems** | Strain-wave gearboxes — JP leader | TYO: 6324 | **OTC: HSDDF** (thin ADR) | ~$350M |
| **Nabtesco** | Cycloidal & precision gearboxes | TYO: 6268 | **OTC: NCTKY** (thin ADR) | ~$2.0B |
| **Leaderdrive** (Leader Drive) | Chinese harmonic-drive challenger | SHA STAR: 688017 | No | ~$200M |
| **SKF** | Planetary roller screws, bearings | STO: SKF-B | **OTC: SKFRY (ADR)** | ~$10B |
| **THK** | Linear guides | TYO: 6481 | **OTC: THKLY (ADR)** | ~$2.5B |
| **Hiwin Technologies** | Linear guides + ball screws (Taiwan) | TWSE: 2049 | No (TW only) | ~$700M |
| **Bosch Rexroth** | Linear motion (Bosch division) | — | No (parent Bosch private) | — |

### Motors

| Company | Role | Ticker | US-listed? | Revenue |
|---|---|---|---|---|
| **Maxon Motor** | High-end precision motors (Swiss) | — | No (private) | est. ~$700M |
| **Kollmorgen** | Robotics motors — subsidiary of Regal Rexnord | Parent **NYSE: RRX** | **Yes (via parent)** | Parent ~$6.0B |

### Compute & control

| Company | Role | Ticker | US-listed? | Revenue |
|---|---|---|---|---|
| **Nvidia** | Jetson AI compute modules — dominant in humanoid prototypes | **NASDAQ: NVDA** | **Yes** | ~$130B (FY25) |
| **Qualcomm** | Dragonwing IQ10 humanoid processor; partnerships with Figure AI, Neura | **NASDAQ: QCOM** | **Yes** | ~$39B |
| **Texas Instruments** | Motor control, real-time comms, sensor fusion ICs | **NASDAQ: TXN** | **Yes** | ~$16B |
| **STMicroelectronics** | Motor control + safety logic | **NYSE: STM** | **Yes** | ~$17B |
| **NXP Semiconductors** | Real-time control + safety | **NASDAQ: NXPI** | **Yes** | ~$13B |
| **Infineon Technologies** | Motor control + power | XETRA: IFX | **OTC: IFNNY (ADR)** | ~$16B |
| **Elmo Motion Control** | Servo controllers — Israeli, owned by Bosch Rexroth | — | No (private) | — |
| **Novanta (Celera Motion)** | Real-time motion control + owns ATI Industrial Automation (force/torque sensors) | **NASDAQ: NOVT** | **Yes** | ~$950M |
| **Synapticon** | Servo controllers (German) | — | No (private) | — |

### Sensing — force/torque, tactile

| Company | Role | Ticker | US-listed? | Revenue |
|---|---|---|---|---|
| **ATI Industrial Automation** | 6-axis F/T sensors (owned by Novanta) | via **NASDAQ: NOVT** | **Yes (via parent)** | — |
| **OnRobot** | F/T sensors + end-effectors (Danish, private) | — | No (private) | est. ~$80M |

### Integrated subsystems / "engine-maker" contenders

| Company | Role | Ticker | US-listed? | Revenue |
|---|---|---|---|---|
| **Schaeffler** | Strain-wave actuators; partnerships with Neura, Humanoid, Leju Robotics — 10% group sales target from new sectors by 2035 | XETRA: SHA | **OTC: SCFLF / SHAEF (ADR, illiquid)** | ~$17B |
| **Bosch** | Component supply + motor production deal with Neura Robotics; Boyuan Capital + Galbot JV | — | No (private — Bosch GmbH) | ~$100B |
| **Magna International** | Equity stake in Sanctuary AI; auto-grade manufacturing applied to humanoids | **NYSE: MGA** | **Yes** | ~$42B |
| **Jabil** | Worldwide production partner for Apptronik Apollo | **NYSE: JBL** | **Yes** | ~$28B |
| **SoftBank Group** | $5.4B acquisition of ABB Robotics announced Oct 2025 — "next frontier is physical AI" | TYO: 9984 | **OTC: SFTBY (ADR)** | ~$60B |
| **ABB** | Robotics arm being acquired by SoftBank | **NYSE: ABB** | **Yes** | ~$32B |
| **Midea Group** | Owns Kuka robotics | SHE: 000333 / HKEX: 0300 | No | ~$60B |
| **Amazon** | Acquired Fauna Robotics, Rightbot Technologies, Rivr | **NASDAQ: AMZN** | **Yes** | ~$620B |
| **Regal Rexnord** | Parent of Kollmorgen (motors) | **NYSE: RRX** | **Yes** | ~$6.0B |

### Humanoid OEMs mentioned (context only — not "parts makers")

| Company | Status |
|---|---|
| **Tesla** (Optimus) | **NASDAQ: TSLA** |
| **Boston Dynamics** (Atlas) | Owned by Hyundai Motor (KRX: 005380, ADR OTC: HYMTF) |
| **Apptronik** (Apollo) | Private |
| **Agility Robotics** (Digit) | Private |
| **Figure AI** | Private |
| **Sanctuary AI** | Private (Magna equity) |
| **Unitree Robotics** | Private (China) |
| **Neura Robotics** | Private (Germany) |
| **Galbot** | Private (China; Bosch JV partner) |
| **Leju Robotics** | Private (China) |

---

## What's US-listed and tradeable (quick-pick list)

The cleanest US-listed exposure to McKinsey's named names, grouped by where the bottleneck is most acute:

**High-risk / high-opportunity (precision motion + sensing — the actual chokepoints):**
- **RRX** (Kollmorgen motors via Regal Rexnord) — small parent, big robotics lever
- **NOVT** (ATI 6-axis F/T sensors + Celera Motion control) — pure-play exposure to the most bottlenecked category, $950M revenue
- **SKFRY** (SKF roller screws, bearings — ADR, watch liquidity)
- **THKLY** (THK linear guides — ADR, watch liquidity)
- **HSDDF / NCTKY** (Harmonic Drive Systems / Nabtesco — thin ADRs, basically untradeable for size)

**Compute & control platform contenders (well-traded):**
- **NVDA** — Jetson modules are the de-facto perception compute today
- **QCOM** — Dragonwing IQ10 is the most explicit humanoid-targeted launch
- **TXN, STM, NXPI** — motor control + safety ICs at scale; smaller exposure individually but a basket trade is sensible
- **IFNNY** — Infineon, similar role; ADR

**Subsystem platform / "engine-maker" plays:**
- **MGA** — Magna's Sanctuary AI stake + auto-manufacturing capability transfer
- **JBL** — Jabil as Apptronik's production partner; contract-mfg leverage
- **ABB** — Robotics division being acquired by SoftBank for $5.4B (consolidation signal)
- **SCFLF** — Schaeffler ADR; signed three actuator partnerships in 5 months and targets 10% of group sales from new sectors by 2035

**Battery (lowest bottleneck, lower edge):**
- **PCRFY** — Panasonic ADR; least pure-play but the most liquid US-traded humanoid-battery exposure

**Notable absence from US markets:**
- All of CATL, LG Energy Solution, Samsung SDI, Hiwin, Leaderdrive, Bosch, Maxon, Elmo, Synapticon, OnRobot are either non-US-listed or private. Direct exposure requires foreign brokerage or wait for ADR/derivative offerings.

## Useful trading angles

1. **The "bottleneck = profit pool" trade**: focus on NOVT, RRX, SCFLF — companies sitting in HIGH-RISK component clusters where capacity expansion has long lead times and pricing power should emerge as humanoid volumes grow.
2. **The "platform consolidator" trade**: ABB (SoftBank takeover already announced), MGA, JBL — these are positioning to be the Tier-1 integrators.
3. **The "rare-earth proxy" trade**: not in this report directly, but McKinsey flags the NdFeB magnet 90%-China concentration as a structural risk → MP Materials (NYSE: MP) and Lynas (OTC: LYSCF / ASX) get a tailwind whenever export controls or substitution news hits.
4. **The "compute spec setter" trade**: NVDA + QCOM — QCOM is the more interesting *delta* here since Dragonwing IQ10 is brand-new and humanoid-specific; NVDA already has the position priced in.
5. **The bifurcation trade**: long Chinese hardware (via HK-listed CATL 3300 or A-share access if available) + long US frontier-AI compute (NVDA, QCOM). McKinsey's explicit "bifurcated ecosystem" thesis is the framework.
