# e6data Python Connector

![version](https://img.shields.io/badge/version-2.3.12-blue.svg)

## Introduction

The e6data Connector for Python provides an interface for writing Python applications that can connect to e6data and perform operations. It includes automatic support for blue-green deployments, ensuring seamless failover during server updates without query interruption.

### Dependencies
Make sure to install below dependencies and wheel before install e6data-python-connector.
```shell
# Amazon Linux / CentOS dependencies
yum install python3-devel gcc-c++ -y

# Ubuntu/Debian dependencies
apt install python3-dev g++ -y

# Windows dependencies
# Install Visual C++ Build Tools from:
# https://visualstudio.microsoft.com/visual-cpp-build-tools/
# Select the "Desktop Development with C++" option during installation.

# Pip dependencies
pip install wheel
```


To install the Python package, use the command below:
```shell
pip install --no-cache-dir e6data-python-connector
```
### Prerequisites

* Open Inbound Port 80 in the Engine Cluster.
* Limit access to Port 80 according to your organizational security policy. Public access is not encouraged.
* Access Token generated in the e6data console.

### Create a Connection

Use your e6data Email ID as the username and your access token as the password.

```python
from e6data_python_connector import Connection
# For connection pooling (recommended for concurrent operations)
from e6data_python_connector import ConnectionPool

username = '<username>'  # Your e6data Email ID.
password = '<password>'  # Access Token generated in the e6data console.

host = '<host>'  # IP address or hostname of the cluster to be used.
database = '<database>'  # Database to perform the query on.
port = 80  # Port of the e6data engine.
catalog_name = '<catalog_name>'

# Single connection (for simple, single-threaded use)
conn = Connection(
    host=host,
    port=port,
    username=username,
    database=database,
    password=password
)

# Or use connection pool (for concurrent/multi-threaded use)
pool = ConnectionPool(
    min_size=2,
    max_size=10,
    host=host,
    port=port,
    username=username,
    database=database,
    password=password
)
```

#### Connection Parameters

The `Connection` class supports the following parameters:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `host` | str | Yes | - | IP address or hostname of the e6data cluster |
| `port` | int | Yes | - | Port of the e6data engine (typically 80) |
| `username` | str | Yes | - | Your e6data Email ID |
| `password` | str | Yes | - | Access Token generated in the e6data console |
| `database` | str | No | None | Database to perform queries on |
| `catalog` | str | No | None | Catalog name |
| `cluster_name` | str | No | None | Name of the cluster for cluster-specific operations |
| `secure` | bool | No | False | Enable SSL/TLS for secure connections |
| `ssl_cert` | str/bytes | No | None | Path to CA certificate (PEM) or certificate bytes for HTTPS connections |
| `auto_resume` | bool | No | True | Automatically resume cluster if suspended |
| `grpc_options` | dict | No | None | Additional gRPC configuration options |
| `debug` | bool | No | False | Enable debug logging for troubleshooting |
| `require_fastbinary` | bool | No | True | Require fastbinary module for Thrift deserialization. Set to False to use pure Python implementation if system dependencies cannot be installed |

#### Secure Connection Example

To establish a secure connection using SSL/TLS:

```python
conn = Connection(
    host=host,
    port=443,  # Typically 443 for secure connections
    username=username,
    password=password,
    database=database,
    cluster_name='production-cluster',
    secure=True  # Enable SSL/TLS
)
```

#### Cluster-Specific Connection

When working with multiple clusters, specify the cluster name:

```python
conn = Connection(
    host=host,
    port=port,
    username=username,
    password=password,
    database=database,
    cluster_name='analytics-cluster-01',  # Specify cluster name
    secure=True
)
```

#### HTTPS Connection with HAProxy

When connecting through HAProxy with HTTPS, you can provide a custom CA certificate for secure connections. The `ssl_cert` parameter accepts either a file path to a PEM certificate or the certificate content as bytes.

**Using a CA certificate file path:**

```python
conn = Connection(
    host=host,
    port=443,
    username=username,
    password=password,
    database=database,
    secure=True,
    ssl_cert='/path/to/ca-cert.pem'  # Path to your CA certificate
)
```

**Reading certificate content as bytes:**

```python
# Read certificate file and pass as bytes
with open('/path/to/ca-cert.pem', 'rb') as cert_file:
    cert_data = cert_file.read()

conn = Connection(
    host=host,
    port=443,
    username=username,
    password=password,
    database=database,
    secure=True,
    ssl_cert=cert_data  # Certificate content as bytes
)
```

**Using system CA bundle for publicly signed certificates:**

```python
# When ssl_cert is None, system default CA bundle is used
conn = Connection(
    host=host,
    port=443,
    username=username,
    password=password,
    database=database,
    secure=True  # Uses system CA bundle by default
)
```

**Connection pooling with custom CA certificate:**

```python
pool = ConnectionPool(
    min_size=2,
    max_size=10,
    host=host,
    port=443,
    username=username,
    password=password,
    database=database,
    secure=True,
    ssl_cert='/path/to/ca-cert.pem'  # Custom CA certificate for pool connections
)
```

#### Handling Missing System Dependencies

The e6data connector uses the `fastbinary` module (from Apache Thrift) for optimal performance when deserializing data. This module requires system-level dependencies (`python3-devel` and `gcc-c++`) to be installed.

**Default Behavior (Recommended):**
By default, the connector requires `fastbinary` to be available. If it's not found, the connection will fail immediately with a clear error message:

```python
conn = Connection(
    host=host,
    port=port,
    username=username,
    password=password,
    database=database
)
# Raises exception if fastbinary is not available
```

**Fallback to Pure Python:**
If you cannot install system dependencies (e.g., in restricted environments, serverless platforms, or containers without build tools), you can disable the `fastbinary` requirement. The connector will fall back to a pure Python implementation with a performance penalty:

```python
conn = Connection(
    host=host,
    port=port,
    username=username,
    password=password,
    database=database,
    require_fastbinary=False  # Allow operation without fastbinary
)
# Logs warning but continues with pure Python implementation
```

**When to use `require_fastbinary=False`:**
- Running in AWS Lambda or other serverless environments
- Docker containers built without compilation tools
- Restricted environments where system packages cannot be installed
- Development/testing environments where performance is not critical

**Performance Impact:**
- With `fastbinary`: Optimal performance for data deserialization
- Without `fastbinary` (pure Python): ~2-3x slower deserialization, but otherwise fully functional

**Note:** It's strongly recommended to install system dependencies when possible for best performance. The `require_fastbinary=False` option should only be used when system dependencies cannot be installed.

### Perform a Queries & Get Results

```python

query = 'SELECT * FROM <TABLE_NAME>'  # Replace with the query.

cursor = conn.cursor(catalog_name=catalog_name)
query_id = cursor.execute(query)  # The execute function returns a unique query ID, which can be use to abort the query.
all_records = cursor.fetchall()
for row in all_records:
   print(row)
```

To fetch all the records:
```python
records = cursor.fetchall()
```

To fetch one record:
```python
record = cursor.fetchone()
```

To fetch limited records:
```python
limit = 500
records = cursor.fetchmany(limit)
```

To fetch all the records in buffer to reduce memory consumption:
```python
records_iterator = cursor.fetchall_buffer()  # Returns generator
for item in records_iterator:
    print(item)
```

To get the execution plan after query execution:
```python
import json
explain_response = cursor.explain_analyse()
query_planner = json.loads(explain_response.get('planner'))
```

To abort a running query:
```python
query_id = '<query_id>'  # query id from execute function response.
cursor.cancel(query_id)
```

Switch database in an existing connection:
```python
database = '<new_database_name>'  # Replace with the new database.
cursor = conn.cursor(database, catalog_name)
```

### Get Query Time Metrics
```python
import json
query = 'SELECT * FROM <TABLE_NAME>'

cursor = conn.cursor(catalog_name)
query_id = cursor.execute(query)  # execute function returns query id, can be use for aborting the query.
all_records = cursor.fetchall()
explain_response = cursor.explain_analyse()
query_planner = json.loads(explain_response.get('planner'))

execution_time = query_planner.get("total_query_time")  # In milliseconds
queue_time = query_planner.get("executionQueueingTime")  # In milliseconds
parsing_time = query_planner.get("parsingTime")  # In milliseconds
row_count = query_planner.rowcount
```

### Get Schema - a list of Databases, Tables or Columns
The following code returns a dictionary of all databases, all tables and all columns connected to the cluster currently in use.
This function can be used without passing database name to get list of all databases.

```python
databases = conn.get_schema_names()  # To get list of databases.
print(databases)

database = '<database_name>'  # Replace with actual database name.
tables = conn.get_tables(database=database)  # To get list of tables from a database.
print(tables)

table_name = '<table_name>'  # Replace with actual table name.
columns = conn.get_tables(database=database, table=table_name)  # To get the list of columns from a table.
columns_with_type = list()
"""
Getting the column name and type.
"""
for column in columns:
   columns_with_type.append(dict(column_name=column.fieldName, column_type=column.fieldType))
print(columns_with_type)
```

### Code Hygiene
It is recommended to clear the cursor, close the cursor and close the connection after running a function as a best practice. 
This enhances performance by clearing old data from memory.

```python
cursor.clear() # Not needed when aborting a query
cursor.close()
conn.close()
```

### Code Example
The following code is an example which combines a few functions described above.
```python
from e6data_python_connector import Connection
import json

username = '<username>'  # Your e6data Email ID.
password = '<password>'  # Access Token generated in the e6data console.

host = '<host>'  # IP address or hostname of the cluster to be used.
database = '<database>'  # # Database to perform the query on.
port = 80  # Port of the e6data engine.

sql_query = 'SELECT * FROM <TABLE_NAME>'  # Replace with the actual query.

catalog_name = '<catalog_name>'  # Replace with the actual catalog name.

conn = Connection(
    host=host,
    port=port,
    username=username,
    database=database,
    password=password
)

cursor = conn.cursor(db_name=database, catalog_name=catalog_name)
query_id = cursor.execute(sql_query)
all_records = cursor.fetchall()
explain_response = cursor.explain_analyse()
planner_result = json.loads(explain_response.get('planner'))
execution_time = planner_result.get("total_query_time") / 1000  # Converting into seconds.
row_count = cursor.rowcount
columns = [col[0] for col in cursor.description]  # Get the column names and merge them with the results.
results = []
for row in all_records:
   row = dict(zip(columns, row))
   results.append(row)
   print(row)
print('Total row count {}, Execution Time (seconds): {}'.format(row_count, execution_time))
cursor.clear()
cursor.close()
conn.close()
```

## Zero Downtime Deployment

### 🚀 Zero Downtime Features

The e6data Python Connector provides **automatic zero downtime deployment** support through intelligent blue-green deployment strategy management:

#### ✅ **No Code Changes Required**
Your existing applications automatically benefit from zero downtime deployment without any modifications:

```python
# Your existing code works exactly the same
from e6data_python_connector import Connection

conn = Connection(
    host='your-host',
    port=80,
    username='your-email',
    password='your-token',
    database='your-database'
)

cursor = conn.cursor()
cursor.execute("SELECT * FROM your_table")
results = cursor.fetchall()
```

#### 🔄 **Automatic Strategy Detection**
- Detects active deployment strategy (blue/green) on connection
- Caches strategy information for optimal performance
- Automatically switches strategies when deployments occur

#### 🛡️ **Seamless Query Protection**
- **Running queries continue uninterrupted** during deployments
- New queries automatically use the new deployment strategy
- Graceful transitions ensure no query loss or failures

#### ⚡ **Performance Optimized**
- **< 100ms** additional latency on first connection (one-time cost)
- **0ms overhead** for 95% of queries (cached strategy)
- **< 1KB** additional memory usage per connection

#### 🔧 **Thread & Process Safe**
- Full support for multi-threaded applications
- Process-safe shared memory management
- Concurrent query execution without conflicts

### Advanced Configuration (Optional)

For enhanced monitoring and performance tuning:

```python
# Enhanced gRPC configuration for zero downtime
grpc_options = {
    'keepalive_timeout_ms': 60000,      # 1 minute keepalive timeout
    'keepalive_time_ms': 30000,         # 30 seconds keepalive interval
    'max_receive_message_length': 100 * 1024 * 1024,  # 100MB
    'max_send_message_length': 100 * 1024 * 1024,     # 100MB
}

conn = Connection(
    host='your-host',
    port=80,
    username='your-email',
    password='your-token',
    database='your-database',
    grpc_options=grpc_options
)
```

### Environment Configuration

Configure zero downtime features using environment variables:

```bash
# Strategy cache timeout (default: 300 seconds)
export E6DATA_STRATEGY_CACHE_TIMEOUT=300

# Maximum retry attempts (default: 5)
export E6DATA_MAX_RETRY_ATTEMPTS=5

# Enable debug logging for strategy operations
export E6DATA_STRATEGY_LOG_LEVEL=INFO
```

### Testing Zero Downtime

Use the included mock server for testing and development:

```bash
# Terminal 1: Start mock server
python mock_grpc_server.py

# Terminal 2: Run test client
python test_mock_server.py

# Or use the convenience script
./run_mock_test.sh
```

### 📚 **Comprehensive Documentation**

Explore detailed documentation in the [`docs/zero-downtime/`](docs/zero-downtime/) directory:

- **[📋 Overview](docs/zero-downtime/README.md)** - Complete guide and feature overview
- **[🔧 API Reference](docs/zero-downtime/api-reference.md)** - Detailed API documentation
- **[🌊 Flow Documentation](docs/zero-downtime/flow-documentation.md)** - Process flows and diagrams
- **[💼 Business Logic](docs/zero-downtime/business-logic.md)** - Business rules and decisions
- **[🏗️ Architecture](docs/zero-downtime/architecture.md)** - System architecture and design
- **[⚙️ Configuration](docs/zero-downtime/configuration.md)** - Complete configuration guide
- **[🧪 Testing](docs/zero-downtime/testing.md)** - Testing strategies and tools
- **[🔍 Troubleshooting](docs/zero-downtime/troubleshooting.md)** - Common issues and solutions
- **[🚀 Migration Guide](docs/zero-downtime/migration-guide.md)** - Step-by-step migration instructions

### Key Benefits

| Feature | Benefit |
|---------|---------|
| **Zero Downtime** | Applications continue running during e6data deployments |
| **Automatic** | No code changes or manual intervention required |
| **Reliable** | Robust error handling and automatic recovery |
| **Fast** | Minimal performance impact with intelligent caching |
| **Safe** | Thread-safe and process-safe operation |
| **Monitored** | Comprehensive logging and monitoring capabilities |

### Migration

Existing applications automatically benefit from zero downtime deployment:

1. **Update connector**: `pip install --upgrade e6data-python-connector`
2. **No code changes**: Your existing code works without modifications
3. **Monitor**: Use enhanced logging to monitor strategy transitions
4. **Validate**: Test with your existing applications

For detailed migration instructions, see the [Migration Guide](docs/zero-downtime/migration-guide.md).

## Performance Optimization

### Memory Efficiency
- Use `fetchall_buffer()` for memory-efficient large result sets
- Automatic cleanup of query-strategy mappings
- Bounded memory usage with TTL-based caching

### Network Performance
- Configure gRPC options for optimal network performance
- Intelligent keepalive settings for connection stability
- Message size optimization for large queries

### Connection Management

#### Connection Pooling

The e6data Python connector now includes a built-in connection pool for efficient connection management and reuse across multiple threads. The `ConnectionPool` class provides:

- **Thread-safe connection reuse**: Each thread automatically reuses its assigned connection
- **Automatic lifecycle management**: Handles connection creation, health checks, and cleanup
- **Overflow connections**: Creates temporary connections when pool is exhausted
- **Connection health monitoring**: Automatic detection and replacement of broken connections
- **Statistics tracking**: Monitor pool usage and performance

##### Basic Connection Pool Usage

```python
from e6data_python_connector import ConnectionPool

# Create a connection pool
pool = ConnectionPool(
    min_size=2,        # Minimum connections to maintain
    max_size=10,       # Maximum connections in pool
    max_overflow=5,    # Additional temporary connections allowed
    timeout=30.0,      # Timeout for getting connection (seconds)
    recycle=3600,      # Maximum age before recycling (seconds)
    debug=False,       # Enable debug logging
    pre_ping=True,     # Check connection health before use
    # Connection parameters
    host=host,
    port=port,
    username=username,
    password=password,
    database=database,
    catalog=catalog_name,
    cluster_name=cluster_name,
    secure=True
)

# Get connection and execute query
conn = pool.get_connection()
cursor = conn.cursor()
cursor.execute("SELECT * FROM table")
results = cursor.fetchall()

# Return connection to pool (important!)
pool.return_connection(conn)

# Clean up when done
pool.close_all()
```

##### Using Context Manager (Recommended)

The context manager pattern ensures connections are automatically returned to the pool:

```python
from e6data_python_connector import ConnectionPool

pool = ConnectionPool(
    min_size=2,
    max_size=10,
    host=host,
    port=port,
    username=username,
    password=password,
    database=database
)

# Connection automatically returned to pool after use
with pool.get_connection_context() as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM table")
    results = cursor.fetchall()
    print(results)
```

##### Concurrent Query Execution

Connection pooling is especially beneficial for concurrent query execution:

```python
import concurrent.futures
from e6data_python_connector import ConnectionPool

def execute_query(pool, query_id, query):
    """Execute a query using a pooled connection."""
    # Each thread will reuse its assigned connection
    conn = pool.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        results = cursor.fetchall()
        return f"Query {query_id}: {len(results)} rows"
    finally:
        pool.return_connection(conn)

# Create pool
pool = ConnectionPool(
    min_size=3,
    max_size=10,
    host=host,
    port=port,
    username=username,
    password=password,
    database=database
)

# Execute multiple queries concurrently
queries = [
    "SELECT COUNT(*) FROM table1",
    "SELECT AVG(value) FROM table2",
    "SELECT MAX(date) FROM table3"
]

with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    futures = [
        executor.submit(execute_query, pool, i, query)
        for i, query in enumerate(queries)
    ]
    
    for future in concurrent.futures.as_completed(futures):
        print(future.result())

# Clean up
pool.close_all()
```

##### Connection Pool Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `min_size` | int | 2 | Minimum number of connections to maintain |
| `max_size` | int | 10 | Maximum number of connections in pool |
| `max_overflow` | int | 5 | Additional temporary connections allowed |
| `timeout` | float | 30.0 | Timeout for getting connection (seconds) |
| `recycle` | int | 3600 | Maximum connection age before recycling (seconds) |
| `debug` | bool | False | Enable debug logging for pool operations |
| `pre_ping` | bool | True | Check connection health before returning from pool |

##### Monitoring Pool Statistics

```python
# Get pool statistics
stats = pool.get_statistics()
print(f"Active connections: {stats['active_connections']}")
print(f"Idle connections: {stats['idle_connections']}")
print(f"Total requests: {stats['total_requests']}")
print(f"Failed connections: {stats['failed_connections']}")
```

##### When to Use Connection Pooling

Connection pooling is recommended when:
- Executing multiple queries concurrently
- Building web applications or APIs
- Running batch processing jobs
- Reducing connection overhead
- Improving application performance

##### Direct Connection Usage (Without Pool)

For simple, single-threaded applications, you can still use direct connections:

```python
from e6data_python_connector import Connection

conn = Connection(
    host=host,
    port=port,
    username=username,
    password=password,
    database=database
)

cursor = conn.cursor()
cursor.execute("SELECT * FROM table")
results = cursor.fetchall()
conn.close()
```

#### Additional Connection Management Features
- Automatic connection health monitoring
- Graceful connection recovery and retry logic
- Blue-green deployment support with automatic failover

## Debugging and Troubleshooting

### Enable Debug Mode

Enable comprehensive debugging to troubleshoot connection and query issues:

```python
from e6data_python_connector import Connection

conn = Connection(
    host=host,
    port=port,
    username=username,
    password=password,
    database=database,
    debug=True  # Enable debug logging
)
```

When `debug=True`, the following features are enabled:
- Python logging at DEBUG level for all operations
- Blue-green strategy transition logging
- Connection lifecycle logging
- Query execution detailed logging

### gRPC Network Tracing

For low-level gRPC network debugging (HTTP/2 frames, TCP events), set environment variables **before** running your Python script:

```bash
# Enable gRPC network tracing
export GRPC_VERBOSITY=DEBUG
export GRPC_TRACE=client_channel,http2

# For comprehensive tracing
export GRPC_TRACE=api,call_error,channel,client_channel,connectivity_state,http,http2_stream,tcp,transport_security

# Run your script
python your_script.py
```

**Note**: These environment variables must be set before Python starts, as the gRPC C++ core reads them at module import time.

### Common Issues and Solutions

| Issue | Solution |
|-------|----------|
| Connection timeout | Check network connectivity, firewall rules, and ensure port 80/443 is open |
| Authentication failure | Verify username (email) and access token are correct |
| 503 Service Unavailable | Cluster may be suspended; enable `auto_resume=True` |
| 456 Strategy Error | Automatic blue-green failover will handle this |
| Memory issues with large results | Use `fetchall_buffer()` instead of `fetchall()` |
| gRPC message size errors | Configure `grpc_options` with appropriate message size limits |
| fastbinary import error | Install system dependencies (`python3-devel`, `gcc-c++`) or set `require_fastbinary=False` |

See [TECH_DOC.md](TECH_DOC.md) for detailed technical documentation.
