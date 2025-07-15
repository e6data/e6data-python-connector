# Zero Downtime Deployment - API Reference

## Overview

The e6data Python Connector provides automatic zero downtime deployment support through a blue-green deployment strategy. This document describes the internal APIs and functions that manage this functionality.

## Core API Functions

### Strategy Management Functions

#### `_get_active_strategy()`

**Description**: Retrieves the currently active deployment strategy from shared memory.

**Returns**: 
- `str`: The active strategy ("blue" or "green")
- `None`: If no strategy is cached or cache has expired

**Thread Safety**: Yes (uses `_strategy_lock`)

**Example Usage**:
```python
current_strategy = _get_active_strategy()
if current_strategy:
    print(f"Current strategy: {current_strategy}")
```

#### `_set_active_strategy(strategy)`

**Description**: Sets the active deployment strategy in shared memory.

**Parameters**:
- `strategy` (str): The strategy to set ("blue" or "green", case-insensitive)

**Validation**: 
- Normalizes input to lowercase
- Validates strategy is either "blue" or "green"
- Logs warnings for invalid values

**Thread Safety**: Yes (uses `_strategy_lock`)

**Example Usage**:
```python
_set_active_strategy("Blue")  # Normalized to "blue"
_set_active_strategy("invalid")  # Logs warning and returns early
```

#### `_set_pending_strategy(strategy)`

**Description**: Sets a pending strategy to be applied after current queries complete.

**Parameters**:
- `strategy` (str): The pending strategy ("blue" or "green", case-insensitive)

**Behavior**:
- Only sets pending strategy if different from current active strategy
- Validates and normalizes input
- Used for graceful strategy transitions

**Thread Safety**: Yes (uses `_strategy_lock`)

**Example Usage**:
```python
_set_pending_strategy("green")  # Will be applied after current queries finish
```

#### `_apply_pending_strategy()`

**Description**: Applies the pending strategy as the new active strategy.

**Behavior**:
- Moves pending strategy to active strategy
- Clears pending strategy
- Updates last check time
- Logs transition completion

**Thread Safety**: Yes (uses `_strategy_lock`)

**Called By**: 
- `clear()` method after query completion
- `cancel()` method after query cancellation

#### `_clear_strategy_cache()`

**Description**: Clears the cached strategy to force re-detection.

**Behavior**:
- Resets active strategy to None
- Resets last check time to 0
- Clears pending strategy
- Forces strategy re-detection on next request

**Thread Safety**: Yes (uses `_strategy_lock`)

**Use Cases**:
- 456 error handling (strategy mismatch)
- Forced strategy refresh
- Error recovery scenarios

### Query Strategy Management

#### `_register_query_strategy(query_id, strategy)`

**Description**: Associates a specific query with the strategy used to execute it.

**Parameters**:
- `query_id` (str): Unique identifier for the query
- `strategy` (str): Strategy used for this query ("blue" or "green")

**Validation**:
- Validates both parameters are not None/empty
- Normalizes strategy to lowercase
- Validates strategy is "blue" or "green"

**Thread Safety**: Yes (uses `_strategy_lock`)

**Example Usage**:
```python
_register_query_strategy("query_123", "blue")
```

#### `_get_query_strategy(query_id)`

**Description**: Retrieves the strategy used for a specific query.

**Parameters**:
- `query_id` (str): Query identifier

**Returns**:
- `str`: Strategy used for the query
- Falls back to current active strategy if query not found

**Thread Safety**: Yes (uses `_strategy_lock`)

**Example Usage**:
```python
strategy = _get_query_strategy("query_123")
```

#### `_cleanup_query_strategy(query_id)`

**Description**: Removes the strategy mapping for a completed query.

**Parameters**:
- `query_id` (str): Query identifier to remove

**Behavior**:
- Removes query from strategy mapping
- Prevents memory leaks from long-running applications
- Called automatically on query completion

**Thread Safety**: Yes (uses `_strategy_lock`)

### Header Management

#### `_get_grpc_header(engine_ip=None, cluster=None, strategy=None)`

**Description**: Constructs gRPC metadata headers for requests.

**Parameters**:
- `engine_ip` (str, optional): Engine IP address
- `cluster` (str, optional): Cluster UUID
- `strategy` (str, optional): Deployment strategy

**Returns**:
- `list`: List of tuples containing gRPC metadata

**Strategy Handling**:
- Normalizes strategy to lowercase
- Validates strategy is "blue" or "green"
- Logs warnings for invalid strategies
- Omits invalid strategies from headers

**Example Usage**:
```python
headers = _get_grpc_header(
    engine_ip="192.168.1.100",
    cluster="cluster-uuid-123",
    strategy="blue"
)
```

### Shared Memory Management

#### `_get_shared_strategy()`

**Description**: Gets or creates the shared strategy storage.

