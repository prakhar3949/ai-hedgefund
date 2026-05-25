#!/usr/bin/env python3
"""
Performance Profiler - Measure script execution time and bottlenecks
Helps identify slow scripts and track performance improvements
"""

import subprocess
import time
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

CLAWD_DIR = Path.home() / "clawd"

# Scripts to profile (name, command_parts)
SCRIPTS_TO_PROFILE = [
    ("Quick Lookup: Price", ["tools/quick-lookup.sh", "price", "SPY"]),
    ("Quick Lookup: Info", ["tools/quick-lookup.sh", "info", "SPY"]),
    ("Quick Lookup: Market", ["tools/quick-lookup.sh", "market"]),
    ("Quick Lookup: Sectors", ["tools/quick-lookup.sh", "sectors"]),
    ("Stock Monitor", ["venv/bin/python", "tools/stock-monitor-yfinance.py"]),
    ("Stock Monitor v2", ["venv/bin/python", "tools/stock-monitor-yfinance-v2.py"]),
    ("Crash Monitor", ["venv/bin/python", "tools/crash-monitor.py"]),
    ("Crash Monitor v2", ["venv/bin/python", "tools/crash-monitor-v2.py"]),
    ("Smart Router: Price", ["tools/smart-router.sh", "price AMD"]),
    ("Smart Router: Market", ["tools/smart-router.sh", "market"]),
]

def profile_script(name: str, cmd: List[str], runs: int = 5, timeout: int = 30) -> Dict:
    """Profile a script execution
    
    Args:
        name: Human-readable script name
        cmd: Command parts to execute
        runs: Number of times to run (default 5)
        timeout: Timeout in seconds (default 30)
        
    Returns:
        Dict with timing stats and success/error counts
    """
    times = []
    errors = []
    
    for run in range(runs):
        start = time.time()
        try:
            result = subprocess.run(
                cmd,
                cwd=CLAWD_DIR,
                capture_output=True,
                timeout=timeout,
                text=True
            )
            elapsed = time.time() - start
            
            if result.returncode == 0:
                times.append(elapsed)
            else:
                errors.append(f"Exit code {result.returncode}")
                
        except subprocess.TimeoutExpired:
            errors.append(f"Timeout (>{timeout}s)")
        except FileNotFoundError:
            errors.append("Script not found")
            break  # No point retrying
        except Exception as e:
            errors.append(f"Error: {str(e)}")
    
    if times:
        avg = sum(times) / len(times)
        min_time = min(times)
        max_time = max(times)
        
        return {
            "name": name,
            "runs": runs,
            "successful": len(times),
            "errors": len(errors),
            "avg_seconds": round(avg, 3),
            "min_seconds": round(min_time, 3),
            "max_seconds": round(max_time, 3),
            "error_messages": errors[:3]  # Keep first 3 errors
        }
    else:
        return {
            "name": name,
            "runs": runs,
            "successful": 0,
            "errors": len(errors),
            "error": "All runs failed",
            "error_messages": errors[:3]
        }

def compare_versions(results: List[Dict]) -> List[Tuple[str, str, float]]:
    """Compare v1 vs v2 scripts to show improvements
    
    Returns:
        List of (script_name, comparison, improvement_pct) tuples
    """
    comparisons = []
    
    # Group by base name
    by_base = {}
    for result in results:
        if "error" in result:
            continue
        
        name = result["name"]
        if " v2" in name or " V2" in name:
            base = name.replace(" v2", "").replace(" V2", "")
            version = "v2"
        else:
            base = name
            version = "v1"
        
        if base not in by_base:
            by_base[base] = {}
        by_base[base][version] = result["avg_seconds"]
    
    # Calculate improvements
    for base, versions in by_base.items():
        if "v1" in versions and "v2" in versions:
            v1_time = versions["v1"]
            v2_time = versions["v2"]
            improvement = ((v1_time - v2_time) / v1_time) * 100
            
            if improvement > 0:
                comparisons.append((base, "faster", improvement))
            else:
                comparisons.append((base, "slower", abs(improvement)))
    
    return comparisons

def print_summary(results: List[Dict]) -> None:
    """Print formatted summary of profiling results"""
    print("\n" + "=" * 70)
    print("PERFORMANCE SUMMARY")
    print("=" * 70)
    
    # Separate successful and failed
    successful = [r for r in results if "error" not in r]
    failed = [r for r in results if "error" in r]
    
    if successful:
        # Sort by avg time
        successful.sort(key=lambda x: x['avg_seconds'])
        
        print("\n🏆 Fastest to slowest (successful runs):\n")
        for i, result in enumerate(successful, 1):
            print(f"{i}. {result['name']}")
            print(f"   ⏱️  {result['avg_seconds']}s avg (range: {result['min_seconds']}s - {result['max_seconds']}s)")
            print(f"   ✅ {result['successful']}/{result['runs']} successful")
            if result['errors'] > 0:
                print(f"   ⚠️  {result['errors']} errors")
            print()
    
    if failed:
        print("\n❌ Failed scripts:\n")
        for result in failed:
            print(f"• {result['name']}")
            print(f"  {result['error']}")
            if result.get('error_messages'):
                print(f"  Details: {result['error_messages'][0]}")
            print()
    
    # Compare versions
    comparisons = compare_versions(results)
    if comparisons:
        print("\n📊 Version comparisons:\n")
        for base, status, pct in comparisons:
            icon = "🚀" if status == "faster" else "🐌"
            print(f"{icon} {base}: v2 is {pct:.1f}% {status} than v1")
        print()

def main():
    """Main execution"""
    print("📊 Script Performance Profiler")
    print("=" * 70)
    print(f"Profiling {len(SCRIPTS_TO_PROFILE)} scripts (5 runs each)...")
    print("This may take a few minutes...\n")
    
    results = []
    
    for i, (name, cmd) in enumerate(SCRIPTS_TO_PROFILE, 1):
        print(f"[{i}/{len(SCRIPTS_TO_PROFILE)}] {name}...", end=" ", flush=True)
        
        result = profile_script(name, cmd)
        results.append(result)
        
        if "error" not in result:
            print(f"✅ {result['avg_seconds']}s")
        else:
            print(f"❌ {result['error']}")
    
    # Print summary
    print_summary(results)
    
    # Save results
    output_file = CLAWD_DIR / "memory" / "performance-profile.json"
    output_file.parent.mkdir(exist_ok=True)
    
    profile_data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": results
    }
    
    with open(output_file, 'w') as f:
        json.dump(profile_data, f, indent=2)
    
    print(f"💾 Results saved to: {output_file}")
    
    # Exit code based on failures
    failed_count = len([r for r in results if "error" in r])
    if failed_count > 0:
        print(f"\n⚠️  {failed_count} scripts failed profiling")
        sys.exit(1)
    else:
        print("\n✅ All scripts profiled successfully")
        sys.exit(0)

if __name__ == "__main__":
    main()
