# Zero Downtime Deployment - Configuration Documentation

## Overview

This document provides comprehensive configuration options for zero downtime deployment features in the e6data Python Connector. It covers both programmatic configuration and environment-based settings.

## Configuration Parameters

### 1. Strategy Cache Configuration

#### `STRATEGY_CACHE_TIMEOUT`

**Description**: Controls how long the strategy cache remains valid before expiring.

**Default**: `300` seconds (5 minutes)

**Range**: `60` - `1800` seconds (1 minute to 30 minutes)

**Configuration**:
```python
# In e6data_grpc.py
STRATEGY_CACHE_TIMEOUT = 300  # 5 minutes

# Environment variable
import os
STRATEGY_CACHE_TIMEOUT = int(os.getenv('E6DATA_STRATEGY_CACHE_TIMEOUT', 300))
```

**Usage Impact**:
- **Lower values**: More frequent strategy detection, higher accuracy, higher overhead
- **Higher values**: Less frequent strategy detection, lower accuracy, lower overhead

**Recommendations**:
- **Development**: `60` seconds for faster testing
- **Production**: `300` seconds for balance
- **High-change environments**: `120` seconds for responsiveness

### 2. Retry Configuration

#### `MAX_RETRY_ATTEMPTS`

**Description**: Maximum number of retry attempts for failed operations.

**Default**: `5`

**Range**: `1` - `10`

**Configuration**:
```python
# In @re_auth decorator
max_retry = 5

# Environment variable
import os
MAX_RETRY_ATTEMPTS = int(os.getenv('E6DATA_MAX_RETRY_ATTEMPTS', 5))
```

#### `RETRY_BACKOFF_FACTOR`

**Description**: Multiplier for exponential backoff between retries.

**Default**: `0.2` seconds

**Range**: `0.1` - `2.0` seconds

**Configuration**:
```python
# In @re_auth decorator
time.sleep(0.2)

# Configurable backoff
import os
RETRY_BACKOFF_FACTOR = float(os.getenv('E6DATA_RETRY_BACKOFF_FACTOR', 0.2))
```

### 3. Detection Configuration

#### `STRATEGY_DETECTION_TIMEOUT`

**Description**: Timeout for strategy detection operations.

**Default**: `30` seconds

**Range**: `10` - `120` seconds

**Configuration**:
```python
# Environment variable
import os
STRATEGY_DETECTION_TIMEOUT = int(os.getenv('E6DATA_STRATEGY_DETECTION_TIMEOUT', 30))

# Usage in connection
def detect_strategy_with_timeout():
    import signal
    
    def timeout_handler(signum, frame):
        raise TimeoutError("Strategy detection timeout")
    
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(STRATEGY_DETECTION_TIMEOUT)
    
    try:
        # Strategy detection logic
        pass
    finally:
        signal.alarm(0)
```

## Connection Configuration

### 1. Basic Connection Parameters

```python
from e6data_python_connector.e6data_grpc import Connection

# Basic configuration
connection = Connection(
    host='your-host',
    port=80,
    username='your-email',
    password='your-token',
    catalog='your-catalog',
    database='your-database',
    cluster_uuid='your-cluster-uuid',
    secure=True,
    auto_resume=True
)
```

### 2. gRPC Configuration for Zero Downtime

```python
# Optimized gRPC configuration for zero downtime
grpc_options = {
    # Connection management
    'keepalive_timeout_ms': 60000,      # 1 minute keepalive timeout
    'keepalive_time_ms': 30000,         # 30 seconds keepalive interval
    'keepalive_permit_without_calls': 1, # Allow keepalive without active calls
    
    # Message size limits
    'max_receive_message_length': 100 * 1024 * 1024,  # 100MB
    'max_send_message_length': 100 * 1024 * 1024,     # 100MB
    
    # HTTP/2 settings
    'http2.max_pings_without_data': 0,                 # Unlimited pings
    'http2.min_time_between_pings_ms': 10000,          # 10 seconds between pings
    'http2.min_ping_interval_without_data_ms': 10000,  # 10 seconds ping interval
    
    # Timeouts
    'grpc_prepare_timeout': 600,        # 10 minutes prepare timeout
    'grpc_auto_resume_timeout_seconds': 300,  # 5 minutes auto resume timeout
}

connection = Connection(
    host='your-host',
    port=80,
    username='your-email',
    password='your-token',
    grpc_options=grpc_options
)
```

