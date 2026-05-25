#!/usr/bin/env python3
"""Access Lighter through free proxy services"""

import requests
import json
import sys

# Free proxy services to try
PROXIES = [
    # ProxyScrape free proxies
    "https://api.proxyscrape.com/v2/?request=get&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
]

def get_free_proxy():
    """Fetch a free proxy"""
    try:
        response = requests.get(PROXIES[0], timeout=10)
        proxies = response.text.strip().split('\n')
        for proxy in proxies[:5]:  # Try first 5
            if proxy:
                return f"http://{proxy}"
    except Exception as e:
        print(f"Error fetching proxies: {e}", file=sys.stderr)
    return None

def test_lighter_access(proxy=None):
    """Test if we can access Lighter"""
    url = "https://www.lighter.xyz"
    proxies_dict = {"http": proxy, "https": proxy} if proxy else None
    
    try:
        response = requests.get(url, proxies=proxies_dict, timeout=10)
        return response.status_code == 200
    except Exception as e:
        return False

if __name__ == "__main__":
    print("Fetching free proxy...", file=sys.stderr)
    proxy = get_free_proxy()
    
    if proxy:
        print(f"Testing proxy: {proxy}", file=sys.stderr)
        if test_lighter_access(proxy):
            print(json.dumps({"success": True, "proxy": proxy}))
        else:
            print(json.dumps({"success": False, "error": "Proxy failed"}))
    else:
        print(json.dumps({"success": False, "error": "No proxy available"}))
