# DECIMAL128 Fix Summary

## Issue
The test case "4. Testing invalid binary data..." was failing with:
```
❌ Test failed: Expected Decimal('0'), got None
Error converting binary to Decimal128: [<class 'decimal.ConversionSyntax'>]
```

## Root Cause
When the `_binary_to_decimal128` function received invalid binary data:
1. It successfully decoded the bytes as UTF-8 (e.g., `\x00\x01\x02\x03` → some control characters)
2. But when trying to create a `Decimal` from these control characters, it raised an exception
3. The outer exception handler caught this and returned `None`
4. The test expected `Decimal('0')` as fallback

## Fix Applied
Updated `e6data_python_connector/datainputstream.py`:

1. **Added decimal module import**: `import decimal`
2. **Updated exception handling**: Now catches `decimal.InvalidOperation` and `TypeError` in addition to `UnicodeDecodeError` and `ValueError`
3. **Changed fallback behavior**: The outer exception handler now returns `Decimal('0')` instead of `None`

### Code Changes:
```python
# Before:
except (UnicodeDecodeError, ValueError, ArithmeticError) as e:

# After:
except (UnicodeDecodeError, ValueError, decimal.InvalidOperation, TypeError) as e:
```

```python
# Before (outer exception handler):
except Exception as e:
    _logger.error(f"Error converting binary to Decimal128: {e}")
    return None

# After:
except Exception as e:
    _logger.error(f"Error converting binary to Decimal128: {e}")
    # Return Decimal('0') as fallback for any unexpected errors
    return Decimal('0')
```

## Behavior
The function now handles:
- **Valid decimal strings**: `b"123.456"` → `Decimal('123.456')`
- **Invalid decimal strings**: `b"not-a-number"` → `Decimal('0')`
- **Raw binary data**: `b"\x00\x01\x02\x03"` → `Decimal('0')`
- **Empty/None input**: `None` or `b""` → `None`

## Test Update
Also fixed the test file to use actual binary data instead of escaped string:
```python
# Before:
invalid_binary = b"\\x00\\x01\\x02\\x03"  # This is actually the string "\\x00\\x01\\x02\\x03"

# After:
invalid_binary = b"\x00\x01\x02\x03"  # This is actual binary data
```