#!/usr/bin/env python3
"""
Demo script showcasing ConnectionPool usage with e6data.

This demonstrates:
1. Basic pool usage
2. Thread-safe connection sharing
3. Concurrent query execution
4. Connection reuse across threads
5. Pool statistics monitoring
"""

import concurrent.futures
import logging
import os
import threading
import time
from typing import List, Dict, Any

from e6data_python_connector.connection_pool import ConnectionPool

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ConnectionPoolDemo:
    """Demonstration of ConnectionPool features."""
    
    def __init__(self):
        """Initialize demo with connection parameters."""
        # Get connection parameters from environment or use defaults
        self.connection_params = {
            'host': os.getenv('ENGINE_IP', 'your.cluster.e6data.com'),
            'port': int(os.getenv('PORT', '443')),
            'username': os.getenv('EMAIL', 'user@example.com'),
            'password': os.getenv('PASSWORD', 'your_access_token'),
            'database': os.getenv('DB_NAME', 'default'),
            'catalog': os.getenv('CATALOG', 'glue'),
            'cluster_name': os.getenv('CLUSTER_NAME', 'your_cluster'),
            'secure': True
        }
        
        self.pool = None
    
    def create_pool(self, min_size=2, max_size=10):
        """Create a connection pool."""
        logger.info(f"Creating connection pool (min={min_size}, max={max_size})")
        
        self.pool = ConnectionPool(
            min_size=min_size,
            max_size=max_size,
            max_overflow=5,
            timeout=30.0,
            recycle=3600,
            debug=True,  # Enable debug logging
            pre_ping=True,  # Check connection health
            **self.connection_params
        )
        
        stats = self.pool.get_statistics()
        logger.info(f"Pool created with stats: {stats}")
        return self.pool
    
    def execute_query(self, query_id: str, query: str, sleep_time: float = 0.5) -> Dict[str, Any]:
        """
        Execute a query using a pooled connection.
        
        This demonstrates connection reuse - the same thread will reuse
        its connection for multiple queries.
        """
        thread_id = threading.get_ident()
        logger.info(f"[Query {query_id}] Starting on thread {thread_id}")
        
        try:
            # Get connection from pool
            conn = self.pool.get_connection()
            logger.info(f"[Query {query_id}] Got connection (use_count={conn.use_count})")
            
            # Create cursor and execute query
            cursor = conn.cursor()
            cursor.execute(query)
            
            # Simulate processing time
            time.sleep(sleep_time)
            
            # Fetch results
            results = cursor.fetchall()
            logger.info(f"[Query {query_id}] Completed with {len(results) if results else 0} rows")
            
            # Return connection to pool
            self.pool.return_connection(conn)
            
            return {
                'query_id': query_id,
                'thread_id': thread_id,
                'success': True,
                'rows': len(results) if results else 0
            }
            
        except Exception as e:
            logger.error(f"[Query {query_id}] Failed: {e}")
            return {
                'query_id': query_id,
                'thread_id': thread_id,
                'success': False,
                'error': str(e)
            }
    
    def demo_basic_usage(self):
        """Demo 1: Basic pool usage with single thread."""
        logger.info("\n" + "="*60)
        logger.info("Demo 1: Basic Pool Usage")
        logger.info("="*60)
        
        # Create pool
        self.create_pool(min_size=1, max_size=5)
        
        # Execute queries sequentially
        queries = [
            "SELECT 1 as test",
            "SELECT 2 as test",
            "SELECT 3 as test"
        ]
        
        for i, query in enumerate(queries):
            result = self.execute_query(f"basic_{i}", query, sleep_time=0.2)
            logger.info(f"Result: {result}")
        
        # Show statistics
        stats = self.pool.get_statistics()
        logger.info(f"Pool statistics: {stats}")
        
        # Note: Same thread reuses the same connection
        logger.info("Notice: All queries from same thread reused the same connection")
    
    def demo_concurrent_queries(self):
        """Demo 2: Concurrent query execution with thread pool."""
        logger.info("\n" + "="*60)
        logger.info("Demo 2: Concurrent Query Execution")
        logger.info("="*60)
        
        # Create pool
        self.create_pool(min_size=3, max_size=10)
        
        # Define queries
        queries = [f"SELECT {i} as id, 'query_{i}' as name" for i in range(20)]
        
        # Execute queries concurrently
        logger.info(f"Executing {len(queries)} queries concurrently...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for i, query in enumerate(queries):
                future = executor.submit(
                    self.execute_query,
                    f"concurrent_{i}",
                    query,
                    sleep_time=0.5
                )
                futures.append(future)
            
            # Collect results
            results = []
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results.append(result)
        
        # Analyze results
        successful = sum(1 for r in results if r['success'])
        unique_threads = len(set(r['thread_id'] for r in results))
        
        logger.info(f"Completed: {successful}/{len(queries)} successful")
        logger.info(f"Used {unique_threads} unique threads")
        
        # Show final statistics
        stats = self.pool.get_statistics()
        logger.info(f"Final pool statistics: {stats}")
        
        # Note about connection reuse
        logger.info("Notice: Each thread reused its connection for multiple queries")
    
    def demo_connection_reuse(self):
        """Demo 3: Connection reuse pattern within threads."""
        logger.info("\n" + "="*60)
        logger.info("Demo 3: Connection Reuse Pattern")
        logger.info("="*60)
        
        # Create pool
        self.create_pool(min_size=2, max_size=5)
        
        def worker_task(worker_id: int, num_queries: int):
            """Worker that executes multiple queries."""
            thread_id = threading.get_ident()
            logger.info(f"Worker {worker_id} started on thread {thread_id}")
            
            for i in range(num_queries):
                query = f"SELECT {worker_id} as worker, {i} as query_num"
                result = self.execute_query(f"worker_{worker_id}_query_{i}", query, sleep_time=0.1)
                
                # Log connection reuse
                if i == 0:
                    logger.info(f"Worker {worker_id}: First query on thread {thread_id}")
                else:
                    logger.info(f"Worker {worker_id}: Reusing connection for query {i}")
            
            return f"Worker {worker_id} completed {num_queries} queries"
        
        # Run workers
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(worker_task, i, 5)
                for i in range(3)
            ]
            
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                logger.info(result)
        
        # Show statistics
        stats = self.pool.get_statistics()
        logger.info(f"Pool statistics: {stats}")
        logger.info("Notice: Each worker thread reused same connection for all its queries")
    
    def demo_context_manager(self):
        """Demo 4: Using context manager for automatic connection management."""
        logger.info("\n" + "="*60)
        logger.info("Demo 4: Context Manager Usage")
        logger.info("="*60)
        
        # Create pool
        self.create_pool(min_size=1, max_size=5)
        
        # Use context manager
        logger.info("Using context manager for automatic connection management...")
        
        with self.pool.get_connection_context() as conn:
            logger.info(f"Got connection in context (use_count={conn.use_count})")
            
            cursor = conn.cursor()
            cursor.execute("SELECT 'context_manager_test' as test")
            results = cursor.fetchall()
            
            logger.info(f"Query executed, results: {results}")
            # Connection automatically returned when context exits
        
        logger.info("Connection automatically returned to pool")
        
        # Show statistics
        stats = self.pool.get_statistics()
        logger.info(f"Pool statistics after context exit: {stats}")
    
    def demo_pool_exhaustion(self):
        """Demo 5: Handling pool exhaustion with overflow."""
        logger.info("\n" + "="*60)
        logger.info("Demo 5: Pool Exhaustion and Overflow")
        logger.info("="*60)
        
        # Create small pool
        self.create_pool(min_size=1, max_size=2)
        self.pool.max_overflow = 2  # Allow 2 overflow connections
        
        logger.info("Pool created with max_size=2, max_overflow=2")
        
        # Hold connections without returning them
        held_connections = []
        
        for i in range(4):
            try:
                logger.info(f"Getting connection {i+1}...")
                conn = self.pool.get_connection(timeout=2)
                held_connections.append(conn)
                
                stats = self.pool.get_statistics()
                logger.info(f"Got connection {i+1}. Stats: {stats}")
                
            except TimeoutError as e:
                logger.error(f"Failed to get connection {i+1}: {e}")
        
        # Try to get one more (should fail)
        logger.info("Trying to get 5th connection (should timeout)...")
        try:
            conn = self.pool.get_connection(timeout=1)
            logger.error("Should not have gotten connection!")
        except TimeoutError:
            logger.info("Correctly timed out when pool exhausted")
        
        # Return all connections
        logger.info("Returning all connections...")
        for conn in held_connections:
            self.pool.return_connection(conn)
        
        # Show final statistics
        stats = self.pool.get_statistics()
        logger.info(f"Final pool statistics: {stats}")
    
    def cleanup(self):
        """Clean up pool resources."""
        if self.pool:
            logger.info("\nClosing all connections in pool...")
            self.pool.close_all()
            logger.info("Pool closed")
    
    def run_all_demos(self):
        """Run all demonstration scenarios."""
        try:
            self.demo_basic_usage()
            time.sleep(1)
            
            self.demo_concurrent_queries()
            time.sleep(1)
            
            self.demo_connection_reuse()
            time.sleep(1)
            
            self.demo_context_manager()
            time.sleep(1)
            
            self.demo_pool_exhaustion()
            
        finally:
            self.cleanup()


