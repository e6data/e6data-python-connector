# e6data Python Connector

![version](https://img.shields.io/badge/version-2.2.6-blue.svg)

## Introduction

The e6data Connector for Python provides an interface for writing Python applications that can connect to e6data and perform operations. It includes automatic support for blue-green deployments, ensuring seamless failover during server updates without query interruption.

### Dependencies
Make sure to install below dependencies and wheel before install e6data-python-connector.
```shell
# Amazon Linux / CentOS dependencies
yum install python3-devel gcc-c++ -y

# Ubuntu/Debian dependencies
apt install python3-dev g++ -y


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

username = '<username>'  # Your e6data Email ID.
password = '<password>'  # Access Token generated in the e6data console.

host = '<host>'  # IP address or hostname of the cluster to be used.
database = '<database>'  # Database to perform the query on.
port = 80  # Port of the e6data engine.
catalog_name = '<catalog_name>'

conn = Connection(
    host=host,
    port=port,
    username=username,
    database=database,
    password=password
)
```

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
- Enable connection pooling for better resource utilization
- Automatic connection health monitoring
- Graceful connection recovery and retry logic

See [TECH_DOC.md](TECH_DOC.md) for detailed technical documentation.
