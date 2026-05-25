#!/usr/bin/env python3
"""Access Lighter through cloud proxy service"""
import requests
from requests.auth import HTTPProxyAuth

# Using free proxy rotation service
PROXY_SERVICES = [
    "https://proxy.webshare.io/api/v2/proxy/list/",  # Free tier available
]

def access_lighter_with_proxy():
    """Try to access Lighter through various proxy methods"""
    
    # Method 1: Direct access (might work from some IPs)
    try:
        response = requests.get("https://www.lighter.xyz/trade", timeout=10)
        if response.status_code == 200:
            return {"success": True, "method": "direct", "content_length": len(response.text)}
    except:
        pass
    
    # Method 2: Through free web proxy
    try:
        proxy_url = "https://www.croxyproxy.com/go?q=https://www.lighter.xyz/trade"
        response = requests.get(proxy_url, timeout=15)
        if "lighter" in response.text.lower():
            return {"success": True, "method": "web_proxy", "url": proxy_url}
    except:
        pass
    
    return {"success": False, "error": "All methods failed"}

if __name__ == "__main__":
    import json
    result = access_lighter_with_proxy()
    print(json.dumps(result, indent=2))
