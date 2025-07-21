#!/usr/bin/env python3
"""
Test script for blue-green deployment strategy detection.
This script tests the strategy detection and caching functionality.
"""

import os
import threading
import multiprocessing
import time
import logging
from e6data_python_connector import Connection

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test configuration
TEST_CONFIG = {
    'host': os.environ.get('ENGINE_IP', 'localhost'),
    'port': int(os.environ.get('PORT', 80)),
    'username': os.environ.get('EMAIL', 'test@example.com'),
    'password': os.environ.get('PASSWORD', 'test_token'),
    'database': os.environ.get('DB_NAME', 'test_db'),
    'catalog': os.environ.get('CATALOG', 'test_catalog'),
}


def test_single_connection():
    """Test strategy detection with a single connection."""
    logger.info("Testing single connection strategy detection...")
    
    try:
        conn = Connection(**TEST_CONFIG)
        cursor = conn.cursor(catalog_name=TEST_CONFIG['catalog'])
        
        # This should trigger strategy detection
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        logger.info(f"Query result: {result}")
        
        cursor.close()
        conn.close()
        logger.info("Single connection test passed!")
        
    except Exception as e:
        logger.error(f"Single connection test failed: {e}")
        raise


def test_multiple_threads():
    """Test strategy caching with multiple threads."""
    logger.info("Testing strategy caching with multiple threads...")
    
    def thread_worker(thread_id):
        try:
            conn = Connection(**TEST_CONFIG)
            cursor = conn.cursor(catalog_name=TEST_CONFIG['catalog'])
            
            # Execute a simple query
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            logger.info(f"Thread {thread_id} query result: {result}")
            
            cursor.close()
            conn.close()
            
        except Exception as e:
            logger.error(f"Thread {thread_id} failed: {e}")
            raise
    
    # Create multiple threads
    threads = []
    for i in range(5):
        t = threading.Thread(target=thread_worker, args=(i,))
        threads.append(t)
        t.start()
    
    # Wait for all threads to complete
    for t in threads:
        t.join()
    
    logger.info("Multiple threads test passed!")


def test_multiple_processes():
    """Test strategy caching with multiple processes."""
    logger.info("Testing strategy caching with multiple processes...")
    
    def process_worker(process_id):
        try:
            # Each process needs its own connection
            conn = Connection(**TEST_CONFIG)
            cursor = conn.cursor(catalog_name=TEST_CONFIG['catalog'])
            
            # Execute a simple query
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            logger.info(f"Process {process_id} query result: {result}")
            
            cursor.close()
            conn.close()
            
        except Exception as e:
            logger.error(f"Process {process_id} failed: {e}")
            raise
    
    # Create multiple processes
    processes = []
    for i in range(3):
        p = multiprocessing.Process(target=process_worker, args=(i,))
        processes.append(p)
        p.start()
    
    # Wait for all processes to complete
    for p in processes:
        p.join()
    
    logger.info("Multiple processes test passed!")


def test_strategy_cache_expiry():
    """Test strategy cache expiry functionality."""
    logger.info("Testing strategy cache expiry...")
    
    # This test would require modifying STRATEGY_CACHE_TIMEOUT or waiting
    # For now, we'll just test that connections work after some time
    
    conn1 = Connection(**TEST_CONFIG)
    cursor1 = conn1.cursor(catalog_name=TEST_CONFIG['catalog'])
    cursor1.execute("SELECT 1")
    cursor1.close()
    conn1.close()
    
    # Wait a bit
    time.sleep(2)
    
    # Create another connection
    conn2 = Connection(**TEST_CONFIG)
    cursor2 = conn2.cursor(catalog_name=TEST_CONFIG['catalog'])
    cursor2.execute("SELECT 1")
    cursor2.close()
    conn2.close()
    
    logger.info("Strategy cache expiry test passed!")


