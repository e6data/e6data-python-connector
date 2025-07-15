# Zero Downtime Deployment - Troubleshooting Guide

## Overview

This guide provides comprehensive troubleshooting information for zero downtime deployment issues in the e6data Python Connector. It covers common problems, diagnostic steps, and solutions.

## Common Issues and Solutions

### 1. Strategy Detection Failures

#### Problem: Connection fails during strategy detection

**Symptoms**:
- Connection timeouts during authentication
- "No valid strategy found" errors
- Repeated authentication attempts

**Diagnostic Steps**:
```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Check strategy detection
from e6data_python_connector.e6data_grpc import _get_active_strategy, _clear_strategy_cache
print(f"Current strategy: {_get_active_strategy()}")

# Clear cache and retry
_clear_strategy_cache()
```

**Solutions**:
1. **Check Network Connectivity**:
   ```bash
   # Test connectivity to e6data cluster
   telnet <host> <port>
   ```

2. **Verify Credentials**:
   ```python
   # Test with different credentials
   connection = Connection(
       host="your-host",
       port=80,
       username="your-email",
       password="your-token"
   )
   ```

3. **Check Cluster Status**:
   ```python
   # Use cluster manager to check status
   from e6data_python_connector.cluster_manager import ClusterManager
   cm = ClusterManager(host="your-host", port=80, user="email", password="token")
   status = cm.get_cluster_status()
   ```

### 2. 456 Error Handling

#### Problem: Frequent 456 errors during operations

**Symptoms**:
- "Wrong strategy. Status: 456" errors
- Strategy mismatch errors
- Connection retries

**Diagnostic Steps**:
```python
# Monitor 456 errors
import logging
logger = logging.getLogger('e6data_python_connector.e6data_grpc')
logger.setLevel(logging.INFO)

# Check strategy state
from e6data_python_connector.e6data_grpc import _get_shared_strategy
shared_state = _get_shared_strategy()
print(f"Strategy state: {dict(shared_state)}")
```

**Solutions**:
1. **Clear Strategy Cache**:
   ```python
   from e6data_python_connector.e6data_grpc import _clear_strategy_cache
   _clear_strategy_cache()
   ```

2. **Check Strategy Synchronization**:
   ```python
   # Verify strategy consistency
   from e6data_python_connector.e6data_grpc import _get_active_strategy
   
   # Multiple calls should return same strategy
   for i in range(5):
       strategy = _get_active_strategy()
       print(f"Call {i}: {strategy}")
   ```

3. **Implement Retry Logic**:
   ```python
   import time
   from grpc import StatusCode
   
   def retry_with_strategy_detection(func, max_retries=3):
       for attempt in range(max_retries):
           try:
               return func()
           except Exception as e:
               if '456' in str(e) and attempt < max_retries - 1:
                   _clear_strategy_cache()
                   time.sleep(0.1 * (2 ** attempt))  # Exponential backoff
                   continue
               raise
   ```

### 3. Query Strategy Inconsistencies

#### Problem: Queries using wrong strategy

**Symptoms**:
- Queries fail with strategy errors
- Inconsistent query behavior
- Strategy mismatch during execution

**Diagnostic Steps**:
```python
# Check query strategy mapping
from e6data_python_connector.e6data_grpc import _get_shared_strategy

def debug_query_strategies():
    shared_state = _get_shared_strategy()
    query_map = shared_state.get('query_strategy_map', {})
    print(f"Active queries: {dict(query_map)}")
    print(f"Active strategy: {shared_state.get('active_strategy')}")
    print(f"Pending strategy: {shared_state.get('pending_strategy')}")
```

**Solutions**:
1. **Clean Query Mappings**:
   ```python
   from e6data_python_connector.e6data_grpc import _cleanup_query_strategy
   
   # Clean up specific query
   _cleanup_query_strategy("problematic_query_id")
   ```

2. **Force Strategy Refresh**:
   ```python
   from e6data_python_connector.e6data_grpc import _clear_strategy_cache, _apply_pending_strategy
   
   # Clear cache and apply pending changes
   _clear_strategy_cache()
   _apply_pending_strategy()
   ```

