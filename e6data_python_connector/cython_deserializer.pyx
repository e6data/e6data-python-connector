# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True
# cython: nonecheck=False

"""
Cython-optimized data deserialization for e6data Python connector.
Provides significant performance improvements for query result processing.
"""

import cython
import pytz
from datetime import datetime, timedelta
from decimal import Decimal
from libc.stdint cimport int64_t, int32_t
from cpython cimport PyList_New, PyList_SET_ITEM, Py_INCREF

from e6data_python_connector.e6x_vector.ttypes import Vector, VectorType
from e6data_python_connector.date_time_utils import floor_div, floor_mod

# Type definitions for better performance
ctypedef int64_t long_t
ctypedef int32_t int_t
ctypedef double double_t
ctypedef float float_t

# Cache timezone for performance
cdef object UTC_ZONE = pytz.UTC

@cython.boundscheck(False)
@cython.wraparound(False)
cdef inline bint get_null_fast(vector, int row):
    """Fast null checking with minimal Python overhead."""
    if hasattr(vector, 'nullSet') and vector.nullSet:
        if vector.isConstantVector:
            return vector.nullSet[0] if len(vector.nullSet) > 0 else False
        else:
            return vector.nullSet[row] if row < len(vector.nullSet) else False
    return False

@cython.boundscheck(False)
@cython.wraparound(False)
def fast_get_column_from_chunk(vector):
    """
    Optimized version of get_column_from_chunk using Cython.
    
    Args:
        vector: Vector object containing column data
        
    Returns:
        list: Processed column values
    """
    cdef int size = vector.size
    cdef int d_type = vector.vectorType
    cdef int row
    cdef list value_array = PyList_New(size)
    cdef object value
    
    # Long/BigInt processing
    if d_type == VectorType.LONG:
        if vector.isConstantVector:
            constant_value = vector.data.numericConstantData.data
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    value = constant_value
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
        else:
            data = vector.data.int64Data.data
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    value = data[row]
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
    
    # Date processing
    elif d_type == VectorType.DATE:
        if vector.isConstantVector:
            constant_epoch = vector.data.dateConstantData.data
            constant_seconds = floor_div(constant_epoch, 1000_000)
            constant_date = datetime.fromtimestamp(constant_seconds, UTC_ZONE)
            constant_str = constant_date.strftime("%Y-%m-%d")
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    value = constant_str
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
        else:
            data = vector.data.dateData.data
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    epoch_seconds = floor_div(data[row], 1000_000)
                    date = datetime.fromtimestamp(epoch_seconds, UTC_ZONE)
                    value = date.strftime("%Y-%m-%d")
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
    
    # DateTime processing
    elif d_type == VectorType.DATETIME:
        if vector.isConstantVector:
            constant_micros = vector.data.timeConstantData.data
            constant_seconds = floor_div(constant_micros, 1000_000)
            micros_remainder = floor_mod(constant_micros, 1000_000)
            constant_dt = datetime.fromtimestamp(constant_seconds, UTC_ZONE)
            constant_dt = constant_dt + timedelta(microseconds=micros_remainder)
            constant_str = constant_dt.isoformat(timespec='milliseconds')
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    value = constant_str
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
        else:
            data = vector.data.timeData.data
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    epoch_micros = data[row]
                    epoch_seconds = floor_div(epoch_micros, 1000_000)
                    micros_remainder = floor_mod(epoch_micros, 1000_000)
                    dt = datetime.fromtimestamp(epoch_seconds, UTC_ZONE)
                    dt = dt + timedelta(microseconds=micros_remainder)
                    value = dt.isoformat(timespec='milliseconds')
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
    
    # String/Array/Map/Struct processing
    elif d_type in (VectorType.STRING, VectorType.ARRAY, VectorType.MAP, VectorType.STRUCT):
        if vector.isConstantVector:
            constant_value = vector.data.varcharConstantData.data
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    value = constant_value
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
        else:
            data = vector.data.varcharData.data
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    value = data[row]
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
    
    # Double processing
    elif d_type == VectorType.DOUBLE:
        if vector.isConstantVector:
            constant_value = vector.data.numericDecimalConstantData.data
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    value = constant_value
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
        else:
            data = vector.data.float64Data.data
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    value = data[row]
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
    
    # Float processing
    elif d_type == VectorType.FLOAT:
        if vector.isConstantVector:
            constant_value = vector.data.numericDecimalConstantData.data
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    value = constant_value
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
        else:
            data = vector.data.float32Data.data
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    value = data[row]
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
    
    # Boolean processing
    elif d_type == VectorType.BOOLEAN:
        if vector.isConstantVector:
            constant_value = vector.data.boolConstantData.data
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    value = constant_value
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
        else:
            data = vector.data.boolData.data
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    value = data[row]
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
    
    # Integer processing
    elif d_type == VectorType.INTEGER:
        if vector.isConstantVector:
            constant_value = vector.data.numericConstantData.data
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    value = constant_value
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
        else:
            data = vector.data.int32Data.data
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    value = data[row]
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
    
    # Decimal processing (most complex)
    elif d_type == VectorType.DECIMAL:
        if vector.isConstantVector:
            constant_binary = vector.data.decimalConstantData.data
            try:
                from e6data_python_connector.datainputstream import _binary_to_decimal128
                constant_value = _binary_to_decimal128(constant_binary)
            except:
                constant_value = None
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    value = constant_value
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
        else:
            data = vector.data.decimalData.data
            from e6data_python_connector.datainputstream import _binary_to_decimal128
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    try:
                        value = _binary_to_decimal128(data[row])
                    except:
                        value = None
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
    
    # Binary processing
    elif d_type == VectorType.BINARY:
        if vector.isConstantVector:
            constant_value = vector.data.varcharConstantData.data
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    value = constant_value
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
        else:
            data = vector.data.varcharData.data
            for row in range(size):
                if get_null_fast(vector, row):
                    value = None
                else:
                    value = data[row]
                Py_INCREF(value)
                PyList_SET_ITEM(value_array, row, value)
    
    else:
        # Fallback for unknown types
        for row in range(size):
            value = None
            Py_INCREF(value)
            PyList_SET_ITEM(value_array, row, value)
    
    return value_array


