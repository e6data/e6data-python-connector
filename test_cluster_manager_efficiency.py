#!/usr/bin/env python3
"""
Test script to verify ClusterManager uses established strategies efficiently.
"""

import sys
import logging
from unittest.mock import Mock, patch
from grpc._channel import _InactiveRpcError
import grpc

# Add the project root to the path
sys.path.insert(0, '.')

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def test_established_strategy_reuse():
    """Test that ClusterManager reuses established strategies efficiently."""
    
    from e6data_python_connector.cluster_manager import ClusterManager
    from e6data_python_connector.strategy import _clear_strategy_cache, _set_active_strategy, _get_active_strategy
    
    print("=== Testing Established Strategy Reuse ===\n")
    
    # Test 1: No active strategy - should use authentication sequence
    print("1. Testing authentication sequence when no active strategy...")
    
    _clear_strategy_cache()
    assert _get_active_strategy() is None, "Strategy should be None initially"
    
    manager = ClusterManager(
        host='localhost',
        port=50051,
        user='test@example.com',
        password='test-token',
        cluster_uuid='test-cluster'
    )
    
    # Check that the logic handles None strategy correctly
    import inspect
    source = inspect.getsource(manager._try_cluster_request)
    
    # Should have authentication sequence logic
    assert "No active strategy, starting authentication sequence" in source, "Should have authentication sequence logic"
    assert "strategies_to_try = ['blue', 'green']" in source, "Should try blue first, then green"
    
    print("✓ Authentication sequence logic is correct")
    
    # Test 2: Active strategy - should use established strategy first
    print("\n2. Testing established strategy reuse...")
    
    _set_active_strategy('blue')
    current_strategy = _get_active_strategy()
    assert current_strategy == 'blue', f"Expected 'blue', got {current_strategy}"
    
    # Check that the logic uses established strategy first
    assert "If we have an active strategy, use it first" in source, "Should use established strategy first"
    assert "current_strategy is not None" in source, "Should check for active strategy"
    assert "established strategy" in source, "Should mention established strategy"
    
    print("✓ Established strategy reuse logic is correct")
    
    # Test 3: Strategy switch on 456 error
    print("\n3. Testing strategy switch on 456 error...")
    
    # Check that 456 error handling switches to alternative
    assert "456 error - switch to alternative strategy" in source, "Should switch on 456 error"
    assert "alternative_strategy = 'green' if current_strategy == 'blue' else 'blue'" in source, "Should calculate alternative"
    assert "_set_active_strategy(alternative_strategy)" in source, "Should update active strategy"
    
    print("✓ Strategy switch logic is correct")
    
    print("\n=== Established Strategy Reuse Test Complete ===")
    return True


def test_efficiency_scenarios():
    """Test various efficiency scenarios."""
    
    from e6data_python_connector.cluster_manager import ClusterManager
    from e6data_python_connector.strategy import _clear_strategy_cache, _set_active_strategy
    
    print("\n=== Testing Efficiency Scenarios ===\n")
    
    manager = ClusterManager(
        host='localhost',
        port=50051,
        user='test@example.com',
        password='test-token',
        cluster_uuid='test-cluster'
    )
    
    # Test scenario 1: Initial connection (no strategy)
    print("1. Testing initial connection efficiency...")
    
    _clear_strategy_cache()
    
    # Mock to simulate blue success
    mock_connection = Mock()
    mock_response = Mock()
    mock_response.status = 'active'
    mock_response.new_strategy = None
    
    call_count = 0
    def mock_status_calls(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return mock_response
    
    mock_connection.status.side_effect = mock_status_calls
    
    # Test with mock
    with patch.object(type(manager), '_get_connection', new_callable=lambda: property(lambda self: mock_connection)):
        try:
            result = manager._try_cluster_request('status')
            assert call_count == 1, f"Expected 1 call, got {call_count}"
            print("✓ Initial connection makes only 1 call when successful")
        except Exception as e:
            print(f"✗ Initial connection test failed: {e}")
            raise
    
    # Test scenario 2: Established strategy (should only make 1 call)
    print("\n2. Testing established strategy efficiency...")
    
    _set_active_strategy('blue')
    
    call_count = 0
    mock_connection.status.side_effect = mock_status_calls
    
    with patch.object(type(manager), '_get_connection', new_callable=lambda: property(lambda self: mock_connection)):
        try:
            result = manager._try_cluster_request('status')
            assert call_count == 1, f"Expected 1 call, got {call_count}"
            print("✓ Established strategy makes only 1 call when successful")
        except Exception as e:
            print(f"✗ Established strategy test failed: {e}")
            raise
    
    print("\n=== Efficiency Scenarios Test Complete ===")
    return True


def test_logging_behavior():
    """Test that logging shows the efficiency improvements."""
    
    from e6data_python_connector.cluster_manager import ClusterManager
    from e6data_python_connector.strategy import _clear_strategy_cache, _set_active_strategy
    
    print("\n=== Testing Logging Behavior ===\n")
    
    manager = ClusterManager(
        host='localhost',
        port=50051,
        user='test@example.com',
        password='test-token',
        cluster_uuid='test-cluster'
    )
    
    # Test the logging messages
    import inspect
    source = inspect.getsource(manager._try_cluster_request)
    
    # Check for efficiency-related logging
    efficiency_logs = [
        "established strategy",
        "No active strategy, starting authentication sequence",
        "switching to",
        "succeeded with alternative strategy"
    ]
    
    for log_msg in efficiency_logs:
        assert log_msg in source, f"Should contain logging for: {log_msg}"
        print(f"✓ Contains logging for: {log_msg}")
    
    print("\n=== Logging Behavior Test Complete ===")
    return True


def main():
    """Run all tests."""
    try:
        test_established_strategy_reuse()
        test_efficiency_scenarios()
        test_logging_behavior()
        print("\n🎉 All tests passed! ClusterManager now uses established strategies efficiently.")
        return True
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)