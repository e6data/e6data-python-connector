from e6data_python_connector.e6data_grpc import Connection, Cursor
from e6data_python_connector.connection_pool import ConnectionPool

# Auto-enable optimizations if available
try:
    from e6data_python_connector.fast_deserializer import get_optimization_info
    import logging
    _logger = logging.getLogger(__name__)
    
    # Initialize optimizations silently
    info = get_optimization_info()
    if info['current_mode'] != 'default':
        _logger.debug(f"e6data optimizations enabled: {info['current_mode']}")
except Exception:
    # Silently continue if optimizations fail
    pass

__all__ = ['Connection', 'Cursor', 'ConnectionPool']
