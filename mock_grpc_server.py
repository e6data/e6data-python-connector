#!/usr/bin/env python3
"""
Mock gRPC server for testing blue-green deployment strategy.
This server simulates the e6data engine service and switches strategies every 2 minutes.
"""

import grpc
from concurrent import futures
import time
import threading
import logging
import random
import struct
from datetime import datetime
import uuid
from io import BytesIO

from e6data_python_connector.server import e6x_engine_pb2, e6x_engine_pb2_grpc
from e6data_python_connector.datainputstream import DataInputStream
from e6data_python_connector.typeId import TypeId

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global strategy management
class StrategyManager:
    def __init__(self):
        self.current_strategy = "blue"
        self.switch_time = time.time()
        self.lock = threading.Lock()
        self.pending_strategy = None
        self.strategy_switch_interval = 120  # 2 minutes
        
    def get_current_strategy(self):
        with self.lock:
            return self.current_strategy
    
    def get_new_strategy_if_changed(self):
        """Returns the new strategy if it's time to switch, None otherwise."""
        with self.lock:
            current_time = time.time()
            if current_time - self.switch_time >= self.strategy_switch_interval:
                # Time to switch
                self.pending_strategy = "green" if self.current_strategy == "blue" else "blue"
                return self.pending_strategy
            return None
    
    def apply_pending_strategy(self):
        """Apply the pending strategy switch."""
        with self.lock:
            if self.pending_strategy:
                old_strategy = self.current_strategy
                self.current_strategy = self.pending_strategy
                self.pending_strategy = None
                self.switch_time = time.time()
                logger.info(f"Strategy switched from {old_strategy} to {self.current_strategy}")
    
    def check_strategy_header(self, context):
        """Check if the client sent the correct strategy header."""
        metadata = dict(context.invocation_metadata())
        client_strategy = metadata.get('strategy')
        current_strategy = self.get_current_strategy()
        
        if client_strategy and client_strategy != current_strategy:
            # Client has wrong strategy
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, 
                         f"Wrong strategy. Status: 456. Expected: {current_strategy}, Got: {client_strategy}")
        
        return current_strategy

# Global strategy manager instance
strategy_manager = StrategyManager()

# Mock data storage
class MockDataStore:
    def __init__(self):
        self.sessions = {}
        self.queries = {}
        self.query_results = {}
        self.schemas = {
            "default": ["sales", "marketing", "finance"],
            "analytics": ["reports", "dashboards", "metrics"]
        }
        self.tables = {
            "sales": ["orders", "customers", "products"],
            "marketing": ["campaigns", "leads", "conversions"],
            "finance": ["transactions", "accounts", "budgets"]
        }
        self.columns = {
            "orders": [
                {"fieldName": "order_id", "fieldType": "LONG"},
                {"fieldName": "customer_id", "fieldType": "LONG"},
                {"fieldName": "order_date", "fieldType": "TIMESTAMP"},
                {"fieldName": "total_amount", "fieldType": "DOUBLE"},
                {"fieldName": "status", "fieldType": "STRING"}
            ],
            "customers": [
                {"fieldName": "customer_id", "fieldType": "LONG"},
                {"fieldName": "name", "fieldType": "STRING"},
                {"fieldName": "email", "fieldType": "STRING"},
                {"fieldName": "created_date", "fieldType": "DATE"}
            ]
        }

# Global data store
data_store = MockDataStore()

def create_mock_result_batch(query_string, batch_number=0):
    """Create a mock result batch based on the query."""
    # Simple mock data generation
    buffer = BytesIO()
    
    # Determine result based on query
    if "SELECT 1" in query_string.upper():
        # Single row, single column
        write_long(buffer, 1)  # row count
        write_long(buffer, 1)  # value
    elif "SELECT 2" in query_string.upper():
        # Single row, single column
        write_long(buffer, 1)  # row count
        write_long(buffer, 2)  # value
    elif "SELECT 3" in query_string.upper():
        # Single row, single column
        write_long(buffer, 1)  # row count
        write_long(buffer, 3)  # value
    else:
        # Generic result with multiple rows
        row_count = 5
        write_long(buffer, row_count)
        
        for i in range(row_count):
            write_long(buffer, i + 1 + (batch_number * 5))  # id
            write_string(buffer, f"Name_{i + 1 + (batch_number * 5)}")  # name
            write_double(buffer, random.uniform(100.0, 1000.0))  # amount
            write_timestamp(buffer, int(time.time() * 1000))  # timestamp
    
    return buffer.getvalue()

