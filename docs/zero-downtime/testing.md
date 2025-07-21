# Zero Downtime Deployment - Testing Documentation

## Overview

This document provides comprehensive testing strategies, test cases, and tools for validating zero downtime deployment functionality in the e6data Python Connector.

## Testing Strategy

### 1. Testing Pyramid

```
┌─────────────────────────────────────────────┐
│              E2E Tests (10%)                │
│         Integration Tests (20%)             │
│            Unit Tests (70%)                 │
└─────────────────────────────────────────────┘
```

### 2. Test Categories

#### Unit Tests
- Strategy detection logic
- Cache management
- Error handling
- State transitions
- Validation functions

#### Integration Tests
- gRPC communication
- Database operations
- Strategy switching
- Error recovery
- Performance benchmarks

#### End-to-End Tests
- Complete application workflows
- Production-like scenarios
- Load testing
- Failover testing

## Unit Tests

### 1. Strategy Management Tests

```python
import unittest
from unittest.mock import Mock, patch
from e6data_python_connector.e6data_grpc import (
    _get_active_strategy, _set_active_strategy, _clear_strategy_cache,
    _set_pending_strategy, _apply_pending_strategy
)

class TestStrategyManagement(unittest.TestCase):
    
    def setUp(self):
        """Setup test environment"""
        _clear_strategy_cache()
    
    def test_set_and_get_active_strategy(self):
        """Test basic strategy setting and retrieval"""
        # Test valid strategies
        _set_active_strategy("blue")
        self.assertEqual(_get_active_strategy(), "blue")
        
        _set_active_strategy("GREEN")  # Test case insensitive
        self.assertEqual(_get_active_strategy(), "green")
    
    def test_invalid_strategy_values(self):
        """Test handling of invalid strategy values"""
        # Test invalid strategy
        _set_active_strategy("invalid")
        self.assertIsNone(_get_active_strategy())
        
        # Test None strategy
        _set_active_strategy(None)
        self.assertIsNone(_get_active_strategy())
    
    def test_pending_strategy_logic(self):
        """Test pending strategy management"""
        # Set initial strategy
        _set_active_strategy("blue")
        
        # Set pending strategy
        _set_pending_strategy("green")
        
        # Active strategy should remain unchanged
        self.assertEqual(_get_active_strategy(), "blue")
        
        # Apply pending strategy
        _apply_pending_strategy()
        
        # Active strategy should now be updated
        self.assertEqual(_get_active_strategy(), "green")
    
    def test_strategy_cache_expiration(self):
        """Test strategy cache expiration logic"""
        with patch('time.time') as mock_time:
            # Set initial time
            mock_time.return_value = 1000
            _set_active_strategy("blue")
            
            # Strategy should be cached
            self.assertEqual(_get_active_strategy(), "blue")
            
            # Advance time beyond cache timeout
            mock_time.return_value = 1400  # 400 seconds later
            
            # Strategy should still be cached (we disabled expiration)
            self.assertEqual(_get_active_strategy(), "blue")
    
    def test_clear_strategy_cache(self):
        """Test cache clearing functionality"""
        _set_active_strategy("blue")
        self.assertEqual(_get_active_strategy(), "blue")
        
        _clear_strategy_cache()
        self.assertIsNone(_get_active_strategy())
```

### 2. Query Strategy Mapping Tests

```python
import unittest
from e6data_python_connector.e6data_grpc import (
    _register_query_strategy, _get_query_strategy, _cleanup_query_strategy
)

class TestQueryStrategyMapping(unittest.TestCase):
    
    def setUp(self):
        """Setup test environment"""
        _clear_strategy_cache()
    
    def test_query_strategy_registration(self):
        """Test query strategy registration"""
        query_id = "test_query_123"
        strategy = "blue"
        
        _register_query_strategy(query_id, strategy)
        retrieved_strategy = _get_query_strategy(query_id)
        
        self.assertEqual(retrieved_strategy, strategy)
    
    def test_query_strategy_cleanup(self):
        """Test query strategy cleanup"""
        query_id = "test_query_456"
        strategy = "green"
        
        _register_query_strategy(query_id, strategy)
        self.assertEqual(_get_query_strategy(query_id), strategy)
        
        _cleanup_query_strategy(query_id)
        # Should fall back to active strategy
        self.assertIsNone(_get_query_strategy(query_id))
    
    def test_query_strategy_fallback(self):
        """Test fallback to active strategy"""
        _set_active_strategy("blue")
        
        # Query not registered should use active strategy
        strategy = _get_query_strategy("nonexistent_query")
        self.assertEqual(strategy, "blue")
```

