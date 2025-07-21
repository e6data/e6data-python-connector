#!/usr/bin/env python3
"""
Test script to verify strategy persistence after cluster resume is fixed.
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


def test_strategy_persistence_after_resume():
    """Test that strategy persists after successful cluster resume."""
    
    from e6data_python_connector.cluster_manager import ClusterManager
    from e6data_python_connector.strategy import _clear_strategy_cache, _get_active_strategy, _set_active_strategy
    
    print("=== Testing Strategy Persistence After Resume ===\n")
    
    # Clear strategy cache to start fresh
    _clear_strategy_cache()
    
    # Verify strategy is None initially
    current_strategy = _get_active_strategy()
    assert current_strategy is None, f"Expected None strategy, got {current_strategy}"
    print("✓ Strategy is None initially")
    
    # Initialize ClusterManager
    manager = ClusterManager(
        host='localhost',
        port=50051,
        user='test@example.com',
        password='test-token',
        cluster_uuid='test-cluster'
    )
    
    print("✓ ClusterManager initialized")
    
    # Test 1: Test strategy persistence in _try_cluster_request
    print("\n1. Testing strategy persistence in _try_cluster_request...")
    
    # Mock successful response
    mock_connection = Mock()
    mock_response = Mock()
    mock_response.status = 'active'
    mock_response.new_strategy = None
    
    # Mock that returns successful response
    def mock_status_success(*args, **kwargs):
        return mock_response
    
    mock_connection.status.side_effect = mock_status_success
    
    # Mock the _get_connection property
    with patch.object(type(manager), '_get_connection', new_callable=lambda: property(lambda self: mock_connection)):
        # Call _try_cluster_request which should set the strategy
        result = manager._try_cluster_request('status')
        
        # Verify strategy is now set
        current_strategy = _get_active_strategy()
        assert current_strategy == 'blue', f"Expected 'blue' strategy after success, got {current_strategy}"
        print(f"✓ Strategy set to '{current_strategy}' after successful request")
    
    # Test 2: Test strategy persistence across multiple calls
    print("\n2. Testing strategy persistence across multiple calls...")
    
    call_count = 0
    def mock_status_with_counter(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Check that established strategy is used
        metadata = kwargs.get('metadata', [])
        strategy_header = next((header for header in metadata if header[0] == 'strategy'), None)
        assert strategy_header is not None, "Strategy header should be present"
        assert strategy_header[1] == 'blue', f"Expected 'blue' strategy header, got {strategy_header[1]}"
        return mock_response
    
    mock_connection.status.side_effect = mock_status_with_counter
    
    with patch.object(type(manager), '_get_connection', new_callable=lambda: property(lambda self: mock_connection)):
        # Make multiple calls
        for i in range(3):
            result = manager._try_cluster_request('status')
            current_strategy = _get_active_strategy()
            assert current_strategy == 'blue', f"Strategy should persist across calls, got {current_strategy}"
    
    assert call_count == 3, f"Expected 3 calls, got {call_count}"
    print(f"✓ Strategy persisted across {call_count} calls")
    
    # Test 3: Test strategy switching by manually setting different strategy
    print("\n3. Testing strategy switching...")
    
    # Manually set strategy to green
    _set_active_strategy('green')
    current_strategy = _get_active_strategy()
    assert current_strategy == 'green', f"Expected 'green' strategy after manual set, got {current_strategy}"
    print(f"✓ Strategy switched to '{current_strategy}' manually")
    
    # Test 4: Test strategy persistence after switching
    print("\n4. Testing strategy persistence after switching...")
    
    call_count = 0
    def mock_status_with_green(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Should use green strategy now
        metadata = kwargs.get('metadata', [])
        strategy_header = next((header for header in metadata if header[0] == 'strategy'), None)
        assert strategy_header[1] == 'green', f"Should use green strategy, got {strategy_header[1]}"
        return mock_response
    
    mock_connection.status.side_effect = mock_status_with_green
    
    with patch.object(type(manager), '_get_connection', new_callable=lambda: property(lambda self: mock_connection)):
        # Make multiple calls - should all use green
        for i in range(3):
            result = manager._try_cluster_request('status')
            current_strategy = _get_active_strategy()
            assert current_strategy == 'green', f"Strategy should persist as green, got {current_strategy}"
    
    assert call_count == 3, f"Expected 3 calls, got {call_count}"
    print(f"✓ Strategy persisted as 'green' across {call_count} calls")
    
    print("\n=== Strategy Persistence Test Complete ===")
    return True


def test_cluster_resume_integration():
    """Test that strategy persists through the full cluster resume flow."""
    
    from e6data_python_connector.cluster_manager import ClusterManager
    from e6data_python_connector.strategy import _clear_strategy_cache, _get_active_strategy
    
    print("\n=== Testing Cluster Resume Integration ===\n")
    
    # Clear strategy cache
    _clear_strategy_cache()
    
    # Initialize ClusterManager
    manager = ClusterManager(
        host='localhost',
        port=50051,
        user='test@example.com',
        password='test-token',
        cluster_uuid='test-cluster'
    )
    
    # Mock cluster responses
    mock_connection = Mock()
    
    # Mock suspended status response
    suspended_response = Mock()
    suspended_response.status = 'suspended'
    suspended_response.new_strategy = None
    
    # Mock resume response
    resume_response = Mock()
    resume_response.status = 'resuming'
    resume_response.new_strategy = None
    
    # Mock active status response
    active_response = Mock()
    active_response.status = 'active'
    active_response.new_strategy = None
    
    # Sequence of responses for resume flow
    call_count = 0
    def mock_resume_flow(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        
        if call_count == 1:
            # First call: status check returns suspended
            return suspended_response
        else:
            # Subsequent calls: status checks return active
            return active_response
    
    mock_connection.status.side_effect = mock_resume_flow
    mock_connection.resume.return_value = resume_response
    
    with patch.object(type(manager), '_get_connection', new_callable=lambda: property(lambda self: mock_connection)):
        # Test initial status check
        result = manager._try_cluster_request('status')
        assert result.status == 'suspended'
        
        # Verify strategy was set during status check
        current_strategy = _get_active_strategy()
        assert current_strategy == 'blue', f"Expected 'blue' strategy after status check, got {current_strategy}"
        print(f"✓ Strategy set to '{current_strategy}' during initial status check")
        
        # Test resume request
        result = manager._try_cluster_request('resume')
        assert result.status == 'resuming'
        
        # Verify strategy persisted
        current_strategy = _get_active_strategy()
        assert current_strategy == 'blue', f"Strategy should persist during resume, got {current_strategy}"
        print(f"✓ Strategy persisted as '{current_strategy}' during resume request")
        
        # Test final status check
        result = manager._try_cluster_request('status')
        assert result.status == 'active'
        
        # Verify strategy still persisted
        current_strategy = _get_active_strategy()
        assert current_strategy == 'blue', f"Strategy should persist after resume complete, got {current_strategy}"
        print(f"✓ Strategy persisted as '{current_strategy}' after resume complete")
    
    print("\n=== Cluster Resume Integration Test Complete ===")
    return True


def main():
    """Run all tests."""
    try:
        test_strategy_persistence_after_resume()
        test_cluster_resume_integration()
        print("\n🎉 All tests passed! Strategy persistence after cluster resume is working correctly.")
        return True
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)