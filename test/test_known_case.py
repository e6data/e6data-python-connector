#!/usr/bin/env python3
"""Test the known working case."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from e6data_python_connector.datainputstream import _binary_to_decimal128

# Test the case we know should work
binary_data = b'\xb4\xc4\xb3W\xa5y;\x85\xf6u\xdd\xc0\x00\x00\x00\x02'
expected = 12345678901234567890123456789012345678

print("Testing known case:")
print(f"Binary: {binary_data.hex()}")
print(f"Expected: {expected}")

try:
    result = _binary_to_decimal128(binary_data)
    print(f"Result: {result}")
    print(f"Type: {type(result)}")
    
    if result is not None:
        result_str = str(result)
        expected_str = str(expected)
        match = result_str == expected_str
        print(f"Match: {match}")
        
        if match:
            print("✅ SUCCESS - The fix is working!")
        else:
            print("❌ FAILURE - Still not working correctly")
            print(f"Expected: {expected_str}")
            print(f"Got:      {result_str}")
            
            # Additional debugging
            if str(result).isdigit() and expected_str.isdigit():
                diff = int(result_str) - int(expected_str)
                print(f"Difference: {diff}")
    else:
        print("❌ FAILURE - Result is None")
        
except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()

# Also test the zero case
print("\n" + "="*50)
print("Testing zero case:")
zero_binary = b'\x00' * 16
print(f"Binary: {zero_binary.hex()}")
print(f"Expected: 0")

try:
    result = _binary_to_decimal128(zero_binary)
    print(f"Result: {result}")
    print(f"Match: {str(result) == '0'}")
    
    if str(result) == '0':
        print("✅ Zero case works")
    else:
        print("❌ Zero case failed")
        
except Exception as e:
    print(f"❌ ERROR: {e}")