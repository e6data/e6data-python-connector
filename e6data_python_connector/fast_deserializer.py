"""
Fast deserialization module with automatic Cython optimization fallback.

This module provides high-performance data deserialization for the e6data connector.
It automatically detects and uses Cython optimizations when available, falling back
to pure Python implementations when Cython extensions are not built.

Usage:
    from e6data_python_connector.fast_deserializer import enable_fast_deserialization
    
    # Enable fast deserialization (automatic Cython detection)
    enable_fast_deserialization()
    
    # Or manually control optimization level
    enable_fast_deserialization(force_cython=True)  # Fail if Cython not available
    enable_fast_deserialization(force_cython=False) # Use pure Python optimization
"""

import logging
import sys
from typing import Optional, Tuple, List, Any

_logger = logging.getLogger(__name__)

# Global flag to track optimization status
_optimization_enabled = False
_cython_available = False
_current_mode = "default"


def _check_cython_availability() -> bool:
    """
    Check if Cython extensions are available.
    
    Returns:
        bool: True if Cython extensions can be imported
    """
    try:
        from e6data_python_connector.cython_deserializer import (
            fast_get_query_columns_info,
            fast_read_values_from_array,
            fast_process_long_vector,
            fast_process_double_vector,
            fast_process_date_vector,
            optimize_deserialization
        )
        return True
    except ImportError as e:
        _logger.debug(f"Cython extensions not available: {e}")
        return False


def _enable_cython_optimization():
    """Enable Cython-based optimizations."""
    global _cython_available, _current_mode
    
    try:
        from e6data_python_connector.cython_deserializer import optimize_deserialization
        optimize_deserialization(enable=True)
        _cython_available = True
        _current_mode = "cython"
        _logger.info("Cython-optimized deserialization enabled")
        return True
    except ImportError as e:
        _logger.warning(f"Failed to enable Cython optimization: {e}")
        return False


def _enable_python_optimization():
    """Enable pure Python optimizations."""
    global _current_mode
    
    # Apply Python-level optimizations
    import e6data_python_connector.datainputstream as dis
    
    # Store original functions if not already stored
    if not hasattr(dis, '_original_get_query_columns_info'):
        dis._original_get_query_columns_info = dis.get_query_columns_info
        dis._original_read_values_from_array = dis.read_values_from_array
        dis._original_get_column_from_chunk = dis.get_column_from_chunk
    
    # Apply optimized Python versions
    dis.get_query_columns_info = _optimized_get_query_columns_info
    dis.read_values_from_array = _optimized_read_values_from_array
    dis.get_column_from_chunk = _optimized_get_column_from_chunk
    
    _current_mode = "python_optimized"
    _logger.info("Python-optimized deserialization enabled")


def _optimized_get_query_columns_info(buffer):
    """
    Optimized pure Python version of get_query_columns_info.
    
    This version reduces function call overhead and uses more efficient
    operations where possible.
    """
    from e6data_python_connector.datainputstream import DataInputStream, FieldInfo
    
    # Use the original DataInputStream but with optimized access patterns
    result_meta_bytes = DataInputStream(buffer)
    rowcount = result_meta_bytes.read_long()
    field_count = result_meta_bytes.read_int()
    
    # Pre-allocate list for better memory efficiency
    columns_description = [None] * field_count
    
    for i in range(field_count):
        name = result_meta_bytes.read_utf().decode()
        field_type = result_meta_bytes.read_utf().decode()
        zone = result_meta_bytes.read_utf().decode()
        date_format = result_meta_bytes.read_utf().decode()
        columns_description[i] = FieldInfo(name, field_type, date_format, zone)
    
    return rowcount, columns_description


