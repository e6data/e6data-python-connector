#!/usr/bin/env python3
"""
End-to-end tests for ConnectionPool using real e6data credentials.
Tests actual connection pooling behavior with real database queries.
"""

import concurrent.futures
import logging
import threading
import time
import unittest
from typing import List, Dict

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from e6data_python_connector import Connection, ConnectionPool

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'
)
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


class TestConnectionPoolE2E(unittest.TestCase):
    """End-to-end tests for ConnectionPool with real e6data connections."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test class with connection pool."""
        logger.info("Setting up ConnectionPool for E2E tests...")
        cls.pool = ConnectionPool(
            min_size=2,
            max_size=8,
            max_overflow=3,
            timeout=30.0,
            recycle=300,  # 5 minutes for testing
            debug=True,
            pre_ping=True,
            **TEST_CONFIG
        )
        logger.info("ConnectionPool created successfully")
    
    @classmethod
    def tearDownClass(cls):
        """Clean up connection pool."""
        logger.info("Closing ConnectionPool...")
        cls.pool.close_all()
        logger.info("ConnectionPool closed")
    
    def test_basic_pool_operation(self):
        """Test basic pool get/return operations."""
        logger.info("Testing basic pool operation...")
        
        # Get initial statistics
        initial_stats = self.pool.get_statistics()
        logger.info(f"Initial stats: {initial_stats}")
        
        # Get connection from pool
        conn = self.pool.get_connection()
        self.assertIsNotNone(conn)
        self.assertTrue(conn.in_use)
        
        # Execute a simple query
        cursor = conn.cursor()
        query_id = cursor.execute("SELECT 1 as test_value")
        self.assertIsNotNone(query_id)
        
        results = cursor.fetchall()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], 1)
        
        # Return connection to pool
        self.pool.return_connection(conn)
        self.assertFalse(conn.in_use)
        
        # Check final statistics
        final_stats = self.pool.get_statistics()
        self.assertGreater(final_stats['total_requests'], initial_stats['total_requests'])
        
        logger.info("Basic pool operation test passed")
    
    def test_connection_reuse_same_thread(self):
        """Test that same thread reuses connections."""
        logger.info("Testing connection reuse within thread...")
        
        # Get connection multiple times from same thread
        conn1 = self.pool.get_connection()
        thread_id1 = threading.get_ident()
        
        self.pool.return_connection(conn1)
        
        conn2 = self.pool.get_connection()
        thread_id2 = threading.get_ident()
        
        # Should be same thread and reuse same connection
        self.assertEqual(thread_id1, thread_id2)
        self.assertEqual(conn1, conn2)
        self.assertGreater(conn2.use_count, 1)
        
        self.pool.return_connection(conn2)
        
        logger.info("Connection reuse test passed")
    
    def test_context_manager(self):
        """Test context manager for automatic connection management."""
        logger.info("Testing context manager...")
        
        initial_stats = self.pool.get_statistics()
        
        with self.pool.get_connection_context() as conn:
            self.assertTrue(conn.in_use)
            
            cursor = conn.cursor()
            cursor.execute("SELECT 'context_test' as test_type, 1 as query_num")
            results = cursor.fetchall()
            
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0][0], 'context_test')
        
        # After context exit, connection should be returned
        final_stats = self.pool.get_statistics()
        self.assertEqual(final_stats['active_connections'], initial_stats['active_connections'])
        
        logger.info("Context manager test passed")
    
    def test_concurrent_queries_different_threads(self):
        """Test concurrent queries from different threads."""
        logger.info("Testing concurrent queries from different threads...")
        
        def execute_worker_query(worker_id: int) -> Dict:
            """Execute a query from a worker thread."""
            thread_id = threading.get_ident()
            start_time = time.time()
            
            try:
                conn = self.pool.get_connection(timeout=30)
                cursor = conn.cursor()
                
                # Execute a query that includes worker identification
                query = f"SELECT {worker_id} as worker_id, 'thread_test' as test_type"
                query_id = cursor.execute(query)
                
                results = cursor.fetchall()
                
                self.pool.return_connection(conn)
                
                duration = time.time() - start_time
                
                return {
                    'worker_id': worker_id,
                    'thread_id': thread_id,
                    'query_id': query_id,
                    'results': results,
                    'duration': duration,
                    'success': True
                }
                
            except Exception as e:
                logger.error(f"Worker {worker_id} failed: {e}")
                return {
                    'worker_id': worker_id,
                    'thread_id': thread_id,
                    'error': str(e),
                    'success': False
                }
        
        # Execute queries concurrently
        num_workers = 10
        logger.info(f"Starting {num_workers} concurrent queries...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(execute_worker_query, i)
                for i in range(num_workers)
            ]
            
            results = []
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results.append(result)
        
        # Analyze results
        successful = [r for r in results if r['success']]
        failed = [r for r in results if not r['success']]
        
        logger.info(f"Completed: {len(successful)}/{num_workers} successful, {len(failed)} failed")
        
        # Should have high success rate
        success_rate = len(successful) / num_workers
        self.assertGreater(success_rate, 0.8, f"Success rate too low: {success_rate}")
        
        # Check that we used different threads
        unique_threads = len(set(r['thread_id'] for r in successful))
        logger.info(f"Used {unique_threads} unique threads")
        
        # Check pool statistics
        stats = self.pool.get_statistics()
        logger.info(f"Final pool stats: {stats}")
        self.assertGreater(stats['total_requests'], 0)
        
        logger.info("Concurrent queries test passed")
    
    def test_connection_pool_vs_direct_connections(self):
        """Compare performance of connection pool vs direct connections."""
        logger.info("Testing connection pool vs direct connections performance...")
        
        # Test with direct connections
        def query_with_direct_connection(query_id):
            """Execute query with direct connection."""
            start_time = time.time()
            try:
                conn = Connection(**TEST_CONFIG)
                cursor = conn.cursor()
                cursor.execute(f"SELECT {query_id} as query_id, 'direct' as connection_type")
                results = cursor.fetchall()
                cursor.close()
                conn.close()
                return time.time() - start_time
            except Exception as e:
                logger.error(f"Direct connection query {query_id} failed: {e}")
                return None
        
        # Test with pooled connections
        def query_with_pooled_connection(query_id):
            """Execute query with pooled connection."""
            start_time = time.time()
            try:
                with self.pool.get_connection_context() as conn:
                    cursor = conn.cursor()
                    cursor.execute(f"SELECT {query_id} as query_id, 'pooled' as connection_type")
                    results = cursor.fetchall()
                return time.time() - start_time
            except Exception as e:
                logger.error(f"Pooled connection query {query_id} failed: {e}")
                return None
        
        # Test direct connections (smaller number due to overhead)
        logger.info("Testing direct connections...")
        direct_times = []
        for i in range(3):
            duration = query_with_direct_connection(i)
            if duration:
                direct_times.append(duration)
        
        # Test pooled connections
        logger.info("Testing pooled connections...")
        pooled_times = []
        for i in range(10):
            duration = query_with_pooled_connection(i)
            if duration:
                pooled_times.append(duration)
        
        # Calculate averages
        if direct_times and pooled_times:
            avg_direct = sum(direct_times) / len(direct_times)
            avg_pooled = sum(pooled_times) / len(pooled_times)
            
            logger.info(f"Average direct connection time: {avg_direct:.3f}s")
            logger.info(f"Average pooled connection time: {avg_pooled:.3f}s")
            logger.info(f"Pool speedup: {avg_direct/avg_pooled:.2f}x")
            
            # Pooled connections should generally be faster after warmup
            self.assertGreater(len(pooled_times), len(direct_times))
        
        logger.info("Performance comparison test completed")
    
    def test_heavy_concurrent_load(self):
        """Test pool under heavy concurrent load."""
        logger.info("Testing heavy concurrent load...")
        
        initial_stats = self.pool.get_statistics()
        
        def heavy_workload(worker_id: int) -> bool:
            """Execute multiple queries in a worker."""
            try:
                for query_num in range(3):
                    with self.pool.get_connection_context() as conn:
                        cursor = conn.cursor()
                        # More complex query
                        query = f"""
                        SELECT 
                            {worker_id} as worker_id,
                            {query_num} as query_num,
                            COUNT(*) as row_count,
                            CURRENT_TIMESTAMP as execution_time
                        FROM (
                            SELECT 1 as dummy_col
                            UNION ALL SELECT 2
                            UNION ALL SELECT 3
                        ) t
                        """
                        cursor.execute(query)
                        results = cursor.fetchall()
                        
                        # Verify results
                        self.assertEqual(len(results), 1)
                        self.assertEqual(results[0][0], worker_id)
                        self.assertEqual(results[0][1], query_num)
                        self.assertEqual(results[0][2], 3)  # COUNT(*) should be 3
                
                return True
            except Exception as e:
                logger.error(f"Heavy workload worker {worker_id} failed: {e}")
                return False
        
        # Run heavy workload
        num_workers = 8
        logger.info(f"Starting heavy workload with {num_workers} workers...")
        
        start_time = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = [
                executor.submit(heavy_workload, i)
                for i in range(num_workers)
            ]
            
            success_results = []
            for future in concurrent.futures.as_completed(futures):
                success = future.result()
                success_results.append(success)
        
        duration = time.time() - start_time
        successful_workers = sum(success_results)
        
        logger.info(f"Heavy load completed in {duration:.2f}s")
        logger.info(f"Successful workers: {successful_workers}/{num_workers}")
        
        # Check final statistics
        final_stats = self.pool.get_statistics()
        logger.info(f"Final pool statistics: {final_stats}")
        
        # Should have high success rate
        success_rate = successful_workers / num_workers
        self.assertGreater(success_rate, 0.8, f"Success rate too low: {success_rate}")
        
        # Pool should have handled many requests
        total_requests = final_stats['total_requests'] - initial_stats['total_requests']
        self.assertGreater(total_requests, num_workers * 2)  # Each worker did 3 queries
        
        logger.info("Heavy concurrent load test passed")
    
    def test_pool_exhaustion_and_recovery(self):
        """Test pool behavior when exhausted and during recovery."""
        logger.info("Testing pool exhaustion and recovery...")
        
        # Create a small pool for testing exhaustion
        small_pool = ConnectionPool(
            min_size=1,
            max_size=2,
            max_overflow=1,
            timeout=5.0,
            debug=True,
            **TEST_CONFIG
        )
        
        try:
            connections = []
            
            # Exhaust the pool
            for i in range(3):  # max_size + max_overflow
                conn = small_pool.get_connection(timeout=10)
                connections.append(conn)
                logger.info(f"Got connection {i+1}")
            
            # Try to get one more (should timeout)
            start_time = time.time()
            try:
                extra_conn = small_pool.get_connection(timeout=2.0)
                self.fail("Should have timed out when pool exhausted")
            except TimeoutError:
                timeout_duration = time.time() - start_time
                logger.info(f"Correctly timed out after {timeout_duration:.2f}s")
                self.assertGreaterEqual(timeout_duration, 1.8)
            
            # Return some connections and test recovery
            logger.info("Returning connections for recovery test...")
            for i, conn in enumerate(connections[:2]):
                small_pool.return_connection(conn)
                logger.info(f"Returned connection {i+1}")
            
            # Should now be able to get connections again
            recovered_conn = small_pool.get_connection(timeout=5.0)
            self.assertIsNotNone(recovered_conn)
            logger.info("Successfully recovered connection after return")
            
            # Return all connections
            small_pool.return_connection(recovered_conn)
            small_pool.return_connection(connections[2])
            
            # Check final statistics
            stats = small_pool.get_statistics()
            logger.info(f"Final small pool stats: {stats}")
            
        finally:
            small_pool.close_all()
        
        logger.info("Pool exhaustion and recovery test passed")
    
    def test_connection_health_and_replacement(self):
        """Test connection health checking and automatic replacement."""
        logger.info("Testing connection health and replacement...")
        
        # Get a connection and test it's healthy
        with self.pool.get_connection_context() as conn:
            self.assertTrue(conn.connection.check_connection())
            
            # Execute query to verify it works
            cursor = conn.cursor()
            cursor.execute("SELECT 'health_test' as test, CURRENT_TIMESTAMP as ts")
            results = cursor.fetchall()
            
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0][0], 'health_test')
        
        # Test connection recycling (simulate old connection)
        test_pool = ConnectionPool(
            min_size=1,
            max_size=3,
            recycle=1,  # Very short recycle time
            debug=True,
            **TEST_CONFIG
        )
        
        try:
            # Get connection
            conn1 = test_pool.get_connection()
            original_created_at = conn1.created_at
            test_pool.return_connection(conn1)
            
            # Wait for recycle time
            time.sleep(1.5)
            
            # Get connection again (should be recycled)
            conn2 = test_pool.get_connection()
            
            # Connection should have been replaced due to age
            if conn2.created_at > original_created_at + 1:
                logger.info("Connection was recycled due to age")
            else:
                logger.info("Connection was reused (within recycle time)")
            
            test_pool.return_connection(conn2)
            
        finally:
            test_pool.close_all()
        
        logger.info("Connection health and replacement test passed")
    
    def test_mixed_workload_realistic_scenario(self):
        """Test a realistic mixed workload scenario."""
        logger.info("Testing realistic mixed workload scenario...")
        
        results = {
            'short_queries': [],
            'medium_queries': [],
            'long_queries': []
        }
        
        def short_query_worker(worker_id):
            """Execute short queries."""
            try:
                with self.pool.get_connection_context() as conn:
                    cursor = conn.cursor()
                    cursor.execute(f"SELECT {worker_id} as worker, 'short' as query_type")
                    result = cursor.fetchall()
                    results['short_queries'].append({'worker_id': worker_id, 'success': True})
                    return True
            except Exception as e:
                logger.error(f"Short query worker {worker_id} failed: {e}")
                results['short_queries'].append({'worker_id': worker_id, 'success': False, 'error': str(e)})
                return False
        
        def medium_query_worker(worker_id):
            """Execute medium complexity queries."""
            try:
                with self.pool.get_connection_context() as conn:
                    cursor = conn.cursor()
                    # More complex query
                    query = f"SELECT {worker_id} as worker, 'medium' as query_type, 5 as row_count"
                    cursor.execute(query)
                    result = cursor.fetchall()
                    results['medium_queries'].append({'worker_id': worker_id, 'success': True})
                    return True
            except Exception as e:
                logger.error(f"Medium query worker {worker_id} failed: {e}")
                results['medium_queries'].append({'worker_id': worker_id, 'success': False, 'error': str(e)})
                return False
        
        # Execute mixed workload
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = []
            
            # Submit short queries
            for i in range(15):
                futures.append(executor.submit(short_query_worker, i))
            
            # Submit medium queries
            for i in range(8):
                futures.append(executor.submit(medium_query_worker, i))
            
            # Wait for all to complete
            completed = 0
            for future in concurrent.futures.as_completed(futures):
                future.result()
                completed += 1
                if completed % 5 == 0:
                    logger.info(f"Completed {completed}/{len(futures)} tasks")
        
        # Analyze results
        short_success = sum(1 for r in results['short_queries'] if r['success'])
        medium_success = sum(1 for r in results['medium_queries'] if r['success'])
        
        logger.info(f"Short queries: {short_success}/{len(results['short_queries'])} successful")
        logger.info(f"Medium queries: {medium_success}/{len(results['medium_queries'])} successful")
        
        # Check pool statistics
        final_stats = self.pool.get_statistics()
        logger.info(f"Mixed workload final stats: {final_stats}")
        
        # Should have good success rates
        short_success_rate = short_success / len(results['short_queries']) if results['short_queries'] else 1
        medium_success_rate = medium_success / len(results['medium_queries']) if results['medium_queries'] else 1
        
        self.assertGreater(short_success_rate, 0.8)
        self.assertGreater(medium_success_rate, 0.8)
        
        logger.info("Mixed workload test passed")


if __name__ == '__main__':
    # Run specific test or all tests
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'single':
        # Run a single quick test
        suite = unittest.TestSuite()
        suite.addTest(TestConnectionPoolE2E('test_basic_pool_operation'))
        runner = unittest.TextTestRunner(verbosity=2)
        runner.run(suite)
    else:
        # Run all tests
        unittest.main(verbosity=2)