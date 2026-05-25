#!/usr/bin/env python3
"""
Explore what OpenBB crypto methods are actually available
"""

import sys

print("Testing OpenBB import and available methods...")

try:
    from openbb import obb
    print("✓ OpenBB imported successfully")
    
    # Check if crypto module exists
    if hasattr(obb, 'crypto'):
        print("✓ crypto module exists")
        print(f"\nAvailable crypto methods:")
        crypto_attrs = [attr for attr in dir(obb.crypto) if not attr.startswith('_')]
        for attr in crypto_attrs:
            print(f"  - {attr}")
        
        # Check price submodule
        if hasattr(obb.crypto, 'price'):
            print(f"\nAvailable crypto.price methods:")
            price_attrs = [attr for attr in dir(obb.crypto.price) if not attr.startswith('_')]
            for attr in price_attrs:
                print(f"  - {attr}")
        
        # Try to get a simple quote
        print("\n" + "="*50)
        print("Attempting to fetch BTC data...")
        print("="*50)
        
        # Try different methods
        methods_to_try = [
            ("crypto.load", lambda: obb.crypto.load("BTCUSD")),
            ("crypto.price.historical (yfinance)", lambda: obb.crypto.price.historical(symbol="BTCUSD", provider="yfinance")),
            ("crypto.price.historical (fmp)", lambda: obb.crypto.price.historical(symbol="BTCUSD", provider="fmp")),
        ]
        
        for method_name, method_call in methods_to_try:
            try:
                print(f"\nTrying: {method_name}")
                result = method_call()
                print(f"  ✓ Success! Type: {type(result)}")
                if hasattr(result, 'results'):
                    print(f"  Results count: {len(result.results) if result.results else 0}")
                    if result.results:
                        print(f"  Sample data: {result.results[0]}")
                elif hasattr(result, 'to_dict'):
                    print(f"  Data: {result.to_dict()}")
                else:
                    print(f"  Data: {result}")
            except Exception as e:
                print(f"  ✗ Failed: {e}")
    else:
        print("✗ crypto module not found")
        print(f"Available OBB modules: {[attr for attr in dir(obb) if not attr.startswith('_')]}")
        
except ImportError as e:
    print(f"✗ Failed to import OpenBB: {e}")
except Exception as e:
    print(f"✗ Unexpected error: {e}")
    import traceback
    traceback.print_exc()
