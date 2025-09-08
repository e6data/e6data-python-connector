#!/usr/bin/env python3
"""
Comprehensive tests for ConnectionPool in multi-threading and multi-processing environments.
Tests thread safety, process safety, and performance under various concurrency scenarios.
"""

import concurrent.futures
import logging
import multiprocessing
import os
import queue
import threading
import time
from typing import Dict, List, Any
import random

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from e6data_python_connector import Connection, ConnectionPool

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(processName)s:%(threadName)s] - %(levelname)s - %(message)s'
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


# =============================================================================
# Multi-Threading Tests
# =============================================================================

def test_multi_threading_basic():
    """Test basic multi-threading with ConnectionPool."""
    logger.info("=" * 60)
    logger.info("TEST: Basic Multi-Threading")
    logger.info("=" * 60)
    
    pool = ConnectionPool(
        min_size=3,
        max_size=10,
        max_overflow=5,
        debug=False,  # Disable debug for cleaner output
        **TEST_CONFIG
    )
    
    results = {'success': 0, 'failed': 0, 'threads': set()}
    results_lock = threading.Lock()
    
    def worker_thread(worker_id: int, num_queries: int) -> Dict:
        """Worker function for thread pool."""
        thread_id = threading.current_thread().ident
        process_id = os.getpid()
        
        worker_results = {
            'worker_id': worker_id,
            'thread_id': thread_id,
            'process_id': process_id,
            'queries_executed': 0,
            'errors': []
        }
        
        for query_num in range(num_queries):
            try:
                with pool.get_connection_context() as conn:
                    cursor = conn.cursor()
                    query = f"SELECT {worker_id} as worker, {query_num} as query_num"
                    cursor.execute(query)
                    results_data = cursor.fetchall()
                    
                    # Verify results
                    assert results_data[0][0] == worker_id
                    assert results_data[0][1] == query_num
                    
                    worker_results['queries_executed'] += 1
                    
            except Exception as e:
                worker_results['errors'].append(str(e))
                logger.error(f"Worker {worker_id} query {query_num} failed: {e}")
        
        # Update shared results
        with results_lock:
            results['threads'].add(thread_id)
            if worker_results['queries_executed'] == num_queries:
                results['success'] += 1
            else:
                results['failed'] += 1
        
        return worker_results
    
    # Run with ThreadPoolExecutor
    num_workers = 20
    queries_per_worker = 5
    
    logger.info(f"Starting {num_workers} threads, {queries_per_worker} queries each")
    start_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(worker_thread, i, queries_per_worker)
            for i in range(num_workers)
        ]
        
        worker_results = []
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            worker_results.append(result)
    
    duration = time.time() - start_time
    
    # Analyze results
    total_queries = sum(r['queries_executed'] for r in worker_results)
    total_errors = sum(len(r['errors']) for r in worker_results)
    unique_threads = len(results['threads'])
    
    logger.info(f"Completed in {duration:.2f} seconds")
    logger.info(f"Workers: {results['success']} succeeded, {results['failed']} failed")
    logger.info(f"Total queries executed: {total_queries}/{num_workers * queries_per_worker}")
    logger.info(f"Total errors: {total_errors}")
    logger.info(f"Unique threads used: {unique_threads}")
    
    # Get pool statistics
    stats = pool.get_statistics()
    logger.info(f"Pool stats: {stats}")
    
    pool.close_all()
    
    # Verify results
    assert results['success'] >= num_workers * 0.9, f"Too many failures: {results['failed']}/{num_workers}"
    assert total_queries >= num_workers * queries_per_worker * 0.9, "Too few queries executed"
    
    logger.info("✅ Basic multi-threading test PASSED\n")
    return True


