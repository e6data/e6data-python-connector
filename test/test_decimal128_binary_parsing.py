#!/usr/bin/env python3
"""
Test script to verify IEEE 754-2008 Decimal128 binary parsing.
"""

import sys
import os
from decimal import Decimal

# Add the parent directory to the path to import e6data_python_connector
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from e6data_python_connector.datainputstream import _binary_to_decimal128, _decode_decimal128_binary


def test_specific_binary_value():
    """Test the specific binary value provided by the user."""
    
    print("=== Testing Specific Binary Value ===\n")
    
    # The specific binary value from the user
    binary_data = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00%f\x80'
    
    print(f"Binary data: {binary_data}")
    print(f"Length: {len(binary_data)} bytes")
    print(f"Hex representation: {binary_data.hex()}")
    
    # Parse it
    result = _binary_to_decimal128(binary_data)
    print(f"Parsed result: {result}")
    print(f"Type: {type(result)}")
    
    # Let's also analyze the binary structure
    print("\n=== Binary Analysis ===")
    if len(binary_data) == 16:
        bits = int.from_bytes(binary_data, byteorder='big')
        print(f"128-bit integer: {bits}")
        print(f"Binary representation: {bin(bits)}")
        
        # Extract fields
        sign = (bits >> 127) & 1
        combination = (bits >> 110) & 0x1FFFF
        coeff_continuation = bits & 0x3FFFFFFFFFFFFFFFFFFFFFFFFFFFF
        
        print(f"Sign bit: {sign}")
        print(f"Combination field: {combination} (0x{combination:x})")
        print(f"Coefficient continuation: {coeff_continuation}")
        
        # Check if this is a special value
        if (combination >> 15) == 0b11:
            print("This appears to be a special value (infinity/NaN)")
        else:
            print("This appears to be a normal number")
            
            # Extract exponent and MSD
            exponent_bits = (combination >> 3) & 0x3FFF
            msd = combination & 0x7
            exponent = exponent_bits - 6176
            
            print(f"Exponent bits: {exponent_bits}")
            print(f"Actual exponent: {exponent}")
            print(f"Most significant digit: {msd}")
    else:
        print("Invalid length for Decimal128")
    
    print("\n=== Test Complete ===")
    return result


def test_known_decimal128_values():
    """Test some known Decimal128 values."""
    
    print("\n=== Testing Known Decimal128 Values ===\n")
    
    # Test zero
    print("1. Testing zero...")
    # Binary representation of 0 in Decimal128
    zero_binary = b'\x00' * 16
    result = _binary_to_decimal128(zero_binary)
    print(f"Zero: {zero_binary.hex()} -> {result}")
    
    # Test positive one
    print("\n2. Testing positive one...")
    # This is a simplified test - actual binary would be more complex
    # For now, let's test the parsing logic
    
    # Test various lengths
    print("\n3. Testing various lengths...")
    test_cases = [
        (b'\x00', "1 byte"),
        (b'\x00' * 8, "8 bytes"),
        (b'\x00' * 15, "15 bytes"),
        (b'\x00' * 16, "16 bytes"),
        (b'\x00' * 17, "17 bytes")
    ]
    
    for binary_data, description in test_cases:
        result = _binary_to_decimal128(binary_data)
        print(f"{description}: {result}")
    
    print("\n=== Known Values Test Complete ===")


def test_string_compatibility():
    """Test that string representations still work."""
    
    print("\n=== Testing String Compatibility ===\n")
    
    test_cases = [
        "123.456",
        "-789.012",
        "0",
        "1.23E+10",
        "0.000000000000000001"
    ]
    
    for test_str in test_cases:
        binary_data = test_str.encode('utf-8')
        result = _binary_to_decimal128(binary_data)
        expected = Decimal(test_str)
        print(f"String '{test_str}': {result} (expected: {expected})")
        assert result == expected, f"String parsing failed for {test_str}"
    
    print("\n✓ String compatibility maintained")


def debug_binary_parsing():
    """Debug the binary parsing for the specific value."""
    
    print("\n=== Debugging Binary Parsing ===\n")
    
    binary_data = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00%f\x80'
    
    print(f"Input: {binary_data.hex()}")
    print(f"Length: {len(binary_data)}")
    
    # Let's manually parse this
    bits = int.from_bytes(binary_data, byteorder='big')
    print(f"As 128-bit integer: {bits}")
    print(f"As hex: 0x{bits:032x}")
    print(f"As binary: {bin(bits)}")
    
    # The hex is: 00000000000000000000000000256680
    # The last few bytes are: 00256680
    # This translates to: 0x00256680 = 2385536
    
    # Let's see what this means in Decimal128 format
    sign = (bits >> 127) & 1
    combination = (bits >> 110) & 0x1FFFF
    coeff_continuation = bits & 0x3FFFFFFFFFFFFFFFFFFFFFFFFFFFF
    
    print(f"\nDecoded fields:")
    print(f"Sign: {sign}")
    print(f"Combination: {combination:017b} ({combination})")
    print(f"Coefficient continuation: {coeff_continuation}")
    
    # Check the combination field more closely
    print(f"\nCombination field analysis:")
    print(f"Top 2 bits: {(combination >> 15):02b}")
    print(f"Next 14 bits (exponent): {(combination >> 3) & 0x3FFF}")
    print(f"Bottom 3 bits (MSD): {combination & 0x7}")
    
    if (combination >> 15) != 0b11:
        exponent_bits = (combination >> 3) & 0x3FFF
        msd = combination & 0x7
        exponent = exponent_bits - 6176
        print(f"Exponent: {exponent}")
        print(f"MSD: {msd}")
        
        # This should give us a clue about the actual value
        print(f"Raw coefficient continuation: {coeff_continuation}")
        
        # Try to decode it
        result = _decode_decimal128_binary(binary_data)
        print(f"Decoded result: {result}")
    else:
        print("Special value detected")


def main():
    """Run all tests."""
    try:
        result = test_specific_binary_value()
        test_known_decimal128_values()
        test_string_compatibility()
        debug_binary_parsing()
        
        print(f"\n🎉 All tests completed!")
        print(f"The specific binary value b'\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00%f\\x80' parsed as: {result}")
        return True
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)