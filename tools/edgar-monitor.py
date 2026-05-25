#!/usr/bin/env python3
"""
SEC EDGAR 8-K Earnings Filing Monitor (Schedule-Driven)

Polls EDGAR EFTS for Item 2.02 (Results of Operations) filings,
filters for watchlist companies, sends multi-channel alerts via clawdbot.

Runs on an earnings calendar: fetches the week's schedule from yfinance,
only polls during active earnings windows (15s intervals), and tracks
prices after detection. Sleeps when no earnings are expected.

Usage:
    edgar-monitor.py                  # Single poll cycle
    edgar-monitor.py --daemon         # Schedule-driven daemon
    edgar-monitor.py --refresh-calendar  # Rebuild earnings schedule from yfinance
    edgar-monitor.py --test-schedule  # Show today's windows (dry run)
    edgar-monitor.py --bootstrap      # Rebuild CIK mapping only
    edgar-monitor.py --test           # Dry run with mock data
"""

import json
import logging
import re
import signal
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

try:
    import yfinance as yf
except ImportError:
    yf = None

# ─── PATHS ───────────────────────────────────────────────────────────
CLAWD_DIR = Path.home() / "clawd"
MEMORY_DIR = CLAWD_DIR / "memory"
LOGS_DIR = CLAWD_DIR / "logs"

WATCHLIST_PATH = MEMORY_DIR / "watchlist.json"
THESES_PATH = MEMORY_DIR / "current-theses.json"
CIK_MAP_PATH = MEMORY_DIR / "edgar-cik-map.json"
SEEN_PATH = MEMORY_DIR / "edgar-seen.json"
SCHEDULE_PATH = MEMORY_DIR / "earnings-schedule.json"
LOG_PATH = LOGS_DIR / "edgar-monitor.log"

# ─── SEC ENDPOINTS ───────────────────────────────────────────────────
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
RSS_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
SUBMISSIONS_URL = "https://data.sec.gov/submissions"

_sec_email_path = Path.home() / ".clawdbot/credentials/sec-contact-email"
_sec_email = _sec_email_path.read_text().strip() if _sec_email_path.exists() else "contact@example.com"
USER_AGENT = f"ClaWd-EDGAR-Monitor/1.0 ({_sec_email})"

# ─── ALERT CONFIG ────────────────────────────────────────────────────
DISCORD_CHANNEL = "1469449368603066635"  # #sec-filings
# Loaded from ~/.clawdbot/credentials/ at runtime (not hardcoded)
WHATSAPP_TARGET = Path.home() / ".clawdbot/credentials/whatsapp-target"
WHATSAPP_TARGET = WHATSAPP_TARGET.read_text().strip() if WHATSAPP_TARGET.exists() else ""
TELEGRAM_CHAT_ID = Path.home() / ".clawdbot/credentials/telegram-chat-id"
TELEGRAM_CHAT_ID = TELEGRAM_CHAT_ID.read_text().strip() if TELEGRAM_CHAT_ID.exists() else ""

# Max seen entries to keep (prevents unbounded growth)
MAX_SEEN = 500

ET_TZ = ZoneInfo("America/New_York")

# ─── SCHEDULE CONFIG ────────────────────────────────────────────────
# Polling windows (ET) — only poll EFTS during these hours on earnings days
BMO_WINDOW = (dtime(5, 30), dtime(9, 45))   # Before market open releases
AMC_WINDOW = (dtime(15, 45), dtime(18, 0))  # After market close releases
POLL_INTERVAL = 15       # seconds between EFTS polls during active window
PRICE_TRACK_DURATION = 600  # seconds to track price after filing detected (10 min)
PRICE_TRACK_INTERVAL = 15   # seconds between price checks
SCHEDULE_STALE_DAYS = 3     # refresh calendar if older than this

# ─── LOGGING ─────────────────────────────────────────────────────────
LOGS_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("edgar-monitor")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(LOG_PATH)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(file_handler)

stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(stderr_handler)

# ─── GRACEFUL SHUTDOWN ───────────────────────────────────────────────
_shutdown = False

def _handle_signal(signum, frame):
    global _shutdown
    logger.info(f"Received signal {signum}, shutting down...")
    _shutdown = True

signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# ─── RATE-LIMITED SESSION ────────────────────────────────────────────
class EdgarSession:
    """HTTP session with SEC-compliant rate limiting (10 req/sec)."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        })
        self._last_request = 0.0

    def get(self, url, params=None, timeout=30):
        elapsed = time.time() - self._last_request
        if elapsed < 0.12:  # ~8 req/sec to stay safe
            time.sleep(0.12 - elapsed)
        self._last_request = time.time()
        return self.session.get(url, params=params, timeout=timeout)


# ─── WATCHLIST ───────────────────────────────────────────────────────
def load_watchlist():
    """Load all unique tickers from watchlist.json with category info.

    Returns: {ticker: {"category": str, "weight": float|None}}
    """
    with open(WATCHLIST_PATH) as f:
        data = json.load(f)

    tickers = {}
    stocks = data.get("stocks", {})

    # Holdings first (highest priority)
    for ticker, info in stocks.get("holdings", {}).items():
        weight = info.get("weight")
        tickers[ticker] = {"category": "holding", "weight": weight}

    # Priority
    for ticker in stocks.get("priority", []):
        if ticker not in tickers:
            tickers[ticker] = {"category": "priority", "weight": None}

    # Megacap tech
    for ticker in stocks.get("megacapTech", []):
        if ticker not in tickers:
            tickers[ticker] = {"category": "megacap", "weight": None}

    # AI infrastructure
    for ticker in stocks.get("aiInfrastructure", []):
        if ticker not in tickers:
            tickers[ticker] = {"category": "ai_infra", "weight": None}

    return tickers


def load_theses():
    """Load thesis data for portfolio context."""
    try:
        with open(THESES_PATH) as f:
            data = json.load(f)
        return data.get("theses", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# ─── CIK MAPPING ────────────────────────────────────────────────────
def bootstrap_cik_map(session, watchlist):
    """Fetch SEC ticker-to-CIK mapping and filter for watchlist.

    SEC provides https://www.sec.gov/files/company_tickers.json with structure:
    {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
    """
    logger.info("Bootstrapping CIK map from SEC...")
    resp = session.get(SEC_TICKERS_URL)
    resp.raise_for_status()
    sec_data = resp.json()

    # Build full ticker -> CIK lookup from SEC data
    sec_lookup = {}
    for entry in sec_data.values():
        ticker = entry.get("ticker", "").upper()
        cik = str(entry.get("cik_str", "")).zfill(10)
        name = entry.get("title", "")
        sec_lookup[ticker] = {"cik": cik, "name": name}

    # Filter for our watchlist
    by_ticker = {}
    by_cik = {}
    unmapped = []

    for ticker in watchlist:
        if ticker in sec_lookup:
            info = sec_lookup[ticker]
            by_ticker[ticker] = info
            by_cik[info["cik"]] = ticker
        else:
            unmapped.append(ticker)

    cik_map = {
        "last_updated": datetime.now(ET_TZ).isoformat(),
        "total_mapped": len(by_ticker),
        "total_watchlist": len(watchlist),
        "unmapped": sorted(unmapped),
        "by_ticker": by_ticker,
        "by_cik": by_cik,
    }

    with open(CIK_MAP_PATH, "w") as f:
        json.dump(cik_map, f, indent=2)

    logger.info(
        f"CIK map: {len(by_ticker)}/{len(watchlist)} tickers mapped. "
        f"Unmapped: {unmapped or 'none'}"
    )
    return cik_map


def load_cik_map():
    """Load existing CIK map from disk."""
    try:
        with open(CIK_MAP_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ─── DEDUPLICATION ───────────────────────────────────────────────────
def load_seen():
    try:
        with open(SEEN_PATH) as f:
            data = json.load(f)
        return set(data.get("seen", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_seen(seen):
    # Keep only the most recent entries
    seen_list = sorted(seen)[-MAX_SEEN:]
    data = {
        "seen": seen_list,
        "last_poll": datetime.now(ET_TZ).isoformat(),
        "count": len(seen_list),
    }
    with open(SEEN_PATH, "w") as f:
        json.dump(data, f, indent=2)


# ─── EDGAR POLLING ───────────────────────────────────────────────────
def poll_efts(session, date_str):
    """Poll EDGAR Full-Text Search for today's 8-K Item 2.02 filings.

    EFTS response structure per hit._source:
        ciks: ["0001413329"]
        display_names: ["Philip Morris International Inc.  (PM)  (CIK 0001413329)"]
        adsh: "0001628280-26-005932"
        file_date: "2026-02-06"
        items: ["2.02", "9.01"]
        form: "8-K"

    Returns list of: {accession, cik, company_name, filed_at, filing_url}
    """
    params = {
        "q": '"Item 2.02"',
        "forms": "8-K",
        "dateRange": "custom",
        "startdt": date_str,
        "enddt": date_str,
    }

    try:
        resp = session.get(EFTS_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"EFTS poll failed: {e}")
        return None

    filings = []
    hits = data.get("hits", {}).get("hits", [])

    for hit in hits:
        src = hit.get("_source", {})

        # CIK from ciks array
        ciks = src.get("ciks", [])
        cik = ciks[0] if ciks else "0000000000"

        # Accession number
        accession = src.get("adsh", "")

        # Company name from display_names
        display_names = src.get("display_names", [])
        company_name = display_names[0] if display_names else "Unknown"
        # Clean: "Philip Morris International Inc.  (PM)  (CIK 0001413329)" -> "Philip Morris International Inc."
        name_clean = re.sub(r"\s*\(.*", "", company_name).strip()

        filings.append({
            "accession": accession,
            "cik": cik,
            "company_name": name_clean,
            "filed_at": src.get("file_date", date_str),
            "form_type": src.get("form", "8-K"),
            "items": src.get("items", []),
            "filing_url": build_filing_url(cik, accession),
        })

    return filings


def poll_efts_form(session, date_str, form_type):
    """Poll EFTS for 10-Q or 10-K filings for today."""
    params = {
        "q": "*",
        "forms": form_type,
        "dateRange": "custom",
        "startdt": date_str,
        "enddt": date_str,
    }
    try:
        resp = session.get(EFTS_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.debug(f"EFTS {form_type} poll failed: {e}")
        return []

    filings = []
    for hit in data.get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        ciks = src.get("ciks", [])
        cik = ciks[0] if ciks else "0000000000"
        accession = src.get("adsh", "")
        display_names = src.get("display_names", [])
        company_name = display_names[0] if display_names else "Unknown"
        name_clean = re.sub(r"\s*\(.*", "", company_name).strip()

        filings.append({
            "accession": accession,
            "cik": cik,
            "company_name": name_clean,
            "filed_at": src.get("file_date", date_str),
            "form_type": form_type,
            "items": [],
            "filing_url": build_filing_url(cik, accession),
        })
    return filings


def poll_rss(session):
    """Fallback: Poll SEC RSS atom feed for recent 8-K filings."""
    params = {
        "action": "getcurrent",
        "type": "8-K",
        "dateb": "",
        "owner": "include",
        "count": "40",
        "search_text": "",
        "output": "atom",
    }

    try:
        resp = session.get(RSS_URL, params=params)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"RSS poll failed: {e}")
        return None

    filings = []
    try:
        root = ET.fromstring(resp.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for entry in root.findall("atom:entry", ns):
            title = entry.findtext("atom:title", "", ns)
            link_el = entry.find("atom:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            updated = entry.findtext("atom:updated", "", ns)

            # Extract CIK from title: "8-K - COMPANY NAME (0001234567)"
            cik_match = re.search(r"\((\d{10})\)", title)
            cik = cik_match.group(1) if cik_match else ""

            # Extract company name
            name_match = re.search(r"8-K\s*-\s*(.+?)\s*\(", title)
            company_name = name_match.group(1).strip() if name_match else title

            # Build accession from link URL
            accession = ""
            acc_match = re.search(r"/(\d{10}-\d{2}-\d{6})", link)
            if acc_match:
                accession = acc_match.group(1)

            if cik:
                filings.append({
                    "accession": accession,
                    "cik": cik,
                    "company_name": company_name,
                    "filed_at": updated,
                    "form_type": "8-K",
                    "filing_url": link,
                })
    except ET.ParseError as e:
        logger.warning(f"RSS XML parse failed: {e}")
        return None

    return filings


def build_filing_url(cik, accession):
    """Build SEC filing URL from CIK and accession number."""
    # Remove dashes from accession for URL path
    acc_nodash = accession.replace("-", "")
    cik_int = cik.lstrip("0") or "0"
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{accession}-index.htm"


# ─── FILTERING ───────────────────────────────────────────────────────
def filter_watchlist(filings, cik_map, seen):
    """Filter filings to watchlist companies, exclude already-seen."""
    by_cik = cik_map.get("by_cik", {})
    new_filings = []

    for f in filings:
        if f["accession"] in seen:
            continue
        if f["cik"] in by_cik:
            f["ticker"] = by_cik[f["cik"]]
            new_filings.append(f)

    return new_filings


# ─── AFTER-HOURS PRICE ───────────────────────────────────────────────
def get_ah_price(ticker):
    """Fetch after-hours / current price change for a ticker."""
    if yf is None:
        return None
    try:
        t = yf.Ticker(ticker)
        fi = t.fast_info
        price = fi.last_price
        prev = fi.previous_close
        if price and prev and prev > 0:
            pct = ((price - prev) / prev) * 100
            return {"price": price, "prev_close": prev, "change_pct": pct}
    except Exception:
        pass
    return None


# ─── PRESS RELEASE PARSING ───────────────────────────────────────────
def fetch_press_release(session, filing):
    """Fetch the 8-K filing index and find the press release (ex-99.1)."""
    url = filing.get("filing_url", "")
    if not url:
        return None
    try:
        resp = session.get(url)
        resp.raise_for_status()
        html = resp.text

        # Find exhibit 99.1 link (the press release)
        ex_match = re.search(
            r'href="([^"]*(?:ex|exhibit)[^"]*99[^"]*\.htm[l]?)"',
            html, re.IGNORECASE
        )
        if not ex_match:
            # Try broader: any .htm that's not the 8-K itself
            ex_match = re.search(
                r'href="([^"]*ex99[^"]*\.htm[l]?)"',
                html, re.IGNORECASE
            )
        if not ex_match:
            return None

        ex_path = ex_match.group(1)
        # Build full URL
        if ex_path.startswith("http"):
            ex_url = ex_path
        else:
            base = url.rsplit("/", 1)[0]
            ex_url = f"{base}/{ex_path}"

        resp2 = session.get(ex_url)
        resp2.raise_for_status()
        return resp2.text
    except Exception as e:
        logger.debug(f"Press release fetch failed for {filing.get('ticker','?')}: {e}")
        return None


def parse_earnings_from_pr(pr_text):
    """Extract EPS and revenue from a press release HTML/text.

    Returns: {"eps": float|None, "revenue": float|None, "revenue_unit": str}
    """
    if not pr_text:
        return {}

    # Strip HTML tags for cleaner regex
    text = re.sub(r"<[^>]+>", " ", pr_text)
    text = re.sub(r"\s+", " ", text)

    result = {}

    # EPS patterns
    eps_patterns = [
        r"(?:diluted|GAAP)?\s*(?:earnings|EPS|net income)\s*(?:per\s*(?:diluted\s*)?share)?\s*(?:of|was|were|:)\s*\$\s*([\d]+\.[\d]{2})",
        r"\$\s*([\d]+\.[\d]{2})\s*(?:per\s*(?:diluted\s*)?share)",
        r"(?:EPS|earnings per share)\s*(?:of|:)?\s*\$\s*([\d]+\.[\d]{2})",
    ]
    for pat in eps_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            result["eps"] = float(m.group(1))
            break

    # Revenue patterns
    rev_patterns = [
        r"(?:revenue|net\s*revenue|total\s*revenue|net\s*sales)\s*(?:of|was|were|:)\s*\$\s*([\d,]+(?:\.[\d]+)?)\s*(billion|million|B|M)",
        r"\$\s*([\d,]+(?:\.[\d]+)?)\s*(billion|million|B|M)\s*(?:in|of)?\s*(?:revenue|net\s*revenue|net\s*sales)",
    ]
    for pat in rev_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = float(m.group(1).replace(",", ""))
            unit = m.group(2).lower()
            if unit in ("billion", "b"):
                val *= 1e9
            elif unit in ("million", "m"):
                val *= 1e6
            result["revenue"] = val
            break

    return result


def get_yf_estimates(ticker):
    """Get consensus EPS and revenue estimates from yfinance."""
    if yf is None:
        return {}
    try:
        t = yf.Ticker(ticker)
        # earnings_estimate has: avg, low, high, numberOfAnalysts
        ee = t.earnings_estimate
        re_est = t.revenue_estimate
        result = {}
        if ee is not None and not ee.empty:
            # Current quarter row
            for idx in ee.index:
                if "0q" in str(idx).lower() or "current" in str(idx).lower():
                    result["eps_est"] = ee.loc[idx, "avg"]
                    break
            if "eps_est" not in result and len(ee) > 0:
                result["eps_est"] = ee.iloc[0]["avg"]
        if re_est is not None and not re_est.empty:
            for idx in re_est.index:
                if "0q" in str(idx).lower() or "current" in str(idx).lower():
                    result["rev_est"] = re_est.loc[idx, "avg"]
                    break
            if "rev_est" not in result and len(re_est) > 0:
                result["rev_est"] = re_est.iloc[0]["avg"]
        return result
    except Exception:
        return {}


# ─── ALERT FORMATTING ───────────────────────────────────────────────
def format_alert(filing, watchlist, theses):
    """Format alert message for a detected earnings filing."""
    ticker = filing.get("ticker", "???")
    company = filing.get("company_name", "Unknown")
    filed_at = filing.get("filed_at", "")
    url = filing.get("filing_url", "")

    # Portfolio context
    wl_info = watchlist.get(ticker, {})
    category = wl_info.get("category", "watchlist")
    weight = wl_info.get("weight")

    thesis_info = theses.get(ticker, {})
    status = thesis_info.get("status", "")
    thesis_text = thesis_info.get("thesis", "")

    # Category label
    cat_labels = {
        "holding": "HOLDING",
        "priority": "PRIORITY",
        "megacap": "MEGACAP",
        "ai_infra": "AI INFRA",
    }
    cat_label = cat_labels.get(category, "WATCHLIST")

    # Determine form description
    form_type = filing.get("form_type", "8-K")
    items = filing.get("items", [])
    if form_type == "10-Q":
        form_desc = "Form 10-Q -- Quarterly Report"
        label = "10-Q FILED"
    elif form_type == "10-K":
        form_desc = "Form 10-K -- Annual Report"
        label = "10-K FILED"
    else:
        form_desc = "Form 8-K | Item 2.02 -- Results of Operations"
        label = "8-K FILED"

    lines = [
        f"**{ticker} {label}**",
        "",
        form_desc,
        f"Filed: {filed_at}",
        url,
        company,
    ]

    # After-hours price
    ah = filing.get("ah_price")
    if ah:
        direction = "+" if ah["change_pct"] >= 0 else ""
        lines.append(f"Price: ${ah['price']:.2f} ({direction}{ah['change_pct']:.1f}%)")

    # Earnings data (from press release parsing)
    earnings = filing.get("earnings", {})
    estimates = filing.get("estimates", {})
    if earnings.get("eps") is not None:
        eps = earnings["eps"]
        eps_line = f"EPS: ${eps:.2f}"
        if estimates.get("eps_est"):
            est = estimates["eps_est"]
            beat_pct = ((eps - est) / abs(est)) * 100 if est else 0
            emoji = "BEAT" if beat_pct > 0 else "MISS" if beat_pct < 0 else "IN-LINE"
            eps_line += f" vs ${est:.2f} est ({emoji} {beat_pct:+.1f}%)"
        lines.append(eps_line)
    if earnings.get("revenue") is not None:
        rev = earnings["revenue"]
        if rev >= 1e9:
            rev_str = f"${rev/1e9:.2f}B"
        else:
            rev_str = f"${rev/1e6:.0f}M"
        rev_line = f"Rev: {rev_str}"
        if estimates.get("rev_est"):
            est = estimates["rev_est"]
            if est >= 1e9:
                est_str = f"${est/1e9:.2f}B"
            else:
                est_str = f"${est/1e6:.0f}M"
            beat_pct = ((rev - est) / abs(est)) * 100 if est else 0
            emoji = "BEAT" if beat_pct > 0 else "MISS" if beat_pct < 0 else "IN-LINE"
            rev_line += f" vs {est_str} est ({emoji} {beat_pct:+.1f}%)"
        lines.append(rev_line)

    # Portfolio context line
    ctx_parts = [cat_label]
    if weight:
        ctx_parts[0] += f" ({weight}%)"
    if status:
        ctx_parts.append(status)
    lines.append("")
    lines.append(" | ".join(ctx_parts))

    if thesis_text:
        lines.append(f"Thesis: {thesis_text[:120]}")

    return "\n".join(lines)


# ─── ALERT DELIVERY ─────────────────────────────────────────────────
def send_clawdbot(channel, target, message):
    """Send a message via clawdbot CLI."""
    cmd = [
        "clawdbot", "message", "send",
        "--channel", channel,
        "--target", target,
        "--message", message,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.warning(f"clawdbot send to {channel} failed: {result.stderr.strip()}")
            return False
        return True
    except Exception as e:
        logger.warning(f"clawdbot send to {channel} error: {e}")
        return False


def send_alert(message, ticker, category):
    """Send alert to appropriate channels based on category."""
    channels_sent = ["discord"]

    # Discord: all filings
    send_clawdbot("discord", f"channel:{DISCORD_CHANNEL}", message)

    # Telegram: all filings (if chat ID configured)
    if TELEGRAM_CHAT_ID:
        send_clawdbot("telegram", TELEGRAM_CHAT_ID, message)
        channels_sent.append("telegram")

    # WhatsApp: holdings and priority only (avoid notification fatigue)
    if category in ("holding", "priority"):
        send_clawdbot("whatsapp", WHATSAPP_TARGET, message)
        channels_sent.append("whatsapp")

    logger.info(f"Alert sent: {ticker} -> {'+'.join(channels_sent)}")


# ─── POLL CYCLE ──────────────────────────────────────────────────────
def run_cycle(session, cik_map, watchlist, theses, seen):
    """Execute one polling cycle. Returns list of new filings alerted."""
    now_et = datetime.now(ET_TZ)
    date_str = now_et.strftime("%Y-%m-%d")

    # Try EFTS first for 8-K Item 2.02
    filings = poll_efts(session, date_str)
    source = "efts"

    # Fall back to RSS if EFTS fails
    if filings is None:
        filings = poll_rss(session)
        source = "rss"

    if filings is None:
        logger.warning("Both EFTS and RSS failed this cycle")
        return []

    # Also check for 10-Q and 10-K filings
    for form in ("10-Q", "10-K"):
        extra = poll_efts_form(session, date_str, form)
        if extra:
            filings.extend(extra)

    # Filter for watchlist + deduplicate
    new_filings = filter_watchlist(filings, cik_map, seen)

    if not new_filings:
        logger.info(
            f"Poll ({source}): {len(filings)} total 8-K filings today, "
            f"0 new watchlist matches"
        )
        return []

    logger.info(
        f"Poll ({source}): {len(new_filings)} NEW watchlist filing(s) detected!"
    )

    # Process each new filing
    for filing in new_filings:
        ticker = filing["ticker"]
        category = watchlist.get(ticker, {}).get("category", "watchlist")

        # Enrich with after-hours price
        ah = get_ah_price(ticker)
        if ah:
            filing["ah_price"] = ah

        # Enrich with press release earnings (8-K only)
        if filing.get("form_type") == "8-K":
            pr_text = fetch_press_release(session, filing)
            if pr_text:
                earnings = parse_earnings_from_pr(pr_text)
                if earnings:
                    filing["earnings"] = earnings
                    filing["estimates"] = get_yf_estimates(ticker)

        message = format_alert(filing, watchlist, theses)
        send_alert(message, ticker, category)

        # Spawn Dexter deep analysis asynchronously (don't block poll loop)
        if filing.get("earnings"):
            try:
                e = filing["earnings"]
                est = filing.get("estimates", {})
                data_parts = []
                if e.get("eps"):
                    data_parts.append(f"EPS:{e['eps']}")
                if e.get("revenue"):
                    data_parts.append(f"REV:{e['revenue']}")
                if est.get("eps_est"):
                    data_parts.append(f"EST_EPS:{est['eps_est']}")
                if est.get("rev_est"):
                    data_parts.append(f"EST_REV:{est['rev_est']}")
                data_str = ",".join(data_parts) if data_parts else "no parsed data"
                import subprocess as _sp
                _sp.Popen(
                    [str(Path.home() / "clawd/tools/earnings-deep-analysis.sh"),
                     ticker, data_str, category],
                    stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                )
                logger.info(f"Spawned deep analysis for {ticker}")
            except Exception as ex:
                logger.warning(f"Failed to spawn deep analysis for {ticker}: {ex}")

        seen.add(filing["accession"])

    save_seen(seen)
    return new_filings


# ─── EARNINGS SCHEDULE ──────────────────────────────────────────────
def refresh_earnings_calendar(watchlist):
    """Fetch upcoming earnings dates for all watchlist tickers via yfinance.

    Writes earnings-schedule.json grouped by date with BMO/AMC classification.
    Called weekly (Sunday 8 PM ET) or when schedule is stale.
    """
    if yf is None:
        logger.error("yfinance not available — cannot refresh calendar")
        return None

    logger.info(f"Refreshing earnings calendar for {len(watchlist)} tickers...")
    by_date = {}
    errors = []

    for ticker, wl_info in watchlist.items():
        try:
            t = yf.Ticker(ticker)
            ed = t.earnings_dates
            if ed is None or ed.empty:
                continue

            # Find the next upcoming earnings date (where Reported EPS is NaN)
            now_et = datetime.now(ET_TZ)
            for idx in ed.index:
                # Convert index to datetime with timezone
                if hasattr(idx, 'tzinfo') and idx.tzinfo is not None:
                    dt = idx.to_pydatetime()
                else:
                    dt = idx.to_pydatetime().replace(tzinfo=ET_TZ)

                # Must be in the future (or today)
                if dt.date() < now_et.date():
                    continue

                # Check if this is unreported (NaN Reported EPS)
                row = ed.loc[idx]
                reported = row.get("Reported EPS")
                if reported is not None and not (isinstance(reported, float) and reported != reported):
                    continue  # Already reported

                date_str = dt.strftime("%Y-%m-%d")
                hour = dt.hour

                # Classify timing: before noon = BMO, after = AMC
                if hour < 12:
                    timing = "BMO"
                else:
                    timing = "AMC"

                entry = {
                    "ticker": ticker,
                    "timing": timing,
                    "category": wl_info.get("category", "watchlist"),
                    "weight": wl_info.get("weight"),
                    "raw_time": dt.strftime("%H:%M"),
                }

                if date_str not in by_date:
                    by_date[date_str] = []
                by_date[date_str].append(entry)
                break  # Only take the next upcoming date

            # Rate limit: be gentle with yfinance
            time.sleep(0.3)

        except Exception as e:
            errors.append(ticker)
            logger.debug(f"Calendar fetch failed for {ticker}: {e}")

    # Find the next earnings date
    future_dates = sorted(d for d in by_date if d >= now_et.strftime("%Y-%m-%d"))
    next_earnings = future_dates[0] if future_dates else None

    schedule = {
        "last_refreshed": datetime.now(ET_TZ).isoformat(),
        "refresh_source": "yfinance",
        "by_date": dict(sorted(by_date.items())),
        "next_earnings": next_earnings,
        "total_scheduled": sum(len(v) for v in by_date.values()),
        "errors": errors,
    }

    with open(SCHEDULE_PATH, "w") as f:
        json.dump(schedule, f, indent=2)

    logger.info(
        f"Earnings calendar refreshed: {schedule['total_scheduled']} earnings across "
        f"{len(by_date)} dates. Next: {next_earnings}. Errors: {len(errors)}"
    )
    return schedule


def load_schedule():
    """Load earnings schedule from disk."""
    try:
        with open(SCHEDULE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def schedule_is_stale(schedule):
    """Check if the schedule needs refreshing."""
    if schedule is None:
        return True
    try:
        refreshed = datetime.fromisoformat(schedule.get("last_refreshed", "2000-01-01"))
        age_days = (datetime.now(ET_TZ) - refreshed).days
        return age_days >= SCHEDULE_STALE_DAYS
    except (ValueError, TypeError):
        return True


def get_todays_windows(schedule):
    """Compute polling windows for today based on the earnings schedule.

    Returns list of (window_start_dt, window_end_dt, [tickers]) for today.
    Empty list if no earnings today.
    """
    if schedule is None:
        return []

    now_et = datetime.now(ET_TZ)
    today_str = now_et.strftime("%Y-%m-%d")

    # Check weekends — no earnings
    if now_et.weekday() >= 5:
        return []

    todays_earnings = schedule.get("by_date", {}).get(today_str, [])
    if not todays_earnings:
        return []

    # Group by timing
    bmo_tickers = [e["ticker"] for e in todays_earnings if e.get("timing") == "BMO"]
    amc_tickers = [e["ticker"] for e in todays_earnings if e.get("timing") == "AMC"]
    tbd_tickers = [e["ticker"] for e in todays_earnings if e.get("timing") not in ("BMO", "AMC")]

    windows = []
    today = now_et.date()

    if bmo_tickers or tbd_tickers:
        start = datetime.combine(today, BMO_WINDOW[0], tzinfo=ET_TZ)
        end = datetime.combine(today, BMO_WINDOW[1], tzinfo=ET_TZ)
        windows.append((start, end, bmo_tickers + tbd_tickers))

    if amc_tickers or tbd_tickers:
        start = datetime.combine(today, AMC_WINDOW[0], tzinfo=ET_TZ)
        end = datetime.combine(today, AMC_WINDOW[1], tzinfo=ET_TZ)
        windows.append((start, end, amc_tickers + tbd_tickers))

    return windows


def find_active_window(windows):
    """Find the currently active polling window, if any."""
    now_et = datetime.now(ET_TZ)
    for start, end, tickers in windows:
        if start <= now_et <= end:
            return (start, end, tickers)
    return None


def next_window_start(windows):
    """Find the next window that hasn't ended yet."""
    now_et = datetime.now(ET_TZ)
    for start, end, tickers in windows:
        if now_et < start:
            return start
    return None


def sleep_until_interruptible(target_dt):
    """Sleep until target datetime, waking every 5s to check for shutdown."""
    while not _shutdown:
        now = datetime.now(ET_TZ)
        remaining = (target_dt - now).total_seconds()
        if remaining <= 0:
            break
        # Sleep in 5-second increments for SIGTERM responsiveness
        time.sleep(min(5, remaining))


def track_prices_background(tickers, watchlist):
    """Track prices for detected tickers in a background thread.

    Polls every 15s for 10 minutes, then sends a summary alert.
    """
    def _track():
        logger.info(f"Price tracking started for {tickers} ({PRICE_TRACK_DURATION}s)")
        snapshots = {t: [] for t in tickers}
        start = time.time()

        while time.time() - start < PRICE_TRACK_DURATION and not _shutdown:
            for ticker in tickers:
                ah = get_ah_price(ticker)
                if ah:
                    snapshots[ticker].append({
                        "time": datetime.now(ET_TZ).strftime("%H:%M:%S"),
                        "price": ah["price"],
                        "change_pct": ah["change_pct"],
                    })
            time.sleep(PRICE_TRACK_INTERVAL)

        # Send price movement summary
        for ticker in tickers:
            snaps = snapshots[ticker]
            if len(snaps) < 2:
                continue
            first = snaps[0]
            last = snaps[-1]
            category = watchlist.get(ticker, {}).get("category", "watchlist")

            # Only alert if meaningful movement (>0.5%)
            move = last["change_pct"] - first["change_pct"]
            if abs(move) < 0.5:
                continue

            direction = "+" if last["change_pct"] >= 0 else ""
            msg = (
                f"**{ticker} POST-EARNINGS MOVE**\n"
                f"${last['price']:.2f} ({direction}{last['change_pct']:.1f}% vs prev close)\n"
                f"Movement since filing: {move:+.1f}pp over {len(snaps)} checks"
            )
            send_clawdbot("discord", f"channel:{DISCORD_CHANNEL}", msg)
            if category in ("holding", "priority"):
                send_clawdbot("whatsapp", WHATSAPP_TARGET, msg)

        logger.info(f"Price tracking complete for {tickers}")

    thread = threading.Thread(target=_track, daemon=True)
    thread.start()


# ─── MAIN ────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]
    mode = "single"

    if "--daemon" in args:
        mode = "daemon"
    elif "--refresh-calendar" in args:
        mode = "refresh-calendar"
    elif "--test-schedule" in args:
        mode = "test-schedule"
    elif "--bootstrap" in args:
        mode = "bootstrap"
    elif "--test" in args:
        mode = "test"
    elif "--get-telegram-id" in args:
        # Helper to find Telegram chat ID after user messages bot
        tg_cfg = Path.home() / ".clawdbot/credentials/telegram-jiivebot.json"
        token = json.loads(tg_cfg.read_text()).get("apiToken", "")
        if not token:
            print("Error: set bot_token in ~/.clawdbot/credentials/telegram-jiivebot.json")
            sys.exit(1)
        resp = requests.get(f"https://api.telegram.org/bot{token}/getUpdates")
        data = resp.json()
        if data.get("result"):
            for update in data["result"][-5:]:
                msg = update.get("message", {})
                chat = msg.get("chat", {})
                print(f"Chat ID: {chat.get('id')} | "
                      f"User: {chat.get('first_name', '')} @{chat.get('username', '')} | "
                      f"Text: {msg.get('text', '')[:50]}")
            print("\nSet TELEGRAM_CHAT_ID in edgar-monitor.py to the chat ID above.")
        else:
            print("No messages yet. Send /start to @Jiivebot on Telegram first.")
        return

    # ── Refresh calendar mode ──
    if mode == "refresh-calendar":
        watchlist = load_watchlist()
        schedule = refresh_earnings_calendar(watchlist)
        if schedule:
            print(f"Earnings calendar refreshed: {schedule['total_scheduled']} earnings")
            print(f"Next earnings: {schedule['next_earnings']}")
            dates = schedule.get("by_date", {})
            for date_str in sorted(dates)[:14]:  # Show next 2 weeks
                tickers = [e['ticker'] for e in dates[date_str]]
                timings = [e.get('timing', 'TBD') for e in dates[date_str]]
                print(f"  {date_str}: {', '.join(f'{t}({tm})' for t, tm in zip(tickers, timings))}")
            if schedule.get("errors"):
                print(f"Errors ({len(schedule['errors'])}): {', '.join(schedule['errors'][:10])}")
        else:
            print("Failed to refresh calendar (yfinance not available?)")
        return

    # ── Test schedule mode ──
    if mode == "test-schedule":
        schedule = load_schedule()
        if schedule is None:
            print("No schedule found. Run --refresh-calendar first.")
            return

        print(f"Schedule refreshed: {schedule.get('last_refreshed', '?')}")
        print(f"Total scheduled: {schedule.get('total_scheduled', 0)}")
        print(f"Next earnings: {schedule.get('next_earnings', 'none')}")
        stale = schedule_is_stale(schedule)
        print(f"Stale: {stale}")

        windows = get_todays_windows(schedule)
        now_et = datetime.now(ET_TZ)
        print(f"\nToday ({now_et.strftime('%Y-%m-%d %A')}):")

        if not windows:
            print("  No earnings windows today.")
        else:
            for start, end, tickers in windows:
                active = start <= now_et <= end
                status = " <-- ACTIVE" if active else ""
                print(f"  {start.strftime('%H:%M')}-{end.strftime('%H:%M')} ET: "
                      f"{', '.join(tickers)}{status}")

        active = find_active_window(windows)
        if active:
            print(f"\nCurrently in active window. Would poll every {POLL_INTERVAL}s.")
        else:
            nxt = next_window_start(windows)
            if nxt:
                delta = nxt - now_et
                mins = int(delta.total_seconds() / 60)
                print(f"\nNext window in {mins} min ({nxt.strftime('%H:%M ET')})")
            else:
                tomorrow_5am = datetime.combine(
                    now_et.date() + timedelta(days=1), dtime(5, 0), tzinfo=ET_TZ
                )
                delta = tomorrow_5am - now_et
                hrs = delta.total_seconds() / 3600
                print(f"\nAll windows done. Would sleep {hrs:.1f}h until tomorrow 5:00 AM ET.")

        # Show upcoming week
        print("\nUpcoming:")
        dates = schedule.get("by_date", {})
        shown = 0
        for date_str in sorted(dates):
            if date_str >= now_et.strftime("%Y-%m-%d") and shown < 10:
                tickers = [e['ticker'] for e in dates[date_str]]
                timings = [e.get('timing', 'TBD') for e in dates[date_str]]
                print(f"  {date_str}: {', '.join(f'{t}({tm})' for t, tm in zip(tickers, timings))}")
                shown += 1
        return

    session = EdgarSession()
    watchlist = load_watchlist()
    theses = load_theses()

    # Bootstrap CIK map if needed
    cik_map = load_cik_map()
    if cik_map is None or mode == "bootstrap":
        cik_map = bootstrap_cik_map(session, watchlist)
        if mode == "bootstrap":
            print(f"CIK map built: {cik_map['total_mapped']}/{cik_map['total_watchlist']} mapped")
            if cik_map["unmapped"]:
                print(f"Unmapped: {', '.join(cik_map['unmapped'])}")
            return

    # Refresh CIK map if stale (>7 days old)
    try:
        last_updated = datetime.fromisoformat(cik_map.get("last_updated", "2000-01-01"))
        if (datetime.now(ET_TZ) - last_updated.replace(tzinfo=ET_TZ)).days > 7:
            logger.info("CIK map stale (>7 days), refreshing...")
            cik_map = bootstrap_cik_map(session, watchlist)
    except (ValueError, TypeError):
        cik_map = bootstrap_cik_map(session, watchlist)

    seen = load_seen()

    if mode == "test":
        # Mock test with fake filing
        mock_filing = {
            "accession": "0000000000-00-000000",
            "cik": cik_map["by_ticker"].get("NVDA", {}).get("cik", "0001045810"),
            "company_name": "NVIDIA CORP",
            "filed_at": datetime.now(ET_TZ).strftime("%Y-%m-%d %I:%M %p ET"),
            "form_type": "8-K",
            "filing_url": "https://www.sec.gov/Archives/edgar/data/1045810/000000000000000000/test-index.htm",
            "ticker": "NVDA",
        }
        msg = format_alert(mock_filing, watchlist, theses)
        print("=== TEST ALERT ===")
        print(msg)
        print("==================")
        print(f"\nWatchlist: {len(watchlist)} tickers")
        print(f"CIK mapped: {cik_map['total_mapped']}")
        print(f"Seen filings: {len(seen)}")
        return

    if mode == "single":
        new = run_cycle(session, cik_map, watchlist, theses, seen)
        sys.exit(1 if new else 0)

    # ── Schedule-driven daemon mode ──
    logger.info(
        f"EDGAR monitor daemon starting (schedule-driven). "
        f"Watching {cik_map['total_mapped']} companies. "
        f"Seen: {len(seen)} filings."
    )

    # Ensure we have a schedule
    schedule = load_schedule()
    if schedule_is_stale(schedule):
        logger.info("Earnings schedule stale or missing, refreshing...")
        schedule = refresh_earnings_calendar(watchlist)

    cycle_count = 0
    last_schedule_check = time.time()

    while not _shutdown:
        now_et = datetime.now(ET_TZ)

        # Refresh schedule periodically (check staleness every 6 hours)
        if time.time() - last_schedule_check > 21600:  # 6 hours
            last_schedule_check = time.time()
            if schedule_is_stale(schedule):
                logger.info("Schedule stale, refreshing...")
                schedule = refresh_earnings_calendar(watchlist)

        # Get today's windows
        windows = get_todays_windows(schedule)

        if not windows:
            # No earnings today — sleep until tomorrow 5:00 AM ET
            tomorrow_5am = datetime.combine(
                now_et.date() + timedelta(days=1), dtime(5, 0), tzinfo=ET_TZ
            )
            logger.info(
                f"No earnings today ({now_et.strftime('%A %Y-%m-%d')}). "
                f"Sleeping until {tomorrow_5am.strftime('%Y-%m-%d %H:%M ET')}."
            )
            sleep_until_interruptible(tomorrow_5am)
            continue

        # Check if we're in an active window
        active = find_active_window(windows)

        if active:
            start, end, tickers = active
            cycle_count += 1

            try:
                new_filings = run_cycle(session, cik_map, watchlist, theses, seen)
                if new_filings:
                    logger.info(f"Cycle #{cycle_count}: {len(new_filings)} alerts sent")
                    # Start background price tracking for detected tickers
                    detected_tickers = [f["ticker"] for f in new_filings]
                    track_prices_background(detected_tickers, watchlist)
            except Exception as e:
                logger.error(f"Cycle #{cycle_count} error: {e}")

            # Sleep 15 seconds before next poll
            sleep_end = time.time() + POLL_INTERVAL
            while time.time() < sleep_end and not _shutdown:
                time.sleep(1)

        else:
            # Not in a window — find next one
            nxt = next_window_start(windows)
            if nxt:
                delta = nxt - now_et
                mins = int(delta.total_seconds() / 60)
                logger.info(
                    f"Between windows. Next: {nxt.strftime('%H:%M ET')} "
                    f"({mins} min). Sleeping..."
                )
                sleep_until_interruptible(nxt)
            else:
                # All windows done today — sleep until tomorrow
                tomorrow_5am = datetime.combine(
                    now_et.date() + timedelta(days=1), dtime(5, 0), tzinfo=ET_TZ
                )
                logger.info(
                    f"All windows done for today. "
                    f"Sleeping until {tomorrow_5am.strftime('%Y-%m-%d %H:%M ET')}."
                )
                sleep_until_interruptible(tomorrow_5am)

    logger.info("EDGAR monitor daemon stopped.")


if __name__ == "__main__":
    main()
