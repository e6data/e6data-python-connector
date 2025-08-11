# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True
# cython: profile=False

"""
Cython-optimized data deserialization for e6data Python connector.

This module provides fast deserialization of binary data received from e6data engine.
Performance improvements come from:
1. Reduced Python object overhead
2. Direct memory access for numeric types
3. Optimized loops with typed variables
4. Minimal function call overhead
"""

cimport cython
from libc.stdlib cimport malloc, free
from libc.string cimport memcpy
from libc.stdint cimport int32_t, int64_t, uint8_t, uint16_t, uint32_t, uint64_t
from cpython.bytes cimport PyBytes_AsString, PyBytes_Size
from cpython.object cimport PyObject
from cpython.unicode cimport PyUnicode_DecodeUTF8

import struct
from datetime import datetime, timedelta
from decimal import Decimal
import pytz

# Define typed views for better performance
cdef extern from "Python.h":
    int PyObject_GetBuffer(object obj, Py_buffer *view, int flags) except -1
    void PyBuffer_Release(Py_buffer *view)

# Constants
DEF MICROS_PER_SECOND = 1000000
DEF SECONDS_PER_DAY = 86400
DEF JULIAN_EPOCH_OFFSET = 2440588

# Type definitions matching Java implementation
cdef enum VectorType:
    LONG = 0
    DATE = 1
    DATETIME = 2
    STRING = 3
    DOUBLE = 4
    BINARY = 5
    FLOAT = 6
    BOOLEAN = 7
    INTEGER = 8
    NULL = 9
    TIMESTAMP_TZ = 10
    DECIMAL128 = 11
    ARRAY = 12
    MAP = 13
    STRUCT = 14

cdef class FastDataInputStream:
    """Fast binary data reader using Cython optimizations."""
    
    cdef:
        bytes _buffer
        char* _data
        Py_ssize_t _size
        Py_ssize_t _pos
        
    def __init__(self, bytes buffer):
        self._buffer = buffer
        self._data = PyBytes_AsString(buffer)
        self._size = PyBytes_Size(buffer)
        self._pos = 0
        
    cdef inline void check_available(self, Py_ssize_t n) except *:
        if self._pos + n > self._size:
            raise ValueError(f"Not enough data: need {n} bytes, have {self._size - self._pos}")
    
    cdef inline uint8_t read_uint8(self) except? 0:
        self.check_available(1)
        cdef uint8_t value = (<uint8_t*>(self._data + self._pos))[0]
        self._pos += 1
        return value
    
    cdef inline int8_t read_int8(self) except? 0:
        self.check_available(1)
        cdef int8_t value = (<int8_t*>(self._data + self._pos))[0]
        self._pos += 1
        return value
    
    cdef inline uint16_t read_uint16_be(self) except? 0:
        self.check_available(2)
        cdef uint16_t value = ((<uint8_t*>(self._data + self._pos))[0] << 8) | \
                              (<uint8_t*>(self._data + self._pos))[1]
        self._pos += 2
        return value
    
    cdef inline int16_t read_int16_be(self) except? 0:
        cdef uint16_t unsigned_val = self.read_uint16_be()
        return <int16_t>unsigned_val
    
    cdef inline uint32_t read_uint32_be(self) except? 0:
        self.check_available(4)
        cdef uint32_t value = ((<uint8_t*>(self._data + self._pos))[0] << 24) | \
                              ((<uint8_t*>(self._data + self._pos))[1] << 16) | \
                              ((<uint8_t*>(self._data + self._pos))[2] << 8) | \
                              (<uint8_t*>(self._data + self._pos))[3]
        self._pos += 4
        return value
    
    cdef inline int32_t read_int32_be(self) except? 0:
        cdef uint32_t unsigned_val = self.read_uint32_be()
        return <int32_t>unsigned_val
    
    cdef inline uint64_t read_uint64_be(self) except? 0:
        self.check_available(8)
        cdef uint64_t value = 0
        cdef int i
        for i in range(8):
            value = (value << 8) | (<uint8_t*>(self._data + self._pos))[i]
        self._pos += 8
        return value
    
    cdef inline int64_t read_int64_be(self) except? 0:
        cdef uint64_t unsigned_val = self.read_uint64_be()
        return <int64_t>unsigned_val
    
    cdef inline double read_double_be(self) except? 0.0:
        cdef uint64_t bits = self.read_uint64_be()
        return (<double*>&bits)[0]
    
    cdef inline float read_float_be(self) except? 0.0:
        cdef uint32_t bits = self.read_uint32_be()
        return (<float*>&bits)[0]
    
    cdef inline bytes read_bytes(self, Py_ssize_t n):
        self.check_available(n)
        cdef bytes result = self._buffer[self._pos:self._pos + n]
        self._pos += n
        return result
    
    cdef inline str read_utf_string(self):
        cdef uint16_t length = self.read_uint16_be()
        cdef bytes utf_bytes = self.read_bytes(length)
        return utf_bytes.decode('utf-8')
        
    cdef inline bint read_boolean(self) except? False:
        return self.read_uint8() != 0


