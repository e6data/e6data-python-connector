# Zero Downtime Deployment - Migration Guide

## Overview

This guide provides step-by-step instructions for migrating existing applications to use the zero downtime deployment features in the e6data Python Connector. It covers compatibility considerations, migration strategies, and best practices.

## Compatibility Assessment

### 1. Version Compatibility

#### Supported Versions
- **Python**: 3.7+
- **e6data Python Connector**: 2.0+
- **e6data Cluster**: All versions with blue-green deployment support

#### Breaking Changes
- No breaking changes for existing applications
- Zero downtime features are automatically enabled
- Existing code works without modifications

### 2. Dependency Assessment

#### Required Dependencies
```python
# No additional dependencies required
# All zero downtime features are built into the connector
```

#### Optional Dependencies
```python
# For enhanced monitoring and debugging
pip install psutil  # Memory monitoring
pip install prometheus_client  # Metrics collection
```

## Migration Strategies

### 1. No-Change Migration (Recommended)

**Description**: Existing applications automatically benefit from zero downtime deployment without any code changes.

**Requirements**:
- Update to latest connector version
- No application code changes needed
- Automatic strategy detection and switching

**Implementation**:
```python
# Existing code continues to work as-is
from e6data_python_connector.e6data_grpc import Connection

# No changes needed
connection = Connection(
    host='your-host',
    port=80,
    username='your-email',
    password='your-token'
)

cursor = connection.cursor()
cursor.execute("SELECT * FROM your_table")
results = cursor.fetchall()
```

**Benefits**:
- Zero development effort
- Immediate zero downtime benefits
- No risk of introducing bugs

### 2. Enhanced Migration (Optional)

**Description**: Optionally enhance applications with explicit strategy monitoring and configuration.

**Requirements**:
- Update to latest connector version
- Add optional monitoring and configuration
- Enhanced error handling

**Implementation**:
```python
from e6data_python_connector.e6data_grpc import Connection
import logging

# Enhanced logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Enhanced configuration
grpc_options = {
    'keepalive_timeout_ms': 60000,
    'keepalive_time_ms': 30000,
    'max_receive_message_length': 100 * 1024 * 1024,
    'max_send_message_length': 100 * 1024 * 1024,
}

connection = Connection(
    host='your-host',
    port=80,
    username='your-email',
    password='your-token',
    grpc_options=grpc_options
)

# Enhanced error handling
try:
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM your_table")
    results = cursor.fetchall()
except Exception as e:
    logger.error(f"Query failed: {e}")
    # Application-specific error handling
```

## Step-by-Step Migration Process

### Phase 1: Preparation (1-2 hours)

#### Step 1: Backup Current Installation
```bash
# Create backup of current connector
pip list | grep e6data-python-connector > current_version.txt
pip freeze > requirements_backup.txt
```

#### Step 2: Update Connector
```bash
# Update to latest version
pip install --upgrade e6data-python-connector

# Verify installation
python -c "from e6data_python_connector import __version__; print(__version__)"
```

#### Step 3: Verify Compatibility
```python
# Test basic connection
from e6data_python_connector.e6data_grpc import Connection

def test_connection():
    try:
        connection = Connection(
            host='your-host',
            port=80,
            username='your-email',
            password='your-token'
        )
        session_id = connection.get_session_id
        print(f"Connection successful: {session_id[:8]}...")
        connection.close()
        return True
    except Exception as e:
        print(f"Connection failed: {e}")
        return False

if __name__ == "__main__":
    success = test_connection()
    print(f"Migration readiness: {'READY' if success else 'NOT READY'}")
```

### Phase 2: Testing (2-4 hours)

#### Step 1: Unit Testing
```python
# Test basic functionality
import unittest
from e6data_python_connector.e6data_grpc import Connection

class TestMigration(unittest.TestCase):
    def setUp(self):
        self.connection = Connection(
            host='your-host',
            port=80,
            username='your-email',
            password='your-token'
        )
    
    def test_connection(self):
        """Test basic connection functionality"""
        session_id = self.connection.get_session_id
        self.assertIsNotNone(session_id)
    
    def test_query_execution(self):
        """Test query execution"""
        cursor = self.connection.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        self.assertEqual(result[0], 1)
        cursor.close()
    
    def tearDown(self):
        self.connection.close()

if __name__ == "__main__":
    unittest.main()
```

#### Step 2: Integration Testing
```python
# Test with existing application code
def test_existing_application():
    """Test existing application code with new connector"""
    # Run your existing application code
    # Verify it works with zero downtime features
    pass

def test_strategy_switching():
    """Test strategy switching behavior"""
    from e6data_python_connector.e6data_grpc import _get_active_strategy
    
    # Test strategy detection
    strategy = _get_active_strategy()
    print(f"Current strategy: {strategy}")
    
    # Test multiple connections
    connections = []
    for i in range(5):
        conn = Connection(
            host='your-host',
            port=80,
            username='your-email',
            password='your-token'
        )
        connections.append(conn)
    
    # All connections should use same strategy
    for conn in connections:
        conn.close()
```

