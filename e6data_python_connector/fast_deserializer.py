"""
Fast data deserialization module for e6data Python connector.
Provides automatic optimization detection and fallback mechanisms.
"""

import logging
import os
import json
from typing import Dict, Any, List, Optional

_logger = logging.getLogger(__name__)

# Global optimization state
_optimization_enabled = True
_current_mode = "default"
_cython_available = False
_force_mode = None  # Can be 'cython', 'python', 'default', or None for auto

def _detect_cython():
    """Detect if Cython extensions are available."""
    global _cython_available, _force_mode
    
    # Check if Cython is disabled via environment variable
    if os.environ.get('E6DATA_DISABLE_CYTHON', '').lower() in ('1', 'true', 'yes'):
        _logger.info("Cython disabled via E6DATA_DISABLE_CYTHON environment variable")
        _cython_available = False
        return False
    
    # Check for forced mode via environment variable
    env_force_mode = os.environ.get('E6DATA_FORCE_MODE', '').lower()
    if env_force_mode in ('cython', 'python', 'default'):
        _force_mode = env_force_mode
        _logger.info(f"Force mode set via E6DATA_FORCE_MODE: {env_force_mode}")
    
    try:
        from e6data_python_connector import cython_deserializer
        _cython_available = True
        _logger.debug("Cython extensions detected and loaded")
        return True
    except ImportError as e:
        _cython_available = False
        _logger.debug(f"Cython extensions not available: {e}")
        return False

