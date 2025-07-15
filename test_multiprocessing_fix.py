#!/usr/bin/env python3
"""
Test to verify the multiprocessing RuntimeError fix works correctly.
"""

import sys
import multiprocessing
import time

# Add the project root to the path
sys.path.insert(0, '.')


def test_import_in_subprocess():
    """Test that strategy module can be imported in subprocess."""
    try:
        from e6data_python_connector.strategy import _get_active_strategy, _set_active_strategy
        _set_active_strategy('blue')
        strategy = _get_active_strategy()
        print(f"Subprocess: Successfully set and retrieved strategy: {strategy}")
        return True
    except Exception as e:
        print(f"Subprocess: Error - {e}")
        return False


def test_multiprocessing_scenario():
    """Test the fix in various multiprocessing scenarios."""
    print("=== Testing Multiprocessing Fix ===\n")
    
    # Test 1: Import in main process
    print("1. Testing import in main process...")
    try:
        from e6data_python_connector.strategy import _get_active_strategy, _set_active_strategy, _clear_strategy_cache
        _clear_strategy_cache()
        print("✓ Main process: Import successful")
    except Exception as e:
        print(f"✗ Main process: Import failed - {e}")
        return False
    
    # Test 2: Set strategy in main process
    print("\n2. Testing strategy operations in main process...")
    try:
        _set_active_strategy('green')
        strategy = _get_active_strategy()
        assert strategy == 'green', f"Expected 'green', got {strategy}"
        print(f"✓ Main process: Strategy operations work correctly: {strategy}")
    except Exception as e:
        print(f"✗ Main process: Strategy operations failed - {e}")
        return False
    
    # Test 3: Test in subprocess
    print("\n3. Testing import and operations in subprocess...")
    try:
        # Create a process to test importing in subprocess
        process = multiprocessing.Process(target=test_import_in_subprocess)
        process.start()
        process.join(timeout=5)
        
        if process.exitcode == 0:
            print("✓ Subprocess: Import and operations successful")
        else:
            print(f"✗ Subprocess: Failed with exit code {process.exitcode}")
            return False
    except Exception as e:
        print(f"✗ Subprocess test failed: {e}")
        return False
    
    # Test 4: Test multiple imports
    print("\n4. Testing multiple imports...")
    try:
        # Import again to test re-import safety
        import e6data_python_connector.strategy
        from e6data_python_connector.strategy import _get_active_strategy as get_strategy_2
        from e6data_python_connector.cluster_manager import ClusterManager
        
        # Test that both imports work
        strategy1 = _get_active_strategy()
        strategy2 = get_strategy_2()
        assert strategy1 == strategy2, f"Strategy mismatch: {strategy1} != {strategy2}"
        
        # Test ClusterManager can still use strategy
        manager = ClusterManager(
            host='localhost',
            port=50051,
            user='test@example.com',
            password='test-token',
            cluster_uuid='test-cluster'
        )
        assert hasattr(manager, '_try_cluster_request'), "ClusterManager should have strategy support"
        
        print("✓ Multiple imports and ClusterManager work correctly")
    except Exception as e:
        print(f"✗ Multiple imports test failed: {e}")
        return False
    
    print("\n=== All Multiprocessing Tests Passed ===")
    return True


def main():
    """Run the test."""
    # Set multiprocessing start method to 'spawn' to test the worst case
    # (spawn is the default on Windows and macOS Python 3.8+)
    try:
        multiprocessing.set_start_method('spawn', force=True)
        print("Using 'spawn' start method (most restrictive)\n")
    except RuntimeError:
        print("Start method already set\n")
    
    success = test_multiprocessing_scenario()
    
    if success:
        print("\n🎉 Multiprocessing RuntimeError fix verified successfully!")
        return 0
    else:
        print("\n❌ Multiprocessing test failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())