### 3. Error Handling Tests

```python
import unittest
from unittest.mock import Mock, patch
from grpc import StatusCode, RpcError
from e6data_python_connector.e6data_grpc import re_auth, _InactiveRpcError

class TestErrorHandling(unittest.TestCase):
    
    def test_456_error_handling(self):
        """Test 456 error handling and retry logic"""
        mock_connection = Mock()
        mock_connection.get_re_authenticate_session_id = Mock()
        
        # Create a mock function that fails with 456 error then succeeds
        call_count = 0
        def mock_function(self):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                error = _InactiveRpcError(Mock())
                error.code = Mock(return_value=StatusCode.UNKNOWN)
                error.details = Mock(return_value="status: 456")
                raise error
            return "success"
        
        # Apply decorator
        decorated_function = re_auth(mock_function)
        
        # Create mock instance
        mock_instance = Mock()
        mock_instance.connection = mock_connection
        
        # Test retry logic
        result = decorated_function(mock_instance)
        
        self.assertEqual(result, "success")
        self.assertEqual(call_count, 2)
        mock_connection.get_re_authenticate_session_id.assert_called_once()
    
    def test_authentication_error_handling(self):
        """Test authentication error handling"""
        mock_connection = Mock()
        mock_connection.get_re_authenticate_session_id = Mock()
        
        # Create a mock function that fails with auth error then succeeds
        call_count = 0
        def mock_function(self):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                error = _InactiveRpcError(Mock())
                error.code = Mock(return_value=StatusCode.INTERNAL)
                error.details = Mock(return_value="Access denied")
                raise error
            return "success"
        
        # Apply decorator
        decorated_function = re_auth(mock_function)
        
        # Create mock instance
        mock_instance = Mock()
        mock_instance.connection = mock_connection
        
        # Test retry logic
        result = decorated_function(mock_instance)
        
        self.assertEqual(result, "success")
        self.assertEqual(call_count, 2)
        mock_connection.get_re_authenticate_session_id.assert_called_once()
```

## Integration Tests

### 1. Strategy Detection Integration Tests

```python
import unittest
from unittest.mock import Mock, patch
from e6data_python_connector.e6data_grpc import Connection

class TestStrategyDetectionIntegration(unittest.TestCase):
    
    def setUp(self):
        """Setup test environment"""
        self.host = "localhost"
        self.port = 50052
        self.username = "test@example.com"
        self.password = "test-token"
    
    @patch('e6data_python_connector.e6data_grpc.grpc.insecure_channel')
    @patch('e6data_python_connector.e6data_grpc.e6x_engine_pb2_grpc.QueryEngineServiceStub')
    def test_strategy_detection_blue_first(self, mock_stub, mock_channel):
        """Test strategy detection when blue works first"""
        # Mock successful blue authentication
        mock_client = Mock()
        mock_response = Mock()
        mock_response.sessionId = "test_session_123"
        mock_client.authenticate.return_value = mock_response
        mock_stub.return_value = mock_client
        
        # Create connection
        conn = Connection(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password
        )
        
        # Test authentication
        session_id = conn.get_session_id
        
        self.assertEqual(session_id, "test_session_123")
        
        # Verify blue strategy was tried first
        auth_calls = mock_client.authenticate.call_args_list
        self.assertEqual(len(auth_calls), 1)
        
        # Check metadata for blue strategy
        metadata = auth_calls[0][1]['metadata']
        strategy_header = next((item for item in metadata if item[0] == 'strategy'), None)
        self.assertIsNotNone(strategy_header)
        self.assertEqual(strategy_header[1], 'blue')
    
    @patch('e6data_python_connector.e6data_grpc.grpc.insecure_channel')
    @patch('e6data_python_connector.e6data_grpc.e6x_engine_pb2_grpc.QueryEngineServiceStub')
    def test_strategy_detection_fallback_to_green(self, mock_stub, mock_channel):
        """Test strategy detection fallback to green"""
        # Mock blue failure, green success
        mock_client = Mock()
        
        def mock_authenticate(request, metadata=None):
            # Check strategy in metadata
            strategy_header = next((item for item in metadata if item[0] == 'strategy'), None)
            if strategy_header and strategy_header[1] == 'blue':
                # Blue fails with 456
                error = _InactiveRpcError(Mock())
                error.code = Mock(return_value=StatusCode.UNKNOWN)
                error.details = Mock(return_value="status: 456")
                raise error
            else:
                # Green succeeds
                response = Mock()
                response.sessionId = "test_session_456"
                return response
        
        mock_client.authenticate.side_effect = mock_authenticate
        mock_stub.return_value = mock_client
        
        # Create connection
        conn = Connection(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password
        )
        
        # Test authentication
        session_id = conn.get_session_id
        
        self.assertEqual(session_id, "test_session_456")
        
        # Verify both strategies were tried
        auth_calls = mock_client.authenticate.call_args_list
        self.assertEqual(len(auth_calls), 2)
```

