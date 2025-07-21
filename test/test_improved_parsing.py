#!/usr/bin/env python3
"""Test the improved binary parsing implementation."""

import sys
import os
from decimal import Decimal

# Add the parent directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from e6data_python_connector.datainputstream import _binary_to_decimal128, _decode_decimal128_binary

def test_specific_binary_improved():
    """Test the specific binary value with improved parsing."""
    
    # The exact binary value from the user
    binary_data = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00%f\x80'
    
    print(f"Testing binary: {binary_data}")
    print(f"Hex: {binary_data.hex()}")
    print(f"Length: {len(binary_data)} bytes")
    
    # Test the improved parsing
    result = _binary_to_decimal128(binary_data)
    print(f"Result: {result}")
    print(f"Type: {type(result)}")
    
    # Test direct binary decoding
    direct_result = _decode_decimal128_binary(binary_data)
    print(f"Direct decode result: {direct_result}")
    
    # Manual analysis
    bits = int.from_bytes(binary_data, byteorder='big')
    print(f"\nBinary analysis:")
    print(f"128-bit integer: {bits}")
    print(f"Hex: 0x{bits:032x}")
    
    # Extract fields
    sign = (bits >> 127) & 1
    combination = (bits >> 110) & 0x1FFFF
    coeff_continuation = bits & 0x3FFFFFFFFFFFFFFFFFFFFFFFFFFFF
    
    print(f"Sign: {sign}")
    print(f"Combination: {combination} (0x{combination:x})")
    print(f"Coefficient continuation: {coeff_continuation}")
    
    # Extract the last 4 bytes (where the meaningful data is)
    last_4_bytes = binary_data[-4:]
    last_4_int = int.from_bytes(last_4_bytes, byteorder='big')
    print(f"Last 4 bytes: {last_4_bytes.hex()} = {last_4_int}")
    
    # Check if it's a normal number
    if (combination >> 15) != 0b11:
        exponent_bits = (combination >> 3) & 0x3FFF
        msd = combination & 0x7
        exponent = exponent_bits - 6176
        
        print(f"Exponent bits: {exponent_bits}")
        print(f"Actual exponent: {exponent}")
        print(f"MSD: {msd}")
        
        # Show meaningful bits
        meaningful_bits = coeff_continuation & 0xFFFFFFFF
        print(f"Meaningful bits (last 32): {meaningful_bits}")
        
        # Try some interpretations
        print(f"\nPossible interpretations:")
        print(f"  Raw coefficient: {last_4_int}")
        print(f"  Scaled by 1e-6: {last_4_int / 1000000}")
        print(f"  Scaled by 1e-3: {last_4_int / 1000}")
        print(f"  With exponent: {last_4_int}E{exponent}")
        
        # Check if this could be a currency or percentage value
        # 0x256680 = 2385536
        # Maybe it's 23.85536 (scaled by 100000)?
        # Maybe it's 2.385536 (scaled by 1000000)?
        
        currency_interpretations = [
            (last_4_int / 100, "cents to dollars"),
            (last_4_int / 1000, "scaled by 1000"),
            (last_4_int / 10000, "scaled by 10000"),
            (last_4_int / 100000, "scaled by 100000"),
            (last_4_int / 1000000, "scaled by 1000000"),
        ]
        
        print(f"\nCurrency/percentage interpretations:")
        for value, desc in currency_interpretations:
            print(f"  {value:10.6f} ({desc})")

def test_other_binary_patterns():
    """Test other binary patterns to understand the encoding."""
    
    print(f"\n=== Testing Other Binary Patterns ===")
    
    # Test all zeros
    zeros = b'\x00' * 16
    result = _binary_to_decimal128(zeros)
    print(f"All zeros: {result}")
    
    # Test simple patterns
    patterns = [
        b'\x00' * 15 + b'\x01',  # Just 1 in the last byte
        b'\x00' * 14 + b'\x01\x00',  # 1 in byte 14
        b'\x00' * 12 + b'\x00\x01\x00\x00',  # 1 in byte 12
    ]
    
    for i, pattern in enumerate(patterns):
        result = _binary_to_decimal128(pattern)
        print(f"Pattern {i+1}: {pattern.hex()} -> {result}")

if __name__ == "__main__":
    test_specific_binary_improved()
    test_other_binary_patterns()