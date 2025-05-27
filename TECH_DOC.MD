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

6. **Testing Suite**:
   - Offers multiple layers of testing using Python's `unittest` framework.
   - Includes integration tests for connection, query execution, and fetching logic.

---

## **Components and Interfaces**

### **1. Connection Object**
The `Connection` class represents an open connection to the database.  

#### **Parameters**
| Parameter              | Type      | Description                                                                                                  |
|------------------------|-----------|--------------------------------------------------------------------------------------------------------------|
| `host`                 | `string`  | IP address or hostname of the e6Data cluster.                                                               |
| `port`                 | `int`     | Port number for the gRPC service (e.g., `4000`).                                                            |
| `username`             | `string`  | User's email for authentication.                                                                            |
| `password`             | `string`  | Authentication token obtained from the console.                                                             |
| `catalog`              | `string`  | The catalog name for accessing metadata.                                                                    |
| `database`             | `string`  | Database to query.                                                                                          |
| `secure`               | `bool`    | Whether to use gRPC secure channel (SSL). Defaults to `False`.                                              |
| `grpc_options`         | `dict`    | Advanced gRPC configurations such as timeouts, keep-alive settings, and max sizes for send/receive messages.|

---

### **2. Cursor Object**
A `Cursor` facilitates query execution and data fetching. Cursors are bound to a `Connection` object and are not isolated, meaning that changes in a cursor are immediately visible to others.

#### **Key Methods**
| Method                     | Description                                                                                                         |
|----------------------------|---------------------------------------------------------------------------------------------------------------------|
| `execute(sql, params)`     | Executes a SQL statement. Supports parameterized queries.                                                           |
| `fetchone()`               | Fetches a single row from the query result.                                                                         |
| `fetchmany(size=N)`        | Fetches `N` rows from the result.                                                                                   |
| `fetchall()`               | Fetches all rows from the query result. Useful for small datasets.                                                  |
| `explain_analyse()`        | Provides runtime statistics and query metrics such as parsing time, queuing time, etc.                              |
| `get_tables()`             | Lists all tables in the current database.                                                                           |
| `get_columns()`            | Lists column metadata for a given table.                                                                            |
| `clear()`                  | Clears cached results of the previous query to free memory.                                                         |

---

## **Execution Details and Timings**

### **Execution Lifecycle**
1. **Initialization**:
   - Establishes a gRPC channel (secure or non-secure) during connection initialization. Options such as timeouts and keepalives affect setup time.
   - _Estimated Wall Time_: ~100ms, depending on network conditions.

2. **Authentication**:
   - Authenticates via gRPC by passing `username` and `password`.
   - _Execution Time_: ~300ms–800ms.

3. **Prepare Statement**:
   - Queries are sent via `prepareStatement` API for compilation before execution.
   - _Execution Time_: Varies with query complexity (average: 100ms–1s).

4. **Query Execution**:
   - Executes the prepared query with IDs and retrieves data.
   - Includes optional metrics such as parsing time and queuing time.
   - _Execution Time_: Depends on query and result dataset size (measured through `explain_analyse`).

5. **Fetching Results**:
   - Data is streamed in batches using gRPC to optimize memory usage.
   - _Execution Time_: Variable (based on `fetch size`).

### **Best Practices to Minimize Execution Times**
- **Enable Query Caching**:
  Use gRPC cache settings to reduce repeated query times (saves ~20ms–200ms for subsequent executions).
  
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

#### **What is `pyformat`?**
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

## **Summary**

The `e6Data Python Connector` is a scalable and efficient interface for gRPC-based database interactions. It is optimized for robust performance, enhanced with error-handling mechanisms, and is PEP-249 compliant, making it easy to integrate into Python-based applications. With tests and metrics in place, it ensures reliable operations and performance tuning.