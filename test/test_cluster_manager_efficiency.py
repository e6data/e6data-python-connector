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
sys.path.insert(0, '..')

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


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
    
    expected_strategy = 'blue'
    # Existing synthetic boundary regression.
    with patch.object(type(manager), '_get_connection', new_callable=lambda: property(lambda self: mock_connection)):
        try:
            result = manager._try_cluster_request('status')
            assert call_count == 1, f"Expected 1 call, got {call_count}"
            assert result is mock_response
            assert dict(mock_connection.status.call_args.kwargs['metadata'])['strategy'] == expected_strategy
            print("✓ Initial connection makes only 1 call when successful")
        except Exception as e:
            print(f"✗ Initial connection test failed: {e}")
            raise
    
    # Test scenario 2: Established strategy (should only make 1 call)
    print("\n2. Testing established strategy efficiency...")
    
    _set_active_strategy('green')
    expected_strategy = 'green'
    
    call_count = 0
    mock_connection.status.side_effect = mock_status_calls
    
    with patch.object(type(manager), '_get_connection', new_callable=lambda: property(lambda self: mock_connection)):
        try:
            result = manager._try_cluster_request('status')
            assert call_count == 1, f"Expected 1 call, got {call_count}"
            assert result is mock_response
            assert dict(mock_connection.status.call_args.kwargs['metadata'])['strategy'] == expected_strategy
            print("✓ Established strategy makes only 1 call when successful")
        except Exception as e:
            print(f"✗ Established strategy test failed: {e}")
            raise
    
    print("\n=== Efficiency Scenarios Test Complete ===")


def main():
    """Run all tests."""
    try:
        test_efficiency_scenarios()
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