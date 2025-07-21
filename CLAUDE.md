# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the e6data Python Connector - a DB-API 2.0 compliant database connector for the e6data distributed SQL Engine. The connector uses gRPC for communication with e6data clusters and provides SQLAlchemy dialect support.

### Key Features
- DB-API 2.0 compliant interface
- gRPC-based communication with SSL/TLS support
- SQLAlchemy dialect integration
- Blue-green deployment strategy support with automatic failover
- Thread-safe and process-safe operation
- Automatic retry and re-authentication logic

## Common Development Commands

### Building and Installing
```bash
# Install development dependencies
pip install -r requirements.txt

# Install the package in development mode
pip install -e .

# Build distribution packages
python setup.py sdist bdist_wheel

# Upload to PyPI (requires credentials)
twine upload dist/*
```

### Running Tests
```bash
# Run tests using unittest (requires environment variables)
# Set these environment variables first:
# - ENGINE_IP: IP address of the e6data engine
# - DB_NAME: Database name
# - EMAIL: Your e6data email
# - PASSWORD: Access token from e6data console
# - CATALOG: Catalog name
# - PORT: Port number (default: 80)

# Run all tests
python -m unittest tests.py tests_grpc.py

# Run specific test file
python -m unittest tests.py
python -m unittest tests_grpc.py
```

### Protocol Buffer Compilation
```bash
# Install protobuf compiler
pip install grpcio-tools

# Regenerate gRPC code from proto files (if proto files change)
python -m grpc_tools.protoc -I. --python_out=e6data_python_connector/server --grpc_python_out=e6data_python_connector/server e6x_engine.proto
python -m grpc_tools.protoc -I. --python_out=e6data_python_connector/cluster_server --grpc_python_out=e6data_python_connector/cluster_server cluster.proto
```

### Testing Blue-Green Strategy
```bash
# Start mock server (in one terminal)
python mock_grpc_server.py

# Run test client (in another terminal)
python test_mock_server.py

# Or use the convenience script
./run_mock_test.sh
```

## Architecture Overview

### Core Components

1. **Connection Management (`e6data_grpc.py`)**
   - Main `Connection` class implementing DB-API 2.0 interface
   - Handles gRPC channel creation (secure/insecure)
   - Authentication using email/password (access token)
   - Connection pooling and retry logic

2. **Cursor Implementation (`e6data_grpc.py`)**
   - `GRPCCursor` class for query execution
   - Supports parameterized queries using `pyformat` style
   - Fetch operations: `fetchone()`, `fetchmany()`, `fetchall()`, `fetchall_buffer()`
   - Query analysis with `explain_analyse()`

3. **gRPC Services**
   - **Query Engine Service** (`server/`): Main query execution interface
   - **Cluster Service** (`cluster_server/`): Cluster management operations
   - Both use Protocol Buffers for message serialization

4. **SQLAlchemy Integration (`dialect.py`)**
   - Custom dialect registered as `e6data+e6data_python_connector`
   - Enables use with SQLAlchemy ORM and query builder

5. **Type System**
   - `typeId.py`: Type mapping between e6data and Python types
   - `date_time_utils.py`: Date/time handling utilities
   - `datainputstream.py`: Binary data deserialization

### Key Design Patterns

1. **Error Handling**: Automatic retry with re-authentication for gRPC errors
2. **Resource Management**: Proper cleanup with `clear()`, `close()` methods
3. **Memory Efficiency**: `fetchall_buffer()` returns generator for large datasets
4. **Security**: SSL/TLS support for secure connections
5. **Blue-Green Deployment**: 
   - Automatic strategy detection and switching
   - Graceful transitions without query interruption
   - Thread-safe and process-safe strategy caching
   - 456 error handling for strategy mismatches

### Configuration Options

The connector supports extensive gRPC configuration through `grpc_options`:
- Message size limits
- Keepalive settings
- Timeout configurations
- HTTP/2 ping settings

See TECH_DOC.md for detailed gRPC options documentation.

## Important Notes

- Always use environment variables for credentials in tests
- The connector requires network access to e6data clusters
- Port 80 must be open for inbound connections
- Tests require a running e6data cluster with valid credentials
- When modifying proto files, regenerate the Python code
- Follow DB-API 2.0 specification for any API changes
- Blue-green strategy is handled automatically - no code changes required
- All API responses now include optional `new_strategy` field
- Strategy transitions happen after query completion (on clear/cancel)

## Blue-Green Deployment Strategy

The connector automatically handles blue-green deployments:

1. **Initial Detection**: On first connection, tries both strategies
2. **Header Injection**: Adds "strategy" header to all gRPC requests
3. **Graceful Transition**: Current queries complete with old strategy
4. **Automatic Failover**: Handles 456 errors with strategy retry
5. **Caching**: 5-minute cache timeout for performance

See `BLUE_GREEN_STRATEGY.md` for detailed documentation.