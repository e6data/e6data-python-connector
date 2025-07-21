#!/usr/bin/env python3
"""
Test client for the mock gRPC server.
This script demonstrates the blue-green strategy switching behavior.
"""

import time
import logging
import threading
from e6data_python_connector import Connection

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Test configuration for mock server
TEST_CONFIG = {
    'host': 'localhost',
    'port': 50051,
    'username': 'test@example.com',
    'password': 'test_token',
    'database': 'sales',
    'catalog': 'default',
    'secure': False,  # Mock server uses insecure channel
}

def test_continuous_queries():
    """Run continuous queries to demonstrate strategy switching."""
    logger.info("Starting continuous query test...")
    
    # Create connection
    conn = Connection(**TEST_CONFIG)
    logger.info("Connected to mock server")
    
    query_count = 0
    start_time = time.time()
    
    try:
        while True:
            query_count += 1
            elapsed_time = time.time() - start_time
            
            logger.info(f"\n{'='*60}")
            logger.info(f"Query #{query_count} at {elapsed_time:.1f} seconds")
            
            # Create a new cursor for each query
            cursor = conn.cursor(catalog_name=TEST_CONFIG['catalog'])
            
            try:
                # Execute a simple query
                query = f"SELECT {query_count}, 'query_{query_count}', CURRENT_TIMESTAMP"
                query_id = cursor.execute(query)
                logger.info(f"Executed query: {query}")
                logger.info(f"Query ID: {query_id}")
                
                # Fetch results
                results = cursor.fetchall()
                logger.info(f"Results: {results}")
                
                # Get query stats
                explain_result = cursor.explain_analyse()
                logger.info(f"Query stats - Cached: {explain_result.get('is_cached')}, "
                          f"Parsing time: {explain_result.get('parsing_time')}ms")
                
                # Clear the query
                cursor.clear()
                logger.info("Query cleared")
                
            except Exception as e:
                logger.error(f"Query error: {e}")
                # Check if it's a strategy error
                if "456" in str(e):
                    logger.warning("Strategy mismatch detected! Connector should handle this automatically.")
            
            finally:
                cursor.close()
            
            # Wait before next query
            logger.info("Waiting 30 seconds before next query...")
            time.sleep(30)
            
            # After 5 minutes, also test schema operations
            if elapsed_time > 300 and query_count % 5 == 0:
                test_schema_operations(conn)
            
    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
    finally:
        conn.close()
        logger.info(f"Test completed. Ran {query_count} queries in {time.time() - start_time:.1f} seconds")

def test_schema_operations(conn):
    """Test schema-related operations."""
    logger.info("\n--- Testing schema operations ---")
    
    cursor = conn.cursor(catalog_name=TEST_CONFIG['catalog'])
    
    try:
        # Get schemas
        schemas = cursor.get_schema_names()
        logger.info(f"Available schemas: {schemas}")
        
        # Get tables
        tables = cursor.get_tables()
        logger.info(f"Tables in {TEST_CONFIG['database']}: {tables}")
        
        # Get columns for first table
        if tables:
            columns = cursor.get_columns(tables[0])
            logger.info(f"Columns in {tables[0]}: {columns}")
    
    except Exception as e:
        logger.error(f"Schema operation error: {e}")
    finally:
        cursor.close()

def test_concurrent_queries():
    """Test multiple concurrent queries during strategy switch."""
    logger.info("Starting concurrent query test...")
    
    def run_query_loop(thread_id):
        """Run queries in a loop for a single thread."""
        conn = Connection(**TEST_CONFIG)
        
        for i in range(10):
            try:
                cursor = conn.cursor(catalog_name=TEST_CONFIG['catalog'])
                query = f"SELECT {thread_id}, {i}, 'thread_{thread_id}_query_{i}'"
                
                query_id = cursor.execute(query)
                results = cursor.fetchall()
                logger.info(f"Thread {thread_id} - Query {i} completed: {results}")
                
                cursor.clear()
                cursor.close()
                
                time.sleep(15)  # Wait 15 seconds between queries
                
            except Exception as e:
                logger.error(f"Thread {thread_id} - Query {i} failed: {e}")
        
        conn.close()
        logger.info(f"Thread {thread_id} completed")
    
    # Start multiple threads
    threads = []
    for i in range(3):
        thread = threading.Thread(target=run_query_loop, args=(i,))
        threads.append(thread)
        thread.start()
    
    # Wait for all threads
    for thread in threads:
        thread.join()
    
    logger.info("Concurrent query test completed")

def main():
    """Main test function."""
    logger.info("Mock server test client started")
    logger.info("This test will demonstrate blue-green strategy switching")
    logger.info("The server switches strategies every 2 minutes")
    logger.info("Watch for strategy change notifications in the logs")
    
    print("\nSelect test mode:")
    print("1. Continuous queries (demonstrates strategy switching)")
    print("2. Concurrent queries (multiple threads)")
    print("3. Exit")
    
    choice = input("\nEnter choice (1-3): ")
    
    if choice == "1":
        test_continuous_queries()
    elif choice == "2":
        test_concurrent_queries()
    else:
        print("Exiting...")

if __name__ == "__main__":
    main()