### 2. Query Execution Integration Tests

```python
import unittest
from unittest.mock import Mock, patch
from e6data_python_connector.e6data_grpc import Connection

class TestQueryExecutionIntegration(unittest.TestCase):
    
    def setUp(self):
        """Setup test environment"""
        self.connection = Mock()
        self.connection.get_session_id = "test_session"
        self.connection.cluster_uuid = "test_cluster"
        self.connection.client = Mock()
        self.connection.grpc_prepare_timeout = 600
    
    def test_query_execution_with_strategy_transition(self):
        """Test query execution during strategy transition"""
        from e6data_python_connector.e6data_grpc import Cursor
        
        # Mock prepare response with new strategy
        prepare_response = Mock()
        prepare_response.queryId = "test_query_123"
        prepare_response.engineIP = "127.0.0.1"
        prepare_response.new_strategy = "green"
        
        # Mock execute response
        execute_response = Mock()
        
        # Mock metadata response
        metadata_response = Mock()
        metadata_response.resultMetaData = b"mock_metadata"
        
        self.connection.client.prepareStatementV2.return_value = prepare_response
        self.connection.client.executeStatementV2.return_value = execute_response
        self.connection.client.getResultMetadata.return_value = metadata_response
        
        # Create cursor
        cursor = Cursor(self.connection, catalog_name="test_catalog")
        
        # Mock get_query_columns_info
        with patch('e6data_python_connector.e6data_grpc.get_query_columns_info') as mock_columns:
            mock_columns.return_value = (10, [])
            
            # Execute query
            query_id = cursor.execute("SELECT 1")
            
            self.assertEqual(query_id, "test_query_123")
            
            # Verify prepare was called
            self.connection.client.prepareStatementV2.assert_called_once()
            
            # Verify execute was called
            self.connection.client.executeStatementV2.assert_called_once()
            
            # Verify pending strategy was set
            # This would need access to internal state
```

## Mock Server Tests

### 1. Mock Server Strategy Tests

```python
import unittest
import threading
import time
from unittest.mock import patch
import grpc
from e6data_python_connector.e6data_grpc import Connection

class TestMockServerStrategy(unittest.TestCase):
    
    def setUp(self):
        """Setup mock server for testing"""
        # Start mock server in background
        self.mock_server_thread = threading.Thread(
            target=self.start_mock_server,
            daemon=True
        )
        self.mock_server_thread.start()
        time.sleep(1)  # Wait for server to start
    
    def start_mock_server(self):
        """Start mock gRPC server"""
        # This would start the actual mock server
        # For testing purposes, we'll simulate it
        pass
    
    def test_mock_server_strategy_switching(self):
        """Test strategy switching with mock server"""
        # This test would connect to the mock server
        # and verify strategy switching behavior
        pass
    
    def test_mock_server_456_error_simulation(self):
        """Test 456 error simulation with mock server"""
        # This test would simulate 456 errors
        # and verify recovery behavior
        pass
```

## Performance Tests

### 1. Strategy Detection Performance

