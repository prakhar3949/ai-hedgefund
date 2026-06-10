"""
sector-cycle-backtest.py — Which sectors / commodities win across Fed hiking cycles, and how does
leadership flip between INFLATION-driven, GROWTH-driven, and SUPPLY/CAPEX-driven cycles?

Total-return performance across the phases of SIX Fed cycles (1988→2023):
  PRICING-IN (≈12mo pre-liftoff) / HIKING (liftoff→terminal) / PLATEAU (liftoff→1st cut).

Two data eras (sector ETFs didn't exist before Dec-1998):
  MODERN (1999+): 11 GICS sector SPDRs + futures/GSCI commodity basket + SPY/TLT/KRE.
  LEGACY (pre-1999): Fidelity Select sector funds (NAV total return, since 1986) as sector proxies
                     + FSAGX gold-fund as the real-asset tell + ^GSPC/^IXIC/^DJI context.
  Legacy sector proxies are approximations (FSCHX=chemicals≈materials, FSDAX=defense≈industrials,
  FSRPX=retail≈discretionary); no Comm-Svcs/Real-Estate/broad-commodity proxy pre-1999.

Data: Yahoo chart API adjusted close. No key. NB: front-month futures = price return (excl roll).
"""
from __future__ import annotations
import sys, time
import requests
from datetime import datetime, timezone

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ── Modern universe (1999+) ───────────────────────────────────────────────────
MOD_SECTORS = {
    "XLE": "Energy", "XLF": "Financials", "XLK": "Technology", "XLV": "Health Care",
    "XLI": "Industrials", "XLP": "Cons Staples", "XLY": "Cons Discr", "XLU": "Utilities",
    "XLC": "Comm Svcs", "XLB": "Materials", "XLRE": "Real Estate",
}
MOD_COMMOD = {
    "^SPGSCI": "Broad (GSCI)", "CL=F": "Crude Oil", "HG=F": "Copper",
    "GC=F": "Gold", "SI=F": "Silver",
}
MOD_CONTEXT = {"SPY": "S&P 500", "TLT": "20Y Treasuries", "KRE": "Regional Banks"}

# ── Legacy universe (pre-1999): Fidelity Select sector funds + indices ─────────
LEG_SECTORS = {
    "FSENX": "Energy", "FIDSX": "Financials", "FSPTX": "Technology", "FSPHX": "Health Care",
    "FSDAX": "Industrials*", "FDFAX": "Cons Staples", "FSRPX": "Cons Discr*", "FSUTX": "Utilities",
    "FSCHX": "Materials*",
}
LEG_COMMOD = {"FSAGX": "Gold (miners)"}
LEG_CONTEXT = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq (growth)", "^DJI": "Dow"}

# ── Cycles (chronological). u = universe era; note = caveat. ───────────────────
CYCLES = {
    "1988-1989  (post-'87-crash, hiking into strong economy)": {
        "u": "legacy", "note": "PRICING-IN window contains the Oct-1987 crash",
        "w": {"PRICING-IN": ("1987-03-30", "1988-03-30"),
              "HIKING":     ("1988-03-30", "1989-02-24"),
              "PLATEAU":    ("1988-03-30", "1989-06-05")},
    },
    "1994-1995  (preemptive 'bond massacre', metals uptick)": {
        "u": "legacy", "note": "",
        "w": {"PRICING-IN": ("1993-02-04", "1994-02-04"),
              "HIKING":     ("1994-02-04", "1995-02-01"),
              "PLATEAU":    ("1994-02-04", "1995-07-06")},
    },
    "1999-2000  (LATE-CYCLE, hiking into the dot-com bubble)": {
        "u": "modern", "note": "PRICING-IN ~6mo (from SPDR inception); futures n/a pre-2000",
        "w": {"PRICING-IN": ("1998-12-22", "1999-06-30"),
              "HIKING":     ("1999-06-30", "2000-05-16"),
              "PLATEAU":    ("1999-06-30", "2001-01-03")},
    },
    "2004-2006  (SUPPLY/CHINA-demand, capex+commodity boom)": {
        "u": "modern", "note": "",
        "w": {"PRICING-IN": ("2003-06-30", "2004-06-30"),
              "HIKING":     ("2004-06-30", "2006-06-29"),
              "PLATEAU":    ("2004-06-30", "2007-09-18")},
    },
    "2015-2018  (GROWTH-driven, disinflationary)": {
        "u": "modern", "note": "",
        "w": {"PRICING-IN": ("2014-12-16", "2015-12-16"),
              "HIKING":     ("2015-12-16", "2018-12-19"),
              "PLATEAU":    ("2015-12-16", "2019-07-31")},
    },
    "2021-2023  (INFLATION-driven, supply shock)": {
        "u": "modern", "note": "",
        "w": {"PRICING-IN": ("2021-03-16", "2022-03-16"),
              "HIKING":     ("2022-03-16", "2023-07-26"),
              "PLATEAU":    ("2022-03-16", "2024-09-18")},
    },
}

