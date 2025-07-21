#!/usr/bin/env python3
"""Debug the binary encoding step by step."""

# Binary data
binary_data = b'\xb4\xc4\xb3W\xa5y;\x85\xf6u\xdd\xc0\x00\x00\x00\x02'
expected = 12345678901234567890123456789012345678

print(f"Binary: {' '.join(f'{b:02x}' for b in binary_data)}")
print(f"Expected: {expected}")

# Convert to 128-bit integer
bits = int.from_bytes(binary_data, byteorder='big')
print(f"128-bit int: {bits}")

# Extract fields manually
sign = (bits >> 127) & 1
G = (bits >> 122) & 0x1F
exp_continuation = (bits >> 110) & 0xFFF
coeff_continuation = bits & ((1 << 110) - 1)

print(f"\nFields:")
print(f"Sign: {sign}")
print(f"G: {G} = 0b{G:05b}")
print(f"Exp continuation: {exp_continuation}")
print(f"Coeff continuation: {coeff_continuation}")

# G field analysis
print(f"\nG field analysis:")
print(f"G = {G} = 0b{G:05b}")
print(f"G < 24? {G < 24}")
print(f"G < 30? {G < 30}")

if G < 24:
    exp_high = G >> 3
    msd = G & 0x7
    print(f"Normal case: exp_high={exp_high}, msd={msd}")
elif G < 30:
    exp_high = 0b11
    msd = 8 + (G & 0x1)
    print(f"Large MSD case: exp_high={exp_high}, msd={msd}")
else:
    print(f"Special case: G={G}")

# Calculate exponent
if 'exp_high' in locals():
    biased_exponent = (exp_high << 12) | exp_continuation
    exponent = biased_exponent - 6176
    print(f"\nExponent calculation:")
    print(f"Biased exponent: {biased_exponent}")
    print(f"Actual exponent: {exponent}")

# What should the coefficient be?
print(f"\nCoefficient analysis:")
if 'exponent' in locals():
    # For the value 12345678901234567890123456789012345678
    # If exponent is e, then coefficient should be value / (10^e)
    target_coefficient = expected // (10 ** exponent)
    remainder = expected % (10 ** exponent)
    
    print(f"Target coefficient: {target_coefficient}")
    print(f"Target coefficient length: {len(str(target_coefficient))}")
    print(f"Remainder: {remainder}")
    
    if remainder == 0 and len(str(target_coefficient)) <= 34:
        print(f"✓ Valid coefficient representation")
        
        # Check if MSD matches
        target_msd = int(str(target_coefficient)[0])
        print(f"Target MSD: {target_msd}")
        print(f"Actual MSD: {msd}")
        print(f"MSD matches: {target_msd == msd}")
        
        if target_msd == msd:
            # Check remaining digits
            remaining_digits = str(target_coefficient)[1:]
            remaining_value = int(remaining_digits) if remaining_digits else 0
            
            print(f"Remaining digits: '{remaining_digits}'")
            print(f"Remaining value: {remaining_value}")
            print(f"Coeff continuation: {coeff_continuation}")
            print(f"Match: {remaining_value == coeff_continuation}")
            
            if remaining_value != coeff_continuation:
                print(f"Ratio: {remaining_value / coeff_continuation if coeff_continuation > 0 else 'inf'}")
                
                # Look for encoding pattern
                print(f"\nLooking for encoding pattern:")
                
                # Maybe it's stored in hex format?
                hex_str = f"{coeff_continuation:x}"
                print(f"Coeff continuation in hex: {hex_str}")
                
                # Try DPD decoding approach
                print(f"\nTrying DPD-like decoding:")
                
                # The coefficient continuation has 110 bits
                # Let's see what the actual bit pattern looks like
                coeff_bits = f"{coeff_continuation:0110b}"
                print(f"Coeff continuation bits: {coeff_bits}")
                
                # Try interpreting in groups of 10 bits (DPD groups)
                print(f"DPD groups (10 bits each):")
                for i in range(11):  # 110 bits = 11 groups of 10 bits
                    group_bits = (coeff_continuation >> (10 * i)) & 0x3FF
                    print(f"  Group {i}: {group_bits:010b} = {group_bits} = 0x{group_bits:03x}")
                
                # Check if there's a simple pattern in the binary
                print(f"\nBinary analysis:")
                print(f"Leading zeros in coeff_continuation: {coeff_continuation.bit_length()}")
                print(f"Coeff continuation >> 100: {coeff_continuation >> 100}")
                print(f"Coeff continuation & 0xFFFFFFFF: {coeff_continuation & 0xFFFFFFFF}")
                
                # Maybe the coefficient continuation encodes the digits in a different way
                # Let's try to see if there's a pattern by looking at the hex representation
                print(f"\nHex digit analysis:")
                hex_digits = f"{coeff_continuation:x}"
                print(f"Hex representation: {hex_digits}")
                
                # Try converting hex digits to decimal
                decimal_from_hex = ""
                for char in hex_digits:
                    if char.isdigit():
                        decimal_from_hex += char
                    else:
                        # a=10, b=11, c=12, d=13, e=14, f=15
                        decimal_from_hex += str(ord(char.lower()) - ord('a') + 10)
                
                print(f"Decimal from hex: {decimal_from_hex}")
                
                # Try this as the remaining digits
                if len(decimal_from_hex) <= 33:
                    padded_decimal = decimal_from_hex.zfill(33)
                    reconstructed = str(msd) + padded_decimal
                    if len(reconstructed) <= 34:
                        reconstructed_int = int(reconstructed)
                        final_value = reconstructed_int * (10 ** exponent)
                        print(f"Reconstructed coefficient: {reconstructed}")
                        print(f"Final value: {final_value}")
                        print(f"Matches expected: {final_value == expected}")
                        
                        if final_value == expected:
                            print(f"✓ FOUND THE SOLUTION!")
                            print(f"  Method: Convert hex digits to decimal")
                            print(f"  Hex: {hex_digits}")
                            print(f"  Decimal: {decimal_from_hex}")
                            print(f"  Padded: {padded_decimal}")
                            print(f"  Coefficient: {reconstructed}")
    else:
        print(f"❌ Cannot represent as valid coefficient")
else:
    print(f"❌ Could not calculate exponent")