def main():
    """Main entry point for demo."""
    logger.info("="*60)
    logger.info("E6Data Connection Pool Demo")
    logger.info("="*60)
    
    # Check for required environment variables
    required_vars = ['ENGINE_IP', 'EMAIL', 'PASSWORD', 'DB_NAME']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.warning(f"Missing environment variables: {missing_vars}")
        logger.info("\nTo run this demo with real connections, set:")
        for var in required_vars:
            logger.info(f"  export {var}=<your_value>")
        logger.info("\nRunning with mock connection parameters...")
        logger.info("Note: Queries will fail without valid credentials")
    
    # Run demo
    demo = ConnectionPoolDemo()
    
    # Choose which demos to run
    choice = input("\nSelect demo to run (1-5 for individual, 'all' for all, 'q' to quit): ")
    
    if choice == 'q':
        return
    elif choice == '1':
        demo.demo_basic_usage()
    elif choice == '2':
        demo.demo_concurrent_queries()
    elif choice == '3':
        demo.demo_connection_reuse()
    elif choice == '4':
        demo.demo_context_manager()
    elif choice == '5':
        demo.demo_pool_exhaustion()
    elif choice.lower() == 'all':
        demo.run_all_demos()
    else:
        logger.info("Invalid choice. Running all demos...")
        demo.run_all_demos()
    
    demo.cleanup()
    logger.info("\nDemo completed!")


if __name__ == "__main__":
    main()