@cython.boundscheck(False)
@cython.wraparound(False)
def fast_process_chunk(buffer, query_columns_description):
    """
    Optimized version of get_query_columns_info using Cython.
    
    Args:
        buffer: Binary buffer containing chunk data
        query_columns_description: Column metadata
        
    Returns:
        list: Processed rows
    """
    # Import here to avoid circular imports
    from thrift.transport import TTransport
    from thrift.protocol import TBinaryProtocol
    from e6data_python_connector.e6x_vector.ttypes import Chunk
    
    # Deserialize chunk using Thrift
    transport = TTransport.TMemoryBuffer(buffer)
    protocol = TBinaryProtocol.TBinaryProtocolAccelerated(transport)
    
    chunk = Chunk()
    chunk.read(protocol)
    
    if chunk.size <= 0:
        return None
    
    cdef int chunk_size = chunk.size
    cdef int num_columns = len(query_columns_description)
    cdef int row_index, col_index
    
    # Pre-process all columns using fast column extraction
    columns = []
    for col_index in range(num_columns):
        column_data = fast_get_column_from_chunk(chunk.vectors[col_index])
        columns.append(column_data)
    
    # Build rows with optimized loops
    cdef list rows = PyList_New(chunk_size)
    cdef list row_values
    cdef object value
    
    for row_index in range(chunk_size):
        row_values = PyList_New(num_columns)
        for col_index in range(num_columns):
            value = columns[col_index][row_index]
            Py_INCREF(value)
            PyList_SET_ITEM(row_values, col_index, value)
        Py_INCREF(row_values)
        PyList_SET_ITEM(rows, row_index, row_values)
    
    return rows