def write_long(buffer, value):
    """Write a long value to buffer."""
    buffer.write(struct.pack('>q', value))

def write_double(buffer, value):
    """Write a double value to buffer."""
    buffer.write(struct.pack('>d', value))

def write_string(buffer, value):
    """Write a string value to buffer."""
    if value is None:
        buffer.write(struct.pack('>i', -1))
    else:
        encoded = value.encode('utf-8')
        buffer.write(struct.pack('>i', len(encoded)))
        buffer.write(encoded)

def write_timestamp(buffer, value):
    """Write a timestamp value to buffer."""
    buffer.write(struct.pack('>q', value))

def create_mock_metadata(query_string):
    """Create mock metadata for a query result."""
    buffer = BytesIO()
    
    # Determine columns based on query
    if any(x in query_string.upper() for x in ["SELECT 1", "SELECT 2", "SELECT 3"]):
        # Single column result
        write_long(buffer, 10)  # total row count
        write_long(buffer, 1)   # column count
        
        # Column info
        write_string(buffer, "value")  # column name
        write_long(buffer, TypeId.BIGINT_TYPE)  # column type
    else:
        # Multi-column result
        write_long(buffer, 50)  # total row count
        write_long(buffer, 4)   # column count
        
        # Column info
        columns = [
            ("id", TypeId.BIGINT_TYPE),
            ("name", TypeId.STRING_TYPE),
            ("amount", TypeId.DOUBLE_TYPE),
            ("created_at", TypeId.TIMESTAMP_TYPE)
        ]
        
        for col_name, col_type in columns:
            write_string(buffer, col_name)
            write_long(buffer, col_type)
    
    return buffer.getvalue()

