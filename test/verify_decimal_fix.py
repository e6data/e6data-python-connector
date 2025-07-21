#!/usr/bin/env python3
"""Verify the decimal fix works."""
import sys
sys.path.insert(0, '..')

print("Testing DECIMAL128 invalid binary data handling...\n")

from e6data_python_connector.datainputstream import _binary_to_decimal128
from decimal import Decimal

# Test case that was failing
print("1. Testing raw binary data (\\x00\\x01\\x02\\x03):")
invalid_binary = b"\x00\x01\x02\x03"
result = _binary_to_decimal128(invalid_binary)
print(f"   Input: {repr(invalid_binary)}")
print(f"   Result: {result}")
print(f"   Type: {type(result)}")
print(f"   Expected: Decimal('0')")
print(f"   Success: {result == Decimal('0')}")

# Test other edge cases
print("\n2. Testing other edge cases:")
test_cases = [
    (b"123.456", "Valid decimal string"),
    (b"not-a-number", "Invalid decimal string"),
    (b"", "Empty bytes"),
    (None, "None input"),
    (b"\xff\xfe\xfd", "More random bytes")
]

for data, desc in test_cases:
    result = _binary_to_decimal128(data)
    print(f"   {desc}: {repr(data)} -> {result}")

print("\n✓ All tests completed!")