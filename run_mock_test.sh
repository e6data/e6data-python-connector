#!/bin/bash
# Script to run mock server and test client for blue-green strategy testing

echo "Blue-Green Strategy Mock Test"
echo "============================"
echo ""
echo "This script will:"
echo "1. Start a mock gRPC server on port 50051"
echo "2. The server switches between 'blue' and 'green' strategies every 2 minutes"
echo "3. Run a test client that executes queries continuously"
echo ""

# Function to cleanup on exit
cleanup() {
    echo -e "\n\nStopping mock server..."
    kill $SERVER_PID 2>/dev/null
    exit 0
}

# Set trap to cleanup on script exit
trap cleanup EXIT INT TERM

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not found in PATH"
    exit 1
fi

# Start the mock server in background
echo "Starting mock gRPC server..."
python3 mock_grpc_server.py &
SERVER_PID=$!

# Wait for server to start
echo "Waiting for server to start..."
sleep 3

# Check if server is running
if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo "Error: Mock server failed to start"
    echo "Please check if port 50052 is available"
    exit 1
fi

echo "Mock server started successfully (PID: $SERVER_PID)"
echo ""
echo "Starting test client in 2 seconds..."
echo "Press Ctrl+C to stop both server and client"
echo ""
sleep 2

# Run the test client (this will run in foreground)
python3 test_mock_server.py

# Script will exit and cleanup when client exits