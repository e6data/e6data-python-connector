# Technical Documentation: e6Data Python Connector (gRPC-based Implementation)

## Overview
The `e6Data` Python connector is a [DB-API 2.0 compliant](https://peps.python.org/pep-0249/) implementation that facilitates communication with `e6Data` clusters. It relies on gRPC (Google Remote Procedure Calls) for interaction with the server and supports a wide range of operations such as establishing connections, running queries, fetching results, and manipulating metadata.

This documentation covers technical details of the connector, including architecture, components, execution times, and best practices for implementation.

---

## **System Features**

### **Key Features**
1. **Database Connection**:
   - Provides a simple utility to connect to an e6Data cluster.
   - Supports secure connections using SSL.

2. **Query Execution**:
   - Executes queries using prepare statements via gRPC.
   - Includes support for parameterized queries adhering to a PEP-249 standard (`paramstyle='pyformat'`).

3. **Result Handling**:
   - Fetch operations (`fetchone`, `fetchmany`, `fetchall`) are supported.
   - `fetchall_buffer` is supported with gRPC for better memory management during large data fetches.

4. **Query Metadata**:
   - Supports query explanation and runtime analysis (`explain_analyse`) for debugging and optimization.
   - Accesses schemas, tables, and column metadata dynamically.

5. **Error Handling & Authentication**:
   - Automatically retries with re-authentication for common gRPC errors (e.g., access denied).
   - Provides graceful handling of connection errors and retries.

6. **Blue-Green Deployment Support**:
   - Automatic detection of active deployment strategy (blue/green).
   - Graceful strategy transitions without query interruption.
   - Thread-safe and process-safe strategy caching.
   - Handles 456 errors for strategy mismatches with automatic retry.

7. **Testing Suite**:
   - Offers multiple layers of testing using Python's `unittest` framework.
   - Includes integration tests for connection, query execution, and fetching logic.
   - Mock gRPC server for testing blue-green deployment scenarios.

---

## **Components and Interfaces**

### **Connection Object**
The `Connection` class represents an open connection to the database.  

#### **Parameters**
| Parameter              | Type      | Description                                                                                                  |
|------------------------|-----------|--------------------------------------------------------------------------------------------------------------|
| `host`                 | `string`  | IP address or hostname of the e6Data cluster.                                                                |
| `port`                 | `int`     | Port number for the gRPC service (e.g., `80`, `443`).                                                        |
| `username`             | `string`  | User's email for authentication.                                                                             |
| `password`             | `string`  | Personal Access Token for authentication obtained from the e6data dashboard.                                 |
| `catalog`              | `string`  | The catalog name for accessing metadata.                                                                     |
| `database`             | `string`  | Database to query.                                                                                           |
| `secure`               | `bool`    | Whether to use gRPC secure channel (SSL). Defaults to `False`.                                               |
| `grpc_options`         | `dict`    | Advanced gRPC configurations such as timeouts, keep-alive settings, and max sizes for send/receive messages. |

---

### **Cursor Object**
A `Cursor` facilitates query execution and data fetching. Cursors are bound to a `Connection` object and are not isolated, meaning that changes in a cursor are immediately visible to others.

#### **Key Methods**
| Method                     | Description                                                                            |
|----------------------------|----------------------------------------------------------------------------------------|
| `execute(sql, params)`     | Executes a SQL statement. Supports parameterized queries.                              |
| `fetchone()`               | Fetches a single row from the query result.                                            |
| `fetchmany(size=N)`        | Fetches `N` rows from the result.                                                      |
| `fetchall()`               | Fetches all rows from the query result. Useful for small datasets.                     |
| `fetchall_buffer()`        | Fetches all rows from the query result. Useful for large datasets.                     |
| `explain_analyse()`        | Provides runtime statistics and query metrics such as parsing time, queuing time, etc. |
| `get_tables()`             | Lists all tables in the current database.                                              |
| `get_columns()`            | Lists column metadata for a given table.                                               |
| `clear()`                  | Clears cached results of the previous query to free memory.                            |

---

## **Execution Details and Timings**

### **Execution Lifecycle**
1. **Initialization**:
   - Establishes a gRPC channel (secure or non-secure) during connection initialization. Options such as timeouts and keepalives affect setup time.

2. **Authentication**:
   - Authenticates via gRPC by passing `username` and `password`.

3. **Prepare Statement**:
   - Queries are sent via `prepareStatement` API for compilation before execution.

4. **Query Execution**:
   - Executes the prepared query with IDs and retrieves data.
   - Includes optional metrics such as parsing time and queuing time.
   - _Execution Time_: Depends on query and result dataset size (measured through `explain_analyse`).

5. **Fetching Results**:
   - Data is streamed in batches using gRPC to optimize memory usage.
   - _Execution Time_: Variable (based on `fetch size`).

### **Best Practices to Minimize Execution Times**
- **Enable Query Caching**:
  Use gRPC cache settings to reduce repeated query times.
  
- **Limit Result Sets**:
  Use `LIMIT` clauses during queries to avoid fetching unnecessary data.

- **Connection Pooling**:
  Create a pool of connections to eliminate recurring connection overhead.

---

### Documentation on gRPC Options in Connection
The **`grpc_options`** parameter in the connection configuration plays an integral role in customizing advanced gRPC settings. This section expands on its functionalities and use cases, showcasing how it can enhance performance, optimize resource consumption, and handle specific gRPC-related scenarios.
#### **gRPC Options Details**
The parameter accepts a dictionary that allows users to control behavior and configuration of the gRPC communication layer. Below are some of the most commonly supported options and their specific purposes: `grpc_options`

| Option Name | Default Value | Description |
| --- | --- | --- |
| **`grpc_prepare_timeout`** | `600000ms` (10 minutes) | Time period (in milliseconds) to wait for the `prepare` statement process to complete. |
| **`keepalive_timeout_ms`** | `900000ms` | Maximum time in milliseconds that the connection can remain idle before sending a keepalive ping. |
| **`keepalive_time_ms`** | `30000ms` (30 seconds) | Interval in milliseconds between keep-alive pings when the connection is idle. |
| **`keepalive_permit_without_calls`** | `1` | Allows keepalive pings even when there are no active RPC calls. |
| **`max_receive_message_length`** | `-1` (unlimited) | Maximum size (in bytes) for incoming message payloads. |
| **`max_send_message_length`** | `300 * 1024 * 1024` | Maximum size (in bytes) for outgoing message payloads (default: 300 MB). |
| **`http2.max_pings_without_data`** | `0` | Number of pings that can be sent without data. `0` means unlimited pings. |
| **`http2.min_time_between_pings_ms`** | `15000ms` (15 seconds) | Minimum interval between consecutive pings to verify connection status. |
| **`http2.min_ping_interval_without_data_ms`** | `15000ms` (15 seconds) | Interval between pings sent without any data being exchanged. |

#### **Use Case Scenarios**
Here are some practical examples of how the gRPC options can be configured to address specific scenarios:
1. **Handling Large Query Results**: When returning large datasets, configure the limits for transmitted message sizes to prevent errors or connection resets.
``` python
   grpc_options = {
       'max_receive_message_length': 500 * 1024 * 1024,  # Set maximum incoming response size to 500 MB
       'max_send_message_length': 500 * 1024 * 1024      # Allow larger query requests up to 500 MB
   }
```
1. **Improving Connection Stability**: For unreliable network conditions, regular keep-alive pings can prevent unexpected connection downtime.
``` python
   grpc_options = {
       'keepalive_time_ms': 10000,   # Send pings every 10 seconds
       'keepalive_timeout_ms': 20000,  # Consider timeout if no response within 20 seconds
       'keepalive_permit_without_calls': 1  # Allow keep-alive pings even without ongoing RPCs
   }
```
1. **Preventing Excessive Bandwidth Usage**: By setting limits to the frequency of HTTP/2 pings and message payload sizes, users can balance performance with bandwidth constraints.
``` python
   grpc_options = {
       'http2.max_pings_without_data': 5,               # Limit extra pings without data to 5
       'http2.min_time_between_pings_ms': 30000,        # Minimum 30 seconds between pings
       'http2.min_ping_interval_without_data_ms': 30000
   }
```
1. **Extending Query Timeouts**: For complex or long-running queries, extending the can help avoid premature termination of query preparation tasks. `grpc_prepare_timeout`
``` python
   grpc_options = {
       'grpc_prepare_timeout': 20 * 60 * 1000,  # Increase prepare timeout to 20 minutes
   }
```
#### **Best Practices for gRPC Configuration**
- **Start with Defaults**: Unless you encounter specific issues, start with the default values provided by the system.
- **Monitor Metrics**: Use performance testing tools to identify bottlenecks and fine-tune gRPC parameters accordingly.
- **Network Considerations**: Evaluate network quality when setting keepalive and timeout settings to maintain a balance between performance and resource consumption.
- **Payload Size**: Always configure carefully when handling large datasets to prevent memory overflows. `max_receive_message_length`

#### **How It Works Internally**
The are passed during gRPC channel creation to configure its behavior, either using a secure (SSL-enabled) or insecure channel. These options are cached to prevent redundant configuration rebuilding for repeated operations. `grpc_options`
``` python
self._channel = grpc.insecure_channel(
    target='{}:{}'.format(self._host, self._port),
    options=self._get_grpc_options
)
```
Secure channels additionally use SSL credentials when enabled:
``` python
self._channel = grpc.secure_channel(
    target='{}:{}'.format(self._host, self._port),
    options=self._get_grpc_options,
    credentials=grpc.ssl_channel_credentials()
)
```
The merged configuration ensures all user-defined parameters override the default settings where applicable.

---

### **What is `pyformat`?**
The `pyformat` parameter style is a method to include parameters in SQL queries using a Python-specific formatting style. It is one of the five parameter styles recommended by [PEP-249](https://peps.python.org/pep-0249/) for database interactions. This approach is particularly useful for writing parameterized queries that prevent SQL injection and improve code readability.
`pyformat` uses **named placeholders** as parameters, which are represented in the SQL query with the syntax. `%(name)s`
#### **Examples of `pyformat` SQL Queries**
1. **Parameterized Query for Selection**
``` python
   sql = "SELECT * FROM users WHERE age > %(age)s"
   params = {"age": 25}
   cursor.execute(sql, params)
```

### **Why Use `pyformat`?**
1. **Prevention of SQL Injection**
    - With parameterized queries, the input data is automatically escaped and sanitized, reducing the risk of injection attacks.

2. **Readability**
    - The named placeholders make SQL queries more descriptive and easier to understand.

3. **Flexibility**
    - Using a dictionary for parameters allows supplying non-sequential or optional data dynamically without altering the query structure.

### **Common Errors and Resolutions When Using `pyformat`**
1. **Missing Placeholder in Parameters**
    - Error: `KeyError: 'placeholder_name'`
    - Cause: A parameter placeholder in the query does not have a matching key in the `params` dictionary.
    - Solution: Verify that all placeholders in the query have corresponding keys in the `params` dictionary.

2. **Incorrect Parameter Type**
    - Error: `TypeError: %d format: a number is required, not str`
    - Cause: A placeholder expects a certain type (e.g., integer for ), but an incompatible type is provided. `%d`
    - Solution: Ensure that parameter values match the expected types for the placeholders.

3. **SQL Syntax Issues**
    - Error: `ProgrammingError: syntax error at or near`
    - Cause: Incorrect SQL syntax or improper placement of parameter placeholders.
    - Solution: Double-check the SQL query syntax and ensure that the `pyformat` placeholders are used correctly.

### **Best Practices for Using `pyformat`**
- **Always Use Parameterized Queries**: They are secure and eliminate SQL injection risks.
- **Validate Input Data**: Ensure that the data passed in the `params` dictionary is sanitized and of the correct type.
- **Log Queries for Debugging**: Log the queries when necessary (avoiding logging sensitive information).
- **Handle Errors Gracefully**: Use a try-except block to catch and handle errors during execution.

---

## **Error Handling and Recovery**
The connector includes robust error handling mechanisms, with retry logic for common gRPC errors.

### **Common Errors and Resolutions**
| Error           | Cause                                         | Resolution                                                                                |
|-----------------|----------------------------------------------|-------------------------------------------------------------------------------------------|
| Authentication  | Invalid credentials or expired session.      | Retries to authentication max 5 times.                                                    |
| Connection      | gRPC channel timeout or server unavailability| Graceful retries using `_InactiveRpcError` handling. |

---

## **Performance Testing**

### **Test Execution Workflow**
1. **Connection Validation**:
   Verify a connection to the server using environment variables for host and database.

2. **Query Execution**:
   Execute SQL queries of various complexities to measure correctness, latency, and response times.

3. **Caching Validation**:
   Test query performance under cache-enabled and cache-disabled settings.

4. **Explain Plans**:
   Ensure that `explain_analyse` produces correct and useful insights regarding query execution.

---

### Improving Performance using Python 3.12 or Latest

To improve the performance of the `e6Data Python Connector` and ensure compatibility with state-of-the-art features, it is recommended to use Python 3.12 (or the latest stable version). Below are the enhancements in Python 3.12 that can benefit the connector:


### **Key Benefits of Using Python 3.12+**

1. **Faster Startup Time**:
   - Python 3.12 introduces enhanced interpreter internals, reducing startup times for processes, which is beneficial for short-lived connections or scripts.

2. **Improved Performance of `cpython`**:
   - Optimized execution of imported modules and object handling.
   - Faster `for` loops and tighter memory management, which significantly impacts iterative data fetching methods like `fetchmany` or `fetchall`.

3. **Better Memory Usage**:
   - Python 3.12 has improvements in memory allocation for frequently created objects, which can reduce overhead during large query-handling operations.

4. **Support for the `perf` Module**:
   - Python 3.12 introduces better compatibility with debugging and performance profiling libraries like `perf`. Using this module, you can precisely measure the performance of the connector and identify bottlenecks.

5. **Typing Enhancements**:
   - Enhanced type annotations allow you to write cleaner, more optimized code if you extend or interact with the connector in custom applications.

6. **Improved Error Tracing**:
   - The new traceback system provides better visibility into exceptions. This can lead to faster debugging when encountering issues such as query failures or connection problems.

---

### **Best Practices To Leverage Python 3.12 (or Latest)**

1. **Use Faster Built-in Functions**:
   - Python 3.12's built-in functions now execute more efficiently. Functions like `len()`, `max()`, and `min()` are faster. Use these directly during logic implementation.

2. **Enable Adaptive Specialization**:
   - Turn on optimizations available in Python 3.12 by using runtime flags:
```shell script
python3.12 -X adaptive
```


3. **Use Robust Async Functionality**:
   - For better async handling (e.g., with large data transfers), Python 3.12 introduces internals that speed up `asyncio` operations, especially useful in gRPC async calls.

4. **Upgraded Garbage Collection**:
   - Python 3.12 reduces the overhead of garbage collection by improving the cleanup of short-lived objects. For large datasets or batch operations, this helps reduce memory usage.

5. **Leverage New PEP Features**:
   - Python 3.12 includes additional PEP compliance, such as [PEP 709 (Inlined Comprehensions)], which can make code execution for list comprehensions faster:
```python
# Starting Python 3.12 – optimizations are now inline without manual intervention.
data_rows = [process(row) for row in cursor.fetchall()]
```


---

### **Recommendations for Transition**

1. **Upgrade Environment**:
   - Ensure your Python environment uses the latest stable version of Python 3.12 or above. Use `virtualenv` to isolate the upgraded environment.
```shell script
python3.12 -m venv venv
source venv/bin/activate
```


2. **Rebuild Dependencies**:
   - Re-install the connector using an updated Python version to ensure compatibility. Test for warnings or deprecations after upgrading:
```shell script
pip install --upgrade .
```


3. **Configure gRPC for Compatibility**:
   - Use Python 3.12's updated `multithreading` and `multiprocessing` support to handle concurrent requests more efficiently. This helps maintain stable performance during multiple gRPC transactions.

4. **Monitor and Profile**:
   - Use Python 3.12's enhanced debugging and profiling tools (e.g., `perf` or `time.perf_counter()`) to measure performance improvements:
```python
import time

start = time.perf_counter()
cursor.fetchall()
end = time.perf_counter()
print(f"Fetch Time: {end - start}")
```

---

### **Testing Performance with Python 3.12**

**Benchmark Handling of Large Data**:
   - Test bulk fetches and analyze memory usage to ensure Python 3.12 optimizations are applied:
```python
test_data = cursor.fetchmany(10000)
assert isinstance(test_data, list)
```


With Python 3.12's adaptive optimizations, your application can achieve better memory utilization, faster data processing, and smoother user experience overall for `e6Data` Python Connector-based solutions.

---

## **Blue-Green Deployment Strategy Implementation**

### **Overview**
The connector implements automatic blue-green deployment strategy detection and handling to ensure zero-downtime during server updates.

### **Architecture**
1. **Strategy Storage**:
   - Thread-safe and process-safe shared memory storage
   - Uses `threading.Lock` and `multiprocessing.Manager`
   - Falls back to thread-local storage if Manager unavailable
   
2. **Strategy Detection**:
   - Initial detection on first authentication
   - Tries both "blue" and "green" strategies
   - Caches successful strategy for 5 minutes

3. **gRPC Headers**:
   - All requests include "strategy" header
   - Server validates and returns 456 error for mismatches
   - Error triggers automatic retry with correct strategy

4. **Graceful Transitions**:
   - Server sends `new_strategy` in response when switching
   - Current queries continue with original strategy
   - New strategy applied after query completion (clear/cancel)
   - Per-query strategy tracking ensures consistency

### **API Response Handling**
All gRPC responses check for `new_strategy` field:
- AuthenticateResponse
- PrepareStatementResponse
- ExecuteStatementResponse
- GetNextResultBatchResponse
- GetResultMetadataResponse
- StatusResponse
- ClearResponse/ClearOrCancelQueryResponse
- CancelQueryResponse
- GetTablesResponse/GetSchemaNamesResponse/GetColumnsResponse
- ExplainResponse/ExplainAnalyzeResponse

### **Implementation Details**

#### **Key Functions**:
```python
# Get current active strategy
_get_active_strategy() -> Optional[str]

# Set active strategy with timestamp
_set_active_strategy(strategy: str) -> None

# Clear strategy cache (forces re-detection)
_clear_strategy_cache() -> None

# Set pending strategy for next query
_set_pending_strategy(strategy: str) -> None

# Apply pending strategy after query completion
_apply_pending_strategy() -> None

# Track strategy per query
_register_query_strategy(query_id: str, strategy: str) -> None
_get_query_strategy(query_id: str) -> str
_cleanup_query_strategy(query_id: str) -> None
```

#### **Error Handling**:
The `re_auth` decorator handles both authentication and strategy errors:
- Access denied: Re-authenticates and retries
- 456 error: Clears strategy cache and re-detects

### **Testing**
1. **Unit Tests**: `test_strategy.py` covers all scenarios
2. **Mock Server**: `mock_grpc_server.py` simulates strategy switching
3. **Test Client**: `test_mock_server.py` demonstrates behavior

### **Best Practices**
1. No code changes required in applications
2. Strategy handled transparently by connector
3. Monitor logs for strategy transitions
4. Test with mock server before production deployment

----

## **Summary**

The `e6Data Python Connector` is a scalable and efficient interface for gRPC-based database interactions. It is optimized for robust performance, enhanced with error-handling mechanisms, and is PEP-249 compliant, making it easy to integrate into Python-based applications. With comprehensive blue-green deployment support, tests and metrics in place, it ensures reliable operations and performance tuning.