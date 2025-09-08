"""
Comprehensive test suite for ConnectionPool implementation.
"""

import concurrent.futures
import logging
import threading
import time
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from e6data_python_connector.connection_pool import ConnectionPool, PooledConnection
from e6data_python_connector.e6data_grpc import Connection

# Configure logging for tests
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class TestConnectionPool(unittest.TestCase):
    """Test cases for ConnectionPool functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_connection_params = {
            'host': 'test.e6data.com',
            'port': 443,
            'username': 'test@e6data.com',
            'password': 'test_token',
            'database': 'test_db',
            'cluster_name': 'test_cluster',
            'secure': True
        }
    
    @patch('e6data_python_connector.connection_pool.Connection')
    def test_pool_initialization(self, mock_connection_class):
        """Test that pool initializes with minimum connections."""
        mock_connection_class.return_value = MagicMock(spec=Connection)
        
        pool = ConnectionPool(
            min_size=3,
            max_size=10,
            **self.mock_connection_params
        )
        
        # Check that minimum connections were created
        self.assertEqual(mock_connection_class.call_count, 3)
        
        stats = pool.get_statistics()
        self.assertEqual(stats['created_connections'], 3)
        self.assertEqual(stats['idle_connections'], 3)
        self.assertEqual(stats['active_connections'], 0)
        
        pool.close_all()
    
    @patch('e6data_python_connector.connection_pool.Connection')
    def test_get_and_return_connection(self, mock_connection_class):
        """Test getting and returning connections from pool."""
        mock_conn = MagicMock(spec=Connection)
        mock_conn.check_connection.return_value = True
        mock_conn.get_session_id = PropertyMock(return_value='test_session')
        mock_connection_class.return_value = mock_conn
        
        pool = ConnectionPool(
            min_size=2,
            max_size=5,
            **self.mock_connection_params
        )
        
        # Get a connection
        conn1 = pool.get_connection()
        self.assertIsInstance(conn1, PooledConnection)
        self.assertTrue(conn1.in_use)
        
        stats = pool.get_statistics()
        self.assertEqual(stats['active_connections'], 1)
        
        # Return the connection
        pool.return_connection(conn1)
        self.assertFalse(conn1.in_use)
        
        stats = pool.get_statistics()
        self.assertEqual(stats['active_connections'], 0)
        
        pool.close_all()
    
    @patch('e6data_python_connector.connection_pool.Connection')
    def test_thread_connection_reuse(self, mock_connection_class):
        """Test that same thread reuses its connection."""
        mock_conn = MagicMock(spec=Connection)
        mock_conn.check_connection.return_value = True
        mock_conn.get_session_id = PropertyMock(return_value='test_session')
        mock_connection_class.return_value = mock_conn
        
        pool = ConnectionPool(
            min_size=1,
            max_size=5,
            **self.mock_connection_params
        )
        
        # Get connection twice from same thread
        conn1 = pool.get_connection()
        conn2 = pool.get_connection()
        
        # Should be the same connection
        self.assertIs(conn1, conn2)
        self.assertEqual(conn1.use_count, 2)
        
        pool.close_all()
    
    @patch('e6data_python_connector.connection_pool.Connection')
    def test_concurrent_access(self, mock_connection_class):
        """Test concurrent access from multiple threads."""
        mock_conn = MagicMock(spec=Connection)
        mock_conn.check_connection.return_value = True
        mock_conn.get_session_id = PropertyMock(return_value='test_session')
        mock_connection_class.return_value = mock_conn
        
        pool = ConnectionPool(
            min_size=2,
            max_size=10,
            debug=True,
            **self.mock_connection_params
        )
        
        results = []
        lock = threading.Lock()
        
        def worker(worker_id):
            """Worker function for concurrent test."""
            try:
                conn = pool.get_connection()
                thread_id = threading.get_ident()
                
                with lock:
                    results.append({
                        'worker_id': worker_id,
                        'thread_id': thread_id,
                        'connection': conn
                    })
                
                # Simulate work
                time.sleep(0.1)
                
                pool.return_connection(conn)
                return True
            except Exception as e:
                logger.error(f"Worker {worker_id} failed: {e}")
                return False
        
        # Run workers concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker, i) for i in range(10)]
            success = all(f.result() for f in concurrent.futures.as_completed(futures))
        
        self.assertTrue(success)
        self.assertEqual(len(results), 10)
        
        # Check statistics
        stats = pool.get_statistics()
        self.assertGreater(stats['total_requests'], 0)
        
        pool.close_all()
    
    @patch('e6data_python_connector.connection_pool.Connection')
    def test_context_manager(self, mock_connection_class):
        """Test context manager for automatic connection return."""
        mock_conn = MagicMock(spec=Connection)
        mock_conn.check_connection.return_value = True
        mock_conn.get_session_id = PropertyMock(return_value='test_session')
        mock_connection_class.return_value = mock_conn
        
        pool = ConnectionPool(
            min_size=1,
            max_size=5,
            **self.mock_connection_params
        )
        
        # Use context manager
        with pool.get_connection_context() as conn:
            self.assertIsInstance(conn, PooledConnection)
            self.assertTrue(conn.in_use)
            stats_during = pool.get_statistics()
            self.assertEqual(stats_during['active_connections'], 1)
        
        # After context, connection should be returned
        stats_after = pool.get_statistics()
        self.assertEqual(stats_after['active_connections'], 0)
        
        pool.close_all()
    
    @patch('e6data_python_connector.connection_pool.Connection')
    def test_connection_health_check(self, mock_connection_class):
        """Test connection health checking and replacement."""
        # Create a connection that becomes unhealthy
        mock_conn = MagicMock(spec=Connection)
        mock_conn.check_connection.side_effect = [True, True, False, True]
        mock_conn.get_session_id = PropertyMock(return_value='test_session')
        
        # New connection for replacement
        mock_new_conn = MagicMock(spec=Connection)
        mock_new_conn.check_connection.return_value = True
        mock_new_conn.get_session_id = PropertyMock(return_value='new_session')
        
        mock_connection_class.side_effect = [mock_conn, mock_new_conn]
        
        pool = ConnectionPool(
            min_size=1,
            max_size=5,
            pre_ping=True,
            **self.mock_connection_params
        )
        
        # Get connection (healthy)
        conn1 = pool.get_connection()
        pool.return_connection(conn1)
        
        # Get connection again (now unhealthy, should be replaced)
        conn2 = pool.get_connection()
        
        # Should have created a new connection
        self.assertEqual(mock_connection_class.call_count, 2)
        
        pool.close_all()
    
    @patch('e6data_python_connector.connection_pool.Connection')
    def test_overflow_connections(self, mock_connection_class):
        """Test overflow connection creation when pool is exhausted."""
        mock_conn = MagicMock(spec=Connection)
        mock_conn.check_connection.return_value = True
        mock_conn.get_session_id = PropertyMock(return_value='test_session')
        mock_connection_class.return_value = mock_conn
        
        pool = ConnectionPool(
            min_size=1,
            max_size=2,
            max_overflow=2,
            **self.mock_connection_params
        )
        
        connections = []
        
        # Get connections up to max_size + max_overflow
        for i in range(4):
            conn = pool.get_connection(timeout=1)
            connections.append(conn)
        
        stats = pool.get_statistics()
        self.assertEqual(stats['created_connections'], 4)
        self.assertEqual(stats['overflow_connections'], 2)
        
        # Return all connections
        for conn in connections:
            pool.return_connection(conn)
        
        pool.close_all()
    
    @patch('e6data_python_connector.connection_pool.Connection')
    def test_timeout_when_pool_exhausted(self, mock_connection_class):
        """Test timeout when pool is exhausted and no overflow allowed."""
        mock_conn = MagicMock(spec=Connection)
        mock_conn.check_connection.return_value = True
        mock_conn.get_session_id = PropertyMock(return_value='test_session')
        mock_connection_class.return_value = mock_conn
        
        pool = ConnectionPool(
            min_size=1,
            max_size=1,
            max_overflow=0,
            timeout=0.5,
            **self.mock_connection_params
        )
        
        # Get the only connection
        conn1 = pool.get_connection()
        
        # Try to get another (should timeout)
        with self.assertRaises(TimeoutError):
            pool.get_connection(timeout=0.5)
        
        pool.return_connection(conn1)
        pool.close_all()
    
    @patch('e6data_python_connector.connection_pool.Connection')
    def test_connection_recycling(self, mock_connection_class):
        """Test connection recycling based on age."""
        mock_conn = MagicMock(spec=Connection)
        mock_conn.check_connection.return_value = True
        mock_conn.get_session_id = PropertyMock(return_value='test_session')
        
        mock_new_conn = MagicMock(spec=Connection)
        mock_new_conn.check_connection.return_value = True
        mock_new_conn.get_session_id = PropertyMock(return_value='new_session')
        
        mock_connection_class.side_effect = [mock_conn, mock_new_conn]
        
        pool = ConnectionPool(
            min_size=1,
            max_size=5,
            recycle=0.1,  # Very short recycle time for testing
            **self.mock_connection_params
        )
        
        # Get connection
        conn1 = pool.get_connection()
        pool.return_connection(conn1)
        
        # Wait for recycle time
        time.sleep(0.2)
        
        # Get connection again (should be recycled)
        conn2 = pool.get_connection()
        
        # Should have created a new connection
        self.assertEqual(mock_connection_class.call_count, 2)
        
        pool.close_all()
    
    @patch('e6data_python_connector.connection_pool.Connection')
    def test_statistics_tracking(self, mock_connection_class):
        """Test that pool tracks statistics correctly."""
        mock_conn = MagicMock(spec=Connection)
        mock_conn.check_connection.return_value = True
        mock_conn.get_session_id = PropertyMock(return_value='test_session')
        mock_connection_class.return_value = mock_conn
        
        pool = ConnectionPool(
            min_size=2,
            max_size=5,
            **self.mock_connection_params
        )
        
        initial_stats = pool.get_statistics()
        self.assertEqual(initial_stats['created_connections'], 2)
        self.assertEqual(initial_stats['total_requests'], 0)
        
        # Get and return connections
        conn1 = pool.get_connection()
        conn2 = pool.get_connection()
        
        stats = pool.get_statistics()
        self.assertGreater(stats['total_requests'], 0)
        self.assertEqual(stats['active_connections'], 1)  # Same thread reuses connection
        
        pool.return_connection(conn1)
        pool.return_connection(conn2)
        
        final_stats = pool.get_statistics()
        self.assertEqual(final_stats['active_connections'], 0)
        
        pool.close_all()


class TestPooledConnection(unittest.TestCase):
    """Test cases for PooledConnection wrapper."""
    
    @patch('e6data_python_connector.connection_pool.ConnectionPool')
    @patch('e6data_python_connector.connection_pool.Connection')
    def test_pooled_connection_cursor(self, mock_connection_class, mock_pool_class):
        """Test cursor creation and caching in pooled connection."""
        mock_conn = MagicMock(spec=Connection)
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.check_connection.return_value = True
        
        mock_pool = MagicMock(spec=ConnectionPool)
        
        pooled_conn = PooledConnection(mock_conn, mock_pool)
        
        # First cursor call should create new cursor
        cursor1 = pooled_conn.cursor()
        self.assertEqual(cursor1, mock_cursor)
        mock_conn.cursor.assert_called_once()
        
        # Second call should return cached cursor
        cursor2 = pooled_conn.cursor()
        self.assertEqual(cursor2, mock_cursor)
        self.assertEqual(mock_conn.cursor.call_count, 1)  # Still only called once
        
        # Close cursor
        pooled_conn.close_cursor()
        mock_cursor.close.assert_called_once()
        
        # After closing, new cursor should be created
        mock_conn.cursor.reset_mock()
        cursor3 = pooled_conn.cursor()
        mock_conn.cursor.assert_called_once()
    
    @patch('e6data_python_connector.connection_pool.ConnectionPool')
    @patch('e6data_python_connector.connection_pool.Connection')
    def test_pooled_connection_context_manager(self, mock_connection_class, mock_pool_class):
        """Test pooled connection as context manager."""
        mock_conn = MagicMock(spec=Connection)
        mock_pool = MagicMock(spec=ConnectionPool)
        
        pooled_conn = PooledConnection(mock_conn, mock_pool)
        
        with pooled_conn as conn:
            self.assertEqual(conn, pooled_conn)
        
        # Should return to pool on exit
        mock_pool.return_connection.assert_called_once_with(pooled_conn)


if __name__ == '__main__':
    unittest.main()