# Cython Toggle Control Guide

## Overview

The e6data Python connector provides multiple ways to control Cython optimizations at runtime and build time. This guide covers all available toggle methods and configuration options.

## Toggle Methods

### 1. Runtime Toggle Functions

#### Basic Control
```python
from e6data_python_connector.fast_deserializer import (
    enable_fast_deserialization,
    disable_fast_deserialization,
    set_optimization_mode,
    get_optimization_info,
    get_available_modes
)

# Enable optimizations (auto-detect best mode)
enable_fast_deserialization()

# Force specific mode
enable_fast_deserialization(force_cython=True)   # Force Cython
enable_fast_deserialization(force_cython=False)  # Force Python optimized

# Disable all optimizations
disable_fast_deserialization()

# Set mode directly
set_optimization_mode('cython')      # Force Cython
set_optimization_mode('python')      # Force Python optimized
set_optimization_mode('default')     # Use original unoptimized code
set_optimization_mode('auto')        # Auto-detect best available

# Check available modes
modes = get_available_modes()  # ['default', 'python', 'cython', 'auto']

# Get detailed status
info = get_optimization_info()
print(f"Mode: {info['current_mode']}")
print(f"Cython available: {info['cython_available']}")
```

#### Persistent Configuration
```python
from e6data_python_connector.fast_deserializer import (
    set_and_save_mode,
    save_config_file
)

# Set mode and save to config file
success = set_and_save_mode('cython')
if success:
    print("Configuration saved successfully")

# Save custom configuration
config = {
    'mode': 'python',
    'enabled': True,
    'notes': 'Using Python optimized for compatibility'
}
save_config_file(config)
```

### 2. Environment Variables

#### Runtime Control
```bash
# Disable Cython completely
export E6DATA_DISABLE_CYTHON=1

# Disable all optimizations
export E6DATA_DISABLE_OPTIMIZATIONS=1

# Force specific mode
export E6DATA_FORCE_MODE=cython     # Force Cython
export E6DATA_FORCE_MODE=python     # Force Python optimized
export E6DATA_FORCE_MODE=default    # Force default (unoptimized)
```

#### Build Time Control
```bash
# Enable Cython build
export BUILD_CYTHON=1
pip install -e .

# Disable Cython build (Python only)
unset BUILD_CYTHON
pip install -e .
```

### 3. Configuration Files

#### Local Configuration (Project-specific)
Create `.e6data_config.json` in your project directory:
```json
{
  "optimization": {
    "mode": "cython",
    "enabled": true,
    "saved_at": "2024-01-15T10:30:00.000Z"
  }
}
```

#### Global Configuration (User-wide)
Create `~/.e6data_config.json` in your home directory:
```json
{
  "optimization": {
    "mode": "python",
    "enabled": true,
    "notes": "Global preference for Python optimized mode"
  }
}
```

## Configuration Priority

The optimization mode is determined in this order (highest to lowest priority):

1. **Environment Variables**
   - `E6DATA_DISABLE_OPTIMIZATIONS=1` (disables all)
   - `E6DATA_DISABLE_CYTHON=1` (disables Cython only)
   - `E6DATA_FORCE_MODE=<mode>` (forces specific mode)

2. **Runtime Function Calls**
   - `set_optimization_mode(mode)`
   - `enable_fast_deserialization(force_cython=...)`

3. **Configuration Files**
   - `.e6data_config.json` (project-specific)
   - `~/.e6data_config.json` (user-specific)

4. **Auto-Detection**
   - Cython if available, otherwise Python optimized

## Usage Examples

### Development Setup
```python
# For development with frequent code changes
from e6data_python_connector.fast_deserializer import set_optimization_mode

# Use Python optimized during development
set_optimization_mode('python')

# Switch to Cython for performance testing
set_optimization_mode('cython')

# Check status
from e6data_python_connector.fast_deserializer import get_optimization_info
print(get_optimization_info())
```

### Production Deployment
```bash
# Environment-based configuration for production
export E6DATA_FORCE_MODE=cython
export BUILD_CYTHON=1

# Build with Cython
pip install cython numpy
pip install -e .

# Verify optimization in production
python -c "
from e6data_python_connector.fast_deserializer import get_optimization_info
info = get_optimization_info()
assert info['current_mode'] == 'cython', f'Expected cython, got {info[\"current_mode\"]}'
print('✅ Production optimizations active')
"
```

