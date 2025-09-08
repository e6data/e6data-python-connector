"""
Connection Pool implementation for e6data Python connector.

This module provides a thread-safe connection pool that allows multiple threads
to share and reuse connections efficiently, reducing connection overhead and
improving performance for concurrent query execution.
"""

import logging
import queue
import threading
import time
from contextlib import contextmanager
from typing import Dict, Any, Optional, List

from e6data_python_connector.e6data_grpc import Connection

# Set up logging
logger = logging.getLogger(__name__)


class PooledConnection:
    """Wrapper around Connection to track pool-specific metadata."""
    
    def __init__(self, connection: Connection, pool: 'ConnectionPool'):
        self.connection = connection
        self.pool = pool
        self.in_use = False
        self.last_used = time.time()
        self.created_at = time.time()
        self.use_count = 0
        self.thread_id = None
        self._cursor = None
    
    def cursor(self, catalog_name=None, db_name=None):
        """Create a cursor from the pooled connection."""
        if self._cursor is None or not self._is_cursor_valid():
            self._cursor = self.connection.cursor(catalog_name, db_name)
        return self._cursor
    
    def _is_cursor_valid(self):
        """Check if the current cursor is still valid."""
        try:
            # Check if cursor exists and connection is still alive
            return self._cursor is not None and self.connection.check_connection()
        except:
            return False
    
    def close_cursor(self):
        """Close the current cursor if it exists."""
        if self._cursor:
            try:
                self._cursor.close()
            except:
                pass
            finally:
                self._cursor = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Return connection to pool when done
        self.pool.return_connection(self)


