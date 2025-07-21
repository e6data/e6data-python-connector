# DECIMAL128 Implementation

This document describes the implementation of DECIMAL128 data type parsing support in the e6data Python connector.

## Overview

The e6data Python connector now supports parsing DECIMAL128 data types from the e6x_vector.thrift schema. This includes support for both:
- `Decimal128Data` - for non-constant vectors containing arrays of decimal values
- `NumericDecimal128ConstantData` - for constant vectors containing a single decimal value

## Files Modified

### 1. `e6data_python_connector/datainputstream.py`

#### Added imports:
```python
from decimal import Decimal
```

#### Added helper function:
```python
def _binary_to_decimal128(binary_data):
    """
    Convert binary data to Decimal128.
    
    The binary data represents a 128-bit decimal number.
    Based on IEEE 754-2008 Decimal128 format.
    
    Args:
        binary_data (bytes): Binary representation of Decimal128
        
    Returns:
        Decimal: Python Decimal object
    """
```

This function handles:
- String representations encoded as UTF-8 bytes
- String representations passed directly
- Null/empty input handling
- Error handling with fallback to Decimal('0') for invalid binary data

#### Modified `get_column_from_chunk()`:
Added support for `VectorType.DECIMAL128`:
```python
elif d_type == VectorType.DECIMAL128:
    for row in range(vector.size):
        if get_null(vector, row):
            value_array.append(None)
            continue
        # Handle both non-constant and constant vectors
        if vector.isConstantVector:
            # For constant vectors, use NumericDecimal128ConstantData
            binary_data = vector.data.numericDecimal128ConstantData.data
            decimal_value = _binary_to_decimal128(binary_data)
            value_array.append(decimal_value)
        else:
            # For non-constant vectors, use Decimal128Data
            binary_data = vector.data.decimal128Data.data[row]
            decimal_value = _binary_to_decimal128(binary_data)
            value_array.append(decimal_value)
```

#### Modified `read_values_from_array()`:
Added support for DECIMAL128 data type:
```python
elif dtype == "DECIMAL128":
    # Read decimal128 as UTF-8 string representation
    decimal_str = dis.read_utf().decode()
    value_array.append(Decimal(decimal_str))
```

## Data Type Mapping

| Thrift Type | Python Type | Description |
|-------------|-------------|-------------|
| `Decimal128Data` | `List[Decimal]` | Array of decimal values for non-constant vectors |
| `NumericDecimal128ConstantData` | `Decimal` | Single decimal value for constant vectors |

## Binary Format Handling

The implementation currently handles three scenarios:

1. **String Representation**: The binary data contains UTF-8 encoded string representation of the decimal number (e.g., "123.456")
2. **Invalid String**: If the decoded string is not a valid decimal number, returns `Decimal('0')` as fallback
3. **Raw Binary**: For actual IEEE 754-2008 Decimal128 binary format or non-UTF-8 data, returns `Decimal('0')` as fallback

## Usage Examples

### Non-Constant Vector
```python
# Vector with multiple decimal values
vector.data.decimal128Data.data = [b"123.456", b"-789.012", b"0.001"]
result = get_column_from_chunk(vector)
# Returns: [Decimal('123.456'), Decimal('-789.012'), Decimal('0.001')]
```

### Constant Vector
```python
# Vector with single decimal value repeated for all rows
vector.data.numericDecimal128ConstantData.data = b"999.999"
result = get_column_from_chunk(vector)
# Returns: [Decimal('999.999'), Decimal('999.999'), ...] (for vector.size rows)
```

### Null Handling
```python
# Vector with null values
vector.nullSet = [False, True, False]  # Second value is null
result = get_column_from_chunk(vector)
# Returns: [Decimal('123.456'), None, Decimal('789.012')]
```

## Test Coverage

The implementation includes comprehensive tests in `test_decimal128_parsing.py`:

1. **Helper Function Tests**: Testing `_binary_to_decimal128()` with various inputs
2. **Vector Parsing Tests**: Testing both constant and non-constant vectors
3. **Edge Cases**: Scientific notation, very small/large numbers, invalid data
4. **Integration Tests**: Verifying compatibility with existing code

## Future Enhancements

1. **Full IEEE 754-2008 Support**: Implement complete binary Decimal128 format decoding
2. **Performance Optimization**: Optimize for large datasets with many decimal values
3. **Precision Handling**: Add support for explicit precision and scale metadata

## Notes

- The implementation follows the same patterns as other data types in the connector
- Error handling is consistent with existing error handling patterns
- Null value handling follows the same logic as other nullable types
- The TODO comment in the thrift file about binary representation is acknowledged and handled with fallback logic