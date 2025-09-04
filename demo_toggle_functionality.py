#!/usr/bin/env python3
"""
Demo script showing Cython optimization toggle functionality.

This script demonstrates all the ways to control Cython optimizations
in the e6data Python connector.
"""

import time
import os
from e6data_python_connector.fast_deserializer import (
    get_optimization_info,
    set_optimization_mode,
    get_available_modes,
    enable_fast_deserialization,
    disable_fast_deserialization,
    set_and_save_mode
)

def print_separator(title):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print('='*50)

def show_current_status():
    """Display current optimization status."""
    info = get_optimization_info()
    print(f"Current mode: {info['current_mode']}")
    print(f"Optimization enabled: {info['optimization_enabled']}")
    print(f"Cython available: {info['cython_available']}")
    print(f"Force mode: {info['force_mode']}")
    print(f"Available modes: {info['available_modes']}")
    
    if info['recommendations']:
        print("Recommendations:")
        for rec in info['recommendations']:
            print(f"  - {rec}")

def benchmark_mode(mode_name, setup_func):
    """Benchmark a specific optimization mode."""
    try:
        setup_func()
        
        # Simple performance test (creating/processing lists)
        start = time.time()
        for _ in range(1000):
            data = list(range(1000))
            result = [x * 2 for x in data]
        end = time.time()
        
        info = get_optimization_info()
        print(f"✅ {mode_name}: {end-start:.4f}s (mode: {info['current_mode']})")
        return end - start
        
    except Exception as e:
        print(f"❌ {mode_name}: Error - {e}")
        return None

def main():
    print("e6data Python Connector - Cython Toggle Demo")
    
    # 1. Show initial status
    print_separator("Initial Optimization Status")
    show_current_status()
    
    # 2. Show available modes
    print_separator("Available Optimization Modes")
    modes = get_available_modes()
    for i, mode in enumerate(modes, 1):
        print(f"{i}. {mode}")
    
    # 3. Test all modes
    print_separator("Testing All Optimization Modes")
    
    mode_tests = [
        ("Default (Original)", lambda: set_optimization_mode('default')),
        ("Python Optimized", lambda: set_optimization_mode('python')),
        ("Auto Detection", lambda: set_optimization_mode('auto')),
    ]
    
    # Add Cython test if available
    info = get_optimization_info()
    if info['cython_available']:
        mode_tests.append(("Cython Optimized", lambda: set_optimization_mode('cython')))
    
    results = {}
    for mode_name, setup_func in mode_tests:
        results[mode_name] = benchmark_mode(mode_name, setup_func)
    
    # 4. Show performance comparison
    if any(results.values()):
        print_separator("Performance Comparison")
        valid_results = {k: v for k, v in results.items() if v is not None}
        if len(valid_results) > 1:
            baseline = max(valid_results.values())
            for mode, duration in valid_results.items():
                if duration:
                    speedup = baseline / duration
                    print(f"{mode}: {duration:.4f}s ({speedup:.2f}x speedup)")
    
    # 5. Test configuration saving
    print_separator("Configuration Management")
    try:
        success = set_and_save_mode('python')
        print(f"Configuration saved: {success}")
        
        if success and os.path.exists('.e6data_config.json'):
            with open('.e6data_config.json', 'r') as f:
                print("Saved configuration:")
                print(f.read())
    except Exception as e:
        print(f"Configuration test failed: {e}")
    
    # 6. Test environment variable precedence
    print_separator("Environment Variable Controls")
    
    print("Testing environment variable precedence...")
    print("(Environment variables override all other settings)")
    
    env_tests = [
        ("E6DATA_DISABLE_CYTHON=1", "Cython should be unavailable"),
        ("E6DATA_FORCE_MODE=python", "Should force Python optimized"),
        ("E6DATA_DISABLE_OPTIMIZATIONS=1", "Should disable all optimizations")
    ]
    
    for env_var, expected in env_tests:
        print(f"\nTo test: export {env_var}")
        print(f"Expected: {expected}")
    
    print("\nExample usage:")
    print("E6DATA_FORCE_MODE=cython python your_script.py")
    
    # 7. Final status
    print_separator("Final Status")
    show_current_status()
    
    print("\n🎉 Toggle functionality demonstration complete!")
    print("\nFor more information, see:")
    print("- CYTHON_TOGGLE_GUIDE.md - Complete toggle control guide")
    print("- CYTHON_OPTIMIZATION_GUIDE.md - Performance and installation guide")
    print("- CYTHON_BUILD_GUIDE.md - Build and regeneration guide")

if __name__ == "__main__":
    main()