### 3. Environment-Based Configuration

```python
import os

# Environment-based connection configuration
def create_connection_from_env():
    return Connection(
        host=os.getenv('E6DATA_HOST', 'localhost'),
        port=int(os.getenv('E6DATA_PORT', 80)),
        username=os.getenv('E6DATA_USERNAME'),
        password=os.getenv('E6DATA_PASSWORD'),
        catalog=os.getenv('E6DATA_CATALOG'),
        database=os.getenv('E6DATA_DATABASE'),
        cluster_uuid=os.getenv('E6DATA_CLUSTER_UUID'),
        secure=os.getenv('E6DATA_SECURE', 'false').lower() == 'true',
        auto_resume=os.getenv('E6DATA_AUTO_RESUME', 'true').lower() == 'true',
        grpc_options=get_grpc_options_from_env()
    )

def get_grpc_options_from_env():
    return {
        'keepalive_timeout_ms': int(os.getenv('E6DATA_KEEPALIVE_TIMEOUT_MS', 60000)),
        'keepalive_time_ms': int(os.getenv('E6DATA_KEEPALIVE_TIME_MS', 30000)),
        'max_receive_message_length': int(os.getenv('E6DATA_MAX_RECEIVE_MSG_LENGTH', 100 * 1024 * 1024)),
        'max_send_message_length': int(os.getenv('E6DATA_MAX_SEND_MSG_LENGTH', 100 * 1024 * 1024)),
        'grpc_prepare_timeout': int(os.getenv('E6DATA_PREPARE_TIMEOUT', 600)),
        'grpc_auto_resume_timeout_seconds': int(os.getenv('E6DATA_AUTO_RESUME_TIMEOUT', 300)),
    }
```

## Logging Configuration

### 1. Strategy-Specific Logging

```python
import logging

# Configure strategy-specific logging
def configure_strategy_logging():
    # Create strategy logger
    strategy_logger = logging.getLogger('e6data_strategy')
    strategy_logger.setLevel(logging.INFO)
    
    # Create handler
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    handler.setFormatter(formatter)
    
    # Add handler to logger
    strategy_logger.addHandler(handler)
    
    return strategy_logger

# Usage
strategy_logger = configure_strategy_logging()
```

### 2. Structured Logging Configuration

```python
import logging
import json
import sys

class StrategyFormatter(logging.Formatter):
    """Custom formatter for strategy-related logs"""
    
    def format(self, record):
        log_entry = {
            'timestamp': self.formatTime(record),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add strategy-specific fields
        if hasattr(record, 'strategy'):
            log_entry['strategy'] = record.strategy
        if hasattr(record, 'query_id'):
            log_entry['query_id'] = record.query_id
        if hasattr(record, 'transition_type'):
            log_entry['transition_type'] = record.transition_type
        
        return json.dumps(log_entry)

# Configure structured logging
def configure_structured_logging():
    logger = logging.getLogger('e6data_python_connector')
    logger.setLevel(logging.DEBUG)
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StrategyFormatter())
    
    logger.addHandler(handler)
    return logger
```

### 3. Log Level Configuration