### 4. Memory Issues

#### Problem: Memory leaks or excessive memory usage

**Symptoms**:
- Growing memory usage over time
- OutOfMemory errors
- Slow application performance

**Diagnostic Steps**:
```python
# Monitor memory usage
import psutil
import os

def monitor_memory():
    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()
    print(f"RSS: {memory_info.rss / 1024 / 1024:.2f} MB")
    print(f"VMS: {memory_info.vms / 1024 / 1024:.2f} MB")

# Check query mapping size
from e6data_python_connector.e6data_grpc import _get_shared_strategy

def check_query_mapping_size():
    shared_state = _get_shared_strategy()
    query_map = shared_state.get('query_strategy_map', {})
    print(f"Query mapping size: {len(query_map)}")
    return query_map
```

**Solutions**:
1. **Clean Up Query Mappings**:
   ```python
   from e6data_python_connector.e6data_grpc import _get_shared_strategy
   
   def cleanup_stale_queries():
       shared_state = _get_shared_strategy()
       query_map = shared_state.get('query_strategy_map', {})
       
       # Clear all mappings (use cautiously)
       if isinstance(query_map, dict):
           query_map.clear()
       
       shared_state['query_strategy_map'] = query_map
   ```

2. **Implement Periodic Cleanup**:
   ```python
   import threading
   import time
   
   def periodic_cleanup():
       while True:
           time.sleep(300)  # 5 minutes
           try:
               # Clean up old query mappings
               cleanup_stale_queries()
           except Exception as e:
               print(f"Cleanup error: {e}")
   
   # Start cleanup thread
   cleanup_thread = threading.Thread(target=periodic_cleanup, daemon=True)
   cleanup_thread.start()
   ```

### 5. Performance Issues

#### Problem: Slow strategy detection or transitions

**Symptoms**:
- Slow connection establishment
- Timeouts during operations
- High latency

**Diagnostic Steps**:
```python
import time
from e6data_python_connector.e6data_grpc import _get_active_strategy, _clear_strategy_cache

def benchmark_strategy_operations():
    # Test cache hit performance
    start_time = time.time()
    strategy = _get_active_strategy()
    cache_hit_time = time.time() - start_time
    print(f"Cache hit time: {cache_hit_time:.4f}s")
    
    # Test cache miss performance
    _clear_strategy_cache()
    start_time = time.time()
    strategy = _get_active_strategy()
    cache_miss_time = time.time() - start_time
    print(f"Cache miss time: {cache_miss_time:.4f}s")
```

**Solutions**:
1. **Optimize Cache TTL**:
   ```python
   # Adjust cache timeout (in e6data_grpc.py)
   STRATEGY_CACHE_TIMEOUT = 600  # 10 minutes instead of 5
   ```

2. **Use Connection Pooling**:
   ```python
   # Implement connection pool
   class ConnectionPool:
       def __init__(self, max_connections=10):
           self.pool = []
           self.max_connections = max_connections
           self.lock = threading.Lock()
       
       def get_connection(self):
           with self.lock:
               if self.pool:
                   return self.pool.pop()
               return self.create_new_connection()
       
       def return_connection(self, conn):
           with self.lock:
               if len(self.pool) < self.max_connections:
                   self.pool.append(conn)
   ```

### 6. Concurrency Issues

#### Problem: Race conditions or deadlocks

**Symptoms**:
- Random failures under load
- Deadlock exceptions
- Inconsistent behavior

**Diagnostic Steps**:
```python
import threading
import time

def test_concurrent_access():
    """Test concurrent strategy access"""
    results = []
    
    def worker():
        try:
            strategy = _get_active_strategy()
            results.append(strategy)
        except Exception as e:
            results.append(f"Error: {e}")
    
    threads = []
    for i in range(10):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    print(f"Results: {results}")
    print(f"Unique results: {set(results)}")
```

