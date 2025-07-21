#!/usr/bin/env python3
from e6data_python_connector.datainputstream import _binary_to_decimal128

# Test the binary value that should decode to 38 nines
binary_data = b'\xb4\xc4\xb3W\xa5y;\x85\xf6u\xdd\xc0\x00\x00\x00\x02'
result = _binary_to_decimal128(binary_data)

print(f'Binary data: {binary_data.hex()}')
print(f'Result: {result}')
print(f'Expected: 99999999999999999999999999999999999999')
print(f'Match: {str(result) == "99999999999999999999999999999999999999"}')