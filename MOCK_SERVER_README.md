# Mock gRPC Server for Blue-Green Testing

This directory contains a mock gRPC server that simulates the e6data engine service with blue-green deployment strategy switching.

## Features

- Implements the full e6data gRPC service interface
- Automatically switches between "blue" and "green" strategies every 2 minutes
- Returns `new_strategy` field in responses when a switch is pending
- Validates client strategy headers and returns 456 errors for mismatches
- Simulates query execution with mock data
- Supports all major API operations (authenticate, query, fetch, schema operations)

## Prerequisites

Install the required dependencies:

```bash
pip install grpcio grpcio-tools
```

Generate the gRPC Python code from proto files (if needed):

```bash
python -m grpc_tools.protoc -I. --python_out=e6data_python_connector/server --grpc_python_out=e6data_python_connector/server e6x_engine.proto
```

## Running the Mock Server

1. Start the mock server:

```bash
python mock_grpc_server.py
```

The server will:
- Listen on port 50051
- Start with "blue" strategy
- Switch strategies every 2 minutes
- Log all activity including strategy changes

## Testing Strategy Switching

1. In another terminal, run the test client:

```bash
python test_mock_server.py
```

Choose option 1 for continuous queries to see strategy switching in action.

## How Strategy Switching Works

1. **Initial State**: Server starts with "blue" strategy
2. **Timer**: After 2 minutes, server prepares to switch to "green"
3. **Notification**: Next API response includes `new_strategy: "green"`
4. **Client Update**: Client stores pending strategy but continues using "blue" for current query
5. **Query Completion**: When query completes (clear/cancel), client applies the new strategy
6. **Next Query**: Uses "green" strategy
7. **Validation**: Server accepts "green", rejects "blue" with 456 error

## Mock Server Behavior

### Authentication
- Accepts any non-empty username/password
- Returns a UUID session ID
- Includes `new_strategy` when switch is pending

### Query Execution
- PrepareStatement: Assigns query ID, stores query
- ExecuteStatement: Generates mock result data
- GetNextResultBatch: Returns data in batches
- Clear/Cancel: Cleans up query, triggers strategy switch

### Schema Operations
- GetSchemaNames: Returns mock schemas
- GetTables: Returns mock tables
- GetColumns: Returns mock column definitions

### Strategy Validation
- Checks "strategy" header in request metadata
- Returns 456 error if strategy doesn't match current
- Includes `new_strategy` in response when switch pending

## Example Output

### Server Logs:
```
2024-01-15 10:00:00 - INFO - Mock e6data gRPC server started on port 50051
2024-01-15 10:00:00 - INFO - Initial strategy: blue
2024-01-15 10:00:00 - INFO - Strategy will switch every 120 seconds
2024-01-15 10:00:30 - INFO - Authenticated user test@example.com with session 123e4567-e89b-12d3-a456-426614174000
2024-01-15 10:01:50 - INFO - Strategy change pending: blue -> green
2024-01-15 10:02:00 - INFO - Notifying client about pending strategy change to: green
2024-01-15 10:02:05 - INFO - Strategy switched from blue to green
```

### Client Logs:
```
2024-01-15 10:00:30 - INFO - Successfully authenticated with strategy: blue
2024-01-15 10:01:00 - INFO - Query #1 executed successfully
2024-01-15 10:02:00 - INFO - Pending deployment strategy set to: green
2024-01-15 10:02:05 - INFO - Strategy transition completed: blue -> green
2024-01-15 10:02:30 - INFO - Query #2 executed with new strategy: green
```

## Customization

You can modify the mock server behavior:

- **Switch Interval**: Change `strategy_switch_interval` in StrategyManager
- **Mock Data**: Modify `create_mock_result_batch()` for different data
- **Error Scenarios**: Add additional error conditions
- **Response Delays**: Add delays to simulate network latency

## Troubleshooting

1. **Port Already in Use**: Change port in both server and test client
2. **Import Errors**: Ensure proto files are compiled and in PYTHONPATH
3. **Strategy Not Switching**: Check server logs for pending changes
4. **456 Errors**: Normal during transition, client should retry automatically