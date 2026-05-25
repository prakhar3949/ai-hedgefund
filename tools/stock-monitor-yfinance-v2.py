#!/usr/bin/env python3
"""
Stock Monitor v2 - Improved performance and error handling
Uses fast_info and implements caching for frequent calls
"""

import json
import sys
from pathlib import Path
import yfinance as yf
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
import pickle

WATCHLIST_PATH = Path.home() / "clawd/memory/watchlist.json"
CACHE_PATH = Path.home() / "clawd/memory/.stock-cache.pkl"
CACHE_TTL = 60  # Cache for 60 seconds

class StockCache:
    """Simple file-based cache with TTL"""
    
    def __init__(self, cache_path: Path, ttl: int):
        self.cache_path = cache_path
        self.ttl = ttl
        self.cache = self._load_cache()
    
    def _load_cache(self) -> Dict:
        """Load cache from disk"""
        if self.cache_path.exists():
            try:
                with open(self.cache_path, 'rb') as f:
                    return pickle.load(f)
            except Exception:
                # Corrupted cache, start fresh
                return {}
        return {}
    
    def _save_cache(self) -> None:
        """Save cache to disk"""
        try:
            self.cache_path.parent.mkdir(exist_ok=True)
            with open(self.cache_path, 'wb') as f:
                pickle.dump(self.cache, f)
        except Exception as e:
            print(f"Warning: Could not save cache: {e}", file=sys.stderr)
    
    def get(self, key: str) -> Tuple[bool, any]:
        """Get cached value if not expired
        
        Returns:
            (hit, value) tuple - hit=True if cached and not expired
        """
        if key in self.cache:
            timestamp, value = self.cache[key]
            if datetime.now() - timestamp < timedelta(seconds=self.ttl):
                return True, value
        return False, None
    
    def set(self, key: str, value: any) -> None:
        """Set cache value with current timestamp"""
        self.cache[key] = (datetime.now(), value)
        self._save_cache()
    
    def clear(self) -> None:
        """Clear all cached data"""
        self.cache = {}
        self._save_cache()

def load_watchlist() -> Tuple[Dict[str, str], Dict]:
    """Load watchlist from JSON
    
    Returns:
        (tickers_dict, watchlist_data) where tickers_dict maps ticker -> category
    """
    try:
        with open(WATCHLIST_PATH) as f:
            data = json.load(f)
        
        tickers = {}
        
        # Add holdings
        for ticker in data["stocks"].get("holdings", {}).keys():
            tickers[ticker] = "holding"
        
        # Add priority watchlist
        for ticker in data["stocks"].get("priority", []):
            if ticker not in tickers:
                tickers[ticker] = "priority"
        
        return tickers, data
        
    except FileNotFoundError:
        print(f"Error: Watchlist not found at {WATCHLIST_PATH}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in watchlist: {e}", file=sys.stderr)
        sys.exit(1)

def get_quote_fast(ticker: str, cache: StockCache) -> Dict:
    """Get quote for single ticker with caching
    
    Uses fast_info for speed (3-4x faster than download)
    Caches results to prevent redundant API calls
    
    Args:
        ticker: Stock ticker symbol
        cache: StockCache instance
        
    Returns:
        Dict with quote data or error
    """
    # Check cache first
    hit, cached = cache.get(ticker)
    if hit:
        return cached
    
    try:
        t = yf.Ticker(ticker)
        fast = t.fast_info
        
        # Validate data
        if not hasattr(fast, 'last_price') or not hasattr(fast, 'previous_close'):
            result = {
                "symbol": ticker,
                "error": "Missing price data",
                "timestamp": datetime.now().isoformat()
            }
            return result
        
        # Calculate change
        curr = fast.last_price
        prev = fast.previous_close
        
        if prev <= 0:
            result = {
                "symbol": ticker,
                "error": "Invalid previous close",
                "timestamp": datetime.now().isoformat()
            }
            return result
        
        change = curr - prev
        change_pct = (change / prev) * 100
        
        result = {
            "symbol": ticker,
            "price": round(curr, 2),
            "change": round(change, 2),
            "changePercent": round(change_pct, 2),
            "volume": getattr(fast, 'last_volume', None),
            "high": getattr(fast, 'day_high', None),
            "low": getattr(fast, 'day_low', None),
            "timestamp": datetime.now().isoformat()
        }
        
        # Cache result
        cache.set(ticker, result)
        return result
        
    except AttributeError as e:
        error_result = {
            "symbol": ticker,
            "error": f"Data error: {str(e)}",
            "timestamp": datetime.now().isoformat()
        }
        return error_result
    except Exception as e:
        error_result = {
            "symbol": ticker,
            "error": f"Fetch error: {str(e)}",
            "timestamp": datetime.now().isoformat()
        }
        return error_result

def get_quotes_batch(tickers: List[str], cache: StockCache) -> List[Dict]:
    """Get quotes for multiple tickers with caching
    
    Args:
        tickers: List of ticker symbols
        cache: StockCache instance
        
    Returns:
        List of quote dicts
    """
    results = []
    
    for ticker in tickers:
        quote = get_quote_fast(ticker, cache)
        results.append(quote)
    
    return results

def main():
    """Main execution"""
    # Initialize cache
    cache = StockCache(CACHE_PATH, CACHE_TTL)
    
    # Load watchlist
    tickers_dict, watchlist = load_watchlist()
    
    # Filter to holdings only if requested
    if len(sys.argv) > 1 and sys.argv[1] == "--holdings":
        tickers_dict = {k: v for k, v in tickers_dict.items() if v == "holding"}
    
    # Clear cache if requested
    if len(sys.argv) > 1 and sys.argv[1] == "--clear-cache":
        cache.clear()
        print("Cache cleared", file=sys.stderr)
        return
    
    # Get quotes
    tickers_list = list(tickers_dict.keys())
    if not tickers_list:
        print("Warning: No tickers in watchlist", file=sys.stderr)
        print("[]")
        return
    
    quotes = get_quotes_batch(tickers_list, cache)
    
    # Add category to each quote
    for quote in quotes:
        if "symbol" in quote:
            quote["category"] = tickers_dict.get(quote["symbol"], "unknown")
    
    # Output JSON
    print(json.dumps(quotes, indent=2))

if __name__ == "__main__":
    main()