@cython.boundscheck(False)
@cython.wraparound(False)
cpdef tuple fast_get_query_columns_info(bytes buffer):
    """
    Fast version of get_query_columns_info using Cython.
    
    Args:
        buffer: Binary buffer containing metadata
        
    Returns:
        tuple: (rowcount, columns_description)
    """
    cdef FastDataInputStream stream = FastDataInputStream(buffer)
    cdef int64_t rowcount = stream.read_int64_be()
    cdef int32_t field_count = stream.read_int32_be()
    
    columns_description = []
    cdef int i
    cdef str name, field_type, zone, date_format
    
    for i in range(field_count):
        name = stream.read_utf_string()
        field_type = stream.read_utf_string()
        zone = stream.read_utf_string()
        date_format = stream.read_utf_string()
        
        # Create FieldInfo object (keep using Python object for compatibility)
        from e6data_python_connector.datainputstream import FieldInfo
        field_info = FieldInfo(name, field_type, date_format, zone)
        columns_description.append(field_info)
    
    return rowcount, columns_description


@cython.boundscheck(False)
@cython.wraparound(False)
cpdef list fast_read_values_from_array(list query_columns_description, bytes buffer):
    """
    Fast version of read_values_from_array using Cython.
    
    This function deserializes row data from binary format.
    """
    cdef FastDataInputStream stream = FastDataInputStream(buffer)
    cdef list value_array = []
    cdef object field_info, value
    cdef str dtype
    cdef int8_t is_present
    cdef int64_t long_val, epoch_micros
    cdef int32_t int_val, julian_day
    cdef float float_val
    cdef double double_val
    cdef bint bool_val
    cdef int16_t short_val
    cdef int8_t byte_val
    
    for field_info in query_columns_description:
        dtype = field_info.get_field_type()
        is_present = stream.read_int8()
        
        if is_present == 0:
            value_array.append(None)
            continue
            
        try:
            if dtype == "LONG":
                value_array.append(stream.read_int64_be())
                
            elif dtype == "DATE":
                long_val = stream.read_int64_be()
                epoch_seconds = long_val // MICROS_PER_SECOND
                date = datetime.fromtimestamp(epoch_seconds, pytz.UTC)
                value_array.append(date.strftime("%Y-%m-%d"))
                
            elif dtype == "DATETIME":
                epoch_micros = stream.read_int64_be()
                epoch_seconds = epoch_micros // MICROS_PER_SECOND
                micros_of_day = epoch_micros % MICROS_PER_SECOND
                date_time = datetime.fromtimestamp(epoch_seconds, pytz.UTC)
                date_time = date_time + timedelta(microseconds=micros_of_day)
                value_array.append(date_time.strftime("%Y-%m-%d %H:%M:%S"))
                
            elif dtype in ("STRING", "ARRAY", "MAP", "STRUCT"):
                value_array.append(stream.read_utf_string())
                
            elif dtype == "INT" or dtype == "INTEGER":
                value_array.append(stream.read_int32_be())
                
            elif dtype == "DOUBLE":
                value_array.append(stream.read_double_be())
                
            elif dtype == "BINARY":
                length = stream.read_uint16_be()
                value_array.append(stream.read_bytes(length))
                
            elif dtype == "FLOAT":
                value_array.append(stream.read_float_be())
                
            elif dtype == "BOOLEAN":
                value_array.append(stream.read_boolean())
                
            elif dtype == "SHORT":
                value_array.append(stream.read_int16_be())
                
            elif dtype == "BYTE":
                value_array.append(stream.read_int8())
                
            elif dtype == "INT96":
                julian_day = stream.read_int32_be()
                long_val = stream.read_int64_be()
                date_time = datetime.fromtimestamp((julian_day - JULIAN_EPOCH_OFFSET) * SECONDS_PER_DAY)
                date_time_with_nanos = date_time + timedelta(microseconds=(long_val / 1000))
                value_array.append(date_time_with_nanos)
                
            elif dtype == "DECIMAL128":
                decimal_str = stream.read_utf_string()
                value_array.append(Decimal(decimal_str))
                
            else:
                value_array.append(None)
                
        except Exception as e:
            value_array.append('Failed to parse.')
    
    return value_array


