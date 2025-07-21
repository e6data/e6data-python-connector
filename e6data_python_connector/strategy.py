"""
Strategy management module for blue-green deployment support.

This module provides centralized strategy management functionality that can be
imported by both the main e6data_grpc module and the cluster_manager module
without causing circular imports.
"""

import logging
import multiprocessing
import time
import threading

# Set up logging
_logger = logging.getLogger(__name__)

# Global variables for lazy initialization
_manager = None
_shared_strategy = None
_initialization_lock = threading.Lock()

# Thread-local fallback storage in case multiprocessing fails
_local_strategy_cache = {
    'active_strategy': None,
    'last_check_time': 0,
    'pending_strategy': None,
    'query_strategy_map': {},
    'last_transition_time': 0,
    'session_invalidated': False
}

# Cache timeout in seconds (5 minutes)
_STRATEGY_CACHE_TIMEOUT = 300


def _initialize_shared_state():
    """Initialize the shared state using multiprocessing Manager with lazy loading."""
    global _manager, _shared_strategy
    
    with _initialization_lock:
        if _shared_strategy is not None:
            return _shared_strategy
        
        try:
            # Try to create multiprocessing Manager
            _manager = multiprocessing.Manager()
            _shared_strategy = _manager.dict({
                'active_strategy': None,
                'last_check_time': 0,
                'pending_strategy': None,
                'query_strategy_map': _manager.dict(),
                'last_transition_time': 0,
                'session_invalidated': False
            })
            _logger.debug("Successfully initialized multiprocessing Manager for strategy sharing")
            return _shared_strategy
        except Exception as e:
            # Fall back to thread-local storage if Manager fails
            _logger.warning(f"Failed to initialize multiprocessing Manager: {e}. Using thread-local storage.")
            return _local_strategy_cache


def _get_shared_strategy():
    """Get the shared strategy state dictionary."""
    if _shared_strategy is None:
        return _initialize_shared_state()
    return _shared_strategy


def _get_active_strategy():
    """Get the currently active deployment strategy."""
    return _get_shared_strategy().get('active_strategy')


def _set_active_strategy(strategy):
    """Set the active deployment strategy."""
    shared_strategy = _get_shared_strategy()
    if strategy is None:
        shared_strategy['active_strategy'] = None
        return
    
    # Validate strategy
    normalized_strategy = strategy.lower()
    if normalized_strategy not in ['blue', 'green']:
        _logger.warning(f"Invalid strategy value: {strategy}. Must be 'blue' or 'green'.")
        return
    
    shared_strategy['active_strategy'] = normalized_strategy
    shared_strategy['last_check_time'] = time.time()
    _logger.info(f"Active deployment strategy set to: {normalized_strategy}")


def _set_pending_strategy(strategy):
    """Set the pending deployment strategy."""
    shared_strategy = _get_shared_strategy()
    if strategy is None:
        shared_strategy['pending_strategy'] = None
        return
    
    # Validate strategy
    normalized_strategy = strategy.lower()
    if normalized_strategy not in ['blue', 'green']:
        _logger.warning(f"Invalid pending strategy value: {strategy}. Must be 'blue' or 'green'.")
        return
    
    current_active = shared_strategy.get('active_strategy')
    if normalized_strategy != current_active:
        shared_strategy['pending_strategy'] = normalized_strategy
        _logger.info(f"Pending deployment strategy set to: {normalized_strategy}")


def _clear_strategy_cache():
    """Clear the strategy cache and reset state."""
    shared_strategy = _get_shared_strategy()
    shared_strategy['active_strategy'] = None
    shared_strategy['last_check_time'] = 0
    shared_strategy['pending_strategy'] = None
    if hasattr(shared_strategy.get('query_strategy_map'), 'clear'):
        shared_strategy['query_strategy_map'].clear()
    else:
        shared_strategy['query_strategy_map'] = {}
    shared_strategy['last_transition_time'] = 0
    shared_strategy['session_invalidated'] = False
    _logger.info("Strategy cache cleared")


def _register_query_strategy(query_id, strategy):
    """Register a query with its strategy."""
    if query_id and strategy:
        shared_strategy = _get_shared_strategy()
        query_map = shared_strategy.get('query_strategy_map', {})
        query_map[query_id] = strategy
        shared_strategy['query_strategy_map'] = query_map


def _get_query_strategy(query_id):
    """Get the strategy for a specific query."""
    shared_strategy = _get_shared_strategy()
    query_map = shared_strategy.get('query_strategy_map', {})
    return query_map.get(query_id)


def _unregister_query_strategy(query_id):
    """Unregister a query from the strategy map."""
    shared_strategy = _get_shared_strategy()
    query_map = shared_strategy.get('query_strategy_map', {})
    if query_id in query_map:
        del query_map[query_id]
        shared_strategy['query_strategy_map'] = query_map


def _apply_pending_strategy():
    """Apply pending strategy if no active queries are running."""
    shared_strategy = _get_shared_strategy()
    pending_strategy = shared_strategy.get('pending_strategy')
    active_strategy = shared_strategy.get('active_strategy')
    
    if pending_strategy and pending_strategy != active_strategy:
        query_map = shared_strategy.get('query_strategy_map', {})
        if len(query_map) == 0:
            # No active queries, safe to transition
            _logger.info(f"Last query completed, applying pending strategy: {pending_strategy}")
            shared_strategy['active_strategy'] = pending_strategy
            shared_strategy['pending_strategy'] = None
            shared_strategy['last_transition_time'] = time.time()
            shared_strategy['session_invalidated'] = True  # Invalidate all sessions
            _logger.info(f"Strategy transition completed: {active_strategy} -> {pending_strategy}")


def _is_strategy_cache_valid():
    """Check if the strategy cache is still valid."""
    shared_strategy = _get_shared_strategy()
    last_check = shared_strategy.get('last_check_time', 0)
    return (time.time() - last_check) < _STRATEGY_CACHE_TIMEOUT


def _get_grpc_header(engine_ip=None, cluster=None, strategy=None):
    """
    Generate gRPC metadata headers for the request.
    
    Args:
        engine_ip (str, optional): The IP address of the engine.
        cluster (str, optional): The UUID of the cluster.
        strategy (str, optional): The deployment strategy (blue/green).
    
    Returns:
        list: A list of tuples representing the gRPC metadata headers.
    """
    metadata = []
    if engine_ip:
        metadata.append(('plannerip', engine_ip))
    if cluster:
        metadata.append(('cluster-uuid', cluster))
    if strategy:
        # Normalize strategy to lowercase
        normalized_strategy = strategy.lower() if isinstance(strategy, str) else strategy
        if normalized_strategy in ['blue', 'green']:
            metadata.append(('strategy', normalized_strategy))
        else:
            _logger.warning(f"Invalid strategy value in header: {strategy}. Must be 'blue' or 'green'.")
    return metadata