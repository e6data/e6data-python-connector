#!/usr/bin/env python3
"""Manual analysis of the 38 nines binary data."""

# Binary data that should decode to 38 nines
binary_data = b'\xb4\xc4\xb3W\xa5y;\x85\xf6u\xdd\xc0\x00\x00\x00\x02'

# Convert to 128-bit integer
bits = int.from_bytes(binary_data, byteorder='big')
print(f"Binary data: {binary_data.hex()}")
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

# For 38 nines, we need coefficient = 9999999999999999999999999999999999999 (34 digits)
# with exponent = 4, so the final value is 9999999999999999999999999999999999999 * 10^4
expected_coefficient = 9999999999999999999999999999999999999
print(f"\nExpected coefficient: {expected_coefficient}")
print(f"Expected coefficient length: {len(str(expected_coefficient))}")

# This is what we should get from the DPD decoding
# Let's see if the coefficient continuation could encode this
print(f"\nCoefficient continuation: {coeff_continuation}")
print(f"Coefficient continuation hex: 0x{coeff_continuation:x}")

# The issue is likely in the DPD decoding
# The coefficient continuation should encode 33 decimal digits (after the MSD)
# Let's try a simple approach: if the exponent is 4, we can reverse-engineer what
# the coefficient should be to get 38 nines

if 'exponent' in locals() and exponent == 4:
    # If exponent is 4, coefficient should be 9999999999999999999999999999999999999
    # which is 9 followed by 33 nines
    
    # Let's see if we can build this from the most significant digit
    if msd == 9:
        # Perfect! The MSD is 9
        # Now we need 33 more nines from the coefficient continuation
        remaining_nines = "9" * 33
        expected_remaining = int(remaining_nines)
        print(f"\nIf MSD is 9, remaining digits should be: {expected_remaining}")
        print(f"Remaining digits length: {len(remaining_nines)}")
        
        # The coefficient continuation should decode to this value
        # Let's see what we're getting from the current DPD algorithm
        
        # For debugging, let's check if the coefficient continuation
        # could represent 33 nines in some encoding
        
        # 33 nines = 999999999999999999999999999999999
        # This is approximately 10^33 - 1
        
        # The coefficient continuation has 110 bits
        # 110 bits can represent up to 2^110 - 1 ≈ 1.3 × 10^33
        # So it's theoretically possible to encode 33 nines
        
        max_110_bits = (1 << 110) - 1
        print(f"Max value in 110 bits: {max_110_bits}")
        print(f"33 nines: {expected_remaining}")
        print(f"Can 110 bits encode 33 nines? {max_110_bits >= expected_remaining}")
        
        # If our coefficient continuation is much smaller, 
        # then either the encoding is wrong, or the interpretation is wrong
        print(f"Actual coefficient continuation: {coeff_continuation}")
        print(f"Ratio: {coeff_continuation / expected_remaining if expected_remaining > 0 else 0}")
        
        # Maybe the coefficient continuation is already the right value
        # but we need to interpret it differently
        
        # Let's try: maybe the coefficient continuation IS the remaining digits
        # and we just need to combine it with the MSD
        
        combined_coefficient = int(str(msd) + str(coeff_continuation).zfill(33))
        print(f"\nDirect combination: {msd} + {coeff_continuation} = {combined_coefficient}")
        print(f"Combined coefficient length: {len(str(combined_coefficient))}")
        
        if len(str(combined_coefficient)) <= 34:
            final_value = combined_coefficient * (10 ** exponent)
            print(f"Final value: {final_value}")
            print(f"Matches 38 nines? {final_value == int('9' * 38)}")