@cython.boundscheck(False)
@cython.wraparound(False)
cdef inline int64_t floor_div_fast(int64_t a, int64_t b) nogil:
    """Fast floor division for time calculations."""
    return a // b


@cython.boundscheck(False)
@cython.wraparound(False)
cdef inline int64_t floor_mod_fast(int64_t a, int64_t b) nogil:
    """Fast floor modulo for time calculations."""
    return a % b


@cython.boundscheck(False)
@cython.wraparound(False)
cpdef list fast_process_long_vector(object vector, int size):
    """Optimized processing for LONG type vectors."""
    cdef list result = []
    cdef int i
    cdef object data_array
    cdef bint is_constant = vector.isConstantVector
    cdef object null_set = vector.nullSet
    
    if is_constant:
        # Constant vector - same value for all rows
        constant_val = vector.data.numericConstantData.data
        for i in range(size):
            if null_set[0]:
                result.append(None)
            else:
                result.append(constant_val)
    else:
        # Non-constant vector - different values per row
        data_array = vector.data.int64Data.data
        for i in range(size):
            if null_set[i]:
                result.append(None)
            else:
                result.append(data_array[i])
    
    return result


@cython.boundscheck(False)
@cython.wraparound(False)
cpdef list fast_process_double_vector(object vector, int size):
    """Optimized processing for DOUBLE type vectors."""
    cdef list result = []
    cdef int i
    cdef object data_array
    cdef bint is_constant = vector.isConstantVector
    cdef object null_set = vector.nullSet
    
    if is_constant:
        constant_val = vector.data.numericDecimalConstantData.data
        for i in range(size):
            if null_set[0]:
                result.append(None)
            else:
                result.append(constant_val)
    else:
        data_array = vector.data.float64Data.data
        for i in range(size):
            if null_set[i]:
                result.append(None)
            else:
                result.append(data_array[i])
    
    return result


@cython.boundscheck(False)
@cython.wraparound(False)
cpdef list fast_process_date_vector(object vector, int size, object zone):
    """Optimized processing for DATE type vectors."""
    cdef list result = []
    cdef int i
    cdef int64_t epoch_micros, epoch_seconds
    cdef object data_array
    cdef bint is_constant = vector.isConstantVector
    cdef object null_set = vector.nullSet
    
    if is_constant:
        constant_val = vector.data.dateConstantData.data
        epoch_seconds = constant_val // MICROS_PER_SECOND
        date = datetime.fromtimestamp(epoch_seconds, zone)
        date_str = date.strftime("%Y-%m-%d")
        
        for i in range(size):
            if null_set[0]:
                result.append(None)
            else:
                result.append(date_str)
    else:
        data_array = vector.data.dateData.data
        for i in range(size):
            if null_set[i]:
                result.append(None)
            else:
                epoch_micros = data_array[i]
                epoch_seconds = epoch_micros // MICROS_PER_SECOND
                date = datetime.fromtimestamp(epoch_seconds, zone)
                result.append(date.strftime("%Y-%m-%d"))
    
    return result


# Public API function that can be called from Python
def optimize_deserialization(enable=True):
    """
    Enable or disable Cython-optimized deserialization.
    
    When enabled, the connector will use Cython-optimized functions
    for deserializing data, providing significant performance improvements.
    
    Args:
        enable (bool): Whether to enable Cython optimization
    """
    if enable:
        # Monkey-patch the original functions with Cython versions
        import e6data_python_connector.datainputstream as dis
        
        # Store original functions
        if not hasattr(dis, '_original_get_query_columns_info'):
            dis._original_get_query_columns_info = dis.get_query_columns_info
            dis._original_read_values_from_array = dis.read_values_from_array
        
        # Replace with Cython versions
        dis.get_query_columns_info = fast_get_query_columns_info
        dis.read_values_from_array = fast_read_values_from_array
        
        print("Cython-optimized deserialization enabled")
    else:
        # Restore original functions
        import e6data_python_connector.datainputstream as dis
        
        if hasattr(dis, '_original_get_query_columns_info'):
            dis.get_query_columns_info = dis._original_get_query_columns_info
            dis.read_values_from_array = dis._original_read_values_from_array
        
        print("Cython-optimized deserialization disabled")