def _python_optimized_get_column_from_chunk(vector):
    """
    Python-optimized version of get_column_from_chunk.
    Uses optimizations like pre-allocated lists and reduced function calls.
    """
    size = vector.size
    d_type = vector.vectorType
    zone = getattr(_python_optimized_get_column_from_chunk, '_cached_zone', None)
    if zone is None:
        import pytz
        zone = pytz.UTC
        _python_optimized_get_column_from_chunk._cached_zone = zone
    
    # Pre-allocate result array for better performance
    value_array = [None] * size
    
    # Import helper functions once
    from e6data_python_connector.date_time_utils import floor_div, floor_mod
    from e6data_python_connector.e6x_vector.ttypes import VectorType
    from datetime import datetime, timedelta
    
    # Get null checking function reference (matches original implementation)
    def get_null_check(vector, row):
        if hasattr(vector, 'nullSet') and vector.nullSet:
            if vector.isConstantVector:
                return vector.nullSet[0] if len(vector.nullSet) > 0 else False
            else:
                return vector.nullSet[row] if row < len(vector.nullSet) else False
        return False
    
    # Process based on data type with optimized loops
    if d_type == VectorType.LONG:
        if vector.isConstantVector:
            constant_value = vector.data.numericConstantData.data
            for row in range(size):
                value_array[row] = None if get_null_check(vector, row) else constant_value
        else:
            data = vector.data.int64Data.data
            for row in range(size):
                value_array[row] = None if get_null_check(vector, row) else data[row]
                
    elif d_type == VectorType.DATE:
        if vector.isConstantVector:
            constant_epoch = vector.data.dateConstantData.data
            constant_seconds = floor_div(constant_epoch, 1000_000)
            constant_date = datetime.fromtimestamp(constant_seconds, zone)
            constant_str = constant_date.strftime("%Y-%m-%d")
            for row in range(size):
                value_array[row] = None if get_null_check(vector, row) else constant_str
        else:
            data = vector.data.dateData.data
            for row in range(size):
                if get_null_check(vector, row):
                    value_array[row] = None
                else:
                    epoch_seconds = floor_div(data[row], 1000_000)
                    date = datetime.fromtimestamp(epoch_seconds, zone)
                    value_array[row] = date.strftime("%Y-%m-%d")
                    
    elif d_type == VectorType.DATETIME:
        if vector.isConstantVector:
            constant_micros = vector.data.timeConstantData.data
            constant_seconds = floor_div(constant_micros, 1000_000)
            micros_remainder = floor_mod(constant_micros, 1000_000)
            constant_dt = datetime.fromtimestamp(constant_seconds, zone)
            constant_dt = constant_dt + timedelta(microseconds=micros_remainder)
            constant_str = constant_dt.isoformat(timespec='milliseconds')
            for row in range(size):
                value_array[row] = None if get_null_check(vector, row) else constant_str
        else:
            data = vector.data.timeData.data
            for row in range(size):
                if get_null_check(vector, row):
                    value_array[row] = None
                else:
                    epoch_micros = data[row]
                    epoch_seconds = floor_div(epoch_micros, 1000_000)
                    micros_remainder = floor_mod(epoch_micros, 1000_000)
                    dt = datetime.fromtimestamp(epoch_seconds, zone)
                    dt = dt + timedelta(microseconds=micros_remainder)
                    value_array[row] = dt.isoformat(timespec='milliseconds')
                    
    elif d_type in (VectorType.STRING, VectorType.ARRAY, VectorType.MAP, VectorType.STRUCT):
        if vector.isConstantVector:
            constant_value = vector.data.varcharConstantData.data
            for row in range(size):
                value_array[row] = None if get_null_check(vector, row) else constant_value
        else:
            data = vector.data.varcharData.data
            for row in range(size):
                value_array[row] = None if get_null_check(vector, row) else data[row]
                
    elif d_type == VectorType.DOUBLE:
        if vector.isConstantVector:
            constant_value = vector.data.numericDecimalConstantData.data
            for row in range(size):
                value_array[row] = None if get_null_check(vector, row) else constant_value
        else:
            data = vector.data.float64Data.data
            for row in range(size):
                value_array[row] = None if get_null_check(vector, row) else data[row]
                
    elif d_type == VectorType.FLOAT:
        if vector.isConstantVector:
            constant_value = vector.data.numericDecimalConstantData.data
            for row in range(size):
                value_array[row] = None if get_null_check(vector, row) else constant_value
        else:
            data = vector.data.float32Data.data
            for row in range(size):
                value_array[row] = None if get_null_check(vector, row) else data[row]
                
    elif d_type == VectorType.BOOLEAN:
        if vector.isConstantVector:
            constant_value = vector.data.boolConstantData.data
            for row in range(size):
                value_array[row] = None if get_null_check(vector, row) else constant_value
        else:
            data = vector.data.boolData.data
            for row in range(size):
                value_array[row] = None if get_null_check(vector, row) else data[row]
                
    elif d_type == VectorType.INTEGER:
        if vector.isConstantVector:
            constant_value = vector.data.numericConstantData.data
            for row in range(size):
                value_array[row] = None if get_null_check(vector, row) else constant_value
        else:
            data = vector.data.int32Data.data
            for row in range(size):
                value_array[row] = None if get_null_check(vector, row) else data[row]
                
    elif d_type == VectorType.DECIMAL:
        from e6data_python_connector.datainputstream import _binary_to_decimal128
        if vector.isConstantVector:
            try:
                constant_value = _binary_to_decimal128(vector.data.decimalConstantData.data)
            except:
                constant_value = None
            for row in range(size):
                value_array[row] = None if get_null_check(vector, row) else constant_value
        else:
            data = vector.data.decimalData.data
            for row in range(size):
                if get_null_check(vector, row):
                    value_array[row] = None
                else:
                    try:
                        value_array[row] = _binary_to_decimal128(data[row])
                    except:
                        value_array[row] = None
                        
    elif d_type == VectorType.BINARY:
        if vector.isConstantVector:
            constant_value = vector.data.varcharConstantData.data
            for row in range(size):
                value_array[row] = None if get_null_check(vector, row) else constant_value
        else:
            data = vector.data.varcharData.data
            for row in range(size):
                value_array[row] = None if get_null_check(vector, row) else data[row]
    
    else:
        # Unknown type fallback
        for row in range(size):
            value_array[row] = None
    
    return value_array