### Phase 3: Deployment (1-2 hours)

#### Step 1: Staged Deployment
```bash
# Deploy to staging environment first
# Test with staging data and workloads
# Verify zero downtime behavior

# Deploy to production
# Monitor for issues
# Verify strategy switching works
```

#### Step 2: Monitoring Setup
```python
# Set up monitoring for zero downtime features
import logging
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Monitor strategy changes
def monitor_strategy_changes():
    from e6data_python_connector.e6data_grpc import _get_active_strategy
    
    previous_strategy = None
    while True:
        current_strategy = _get_active_strategy()
        if current_strategy != previous_strategy:
            print(f"Strategy changed: {previous_strategy} -> {current_strategy}")
            previous_strategy = current_strategy
        time.sleep(10)

# Start monitoring in background
import threading
monitor_thread = threading.Thread(target=monitor_strategy_changes, daemon=True)
monitor_thread.start()
```

## Migration Patterns

### 1. Simple Application Migration

**Before (Existing Code)**:
```python
from e6data_python_connector.e6data_grpc import Connection

def run_query(query):
    connection = Connection(
        host='host',
        port=80,
        username='user',
        password='pass'
    )
    
    cursor = connection.cursor()
    cursor.execute(query)
    results = cursor.fetchall()
    
    cursor.close()
    connection.close()
    
    return results
```

**After (No Changes Needed)**:
```python
# Same code works with zero downtime features
from e6data_python_connector.e6data_grpc import Connection

def run_query(query):
    connection = Connection(
        host='host',
        port=80,
        username='user',
        password='pass'
    )
    
    cursor = connection.cursor()
    cursor.execute(query)
    results = cursor.fetchall()
    
    cursor.close()
    connection.close()
    
    return results
```

### 2. Connection Pool Migration

**Before**:
```python
import threading
from queue import Queue

class ConnectionPool:
    def __init__(self, size=10):
        self.pool = Queue()
        for _ in range(size):
            conn = Connection(
                host='host',
                port=80,
                username='user',
                password='pass'
            )
            self.pool.put(conn)
    
    def get_connection(self):
        return self.pool.get()
    
    def return_connection(self, conn):
        self.pool.put(conn)
```

**After (Enhanced with Monitoring)**:
```python
import threading
from queue import Queue
import logging

class ConnectionPool:
    def __init__(self, size=10):
        self.pool = Queue()
        self.logger = logging.getLogger(__name__)
        
        # Enhanced gRPC options for zero downtime
        grpc_options = {
            'keepalive_timeout_ms': 60000,
            'keepalive_time_ms': 30000,
        }
        
        for _ in range(size):
            conn = Connection(
                host='host',
                port=80,
                username='user',
                password='pass',
                grpc_options=grpc_options
            )
            self.pool.put(conn)
    
    def get_connection(self):
        conn = self.pool.get()
        # Monitor connection health
        if not conn.check_connection():
            self.logger.warning("Connection unhealthy, creating new one")
            conn = self.create_new_connection()
        return conn
    
    def return_connection(self, conn):
        self.pool.put(conn)
    
    def create_new_connection(self):
        return Connection(
            host='host',
            port=80,
            username='user',
            password='pass'
        )
```

### 3. Long-Running Application Migration

**Before**:
```python
def long_running_application():
    connection = Connection(
        host='host',
        port=80,
        username='user',
        password='pass'
    )
    
    while True:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM monitoring_table")
        results = cursor.fetchall()
        cursor.close()
        
        process_results(results)
        time.sleep(60)
```

**After (Enhanced with Error Handling)**:
```python
import time
import logging

def long_running_application():
    logger = logging.getLogger(__name__)
    
    connection = Connection(
        host='host',
        port=80,
        username='user',
        password='pass',
        grpc_options={
            'keepalive_timeout_ms': 60000,
            'keepalive_time_ms': 30000,
        }
    )
    
    while True:
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM monitoring_table")
            results = cursor.fetchall()
            cursor.close()
            
            process_results(results)
            
        except Exception as e:
            logger.error(f"Query failed: {e}")
            # Zero downtime features will handle strategy switching
            # automatically, so we just continue
            
        time.sleep(60)
```

## Migration Validation

### 1. Functionality Validation

```python
def validate_migration():
    """Validate that migration was successful"""
    
    # Test 1: Basic connectivity
    try:
        connection = Connection(
            host='your-host',
            port=80,
            username='your-email',
            password='your-token'
        )
        session_id = connection.get_session_id
        assert session_id is not None
        print("✓ Basic connectivity works")
    except Exception as e:
        print(f"✗ Basic connectivity failed: {e}")
        return False
    
    # Test 2: Query execution
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        assert result[0] == 1
        cursor.close()
        print("✓ Query execution works")
    except Exception as e:
        print(f"✗ Query execution failed: {e}")
        return False
    
    # Test 3: Strategy detection
    try:
        from e6data_python_connector.e6data_grpc import _get_active_strategy
        strategy = _get_active_strategy()
        assert strategy in ['blue', 'green']
        print(f"✓ Strategy detection works: {strategy}")
    except Exception as e:
        print(f"✗ Strategy detection failed: {e}")
        return False
    
    # Test 4: Multiple connections
    try:
        connections = []
        for i in range(5):
            conn = Connection(
                host='your-host',
                port=80,
                username='your-email',
                password='your-token'
            )
            connections.append(conn)
        
        for conn in connections:
            conn.close()
        print("✓ Multiple connections work")
    except Exception as e:
        print(f"✗ Multiple connections failed: {e}")
        return False
    
    connection.close()
    print("✓ Migration validation successful")
    return True
```

