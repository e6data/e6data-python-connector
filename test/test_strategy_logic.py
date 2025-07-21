#!/usr/bin/env python3
"""
Test script to verify the strategy logic works correctly.
"""

import sys
import time
import logging
from e6data_python_connector.e6data_grpc import Connection, _get_active_strategy, _get_shared_strategy, _clear_strategy_cache

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def test_strategy_logic():
    """Test the strategy logic with mock server"""
    
    # Connection parameters for mock server
    host = "localhost"
    port = 50052
    username = "test@example.com"
    password = "test-token"
    
    print("=== Testing Strategy Logic ===\n")
    
    # Clear any existing strategy cache
    _clear_strategy_cache()
    
    # Test 1: Initial connection should try blue first
    print("1. Testing initial connection...")
    try:
        conn1 = Connection(host=host, port=port, username=username, password=password)
        session1 = conn1.get_session_id
        strategy1 = _get_active_strategy()
        print(f"   Initial strategy: {strategy1}")
        
        # Check strategy state
        shared_state = _get_shared_strategy()
        print(f"   Shared state: active={shared_state.get('active_strategy')}, pending={shared_state.get('pending_strategy')}")
        
        conn1.close()
    except Exception as e:
        print(f"   Error: {e}")
    
    print()
    
    # Test 2: Second connection should use same strategy if no change
    print("2. Testing second connection with same strategy...")
    try:
        conn2 = Connection(host=host, port=port, username=username, password=password)
        session2 = conn2.get_session_id
        strategy2 = _get_active_strategy()
        print(f"   Second connection strategy: {strategy2}")
        
        conn2.close()
    except Exception as e:
        print(f"   Error: {e}")
    
    print()
    
    # Test 3: Execute a query to trigger strategy change
    print("3. Testing query execution with strategy change...")
    try:
        conn3 = Connection(host=host, port=port, username=username, password=password)
        cursor = conn3.cursor()
        
        # Execute a query
        cursor.execute("SELECT 1")
        result = cursor.fetchall()
        print(f"   Query result: {result}")
        
        # Check strategy state after query
        shared_state = _get_shared_strategy()
        print(f"   After query - active={shared_state.get('active_strategy')}, pending={shared_state.get('pending_strategy')}")
        
        cursor.close()
        conn3.close()
    except Exception as e:
        print(f"   Error: {e}")
    
    print()
    
    # Test 4: New connection should use new strategy
    print("4. Testing new connection after strategy change...")
    try:
        conn4 = Connection(host=host, port=port, username=username, password=password)
        session4 = conn4.get_session_id
        strategy4 = _get_active_strategy()
        print(f"   New connection strategy: {strategy4}")
        
        # Check strategy state
        shared_state = _get_shared_strategy()
        print(f"   Final state: active={shared_state.get('active_strategy')}, pending={shared_state.get('pending_strategy')}")
        
        conn4.close()
    except Exception as e:
        print(f"   Error: {e}")
    
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    test_strategy_logic()