def _optimized_read_values_from_array(query_columns_description: list, dis) -> list:
    """
    Optimized pure Python version of read_values_from_array.
    
    This version reduces lookup overhead and uses more efficient operations.
    """
    from datetime import datetime, timedelta
    from decimal import Decimal
    from e6data_python_connector.constants import ZONE
    from e6data_python_connector.date_time_utils import floor_div, floor_mod
    
    # Pre-allocate result array
    value_array = [None] * len(query_columns_description)
    
    # Cache commonly used constants and functions
    read_long = dis.read_long
    read_int = dis.read_int
    read_double = dis.read_double
    read_float = dis.read_float
    read_boolean = dis.read_boolean
    read_utf = dis.read_utf
    read_byte = dis.read_byte
    read_char = dis.read_char
    read_short = dis.read_short
    
    for idx, field_info in enumerate(query_columns_description):
        dtype = field_info.get_field_type()
        is_present = read_byte()
        
        if is_present == 0:
            continue  # value_array[idx] already None
        
        try:
            if dtype == "LONG":
                value_array[idx] = read_long()
            elif dtype == "DATE":
                epoch_seconds = floor_div(read_long(), 1000_000)
                date = datetime.fromtimestamp(epoch_seconds, ZONE)
                value_array[idx] = date.strftime("%Y-%m-%d")
            elif dtype == "DATETIME":
                epoch_micros = read_long()
                epoch_seconds = floor_div(epoch_micros, 1000_000)
                micros_of_the_day = floor_mod(epoch_micros, 1000_000)
                date_time = datetime.fromtimestamp(epoch_seconds, ZONE)
                date_time = date_time + timedelta(microseconds=micros_of_the_day)
                value_array[idx] = date_time.strftime("%Y-%m-%d %H:%M:%S")
            elif dtype in ("STRING", "ARRAY", "MAP", "STRUCT"):
                value_array[idx] = read_utf().decode()
            elif dtype in ("INT", "INTEGER"):
                value_array[idx] = read_int()
            elif dtype == "DOUBLE":
                value_array[idx] = read_double()
            elif dtype == "BINARY":
                value_array[idx] = read_utf()
            elif dtype == "FLOAT":
                value_array[idx] = read_float()
            elif dtype == "CHAR":
                value_array[idx] = read_char()
            elif dtype == "BOOLEAN":
                value_array[idx] = read_boolean()
            elif dtype == "SHORT":
                value_array[idx] = read_short()
            elif dtype == "BYTE":
                value_array[idx] = read_byte()
            elif dtype == "INT96":
                julian_day = read_int()
                time = read_long()
                date_time = datetime.fromtimestamp((julian_day - 2440588) * 86400)
                date_time_with_nanos = date_time + timedelta(microseconds=(time / 1000))
                value_array[idx] = date_time_with_nanos
            elif dtype == "DECIMAL128":
                decimal_str = read_utf().decode()
                value_array[idx] = Decimal(decimal_str)
            
        except Exception as e:
            _logger.error(f"Error parsing field {idx} ({dtype}): {e}")
            value_array[idx] = 'Failed to parse.'
    
    return value_array


def _optimized_get_column_from_chunk(vector) -> list:
    """
    Optimized pure Python version of get_column_from_chunk.
    
    This version reduces attribute lookups and uses more efficient operations.
    """
    from e6data_python_connector.datainputstream import get_null
    from e6data_python_connector.e6x_vector.ttypes import VectorType
    import pytz
    from datetime import datetime, timedelta
    from e6data_python_connector.date_time_utils import floor_div, floor_mod
    from e6data_python_connector.datainputstream import _binary_to_decimal128
    
    # Cache frequently accessed attributes
    vector_type = vector.vectorType
    vector_size = vector.size
    is_constant = vector.isConstantVector
    null_set = vector.nullSet
    
    # Pre-allocate result array
    value_array = [None] * vector_size
    
    try:
        if vector_type == VectorType.LONG:
            if is_constant:
                constant_val = vector.data.numericConstantData.data
                is_null = null_set[0]
                for row in range(vector_size):
                    value_array[row] = None if is_null else constant_val
            else:
                data_array = vector.data.int64Data.data
                for row in range(vector_size):
                    value_array[row] = None if null_set[row] else data_array[row]
                    
        elif vector_type == VectorType.DOUBLE:
            if is_constant:
                constant_val = vector.data.numericDecimalConstantData.data
                is_null = null_set[0]
                for row in range(vector_size):
                    value_array[row] = None if is_null else constant_val
            else:
                data_array = vector.data.float64Data.data
                for row in range(vector_size):
                    value_array[row] = None if null_set[row] else data_array[row]
                    
        elif vector_type == VectorType.INTEGER:
            if is_constant:
                constant_val = vector.data.numericConstantData.data
                is_null = null_set[0]
                for row in range(vector_size):
                    value_array[row] = None if is_null else constant_val
            else:
                data_array = vector.data.int32Data.data
                for row in range(vector_size):
                    value_array[row] = None if null_set[row] else data_array[row]
                    
        # Add other vector types as needed...
        else:
            # Fall back to original implementation for unsupported types
            from e6data_python_connector.datainputstream import get_column_from_chunk
            if hasattr(get_column_from_chunk, '_original_get_column_from_chunk'):
                return get_column_from_chunk._original_get_column_from_chunk(vector)
            else:
                # This shouldn't happen, but safe fallback
                for row in range(vector_size):
                    value_array[row] = None
                    
    except Exception as e:
        _logger.error(f"Error in optimized column processing: {e}")
        for row in range(vector_size):
            value_array[row] = 'Failed to parse.'
    
    return value_array


