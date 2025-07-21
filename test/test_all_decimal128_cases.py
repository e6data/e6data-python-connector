#!/usr/bin/env python3
"""Test all DECIMAL128 cases from the expected query output."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from e6data_python_connector.datainputstream import _binary_to_decimal128
from decimal import Decimal

def test_decimal128_cases():
    """Test various DECIMAL128 cases."""
    
    print("Testing DECIMAL128 cases from query output:")
    print("=" * 60)
    
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
    
    print(f"Expected values:")
    for i, val in enumerate(expected_values, 1):
        print(f"  {i}: {val}")
    
    # Test cases we can verify
    test_cases = [
        {
            'name': 'Case 3: 12345678901234567890123456789012345678',
            'binary': b'\xb4\xc4\xb3W\xa5y;\x85\xf6u\xdd\xc0\x00\x00\x00\x02',
            'expected': 12345678901234567890123456789012345678
        },
        {
            'name': 'Case 4: 99999999999999999999999999999999999999 (38 nines)',
            'binary': None,  # We need to determine this binary representation
            'expected': 99999999999999999999999999999999999999
        },
        {
            'name': 'Case 5: 0',
            'binary': b'\x00' * 16,  # All zeros
            'expected': 0
        }
    ]
    
    print(f"\nRunning tests:")
    print("=" * 60)
    
    for test_case in test_cases:
        print(f"\n{test_case['name']}")
        print(f"Expected: {test_case['expected']}")
        
        if test_case['binary']:
            print(f"Binary: {test_case['binary'].hex()}")
            
            try:
                result = _binary_to_decimal128(test_case['binary'])
                print(f"Result: {result}")
                print(f"Type: {type(result)}")
                
                # Check if result matches expected
                if result is not None:
                    result_str = str(result)
                    expected_str = str(test_case['expected'])
                    match = result_str == expected_str
                    print(f"Match: {match}")
                    
                    if match:
                        print("✅ PASS")
                    else:
                        print("❌ FAIL")
                        print(f"  Expected: {expected_str}")
                        print(f"  Got:      {result_str}")
                else:
                    print("❌ FAIL - Result is None")
                    
            except Exception as e:
                print(f"❌ ERROR: {e}")
        else:
            print("Binary representation unknown - skipping")
    
    print(f"\n" + "=" * 60)
    print("Additional test cases:")
    
    # Test edge cases
    edge_cases = [
        {
            'name': 'Small positive number (1)',
            'test_binary': None,  # Would need actual binary
            'expected': 1
        },
        {
            'name': 'Small negative number (-1)',
            'test_binary': None,  # Would need actual binary  
            'expected': -1
        },
        {
            'name': 'Large negative (case 6): -99999999999999999999999999999999999999',
            'test_binary': None,  # Would need actual binary
            'expected': -99999999999999999999999999999999999999
        },
        {
            'name': 'Large negative (case 7): -99999999999999999999999999999999999998',
            'test_binary': None,  # Would need actual binary
            'expected': -99999999999999999999999999999999999998
        }
    ]
    
    for case in edge_cases:
        print(f"\n{case['name']}")
        print(f"Expected: {case['expected']}")
        print("Binary representation needed for testing")
    
    print(f"\n" + "=" * 60)
    print("Analysis of expected values:")
    
    # Analyze the expected values
    for i, val in enumerate(expected_values, 1):
        if val is not None:
            val_str = str(val)
            print(f"  {i}: {val_str} ({len(val_str)} digits)")
            
            # Check if it can be represented in Decimal128
            if len(val_str) <= 34:
                print(f"      ✓ Fits in Decimal128 coefficient (≤34 digits)")
            else:
                print(f"      ! Requires scientific notation for Decimal128")
                # Calculate required exponent
                required_exp = len(val_str) - 34
                coeff = int(val_str[:34])
                print(f"      Coefficient: {coeff} (34 digits)")
                print(f"      Exponent: {required_exp}")
                print(f"      Representation: {coeff}E{required_exp}")
        else:
            print(f"  {i}: NULL")

if __name__ == "__main__":
    test_decimal128_cases()