def _python_optimized_process_chunk(buffer, query_columns_description):
    """
    Python-optimized version of chunk processing.
    """
    from thrift.transport import TTransport
    from thrift.protocol import TBinaryProtocol
    from e6data_python_connector.e6x_vector.ttypes import Chunk
    
    # Deserialize chunk
    transport = TTransport.TMemoryBuffer(buffer)
    protocol = TBinaryProtocol.TBinaryProtocolAccelerated(transport)
    
    chunk = Chunk()
    chunk.read(protocol)
    
    if chunk.size <= 0:
        return None
    
    # Pre-process all columns
    columns = []
    for col_index, col_name in enumerate(query_columns_description):
        column_data = _python_optimized_get_column_from_chunk(chunk.vectors[col_index])
        columns.append(column_data)
    
    # Build rows efficiently
    rows = []
    chunk_size = chunk.size
    num_columns = len(query_columns_description)
    
    for row_index in range(chunk_size):
        # Pre-allocate row
        row = [None] * num_columns
        for col_index in range(num_columns):
            row[col_index] = columns[col_index][row_index]
        rows.append(row)
    
    return rows

def get_optimized_column_processor():
    """
    Get the best available column processing function.
    
    Returns:
        function: The fastest available column processor
    """
    global _current_mode, _cython_available, _force_mode
    
    # Check for forced mode
    if _force_mode == 'default' or not _optimization_enabled:
        # Import original function for fallback
        from e6data_python_connector.datainputstream import get_column_from_chunk
        _current_mode = "default"
        return get_column_from_chunk
    
    if _force_mode == 'python':
        _current_mode = "python_optimized"
        _logger.debug("Using forced Python-optimized column processor")
        return _python_optimized_get_column_from_chunk
    
    if _force_mode == 'cython':
        if _cython_available:
            try:
                from e6data_python_connector.cython_deserializer import fast_get_column_from_chunk
                _current_mode = "cython"
                _logger.debug("Using forced Cython-optimized column processor")
                return fast_get_column_from_chunk
            except Exception as e:
                _logger.error(f"Forced Cython mode failed: {e}")
                raise
        else:
            raise ImportError("Cython forced but not available")
    
    # Auto mode: Try Cython first
    if _cython_available:
        try:
            from e6data_python_connector.cython_deserializer import fast_get_column_from_chunk
            _current_mode = "cython"
            _logger.debug("Using Cython-optimized column processor")
            return fast_get_column_from_chunk
        except Exception as e:
            _logger.warning(f"Cython processor failed, falling back: {e}")
    
    # Fall back to Python optimized
    _current_mode = "python_optimized"
    _logger.debug("Using Python-optimized column processor")
    return _python_optimized_get_column_from_chunk

def get_optimized_chunk_processor():
    """
    Get the best available chunk processing function.
    
    Returns:
        function: The fastest available chunk processor
    """
    global _current_mode, _cython_available, _force_mode
    
    # Check for forced mode
    if _force_mode == 'default' or not _optimization_enabled:
        # Import original function for fallback
        from e6data_python_connector.datainputstream import get_query_columns_info
        _current_mode = "default"
        return get_query_columns_info
    
    if _force_mode == 'python':
        _current_mode = "python_optimized"
        _logger.debug("Using forced Python-optimized chunk processor")
        return _python_optimized_process_chunk
    
    if _force_mode == 'cython':
        if _cython_available:
            try:
                from e6data_python_connector.cython_deserializer import fast_process_chunk
                _current_mode = "cython"
                _logger.debug("Using forced Cython-optimized chunk processor")
                return fast_process_chunk
            except Exception as e:
                _logger.error(f"Forced Cython mode failed: {e}")
                raise
        else:
            raise ImportError("Cython forced but not available")
    
    # Auto mode: Try Cython first
    if _cython_available:
        try:
            from e6data_python_connector.cython_deserializer import fast_process_chunk
            _current_mode = "cython"
            _logger.debug("Using Cython-optimized chunk processor")
            return fast_process_chunk
        except Exception as e:
            _logger.warning(f"Cython processor failed, falling back: {e}")
    
    # Fall back to Python optimized
    _current_mode = "python_optimized"
    _logger.debug("Using Python-optimized chunk processor")
    return _python_optimized_process_chunk