### 2. Performance Validation

```python
import time

def validate_performance():
    """Validate performance after migration"""
    
    # Test connection establishment time
    start_time = time.time()
    connection = Connection(
        host='your-host',
        port=80,
        username='your-email',
        password='your-token'
    )
    connection_time = time.time() - start_time
    
    # Test query execution time
    cursor = connection.cursor()
    start_time = time.time()
    cursor.execute("SELECT 1")
    cursor.fetchone()
    query_time = time.time() - start_time
    
    cursor.close()
    connection.close()
    
    print(f"Connection time: {connection_time:.4f}s")
    print(f"Query time: {query_time:.4f}s")
    
    # Validate performance is acceptable
    assert connection_time < 5.0, f"Connection time too slow: {connection_time:.4f}s"
    assert query_time < 1.0, f"Query time too slow: {query_time:.4f}s"
    
    print("✓ Performance validation successful")
```

## Rollback Procedures

### 1. Quick Rollback

```bash
# Rollback to previous version
pip install e6data-python-connector==<previous_version>

# Verify rollback
python -c "from e6data_python_connector import __version__; print(__version__)"
```

### 2. Configuration Rollback

```python
# Remove zero downtime configuration
import os

# Remove environment variables
env_vars_to_remove = [
    'E6DATA_STRATEGY_CACHE_TIMEOUT',
    'E6DATA_MAX_RETRY_ATTEMPTS',
    'E6DATA_STRATEGY_LOG_LEVEL'
]

for var in env_vars_to_remove:
    if var in os.environ:
        del os.environ[var]
```

## Best Practices

### 1. Migration Planning

- **Test in staging first**: Always test migration in staging environment
- **Monitor closely**: Monitor application behavior during migration
- **Have rollback plan**: Prepare rollback procedures before migration
- **Document changes**: Document all configuration changes

### 2. Configuration Management

- **Use environment variables**: Configure using environment variables
- **Version control**: Keep configuration in version control
- **Separate environments**: Use different configurations for different environments
- **Validate configuration**: Validate configuration parameters

### 3. Monitoring and Alerting

- **Set up monitoring**: Monitor strategy changes and performance
- **Configure alerts**: Set up alerts for issues
- **Log analysis**: Analyze logs for patterns and issues
- **Health checks**: Implement health checks for zero downtime features

### 4. Testing Strategy

- **Automated testing**: Implement automated tests for migration
- **Load testing**: Test under production load
- **Failover testing**: Test strategy switching scenarios
- **Recovery testing**: Test error recovery scenarios

## Common Migration Issues

### 1. Version Conflicts

**Issue**: Dependency version conflicts during upgrade

**Solution**:
```bash
# Create clean environment
python -m venv clean_env
source clean_env/bin/activate
pip install e6data-python-connector
```

### 2. Configuration Issues

**Issue**: Application behavior changes due to new configuration

**Solution**:
```python
# Explicit configuration
connection = Connection(
    host='your-host',
    port=80,
    username='your-email',
    password='your-token',
    grpc_options={
        'keepalive_timeout_ms': 60000,  # Explicit timeout
        'keepalive_time_ms': 30000,     # Explicit keepalive
    }
)
```

### 3. Performance Issues

**Issue**: Slower performance after migration

**Solution**:
```python
# Performance tuning
grpc_options = {
    'keepalive_timeout_ms': 120000,  # Increase timeout
    'keepalive_time_ms': 60000,      # Increase keepalive
    'max_receive_message_length': 200 * 1024 * 1024,  # Increase limits
    'max_send_message_length': 200 * 1024 * 1024,
}
```

## Support and Resources

### 1. Documentation References

- [API Reference](api-reference.md)
- [Configuration Guide](configuration.md)
- [Troubleshooting Guide](troubleshooting.md)

### 2. Support Channels

- GitHub Issues: Report bugs and issues
- Documentation: Comprehensive guides and examples
- Community: User community and discussions

### 3. Migration Checklist

- [ ] Backup current installation
- [ ] Update connector version
- [ ] Test basic functionality
- [ ] Validate performance
- [ ] Deploy to staging
- [ ] Monitor behavior
- [ ] Deploy to production
- [ ] Set up monitoring
- [ ] Document changes
- [ ] Train team members

This comprehensive migration guide provides all the necessary information and tools for successfully migrating to zero downtime deployment features.