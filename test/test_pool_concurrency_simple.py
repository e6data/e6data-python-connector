#!/usr/bin/env python3
"""
Focused tests for ConnectionPool in multi-threading and multi-processing environments.
Addresses pickling issues and tests real-world concurrency scenarios.
"""

import concurrent.futures
import logging
import multiprocessing
import os
import random
import threading
import time
from multiprocessing import Process, Queue

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from e6data_python_connector import ConnectionPool

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [PID:%(process)d TID:%(thread)d] - %(levelname)s - %(message)s'
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
# Multi-Processing Helper Functions (at module level for pickling)
# =============================================================================

def process_worker_simple(worker_id, config, queries_per_worker, result_queue):
    """Simple process worker that can be pickled."""
    try:
        pid = os.getpid()
        logger.info(f"Process worker {worker_id} starting (PID: {pid})")
        
        # Create pool for this process
        pool = ConnectionPool(
            min_size=1,
            max_size=3,
            debug=False,
            **config
        )
        
        successful_queries = 0
        errors = []
        
        for i in range(queries_per_worker):
            try:
                with pool.get_connection_context() as conn:
                    cursor = conn.cursor()
                    cursor.execute(f"SELECT {worker_id} as worker, {i} as query_num")
                    result = cursor.fetchall()
                    
                    # Validate result
                    if result and result[0][0] == worker_id and result[0][1] == i:
                        successful_queries += 1
                    else:
                        errors.append(f"Invalid result for query {i}")
                        
            except Exception as e:
                errors.append(f"Query {i} error: {str(e)}")
        
        pool.close_all()
        
        # Return results
        result_data = {
            'worker_id': worker_id,
            'pid': pid,
            'successful_queries': successful_queries,
            'total_queries': queries_per_worker,
            'errors': len(errors)
        }
        
        result_queue.put(result_data)
        logger.info(f"Process worker {worker_id} completed: {successful_queries}/{queries_per_worker} successful")
        
    except Exception as e:
        logger.error(f"Process worker {worker_id} failed: {e}")
        result_queue.put({
            'worker_id': worker_id,
            'pid': os.getpid(),
            'successful_queries': 0,
            'total_queries': queries_per_worker,
            'errors': 1,
            'fatal_error': str(e)
        })


def process_with_threading(process_id, config, result_queue):
    """Process that uses threading internally."""
    try:
        pid = os.getpid()
        logger.info(f"Process {process_id} with threading starting (PID: {pid})")
        
        # Create pool for this process
        pool = ConnectionPool(
            min_size=2,
            max_size=4,
            debug=False,
            **config
        )
        
        def thread_worker(thread_id):
            """Thread worker within the process."""
            thread_queries = 0
            for i in range(3):
                try:
                    with pool.get_connection_context() as conn:
                        cursor = conn.cursor()
                        cursor.execute(f"SELECT {process_id} as proc, {thread_id} as thread, {i} as query")
                        cursor.fetchall()
                        thread_queries += 1
                except Exception as e:
                    logger.error(f"Process {process_id} Thread {thread_id} error: {e}")
            return thread_queries
        
        # Use threading within process
        total_queries = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(thread_worker, i) for i in range(4)]
            for future in concurrent.futures.as_completed(futures):
                total_queries += future.result()
        
        pool.close_all()
        
        result_data = {
            'process_id': process_id,
            'pid': pid,
            'successful_queries': total_queries,
            'total_expected': 12  # 4 threads * 3 queries
        }
        
        result_queue.put(result_data)
        logger.info(f"Process {process_id} completed: {total_queries}/12 queries successful")
        
    except Exception as e:
        logger.error(f"Process {process_id} failed: {e}")
        result_queue.put({
            'process_id': process_id,
            'pid': os.getpid(),
            'successful_queries': 0,
            'total_expected': 12,
            'error': str(e)
        })


# =============================================================================
# Test Functions
# =============================================================================