```python
import os
import logging

# Configure log levels from environment
def configure_log_levels():
    log_levels = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    
    # Main logger
    main_level = os.getenv('E6DATA_LOG_LEVEL', 'INFO').upper()
    main_logger = logging.getLogger('e6data_python_connector')
    main_logger.setLevel(log_levels.get(main_level, logging.INFO))
    
    # Strategy logger
    strategy_level = os.getenv('E6DATA_STRATEGY_LOG_LEVEL', 'INFO').upper()
    strategy_logger = logging.getLogger('e6data_python_connector.strategy')
    strategy_logger.setLevel(log_levels.get(strategy_level, logging.INFO))
    
    # gRPC logger
    grpc_level = os.getenv('E6DATA_GRPC_LOG_LEVEL', 'WARNING').upper()
    grpc_logger = logging.getLogger('grpc')
    grpc_logger.setLevel(log_levels.get(grpc_level, logging.WARNING))
```

## Performance Configuration

### 1. Cache Performance Configuration

```python
# Cache performance settings
class CacheConfig:
    def __init__(self):
        self.strategy_cache_size = int(os.getenv('E6DATA_STRATEGY_CACHE_SIZE', 1))
        self.query_mapping_cache_size = int(os.getenv('E6DATA_QUERY_MAPPING_CACHE_SIZE', 1000))
        self.cache_cleanup_interval = int(os.getenv('E6DATA_CACHE_CLEANUP_INTERVAL', 300))
        self.cache_ttl = int(os.getenv('E6DATA_CACHE_TTL', 300))
    
    def get_cache_config(self):
        return {
            'strategy_cache_size': self.strategy_cache_size,
            'query_mapping_cache_size': self.query_mapping_cache_size,
            'cache_cleanup_interval': self.cache_cleanup_interval,
            'cache_ttl': self.cache_ttl
        }

# Usage
cache_config = CacheConfig()
```

### 2. Connection Pool Configuration

```python
# Connection pool settings
class ConnectionPoolConfig:
    def __init__(self):
        self.max_connections = int(os.getenv('E6DATA_MAX_CONNECTIONS', 10))
        self.min_connections = int(os.getenv('E6DATA_MIN_CONNECTIONS', 1))
        self.connection_timeout = int(os.getenv('E6DATA_CONNECTION_TIMEOUT', 30))
        self.idle_timeout = int(os.getenv('E6DATA_IDLE_TIMEOUT', 300))
        self.max_lifetime = int(os.getenv('E6DATA_MAX_LIFETIME', 3600))
    
    def get_pool_config(self):
        return {
            'max_connections': self.max_connections,
            'min_connections': self.min_connections,
            'connection_timeout': self.connection_timeout,
            'idle_timeout': self.idle_timeout,
            'max_lifetime': self.max_lifetime
        }
```

## Environment Variables Reference

### 1. Strategy Configuration

```bash
# Strategy cache timeout (seconds)
export E6DATA_STRATEGY_CACHE_TIMEOUT=300

# Maximum retry attempts
export E6DATA_MAX_RETRY_ATTEMPTS=5

# Retry backoff factor (seconds)
export E6DATA_RETRY_BACKOFF_FACTOR=0.2

# Strategy detection timeout (seconds)
export E6DATA_STRATEGY_DETECTION_TIMEOUT=30

# Enable/disable strategy validation
export E6DATA_STRATEGY_VALIDATION=true
```

### 2. Connection Configuration

```bash
# Connection parameters
export E6DATA_HOST=your-host
export E6DATA_PORT=80
export E6DATA_USERNAME=your-email
export E6DATA_PASSWORD=your-token
export E6DATA_CATALOG=your-catalog
export E6DATA_DATABASE=your-database
export E6DATA_CLUSTER_UUID=your-cluster-uuid
export E6DATA_SECURE=true
export E6DATA_AUTO_RESUME=true
```

### 3. gRPC Configuration

```bash
# gRPC timeouts and limits
export E6DATA_KEEPALIVE_TIMEOUT_MS=60000
export E6DATA_KEEPALIVE_TIME_MS=30000
export E6DATA_MAX_RECEIVE_MSG_LENGTH=104857600
export E6DATA_MAX_SEND_MSG_LENGTH=104857600
export E6DATA_PREPARE_TIMEOUT=600
export E6DATA_AUTO_RESUME_TIMEOUT=300
```

### 4. Logging Configuration

