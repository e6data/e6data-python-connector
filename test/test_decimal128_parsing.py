#!/usr/bin/env python3
"""
Test script to verify DECIMAL128 parsing support is working correctly.
"""

import sys
from decimal import Decimal
from unittest.mock import Mock

# Add the project root to the path
sys.path.insert(0, '..')

from e6data_python_connector.datainputstream import get_column_from_chunk, _binary_to_decimal128
from e6data_python_connector.e6x_vector.ttypes import Vector, VectorType


def test_binary_to_decimal128():
    """Test the _binary_to_decimal128 helper function."""
    
    print("=== Testing _binary_to_decimal128 Helper Function ===\n")
    
    # Test 1: String representation as bytes
    print("1. Testing string representation as bytes...")
    test_decimal_str = "123.456"
    binary_data = test_decimal_str.encode('utf-8')
    result = _binary_to_decimal128(binary_data)
    expected = Decimal("123.456")
    assert result == expected, f"Expected {expected}, got {result}"
    print(f"✓ Successfully parsed: {test_decimal_str} -> {result}")
    
    # Test 2: String representation directly
    print("\n2. Testing string representation directly...")
    test_decimal_str = "999.999"
    result = _binary_to_decimal128(test_decimal_str)
    expected = Decimal("999.999")
    assert result == expected, f"Expected {expected}, got {result}"
    print(f"✓ Successfully parsed: {test_decimal_str} -> {result}")
    
    # Test 3: Large decimal number
    print("\n3. Testing large decimal number...")
    test_decimal_str = "12345678901234567890.123456789012345678"
    binary_data = test_decimal_str.encode('utf-8')
    result = _binary_to_decimal128(binary_data)
    expected = Decimal("12345678901234567890.123456789012345678")
    assert result == expected, f"Expected {expected}, got {result}"
    print(f"✓ Successfully parsed: {test_decimal_str} -> {result}")
    
    # Test 4: Negative decimal
    print("\n4. Testing negative decimal...")
    test_decimal_str = "-456.789"
    binary_data = test_decimal_str.encode('utf-8')
    result = _binary_to_decimal128(binary_data)
    expected = Decimal("-456.789")
    assert result == expected, f"Expected {expected}, got {result}"
    print(f"✓ Successfully parsed: {test_decimal_str} -> {result}")
    
    # Test 5: Zero
    print("\n5. Testing zero...")
    test_decimal_str = "0"
    binary_data = test_decimal_str.encode('utf-8')
    result = _binary_to_decimal128(binary_data)
    expected = Decimal("0")
    assert result == expected, f"Expected {expected}, got {result}"
    print(f"✓ Successfully parsed: {test_decimal_str} -> {result}")
    
    # Test 6: None/empty input
    print("\n6. Testing None/empty input...")
    result = _binary_to_decimal128(None)
    assert result is None, f"Expected None, got {result}"
    print("✓ Successfully handled None input")
    
    result = _binary_to_decimal128(b"")
    assert result is None, f"Expected None, got {result}"
    print("✓ Successfully handled empty bytes input")
    
    print("\n=== _binary_to_decimal128 Helper Function Tests Complete ===")
    return True


