#!/usr/bin/env python3
"""Test the fix for invalid binary data handling."""
import sys
sys.path.insert(0, '..')

from e6data_python_connector.datainputstream import _binary_to_decimal128
from decimal import Decimal

# Test invalid binary data
invalid_binary = b"\x00\x01\x02\x03"  # Random bytes
result = _binary_to_decimal128(invalid_binary)
print(f"Invalid binary result: {result}")
print(f"Type: {type(result)}")
print(f"Expected: Decimal('0')")
print(f"Match: {result == Decimal('0')}")

# Also test the other cases
test_cases = [
    (b"123.456", "valid decimal string"),
    (b"", "empty bytes"),
    (None, "None input"),
    (b"not-a-number", "invalid decimal string")
]

print("\nOther test cases:")
for data, desc in test_cases:
    result = _binary_to_decimal128(data)
    print(f"{desc}: {data} -> {result}")