def test_high_concurrency_threading():
    """Test high concurrency with threading."""
    logger.info("=" * 60)
    logger.info("TEST: High Concurrency Threading")
    logger.info("=" * 60)
    
    pool = ConnectionPool(
        min_size=5,
        max_size=15,
        max_overflow=5,
        timeout=15,
        debug=False,
        **TEST_CONFIG
    )
    
    # Test with many concurrent threads
    def quick_worker(worker_id):
        """Quick worker for high concurrency test."""
        try:
            with pool.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT {worker_id} as id")
                result = cursor.fetchall()
                return {'worker_id': worker_id, 'success': True, 'result': result[0][0]}
        except Exception as e:
            logger.error(f"Worker {worker_id} failed: {e}")
            return {'worker_id': worker_id, 'success': False, 'error': str(e)}
    
    num_workers = 100  # High concurrency
    logger.info(f"Testing with {num_workers} concurrent threads")
    
    start_time = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(quick_worker, i) for i in range(num_workers)]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]
    
    duration = time.time() - start_time
    
    # Analyze results
    successful = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]
    
    logger.info(f"High concurrency test completed in {duration:.2f} seconds")
    logger.info(f"Success rate: {len(successful)}/{num_workers} ({len(successful)/num_workers:.2%})")
    
    # Show pool utilization
    stats = pool.get_statistics()
    logger.info(f"Pool stats: created={stats['created_connections']}, requests={stats['total_requests']}")
    logger.info(f"Connection reuse ratio: {stats['total_requests']}/{stats['created_connections']} = {stats['total_requests']/max(stats['created_connections'], 1):.1f}x")
    
    pool.close_all()
    
    success_rate = len(successful) / num_workers
    assert success_rate >= 0.8, f"Success rate too low: {success_rate:.2%}"
    
    logger.info("✅ High concurrency threading test PASSED\n")
    return True


def test_basic_multiprocessing():
    """Test basic multiprocessing with separate pools per process."""
    logger.info("=" * 60)
    logger.info("TEST: Basic Multiprocessing")
    logger.info("=" * 60)
    
    num_processes = 4
    queries_per_process = 5
    
    logger.info(f"Starting {num_processes} processes, {queries_per_process} queries each")
    
    # Use multiprocessing with Queue
    result_queue = multiprocessing.Queue()
    processes = []
    
    start_time = time.time()
    
    # Start processes
    for i in range(num_processes):
        p = Process(
            target=process_worker_simple,
            args=(i, TEST_CONFIG, queries_per_process, result_queue)
        )
        p.start()
        processes.append(p)
    
    # Wait for completion
    for p in processes:
        p.join()
    
    duration = time.time() - start_time
    
    # Collect results
    results = []
    while not result_queue.empty():
        results.append(result_queue.get())
    
    # Analyze
    total_successful = sum(r['successful_queries'] for r in results)
    total_expected = num_processes * queries_per_process
    total_errors = sum(r['errors'] for r in results)
    unique_pids = len(set(r['pid'] for r in results))
    
    logger.info(f"Multiprocessing completed in {duration:.2f} seconds")
    logger.info(f"Queries: {total_successful}/{total_expected} successful")
    logger.info(f"Errors: {total_errors}")
    logger.info(f"Unique processes: {unique_pids}")
    
    success_rate = total_successful / total_expected
    assert success_rate >= 0.9, f"Success rate too low: {success_rate:.2%}"
    assert unique_pids == num_processes, f"Not all processes ran: {unique_pids}"
    
    logger.info("✅ Basic multiprocessing test PASSED\n")
    return True