def test_multi_threading_stress():
    """Stress test with high concurrency."""
    logger.info("=" * 60)
    logger.info("TEST: Multi-Threading Stress Test")
    logger.info("=" * 60)
    
    pool = ConnectionPool(
        min_size=5,
        max_size=20,
        max_overflow=10,
        timeout=30,
        debug=False,
        **TEST_CONFIG
    )
    
    # Shared metrics
    metrics = {
        'total_queries': 0,
        'successful_queries': 0,
        'failed_queries': 0,
        'connection_timeouts': 0,
        'max_wait_time': 0,
        'total_wait_time': 0
    }
    metrics_lock = threading.Lock()
    
    def stress_worker(worker_id: int) -> None:
        """Stress test worker."""
        for i in range(10):
            start_wait = time.time()
            try:
                conn = pool.get_connection(timeout=10)
                wait_time = time.time() - start_wait
                
                with metrics_lock:
                    metrics['total_wait_time'] += wait_time
                    metrics['max_wait_time'] = max(metrics['max_wait_time'], wait_time)
                
                # Random sleep to simulate work
                time.sleep(random.uniform(0.1, 0.5))
                
                cursor = conn.cursor()
                cursor.execute(f"SELECT {worker_id} as worker, {i} as iteration")
                cursor.fetchall()
                
                pool.return_connection(conn)
                
                with metrics_lock:
                    metrics['successful_queries'] += 1
                    metrics['total_queries'] += 1
                    
            except TimeoutError:
                with metrics_lock:
                    metrics['connection_timeouts'] += 1
                    metrics['failed_queries'] += 1
                    metrics['total_queries'] += 1
                logger.warning(f"Worker {worker_id} timed out waiting for connection")
                
            except Exception as e:
                with metrics_lock:
                    metrics['failed_queries'] += 1
                    metrics['total_queries'] += 1
                logger.error(f"Worker {worker_id} error: {e}")
    
    # Run stress test
    num_workers = 50
    logger.info(f"Starting {num_workers} concurrent workers for stress test")
    start_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
        futures = [executor.submit(stress_worker, i) for i in range(num_workers)]
        concurrent.futures.wait(futures)
    
    duration = time.time() - start_time
    
    # Report results
    logger.info(f"Stress test completed in {duration:.2f} seconds")
    logger.info(f"Total queries: {metrics['total_queries']}")
    logger.info(f"Successful: {metrics['successful_queries']}")
    logger.info(f"Failed: {metrics['failed_queries']}")
    logger.info(f"Timeouts: {metrics['connection_timeouts']}")
    logger.info(f"Max wait time: {metrics['max_wait_time']:.2f}s")
    logger.info(f"Avg wait time: {metrics['total_wait_time']/max(metrics['total_queries'], 1):.2f}s")
    
    stats = pool.get_statistics()
    logger.info(f"Final pool stats: {stats}")
    
    pool.close_all()
    
    # Verify acceptable performance
    success_rate = metrics['successful_queries'] / max(metrics['total_queries'], 1)
    assert success_rate >= 0.8, f"Success rate too low: {success_rate:.2%}"
    
    logger.info(f"✅ Stress test PASSED (success rate: {success_rate:.2%})\n")
    return True


# =============================================================================
# Multi-Processing Tests
# =============================================================================

def process_worker_function(worker_id: int, config: dict, num_queries: int, result_queue: multiprocessing.Queue):
    """Worker function for multiprocessing test."""
    process_id = os.getpid()
    logger.info(f"Process worker {worker_id} started (PID: {process_id})")
    
    # Each process creates its own connection pool
    pool = ConnectionPool(
        min_size=1,
        max_size=3,
        debug=False,
        **config
    )
    
    results = {
        'worker_id': worker_id,
        'process_id': process_id,
        'queries_executed': 0,
        'errors': [],
        'thread_ids': set()
    }
    
    try:
        for query_num in range(num_queries):
            thread_id = threading.current_thread().ident
            results['thread_ids'].add(thread_id)
            
            try:
                with pool.get_connection_context() as conn:
                    cursor = conn.cursor()
                    query = f"SELECT {worker_id} as worker, {query_num} as query_num, {process_id} as pid"
                    cursor.execute(query)
                    data = cursor.fetchall()
                    
                    # Verify results
                    assert data[0][0] == worker_id
                    assert data[0][1] == query_num
                    
                    results['queries_executed'] += 1
                    
            except Exception as e:
                results['errors'].append(str(e))
                logger.error(f"Process worker {worker_id} query {query_num} failed: {e}")
    
    finally:
        pool.close_all()
        # Convert set to list for serialization
        results['thread_ids'] = list(results['thread_ids'])
        result_queue.put(results)
        logger.info(f"Process worker {worker_id} completed")


def test_multi_processing_basic():
    """Test basic multi-processing with ConnectionPool."""
    logger.info("=" * 60)
    logger.info("TEST: Basic Multi-Processing")
    logger.info("=" * 60)
    
    num_processes = 4
    queries_per_process = 5
    
    logger.info(f"Starting {num_processes} processes, {queries_per_process} queries each")
    start_time = time.time()
    
    # Use multiprocessing Queue for results
    result_queue = multiprocessing.Queue()
    
    # Start processes
    processes = []
    for i in range(num_processes):
        p = multiprocessing.Process(
            target=process_worker_function,
            args=(i, TEST_CONFIG, queries_per_process, result_queue)
        )
        p.start()
        processes.append(p)
    
    # Wait for all processes to complete
    for p in processes:
        p.join()
    
    duration = time.time() - start_time
    
    # Collect results
    results = []
    while not result_queue.empty():
        results.append(result_queue.get())
    
    # Analyze results
    total_queries = sum(r['queries_executed'] for r in results)
    total_errors = sum(len(r['errors']) for r in results)
    unique_processes = len(set(r['process_id'] for r in results))
    
    logger.info(f"Completed in {duration:.2f} seconds")
    logger.info(f"Total queries executed: {total_queries}/{num_processes * queries_per_process}")
    logger.info(f"Total errors: {total_errors}")
    logger.info(f"Unique processes used: {unique_processes}")
    
    # Verify results
    assert total_queries == num_processes * queries_per_process, f"Not all queries executed: {total_queries}"
    assert unique_processes == num_processes, f"Not all processes ran: {unique_processes}"
    
    logger.info("✅ Basic multi-processing test PASSED\n")
    return True


