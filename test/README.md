# Test Directory

This directory contains all test files for the e6data-python-connector project.

## Test Files

### Core Tests
- **`tests.py`** - Main test suite with comprehensive e6data connector tests
- **`tests_grpc.py`** - gRPC-specific tests including query execution, caching, and explain functionality

### DECIMAL128 Tests
- **`test_decimal128_parsing.py`** - Comprehensive test suite for DECIMAL128 data type parsing
- **`validate_decimal128.py`** - Validation script to verify DECIMAL128 implementation
- **`verify_decimal_fix.py`** - Verification script for the DECIMAL128 fix
- **`test_fix.py`** - Simple test for invalid binary data handling fix

### Utility Tests
- **`check_decimal_errors.py`** - Utility script to check Decimal module exceptions

## Running Tests

### Prerequisites
Set the following environment variables:
- `ENGINE_IP`: IP address of the e6data engine
- `DB_NAME`: Database name
- `EMAIL`: Your e6data email
- `PASSWORD`: Access token from e6data console
- `CATALOG`: Catalog name
- `PORT`: Port number (default: 80)

### Running Individual Tests

```bash
# Run main test suite
python -m unittest test.tests

# Run gRPC tests
python -m unittest test.tests_grpc

# Run DECIMAL128 tests
python test/test_decimal128_parsing.py

# Run validation
python test/validate_decimal128.py

# Run verification
python test/verify_decimal_fix.py
```

### Running All Tests

```bash
# Run all unittest-based tests
python -m unittest test.tests test.tests_grpc

# Run all standalone tests
python test/test_decimal128_parsing.py
python test/validate_decimal128.py
python test/verify_decimal_fix.py
```

## Test Coverage

The test suite covers:
- Connection management and authentication
- Query execution (simple, parameterized, complex)
- Data fetching (fetchall, fetchone, fetchmany)
- Schema information retrieval
- Database catalog operations
- CSV export functionality
- Multiple cursor support
- Query cancellation
- DECIMAL128 data type parsing
- Error handling and edge cases
- gRPC communication
- Caching mechanisms
- Query explanation and analysis

## Notes

- Tests require network access to e6data clusters
- Port 80 must be open for inbound connections
- Tests require a running e6data cluster with valid credentials
- DECIMAL128 tests use mock data and don't require cluster access