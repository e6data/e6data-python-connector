#!/usr/bin/env python3
"""Move test files to test directory."""
import os
import shutil

# Create test directory
test_dir = ""
if not os.path.exists(test_dir):
    os.makedirs(test_dir)
    print(f"Created directory: {test_dir}")

# List of test files to move
test_files = [
    "tests.py",
    "tests_grpc.py",
    "test_decimal128_parsing.py",
    "test_fix.py",
    "validate_decimal128.py",
    "verify_decimal_fix.py",
    "check_decimal_errors.py",
    # These files from previous session might exist
    "test_cluster_manager_strategy.py",
    "test_cluster_manager_efficiency.py",
    "test_cluster_manager_none_strategy.py",
    "test_multiprocessing_fix.py",
    "test_strategy_persistence_fix.py"
]

# Move files
moved_files = []
for file in test_files:
    if os.path.exists(file):
        dest = os.path.join(test_dir, file)
        shutil.move(file, dest)
        moved_files.append(file)
        print(f"Moved: {file} -> {dest}")

# Create __init__.py in test directory
init_file = os.path.join(test_dir, "__init__.py")
if not os.path.exists(init_file):
    with open(init_file, 'w') as f:
        f.write('"""Test package for e6data-python-connector."""\n')
    print(f"Created: {init_file}")

print(f"\n✅ Moved {len(moved_files)} test files to {test_dir}/ directory")
print("\nMoved files:")
for file in moved_files:
    print(f"  - {file}")