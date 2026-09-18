# e6data Python Connector

Package version and extras are defined in `setup.py`.

## Introduction

The e6data Connector for Python provides an interface for writing Python applications that can connect to e6data and perform operations. It includes routing support for blue-green deployments. Active query handles remain tied to the engine that accepted them; failover does not guarantee uninterrupted results.

## Optional native asyncio API

This branch adds native async connection, cursor, pooling and SQLAlchemy support for Python 3.11+. Release qualification remains incomplete. Install this branch's built package with `[async]` or `[async-sqlalchemy]`; these instructions do not assert that the feature is published.

```python
from e6data_python_connector.aio import AsyncConnection

async def query(config, sql):
    async with AsyncConnection(**config) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(sql)
            return await cursor.fetchall()
```

`config` is application-supplied connection configuration. OAuth requires verified TLS. Native `fetchone()` preserves the one-row outer list, while SQLAlchemy `e6data+asyncio` adapts it to a normal row. Ambiguous submission and incomplete result errors must not be handled by blindly retrying the query. Use context managers for bounded cleanup.

See [Async API](docs/ASYNC_API.md) for the complete API map, deadlines, pooling, SQLAlchemy and test configuration, [OAuth lifecycle](docs/OAUTH_LIFECYCLE.md) for renewal and failure behavior, and [the application example](examples/async_query.py).

The new CI keeps the full-package coverage denominator and a greater-than-80% gate. The initial baseline was about 19%, so focused async test success is not a release pass. Real-service tests require explicit configuration and are qualified separately.

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
| `username` | str | Conditional | None | Your e6data Email ID. Required unless authenticating with OAuth |
| `password` | str | Conditional | None | Access Token generated in the e6data console. Required unless authenticating with OAuth |
| `database` | str | No | None | Database to perform queries on |
| `catalog` | str | No | None | Catalog name |
| `cluster_name` | str | No | None | Name of the cluster for cluster-specific operations |
| `secure` | bool | No | False | Enable SSL/TLS for secure connections |
| `ssl_cert` | str/bytes | No | None | Path to CA certificate (PEM) or certificate bytes for HTTPS connections |
| `auto_resume` | bool | No | True | Automatically resume cluster if suspended |
| `grpc_options` | dict | No | None | Additional gRPC configuration options |
| `debug` | bool | No | False | Enable debug logging for troubleshooting |
| `require_fastbinary` | bool | No | True | Require fastbinary module for Thrift deserialization. Set to False to use pure Python implementation if system dependencies cannot be installed |
| `client_id` | str | No | None | OAuth 2.0 client id. Use with `client_secret` and `token_url` |
| `client_secret` | str | No | None | OAuth 2.0 client secret |
| `token_url` | str | No | None | Token endpoint of the authorization server |
| `oauth_scope` | str | No | None | Space-delimited scopes to request. Omit for the client's full registered set |
| `access_token` | str | No | None | A previously obtained access token, for callers that mint their own |
| `client_auth_method` | str | No | `'basic'` | How client credentials reach the token endpoint: `'basic'` or `'post'` |

#### Authenticating with OAuth 2.0

As an alternative to username and password, a connection can authenticate with an OAuth 2.0 access
token. The connector obtains a token using the client-credentials grant, caches it, and refreshes it
shortly before it expires.

Matching client-credentials configurations share one token cache and concurrent
refresh across sync and async connections, separate pools and threads in the same
process. Connection and transport ownership remain local. See the
[OAuth lifecycle](docs/OAUTH_LIFECYCLE.md) for matching settings and expiry behavior.

```python
conn = Connection(
    host=host,
    port=443,
    database=database,
    cluster_name='<cluster-name>',
    secure=True,
    client_id='<client_id>',
    client_secret='<client_secret>',
    token_url='https://<your-workspace>/oauth2/token',
)
```

If you mint tokens yourself, pass one directly instead. The connector will not refresh it, so a
long-lived connection may outlive the token:

```python
conn = Connection(
    host=host, port=443, database=database, cluster_name='<cluster-name>',
    secure=True, access_token='<token>',
)
```

**Supply exactly one authentication method.** Passing both username/password and OAuth settings
raises a `ValueError` rather than picking one, so a stale value left in a config file cannot quietly
win.

OAuth sends `authorization: Bearer <token>` on every RPC. It does not create an
authentication session; protobuf username, password and session ID fields remain
empty. The server stack must support and enable this bearer-only flow.

Use `secure=True` with your TLS endpoint and an HTTPS `token_url` to protect tokens
and client credentials. OAuth does not enable TLS automatically; `secure` defaults
to `False`. Set `cluster_name` to identify the target cluster explicitly.

With `auto_resume=True` (the default), OAuth can recover an initial query prepare
that returns the exact suspended-cluster response. This requires compatible,
enabled server components that authorize resume and report readiness. The connector
performs one recovery sequence and retries prepare after readiness. It never
replays query execution, metadata retrieval or result fetching, and it does not
treat generic connection failures as suspension.

