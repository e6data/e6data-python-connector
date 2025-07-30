"""
Strategy-aware connection base class that handles all strategy detection and isolation logic.

This module provides a base class that Connection can inherit from to centralize all
strategy management, query isolation, and mid-query strategy change prevention.
"""

import logging
import threading
import time
import weakref
import grpc
from typing import Dict, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

# Set up logging
_logger = logging.getLogger(__name__)


class QueryState(Enum):
    """Query execution states."""
    PREPARING = "preparing"
    EXECUTING = "executing"
    FETCHING = "fetching"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class QueryInfo:
    """Information about a running query."""
    query_id: str
    cursor_id: str
    strategy: str
    state: QueryState
    created_time: float
    last_activity_time: float
    connection_id: Optional[str] = None
    engine_ip: Optional[str] = None
    metadata_requests: int = 0
    fetch_requests: int = 0
    
    def __post_init__(self):
        self.last_activity_time = time.time()
    
    def update_activity(self):
        """Update the last activity timestamp."""
        self.last_activity_time = time.time()
    
    def is_active(self) -> bool:
        """Check if query is in an active state."""
        return self.state in [QueryState.PREPARING, QueryState.EXECUTING, QueryState.FETCHING]
    
    def is_completed(self) -> bool:
        """Check if query is completed (success, failed, or cancelled)."""
        return self.state in [QueryState.COMPLETED, QueryState.FAILED, QueryState.CANCELLED]


