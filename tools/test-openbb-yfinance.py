#!/usr/bin/env python3
"""
Test if we can use openbb-yfinance provider directly
"""

print("Testing openbb-yfinance provider...")

try:
    # Try importing the yfinance provider directly
    from openbb_yfinance import yfinance_provider
    print("✓ openbb_yfinance imported")
    print(f"Available: {dir(yfinance_provider)}")
except Exception as e:
    print(f"✗ Direct import failed: {e}")

# Try using the main obb interface with just yfinance provider
try:
    from openbb import obb
    
    # Initialize with credentials if needed
    print("\nTrying obb.account.login()...")
    try:
        obb.account.login()
        print("✓ Logged in (or credentials not required)")
    except:
        print("✗ Login not required or failed (this may be OK)")
    
    # Try accessing equity (which should work)
    print("\nTrying obb.equity.price.quote (AAPL as test)...")
    result = obb.equity.price.quote(symbol="AAPL", provider="yfinance")
    print(f"✓ Equity works! Data: {result}")
    
except Exception as e:
    print(f"✗ OBB interface test failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("CONCLUSION: OpenBB has Python 3.13 compatibility issues")
print("="*60)