class MockQueryEngineService(e6x_engine_pb2_grpc.QueryEngineServiceServicer):
    
    def authenticate(self, request, context):
        """Handle authentication and return session ID."""
        # Check strategy header
        current_strategy = strategy_manager.check_strategy_header(context)
        
        # Simple authentication - accept any non-empty credentials
        if request.user and request.password:
            session_id = str(uuid.uuid4())
            data_store.sessions[session_id] = {
                "user": request.user,
                "created_at": time.time()
            }
            logger.info(f"Authenticated user {request.user} with session {session_id}")
            
            response = e6x_engine_pb2.AuthenticateResponse(sessionId=session_id)
            
            # Check if strategy is about to change
            new_strategy = strategy_manager.get_new_strategy_if_changed()
            if new_strategy:
                response.new_strategy = new_strategy
                logger.info(f"Notifying client about pending strategy change to: {new_strategy}")
            
            return response
        else:
            context.abort(grpc.StatusCode.UNAUTHENTICATED, "Invalid credentials")
    
    def prepareStatement(self, request, context):
        """Prepare a SQL statement for execution."""
        # Check strategy header
        current_strategy = strategy_manager.check_strategy_header(context)
        
        query_id = str(uuid.uuid4())
        engine_ip = "127.0.0.1"
        
        data_store.queries[query_id] = {
            "session_id": request.sessionId,
            "query": request.queryString,
            "schema": request.schema,
            "status": "prepared",
            "created_at": time.time()
        }
        
        logger.info(f"Prepared query {query_id}: {request.queryString[:50]}...")
        
        response = e6x_engine_pb2.PrepareStatementResponse(
            queryId=query_id,
            engineIP=engine_ip
        )
        
        # Check if strategy is about to change
        new_strategy = strategy_manager.get_new_strategy_if_changed()
        if new_strategy:
            response.new_strategy = new_strategy
            logger.info(f"Notifying client about pending strategy change to: {new_strategy}")
        
        return response
    
    def prepareStatementV2(self, request, context):
        """Prepare a SQL statement for execution (V2)."""
        # Check strategy header
        current_strategy = strategy_manager.check_strategy_header(context)
        
        query_id = str(uuid.uuid4())
        engine_ip = "127.0.0.1"
        
        data_store.queries[query_id] = {
            "session_id": request.sessionId,
            "query": request.queryString,
            "schema": request.schema,
            "catalog": request.catalog,
            "status": "prepared",
            "created_at": time.time()
        }
        
        logger.info(f"Prepared query V2 {query_id}: {request.queryString[:50]}...")
        
        response = e6x_engine_pb2.PrepareStatementResponse(
            queryId=query_id,
            engineIP=engine_ip
        )
        
        # Check if strategy is about to change
        new_strategy = strategy_manager.get_new_strategy_if_changed()
        if new_strategy:
            response.new_strategy = new_strategy
            logger.info(f"Notifying client about pending strategy change to: {new_strategy}")
        
        return response
    
    def executeStatement(self, request, context):
        """Execute a prepared statement."""
        # Check strategy header
        current_strategy = strategy_manager.check_strategy_header(context)
        
        if request.queryId in data_store.queries:
            data_store.queries[request.queryId]["status"] = "executing"
            data_store.queries[request.queryId]["executed_at"] = time.time()
            
            # Generate mock results
            query_string = data_store.queries[request.queryId]["query"]
            data_store.query_results[request.queryId] = {
                "metadata": create_mock_metadata(query_string),
                "batches": [create_mock_result_batch(query_string, i) for i in range(3)],
                "current_batch": 0
            }
            
            logger.info(f"Executed query {request.queryId}")
            
            response = e6x_engine_pb2.ExecuteStatementResponse()
            
            # Check if strategy is about to change
            new_strategy = strategy_manager.get_new_strategy_if_changed()
            if new_strategy:
                response.new_strategy = new_strategy
                logger.info(f"Notifying client about pending strategy change to: {new_strategy}")
            
            return response
        else:
            context.abort(grpc.StatusCode.NOT_FOUND, "Query not found")
    
    def executeStatementV2(self, request, context):
        """Execute a prepared statement (V2)."""
        return self.executeStatement(request, context)
    
    def getResultMetadata(self, request, context):
        """Get metadata for query results."""
        # Check strategy header
        current_strategy = strategy_manager.check_strategy_header(context)
        
        if request.queryId in data_store.query_results:
            metadata = data_store.query_results[request.queryId]["metadata"]
            
            response = e6x_engine_pb2.GetResultMetadataResponse(
                resultMetaData=metadata
            )
            
            # Check if strategy is about to change
            new_strategy = strategy_manager.get_new_strategy_if_changed()
            if new_strategy:
                response.new_strategy = new_strategy
                logger.info(f"Notifying client about pending strategy change to: {new_strategy}")
            
            return response
        else:
            context.abort(grpc.StatusCode.NOT_FOUND, "Query results not found")
    
    def getNextResultBatch(self, request, context):
        """Get the next batch of results."""
        # Check strategy header
        current_strategy = strategy_manager.check_strategy_header(context)
        
        if request.queryId in data_store.query_results:
            results = data_store.query_results[request.queryId]
            current_batch = results["current_batch"]
            
            if current_batch < len(results["batches"]):
                batch_data = results["batches"][current_batch]
                results["current_batch"] += 1
            else:
                batch_data = b""  # No more data
            
            response = e6x_engine_pb2.GetNextResultBatchResponse(
                resultBatch=batch_data
            )
            
            # Check if strategy is about to change
            new_strategy = strategy_manager.get_new_strategy_if_changed()
            if new_strategy:
                response.new_strategy = new_strategy
                logger.info(f"Notifying client about pending strategy change to: {new_strategy}")
            
            return response
        else:
            context.abort(grpc.StatusCode.NOT_FOUND, "Query results not found")
    
    def status(self, request, context):
        """Get query status."""
        # Check strategy header
        current_strategy = strategy_manager.check_strategy_header(context)
        
        if request.queryId in data_store.queries:
            query_info = data_store.queries[request.queryId]
            is_complete = query_info["status"] in ["completed", "executed"]
            row_count = 10 if is_complete else 0
            
            response = e6x_engine_pb2.StatusResponse(
                status=is_complete,
                rowCount=row_count
            )
            
            # Check if strategy is about to change
            new_strategy = strategy_manager.get_new_strategy_if_changed()
            if new_strategy:
                response.new_strategy = new_strategy
                logger.info(f"Notifying client about pending strategy change to: {new_strategy}")
            
            return response
        else:
            context.abort(grpc.StatusCode.NOT_FOUND, "Query not found")
    
    def clearOrCancelQuery(self, request, context):
        """Clear or cancel a query."""
        # Check strategy header
        current_strategy = strategy_manager.check_strategy_header(context)
        
        if request.queryId in data_store.queries:
            data_store.queries[request.queryId]["status"] = "cleared"
            if request.queryId in data_store.query_results:
                del data_store.query_results[request.queryId]
            
            logger.info(f"Cleared query {request.queryId}")
            
            response = e6x_engine_pb2.ClearOrCancelQueryResponse()
            
            # Check if strategy is about to change
            new_strategy = strategy_manager.get_new_strategy_if_changed()
            if new_strategy:
                response.new_strategy = new_strategy
                logger.info(f"Notifying client about pending strategy change to: {new_strategy}")
                # Apply the strategy change after clearing
                strategy_manager.apply_pending_strategy()
            
            return response
        else:
            # Still return success even if query not found
            return e6x_engine_pb2.ClearOrCancelQueryResponse()
    
    def clear(self, request, context):
        """Clear query results."""
        # Similar to clearOrCancelQuery
        clear_request = e6x_engine_pb2.ClearOrCancelQueryRequest(
            queryId=request.queryId,
            sessionId=request.sessionId,
            engineIP=request.engineIP
        )
        return self.clearOrCancelQuery(clear_request, context)
    
    def cancelQuery(self, request, context):
        """Cancel a running query."""
        # Check strategy header
        current_strategy = strategy_manager.check_strategy_header(context)
        
        if request.queryId in data_store.queries:
            data_store.queries[request.queryId]["status"] = "cancelled"
            logger.info(f"Cancelled query {request.queryId}")
        
        response = e6x_engine_pb2.CancelQueryResponse()
        
        # Check if strategy is about to change
        new_strategy = strategy_manager.get_new_strategy_if_changed()
        if new_strategy:
            response.new_strategy = new_strategy
            logger.info(f"Notifying client about pending strategy change to: {new_strategy}")
        
        return response
    
    def getSchemaNamesV2(self, request, context):
        """Get list of schema names."""
        # Check strategy header
        current_strategy = strategy_manager.check_strategy_header(context)
        
        catalog = request.catalog or "default"
        schemas = data_store.schemas.get(catalog, [])
        
        response = e6x_engine_pb2.GetSchemaNamesResponse(schemas=schemas)
        
        # Check if strategy is about to change
        new_strategy = strategy_manager.get_new_strategy_if_changed()
        if new_strategy:
            response.new_strategy = new_strategy
            logger.info(f"Notifying client about pending strategy change to: {new_strategy}")
        
        return response
    
    def getTablesV2(self, request, context):
        """Get list of tables in a schema."""
        # Check strategy header
        current_strategy = strategy_manager.check_strategy_header(context)
        
        tables = data_store.tables.get(request.schema, [])
        
        response = e6x_engine_pb2.GetTablesResponse(tables=tables)
        
        # Check if strategy is about to change
        new_strategy = strategy_manager.get_new_strategy_if_changed()
        if new_strategy:
            response.new_strategy = new_strategy
            logger.info(f"Notifying client about pending strategy change to: {new_strategy}")
        
        return response
    
    def getColumnsV2(self, request, context):
        """Get list of columns in a table."""
        # Check strategy header
        current_strategy = strategy_manager.check_strategy_header(context)
        
        columns = data_store.columns.get(request.table, [])
        field_info = [
            e6x_engine_pb2.GFieldInfo(
                fieldName=col["fieldName"],
                fieldType=col["fieldType"]
            )
            for col in columns
        ]
        
        response = e6x_engine_pb2.GetColumnsResponse(fieldInfo=field_info)
        
        # Check if strategy is about to change
        new_strategy = strategy_manager.get_new_strategy_if_changed()
        if new_strategy:
            response.new_strategy = new_strategy
            logger.info(f"Notifying client about pending strategy change to: {new_strategy}")
        
        return response
    
    def explainAnalyze(self, request, context):
        """Get query execution plan."""
        # Check strategy header
        current_strategy = strategy_manager.check_strategy_header(context)
        
        if request.queryId in data_store.queries:
            query_info = data_store.queries[request.queryId]
            
            # Mock execution plan
            explain_json = {
                "plan": {
                    "type": "Project",
                    "cost": 1000,
                    "rows": 10,
                    "children": [{
                        "type": "TableScan",
                        "table": "mock_table",
                        "cost": 500,
                        "rows": 100
                    }]
                },
                "total_query_time": 150,
                "executionQueueingTime": 10,
                "parsingTime": 5
            }
            
            import json
            response = e6x_engine_pb2.ExplainAnalyzeResponse(
                explainAnalyze=json.dumps(explain_json),
                isCached=False,
                parsingTime=5,
                queueingTime=10
            )
            
            # Check if strategy is about to change
            new_strategy = strategy_manager.get_new_strategy_if_changed()
            if new_strategy:
                response.new_strategy = new_strategy
                logger.info(f"Notifying client about pending strategy change to: {new_strategy}")
            
            return response
        else:
            context.abort(grpc.StatusCode.NOT_FOUND, "Query not found")
    
    # Implement remaining methods as needed...
    def getSchemaNames(self, request, context):
        """Legacy method - redirects to V2."""
        v2_request = e6x_engine_pb2.GetSchemaNamesV2Request(
            sessionId=request.sessionId,
            catalog="default"
        )
        return self.getSchemaNamesV2(v2_request, context)
    
    def getTables(self, request, context):
        """Legacy method - redirects to V2."""
        v2_request = e6x_engine_pb2.GetTablesV2Request(
            sessionId=request.sessionId,
            schema=request.schema,
            catalog="default"
        )
        return self.getTablesV2(v2_request, context)
    
    def getColumns(self, request, context):
        """Legacy method - redirects to V2."""
        v2_request = e6x_engine_pb2.GetColumnsV2Request(
            sessionId=request.sessionId,
            schema=request.schema,
            table=request.table,
            catalog="default"
        )
        return self.getColumnsV2(v2_request, context)

def serve():
    """Start the gRPC server."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    e6x_engine_pb2_grpc.add_QueryEngineServiceServicer_to_server(
        MockQueryEngineService(), server
    )
    
    # Listen on port 50052
    port = 50052
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    
    logger.info(f"Mock e6data gRPC server started on port {port}")
    logger.info(f"Initial strategy: {strategy_manager.get_current_strategy()}")
    logger.info(f"Strategy will switch every {strategy_manager.strategy_switch_interval} seconds")
    
    # Start strategy monitor thread
    def monitor_strategy():
        while True:
            time.sleep(10)  # Check every 10 seconds
            current = strategy_manager.get_current_strategy()
            new = strategy_manager.get_new_strategy_if_changed()
            if new:
                logger.info(f"Strategy change pending: {current} -> {new}")
    
    monitor_thread = threading.Thread(target=monitor_strategy, daemon=True)
    monitor_thread.start()
    
    try:
        while True:
            time.sleep(86400)  # Sleep for a day
    except KeyboardInterrupt:
        server.stop(0)
        logger.info("Server stopped")

if __name__ == '__main__':
    serve()