#!/usr/bin/env python3
"""Analyze the binary data that should decode to 12345678901234567890123456789012345678."""

# Binary data that should decode to the correct value
binary_data = b'\xb4\xc4\xb3W\xa5y;\x85\xf6u\xdd\xc0\x00\x00\x00\x02'

# Expected value
expected = 12345678901234567890123456789012345678
print(f"Expected value: {expected}")
print(f"Expected length: {len(str(expected))} digits")

# Convert to 128-bit integer
bits = int.from_bytes(binary_data, byteorder='big')
print(f"\nBinary data: {binary_data.hex()}")
print(f"128-bit integer: {bits}")
print(f"Hex: 0x{bits:032x}")

# Extract IEEE 754-2008 Decimal128 fields
sign = (bits >> 127) & 1
G = (bits >> 122) & 0x1F  # 5-bit combination field
exp_continuation = (bits >> 110) & 0xFFF  # 12-bit exponent continuation
coeff_continuation = bits & ((1 << 110) - 1)  # 110-bit coefficient

print(f"\nExtracted fields:")
print(f"Sign: {sign}")
print(f"G (combination): {G} (0x{G:x}, {bin(G)})")
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
else:
    print(f"Special value: G={G}")

# Combine exponent
if 'exp_high' in locals():
    biased_exponent = (exp_high << 12) | exp_continuation
    exponent = biased_exponent - 6176
    print(f"Biased exponent: {biased_exponent}")
    print(f"Actual exponent: {exponent}")
    print(f"MSD: {msd}")

# Analysis for the correct value
print(f"\nAnalysis for {expected}:")

# If the value is 12345678901234567890123456789012345678 (38 digits)
# And Decimal128 can only represent 34 significant digits
# Then it must be represented in scientific notation

# The coefficient can be at most 34 digits
# So we need: coefficient × 10^exponent = 12345678901234567890123456789012345678

# If exponent is 4, then coefficient should be 1234567890123456789012345678901234567.8
# But coefficients must be integers in Decimal128

# If exponent is 4, then coefficient should be 1234567890123456789012345678901234567 (34 digits)
# This would give us 1234567890123456789012345678901234567 × 10^4 = 12345678901234567890123456789012345670

print(f"Possible representations:")
for exp in range(10):
    if exp == 0:
        coeff = expected
    else:
        coeff = expected // (10 ** exp)
        remainder = expected % (10 ** exp)
        if remainder == 0 and len(str(coeff)) <= 34:
            print(f"  Exponent {exp}: coefficient = {coeff} ({len(str(coeff))} digits)")
            
            # Check if this matches our extracted values
            if 'exponent' in locals() and exponent == exp and msd == int(str(coeff)[0]):
                print(f"    ✓ Matches extracted exponent {exponent} and MSD {msd}")
                
                # The remaining digits should be in the coefficient continuation
                remaining_digits = str(coeff)[1:]  # Remove the MSD
                if remaining_digits:
                    remaining_value = int(remaining_digits)
                    print(f"    Remaining digits: {remaining_digits} = {remaining_value}")
                    print(f"    Coefficient continuation: {coeff_continuation}")
                    print(f"    Match: {remaining_value == coeff_continuation}")
                else:
                    print(f"    No remaining digits (coefficient continuation should be 0)")
                    print(f"    Coefficient continuation: {coeff_continuation}")
                    print(f"    Match: {coeff_continuation == 0}")

# Let's check if the coefficient continuation directly represents the remaining digits
if 'msd' in locals() and 'exponent' in locals():
    print(f"\nDirect coefficient analysis:")
    print(f"MSD: {msd}")
    print(f"Coefficient continuation: {coeff_continuation}")
    
    # Try to reconstruct the coefficient
    coeff_str = str(msd) + str(coeff_continuation)
    reconstructed_coeff = int(coeff_str)
    print(f"Reconstructed coefficient: {reconstructed_coeff}")
    
    if 'exponent' in locals():
        reconstructed_value = reconstructed_coeff * (10 ** exponent)
        print(f"Reconstructed value: {reconstructed_value}")
        print(f"Matches expected: {reconstructed_value == expected}")
        
        # If it doesn't match, try padding the coefficient continuation
        for padding in range(10):
            padded_coeff_str = str(msd) + str(coeff_continuation).zfill(33 + padding)
            if len(padded_coeff_str) <= 34:
                padded_coeff = int(padded_coeff_str)
                padded_value = padded_coeff * (10 ** exponent)
                if padded_value == expected:
                    print(f"✓ Found match with padding {padding}: {padded_coeff_str}")
                    break