```bash
# Logging levels
export E6DATA_LOG_LEVEL=INFO
export E6DATA_STRATEGY_LOG_LEVEL=INFO
export E6DATA_GRPC_LOG_LEVEL=WARNING

# Logging format
export E6DATA_LOG_FORMAT=json
export E6DATA_LOG_OUTPUT=stdout
```

### 5. Performance Configuration

```bash
# Cache configuration
export E6DATA_STRATEGY_CACHE_SIZE=1
export E6DATA_QUERY_MAPPING_CACHE_SIZE=1000
export E6DATA_CACHE_CLEANUP_INTERVAL=300
export E6DATA_CACHE_TTL=300

# Connection pool configuration
export E6DATA_MAX_CONNECTIONS=10
export E6DATA_MIN_CONNECTIONS=1
export E6DATA_CONNECTION_TIMEOUT=30
export E6DATA_IDLE_TIMEOUT=300
export E6DATA_MAX_LIFETIME=3600
```

## Configuration Validation

### 1. Configuration Validator

```python
import os
import logging
from typing import Dict, Any

class ConfigurationValidator:
    """Validates configuration parameters"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.validation_rules = self._get_validation_rules()
    
    def _get_validation_rules(self) -> Dict[str, Dict[str, Any]]:
        return {
            'E6DATA_STRATEGY_CACHE_TIMEOUT': {
                'type': int,
                'min': 60,
                'max': 1800,
                'default': 300
            },
            'E6DATA_MAX_RETRY_ATTEMPTS': {
                'type': int,
                'min': 1,
                'max': 10,
                'default': 5
            },
            'E6DATA_RETRY_BACKOFF_FACTOR': {
                'type': float,
                'min': 0.1,
                'max': 2.0,
                'default': 0.2
            },
            'E6DATA_PORT': {
                'type': int,
                'min': 1,
                'max': 65535,
                'default': 80
            },
            'E6DATA_SECURE': {
                'type': bool,
                'default': False
            },
            'E6DATA_AUTO_RESUME': {
                'type': bool,
                'default': True
            }
        }
    
    def validate_configuration(self) -> Dict[str, Any]:
        """Validate all configuration parameters"""
        validated_config = {}
        
        for env_var, rules in self.validation_rules.items():
            value = os.getenv(env_var)
            
            if value is None:
                validated_config[env_var] = rules['default']
                continue
            
            try:
                # Type conversion
                if rules['type'] == int:
                    converted_value = int(value)
                elif rules['type'] == float:
                    converted_value = float(value)
                elif rules['type'] == bool:
                    converted_value = value.lower() in ('true', '1', 'yes', 'on')
                else:
                    converted_value = value
                
                # Range validation
                if 'min' in rules and converted_value < rules['min']:
                    self.logger.warning(f"{env_var} value {converted_value} below minimum {rules['min']}")
                    converted_value = rules['min']
                
                if 'max' in rules and converted_value > rules['max']:
                    self.logger.warning(f"{env_var} value {converted_value} above maximum {rules['max']}")
                    converted_value = rules['max']
                
                validated_config[env_var] = converted_value
                
            except (ValueError, TypeError) as e:
                self.logger.error(f"Invalid value for {env_var}: {value}. Using default: {rules['default']}")
                validated_config[env_var] = rules['default']
        
        return validated_config
    
    def apply_validated_configuration(self, config: Dict[str, Any]):
        """Apply validated configuration to environment"""
        for env_var, value in config.items():
            os.environ[env_var] = str(value)
        
        self.logger.info("Configuration validated and applied")

# Usage
validator = ConfigurationValidator()
validated_config = validator.validate_configuration()
validator.apply_validated_configuration(validated_config)
```

## Configuration Examples

### 1. Development Configuration

