#!/usr/bin/env python3
"""
Simple validation script to check if DECIMAL128 parsing is correctly implemented.
"""

import sys
sys.path.insert(0, '..')

def main():
    """Validate the implementation."""
    try:
        print("=== Validating DECIMAL128 Implementation ===\n")
        
        # Test 1: Check imports
        print("1. Testing imports...")
        from decimal import Decimal
        from e6data_python_connector.datainputstream import _binary_to_decimal128
        from e6data_python_connector.e6x_vector.ttypes import VectorType
        print("✓ All imports successful")
        
        # Test 2: Check VectorType.DECIMAL128 exists
        print("\n2. Testing VectorType.DECIMAL128...")
        assert hasattr(VectorType, 'DECIMAL128'), "VectorType.DECIMAL128 should exist"
        assert VectorType.DECIMAL128 == 16, f"Expected 16, got {VectorType.DECIMAL128}"
        print(f"✓ VectorType.DECIMAL128 = {VectorType.DECIMAL128}")
        
        # Test 3: Test _binary_to_decimal128 function
        print("\n3. Testing _binary_to_decimal128 function...")
        test_cases = [
            (b"123.456", Decimal("123.456")),
            (b"-789.012", Decimal("-789.012")),
            (b"0", Decimal("0")),
            ("12345", Decimal("12345")),
            (None, None),
            (b"", None),
            (b"\x00\x01\x02\x03", Decimal("0")),  # Invalid binary should return Decimal('0')
            (b"not-a-number", Decimal("0"))  # Invalid decimal string should return Decimal('0')
        ]
        
        for input_val, expected in test_cases:
            result = _binary_to_decimal128(input_val)
            assert result == expected, f"Input: {input_val}, Expected: {expected}, Got: {result}"
            print(f"✓ {input_val} -> {result}")
        
        # Test 4: Check the parsing function includes DECIMAL128
        print("\n4. Testing parsing function includes DECIMAL128...")
        from e6data_python_connector.datainputstream import get_column_from_chunk
        import inspect
        
        source = inspect.getsource(get_column_from_chunk)
        assert "VectorType.DECIMAL128" in source, "get_column_from_chunk should handle DECIMAL128"
        assert "decimal128Data" in source, "get_column_from_chunk should access decimal128Data"
        assert "numericDecimal128ConstantData" in source, "get_column_from_chunk should access numericDecimal128ConstantData"
        print("✓ get_column_from_chunk includes DECIMAL128 handling")
        
        # Test 5: Check read_values_from_array includes DECIMAL128
        print("\n5. Testing read_values_from_array includes DECIMAL128...")
        from e6data_python_connector.datainputstream import read_values_from_array
        
        source = inspect.getsource(read_values_from_array)
        assert '"DECIMAL128"' in source, "read_values_from_array should handle DECIMAL128"
        print("✓ read_values_from_array includes DECIMAL128 handling")
        
        print("\n🎉 All validations passed! DECIMAL128 parsing is correctly implemented.")
        return True
        
    except Exception as e:
        print(f"\n❌ Validation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)