**Returns**:
- `dict`: Shared strategy storage object

**Behavior**:
- Attempts to use multiprocessing.Manager for process-safe storage
- Falls back to thread-local storage if Manager fails
- Initializes storage structure if needed

**Storage Structure**:
```python
{
    'active_strategy': str,           # Current active strategy
    'last_check_time': float,         # Timestamp of last strategy check
    'pending_strategy': str,          # Strategy to apply next
    'query_strategy_map': dict        # Query ID -> strategy mapping
}
```

## Connection Class Integration

### Authentication with Strategy Detection

The `Connection.get_session_id` property handles automatic strategy detection:

1. **Cached Strategy**: Uses cached strategy if available
2. **Strategy Detection**: Tries both "blue" and "green" if no cache
3. **Error Handling**: Handles 456 errors for strategy mismatches
4. **Strategy Notification**: Processes `new_strategy` fields in responses

### Automatic Strategy Headers

All gRPC requests automatically include strategy headers:

- `authenticate()`: Strategy detection and caching
- `prepareStatement()`: Uses query-specific or active strategy
- `executeStatement()`: Maintains strategy consistency
- `getNextResultBatch()`: Continues with query's original strategy
- `clear()`: Applies pending strategy changes

## Cursor Class Integration

### Query Lifecycle Management

The `Cursor` class integrates strategy management throughout query execution:

1. **Execute**: Registers query with current strategy
2. **Fetch**: Uses query's original strategy for consistency
3. **Clear**: Applies pending strategy transitions
4. **Cancel**: Cleans up strategy mappings

### Metadata Property

The `Cursor.metadata` property dynamically selects the appropriate strategy:

```python
@property
def metadata(self):
    strategy = _get_query_strategy(self._query_id) if self._query_id else _get_active_strategy()
    return _get_grpc_header(engine_ip=self._engine_ip, cluster=self.connection.cluster_uuid, strategy=strategy)
```

## Error Handling

### 456 Error Processing

The `@re_auth` decorator handles strategy-related errors:

```python
elif '456' in e.details() or 'status: 456' in e.details():
    # Strategy changed, clear cache and retry
    _logger.info(f'STRATEGY_CHANGE: Function Name: {func}')
    _logger.info(f'STRATEGY_CHANGE: Clearing strategy cache due to 456 error')
    _clear_strategy_cache()
    # Force re-authentication which will detect new strategy
    self.connection.get_re_authenticate_session_id()
```

### Automatic Recovery

The system provides automatic recovery from strategy mismatches:

1. **Detection**: 456 errors indicate strategy mismatch
2. **Cache Clear**: Clears cached strategy
3. **Re-authentication**: Forces strategy re-detection
4. **Retry**: Retries original operation with new strategy

## Thread and Process Safety

### Locking Mechanism

All strategy functions use `_strategy_lock` for thread safety:

```python
_strategy_lock = threading.Lock()

def _get_active_strategy():
    with _strategy_lock:
        # Thread-safe operations
        pass
```

### Shared Memory

The system uses multiprocessing.Manager for process-safe storage:

```python
def _get_shared_strategy():
    try:
        if _strategy_manager is None:
            _strategy_manager = multiprocessing.Manager()
            _shared_strategy = _strategy_manager.dict()
        return _shared_strategy
    except:
        # Fall back to thread-local storage
        return _local_strategy_cache
```

## Configuration Constants

### Cache Timeout

```python
STRATEGY_CACHE_TIMEOUT = 300  # 5 minutes in seconds
```

The strategy cache expires after 5 minutes to ensure fresh strategy detection while maintaining performance.

## Best Practices

### Strategy Validation

Always validate strategy values:

```python
def validate_strategy(strategy):
    if not strategy:
        return False
    normalized = strategy.lower()
    return normalized in ['blue', 'green']
```

### Error Logging

Log strategy transitions and errors:

```python
_logger.info(f"Strategy transition completed: {old_strategy} -> {new_strategy}")
_logger.warning(f"Invalid strategy value: {strategy}. Must be 'blue' or 'green'.")
```

### Resource Cleanup

Always clean up query strategy mappings:

```python
def cleanup_query(query_id):
    if query_id:
        _cleanup_query_strategy(query_id)
        _apply_pending_strategy()
```

## Monitoring and Debugging

### Strategy State Inspection

Debug current strategy state:

```python
def debug_strategy_state():
    shared = _get_shared_strategy()
    print(f"Active: {shared['active_strategy']}")
    print(f"Pending: {shared['pending_strategy']}")
    print(f"Last Check: {shared['last_check_time']}")
    print(f"Query Map: {shared['query_strategy_map']}")
```

### Performance Considerations

- Strategy detection occurs only on first connection or cache expiry
- Query strategy mappings are cleaned up automatically
- Shared memory usage is minimal and bounded
- Lock contention is minimized through short critical sections