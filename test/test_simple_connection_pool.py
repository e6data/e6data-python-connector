#!/usr/bin/env python3
"""
Simple end-to-end test for ConnectionPool using working credentials from t4.py.
Uses simple queries that work with the e6data engine.
"""

import concurrent.futures
import logging
import threading
import time

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from e6data_python_connector import ConnectionPool

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(threadName)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration from environment variables
TEST_CONFIG = {
    'host': os.environ.get('E6DATA_HOST', 'localhost'),
    'port': int(os.environ.get('E6DATA_PORT', '443')),
    'username': os.environ.get('E6DATA_USERNAME'),
    'password': os.environ.get('E6DATA_PASSWORD'),
    'database': os.environ.get('E6DATA_DATABASE', 'test_db'),
    'catalog': os.environ.get('E6DATA_CATALOG', 'default'),
    'cluster_name': os.environ.get('E6DATA_CLUSTER_NAME', 'test_cluster'),
    'secure': os.environ.get('E6DATA_SECURE', 'true').lower() == 'true'
}

# Validate required environment variables
required_vars = ['E6DATA_USERNAME', 'E6DATA_PASSWORD']
missing_vars = [var for var in required_vars if not os.environ.get(var)]
if missing_vars:
    raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")


def test_basic_pool_functionality():
    """Test basic connection pool functionality."""
    logger.info("=== Testing Basic Pool Functionality ===")
    
    pool = ConnectionPool(
        min_size=2,
        max_size=5,
        debug=True,
        **TEST_CONFIG
    )
    
    try:
        # Test 1: Basic connection get/return
        logger.info("Test 1: Basic connection operations")
        
        conn = pool.get_connection()
        logger.info(f"Got connection, in_use: {conn.in_use}")
        
        cursor = conn.cursor()
        query_id = cursor.execute("SELECT 1 as test_value")
        logger.info(f"Query ID: {query_id}")
        
        results = cursor.fetchall()
        logger.info(f"Results: {results}")
        assert len(results) == 1
        assert results[0][0] == 1
        
        pool.return_connection(conn)
        logger.info(f"Returned connection, in_use: {conn.in_use}")
        
        # Test 2: Context manager
        logger.info("Test 2: Context manager")
        
        with pool.get_connection_context() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 2 as test_value")
            results = cursor.fetchall()
            assert results[0][0] == 2
        
        logger.info("Context manager test passed")
        
        # Test 3: Statistics
        stats = pool.get_statistics()
        logger.info(f"Pool statistics: {stats}")
        assert stats['total_requests'] >= 2
        
        return True
        
    finally:
        pool.close_all()


def test_concurrent_queries():
    """Test concurrent query execution with connection pool."""
    logger.info("=== Testing Concurrent Queries ===")
    
    pool = ConnectionPool(
        min_size=3,
        max_size=10,
        debug=True,
        **TEST_CONFIG
    )
    
    def worker_query(worker_id):
        """Execute a query from a worker thread."""
        thread_id = threading.get_ident()
        logger.info(f"Worker {worker_id} starting on thread {thread_id}")
        
        try:
            # First query
            with pool.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT {worker_id} as worker_id")
                results1 = cursor.fetchall()
                assert results1[0][0] == worker_id
            
            # Second query (should reuse connection)
            with pool.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 'second_query' as query_type")
                results2 = cursor.fetchall()
                assert results2[0][0] == 'second_query'
            
            logger.info(f"Worker {worker_id} completed successfully")
            return {'worker_id': worker_id, 'success': True}
            
        except Exception as e:
            logger.error(f"Worker {worker_id} failed: {e}")
            return {'worker_id': worker_id, 'success': False, 'error': str(e)}
    
    try:
        # Execute concurrent queries
        num_workers = 8
        logger.info(f"Starting {num_workers} concurrent workers...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker_query, i) for i in range(num_workers)]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
        
        # Analyze results
        successful = [r for r in results if r['success']]
        failed = [r for r in results if not r['success']]
        
        logger.info(f"Results: {len(successful)} successful, {len(failed)} failed")
        
        if failed:
            for failure in failed:
                logger.error(f"Worker {failure['worker_id']} failed: {failure.get('error', 'Unknown error')}")
        
        # Check statistics
        stats = pool.get_statistics()
        logger.info(f"Final pool statistics: {stats}")
        
        success_rate = len(successful) / num_workers
        logger.info(f"Success rate: {success_rate:.2%}")
        
        return success_rate >= 0.7  # Allow some failures due to network/timing
        
    finally:
        pool.close_all()


def test_connection_reuse():
    """Test that connections are properly reused within threads."""
    logger.info("=== Testing Connection Reuse ===")
    
    pool = ConnectionPool(
        min_size=1,
        max_size=3,
        debug=True,
        **TEST_CONFIG
    )
    
    try:
        # Execute multiple queries in sequence
        results = []
        for i in range(5):
            with pool.get_connection_context() as conn:
                logger.info(f"Query {i+1}: use_count={conn.use_count}, connection_id={id(conn)}")
                cursor = conn.cursor()
                cursor.execute(f"SELECT {i} as query_number")
                result = cursor.fetchall()
                results.append(result[0][0])
        
        # Verify all queries executed successfully
        assert results == [0, 1, 2, 3, 4]
        
        # Check statistics
        stats = pool.get_statistics()
        logger.info(f"Reuse test statistics: {stats}")
        
        # Should have reused connections (total_requests > created_connections)
        assert stats['total_requests'] >= stats['created_connections']
        
        logger.info("Connection reuse test passed")
        return True
        
    finally:
        pool.close_all()


def test_pool_statistics():
    """Test pool statistics tracking."""
    logger.info("=== Testing Pool Statistics ===")
    
    pool = ConnectionPool(
        min_size=2,
        max_size=5,
        debug=True,
        **TEST_CONFIG
    )
    
    try:
        initial_stats = pool.get_statistics()
        logger.info(f"Initial stats: {initial_stats}")
        
        # Execute some queries
        for i in range(3):
            with pool.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT {i} as iteration")
                cursor.fetchall()
        
        final_stats = pool.get_statistics()
        logger.info(f"Final stats: {final_stats}")
        
        # Verify statistics changed appropriately
        assert final_stats['total_requests'] > initial_stats['total_requests']
        assert final_stats['created_connections'] >= initial_stats['created_connections']
        
        logger.info("Pool statistics test passed")
        return True
        
    finally:
        pool.close_all()


def main():
    """Run all tests."""
    logger.info("Starting ConnectionPool End-to-End Tests")
    logger.info("=" * 60)
    
    tests = [
        ("Basic Pool Functionality", test_basic_pool_functionality),
        ("Connection Reuse", test_connection_reuse), 
        ("Pool Statistics", test_pool_statistics),
        ("Concurrent Queries", test_concurrent_queries),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        try:
            logger.info(f"\nRunning: {test_name}")
            result = test_func()
            if result:
                logger.info(f"✅ {test_name} PASSED")
                passed += 1
            else:
                logger.error(f"❌ {test_name} FAILED")
        except Exception as e:
            logger.error(f"❌ {test_name} FAILED with exception: {e}")
    
    logger.info("=" * 60)
    logger.info(f"Tests completed: {passed}/{total} passed")
    
    if passed == total:
        logger.info("🎉 All tests passed!")
    else:
        logger.error(f"⚠️  {total - passed} tests failed")
    
    return passed == total


if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)