Recovery has a shared 300-second default deadline covering lock waits, token
acquisition, status/resume calls, polling and the resumed prepare. Configure it with
`grpc_options={'grpc_auto_resume_timeout_seconds': 300}`. The deadline starts after
the suspended response; initial prepare has its own timeout. A dispatched resume
may still complete after the client times out.

Set `auto_resume=False` to disable recovery. Invalid credentials, denied permissions,
unsupported servers and failed or unknown cluster states stop recovery without
falling back to username/password authentication. Externally supplied access tokens
are not refreshed.

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

To get the status of a running or completed query:
```python
query_id = '<query_id>'  # query id from execute function response.
status_response = cursor.status(query_id)

# Check if query execution is complete
is_complete = status_response.status  # Returns True when query is done, False if still running

# Get the total row count
row_count = status_response.rowCount  # Total number of rows in the result set

print(f"Query complete: {is_complete}")
print(f"Row count: {row_count}")
```

The `status()` method is useful for:
- **Monitoring long-running queries**: Poll the status periodically to check if execution is complete
- **Checking row counts**: Get the total number of rows without fetching all results
- **Query progress tracking**: Integrate with monitoring systems or progress bars
- **Conditional fetching**: Decide whether to fetch results based on completion status

Example - Polling for query completion:
```python
import time

cursor = conn.cursor(catalog_name=catalog_name)
query_id = cursor.execute("SELECT * FROM large_table")

# Poll until query is complete
while True:
    status_response = cursor.status(query_id)
    if status_response.status:
        print(f"Query complete! Total rows: {status_response.rowCount}")
        break
    else:
        print("Query still running...")
        time.sleep(1)  # Wait 1 second before checking again

# Now fetch the results
results = cursor.fetchall()
```

Switch database in an existing connection:
```python
database = '<new_database_name>'  # Replace with the new database.
cursor = conn.cursor(database, catalog_name)
```

### Opt in to multi-chunk result batches

`enable_result_batch_v2=True` lets a compatible planner return several result
chunks in one `getNextResultBatchV2` response. The default is `False`, which keeps
the existing V1 protocol. Increasing `arraysize` or `fetchmany(size)` changes how
many rows your application receives per call; it does not change the planner's
response size.

The planner must support V2 and have `ENABLE_GET_NEXT_RESULT_BATCH_V2` enabled.
`ENABLE_GET_NEXT_CHUNK_V2` controls the separate executor-to-planner boundary.
Record both flags when qualifying a deployment. V2 can reduce network round
trips, but it does not reduce the number of result bytes or extend the planner's
query lifetime. Completion of a 20-million-row result within 900 seconds must be
measured against the actual workload and deployment.

The following examples use your existing `connection_options`, `sql`, and
`consume` function. Choose a positive `result_receive_limit_bytes` from measured
V2 response sizes and the client's memory budget. The sync API preserves its
existing gRPC options, so supply a finite receive limit for a V2 rollout:

```python
from e6data_python_connector import Connection

sync_options = {
    **connection_options,
    "enable_result_batch_v2": True,
    "grpc_options": {
        **connection_options.get("grpc_options", {}),
        "max_receive_message_length": result_receive_limit_bytes,
    },
}
with Connection(**sync_options) as connection:
    with connection.cursor() as cursor:
        cursor.execute(sql)
        for rows in cursor.fetchall_buffer():
            consume(rows)
```

The async API keeps its finite 64 MiB default. Set
`max_receive_message_bytes` to change that limit. If `grpc_options` also contains
a receive limit, it must agree with this value.

```python
from e6data_python_connector.aio import AsyncConnection

async_options = {
    **connection_options,
    "enable_result_batch_v2": True,
    "max_receive_message_bytes": result_receive_limit_bytes,
}
async with AsyncConnection(**async_options) as connection:
    async with connection.cursor() as cursor:
        await cursor.execute(sql)
        async for rows in cursor.fetchall_buffer():
            consume(rows)
```

SQLAlchemy accepts the same opt-in through `connect_args`:

```python
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine

engine = create_engine("e6data://", connect_args=sync_options)
async_engine = create_async_engine("e6data+asyncio://", connect_args=async_options)
```

Fetch return shapes and row order stay the same. `fetchall_buffer()` yields
decoded chunks; a V2 response can contain several chunks. All chunks in an
envelope are decoded before any are exposed, so V2 may use more memory and delay
the first chunk compared with V1. `fetchall()` still retains the full result.
There is no prefetch or parallel fetching for a query.

An `UNIMPLEMENTED` response switches that query to V1. A later query may try V2
again. Other fetch failures do not trigger a protocol fallback or query replay.
To disable V2 for new connections, omit the option or set it to `False`.

The [result batch qualification instructions](test/README.md#result-batch-v2-qualification)
cover protocol parity and the explicit large-result benchmark. Real-engine
qualification and the 900-second acceptance measurement have not been run for
this change.

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