def test_multi_processing_with_threads():
    """Test multi-processing where each process uses multiple threads."""
    logger.info("=" * 60)
    logger.info("TEST: Multi-Processing with Thread Pools")
    logger.info("=" * 60)
    
    def process_with_threads(process_id: int, config: dict, result_queue: multiprocessing.Queue):
        """Each process runs its own thread pool."""
        pid = os.getpid()
        logger.info(f"Process {process_id} started (PID: {pid})")
        
        # Create pool for this process
        pool = ConnectionPool(
            min_size=2,
            max_size=5,
            debug=False,
            **config
        )
        
        process_results = {
            'process_id': process_id,
            'pid': pid,
            'threads': [],
            'total_queries': 0,
            'successful_queries': 0
        }
        
        def thread_worker(thread_num: int) -> Dict:
            """Thread worker within a process."""
            thread_id = threading.current_thread().ident
            queries_executed = 0
            
            for i in range(3):
                try:
                    with pool.get_connection_context() as conn:
                        cursor = conn.cursor()
                        query = f"SELECT {process_id} as proc, {thread_num} as thread, {i} as query"
                        cursor.execute(query)
                        cursor.fetchall()
                        queries_executed += 1
                except Exception as e:
                    logger.error(f"Process {process_id} Thread {thread_num} error: {e}")
            
            return {'thread_id': thread_id, 'queries_executed': queries_executed}
        
        # Run threads within this process
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(thread_worker, i) for i in range(5)]
            
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                process_results['threads'].append(result)
                process_results['total_queries'] += result['queries_executed']
                if result['queries_executed'] == 3:
                    process_results['successful_queries'] += 1
        
        pool.close_all()
        result_queue.put(process_results)
        logger.info(f"Process {process_id} completed")
    
    num_processes = 3
    logger.info(f"Starting {num_processes} processes, each with thread pools")
    start_time = time.time()
    
    result_queue = multiprocessing.Queue()
    processes = []
    
    for i in range(num_processes):
        p = multiprocessing.Process(
            target=process_with_threads,
            args=(i, TEST_CONFIG, result_queue)
        )
        p.start()
        processes.append(p)
    
    for p in processes:
        p.join()
    
    duration = time.time() - start_time
    
    # Collect and analyze results
    all_results = []
    while not result_queue.empty():
        all_results.append(result_queue.get())
    
    total_queries = sum(r['total_queries'] for r in all_results)
    total_threads = sum(len(r['threads']) for r in all_results)
    
    logger.info(f"Completed in {duration:.2f} seconds")
    logger.info(f"Processes: {len(all_results)}")
    logger.info(f"Total threads across all processes: {total_threads}")
    logger.info(f"Total queries executed: {total_queries}")
    
    # Verify
    assert len(all_results) == num_processes, f"Not all processes completed: {len(all_results)}"
    assert total_queries >= num_processes * 5 * 3 * 0.9, f"Too few queries: {total_queries}"
    
    logger.info("✅ Multi-processing with threads test PASSED\n")
    return True


# =============================================================================
# Comparison Tests
# =============================================================================

def test_threading_vs_multiprocessing_performance():
    """Compare performance between threading and multiprocessing."""
    logger.info("=" * 60)
    logger.info("TEST: Threading vs Multiprocessing Performance")
    logger.info("=" * 60)
    
    num_workers = 8
    queries_per_worker = 10
    
    # Test with threading
    logger.info(f"Testing with {num_workers} threads...")
    pool_threading = ConnectionPool(
        min_size=3,
        max_size=10,
        debug=False,
        **TEST_CONFIG
    )
    
    def thread_worker(worker_id):
        for i in range(queries_per_worker):
            with pool_threading.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT {worker_id} as w, {i} as q")
                cursor.fetchall()
    
    start_time = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(thread_worker, i) for i in range(num_workers)]
        concurrent.futures.wait(futures)
    threading_duration = time.time() - start_time
    
    thread_stats = pool_threading.get_statistics()
    pool_threading.close_all()
    
    # Test with multiprocessing
    logger.info(f"Testing with {num_workers} processes...")
    
    def process_worker(worker_id, config, queries):
        pool = ConnectionPool(min_size=1, max_size=2, debug=False, **config)
        for i in range(queries):
            with pool.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT {worker_id} as w, {i} as q")
                cursor.fetchall()
        pool.close_all()
    
    start_time = time.time()
    processes = []
    for i in range(num_workers):
        p = multiprocessing.Process(
            target=process_worker,
            args=(i, TEST_CONFIG, queries_per_worker)
        )
        p.start()
        processes.append(p)
    
    for p in processes:
        p.join()
    multiprocessing_duration = time.time() - start_time
    
    # Compare results
    logger.info(f"\n📊 Performance Comparison:")
    logger.info(f"Threading: {threading_duration:.2f}s")
    logger.info(f"  - Total connections created: {thread_stats['created_connections']}")
    logger.info(f"  - Connection reuse: {thread_stats['total_requests']}/{thread_stats['created_connections']} = {thread_stats['total_requests']/max(thread_stats['created_connections'], 1):.1f}x")
    logger.info(f"Multiprocessing: {multiprocessing_duration:.2f}s")
    logger.info(f"  - Each process had its own pool (total: {num_workers} pools)")
    
    speedup = multiprocessing_duration / threading_duration
    logger.info(f"\nThreading is {speedup:.2f}x {'faster' if speedup > 1 else 'slower'} than multiprocessing")
    
    logger.info("✅ Performance comparison test completed\n")
    return True


