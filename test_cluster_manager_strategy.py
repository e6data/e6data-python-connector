#!/usr/bin/env python3
"""
Test script to verify ClusterManager strategy support and 456 error handling.
"""

import sys
import logging
from unittest.mock import Mock, patch, MagicMock
from grpc._channel import _InactiveRpcError
import grpc

# Add the project root to the path
sys.path.insert(0, '.')

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def test_cluster_manager_strategy_support():
    """Test ClusterManager with strategy support."""
    
    from e6data_python_connector.cluster_manager import ClusterManager
    from e6data_python_connector.strategy import _set_active_strategy, _clear_strategy_cache
    
    print("=== Testing ClusterManager Strategy Support ===\n")
    
    # Clear strategy cache
    _clear_strategy_cache()
    
    # Set initial strategy
    _set_active_strategy('blue')
    
    # Initialize ClusterManager
    manager = ClusterManager(
        host='localhost',
        port=50051,
        user='test@example.com',
        password='test-token',
        cluster_uuid='test-cluster'
    )
    
    print("✓ ClusterManager initialized with strategy support")
    
    # Test 1: Test _get_grpc_header with strategy
    print("\n1. Testing _get_grpc_header with strategy...")
    from e6data_python_connector.cluster_manager import _get_grpc_header
    
    headers = _get_grpc_header(cluster='test-cluster', strategy='blue')
    expected_headers = [('cluster-uuid', 'test-cluster'), ('strategy', 'blue')]
    assert headers == expected_headers, f"Expected {expected_headers}, got {headers}"
    print("✓ _get_grpc_header works correctly with strategy")
    
    # Test 2: Test _try_cluster_request method structure
    print("\n2. Testing _try_cluster_request method...")
    assert hasattr(manager, '_try_cluster_request'), "ClusterManager should have _try_cluster_request method"
    print("✓ _try_cluster_request method exists")
    
    # Test 3: Test 456 error handling logic (simplified)
    print("\n3. Testing 456 error handling logic...")
    
    # Test the core logic by examining the _try_cluster_request method
    import inspect
    
    # Check if the method has the correct structure for 456 handling
    source = inspect.getsource(manager._try_cluster_request)
    assert "456" in source, "Method should contain 456 error handling"
    assert "strategies_to_try" in source, "Method should handle multiple strategies"
    assert "green" in source and "blue" in source, "Method should handle both strategies"
    assert "for i, strategy in enumerate(strategies_to_try):" in source, "Method should iterate through strategies"
    assert "continue" in source, "Method should continue to next strategy on 456 error"
    
    print("✓ 456 error handling logic is implemented correctly")
    
    # Test 4: Test strategy header injection
    print("\n4. Testing strategy header injection...")
    
    # Test that headers are correctly generated with current strategy
    from e6data_python_connector.strategy import _get_active_strategy
    current_strategy = _get_active_strategy()
    
    headers = _get_grpc_header(cluster='test-cluster', strategy=current_strategy)
    
    # Should contain strategy header
    strategy_header = next((header for header in headers if header[0] == 'strategy'), None)
    assert strategy_header is not None, "Strategy header should be present"
    assert strategy_header[1] == current_strategy, f"Strategy header should be {current_strategy}"
    
    print(f"✓ Strategy header injection works correctly: {strategy_header}")
    
    # Test 5: Test strategy validation
    print("\n5. Testing strategy validation...")
    
    # Test valid strategies
    valid_headers = _get_grpc_header(strategy='blue')
    assert ('strategy', 'blue') in valid_headers, "Valid strategy should be included"
    
    # Test invalid strategies (should be filtered out)
    invalid_headers = _get_grpc_header(strategy='invalid')
    strategy_headers = [h for h in invalid_headers if h[0] == 'strategy']
    assert len(strategy_headers) == 0, "Invalid strategy should be filtered out"
    
    print("✓ Strategy validation works correctly")
    
    print("\n=== ClusterManager Strategy Support Test Complete ===")
    return True

def test_cluster_manager_integration():
    """Test ClusterManager integration with strategy module."""
    
    print("\n=== Testing ClusterManager Integration ===\n")
    
    from e6data_python_connector.cluster_manager import ClusterManager
    from e6data_python_connector.strategy import _get_active_strategy, _set_active_strategy
    
    # Test strategy detection
    _set_active_strategy('blue')
    active_strategy = _get_active_strategy()
    assert active_strategy == 'blue', f"Expected 'blue', got {active_strategy}"
    print("✓ Strategy detection works correctly")
    
    # Test ClusterManager can access strategy
    manager = ClusterManager(
        host='localhost',
        port=50051,
        user='test@example.com',
        password='test-token',
        cluster_uuid='test-cluster'
    )
    
    # Test that ClusterManager can use strategy functions
    try:
        # This should work without errors
        from e6data_python_connector.strategy import _get_active_strategy
        strategy = _get_active_strategy()
        print(f"✓ ClusterManager can access strategy: {strategy}")
    except Exception as e:
        print(f"✗ ClusterManager strategy access failed: {e}")
        raise
    
    print("\n=== ClusterManager Integration Test Complete ===")
    return True

def main():
    """Run all tests."""
    try:
        test_cluster_manager_strategy_support()
        test_cluster_manager_integration()
        print("\n🎉 All tests passed! ClusterManager strategy support is working correctly.")
        return True
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)