```python
import unittest
import time
from statistics import mean, stdev
from e6data_python_connector.e6data_grpc import (
    _get_active_strategy, _set_active_strategy, _clear_strategy_cache
)

class TestStrategyPerformance(unittest.TestCase):
    
    def test_cached_strategy_performance(self):
        """Test performance of cached strategy lookup"""
        # Setup cache
        _set_active_strategy("blue")
        
        # Measure cache hit performance
        times = []
        for i in range(1000):
            start_time = time.perf_counter()
            strategy = _get_active_strategy()
            end_time = time.perf_counter()
            times.append(end_time - start_time)
        
        avg_time = mean(times)
        std_time = stdev(times)
        
        # Cache hits should be very fast
        self.assertLess(avg_time, 0.001)  # Less than 1ms
        self.assertLess(std_time, 0.0005)  # Low variance
        
        print(f"Cache hit performance: {avg_time:.6f}s ± {std_time:.6f}s")
    
    def test_strategy_transition_performance(self):
        """Test performance of strategy transitions"""
        times = []
        
        for i in range(100):
            _set_active_strategy("blue")
            
            start_time = time.perf_counter()
            _set_active_strategy("green")
            end_time = time.perf_counter()
            
            times.append(end_time - start_time)
        
        avg_time = mean(times)
        
        # Strategy transitions should be reasonably fast
        self.assertLess(avg_time, 0.01)  # Less than 10ms
        
        print(f"Strategy transition performance: {avg_time:.6f}s")
```

### 2. Concurrent Access Performance

```python
import unittest
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from e6data_python_connector.e6data_grpc import _get_active_strategy, _set_active_strategy

class TestConcurrentPerformance(unittest.TestCase):
    
    def test_concurrent_strategy_access(self):
        """Test concurrent access to strategy functions"""
        _set_active_strategy("blue")
        
        def worker():
            """Worker function for concurrent access"""
            results = []
            for i in range(100):
                start_time = time.perf_counter()
                strategy = _get_active_strategy()
                end_time = time.perf_counter()
                results.append((strategy, end_time - start_time))
            return results
        
        # Run concurrent workers
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker) for _ in range(10)]
            all_results = []
            for future in futures:
                all_results.extend(future.result())
        
        # Verify all results are consistent
        strategies = [result[0] for result in all_results]
        self.assertTrue(all(s == "blue" for s in strategies))
        
        # Check performance
        times = [result[1] for result in all_results]
        avg_time = sum(times) / len(times)
        
        self.assertLess(avg_time, 0.01)  # Less than 10ms under load
        
        print(f"Concurrent access performance: {avg_time:.6f}s")
```

## Load Testing

### 1. Connection Load Test

```python
import unittest
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from e6data_python_connector.e6data_grpc import Connection

class TestConnectionLoad(unittest.TestCase):
    
    def test_concurrent_connections(self):
        """Test multiple concurrent connections"""
        connection_params = {
            'host': 'localhost',
            'port': 50052,
            'username': 'test@example.com',
            'password': 'test-token'
        }
        
        def create_connection():
            """Create a connection and perform basic operation"""
            try:
                conn = Connection(**connection_params)
                session_id = conn.get_session_id
                conn.close()
                return True, session_id
            except Exception as e:
                return False, str(e)
        
        # Test with multiple concurrent connections
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(create_connection) for _ in range(50)]
            results = [future.result() for future in futures]
        
        # Analyze results
        successful = sum(1 for success, _ in results if success)
        success_rate = successful / len(results)
        
        self.assertGreater(success_rate, 0.9)  # 90% success rate
        
        print(f"Connection load test: {successful}/{len(results)} successful ({success_rate:.2%})")
```

### 2. Query Load Test

```python
import unittest
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from e6data_python_connector.e6data_grpc import Connection

class TestQueryLoad(unittest.TestCase):
    
    def test_concurrent_queries(self):
        """Test multiple concurrent queries"""
        connection_params = {
            'host': 'localhost',
            'port': 50052,
            'username': 'test@example.com',
            'password': 'test-token'
        }
        
        def execute_query():
            """Execute a query and return results"""
            try:
                conn = Connection(**connection_params)
                cursor = conn.cursor()
                
                start_time = time.perf_counter()
                cursor.execute("SELECT 1")
                results = cursor.fetchall()
                end_time = time.perf_counter()
                
                cursor.close()
                conn.close()
                
                return True, end_time - start_time, len(results)
            except Exception as e:
                return False, 0, str(e)
        
        # Test with multiple concurrent queries
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(execute_query) for _ in range(100)]
            results = [future.result() for future in futures]
        
        # Analyze results
        successful = sum(1 for success, _, _ in results if success)
        success_rate = successful / len(results)
        
        if successful > 0:
            avg_time = sum(time for success, time, _ in results if success) / successful
            print(f"Query load test: {successful}/{len(results)} successful ({success_rate:.2%})")
            print(f"Average query time: {avg_time:.4f}s")
        
        self.assertGreater(success_rate, 0.8)  # 80% success rate
```