UNIVERSES = {
    "modern": (MOD_SECTORS, MOD_COMMOD, MOD_CONTEXT),
    "legacy": (LEG_SECTORS, LEG_COMMOD, LEG_CONTEXT),
}


def all_tickers() -> dict:
    out = {}
    for s, c, x in UNIVERSES.values():
        out.update(s); out.update(c); out.update(x)
    return out


def ts(d: str) -> int:
    return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def years_between(a: str, b: str) -> float:
    return (ts(b) - ts(a)) / (365.25 * 86400)


def fetch(ticker: str):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={ts('1986-01-01')}&period2={ts('2025-01-01')}&interval=1d&events=div")
    res = requests.get(url, headers=HEADERS, timeout=20).json()["chart"]["result"][0]
    t = res["timestamp"]
    ind = res["indicators"]
    adj = (ind.get("adjclose", [{}])[0].get("adjclose") if ind.get("adjclose") else None) \
        or ind["quote"][0]["close"]
    out_t, out_a = [], []
    for ti, ai in zip(t, adj):
        if ai is not None:
            out_t.append(ti); out_a.append(ai)
    return out_t, out_a


def price_on(t, a, date, mode="after"):
    target = ts(date)
    if mode == "after":
        for ti, ai in zip(t, a):
            if ti >= target:
                return ai
    else:
        last = None
        for ti, ai in zip(t, a):
            if ti <= target:
                last = ai
            else:
                break
        return last
    return None


def window_ret(t, a, start, end):
    if not t or t[0] > ts(start) + 45 * 86400:   # coverage guard (no mid-window launches)
        return None
    p0, p1 = price_on(t, a, start, "after"), price_on(t, a, end, "before")
    return (p1 / p0 - 1) * 100 if (p0 and p1) else None


def main():
    universe = all_tickers()
    data = {}
    for tk in universe:
        try:
            data[tk] = fetch(tk)
        except Exception as e:
            print(f"  {tk}: {e}", file=sys.stderr)
        time.sleep(0.2)

    for cycle, cfg in CYCLES.items():
        windows = cfg["w"]
        sectors, commod, context = UNIVERSES[cfg["u"]]
        rets = {tk: {w: window_ret(*data[tk], *r) for w, r in windows.items()}
                for tk in data if tk in data}
        dur = {w: years_between(*r) for w, r in windows.items()}

        print("\n" + "═" * 62)
        print(f"  {cycle}")
        print(f"  windows: " + " | ".join(f"{w} {dur[w]:.1f}y" for w in windows)
              + (f"   [{cfg['note']}]" if cfg["note"] else ""))
        print("═" * 62)

        def block(title, label_map):
            print(f"\n{title}")
            print(f"{'':<18}" + "".join(f"{w:>13}" for w in windows))
            print("-" * 58)
            for tk, nm in label_map.items():
                cells = "".join(
                    f"{f'{rets[tk][w]:+.0f}%' if rets.get(tk, {}).get(w) is not None else 'n/a':>13}"
                    for w in windows)
                print(f"{tk+' '+nm:<18}{cells}")

        kind = "(Fidelity Select fund proxies)" if cfg["u"] == "legacy" else "(GICS sector SPDRs)"
        block(f"SECTORS {kind}", sectors)
        block("COMMODITIES / REAL ASSETS", commod)
        block("CONTEXT", context)

        pool = list(sectors) + list(commod)
        print("\nLEADERBOARD (sectors + real assets):")
        for w in windows:
            ranked = sorted([(tk, rets[tk][w]) for tk in pool if rets.get(tk, {}).get(w) is not None],
                            key=lambda x: x[1], reverse=True)
            top = "  ".join(f"{universe[tk]} {v:+.0f}%" for tk, v in ranked[:4])
            bot = "  ".join(f"{universe[tk]} {v:+.0f}%" for tk, v in ranked[-3:])
            print(f"  {w:<11} WIN: {top}   |  LAG: {bot}")


if __name__ == "__main__":
    main()
