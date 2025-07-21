#!/usr/bin/env python3
"""Analyze the specific binary value."""

# The specific binary value
binary_data = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00%f\x80'

print(f"Binary data: {binary_data}")
print(f"Length: {len(binary_data)} bytes")
print(f"Hex: {binary_data.hex()}")

# Convert to 128-bit integer
bits = int.from_bytes(binary_data, byteorder='big')
print(f"128-bit integer: {bits}")
print(f"Hex: 0x{bits:032x}")
print(f"Binary: {bin(bits)}")

# Extract IEEE 754-2008 Decimal128 fields
sign = (bits >> 127) & 1
combination = (bits >> 110) & 0x1FFFF
coeff_continuation = bits & 0x3FFFFFFFFFFFFFFFFFFFFFFFFFFFF

print(f"\nIEEE 754-2008 Decimal128 fields:")
print(f"Sign: {sign}")
print(f"Combination: {combination:017b} (decimal: {combination})")
print(f"Coefficient continuation: {coeff_continuation}")

# The hex representation shows:
# 00000000000000000000000000256680
# This means most of the number is zeros, with the last 4 bytes being 0x00256680

# Let's focus on the last 4 bytes: 0x00256680
last_4_bytes = binary_data[-4:]
print(f"\nLast 4 bytes: {last_4_bytes.hex()}")
print(f"As integer: {int.from_bytes(last_4_bytes, byteorder='big')}")

# 0x256680 = 2385536 decimal
# This suggests the number might be related to this value

# Let's check if this follows the pattern of a small decimal number
# The fact that most bits are zero suggests this is a small positive number

# Check the combination field
print(f"\nCombination field analysis:")
print(f"Top 2 bits: {(combination >> 15):02b}")
if (combination >> 15) != 0b11:
    exponent_bits = (combination >> 3) & 0x3FFF
    msd = combination & 0x7
    exponent = exponent_bits - 6176
    print(f"Exponent bits: {exponent_bits}")
    print(f"Actual exponent: {exponent}")
    print(f"MSD: {msd}")
    print(f"This is a normal number")
else:
    print("This is a special value (infinity/NaN)")

# Let's see what the actual bytes represent
print(f"\nByte analysis:")
for i, byte in enumerate(binary_data):
    print(f"Byte {i:2d}: 0x{byte:02x} ({byte:3d}) {bin(byte)[2:].zfill(8)}")

print(f"\nNon-zero bytes:")
for i, byte in enumerate(binary_data):
    if byte != 0:
        print(f"Byte {i:2d}: 0x{byte:02x} ({byte:3d}) {bin(byte)[2:].zfill(8)}")
        
# The non-zero bytes are at positions 13, 14, 15
# Byte 13: 0x00 (0)
# Byte 14: 0x25 (37) -> '%' character
# Byte 15: 0x66 (102) -> 'f' character  
# Byte 16: 0x80 (128)