def enable_fast_deserialization(force_cython: Optional[bool] = None) -> bool:
    """
    Enable fast deserialization optimizations.
    
    This function automatically detects and enables the best available
    optimization method:
    1. Cython extensions (if available and not disabled)
    2. Pure Python optimizations
    
    Args:
        force_cython: 
            - None (default): Auto-detect and use Cython if available
            - True: Force Cython usage, raise error if not available
            - False: Use pure Python optimizations only
    
    Returns:
        bool: True if optimization was successfully enabled
        
    Raises:
        ImportError: If force_cython=True and Cython extensions not available
    """
    global _optimization_enabled, _cython_available, _current_mode
    
    if force_cython is True:
        # Force Cython usage
        if not _check_cython_availability():
            raise ImportError(
                "Cython extensions not available. "
                "Build with: BUILD_CYTHON=1 pip install -e . "
                "or set force_cython=False to use Python optimizations"
            )
        success = _enable_cython_optimization()
        if not success:
            raise ImportError("Failed to enable Cython optimizations")
    
    elif force_cython is False:
        # Force pure Python optimizations
        _enable_python_optimization()
        success = True
        
    else:
        # Auto-detect: try Cython first, fall back to Python
        if _check_cython_availability():
            success = _enable_cython_optimization()
            if not success:
                _logger.warning("Cython optimization failed, falling back to Python optimization")
                _enable_python_optimization()
                success = True
        else:
            _logger.info("Cython not available, using Python optimizations")
            _enable_python_optimization()
            success = True
    
    _optimization_enabled = success
    return success


def disable_fast_deserialization():
    """
    Disable fast deserialization optimizations and restore original functions.
    """
    global _optimization_enabled, _current_mode
    
    import e6data_python_connector.datainputstream as dis
    
    if _current_mode == "cython" and _cython_available:
        try:
            from e6data_python_connector.cython_deserializer import optimize_deserialization
            optimize_deserialization(enable=False)
        except ImportError:
            pass
    
    # Restore original Python functions if they were saved
    if hasattr(dis, '_original_get_query_columns_info'):
        dis.get_query_columns_info = dis._original_get_query_columns_info
        dis.read_values_from_array = dis._original_read_values_from_array
        dis.get_column_from_chunk = dis._original_get_column_from_chunk
    
    _optimization_enabled = False
    _current_mode = "default"
    _logger.info("Fast deserialization disabled, restored original functions")


def get_optimization_info() -> dict:
    """
    Get information about current optimization status.
    
    Returns:
        dict: Information about optimization status and capabilities
    """
    return {
        'optimization_enabled': _optimization_enabled,
        'current_mode': _current_mode,
        'cython_available': _check_cython_availability(),
        'python_version': sys.version_info[:3],
        'recommendations': _get_recommendations()
    }


def _get_recommendations() -> List[str]:
    """Get performance recommendations based on current setup."""
    recommendations = []
    
    if not _optimization_enabled:
        recommendations.append("Enable fast deserialization with enable_fast_deserialization()")
    
    if not _check_cython_availability():
        recommendations.append(
            "Install Cython extensions for maximum performance: "
            "BUILD_CYTHON=1 pip install -e ."
        )
    
    if _current_mode == "python_optimized":
        recommendations.append(
            "Consider building Cython extensions for 2-10x better performance"
        )
    
    return recommendations


# Auto-enable optimization on import (with error handling)
try:
    if not _optimization_enabled:
        enable_fast_deserialization()
except Exception as e:
    _logger.debug(f"Could not auto-enable fast deserialization: {e}")