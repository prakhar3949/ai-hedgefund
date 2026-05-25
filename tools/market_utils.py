#!/usr/bin/env python3
"""
Market Utilities - Reusable functions for stock data
Eliminates duplication across scripts
"""

import yfinance as yf
from typing import Dict, List, Optional, Tuple
import json
import sys
from pathlib import Path
import re
import requests

# ── Yahoo quoteSummary session + crumb (shared across tools) ─────────────────
# Yahoo's v10/quoteSummary endpoint now returns 401 "Invalid Crumb" without a
# session cookie + crumb token. Bootstrap once per process and reuse.

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

_YAHOO_SESSION: Optional[requests.Session] = None
_YAHOO_CRUMB: Optional[str] = None


def get_yahoo_session() -> Tuple[Optional[requests.Session], Optional[str]]:
    """Return a (Session, crumb) pair authenticated with Yahoo Finance.

    Caches across calls within the process. Returns (None, None) on failure.
    """
    global _YAHOO_SESSION, _YAHOO_CRUMB
    if _YAHOO_SESSION is not None and _YAHOO_CRUMB:
        return _YAHOO_SESSION, _YAHOO_CRUMB
    s = requests.Session()
    s.headers.update(YAHOO_HEADERS)
    try:
        s.get("https://fc.yahoo.com", timeout=10, allow_redirects=True)
        s.get("https://finance.yahoo.com/quote/AAPL", timeout=10)
        r = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10)
        if r.status_code == 200 and r.text and "<" not in r.text:
            _YAHOO_SESSION = s
            _YAHOO_CRUMB = r.text.strip()
            return _YAHOO_SESSION, _YAHOO_CRUMB
    except Exception as e:
        print(f"  yahoo crumb err: {e}", file=sys.stderr)
    return None, None


def yahoo_quote_summary(ticker: str, modules: str, timeout: int = 20) -> Optional[dict]:
    """Fetch Yahoo quoteSummary result[0] for ticker. Handles crumb + retries."""
    yt = ticker.replace(".", "-")
    sess, crumb = get_yahoo_session()
    if not sess:
        return None
    url = (f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{yt}"
           f"?modules={modules}&crumb={crumb}")
    for attempt in range(2):
        try:
            r = sess.get(url, timeout=timeout)
            if r.status_code == 429:
                if attempt == 0:
                    import time; time.sleep(5); continue
                return None
            if r.status_code != 200:
                return None
            res = r.json().get("quoteSummary", {}).get("result", [])
            return res[0] if res else None
        except Exception as e:
            if attempt == 0:
                import time; time.sleep(2); continue
            print(f"  yahoo_quote_summary({ticker}): {e}", file=sys.stderr)
            return None
    return None

def format_market_cap(cap: float) -> str:
    """Format market cap with appropriate suffix"""
    if cap >= 1e12:
        return f'${cap/1e12:.2f}T'
    elif cap >= 1e9:
        return f'${cap/1e9:.2f}B'
    elif cap >= 1e6:
        return f'${cap/1e6:.0f}M'
    else:
        return 'N/A'

def sanitize_ticker(ticker: str) -> Optional[str]:
    """Sanitize ticker input to prevent injection
    
    Returns:
        Clean ticker or None if invalid
    """
    # Only allow 1-5 uppercase letters
    if re.match(r'^[A-Z]{1,5}$', ticker):
        return ticker
    return None

def get_price_info(ticker: str) -> Dict:
    """Get basic price info for a ticker
    
    Returns:
        dict with keys: ticker, price, change_pct, market_cap, prev_close, error (if failed)
    """
    try:
        t = yf.Ticker(ticker)
        fast = t.fast_info
        info = t.info
        
        curr = fast.last_price
        prev = fast.previous_close
        pct = ((curr/prev)-1)*100
        cap = info.get('marketCap', 0)
        
        return {
            'ticker': ticker,
            'price': curr,
            'change_pct': pct,
            'market_cap': format_market_cap(cap),
            'prev_close': prev
        }
    except Exception as e:
        return {'ticker': ticker, 'error': str(e)}