## Test Utilities

### 1. Test Data Generator

```python
class TestDataGenerator:
    """Generate test data for various scenarios"""
    
    @staticmethod
    def generate_query_scenarios():
        """Generate various query scenarios"""
        return [
            {"query": "SELECT 1", "expected_rows": 1},
            {"query": "SELECT 1, 2, 3", "expected_rows": 1},
            {"query": "SELECT * FROM mock_table LIMIT 10", "expected_rows": 10},
            {"query": "SELECT COUNT(*) FROM mock_table", "expected_rows": 1},
        ]
    
    @staticmethod
    def generate_error_scenarios():
        """Generate error scenarios for testing"""
        return [
            {"error_type": "456", "description": "Strategy mismatch"},
            {"error_type": "auth", "description": "Authentication failure"},
            {"error_type": "timeout", "description": "Connection timeout"},
            {"error_type": "network", "description": "Network error"},
        ]
```

### 2. Test Assertions

```python
class StrategyTestAssertions:
    """Custom assertions for strategy testing"""
    
    @staticmethod
    def assert_valid_strategy(strategy):
        """Assert strategy is valid"""
        assert strategy in ['blue', 'green'], f"Invalid strategy: {strategy}"
    
    @staticmethod
    def assert_strategy_transition(old_strategy, new_strategy):
        """Assert valid strategy transition"""
        assert old_strategy != new_strategy, "Strategy should change"
        assert old_strategy in ['blue', 'green'], f"Invalid old strategy: {old_strategy}"
        assert new_strategy in ['blue', 'green'], f"Invalid new strategy: {new_strategy}"
    
    @staticmethod
    def assert_query_strategy_consistency(query_id, expected_strategy):
        """Assert query uses consistent strategy"""
        from e6data_python_connector.e6data_grpc import _get_query_strategy
        actual_strategy = _get_query_strategy(query_id)
        assert actual_strategy == expected_strategy, \
            f"Query {query_id} strategy mismatch: expected {expected_strategy}, got {actual_strategy}"
```

## Test Configuration

### 1. Test Environment Setup

```python
import os
import tempfile
from unittest.mock import patch

class TestEnvironment:
    """Test environment configuration"""
    
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_config = {
            'host': 'localhost',
            'port': 50052,
            'username': 'test@example.com',
            'password': 'test-token',
            'secure': False
        }
    
    def setup_test_environment(self):
        """Setup test environment"""
        # Set environment variables
        os.environ['E6DATA_TEST_MODE'] = 'true'
        os.environ['E6DATA_LOG_LEVEL'] = 'DEBUG'
        
        # Mock external dependencies
        self.setup_mocks()
    
    def setup_mocks(self):
        """Setup common mocks"""
        # Mock multiprocessing.Manager for testing
        with patch('multiprocessing.Manager') as mock_manager:
            mock_manager.return_value.dict.return_value = {}
            yield mock_manager
    
    def cleanup_test_environment(self):
        """Cleanup test environment"""
        # Clean up environment variables
        if 'E6DATA_TEST_MODE' in os.environ:
            del os.environ['E6DATA_TEST_MODE']
        if 'E6DATA_LOG_LEVEL' in os.environ:
            del os.environ['E6DATA_LOG_LEVEL']
        
        # Clean up temp directory
        import shutil
        shutil.rmtree(self.temp_dir)
```

## Running Tests

### 1. Test Execution Commands

```bash
# Run all tests
python -m pytest docs/zero-downtime/

# Run specific test categories
python -m pytest docs/zero-downtime/ -k "unit"
python -m pytest docs/zero-downtime/ -k "integration"
python -m pytest docs/zero-downtime/ -k "performance"

# Run with coverage
python -m pytest docs/zero-downtime/ --cov=e6data_python_connector

# Run with verbose output
python -m pytest docs/zero-downtime/ -v

# Run specific test file
python -m pytest docs/zero-downtime/test_strategy_management.py
```

### 2. Test Reporting

```python
# Generate test report
python -m pytest docs/zero-downtime/ --html=test_report.html

# Generate coverage report
python -m pytest docs/zero-downtime/ --cov=e6data_python_connector --cov-report=html
```

This comprehensive testing documentation provides a complete framework for validating zero downtime deployment functionality across all levels of the system.