#!/usr/bin/env python3
"""Test the current implementation with the corrected expected value."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from e6data_python_connector.datainputstream import _binary_to_decimal128, _decode_decimal128_binary

# Test the binary value that should decode to 12345678901234567890123456789012345678
binary_data = b'\xb4\xc4\xb3W\xa5y;\x85\xf6u\xdd\xc0\x00\x00\x00\x02'
expected = 12345678901234567890123456789012345678

print(f"Binary data: {binary_data.hex()}")
print(f"Expected: {expected}")
print(f"Expected length: {len(str(expected))} digits")

# Test current implementation
try:
    result = _binary_to_decimal128(binary_data)
    print(f"Result: {result}")
    print(f"Result type: {type(result)}")
    print(f"Match: {str(result) == str(expected)}")
    
    if str(result) != str(expected):
        print(f"❌ Current result: {result}")
        print(f"❌ Expected:       {expected}")
        print(f"❌ Difference:     {int(str(result)) - expected if str(result).isdigit() else 'N/A'}")
    else:
        print(f"✅ Perfect match!")
        
except Exception as e:
    print(f"Error: {e}")
    
# Also test the direct binary decoding
try:
    direct_result = _decode_decimal128_binary(binary_data)
    print(f"\nDirect decode result: {direct_result}")
    print(f"Direct match: {str(direct_result) == str(expected)}")
except Exception as e:
    print(f"Direct decode error: {e}")

# Manual field extraction for debugging
bits = int.from_bytes(binary_data, byteorder='big')
print(f"\nManual field extraction:")
print(f"128-bit integer: {bits}")
print(f"Hex: 0x{bits:032x}")

# Extract fields
sign = (bits >> 127) & 1
G = (bits >> 122) & 0x1F
exp_continuation = (bits >> 110) & 0xFFF
coeff_continuation = bits & ((1 << 110) - 1)

print(f"Sign: {sign}")
print(f"G: {G}")
print(f"Exp continuation: {exp_continuation}")
print(f"Coeff continuation: {coeff_continuation}")

# Decode combination field
if G < 24:
    exp_high = G >> 3
    msd = G & 0x7
    print(f"Normal number: exp_high={exp_high}, msd={msd}")
elif G < 30:
    exp_high = 0b11
    msd = 8 + (G & 0x1)
    print(f"Large MSD: exp_high={exp_high}, msd={msd}")

# Calculate exponent
if 'exp_high' in locals():
    biased_exponent = (exp_high << 12) | exp_continuation
    exponent = biased_exponent - 6176
    print(f"Biased exponent: {biased_exponent}")
    print(f"Actual exponent: {exponent}")

# Try to understand the coefficient encoding
print(f"\nCoefficient analysis:")
print(f"Coefficient continuation: {coeff_continuation}")
print(f"Coefficient continuation hex: 0x{coeff_continuation:x}")

# For 12345678901234567890123456789012345678 (38 digits)
# If exponent is 4, coefficient should be 1234567890123456789012345678901234567 (34 digits)
target_coeff = 1234567890123456789012345678901234567

print(f"Target coefficient: {target_coeff}")
print(f"Target coefficient length: {len(str(target_coeff))}")

# Check if we can reconstruct this
if 'msd' in locals():
    print(f"MSD: {msd}")
    remaining_digits = str(target_coeff)[1:]  # Remove MSD
    remaining_value = int(remaining_digits)
    print(f"Remaining digits: {remaining_digits}")
    print(f"Remaining value: {remaining_value}")
    print(f"Matches coeff_continuation: {remaining_value == coeff_continuation}")
    
    # Try reverse engineering
    print(f"\nReverse engineering:")
    coeff_str = str(coeff_continuation)
    print(f"Coeff continuation as string: '{coeff_str}'")
    print(f"Length: {len(coeff_str)}")
    
    # Try padding
    for padding in range(35):
        padded = coeff_str.zfill(padding)
        if len(padded) <= 33:  # 33 remaining digits after MSD
            reconstructed = str(msd) + padded
            if len(reconstructed) <= 34:
                reconstructed_int = int(reconstructed)
                if 'exponent' in locals():
                    final_value = reconstructed_int * (10 ** exponent)
                    if final_value == expected:
                        print(f"✓ Found solution with padding {padding}:")
                        print(f"  Padded coeff continuation: '{padded}'")
                        print(f"  Reconstructed coefficient: {reconstructed}")
                        print(f"  Final value: {final_value}")
                        break