def get_full_info(ticker: str) -> Dict:
    """Get comprehensive ticker information"""
    try:
        t = yf.Ticker(ticker)
        fast = t.fast_info
        info = t.info
        
        curr = fast.last_price
        prev = fast.previous_close
        pct = ((curr/prev)-1)*100
        
        return {
            'ticker': ticker,
            'price': curr,
            'change_pct': pct,
            'market_cap': format_market_cap(info.get('marketCap', 0)),
            'forward_pe': info.get('forwardPE'),
            'beta': info.get('beta'),
            'high_52w': info.get('fiftyTwoWeekHigh'),
            'low_52w': info.get('fiftyTwoWeekLow'),
            'ma_50': info.get('fiftyDayAverage'),
            'ma_200': info.get('twoHundredDayAverage'),
        }
    except Exception as e:
        return {'ticker': ticker, 'error': str(e)}

def get_thesis(ticker: str, theses_path: Path = None) -> Dict:
    """Load thesis for a ticker
    
    Args:
        ticker: Stock ticker symbol
        theses_path: Path to current-theses.json (defaults to ~/clawd/memory/)
    """
    if theses_path is None:
        theses_path = Path.home() / "clawd" / "memory" / "current-theses.json"
    
    try:
        with open(theses_path) as f:
            data = json.load(f)
        
        thesis = data.get('theses', {}).get(ticker, {})
        if thesis:
            return {
                'ticker': ticker,
                'status': thesis.get('status'),
                'thesis': thesis.get('thesis'),
                'pt': thesis.get('pt'),
                'position': thesis.get('position')
            }
        else:
            return {'ticker': ticker, 'error': 'No thesis found'}
    except Exception as e:
        return {'ticker': ticker, 'error': str(e)}

def get_market_snapshot() -> List[Dict]:
    """Get SPY/QQQ/IWM snapshot"""
    tickers = {'SPY': 'S&P 500', 'QQQ': 'Nasdaq', 'IWM': 'Russell'}
    results = []
    
    for sym, name in tickers.items():
        info = get_price_info(sym)
        if 'error' not in info:
            info['name'] = name
            results.append(info)
    
    return results

def get_sector_performance() -> Tuple[List[Dict], List[Dict]]:
    """Get best and worst performing sectors
    
    Returns:
        (best_3, worst_3) tuples of sector dicts
    """
    sectors = {
        'XLK': 'Tech', 'XLF': 'Financials', 'XLE': 'Energy',
        'XLV': 'Healthcare', 'XLI': 'Industrials', 'XLC': 'Communications',
        'XLY': 'Consumer Discretionary', 'XLP': 'Consumer Staples',
        'XLU': 'Utilities', 'XLRE': 'Real Estate', 'XLB': 'Materials'
    }
    
    results = []
    for sym, name in sectors.items():
        info = get_price_info(sym)
        if 'error' not in info:
            info['name'] = name
            results.append(info)
    
    results.sort(key=lambda x: x['change_pct'], reverse=True)
    return results[:3], results[-3:]

def get_holdings_performance(theses_path: Path = None) -> List[Dict]:
    """Get performance of all holdings
    
    Args:
        theses_path: Path to current-theses.json
    """
    if theses_path is None:
        theses_path = Path.home() / "clawd" / "memory" / "current-theses.json"
    
    try:
        with open(theses_path) as f:
            data = json.load(f)
        
        # Get all tickers except MACRO and special keys
        tickers = [
            t for t in data.get('theses', {}).keys() 
            if t not in ['MACRO', '_VERIFICATION_WARNING', '_MANDATORY_TOOLS']
        ]
        
        results = []
        for ticker in tickers[:10]:  # Limit to 10 to avoid rate limits
            info = get_price_info(ticker)
            if 'error' not in info:
                results.append(info)
        
        return results
    except Exception as e:
        return [{'error': str(e)}]