```python
# Development configuration
development_config = {
    'host': 'localhost',
    'port': 50052,
    'username': 'dev@example.com',
    'password': 'dev-token',
    'catalog': 'dev_catalog',
    'database': 'dev_database',
    'secure': False,
    'auto_resume': True,
    'grpc_options': {
        'keepalive_timeout_ms': 30000,
        'keepalive_time_ms': 15000,
        'max_receive_message_length': 50 * 1024 * 1024,
        'max_send_message_length': 50 * 1024 * 1024,
        'grpc_prepare_timeout': 300,
    }
}

# Environment variables for development
development_env = {
    'E6DATA_STRATEGY_CACHE_TIMEOUT': '60',
    'E6DATA_MAX_RETRY_ATTEMPTS': '3',
    'E6DATA_LOG_LEVEL': 'DEBUG',
    'E6DATA_STRATEGY_LOG_LEVEL': 'DEBUG',
}
```

### 2. Production Configuration

```python
# Production configuration
production_config = {
    'host': 'production-host.example.com',
    'port': 80,
    'username': 'prod@example.com',
    'password': 'secure-prod-token',
    'catalog': 'production_catalog',
    'database': 'production_database',
    'secure': True,
    'auto_resume': True,
    'grpc_options': {
        'keepalive_timeout_ms': 90000,
        'keepalive_time_ms': 45000,
        'max_receive_message_length': 200 * 1024 * 1024,
        'max_send_message_length': 200 * 1024 * 1024,
        'grpc_prepare_timeout': 900,
        'grpc_auto_resume_timeout_seconds': 600,
    }
}

# Environment variables for production
production_env = {
    'E6DATA_STRATEGY_CACHE_TIMEOUT': '300',
    'E6DATA_MAX_RETRY_ATTEMPTS': '5',
    'E6DATA_LOG_LEVEL': 'INFO',
    'E6DATA_STRATEGY_LOG_LEVEL': 'INFO',
    'E6DATA_GRPC_LOG_LEVEL': 'WARNING',
}
```

### 3. High-Performance Configuration

```python
# High-performance configuration
high_performance_config = {
    'grpc_options': {
        'keepalive_timeout_ms': 120000,
        'keepalive_time_ms': 60000,
        'max_receive_message_length': 500 * 1024 * 1024,
        'max_send_message_length': 500 * 1024 * 1024,
        'grpc_prepare_timeout': 1800,
        'http2.max_pings_without_data': 0,
        'http2.min_time_between_pings_ms': 5000,
        'http2.min_ping_interval_without_data_ms': 5000,
    }
}

# Environment variables for high-performance
high_performance_env = {
    'E6DATA_STRATEGY_CACHE_TIMEOUT': '600',
    'E6DATA_MAX_RETRY_ATTEMPTS': '3',
    'E6DATA_RETRY_BACKOFF_FACTOR': '0.1',
    'E6DATA_MAX_CONNECTIONS': '20',
    'E6DATA_CONNECTION_TIMEOUT': '60',
}
```

## Configuration Best Practices

### 1. Environment-Specific Configuration

- **Development**: Use shorter cache timeouts and more verbose logging
- **Testing**: Use mock servers and isolated configurations
- **Staging**: Mirror production configuration with test data
- **Production**: Use optimized settings for performance and reliability

### 2. Security Configuration

- **Credentials**: Never hardcode credentials in configuration files
- **TLS**: Always use secure connections in production
- **Token Management**: Implement secure token rotation
- **Network Security**: Configure appropriate network restrictions

### 3. Performance Configuration

- **Cache Tuning**: Adjust cache timeouts based on deployment frequency
- **Connection Pooling**: Configure appropriate pool sizes for load
- **Timeout Settings**: Balance responsiveness with stability
- **Resource Limits**: Set appropriate memory and CPU limits

### 4. Monitoring Configuration

- **Logging**: Configure appropriate log levels and formats
- **Metrics**: Enable performance and health metrics
- **Alerting**: Set up alerts for configuration-related issues
- **Tracing**: Enable distributed tracing for complex scenarios

This comprehensive configuration documentation provides all the necessary information for properly configuring zero downtime deployment features in various environments.