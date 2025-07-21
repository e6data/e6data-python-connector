#!/usr/bin/env python3
"""Analyze the binary fields to understand the encoding."""

# Binary data that should decode to 12345678901234567890123456789012345678
binary_data = b'\xb4\xc4\xb3W\xa5y;\x85\xf6u\xdd\xc0\x00\x00\x00\x02'
expected = 12345678901234567890123456789012345678

# Extract fields
bits = int.from_bytes(binary_data, byteorder='big')
print(f"Binary: {binary_data.hex()}")
print(f"Expected: {expected}")
print(f"128-bit integer: {bits}")
print(f"Hex: 0x{bits:032x}")

# Extract IEEE 754-2008 Decimal128 fields
sign = (bits >> 127) & 1
G = (bits >> 122) & 0x1F
exp_continuation = (bits >> 110) & 0xFFF
coeff_continuation = bits & ((1 << 110) - 1)

print(f"\nFields:")
print(f"Sign: {sign}")
print(f"G: {G} (0b{G:05b})")
print(f"Exp continuation: {exp_continuation}")
print(f"Coeff continuation: {coeff_continuation}")

# Decode G field
if G < 24:
    exp_high = G >> 3
    msd = G & 0x7
    print(f"Normal: exp_high={exp_high}, msd={msd}")
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

# Analysis of coefficient
print(f"\nCoefficient analysis:")
print(f"MSD: {msd}")
print(f"Coefficient continuation: {coeff_continuation}")
print(f"Coefficient continuation hex: 0x{coeff_continuation:x}")

# For the expected value 12345678901234567890123456789012345678:
# If exponent is 4, coefficient should be 1234567890123456789012345678901234567
target_coefficient = 1234567890123456789012345678901234567
print(f"\nTarget coefficient: {target_coefficient}")
print(f"Target coefficient string: '{str(target_coefficient)}'")
print(f"Target coefficient length: {len(str(target_coefficient))}")

# The remaining digits after MSD should be:
remaining_digits = str(target_coefficient)[1:]  # Remove first digit (MSD)
remaining_value = int(remaining_digits)
print(f"Remaining digits: '{remaining_digits}'")
print(f"Remaining value: {remaining_value}")

# Compare with actual coefficient continuation
print(f"\nComparison:")
print(f"Expected remaining: {remaining_value}")
print(f"Actual coeff cont:  {coeff_continuation}")
print(f"Match: {remaining_value == coeff_continuation}")

if remaining_value != coeff_continuation:
    print(f"Ratio: {remaining_value / coeff_continuation if coeff_continuation > 0 else 'N/A'}")
    
    # Try to find a pattern
    print(f"\nLooking for patterns:")
    
    # Check if coefficient continuation is encoded in a different way
    coeff_str = str(coeff_continuation)
    print(f"Coeff continuation as string: '{coeff_str}'")
    print(f"Length: {len(coeff_str)}")
    
    # Check if there's a mathematical relationship
    if coeff_continuation > 0:
        # Try different interpretations
        print(f"\nTrying different interpretations:")
        
        # Direct concatenation with different padding
        for padding in range(35):
            padded = coeff_str.zfill(padding)
            if len(padded) <= 33:
                combined = str(msd) + padded
                if len(combined) <= 34:
                    combined_int = int(combined)
                    if 'exponent' in locals():
                        final_value = combined_int * (10 ** exponent)
                        if final_value == expected:
                            print(f"✓ FOUND SOLUTION:")
                            print(f"  Padding: {padding}")
                            print(f"  Padded coeff cont: '{padded}'")
                            print(f"  Combined coefficient: {combined}")
                            print(f"  Final value: {final_value}")
                            break
        
        # Also check if the coefficient continuation could be in hex
        hex_str = f"{coeff_continuation:x}"
        print(f"\nHex interpretation:")
        print(f"Coeff continuation in hex: 0x{coeff_continuation:x}")
        print(f"Hex string: '{hex_str}'")
        
        # Try interpreting hex as decimal
        try:
            hex_as_decimal = int(hex_str)
            print(f"Hex as decimal: {hex_as_decimal}")
            
            # Try this as remaining digits
            combined = str(msd) + str(hex_as_decimal).zfill(33)
            if len(combined) <= 34:
                combined_int = int(combined)
                if 'exponent' in locals():
                    final_value = combined_int * (10 ** exponent)
                    print(f"Final value with hex interpretation: {final_value}")
                    if final_value == expected:
                        print(f"✓ HEX INTERPRETATION WORKS!")
        except:
            pass