def test_multiprocessing_with_threading():
    """Test multiprocessing where each process uses threading."""
    logger.info("=" * 60)
    logger.info("TEST: Multiprocessing with Threading")
    logger.info("=" * 60)
    
    num_processes = 3
    logger.info(f"Starting {num_processes} processes, each with thread pools")
    
    result_queue = multiprocessing.Queue()
    processes = []
    
    start_time = time.time()
    
    for i in range(num_processes):
        p = Process(
            target=process_with_threading,
            args=(i, TEST_CONFIG, result_queue)
        )
        p.start()
        processes.append(p)
    
    for p in processes:
        p.join()
    
    duration = time.time() - start_time
    
    # Collect results
    results = []
    while not result_queue.empty():
        results.append(result_queue.get())
    
    total_successful = sum(r['successful_queries'] for r in results)
    total_expected = sum(r['total_expected'] for r in results)
    unique_pids = len(set(r['pid'] for r in results))
    
    logger.info(f"Multiprocessing+Threading completed in {duration:.2f} seconds")
    logger.info(f"Queries: {total_successful}/{total_expected} successful")
    logger.info(f"Unique processes: {unique_pids}")
    
    for r in results:
        logger.info(f"Process {r['process_id']} (PID {r['pid']}): {r['successful_queries']}/{r['total_expected']}")
    
    success_rate = total_successful / total_expected if total_expected > 0 else 0
    assert success_rate >= 0.8, f"Success rate too low: {success_rate:.2%}"
    
    logger.info("✅ Multiprocessing with threading test PASSED\n")
    return True


def test_thread_safety_validation():
    """Test thread safety with concurrent access to pool resources."""
    logger.info("=" * 60)
    logger.info("TEST: Thread Safety Validation")
    logger.info("=" * 60)
    
    pool = ConnectionPool(
        min_size=3,
        max_size=8,
        max_overflow=3,
        timeout=10,
        debug=False,
        **TEST_CONFIG
    )
    
    # Shared state to detect race conditions
    shared_state = {
        'connection_count': 0,
        'max_simultaneous': 0,
        'race_conditions': 0
    }
    state_lock = threading.Lock()
    
    def thread_safety_worker(worker_id):
        """Worker that tests for race conditions."""
        for i in range(5):
            try:
                # Increment connection count
                with state_lock:
                    shared_state['connection_count'] += 1
                    shared_state['max_simultaneous'] = max(
                        shared_state['max_simultaneous'],
                        shared_state['connection_count']
                    )
                
                start_time = time.time()
                conn = pool.get_connection(timeout=8)
                get_time = time.time() - start_time
                
                # Hold connection for a bit
                time.sleep(random.uniform(0.1, 0.3))
                
                cursor = conn.cursor()
                cursor.execute(f"SELECT {worker_id} as worker_id, {i} as iteration")
                cursor.fetchall()
                
                pool.return_connection(conn)
                
                # Decrement connection count
                with state_lock:
                    shared_state['connection_count'] -= 1
                
                if get_time > 5:  # Potential race condition if waiting too long
                    with state_lock:
                        shared_state['race_conditions'] += 1
                        
            except Exception as e:
                logger.error(f"Thread safety worker {worker_id} iteration {i} failed: {e}")
                with state_lock:
                    shared_state['connection_count'] = max(0, shared_state['connection_count'] - 1)
                    shared_state['race_conditions'] += 1
    
    # Run many threads to stress test
    num_threads = 30
    logger.info(f"Starting {num_threads} threads for thread safety test")
    
    start_time = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(thread_safety_worker, i) for i in range(num_threads)]
        concurrent.futures.wait(futures)
    
    duration = time.time() - start_time
    
    logger.info(f"Thread safety test completed in {duration:.2f} seconds")
    logger.info(f"Max simultaneous connections: {shared_state['max_simultaneous']}")
    logger.info(f"Race conditions detected: {shared_state['race_conditions']}")
    logger.info(f"Final connection count: {shared_state['connection_count']}")
    
    stats = pool.get_statistics()
    logger.info(f"Pool stats: {stats}")
    
    pool.close_all()
    
    # Verify thread safety
    assert shared_state['connection_count'] == 0, "Connection count should be zero at end"
    race_condition_rate = shared_state['race_conditions'] / (num_threads * 5)
    assert race_condition_rate < 0.1, f"Too many race conditions: {race_condition_rate:.2%}"
    
    logger.info(f"✅ Thread safety test PASSED (race conditions: {race_condition_rate:.2%})\n")
    return True