**Solutions**:
1. **Review Lock Usage**:
   ```python
   # Ensure proper lock usage
   from e6data_python_connector.e6data_grpc import _strategy_lock
   
   def safe_strategy_operation():
       with _strategy_lock:
           # Critical section
           strategy = _get_active_strategy()
           # Process strategy
           return strategy
   ```

2. **Implement Timeout Locks**:
   ```python
   import threading
   
   def timeout_lock_operation(operation, timeout=5):
       """Execute operation with timeout lock"""
       if _strategy_lock.acquire(timeout=timeout):
           try:
               return operation()
           finally:
               _strategy_lock.release()
       else:
           raise TimeoutError("Could not acquire strategy lock")
   ```

## Diagnostic Tools and Scripts

### 1. Strategy State Inspector

```python
#!/usr/bin/env python3
"""
Strategy state inspection tool
"""

from e6data_python_connector.e6data_grpc import _get_shared_strategy, _get_active_strategy
import json
import time

def inspect_strategy_state():
    """Inspect current strategy state"""
    shared_state = _get_shared_strategy()
    
    state_info = {
        'active_strategy': shared_state.get('active_strategy'),
        'pending_strategy': shared_state.get('pending_strategy'),
        'last_check_time': shared_state.get('last_check_time'),
        'query_strategy_map': dict(shared_state.get('query_strategy_map', {})),
        'current_time': time.time()
    }
    
    print("Strategy State Inspection:")
    print(json.dumps(state_info, indent=2))
    
    # Calculate cache age
    if state_info['last_check_time']:
        cache_age = time.time() - state_info['last_check_time']
        print(f"Cache age: {cache_age:.2f} seconds")
    
    return state_info

if __name__ == "__main__":
    inspect_strategy_state()
```

### 2. Connection Tester

```python
#!/usr/bin/env python3
"""
Connection testing tool
"""

import sys
import time
from e6data_python_connector.e6data_grpc import Connection

def test_connection(host, port, username, password, iterations=5):
    """Test connection with strategy detection"""
    results = []
    
    for i in range(iterations):
        start_time = time.time()
        try:
            conn = Connection(
                host=host,
                port=port,
                username=username,
                password=password
            )
            
            # Test authentication
            session_id = conn.get_session_id
            connect_time = time.time() - start_time
            
            result = {
                'iteration': i + 1,
                'success': True,
                'connect_time': connect_time,
                'session_id': session_id[:8] + '...' if session_id else None
            }
            
            conn.close()
            
        except Exception as e:
            connect_time = time.time() - start_time
            result = {
                'iteration': i + 1,
                'success': False,
                'connect_time': connect_time,
                'error': str(e)
            }
        
        results.append(result)
        print(f"Test {i+1}: {'SUCCESS' if result['success'] else 'FAILED'} "
              f"({result['connect_time']:.2f}s)")
        
        if not result['success']:
            print(f"  Error: {result.get('error')}")
    
    # Summary
    successful = sum(1 for r in results if r['success'])
    avg_time = sum(r['connect_time'] for r in results) / len(results)
    
    print(f"\nSummary:")
    print(f"Success rate: {successful}/{len(results)} ({successful/len(results)*100:.1f}%)")
    print(f"Average connect time: {avg_time:.2f}s")
    
    return results

if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage: python connection_tester.py <host> <port> <username> <password>")
        sys.exit(1)
    
    host, port, username, password = sys.argv[1:5]
    test_connection(host, int(port), username, password)
```

### 3. Strategy Monitor

