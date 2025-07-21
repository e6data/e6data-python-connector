#!/usr/bin/env python3
"""Quick test of the fix."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from e6data_python_connector.datainputstream import _binary_to_decimal128

# Test the binary value
binary_data = b'\xb4\xc4\xb3W\xa5y;\x85\xf6u\xdd\xc0\x00\x00\x00\x02'
expected = 12345678901234567890123456789012345678

print(f"Testing binary: {binary_data.hex()}")
print(f"Expected: {expected}")

result = _binary_to_decimal128(binary_data)
print(f"Result: {result}")
print(f"Match: {str(result) == str(expected)}")

if str(result) == str(expected):
    print("✅ SUCCESS!")
else:
    print("❌ Still not matching")
    print(f"Expected: {expected}")
    print(f"Got:      {result}")