def test_connection_reuse_patterns():
    """Test different connection reuse patterns."""
    logger.info("=" * 60)
    logger.info("TEST: Connection Reuse Patterns")
    logger.info("=" * 60)
    
    pool = ConnectionPool(
        min_size=2,
        max_size=6,
        debug=True,  # Enable debug to see reuse
        **TEST_CONFIG
    )
    
    def sequential_reuse_worker(worker_id):
        """Worker that executes queries sequentially to test reuse."""
        connections_seen = set()
        
        for i in range(8):
            with pool.get_connection_context() as conn:
                conn_id = id(conn.connection)
                connections_seen.add(conn_id)
                
                cursor = conn.cursor()
                cursor.execute(f"SELECT {worker_id} as worker, {i} as seq")
                cursor.fetchall()
                
                # Small delay
                time.sleep(0.1)
        
        return {
            'worker_id': worker_id,
            'unique_connections': len(connections_seen),
            'total_queries': 8
        }
    
    # Run sequential workers
    logger.info("Testing sequential connection reuse...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(sequential_reuse_worker, i) for i in range(4)]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]
    
    # Analyze reuse patterns
    for result in results:
        reuse_ratio = result['total_queries'] / result['unique_connections']
        logger.info(f"Worker {result['worker_id']}: {result['unique_connections']} connections for {result['total_queries']} queries (reuse: {reuse_ratio:.1f}x)")
    
    stats = pool.get_statistics()
    overall_reuse = stats['total_requests'] / max(stats['created_connections'], 1)
    logger.info(f"Overall connection reuse: {overall_reuse:.1f}x")
    
    pool.close_all()
    
    # Verify good reuse patterns
    assert overall_reuse >= 2.0, f"Poor connection reuse: {overall_reuse:.1f}x"
    
    logger.info("✅ Connection reuse patterns test PASSED\n")
    return True


# =============================================================================
# Main Test Runner
# =============================================================================

def main():
    """Run all concurrency tests."""
    logger.info("🔧 Starting ConnectionPool Concurrency Tests")
    logger.info("=" * 80)
    
    tests = [
        # Threading tests
        ("High Concurrency Threading", test_high_concurrency_threading),
        ("Thread Safety Validation", test_thread_safety_validation),
        ("Connection Reuse Patterns", test_connection_reuse_patterns),
        
        # Multiprocessing tests  
        ("Basic Multiprocessing", test_basic_multiprocessing),
        ("Multiprocessing with Threading", test_multiprocessing_with_threading),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            logger.info(f"\n🔄 Running: {test_name}")
            start_time = time.time()
            
            success = test_func()
            duration = time.time() - start_time
            
            results.append({
                'test': test_name,
                'success': success,
                'duration': duration
            })
            
            if success:
                logger.info(f"✅ {test_name} PASSED (took {duration:.2f}s)")
            else:
                logger.error(f"❌ {test_name} FAILED")
                
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"❌ {test_name} FAILED with exception: {e}")
            results.append({
                'test': test_name,
                'success': False,
                'duration': duration,
                'error': str(e)
            })
    
    # Final summary
    logger.info("=" * 80)
    logger.info("📊 FINAL TEST SUMMARY")
    logger.info("=" * 80)
    
    passed = sum(1 for r in results if r['success'])
    total = len(results)
    total_duration = sum(r['duration'] for r in results)
    
    logger.info(f"Tests passed: {passed}/{total}")
    logger.info(f"Total test time: {total_duration:.2f} seconds")
    
    for result in results:
        status = "✅ PASS" if result['success'] else "❌ FAIL"
        logger.info(f"  {status} {result['test']} ({result['duration']:.2f}s)")
        if not result['success'] and 'error' in result:
            logger.info(f"    Error: {result['error']}")
    
    if passed == total:
        logger.info("\n🎉 ALL CONCURRENCY TESTS PASSED!")
        logger.info("✅ ConnectionPool is thread-safe and process-safe")
    else:
        logger.error(f"\n⚠️ {total - passed} tests failed")
    
    return passed == total


if __name__ == '__main__':
    # Import required for multiprocessing on macOS
    multiprocessing.set_start_method('spawn', force=True)
    
    success = main()
    exit(0 if success else 1)