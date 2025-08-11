from e6data_python_connector.e6data_grpc import Connection, Cursor

# Auto-enable optimizations on import (with error handling)
try:
    from e6data_python_connector.fast_deserializer import enable_fast_deserialization
    enable_fast_deserialization()
except Exception:
    # Silently fail if optimizations can't be enabled
    pass

__all__ = ['Connection', 'Cursor']
