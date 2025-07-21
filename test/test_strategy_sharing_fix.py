#!/usr/bin/env python3
"""Test that strategy sharing works correctly between ClusterManager and e6data_grpc."""

import sys
import os
import time

# Add the project directory to the Python path
sys.path.insert(0, os.path.dirname(__file__))

def test_strategy_sharing():
    """Test that ClusterManager and e6data_grpc share the same strategy state."""
    
    print("🔧 Testing Strategy Sharing Fix")
    print("=" * 50)
    
    # Import the modules
    from e6data_python_connector.cluster_manager import _get_active_strategy as cm_get_active
    from e6data_python_connector.cluster_manager import _set_active_strategy as cm_set_active
    from e6data_python_connector.e6data_grpc import _get_active_strategy as grpc_get_active
    from e6data_python_connector.e6data_grpc import _get_shared_strategy as grpc_get_shared
    from e6data_python_connector.strategy import _get_active_strategy as strategy_get_active
    from e6data_python_connector.strategy import _set_active_strategy as strategy_set_active
    from e6data_python_connector.strategy import _clear_strategy_cache
    
    # Clear any existing state
    _clear_strategy_cache()
    
    print("\n1️⃣ Test Initial State")
    print("-" * 30)
    
    # Check initial state - should all be None
    cm_initial = cm_get_active()
    grpc_initial = grpc_get_active()
    strategy_initial = strategy_get_active()
    
    print(f"ClusterManager initial: {cm_initial}")
    print(f"e6data_grpc initial: {grpc_initial}")
    print(f"Strategy module initial: {strategy_initial}")
    
    if cm_initial is None and grpc_initial is None and strategy_initial is None:
        print("✅ Initial state is correct (all None)")
    else:
        print("❌ Initial state is incorrect")
        return False
    
    print("\n2️⃣ Test ClusterManager Setting Strategy")
    print("-" * 30)
    
    # Set strategy via ClusterManager
    cm_set_active('blue')
    time.sleep(0.1)  # Small delay for any async operations
    
    # Check if all modules see the same strategy
    cm_after = cm_get_active()
    grpc_after = grpc_get_active()
    strategy_after = strategy_get_active()
    
    print(f"ClusterManager after setting: {cm_after}")
    print(f"e6data_grpc after setting: {grpc_after}")
    print(f"Strategy module after setting: {strategy_after}")
    
    if cm_after == 'blue' and grpc_after == 'blue' and strategy_after == 'blue':
        print("✅ Strategy sharing works correctly!")
    else:
        print("❌ Strategy sharing is broken")
        return False
    
    print("\n3️⃣ Test Strategy Module Setting Strategy")
    print("-" * 30)
    
    # Set strategy via strategy module directly
    strategy_set_active('green')
    time.sleep(0.1)  # Small delay for any async operations
    
    # Check if all modules see the new strategy
    cm_green = cm_get_active()
    grpc_green = grpc_get_active()
    strategy_green = strategy_get_active()
    
    print(f"ClusterManager after green: {cm_green}")
    print(f"e6data_grpc after green: {grpc_green}")
    print(f"Strategy module after green: {strategy_green}")
    
    if cm_green == 'green' and grpc_green == 'green' and strategy_green == 'green':
        print("✅ Strategy sharing works in both directions!")
    else:
        print("❌ Strategy sharing is broken in reverse direction")
        return False
    
    print("\n4️⃣ Test Shared State Access")
    print("-" * 30)
    
    # Test accessing shared state directly
    shared_state = grpc_get_shared()
    print(f"Shared state: {dict(shared_state)}")
    
    active_from_shared = shared_state.get('active_strategy')
    print(f"Active strategy from shared state: {active_from_shared}")
    
    if active_from_shared == 'green':
        print("✅ Shared state access works correctly!")
    else:
        print("❌ Shared state access is broken")
        return False
    
    print("\n5️⃣ Test Cache Clearing")
    print("-" * 30)
    
    # Clear the cache
    _clear_strategy_cache()
    time.sleep(0.1)  # Small delay for any async operations
    
    # Check if all modules see None again
    cm_cleared = cm_get_active()
    grpc_cleared = grpc_get_active()
    strategy_cleared = strategy_get_active()
    
    print(f"ClusterManager after clear: {cm_cleared}")
    print(f"e6data_grpc after clear: {grpc_cleared}")
    print(f"Strategy module after clear: {strategy_cleared}")
    
    if cm_cleared is None and grpc_cleared is None and strategy_cleared is None:
        print("✅ Cache clearing works correctly!")
    else:
        print("❌ Cache clearing is broken")
        return False
    
    print("\n" + "=" * 50)
    print("🎉 ALL TESTS PASSED!")
    print("The strategy sharing fix is working correctly.")
    print("ClusterManager and e6data_grpc now use the same strategy state.")
    
    return True

if __name__ == "__main__":
    success = test_strategy_sharing()
    if success:
        print("\n✅ Strategy sharing fix verified!")
    else:
        print("\n❌ Strategy sharing fix needs more work!")
    sys.exit(0 if success else 1)