### CI/CD Integration
```yaml
# GitHub Actions example
- name: Configure optimizations
  run: |
    echo "E6DATA_FORCE_MODE=cython" >> $GITHUB_ENV
    echo "BUILD_CYTHON=1" >> $GITHUB_ENV

- name: Build with optimizations
  run: |
    pip install cython numpy
    BUILD_CYTHON=1 pip install -e .

- name: Test optimizations
  run: |
    python -c "
    from e6data_python_connector.fast_deserializer import get_optimization_info
    info = get_optimization_info()
    print(f'Mode: {info[\"current_mode\"]}')
    print(f'Cython: {info[\"cython_available\"]}')
    assert info['current_mode'] in ['cython', 'python_optimized']
    "
```

### Debugging Performance Issues
```python
from e6data_python_connector.fast_deserializer import (
    set_optimization_mode, 
    get_optimization_info
)
import time

# Test different modes
modes_to_test = ['default', 'python', 'cython']
results = {}

for mode in modes_to_test:
    try:
        set_optimization_mode(mode)
        
        start = time.time()
        # Your query/processing code here
        end = time.time()
        
        results[mode] = end - start
        print(f"{mode}: {end-start:.3f}s")
        
    except Exception as e:
        print(f"{mode}: Error - {e}")

# Find best performing mode
if results:
    best_mode = min(results, key=results.get)
    print(f"Best performance: {best_mode}")
```

## Troubleshooting

### Common Issues

#### "Cython not available" Error
```python
# Check Cython status
info = get_optimization_info()
print("Cython available:", info['cython_available'])

# If False, install Cython:
# pip install cython numpy
# BUILD_CYTHON=1 pip install -e .
```

#### "Optimization mode not changing"
```python
# Clear any environment variable overrides
import os
os.environ.pop('E6DATA_FORCE_MODE', None)
os.environ.pop('E6DATA_DISABLE_CYTHON', None)

# Set mode programmatically
set_optimization_mode('your_desired_mode')

# Verify change
info = get_optimization_info()
print(f"Current mode: {info['current_mode']}")
```

#### "Configuration file not loading"
```python
# Check config file existence and content
import os
config_files = ['.e6data_config.json', os.path.expanduser('~/.e6data_config.json')]
for cf in config_files:
    if os.path.exists(cf):
        print(f"Found config: {cf}")
        with open(cf) as f:
            print(f.read())
    else:
        print(f"Not found: {cf}")
```

### Debug Logging
```python
import logging

# Enable debug logging
logging.getLogger('e6data_python_connector').setLevel(logging.DEBUG)

# Check optimization decisions
from e6data_python_connector.fast_deserializer import get_optimization_info
info = get_optimization_info()
print("Debug info:", info)
```

## Migration Guide

### From Previous Versions
If you were using the old manual optimization approach:

**Old way:**
```python
# Manual import and usage (no longer needed)
from e6data_python_connector.cython_deserializer import fast_get_column_from_chunk
```

**New way:**
```python
# Automatic optimization (recommended)
from e6data_python_connector import Connection  # Optimizations auto-enabled

# Or explicit control
from e6data_python_connector.fast_deserializer import set_optimization_mode
set_optimization_mode('cython')
```

### Environment Variable Migration
```bash
# Old environment variables (if you used them)
unset DISABLE_CYTHON
unset FORCE_PYTHON_MODE

# New standardized variables
export E6DATA_FORCE_MODE=cython
export BUILD_CYTHON=1
```

## Best Practices

### 1. Development
- Use `python` mode during active development for faster rebuilds
- Use `cython` mode for performance testing
- Save mode preferences to configuration files

### 2. Production
- Set `E6DATA_FORCE_MODE=cython` in production environment
- Build with `BUILD_CYTHON=1` in deployment scripts
- Monitor optimization status in application logs

### 3. Testing
- Test all modes in CI/CD pipeline
- Use `default` mode for baseline performance comparison
- Verify Cython availability in production environments

### 4. Debugging
- Use `default` mode to isolate optimization-related issues
- Enable debug logging for optimization decisions
- Test mode switching at runtime for troubleshooting

This comprehensive toggle system ensures maximum flexibility while maintaining optimal performance.