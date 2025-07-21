#!/usr/bin/env python3
"""Test the new IEEE 754-2008 based implementation."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from e6data_python_connector.datainputstream import _binary_to_decimal128, _decode_decimal128_binary

def test_new_implementation():
    """Test the new implementation based on proper IEEE 754-2008 specification."""
    
    print("🔬 Testing New IEEE 754-2008 Based Implementation")
    print("=" * 60)
    
    # Test cases with expected results
    test_cases = [
        {
            'name': 'Known Case: 12345678901234567890123456789012345678',
            'binary': b'\xb4\xc4\xb3W\xa5y;\x85\xf6u\xdd\xc0\x00\x00\x00\x02',
            'expected': 12345678901234567890123456789012345678
        },
        {
            'name': 'Zero Case',
            'binary': b'\x00' * 16,
            'expected': 0
        }
    ]
    
    print("\nTesting known cases:")
    print("-" * 30)
    
    for i, case in enumerate(test_cases, 1):
        print(f"\n{i}. {case['name']}")
        print(f"   Binary: {case['binary'].hex()}")
        print(f"   Expected: {case['expected']}")
        
        try:
            result = _binary_to_decimal128(case['binary'])
            print(f"   Result: {result}")
            print(f"   Type: {type(result)}")
            
            if result is not None:
                match = str(result) == str(case['expected'])
                print(f"   Match: {match}")
                
                if match:
                    print("   ✅ PASS")
                else:
                    print("   ❌ FAIL")
                    print(f"     Expected: {case['expected']}")
                    print(f"     Got:      {result}")
            else:
                print("   ❌ FAIL - Result is None")
                
        except Exception as e:
            print(f"   ❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
    
    # Test the binary field extraction
    print(f"\n" + "=" * 60)
    print("Binary Field Analysis (Known Case)")
    print("=" * 60)
    
    binary_data = b'\xb4\xc4\xb3W\xa5y;\x85\xf6u\xdd\xc0\x00\x00\x00\x02'
    bits = int.from_bytes(binary_data, byteorder='big')
    
    print(f"Binary: {binary_data.hex()}")
    print(f"128-bit integer: {bits}")
    print(f"Hex: 0x{bits:032x}")
    print(f"Binary: {bin(bits)}")
    
    # Extract fields using new format
    sign = (bits >> 127) & 1
    combination = (bits >> 110) & 0x1FFFF  # 17 bits
    coeff_continuation = bits & ((1 << 110) - 1)  # 110 bits
    
    print(f"\nExtracted fields:")
    print(f"Sign: {sign}")
    print(f"Combination: {combination} (0x{combination:05x}, 0b{combination:017b})")
    print(f"Coeff continuation: {coeff_continuation}")
    
    # Decode combination field
    print(f"\nCombination field analysis:")
    top_2_bits = (combination >> 15) & 0b11
    print(f"Top 2 bits: {top_2_bits:02b}")
    
    if top_2_bits == 0b11:
        # Special case
        top_5_bits = (combination >> 12) & 0b11111
        print(f"Top 5 bits: {top_5_bits:05b}")
        if top_5_bits == 0b11110:
            print("Special value: Infinity")
        elif top_5_bits == 0b11111:
            print("Special value: NaN")
        else:
            print("Large MSD case (8 or 9)")
            exponent_bits = combination & 0x3FFF
            msd = 8 + ((combination >> 14) & 1)
            print(f"Exponent bits: {exponent_bits}")
            print(f"MSD: {msd}")
    else:
        # Normal case
        print("Normal case (MSD 0-7)")
        exponent_bits = (combination >> 3) & 0x3FFF
        msd = combination & 0x7
        print(f"Exponent bits: {exponent_bits}")
        print(f"MSD: {msd}")
    
    if 'exponent_bits' in locals():
        exponent = exponent_bits - 6176
        print(f"Biased exponent: {exponent_bits}")
        print(f"Actual exponent: {exponent}")
        
        # What should the coefficient be?
        expected_value = 12345678901234567890123456789012345678
        if exponent >= 0:
            expected_coeff = expected_value // (10 ** exponent)
            print(f"Expected coefficient: {expected_coeff}")
            print(f"Expected coefficient length: {len(str(expected_coeff))}")
            
            if len(str(expected_coeff)) <= 34:
                print("✅ Coefficient fits in 34 digits")
                
                # Check MSD
                expected_msd = int(str(expected_coeff)[0])
                print(f"Expected MSD: {expected_msd}")
                print(f"MSD match: {expected_msd == msd}")
                
                # Check remaining digits
                if len(str(expected_coeff)) > 1:
                    remaining_digits = str(expected_coeff)[1:]
                    print(f"Expected remaining digits: {remaining_digits}")
                    print(f"Expected remaining length: {len(remaining_digits)}")
                    
                    # This tells us what the coefficient continuation should decode to
                    if len(remaining_digits) <= 33:
                        expected_remaining_int = int(remaining_digits)
                        print(f"Expected remaining value: {expected_remaining_int}")
                        print(f"Coeff continuation: {coeff_continuation}")
                        print(f"Direct match: {expected_remaining_int == coeff_continuation}")
            else:
                print("❌ Coefficient too large for 34 digits")

if __name__ == "__main__":
    test_new_implementation()