class ConnectionPool:
    """
    Thread-safe connection pool for e6data connections.
    
    Features:
    - Automatic connection creation and management
    - Thread-safe connection checkout/checkin
    - Connection health checking and recovery
    - Connection lifecycle management (max age, idle timeout)
    - Statistics and monitoring
    - Context manager support for automatic connection return
    """
    
    def __init__(
        self,
        min_size: int = 2,
        max_size: int = 10,
        max_overflow: int = 5,
        timeout: float = 30.0,
        recycle: int = 3600,
        debug: bool = False,
        pre_ping: bool = True,
        **connection_params
    ):
        """
        Initialize the connection pool.
        
        Parameters:
        -----------
        min_size : int
            Minimum number of connections to maintain in the pool
        max_size : int
            Maximum number of connections in the pool
        max_overflow : int
            Maximum overflow connections that can be created
        timeout : float
            Timeout in seconds for getting a connection from the pool
        recycle : int
            Maximum age in seconds for a connection before recycling
        debug : bool
            Enable debug logging for pool operations
        pre_ping : bool
            Check connection health before returning from pool
        **connection_params : dict
            Parameters to pass to Connection constructor
        """
        self.min_size = min_size
        self.max_size = max_size
        self.max_overflow = max_overflow
        self.timeout = timeout
        self.recycle = recycle
        self.debug = debug
        self.pre_ping = pre_ping
        self.connection_params = connection_params
        
        # Pool storage
        self._pool = queue.Queue(maxsize=max_size)
        self._overflow = 0
        self._lock = threading.Lock()
        
        # Statistics
        self._created_connections = 0
        self._active_connections = 0
        self._waiting_threads = 0
        self._total_requests = 0
        self._failed_connections = 0
        
        # Connection tracking
        self._all_connections: List[PooledConnection] = []
        self._thread_connections: Dict[int, PooledConnection] = {}
        
        # Initialize minimum connections
        self._initialize_pool()
        
        if self.debug:
            logger.setLevel(logging.DEBUG)
            logger.debug(f"Connection pool initialized with min_size={min_size}, max_size={max_size}")
    
    def _initialize_pool(self):
        """Initialize the pool with minimum number of connections."""
        for i in range(self.min_size):
            try:
                conn = self._create_connection()
                self._pool.put(conn)
                if self.debug:
                    logger.debug(f"Created initial connection {i+1}/{self.min_size}")
            except Exception as e:
                logger.error(f"Failed to create initial connection: {e}")
                self._failed_connections += 1
    
    def _create_connection(self) -> PooledConnection:
        """Create a new pooled connection."""
        try:
            raw_conn = Connection(**self.connection_params)
            pooled_conn = PooledConnection(raw_conn, self)
            
            with self._lock:
                self._created_connections += 1
                self._all_connections.append(pooled_conn)
            
            if self.debug:
                logger.debug(f"Created new connection (total: {self._created_connections})")
            
            return pooled_conn
        except Exception as e:
            logger.error(f"Failed to create connection: {e}")
            raise
    
    def _check_connection_health(self, conn: PooledConnection) -> bool:
        """Check if a connection is healthy and usable."""
        try:
            # Check connection age
            age = time.time() - conn.created_at
            if 0 < self.recycle < age:
                if self.debug:
                    logger.debug(f"Connection exceeded recycle time ({age:.1f}s > {self.recycle}s)")
                return False
            
            # Check connection validity
            if not conn.connection.check_connection():
                if self.debug:
                    logger.debug("Connection check failed")
                return False
            
            # Pre-ping check if enabled
            if self.pre_ping:
                try:
                    # Try to get session ID to verify connection is alive
                    _ = conn.connection.get_session_id
                    return True
                except Exception as e:
                    if self.debug:
                        logger.debug(f"Pre-ping failed: {e}")
                    return False
            
            return True
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
    
    def _replace_connection(self, old_conn: PooledConnection) -> PooledConnection:
        """Replace a broken connection with a new one."""
        try:
            # Close the old connection
            try:
                old_conn.close_cursor()
                old_conn.connection.close()
            except:
                pass
            
            # Remove from tracking
            with self._lock:
                if old_conn in self._all_connections:
                    self._all_connections.remove(old_conn)
            
            # Create new connection
            new_conn = self._create_connection()
            
            if self.debug:
                logger.debug("Replaced broken connection with new one")
            
            return new_conn
        except Exception as e:
            logger.error(f"Failed to replace connection: {e}")
            raise
    
    def get_connection(self, timeout: Optional[float] = None) -> PooledConnection:
        """
        Get a connection from the pool.
        
        Parameters:
        -----------
        timeout : float, optional
            Override default timeout for this request
        
        Returns:
        --------
        PooledConnection
            A pooled connection ready for use
        
        Raises:
        -------
        TimeoutError
            If no connection available within timeout
        """
        timeout = timeout or self.timeout
        thread_id = threading.get_ident()
        
        with self._lock:
            self._total_requests += 1
            
            # Check if thread already has a connection
            if thread_id in self._thread_connections:
                conn = self._thread_connections[thread_id]
                if self._check_connection_health(conn):
                    conn.use_count += 1
                    conn.last_used = time.time()
                    if self.debug:
                        logger.debug(f"Reusing connection for thread {thread_id}")
                    return conn
                else:
                    # Remove unhealthy connection
                    del self._thread_connections[thread_id]
        
        start_time = time.time()
        
        while True:
            try:
                # Try to get from pool
                try:
                    conn = self._pool.get(timeout=0.1)
                    
                    # Check connection health
                    if self._check_connection_health(conn):
                        with self._lock:
                            conn.in_use = True
                            conn.thread_id = thread_id
                            conn.use_count += 1
                            conn.last_used = time.time()
                            self._active_connections += 1
                            self._thread_connections[thread_id] = conn
                        
                        if self.debug:
                            logger.debug(f"Checked out connection for thread {thread_id}")
                        
                        return conn
                    else:
                        # Replace unhealthy connection
                        conn = self._replace_connection(conn)
                        with self._lock:
                            conn.in_use = True
                            conn.thread_id = thread_id
                            conn.use_count += 1
                            conn.last_used = time.time()
                            self._active_connections += 1
                            self._thread_connections[thread_id] = conn
                        return conn
                        
                except queue.Empty:
                    # Pool is empty, try to create overflow connection
                    with self._lock:
                        current_total = self._created_connections
                        
                        if current_total < self.max_size + self.max_overflow:
                            self._overflow += 1
                            
                    if current_total < self.max_size + self.max_overflow:
                        try:
                            conn = self._create_connection()
                            with self._lock:
                                conn.in_use = True
                                conn.thread_id = thread_id
                                conn.use_count += 1
                                conn.last_used = time.time()
                                self._active_connections += 1
                                self._thread_connections[thread_id] = conn
                            
                            if self.debug:
                                logger.debug(f"Created overflow connection for thread {thread_id}")
                            
                            return conn
                        except Exception as e:
                            with self._lock:
                                self._overflow -= 1
                                self._failed_connections += 1
                            raise
                
                # Check timeout
                if time.time() - start_time > timeout:
                    raise TimeoutError(f"Failed to get connection within {timeout} seconds")
                
                # Wait a bit before retrying
                with self._lock:
                    self._waiting_threads += 1
                
                time.sleep(0.1)
                
                with self._lock:
                    self._waiting_threads -= 1
                    
            except Exception as e:
                if not isinstance(e, TimeoutError):
                    logger.error(f"Error getting connection: {e}")
                raise
    
    def return_connection(self, conn: PooledConnection):
        """
        Return a connection to the pool.
        
        Parameters:
        -----------
        conn : PooledConnection
            The connection to return to the pool
        """
        if not isinstance(conn, PooledConnection):
            return
        
        thread_id = threading.get_ident()
        
        with self._lock:
            # Remove from thread mapping if it's the current thread's connection
            if thread_id in self._thread_connections and self._thread_connections[thread_id] == conn:
                del self._thread_connections[thread_id]
            
            conn.in_use = False
            conn.thread_id = None
            self._active_connections = max(0, self._active_connections - 1)
        
        # Close cursor if exists
        conn.close_cursor()
        
        # Check if connection is still healthy
        if self._check_connection_health(conn):
            # Return to pool if there's space
            try:
                self._pool.put_nowait(conn)
                if self.debug:
                    logger.debug(f"Returned connection to pool from thread {thread_id}")
            except queue.Full:
                # Pool is full, close the connection
                try:
                    conn.connection.close()
                except:
                    pass
                with self._lock:
                    if conn in self._all_connections:
                        self._all_connections.remove(conn)
                    self._overflow = max(0, self._overflow - 1)
                if self.debug:
                    logger.debug("Closed overflow connection (pool full)")
        else:
            # Connection is unhealthy, close it
            try:
                conn.connection.close()
            except:
                pass
            with self._lock:
                if conn in self._all_connections:
                    self._all_connections.remove(conn)
                self._created_connections -= 1
            
            # Create replacement if below min_size
            if self._pool.qsize() < self.min_size:
                try:
                    new_conn = self._create_connection()
                    self._pool.put_nowait(new_conn)
                except:
                    pass
    
    @contextmanager
    def get_connection_context(self, timeout: Optional[float] = None):
        """
        Context manager for getting and returning connections.
        
        Usage:
        ------
        with pool.get_connection_context() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            results = cursor.fetchall()
        """
        conn = self.get_connection(timeout)
        try:
            yield conn
        finally:
            self.return_connection(conn)
    
    def close_all(self):
        """Close all connections in the pool."""
        # Close connections in pool
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close_cursor()
                conn.connection.close()
            except:
                pass
        
        # Close all tracked connections
        with self._lock:
            for conn in self._all_connections:
                try:
                    conn.close_cursor()
                    conn.connection.close()
                except:
                    pass
            
            self._all_connections.clear()
            self._thread_connections.clear()
            self._created_connections = 0
            self._active_connections = 0
        
        if self.debug:
            logger.debug("Closed all connections in pool")
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get pool statistics.
        
        Returns:
        --------
        dict
            Dictionary containing pool statistics
        """
        with self._lock:
            return {
                'created_connections': self._created_connections,
                'active_connections': self._active_connections,
                'idle_connections': self._pool.qsize(),
                'waiting_threads': self._waiting_threads,
                'total_requests': self._total_requests,
                'failed_connections': self._failed_connections,
                'overflow_connections': self._overflow,
                'thread_connections': len(self._thread_connections),
                'pool_size': len(self._all_connections)
            }
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_all()
    
    def __del__(self):
        """Cleanup connections when pool is destroyed."""
        try:
            self.close_all()
        except:
            pass