def test_decimal128_vector_parsing():
    """Test DECIMAL128 vector parsing with mock data."""
    
    print("\n=== Testing DECIMAL128 Vector Parsing ===\n")
    
    # Test 1: Non-constant vector with multiple decimal values
    print("1. Testing non-constant DECIMAL128 vector...")
    
    # Create mock vector
    vector = Mock(spec=Vector)
    vector.size = 3
    vector.vectorType = VectorType.DECIMAL128
    vector.isConstantVector = False
    vector.nullSet = [False, False, True]  # Third value is null
    
    # Mock the data structure
    vector.data = Mock()
    vector.data.decimal128Data = Mock()
    vector.data.decimal128Data.data = [
        b"123.456",    # First value
        b"-789.012",   # Second value
        b"0"           # Third value (but will be null)
    ]
    
    # Parse the vector
    result = get_column_from_chunk(vector)
    
    # Verify results
    expected = [Decimal("123.456"), Decimal("-789.012"), None]
    assert len(result) == 3, f"Expected 3 values, got {len(result)}"
    assert result[0] == expected[0], f"Expected {expected[0]}, got {result[0]}"
    assert result[1] == expected[1], f"Expected {expected[1]}, got {result[1]}"
    assert result[2] is None, f"Expected None, got {result[2]}"
    
    print(f"✓ Successfully parsed non-constant vector: {result}")
    
    # Test 2: Constant vector with single decimal value
    print("\n2. Testing constant DECIMAL128 vector...")
    
    # Create mock constant vector
    vector = Mock(spec=Vector)
    vector.size = 4
    vector.vectorType = VectorType.DECIMAL128
    vector.isConstantVector = True
    vector.nullSet = [False]  # Constant vector has single null flag
    
    # Mock the constant data structure
    vector.data = Mock()
    vector.data.numericDecimal128ConstantData = Mock()
    vector.data.numericDecimal128ConstantData.data = b"999.999"
    
    # Parse the vector
    result = get_column_from_chunk(vector)
    
    # Verify results - all values should be the same
    expected_value = Decimal("999.999")
    assert len(result) == 4, f"Expected 4 values, got {len(result)}"
    for i, value in enumerate(result):
        assert value == expected_value, f"Expected {expected_value} at index {i}, got {value}"
    
    print(f"✓ Successfully parsed constant vector: {result}")
    
    # Test 3: Constant vector with null values
    print("\n3. Testing constant DECIMAL128 vector with null...")
    
    # Create mock constant vector with null
    vector = Mock(spec=Vector)
    vector.size = 2
    vector.vectorType = VectorType.DECIMAL128
    vector.isConstantVector = True
    vector.nullSet = [True]  # Constant vector is null
    
    # Mock the constant data structure (won't be used due to null)
    vector.data = Mock()
    vector.data.numericDecimal128ConstantData = Mock()
    vector.data.numericDecimal128ConstantData.data = b"123.456"
    
    # Parse the vector
    result = get_column_from_chunk(vector)
    
    # Verify results - all values should be null
    assert len(result) == 2, f"Expected 2 values, got {len(result)}"
    assert result[0] is None, f"Expected None at index 0, got {result[0]}"
    assert result[1] is None, f"Expected None at index 1, got {result[1]}"
    
    print(f"✓ Successfully parsed constant null vector: {result}")
    
    print("\n=== DECIMAL128 Vector Parsing Tests Complete ===")
    return True


def test_decimal128_edge_cases():
    """Test edge cases for DECIMAL128 parsing."""
    
    print("\n=== Testing DECIMAL128 Edge Cases ===\n")
    
    # Test 1: Scientific notation
    print("1. Testing scientific notation...")
    test_decimal_str = "1.23E+10"
    binary_data = test_decimal_str.encode('utf-8')
    result = _binary_to_decimal128(binary_data)
    expected = Decimal("1.23E+10")
    assert result == expected, f"Expected {expected}, got {result}"
    print(f"✓ Successfully parsed scientific notation: {test_decimal_str} -> {result}")
    
    # Test 2: Very small number
    print("\n2. Testing very small number...")
    test_decimal_str = "0.000000000000000001"
    binary_data = test_decimal_str.encode('utf-8')
    result = _binary_to_decimal128(binary_data)
    expected = Decimal("0.000000000000000001")
    assert result == expected, f"Expected {expected}, got {result}"
    print(f"✓ Successfully parsed small number: {test_decimal_str} -> {result}")
    
    # Test 3: Integer without decimal point
    print("\n3. Testing integer without decimal point...")
    test_decimal_str = "12345"
    binary_data = test_decimal_str.encode('utf-8')
    result = _binary_to_decimal128(binary_data)
    expected = Decimal("12345")
    assert result == expected, f"Expected {expected}, got {result}"
    print(f"✓ Successfully parsed integer: {test_decimal_str} -> {result}")
    
    # Test 4: Invalid binary data (should gracefully handle)
    print("\n4. Testing invalid binary data...")
    invalid_binary = b"\x00\x01\x02\x03"  # Random bytes
    result = _binary_to_decimal128(invalid_binary)
    # Should return Decimal('0') as fallback
    assert result == Decimal('0'), f"Expected Decimal('0'), got {result}"
    print("✓ Successfully handled invalid binary data with fallback")
    
    print("\n=== DECIMAL128 Edge Cases Tests Complete ===")
    return True


def test_integration():
    """Test integration with existing type checking."""
    
    print("\n=== Testing Integration ===\n")
    
    # Verify that VectorType.DECIMAL128 is defined
    print("1. Testing VectorType.DECIMAL128 constant...")
    assert hasattr(VectorType, 'DECIMAL128'), "VectorType.DECIMAL128 should be defined"
    assert VectorType.DECIMAL128 == 16, f"Expected DECIMAL128 = 16, got {VectorType.DECIMAL128}"
    print(f"✓ VectorType.DECIMAL128 = {VectorType.DECIMAL128}")
    
    # Test that Decimal import works
    print("\n2. Testing Decimal import...")
    test_decimal = Decimal("123.456")
    assert isinstance(test_decimal, Decimal), "Should be able to create Decimal instances"
    print(f"✓ Decimal import working: {test_decimal}")
    
    print("\n=== Integration Tests Complete ===")
    return True


def main():
    """Run all tests."""
    try:
        test_binary_to_decimal128()
        test_decimal128_vector_parsing()
        test_decimal128_edge_cases()
        test_integration()
        print("\n🎉 All DECIMAL128 parsing tests passed!")
        return True
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)