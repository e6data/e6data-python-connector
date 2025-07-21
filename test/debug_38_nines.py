#!/usr/bin/env python3
"""Debug the 38 nines decoding."""

# Binary data that should decode to 38 nines
binary_data = b'\xb4\xc4\xb3W\xa5y;\x85\xf6u\xdd\xc0\x00\x00\x00\x02'

# Convert to 128-bit integer
bits = int.from_bytes(binary_data, byteorder='big')
print(f"Binary data: {binary_data.hex()}")
print(f"128-bit integer: {bits}")
print(f"Hex: 0x{bits:032x}")
print(f"Binary: {bin(bits)}")

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
biased_exponent = (exp_high << 12) | exp_continuation
exponent = biased_exponent - 6176
print(f"Biased exponent: {biased_exponent}")
print(f"Actual exponent: {exponent}")

# Analyze coefficient continuation
print(f"\nCoefficient analysis:")
print(f"Coefficient continuation: {coeff_continuation}")
print(f"Coefficient hex: 0x{coeff_continuation:x}")

# Check if this follows the pattern for 38 nines
expected = 99999999999999999999999999999999999999
print(f"\nExpected: {expected}")
print(f"Expected digits: {len(str(expected))}")

# For 38 nines, the coefficient would be 9999999999999999999999999999999999999
# (34 digits, the maximum for Decimal128) with an exponent of 4
# So the number would be 9999999999999999999999999999999999999 * 10^4

# Check if our coefficient can encode this
# The coefficient should be around 9999999999999999999999999999999999999
# Let's see what our coefficient looks like in decimal

# For debugging, let's break down the DPD groups
print(f"\nDPD group analysis:")
for i in range(11):
    group_bits = (coeff_continuation >> (10 * i)) & 0x3FF
    print(f"Group {i}: {group_bits:010b} (0x{group_bits:03x}, {group_bits})")

# What would the expected coefficient be?
if exponent == 4:
    # Then coefficient should be 9999999999999999999999999999999999999
    expected_coeff = 9999999999999999999999999999999999999
    print(f"\nIf exponent is 4, expected coefficient: {expected_coeff}")
    
    # Check if this is plausible
    # The coefficient for Decimal128 is limited to 34 digits
    expected_coeff_str = str(expected_coeff)
    if len(expected_coeff_str) <= 34:
        print(f"Coefficient fits in 34 digits: {len(expected_coeff_str)} digits")
    else:
        print(f"Coefficient too large: {len(expected_coeff_str)} digits")