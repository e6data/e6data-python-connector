#!/usr/bin/env python3
"""Clean up original test files after moving to test directory."""
import os

# List of files to remove from root directory
files_to_remove = [
    "tests.py",
    "tests_grpc.py",
    "test_decimal128_parsing.py",
    "test_fix.py",
    "validate_decimal128.py",
    "verify_decimal_fix.py",
    "check_decimal_errors.py",
    "move_tests.py"
]

print("Cleaning up original test files...\n")

removed_files = []
for file in files_to_remove:
    if os.path.exists(file):
        os.remove(file)
        removed_files.append(file)
        print(f"Removed: {file}")

print(f"\n✅ Cleaned up {len(removed_files)} test files from root directory")
print("\nRemoved files:")
for file in removed_files:
    print(f"  - {file}")

print(f"\n📁 All test files are now in the test/ directory")