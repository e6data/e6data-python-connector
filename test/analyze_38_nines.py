#!/usr/bin/env python3
"""Analyze the binary value that should decode to 38 nines."""

# The binary value
binary_data = b'\xb4\xc4\xb3W\xa5y;\x85\xf6u\xdd\xc0\x00\x00\x00\x02'

print(f"Binary data: {binary_data}")
print(f"Length: {len(binary_data)} bytes")
print(f"Hex: {binary_data.hex()}")

# Expected value
expected = "99999999999999999999999999999999999999"
print(f"Expected: {expected} ({len(expected)} digits)")

# Convert to 128-bit integer
bits = int.from_bytes(binary_data, byteorder='big')
print(f"\n128-bit integer: {bits}")
print(f"Hex: 0x{bits:032x}")
print(f"Binary: {bin(bits)}")

# Extract IEEE 754-2008 Decimal128 fields
sign = (bits >> 127) & 1
combination = (bits >> 110) & 0x1FFFF
coeff_continuation = bits & 0x3FFFFFFFFFFFFFFFFFFFFFFFFFFFF

print(f"\nIEEE 754-2008 Decimal128 fields:")
print(f"Sign: {sign} ({'negative' if sign else 'positive'})")
print(f"Combination: {combination:017b} (decimal: {combination})")
print(f"Coefficient continuation: {coeff_continuation}")

# Analyze combination field
print(f"\nCombination field analysis:")
top_2_bits = (combination >> 15)
print(f"Top 2 bits: {top_2_bits:02b}")

if top_2_bits != 0b11:
    exponent_bits = (combination >> 3) & 0x3FFF
    msd = combination & 0x7
    print(f"Exponent bits: {exponent_bits} (0x{exponent_bits:04x})")
    print(f"MSD: {msd}")
else:
    # Check if it's special or has MSD 8-9
    if (combination >> 12) & 0x7 == 0b111:
        print("This is NaN")
    elif (combination >> 12) & 0x7 == 0b110:
        print("This is Infinity")
    else:
        exponent_bits = (combination >> 3) & 0x3FFF
        msd = 8 + (combination & 0x1)
        print(f"Exponent bits: {exponent_bits} (0x{exponent_bits:04x})")
        print(f"MSD (8-9): {msd}")

# Calculate actual exponent
if 'exponent_bits' in locals():
    exponent = exponent_bits - 6176  # Bias is 6176
    print(f"Actual exponent: {exponent}")

# The coefficient for 38 nines should be 99999999999999999999999999999999999999
# This is a 38-digit number
print(f"\nExpected coefficient analysis:")
print(f"38 nines = {int(expected)}")
print(f"38 nines in hex: 0x{int(expected):x}")

# Let's see if the coefficient continuation could encode this
print(f"\nCoefficient continuation analysis:")
print(f"Coefficient continuation: {coeff_continuation}")
print(f"Coefficient continuation hex: 0x{coeff_continuation:x}")

# The coefficient continuation has 110 bits
# It needs to encode 37 more digits (after MSD)
# Using DPD encoding, 3 decimal digits fit in 10 bits
# So 37 digits would need about 124 bits, but we only have 110 bits

# However, the coefficient for Decimal128 can have at most 34 significant digits
# So 38 nines might be represented as 1E38 or similar

# Let's check what the actual encoding might be
print(f"\nPossible interpretations:")

# If it's truly 38 nines, it might be encoded with an exponent
# 9.999...E37 would give us the right magnitude
scientific_form = f"9.{'9' * 33}E4"
print(f"Scientific notation: {scientific_form}")

# Or it could be a special encoding
# Let's check what the combination field tells us about the exponent
if 'exponent' in locals():
    print(f"With exponent {exponent}, coefficient would be scaled by 10^{exponent}")
    
    # If exponent is 4, then coefficient of 9999...9999 (34 digits) would give us 38 digits total
    if exponent == 4:
        print("This suggests coefficient is 34 nines, scaled by 10^4 to give 38 nines")

# Let's also check byte-by-byte
print(f"\nByte-by-byte analysis:")
for i, byte in enumerate(binary_data):
    print(f"Byte {i:2d}: 0x{byte:02x} ({byte:3d}) {bin(byte)[2:].zfill(8)}")