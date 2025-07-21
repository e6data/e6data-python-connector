#!/usr/bin/env python3
"""
Test specifically for the user's binary value that was returning Decimal('0').
"""

import sys
import os
from decimal import Decimal

# Add the parent directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from e6data_python_connector.datainputstream import _binary_to_decimal128

def main():
    """Test the user's specific binary value."""
    
    print("=== Testing User's Binary Value ===\n")
    
    # The exact binary value from the user's report
    binary_data = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00%f\x80'
    
    print(f"Binary value: {binary_data}")
    print(f"Hex representation: {binary_data.hex()}")
    print(f"Length: {len(binary_data)} bytes")
    
    # Test the current implementation
    result = _binary_to_decimal128(binary_data)
    
    print(f"\nParsing result: {result}")
    print(f"Result type: {type(result)}")
    
    # Check if it's no longer Decimal('0')
    if result == Decimal('0'):
        print("❌ Still returning Decimal('0') - parsing not working correctly")
        return False
    else:
        print(f"✅ Successfully parsed as: {result}")
        return True
    
    # Additional analysis
    print(f"\nBinary analysis:")
    
    # Convert to integer for bit analysis
    bits = int.from_bytes(binary_data, byteorder='big')
    print(f"As 128-bit integer: {bits}")
    print(f"Hex: 0x{bits:032x}")
    
    # The meaningful data is in the last 4 bytes
    last_4_bytes = binary_data[-4:]
    last_4_int = int.from_bytes(last_4_bytes, byteorder='big')
    print(f"Last 4 bytes: {last_4_bytes.hex()} = {last_4_int}")
    
    # 0x256680 = 2385536 in decimal
    # This might represent different scaled values
    print(f"\nPossible interpretations of {last_4_int}:")
    
    scale_factors = [1, 10, 100, 1000, 10000, 100000, 1000000]
    for factor in scale_factors:
        scaled = last_4_int / factor
        print(f"  {last_4_int} / {factor} = {scaled}")
        if 0.1 <= scaled <= 100000:  # Reasonable range
            print(f"    ^ This seems reasonable")

if __name__ == "__main__":
    success = main()
    if success:
        print("\n🎉 Binary parsing fix appears to be working!")
    else:
        print("\n❌ Binary parsing still needs work")
    sys.exit(0 if success else 1)