```python
#!/usr/bin/env python3
"""
Strategy monitoring tool
"""

import time
import threading
from e6data_python_connector.e6data_grpc import _get_active_strategy, _get_shared_strategy

class StrategyMonitor:
    def __init__(self):
        self.running = True
        self.previous_state = None
    
    def monitor_strategy(self, interval=10):
        """Monitor strategy changes"""
        while self.running:
            try:
                current_state = self.get_current_state()
                
                if self.previous_state and current_state != self.previous_state:
                    self.log_state_change(self.previous_state, current_state)
                
                self.previous_state = current_state
                time.sleep(interval)
                
            except Exception as e:
                print(f"Monitor error: {e}")
                time.sleep(interval)
    
    def get_current_state(self):
        """Get current strategy state"""
        shared_state = _get_shared_strategy()
        return {
            'active_strategy': shared_state.get('active_strategy'),
            'pending_strategy': shared_state.get('pending_strategy'),
            'query_count': len(shared_state.get('query_strategy_map', {})),
            'timestamp': time.time()
        }
    
    def log_state_change(self, old_state, new_state):
        """Log strategy state change"""
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] Strategy state changed:")
        
        if old_state['active_strategy'] != new_state['active_strategy']:
            print(f"  Active: {old_state['active_strategy']} -> {new_state['active_strategy']}")
        
        if old_state['pending_strategy'] != new_state['pending_strategy']:
            print(f"  Pending: {old_state['pending_strategy']} -> {new_state['pending_strategy']}")
        
        if old_state['query_count'] != new_state['query_count']:
            print(f"  Query count: {old_state['query_count']} -> {new_state['query_count']}")
    
    def stop(self):
        """Stop monitoring"""
        self.running = False

if __name__ == "__main__":
    monitor = StrategyMonitor()
    
    # Start monitoring in background
    monitor_thread = threading.Thread(target=monitor.monitor_strategy, daemon=True)
    monitor_thread.start()
    
    try:
        print("Strategy monitor started. Press Ctrl+C to stop.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping monitor...")
        monitor.stop()
```

## Environment-Specific Troubleshooting

### 1. Development Environment

**Common Issues**:
- Mock server configuration
- Local network issues
- Development credentials

**Solutions**:
```python
# Use mock server for development
def setup_development_environment():
    import subprocess
    
    # Start mock server
    mock_server = subprocess.Popen(['python', 'mock_grpc_server.py'])
    
    # Use localhost connection
    conn = Connection(
        host='localhost',
        port=50052,
        username='test@example.com',
        password='test-token'
    )
    
    return conn, mock_server
```

### 2. Production Environment

**Common Issues**:
- Network latency
- Load balancer configuration
- High concurrency

**Solutions**:
```python
# Production-optimized configuration
def create_production_connection():
    return Connection(
        host='production-host',
        port=80,
        username='production-user',
        password='production-token',
        secure=True,
        grpc_options={
            'keepalive_timeout_ms': 60000,
            'keepalive_time_ms': 30000,
            'max_receive_message_length': 100 * 1024 * 1024,
            'max_send_message_length': 100 * 1024 * 1024
        }
    )
```

## Support and Escalation

### 1. Information to Collect

When reporting issues, collect the following information:
- Python version and platform
- Connector version
- Error messages and stack traces
- Strategy state information
- Network configuration
- Timing information

### 2. Escalation Process

1. **Level 1**: Check common issues and solutions
2. **Level 2**: Use diagnostic tools and scripts
3. **Level 3**: Enable debug logging and collect traces
4. **Level 4**: Contact support with collected information

### 3. Log Collection Script

```python
#!/usr/bin/env python3
"""
Log collection script for support
"""

import sys
import json
import time
import platform
from e6data_python_connector.e6data_grpc import _get_shared_strategy

def collect_support_information():
    """Collect information for support"""
    support_info = {
        'timestamp': time.time(),
        'platform': {
            'python_version': sys.version,
            'platform': platform.platform(),
            'architecture': platform.architecture()
        },
        'connector_version': 'x.x.x',  # Replace with actual version
        'strategy_state': dict(_get_shared_strategy()),
        'environment': {
            'variables': {k: v for k, v in os.environ.items() if 'e6data' in k.lower()}
        }
    }
    
    filename = f"e6data_support_info_{int(time.time())}.json"
    with open(filename, 'w') as f:
        json.dump(support_info, f, indent=2)
    
    print(f"Support information saved to: {filename}")
    return filename

if __name__ == "__main__":
    collect_support_information()
```

This comprehensive troubleshooting guide should help users diagnose and resolve most issues related to zero downtime deployment strategy switching.