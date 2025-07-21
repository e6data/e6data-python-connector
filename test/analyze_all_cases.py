#!/usr/bin/env python3
"""Analyze all expected DECIMAL128 cases."""

# Expected values from the query output
expected_values = [
    1,
    1,
    12345678901234567890123456789012345678,
    99999999999999999999999999999999999999,
    0,
    -99999999999999999999999999999999999999,
    -99999999999999999999999999999999999998,
    -1234567890123456789012345678901234567,
    None  # Empty/null value
]

print("Analysis of expected DECIMAL128 values:")
print("=" * 60)

for i, val in enumerate(expected_values, 1):
    print(f"\nCase {i}: {val}")
    
    if val is None:
        print("  NULL value")
        continue
    
    val_str = str(abs(val))  # Work with absolute value for analysis
    sign = "negative" if val < 0 else "positive"
    
    print(f"  Sign: {sign}")
    print(f"  Digits: {len(val_str)}")
    print(f"  Value: {val_str}")
    
    # Analyze how this should be represented in Decimal128
    if len(val_str) <= 34:
        print(f"  ✓ Fits in Decimal128 coefficient (≤34 digits)")
        print(f"  Representation: coefficient={val_str}, exponent=0")
    else:
        print(f"  ! Requires scientific notation for Decimal128")
        # Calculate required exponent to fit in 34 digits
        required_exp = len(val_str) - 34
        coeff_str = val_str[:34]
        
        print(f"  Coefficient: {coeff_str} (34 digits)")
        print(f"  Exponent: {required_exp}")
        print(f"  Representation: {coeff_str}E{required_exp}")
        
        # Verify the representation
        verification = int(coeff_str) * (10 ** required_exp)
        print(f"  Verification: {verification}")
        print(f"  Matches original: {verification == abs(val)}")
    
    # For IEEE 754-2008 Decimal128, analyze the fields
    print(f"  IEEE 754-2008 Decimal128 fields:")
    
    if len(val_str) <= 34:
        # Simple case: coefficient = value, exponent = 0
        coeff = abs(val)
        exp = 0
    else:
        # Scientific notation case
        exp = len(val_str) - 34
        coeff = int(val_str[:34])
    
    print(f"    Coefficient: {coeff}")
    print(f"    Exponent: {exp}")
    print(f"    Biased exponent: {exp + 6176}")  # Bias is 6176 for Decimal128
    print(f"    Sign bit: {1 if val < 0 else 0}")
    
    # Analyze MSD (Most Significant Digit)
    msd = int(str(coeff)[0])
    print(f"    MSD: {msd}")
    
    # Analyze combination field
    if msd <= 7:
        print(f"    Combination field: Normal case (MSD 0-7)")
    else:
        print(f"    Combination field: Large MSD case (MSD 8-9)")
    
    # Remaining coefficient digits
    remaining_digits = str(coeff)[1:]
    print(f"    Remaining digits: '{remaining_digits}' ({len(remaining_digits)} digits)")
    
    if remaining_digits:
        remaining_value = int(remaining_digits)
        print(f"    Remaining value: {remaining_value}")

print("\n" + "=" * 60)
print("Binary patterns to look for:")

# Known binary pattern
known_binary = b'\xb4\xc4\xb3W\xa5y;\x85\xf6u\xdd\xc0\x00\x00\x00\x02'
known_value = 12345678901234567890123456789012345678

print(f"\nKnown case:")
print(f"  Binary: {known_binary.hex()}")
print(f"  Value: {known_value}")

# Analyze the known binary
bits = int.from_bytes(known_binary, byteorder='big')
print(f"  128-bit int: {bits}")

# Extract fields
sign = (bits >> 127) & 1
G = (bits >> 122) & 0x1F
exp_continuation = (bits >> 110) & 0xFFF
coeff_continuation = bits & ((1 << 110) - 1)

print(f"  Sign: {sign}")
print(f"  G: {G}")
print(f"  Exp continuation: {exp_continuation}")
print(f"  Coeff continuation: {coeff_continuation}")

# Calculate fields
if G < 24:
    exp_high = G >> 3
    msd = G & 0x7
elif G < 30:
    exp_high = 0b11
    msd = 8 + (G & 0x1)

biased_exponent = (exp_high << 12) | exp_continuation
exponent = biased_exponent - 6176

print(f"  Decoded MSD: {msd}")
print(f"  Decoded exponent: {exponent}")
print(f"  Expected coefficient: {known_value // (10 ** exponent)}")

print(f"\nThis gives us a pattern to understand how the encoding works.")
print(f"We can use this to verify our implementation handles all cases correctly.")