def enable_fast_deserialization(force_cython: bool = None):
    """
    Enable fast deserialization optimizations.
    
    Args:
        force_cython: If True, force Cython mode (raises error if unavailable).
                     If False, force Python optimized mode.
                     If None, auto-detect best available.
    """
    global _optimization_enabled, _current_mode, _cython_available
    
    _optimization_enabled = True
    
    if force_cython is True:
        if not _cython_available:
            raise ImportError("Cython extensions not available. Install with: BUILD_CYTHON=1 pip install -e .")
        _current_mode = "cython"
        _logger.info("Forced Cython optimization mode")
        
    elif force_cython is False:
        _current_mode = "python_optimized"
        _logger.info("Forced Python optimized mode")
        
    else:
        # Auto-detect best mode
        if _cython_available:
            _current_mode = "cython"
            _logger.info("Auto-selected Cython optimization mode")
        else:
            _current_mode = "python_optimized"
            _logger.info("Auto-selected Python optimized mode")

def disable_fast_deserialization():
    """Disable all optimizations and use original implementation."""
    global _optimization_enabled, _current_mode
    _optimization_enabled = False
    _current_mode = "default"
    _logger.info("Disabled all optimizations")

def set_optimization_mode(mode: str):
    """
    Set the optimization mode directly.
    
    Args:
        mode: One of 'auto', 'cython', 'python', or 'default'
    """
    global _force_mode, _optimization_enabled
    
    valid_modes = ['auto', 'cython', 'python', 'default']
    if mode not in valid_modes:
        raise ValueError(f"Invalid mode '{mode}'. Must be one of: {valid_modes}")
    
    if mode == 'auto':
        _force_mode = None
        _optimization_enabled = True
        _logger.info("Set to auto-detection mode")
    elif mode == 'default':
        _force_mode = 'default'
        _optimization_enabled = False
        _logger.info("Set to default (unoptimized) mode")
    else:
        _force_mode = mode
        _optimization_enabled = True
        _logger.info(f"Forced to {mode} optimization mode")
    
    # Re-patch datainputstream with new settings
    patch_datainputstream()

def get_available_modes() -> List[str]:
    """
    Get list of available optimization modes.
    
    Returns:
        list: Available modes based on system capabilities
    """
    modes = ['default', 'python']
    
    if _cython_available:
        modes.append('cython')
    
    modes.append('auto')
    return modes

def get_optimization_info() -> Dict[str, Any]:
    """
    Get information about current optimization status.
    
    Returns:
        dict: Optimization status and recommendations
    """
    info = {
        'optimization_enabled': _optimization_enabled,
        'current_mode': _current_mode,
        'cython_available': _cython_available,
        'force_mode': _force_mode,
        'available_modes': get_available_modes(),
        'recommendations': [],
        'environment_variables': {
            'E6DATA_DISABLE_CYTHON': os.environ.get('E6DATA_DISABLE_CYTHON', 'not set'),
            'E6DATA_FORCE_MODE': os.environ.get('E6DATA_FORCE_MODE', 'not set')
        }
    }
    
    if not _cython_available:
        info['recommendations'].append(
            "Install Cython for better performance: pip install cython numpy && BUILD_CYTHON=1 pip install -e ."
        )
    
    if not _optimization_enabled:
        info['recommendations'].append(
            "Enable optimizations: enable_fast_deserialization()"
        )
    
    if _current_mode == "default":
        info['recommendations'].append(
            "Consider enabling optimizations for better performance"
        )
    
    return info

def patch_datainputstream():
    """
    Monkey-patch datainputstream to use optimized functions.
    This is called automatically when optimizations are enabled.
    """
    try:
        import e6data_python_connector.datainputstream as dis
        
        # Store original functions for fallback
        if not hasattr(dis, '_original_get_column_from_chunk'):
            dis._original_get_column_from_chunk = dis.get_column_from_chunk
            dis._original_get_query_columns_info = dis.get_query_columns_info
        
        # Replace with optimized versions
        if _optimization_enabled:
            dis.get_column_from_chunk = get_optimized_column_processor()
            dis.get_query_columns_info = get_optimized_chunk_processor()
            _logger.debug(f"Patched datainputstream with {_current_mode} optimizations")
        else:
            # Restore originals
            dis.get_column_from_chunk = dis._original_get_column_from_chunk
            dis.get_query_columns_info = dis._original_get_query_columns_info
            _logger.debug("Restored original datainputstream functions")
            
    except Exception as e:
        _logger.error(f"Failed to patch datainputstream: {e}")

