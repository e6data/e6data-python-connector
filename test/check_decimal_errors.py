#!/usr/bin/env python3
"""Check what exceptions Decimal raises."""
from decimal import Decimal
import decimal

print("Decimal module exceptions:")
for attr in dir(decimal):
    if "Error" in attr or "Exception" in attr:
        print(f"  - {attr}")

print("\nTrying to create invalid Decimal:")
try:
    result = Decimal("not-a-number")
except Exception as e:
    print(f"Exception type: {type(e)}")
    print(f"Exception: {e}")
    print(f"Module: {type(e).__module__}")

print("\nTrying another invalid case:")
try:
    result = Decimal("\x00\x01\x02\x03")
except Exception as e:
    print(f"Exception type: {type(e)}")
    print(f"Exception: {e}")
    print(f"Module: {type(e).__module__}")