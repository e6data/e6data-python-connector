# Blue-Green Deployment Strategy Support

## Overview

The e6data Python connector now supports automatic detection and handling of blue-green deployments on the server side. When the server is deployed using a blue-green strategy, the connector will automatically detect which deployment (blue or green) is active and route all requests accordingly.

## How It Works

### Strategy Detection

1. **Initial Detection**: On the first authentication request, the connector tries to determine the active strategy by attempting authentication with both "blue" and "green" strategies.

2. **Strategy Header**: The connector adds a `strategy` header to all gRPC requests with the detected value ("blue" or "green").

3. **Graceful Transition**: When the server is updated, it includes a `new_strategy` field in query responses (prepare, execute, fetch, status). This allows:
   - Current queries to complete with their original strategy
   - New queries to use the updated strategy
   - No interruption to in-flight queries

4. **Error Handling**: If a request fails with a 456 error code (indicating wrong strategy), the connector automatically:
   - Clears the cached strategy
   - Re-detects the correct strategy
   - Retries the request with the new strategy

### Caching Mechanism

- The detected strategy is cached for 5 minutes (configurable via `STRATEGY_CACHE_TIMEOUT`)
- The cache is thread-safe and process-safe using `threading.Lock` and `multiprocessing.Manager`
- If multiprocessing.Manager is not available, it falls back to thread-local storage

### Automatic Retry

The connector includes automatic retry logic for:
- Authentication failures (existing behavior)
- Strategy mismatches (new behavior)

## Implementation Details

### Key Components

1. **Global Strategy Storage**:
   ```python
   _shared_strategy = {
       'active_strategy': 'blue' or 'green' or None,
       'last_check_time': timestamp,
       'pending_strategy': 'blue' or 'green' or None,  # Next strategy to use
       'query_strategy_map': {query_id: strategy}      # Per-query strategy tracking
   }
   ```

2. **Strategy Functions**:
   - `_get_active_strategy()`: Returns the cached strategy if valid
   - `_set_active_strategy(strategy)`: Updates the cached strategy
   - `_clear_strategy_cache()`: Forces re-detection on next request
   - `_set_pending_strategy(strategy)`: Sets strategy for future queries
   - `_apply_pending_strategy()`: Applies pending strategy after query completion
   - `_register_query_strategy(query_id, strategy)`: Tracks strategy per query
   - `_get_query_strategy(query_id)`: Gets strategy for specific query
   - `_cleanup_query_strategy(query_id)`: Removes completed query tracking

3. **Modified gRPC Headers**:
   All gRPC requests now include the strategy header when available:
   ```python
   metadata = [
       ('plannerip', engine_ip),
       ('cluster-uuid', cluster_uuid),
       ('strategy', 'blue' or 'green')  # New header
   ]
   ```

4. **Response Handling**:
   The connector checks for `new_strategy` in ALL API responses:
   - AuthenticateResponse
   - PrepareStatementResponse
   - ExecuteStatementResponse
   - GetNextResultBatchResponse
   - GetNextResultRowResponse
   - GetResultMetadataResponse
   - StatusResponse
   - ClearResponse
   - ClearOrCancelQueryResponse
   - CancelQueryResponse
   - GetTablesResponse
   - GetSchemaNamesResponse
   - GetColumnsResponse
   - ExplainResponse
   - ExplainAnalyzeResponse
   - DryRunResponse

## Usage

No changes are required in your application code. The connector handles strategy detection automatically:

```python
from e6data_python_connector import Connection

# Create connection as usual
conn = Connection(
    host='your-host',
    port=80,
    username='your-email',
    password='your-token',
    database='your-db',
    catalog='your-catalog'
)

# Use the connection normally
cursor = conn.cursor()
cursor.execute("SELECT * FROM your_table")
results = cursor.fetchall()
```

## Logging

The connector logs strategy-related events at INFO level:
- Strategy detection attempts
- Successful strategy detection
- Strategy cache clearing
- Strategy change detection

Enable logging to see these messages:
```python
import logging
logging.basicConfig(level=logging.INFO)
```

## Testing

Run the included test script to verify the implementation:

```bash
# Set environment variables
export ENGINE_IP=your-engine-ip
export DB_NAME=your-database
export EMAIL=your-email
export PASSWORD=your-token
export CATALOG=your-catalog
export PORT=80

# Run tests
python test_strategy.py
```

## Performance Considerations

- Strategy detection only occurs on the first request or after cache expiry
- Subsequent requests use the cached strategy with minimal overhead
- The cache timeout (5 minutes) balances between performance and responsiveness to strategy changes
- Thread-safe implementation ensures correct behavior in multi-threaded applications
- Process-safe implementation supports multi-process deployments

## Error Scenarios

1. **Both strategies fail**: If neither "blue" nor "green" strategy works, the original error is raised
2. **Strategy change during operation**: Automatically detected via 456 error and handled transparently
3. **Network issues**: Existing retry logic continues to work as before
4. **Graceful transition**: When server sends `new_strategy` in response:
   - Current queries continue with their original strategy
   - New queries use the updated strategy after the current query completes
   - No queries are interrupted or fail due to strategy changes

## Configuration

Currently, the strategy cache timeout is hardcoded to 5 minutes. If needed, this can be made configurable in future versions through the `grpc_options` parameter.