def _load_config_file() -> Dict[str, Any]:
    """
    Load optimization configuration from file.
    
    Looks for .e6data_config.json in current directory or user home.
    
    Returns:
        dict: Configuration settings
    """
    config_files = [
        '.e6data_config.json',  # Current directory
        os.path.expanduser('~/.e6data_config.json')  # User home
    ]
    
    for config_file in config_files:
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                _logger.debug(f"Loaded configuration from {config_file}")
                return config.get('optimization', {})
            except Exception as e:
                _logger.warning(f"Failed to load config from {config_file}: {e}")
    
    return {}

def save_config_file(optimization_config: Dict[str, Any]) -> bool:
    """
    Save optimization configuration to file.
    
    Args:
        optimization_config: Configuration settings to save
        
    Returns:
        bool: True if saved successfully
    """
    config_file = '.e6data_config.json'
    
    # Load existing config if it exists
    existing_config = {}
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                existing_config = json.load(f)
        except Exception as e:
            _logger.warning(f"Failed to load existing config: {e}")
    
    # Update optimization section
    existing_config['optimization'] = optimization_config
    
    try:
        with open(config_file, 'w') as f:
            json.dump(existing_config, f, indent=2)
        _logger.info(f"Saved configuration to {config_file}")
        return True
    except Exception as e:
        _logger.error(f"Failed to save config to {config_file}: {e}")
        return False

def set_and_save_mode(mode: str) -> bool:
    """
    Set optimization mode and save to configuration file.
    
    Args:
        mode: Optimization mode to set and save
        
    Returns:
        bool: True if saved successfully
    """
    set_optimization_mode(mode)
    
    config = {
        'mode': mode,
        'enabled': _optimization_enabled,
        'saved_at': __import__('datetime').datetime.now().isoformat()
    }
    
    return save_config_file(config)

def _auto_enable_optimizations():
    """
    Automatically enable optimizations on module import.
    This provides transparent performance improvements.
    """
    global _current_mode, _force_mode
    
    try:
        # Detect Cython availability and check environment settings
        _detect_cython()
        
        # Check for environment-based disabling
        if os.environ.get('E6DATA_DISABLE_OPTIMIZATIONS', '').lower() in ('1', 'true', 'yes'):
            _logger.info("All optimizations disabled via E6DATA_DISABLE_OPTIMIZATIONS")
            disable_fast_deserialization()
            return
        
        # Load configuration file settings (environment variables take precedence)
        config = _load_config_file()
        if config and not _force_mode:  # Only use config if no env override
            config_mode = config.get('mode', 'auto')
            if config.get('enabled', True):
                _force_mode = config_mode if config_mode != 'auto' else None
                _logger.info(f"Loaded optimization mode from config: {config_mode}")
            else:
                _logger.info("Optimizations disabled via configuration file")
                disable_fast_deserialization()
                return
        
        # Enable optimizations based on force mode or auto-detection
        if _force_mode == 'cython':
            if _cython_available:
                enable_fast_deserialization(force_cython=True)
            else:
                _logger.warning("Cython forced but not available, falling back to Python optimized")
                enable_fast_deserialization(force_cython=False)
        elif _force_mode == 'python':
            enable_fast_deserialization(force_cython=False)
        elif _force_mode == 'default':
            disable_fast_deserialization()
        else:
            # Auto mode
            if _cython_available:
                enable_fast_deserialization(force_cython=True)
            else:
                enable_fast_deserialization(force_cython=False)
        
        patch_datainputstream()
        _logger.info(f"Auto-enabled {_current_mode} optimizations")
        
    except Exception as e:
        _logger.warning(f"Failed to auto-enable optimizations: {e}")
        disable_fast_deserialization()

# Auto-enable optimizations on module import
try:
    _auto_enable_optimizations()
except Exception as e:
    _logger.debug(f"Optimization auto-enablement failed: {e}")