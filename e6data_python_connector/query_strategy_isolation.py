"""
Query-specific strategy isolation to prevent mid-query strategy changes from causing failures.

This module provides robust query lifecycle management that ensures each query maintains
its original strategy throughout its entire execution, even if the global strategy changes.
"""

import logging
import threading
import time
import weakref
from typing import Dict, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum

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


class QueryStrategyIsolationManager:
    """
    Manages query-specific strategy isolation to prevent mid-query failures.
    
    This manager ensures that:
    1. Each query maintains its original strategy throughout execution
    2. Strategy changes are deferred until all queries complete
    3. New queries use the pending strategy
    4. Proper cleanup of completed queries
    """
    
    def __init__(self):
        self._lock = threading.RLock()
        self._active_queries: Dict[str, QueryInfo] = {}
        self._cursor_to_query: Dict[str, str] = {}
        self._connection_queries: Dict[str, Set[str]] = {}
        self._strategy_transition_pending = False
        self._pending_strategy = None
        self._current_strategy = None
        self._query_counter = 0
        
        # Cleanup thread
        self._cleanup_interval = 300  # 5 minutes
        self._last_cleanup = time.time()
        
        # Weak references to cursors for cleanup
        self._cursor_refs: Dict[str, weakref.ref] = {}
    
    def register_cursor(self, cursor, connection_id: Optional[str] = None) -> str:
        """
        Register a cursor for query tracking.
        
        Args:
            cursor: The cursor object
            connection_id: Optional connection identifier
            
        Returns:
            cursor_id: Unique identifier for the cursor
        """
        with self._lock:
            cursor_id = f"cursor_{id(cursor)}_{int(time.time() * 1000)}"
            
            # Store weak reference to cursor
            self._cursor_refs[cursor_id] = weakref.ref(cursor, 
                lambda ref: self._cleanup_cursor_ref(cursor_id))
            
            # Track connection association
            if connection_id:
                if connection_id not in self._connection_queries:
                    self._connection_queries[connection_id] = set()
            
            _logger.debug(f"Registered cursor {cursor_id} for connection {connection_id}")
            return cursor_id
    
    def start_query(self, cursor_id: str, strategy: str, 
                   connection_id: Optional[str] = None) -> Tuple[str, str]:
        """
        Start a new query with strategy isolation.
        
        Args:
            cursor_id: Cursor identifier
            strategy: Strategy to use for this query
            connection_id: Connection identifier
            
        Returns:
            Tuple of (query_id, effective_strategy)
        """
        with self._lock:
            self._query_counter += 1
            query_id = f"query_{cursor_id}_{self._query_counter}_{int(time.time() * 1000)}"
            
            # Determine effective strategy
            effective_strategy = strategy
            if self._strategy_transition_pending and self._pending_strategy:
                # Use pending strategy for new queries
                effective_strategy = self._pending_strategy
                _logger.info(f"Using pending strategy '{effective_strategy}' for new query {query_id}")
            
            query_info = QueryInfo(
                query_id=query_id,
                cursor_id=cursor_id,
                strategy=effective_strategy,
                state=QueryState.PREPARING,
                created_time=time.time(),
                last_activity_time=time.time(),
                connection_id=connection_id
            )
            
            self._active_queries[query_id] = query_info
            self._cursor_to_query[cursor_id] = query_id
            
            # Associate with connection
            if connection_id:
                if connection_id not in self._connection_queries:
                    self._connection_queries[connection_id] = set()
                self._connection_queries[connection_id].add(query_id)
            
            _logger.info(f"Started query {query_id} with strategy '{effective_strategy}' in state {query_info.state}")
            return query_id, effective_strategy
    
    def update_query_state(self, query_id: str, new_state: QueryState, 
                          engine_ip: Optional[str] = None) -> bool:
        """
        Update the state of a query.
        
        Args:
            query_id: Query identifier
            new_state: New state for the query
            engine_ip: Engine IP if available
            
        Returns:
            True if update was successful
        """
        with self._lock:
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
        """
        Get the strategy for a specific query.
        
        Args:
            query_id: Query identifier
            
        Returns:
            Strategy string or None if query not found
        """
        with self._lock:
            query_info = self._active_queries.get(query_id)
            if query_info:
                query_info.update_activity()
                return query_info.strategy
            return None
    
    def get_cursor_query_strategy(self, cursor_id: str) -> Optional[str]:
        """
        Get the strategy for the query associated with a cursor.
        
        Args:
            cursor_id: Cursor identifier
            
        Returns:
            Strategy string or None if not found
        """
        with self._lock:
            query_id = self._cursor_to_query.get(cursor_id)
            if query_id:
                return self.get_query_strategy(query_id)
            return None
    
    def record_query_activity(self, query_id: str, activity_type: str = "fetch"):
        """
        Record activity for a query to prevent premature cleanup.
        
        Args:
            query_id: Query identifier
            activity_type: Type of activity (fetch, metadata, etc.)
        """
        with self._lock:
            query_info = self._active_queries.get(query_id)
            if query_info:
                query_info.update_activity()
                
                if activity_type == "fetch":
                    query_info.fetch_requests += 1
                elif activity_type == "metadata":
                    query_info.metadata_requests += 1
                
                _logger.debug(f"Recorded {activity_type} activity for query {query_id}")
    
    def set_strategy_transition(self, new_strategy: str) -> bool:
        """
        Set a pending strategy transition.
        
        Args:
            new_strategy: The new strategy to transition to
            
        Returns:
            True if transition was set, False if already in progress
        """
        with self._lock:
            if self._strategy_transition_pending:
                _logger.warning(f"Strategy transition already pending to {self._pending_strategy}")
                return False
            
            if new_strategy == self._current_strategy:
                _logger.debug(f"New strategy {new_strategy} is same as current, no transition needed")
                return False
            
            self._strategy_transition_pending = True
            self._pending_strategy = new_strategy
            
            _logger.info(f"Set pending strategy transition: {self._current_strategy} -> {new_strategy}")
            
            # Check if we can apply immediately
            self._check_strategy_transition()
            return True
    
    def _check_strategy_transition(self):
        """Check if pending strategy transition can be applied."""
        if not self._strategy_transition_pending:
            return
        
        # Count active queries
        active_count = sum(1 for q in self._active_queries.values() if q.is_active())
        
        if active_count == 0:
            # No active queries, apply transition
            old_strategy = self._current_strategy
            self._current_strategy = self._pending_strategy
            self._pending_strategy = None
            self._strategy_transition_pending = False
            
            _logger.info(f"Applied strategy transition: {old_strategy} -> {self._current_strategy}")
            
            # Trigger session invalidation for all connections
            self._invalidate_all_sessions()
        else:
            _logger.debug(f"Cannot apply strategy transition yet, {active_count} queries still active")
    
    def _invalidate_all_sessions(self):
        """Invalidate all sessions to force fresh connections with new strategy."""
        # This would integrate with the session manager
        _logger.info("Strategy transition complete - all sessions should be invalidated")
    
    def complete_query(self, query_id: str, success: bool = True) -> bool:
        """
        Mark a query as completed.
        
        Args:
            query_id: Query identifier
            success: Whether the query completed successfully
            
        Returns:
            True if query was found and marked complete
        """
        new_state = QueryState.COMPLETED if success else QueryState.FAILED
        return self.update_query_state(query_id, new_state)
    
    def cancel_query(self, query_id: str) -> bool:
        """
        Mark a query as cancelled.
        
        Args:
            query_id: Query identifier
            
        Returns:
            True if query was found and marked cancelled
        """
        return self.update_query_state(query_id, QueryState.CANCELLED)
    
    def cleanup_cursor(self, cursor_id: str):
        """
        Clean up all queries associated with a cursor.
        
        Args:
            cursor_id: Cursor identifier
        """
        with self._lock:
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
        
        # Remove from connection mapping
        if query_info.connection_id:
            connection_queries = self._connection_queries.get(query_info.connection_id)
            if connection_queries:
                connection_queries.discard(query_id)
                if not connection_queries:
                    del self._connection_queries[query_info.connection_id]
        
        _logger.debug(f"Cleaned up completed query {query_id} (state: {query_info.state})")
    
    def _cleanup_cursor_ref(self, cursor_id: str):
        """Cleanup callback for weak cursor references."""
        self.cleanup_cursor(cursor_id)
    
    def periodic_cleanup(self):
        """Perform periodic cleanup of stale queries."""
        current_time = time.time()
        
        # Only cleanup every 5 minutes
        if current_time - self._last_cleanup < self._cleanup_interval:
            return
        
        with self._lock:
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
        """Get debug information about query management state."""
        with self._lock:
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
            
            return {
                'total_active_queries': len(self._active_queries),
                'active_queries_by_state': {
                    state.value: sum(1 for q in self._active_queries.values() if q.state == state)
                    for state in QueryState
                },
                'strategy_transition_pending': self._strategy_transition_pending,
                'current_strategy': self._current_strategy,
                'pending_strategy': self._pending_strategy,
                'tracked_cursors': len(self._cursor_refs),
                'tracked_connections': len(self._connection_queries),
                'active_queries': active_queries,
                'last_cleanup': self._last_cleanup
            }


# Global instance
_query_isolation_manager = QueryStrategyIsolationManager()


def get_query_isolation_manager() -> QueryStrategyIsolationManager:
    """Get the global query strategy isolation manager."""
    return _query_isolation_manager