# =============================================================================
# Edge Cases and Race Conditions
# =============================================================================

def test_race_conditions():
    """Test for race conditions in connection pool."""
    logger.info("=" * 60)
    logger.info("TEST: Race Conditions")
    logger.info("=" * 60)
    
    pool = ConnectionPool(
        min_size=2,
        max_size=5,
        max_overflow=2,
        timeout=5,
        debug=False,
        **TEST_CONFIG
    )
    
    # Test rapid connection get/return
    errors = []
    connections_held = []
    lock = threading.Lock()
    
    def rapid_fire_worker(worker_id):
        """Rapidly get and return connections."""
        for i in range(20):
            try:
                conn = pool.get_connection(timeout=2)
                
                # Sometimes hold multiple connections
                if random.random() < 0.3:
                    with lock:
                        connections_held.append(conn)
                    if len(connections_held) > 3:
                        # Return some held connections
                        with lock:
                            old_conn = connections_held.pop(0)
                        pool.return_connection(old_conn)
                else:
                    # Quick query
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
                    cursor.fetchall()
                    pool.return_connection(conn)
                    
            except Exception as e:
                errors.append(f"Worker {worker_id}: {str(e)}")
    
    # Run many threads simultaneously
    num_threads = 20
    logger.info(f"Starting {num_threads} threads for race condition test")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(rapid_fire_worker, i) for i in range(num_threads)]
        concurrent.futures.wait(futures)
    
    # Return all held connections
    with lock:
        for conn in connections_held:
            pool.return_connection(conn)
    
    # Check for errors
    if errors:
        logger.warning(f"Errors encountered: {len(errors)}")
        for error in errors[:5]:  # Show first 5 errors
            logger.warning(f"  - {error}")
    
    stats = pool.get_statistics()
    logger.info(f"Final stats: {stats}")
    
    pool.close_all()
    
    # Some errors are acceptable in race condition test
    error_rate = len(errors) / (num_threads * 20)
    assert error_rate < 0.1, f"Too many errors: {error_rate:.2%}"
    
    logger.info(f"✅ Race condition test PASSED (error rate: {error_rate:.2%})\n")
    return True


# =============================================================================
# Main Test Runner
# =============================================================================

def main():
    """Run all multi-threading and multi-processing tests."""
    logger.info("🚀 Starting Multi-Threading and Multi-Processing Tests")
    logger.info("=" * 60)
    
    tests = [
        # Multi-threading tests
        ("Basic Multi-Threading", test_multi_threading_basic),
        ("Multi-Threading Stress Test", test_multi_threading_stress),
        
        # Multi-processing tests
        ("Basic Multi-Processing", test_multi_processing_basic),
        ("Multi-Processing with Threads", test_multi_processing_with_threads),
        
        # Comparison and edge cases
        ("Threading vs Multiprocessing", test_threading_vs_multiprocessing_performance),
        ("Race Conditions", test_race_conditions),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            logger.info(f"\n🔄 Running: {test_name}")
            if test_func():
                passed += 1
            else:
                failed += 1
                logger.error(f"❌ {test_name} returned False")
        except Exception as e:
            failed += 1
            logger.error(f"❌ {test_name} failed with exception: {e}", exc_info=True)
    
    # Summary
    logger.info("=" * 60)
    logger.info("📊 TEST SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total tests: {len(tests)}")
    logger.info(f"Passed: {passed}")
    logger.info(f"Failed: {failed}")
    
    if failed == 0:
        logger.info("🎉 ALL TESTS PASSED!")
        return True
    else:
        logger.error(f"⚠️ {failed} tests failed")
        return False


if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)