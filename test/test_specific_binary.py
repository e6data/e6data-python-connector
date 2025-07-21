#!/usr/bin/env python3
"""Test the specific binary value from the user."""

import sys
import os
from decimal import Decimal

# Add the parent directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from e6data_python_connector.datainputstream import _binary_to_decimal128

def test_specific_binary():
    """Test the specific binary value that was failing."""
    
    # The exact binary value from the user
    binary_data = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00%f\x80'
    
    print(f"Testing binary: {binary_data}")
    print(f"Hex: {binary_data.hex()}")
    print(f"Length: {len(binary_data)} bytes")
    
    # Test the parsing
    result = _binary_to_decimal128(binary_data)
    print(f"Result: {result}")
    print(f"Type: {type(result)}")
    
    # Let's manually analyze this
    bits = int.from_bytes(binary_data, byteorder='big')
    print(f"\nBinary analysis:")
    print(f"128-bit integer: {bits}")
    print(f"Hex: 0x{bits:032x}")
    
    # Extract fields
    sign = (bits >> 127) & 1
    combination = (bits >> 110) & 0x1FFFF
    coeff_continuation = bits & 0x3FFFFFFFFFFFFFFFFFFFFFFFFFFFF
    
    print(f"Sign: {sign}")
    print(f"Combination: {combination}")
    print(f"Coefficient continuation: {coeff_continuation}")
    
    # The hex representation is: 00000000000000000000000000256680
    # This is a very small number with most bits zero
    # The meaningful bits are in the last 4 bytes: 0x00256680
    
    # Let's see if we can decode this manually
    # 0x256680 = 2385536 in decimal
    
    # Looking at the bit pattern, let's check if this represents a simple decimal
    # The fact that it's mostly zeros suggests it's a small positive number
    
    # Let's try to understand what decimal value this should represent
    # by looking at the non-zero bits
    
    # Check if the combination field indicates a normal number
    if (combination >> 15) != 0b11:  # Not a special value
        exponent_bits = (combination >> 3) & 0x3FFF
        msd = combination & 0x7
        exponent = exponent_bits - 6176
        
        print(f"Exponent bits: {exponent_bits}")
        print(f"Actual exponent: {exponent}")
        print(f"MSD: {msd}")
        
        # The coefficient continuation contains the rest of the decimal digits
        print(f"Coefficient continuation: {coeff_continuation}")
        
        # Let's try to guess what this number might be
        # Given the pattern, it could be a small decimal number
        
        # The meaningful part is in the last few bytes
        # Let's focus on the last 4 bytes: 0x00256680
        last_4_bytes = binary_data[-4:]
        last_4_int = int.from_bytes(last_4_bytes, byteorder='big')
        print(f"Last 4 bytes as int: {last_4_int}")
        
        # This might give us a clue about the actual decimal value
        # 0x256680 = 2385536
        # If we interpret this as a coefficient with some scaling...
        
        # Let's see if this could be related to a common decimal pattern
        # Maybe it's representing a number like 2.385536 or 23.85536?
        
        possible_values = [
            2385536,
            238.5536,
            23.85536,
            2.385536,
            0.2385536,
            0.02385536
        ]
        
        print(f"Possible decimal interpretations:")
        for val in possible_values:
            print(f"  {val}")

if __name__ == "__main__":
    test_specific_binary()