class StrategyAwareConnection:
    """
    Base class that provides strategy awareness and query isolation for connections.
    
    This class handles:
    1. Strategy detection and caching
    2. Query-specific strategy isolation
    3. Mid-query strategy change prevention
    4. Process-safe strategy management
    5. Automatic strategy transitions
    """
    
    # Class-level shared state for process safety
    _strategy_lock = threading.RLock()
    _process_strategies: Dict[int, Dict[str, Any]] = {}
    _cleanup_interval = 300  # 5 minutes
    _last_cleanup = time.time()
    
    def __init__(self):
        """Initialize strategy-aware connection base."""
        self._connection_id = f"conn_{id(self)}_{int(time.time() * 1000)}"
        self._instance_lock = threading.RLock()
        
        # Instance-level strategy management
        self._active_strategy: Optional[str] = None
        self._pending_strategy: Optional[str] = None
        self._strategy_transition_pending = False
        self._last_strategy_check = 0
        self._strategy_cache_timeout = 300  # 5 minutes
        
        # Query isolation management
        self._active_queries: Dict[str, QueryInfo] = {}
        self._cursor_to_query: Dict[str, str] = {}
        self._query_counter = 0
        
        # Cursor weak references for cleanup
        self._cursor_refs: Dict[str, weakref.ref] = {}
        
        # Initialize process-level storage
        self._init_process_storage()
    
    def _init_process_storage(self):
        """Initialize process-level storage for cross-instance coordination."""
        import os
        pid = os.getpid()
        
        with self._strategy_lock:
            if pid not in self._process_strategies:
                self._process_strategies[pid] = {
                    'active_strategy': None,
                    'pending_strategy': None,
                    'strategy_transition_pending': False,
                    'query_strategy_map': {},  # Maps query_id to strategy
                    'last_transition_time': 0,
                    'connection_queries': defaultdict(set)  # Maps connection_id to query_ids
                }
    
    def _get_process_storage(self) -> Dict[str, Any]:
        """Get process-level storage for current process."""
        import os
        pid = os.getpid()
        return self._process_strategies.get(pid, {})
    
    def get_strategy_header(self, engine_ip: Optional[str] = None, 
                           cluster: Optional[str] = None, 
                           query_id: Optional[str] = None) -> list:
        """
        Generate gRPC metadata headers with strategy information.
        
        Args:
            engine_ip: Engine IP address
            cluster: Cluster name
            query_id: Query ID for query-specific strategy lookup
            
        Returns:
            List of metadata tuples for gRPC
        """
        metadata = []
        
        # Add engine IP if provided
        if engine_ip:
            metadata.append(('engine_ip', engine_ip))
        
        # Add cluster if provided
        if cluster:
            metadata.append(('cluster', cluster))
        
        # Determine strategy to use
        strategy = None
        
        # First check for query-specific strategy
        if query_id:
            with self._instance_lock:
                query_info = self._active_queries.get(query_id)
                if query_info:
                    strategy = query_info.strategy
                    query_info.update_activity()
        
        # Fallback to active strategy
        if not strategy:
            strategy = self.get_active_strategy()
        
        # Add strategy header
        if strategy:
            metadata.append(('strategy', strategy))
        
        return metadata
    
    def get_active_strategy(self) -> Optional[str]:
        """Get the currently active strategy."""
        with self._strategy_lock:
            storage = self._get_process_storage()
            
            # Check instance cache first
            if self._active_strategy and (time.time() - self._last_strategy_check < self._strategy_cache_timeout):
                return self._active_strategy
            
            # Get from process storage
            self._active_strategy = storage.get('active_strategy')
            self._last_strategy_check = time.time()
            
            return self._active_strategy
    
    def set_active_strategy(self, strategy: str):
        """Set the active strategy."""
        with self._strategy_lock:
            storage = self._get_process_storage()
            storage['active_strategy'] = strategy
            self._active_strategy = strategy
            self._last_strategy_check = time.time()
            
            _logger.info(f"Set active strategy to: {strategy}")
    
    def set_pending_strategy(self, strategy: str):
        """Set a pending strategy for future transition."""
        with self._strategy_lock:
            storage = self._get_process_storage()
            
            current = storage.get('active_strategy')
            if strategy == current:
                return
            
            storage['pending_strategy'] = strategy
            storage['strategy_transition_pending'] = True
            self._pending_strategy = strategy
            self._strategy_transition_pending = True
            
            _logger.info(f"Set pending strategy: {current} -> {strategy}")
            
            # Check if we can apply immediately
            self._check_strategy_transition()
    
    def handle_strategy_response(self, response: Any, current_strategy: Optional[str] = None):
        """
        Handle strategy information in gRPC responses.
        
        Args:
            response: gRPC response object
            current_strategy: Current strategy used for the request
        """
        if hasattr(response, 'new_strategy') and response.new_strategy:
            new_strategy = response.new_strategy.lower()
            active_strategy = self.get_active_strategy()
            
            if new_strategy != active_strategy:
                self.set_pending_strategy(new_strategy)
    
    def register_cursor(self, cursor: Any) -> str:
        """
        Register a cursor for query tracking.
        
        Args:
            cursor: The cursor object
            
        Returns:
            cursor_id: Unique identifier for the cursor
        """
        with self._instance_lock:
            cursor_id = f"cursor_{id(cursor)}_{int(time.time() * 1000)}"
            
            # Store weak reference to cursor
            self._cursor_refs[cursor_id] = weakref.ref(cursor, 
                lambda ref: self._cleanup_cursor_ref(cursor_id))
            
            _logger.debug(f"Registered cursor {cursor_id} for connection {self._connection_id}")
            return cursor_id
    
    def start_query(self, cursor_id: str) -> Tuple[str, str]:
        """
        Start a new query with strategy isolation.
        
        Args:
            cursor_id: Cursor identifier
            
        Returns:
            Tuple of (query_id, effective_strategy)
        """
        with self._instance_lock:
            self._query_counter += 1
            query_id = f"query_{cursor_id}_{self._query_counter}_{int(time.time() * 1000)}"
            
            # Determine effective strategy
            effective_strategy = self.get_active_strategy()
            if not effective_strategy:
                effective_strategy = 'blue'  # Default
            
            # Check for pending strategy for new queries
            with self._strategy_lock:
                storage = self._get_process_storage()
                if storage.get('strategy_transition_pending') and storage.get('pending_strategy'):
                    effective_strategy = storage['pending_strategy']
                    _logger.info(f"Using pending strategy '{effective_strategy}' for new query {query_id}")
            
            query_info = QueryInfo(
                query_id=query_id,
                cursor_id=cursor_id,
                strategy=effective_strategy,
                state=QueryState.PREPARING,
                created_time=time.time(),
                last_activity_time=time.time(),
                connection_id=self._connection_id
            )
            
            self._active_queries[query_id] = query_info
            self._cursor_to_query[cursor_id] = query_id
            
            # Track in process storage
            with self._strategy_lock:
                storage = self._get_process_storage()
                storage['query_strategy_map'][query_id] = effective_strategy
                storage['connection_queries'][self._connection_id].add(query_id)
            
            _logger.info(f"Started query {query_id} with strategy '{effective_strategy}'")
            return query_id, effective_strategy
    
    def update_query_state(self, query_id: str, new_state: QueryState, 
                          engine_ip: Optional[str] = None) -> bool:
        """Update the state of a query."""
        with self._instance_lock:
            query_info = self._active_queries.get(query_id)
            if not query_info:
                _logger.warning(f"Attempted to update unknown query {query_id}")
                return False
            
            old_state = query_info.state
            query_info.state = new_state
            query_info.update_activity()
            
            if engine_ip:
                query_info.engine_ip = engine_ip
            
            _logger.debug(f"Query {query_id} state changed: {old_state} -> {new_state}")
            
            # Check if we can apply pending strategy changes
            if query_info.is_completed():
                self._cleanup_completed_query(query_id)
                self._check_strategy_transition()
            
            return True
    
    def get_query_strategy(self, query_id: str) -> Optional[str]:
        """Get the strategy for a specific query."""
        with self._instance_lock:
            query_info = self._active_queries.get(query_id)
            if query_info:
                query_info.update_activity()
                return query_info.strategy
            
            # Check process storage as fallback
            with self._strategy_lock:
                storage = self._get_process_storage()
                return storage['query_strategy_map'].get(query_id)
    
    def record_query_activity(self, query_id: str, activity_type: str = "fetch"):
        """Record activity for a query to prevent premature cleanup."""
        with self._instance_lock:
            query_info = self._active_queries.get(query_id)
            if query_info:
                query_info.update_activity()
                
                if activity_type == "fetch":
                    query_info.fetch_requests += 1
                elif activity_type == "metadata":
                    query_info.metadata_requests += 1
                
                _logger.debug(f"Recorded {activity_type} activity for query {query_id}")
    
    def complete_query(self, query_id: str, success: bool = True) -> bool:
        """Mark a query as completed."""
        new_state = QueryState.COMPLETED if success else QueryState.FAILED
        return self.update_query_state(query_id, new_state)
    
    def cancel_query(self, query_id: str) -> bool:
        """Mark a query as cancelled."""
        return self.update_query_state(query_id, QueryState.CANCELLED)
    
    def cleanup_cursor(self, cursor_id: str):
        """Clean up all queries associated with a cursor."""
        with self._instance_lock:
            query_id = self._cursor_to_query.get(cursor_id)
            if query_id:
                query_info = self._active_queries.get(query_id)
                if query_info and query_info.is_active():
                    # Mark as cancelled if still active
                    self.cancel_query(query_id)
                
                self._cleanup_completed_query(query_id)
            
            # Remove cursor reference
            if cursor_id in self._cursor_refs:
                del self._cursor_refs[cursor_id]
            
            _logger.debug(f"Cleaned up cursor {cursor_id}")
    
    def _cleanup_completed_query(self, query_id: str):
        """Clean up a completed query."""
        query_info = self._active_queries.pop(query_id, None)
        if not query_info:
            return
        
        # Remove from cursor mapping
        if query_info.cursor_id in self._cursor_to_query:
            if self._cursor_to_query[query_info.cursor_id] == query_id:
                del self._cursor_to_query[query_info.cursor_id]
        
        # Remove from process storage
        with self._strategy_lock:
            storage = self._get_process_storage()
            storage['query_strategy_map'].pop(query_id, None)
            
            if query_info.connection_id in storage['connection_queries']:
                storage['connection_queries'][query_info.connection_id].discard(query_id)
                if not storage['connection_queries'][query_info.connection_id]:
                    del storage['connection_queries'][query_info.connection_id]
        
        _logger.debug(f"Cleaned up completed query {query_id} (state: {query_info.state})")
    
    def _cleanup_cursor_ref(self, cursor_id: str):
        """Cleanup callback for weak cursor references."""
        self.cleanup_cursor(cursor_id)
    
    def _check_strategy_transition(self):
        """Check if pending strategy transition can be applied."""
        with self._strategy_lock:
            storage = self._get_process_storage()
            
            if not storage.get('strategy_transition_pending'):
                return
            
            # Count active queries across all connections
            active_count = 0
            for queries in storage['connection_queries'].values():
                for query_id in queries:
                    # Check if query is still active
                    query_info = None
                    for conn_queries in self._active_queries.values():
                        if isinstance(conn_queries, QueryInfo) and conn_queries.query_id == query_id:
                            query_info = conn_queries
                            break
                    
                    if query_info and query_info.is_active():
                        active_count += 1
            
            if active_count == 0:
                # No active queries, apply transition
                old_strategy = storage.get('active_strategy')
                new_strategy = storage.get('pending_strategy')
                
                storage['active_strategy'] = new_strategy
                storage['pending_strategy'] = None
                storage['strategy_transition_pending'] = False
                storage['last_transition_time'] = time.time()
                
                # Update instance cache
                self._active_strategy = new_strategy
                self._pending_strategy = None
                self._strategy_transition_pending = False
                
                _logger.info(f"Applied strategy transition: {old_strategy} -> {new_strategy}")
            else:
                _logger.debug(f"Cannot apply strategy transition yet, {active_count} queries still active")
    
    def handle_456_error(self, current_strategy: str) -> str:
        """
        Handle 456 error by switching to alternative strategy.
        
        Args:
            current_strategy: The strategy that failed with 456
            
        Returns:
            Alternative strategy to try
        """
        alternative = 'green' if current_strategy == 'blue' else 'blue'
        
        # Update active strategy since current one failed
        self.set_active_strategy(alternative)
        
        _logger.info(f"Handling 456 error: switching from {current_strategy} to {alternative}")
        return alternative
    
    def periodic_cleanup(self):
        """Perform periodic cleanup of stale queries."""
        current_time = time.time()
        
        # Only cleanup every 5 minutes
        if current_time - self._last_cleanup < self._cleanup_interval:
            return
        
        with self._instance_lock:
            stale_queries = []
            stale_timeout = 3600  # 1 hour
            
            for query_id, query_info in self._active_queries.items():
                if (current_time - query_info.last_activity_time > stale_timeout and
                    not query_info.is_completed()):
                    stale_queries.append(query_id)
            
            for query_id in stale_queries:
                _logger.warning(f"Cleaning up stale query {query_id}")
                self.cancel_query(query_id)
            
            self._last_cleanup = current_time
            
            if stale_queries:
                _logger.info(f"Cleaned up {len(stale_queries)} stale queries")
    
    def get_debug_info(self) -> Dict:
        """Get debug information about strategy management state."""
        with self._instance_lock:
            active_queries = [
                {
                    'query_id': q.query_id,
                    'strategy': q.strategy,
                    'state': q.state.value,
                    'age_seconds': time.time() - q.created_time,
                    'last_activity_seconds': time.time() - q.last_activity_time,
                    'fetch_requests': q.fetch_requests,
                    'metadata_requests': q.metadata_requests
                }
                for q in self._active_queries.values()
            ]
            
            with self._strategy_lock:
                storage = self._get_process_storage()
                
                return {
                    'connection_id': self._connection_id,
                    'active_strategy': self.get_active_strategy(),
                    'pending_strategy': storage.get('pending_strategy'),
                    'strategy_transition_pending': storage.get('strategy_transition_pending'),
                    'total_active_queries': len(self._active_queries),
                    'active_queries_by_state': {
                        state.value: sum(1 for q in self._active_queries.values() if q.state == state)
                        for state in QueryState
                    },
                    'tracked_cursors': len(self._cursor_refs),
                    'process_query_count': len(storage.get('query_strategy_map', {})),
                    'active_queries': active_queries,
                    'last_cleanup': self._last_cleanup
                }