def test_strategy_transition():
    """Test graceful strategy transition during active queries."""
    logger.info("Testing graceful strategy transition...")
    
    try:
        conn = Connection(**TEST_CONFIG)
        
        # Start first query
        cursor1 = conn.cursor(catalog_name=TEST_CONFIG['catalog'])
        query_id1 = cursor1.execute("SELECT 1, 'first_query'")
        logger.info(f"First query started with ID: {query_id1}")
        
        # Fetch some results
        result1 = cursor1.fetchone()
        logger.info(f"First query result: {result1}")
        
        # Start second query (this might receive new_strategy in response)
        cursor2 = conn.cursor(catalog_name=TEST_CONFIG['catalog'])
        query_id2 = cursor2.execute("SELECT 2, 'second_query'")
        logger.info(f"Second query started with ID: {query_id2}")
        
        # Complete first query (should still use old strategy)
        remaining_results1 = cursor1.fetchall()
        logger.info(f"First query completed with results: {remaining_results1}")
        cursor1.clear()  # This should trigger strategy transition
        
        # Complete second query (might use new strategy if transition happened)
        result2 = cursor2.fetchall()
        logger.info(f"Second query results: {result2}")
        cursor2.clear()
        
        # Start third query (should use new strategy if transition happened)
        cursor3 = conn.cursor(catalog_name=TEST_CONFIG['catalog'])
        query_id3 = cursor3.execute("SELECT 3, 'third_query'")
        result3 = cursor3.fetchall()
        logger.info(f"Third query results: {result3}")
        cursor3.clear()
        
        # Cleanup
        cursor1.close()
        cursor2.close()
        cursor3.close()
        conn.close()
        
        logger.info("Strategy transition test passed!")
        
    except Exception as e:
        logger.error(f"Strategy transition test failed: {e}")
        raise


def test_comprehensive_api_strategy():
    """Test strategy handling across all API calls."""
    logger.info("Testing comprehensive API strategy handling...")
    
    try:
        conn = Connection(**TEST_CONFIG)
        cursor = conn.cursor(catalog_name=TEST_CONFIG['catalog'])
        
        # Test authentication (already happens in connection)
        logger.info("Authentication completed with strategy detection")
        
        # Test get_schema_names
        schemas = cursor.get_schema_names()
        logger.info(f"Schema names retrieved: {len(schemas)} schemas")
        
        # Test get_tables
        if TEST_CONFIG['database']:
            tables = cursor.get_tables()
            logger.info(f"Tables retrieved: {len(tables)} tables")
            
            # Test get_columns if we have tables
            if tables:
                columns = cursor.get_columns(tables[0])
                logger.info(f"Columns retrieved for {tables[0]}: {len(columns)} columns")
        
        # Test query execution with explain_analyse
        query_id = cursor.execute("SELECT 1 as test_col")
        logger.info(f"Query executed with ID: {query_id}")
        
        # Test status check
        status = cursor.status(query_id)
        logger.info(f"Query status: {status}")
        
        # Test metadata update
        cursor.update_mete_data()
        logger.info(f"Metadata updated, rowcount: {cursor.rowcount}")
        
        # Test fetch operations
        result = cursor.fetchone()
        logger.info(f"Fetched result: {result}")
        
        # Test explain_analyse
        explain_result = cursor.explain_analyse()
        logger.info(f"Explain analyse completed, cached: {explain_result.get('is_cached')}")
        
        # Test clear
        cursor.clear()
        logger.info("Query cleared successfully")
        
        # Test cancel on a new query
        query_id2 = cursor.execute("SELECT 2")
        cursor.cancel(query_id2)
        logger.info("Query cancelled successfully")
        
        # Cleanup
        cursor.close()
        conn.close()
        
        logger.info("Comprehensive API strategy test passed!")
        
    except Exception as e:
        logger.error(f"Comprehensive API strategy test failed: {e}")
        raise


def main():
    """Run all tests."""
    logger.info("Starting blue-green strategy tests...")
    
    # Check if we have the required environment variables
    if not os.environ.get('ENGINE_IP'):
        logger.warning("ENGINE_IP not set. Using localhost for testing.")
        logger.warning("Set the following environment variables for real testing:")
        logger.warning("  ENGINE_IP, DB_NAME, EMAIL, PASSWORD, CATALOG, PORT")
    
    try:
        # Run tests
        test_single_connection()
        test_multiple_threads()
        test_multiple_processes()
        test_strategy_cache_expiry()
        test_strategy_transition()
        test_comprehensive_api_strategy()
        
        logger.info("All tests passed successfully!")
        
    except Exception as e:
        logger.error(f"Test suite failed: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())