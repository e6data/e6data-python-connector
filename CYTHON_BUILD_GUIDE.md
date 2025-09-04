# Cython Build Guide for e6data Python Connector

## Overview

This guide explains how to build, install, and regenerate Cython optimizations for the e6data Python connector. Cython optimizations provide 2-10x performance improvements for data deserialization.

## Prerequisites

### Required Dependencies
```bash
pip install cython>=0.29.0 numpy>=1.19.0
```

### System Requirements
- **C++ compiler** (GCC, Clang, or MSVC)
- **Python development headers**

#### Linux (Ubuntu/Debian)
```bash
sudo apt-get update
sudo apt-get install build-essential python3-dev
```

#### Linux (CentOS/RHEL)
```bash
sudo yum install python3-devel gcc gcc-c++
```

#### macOS
```bash
# Install Xcode command line tools
xcode-select --install

# Or install via Homebrew
brew install python
```

#### Windows
```bash
# Install Visual Studio Build Tools
# https://visualstudio.microsoft.com/visual-cpp-build-tools/
```

## Building Cython Extensions

### Method 1: Development Build (Recommended)
```bash
# Install dependencies
pip install cython numpy

# Build extensions in-place
BUILD_CYTHON=1 python setup.py build_ext --inplace

# Install in development mode
pip install -e .
```

### Method 2: Full Package Install
```bash
# Install dependencies
pip install cython numpy

# Build and install with Cython
BUILD_CYTHON=1 pip install -e .
```

### Method 3: Production Build
```bash
# For deployment
BUILD_CYTHON=1 pip install e6data-python-connector
```

## Verification

### Check Build Success
```bash
# Test Cython import
python -c "from e6data_python_connector.cython_deserializer import fast_get_column_from_chunk; print('✅ Cython extensions built successfully')"

# Check optimization status
python -c "
from e6data_python_connector.fast_deserializer import get_optimization_info
info = get_optimization_info()
print(f'Optimization mode: {info[\"current_mode\"]}')
print(f'Cython available: {info[\"cython_available\"]}')
"
```

### Run Benchmark
```bash
# Test performance with credentials
ENGINE_IP="your-host" EMAIL="your-email" PASSWORD="your-token" python benchmark_cython.py
```

## File Structure

### Source Files
```
e6data_python_connector/
├── cython_deserializer.pyx      # Main Cython implementation
├── fast_deserializer.py         # Integration and fallback layer
├── datainputstream.py          # Original Python implementation
└── __init__.py                 # Auto-enables optimizations
```

### Build Files
```
build/                          # Build artifacts
├── temp.*/                     # Temporary compilation files
└── lib.*/                      # Compiled libraries

e6data_python_connector/
├── cython_deserializer.c       # Generated C code
├── cython_deserializer.cpp     # Generated C++ code
└── cython_deserializer.*.so   # Compiled extension
```

### Configuration Files
```
setup.py                       # Main setup with Cython integration
setup_cython.py               # Cython-specific build configuration
benchmark_cython.py           # Performance benchmarking
```

## Regenerating Cython Code

### When to Regenerate

Regenerate Cython extensions when:
1. **Algorithm changes** - Modifications to `datainputstream.py` logic
2. **Performance improvements** - New optimization opportunities
3. **Data type support** - New vector types or data formats
4. **Dependency updates** - Major Cython or NumPy version changes
5. **Platform changes** - Moving to different OS or architecture

### Regeneration Steps

#### 1. Clean Previous Build
```bash
# Remove build artifacts
rm -rf build/
rm -f e6data_python_connector/cython_deserializer.c
rm -f e6data_python_connector/cython_deserializer.cpp
rm -f e6data_python_connector/cython_deserializer.*.so

# Clean Python cache
find . -name "__pycache__" -type d -exec rm -rf {} +
find . -name "*.pyc" -delete
```

#### 2. Update Source Code
Edit `e6data_python_connector/cython_deserializer.pyx` with your changes:

```cython
# Example: Adding new data type support
elif d_type == VectorType.NEW_TYPE:
    if vector.isConstantVector:
        constant_value = vector.data.newTypeConstantData.data
        for row in range(size):
            if get_null_fast(vector, row):
                value = None
            else:
                value = process_new_type(constant_value)
            Py_INCREF(value)
            PyList_SET_ITEM(value_array, row, value)
    # ... rest of implementation
```

#### 3. Update Fallback Implementation
Update `e6data_python_connector/fast_deserializer.py` with corresponding changes:

```python
# Mirror changes in Python optimized version
elif d_type == VectorType.NEW_TYPE:
    if vector.isConstantVector:
        constant_value = process_new_type(vector.data.newTypeConstantData.data)
        for row in range(size):
            value_array[row] = None if get_null_check(vector, row) else constant_value
    # ... rest of implementation
```

#### 4. Rebuild Extensions
```bash
# Rebuild Cython extensions
BUILD_CYTHON=1 python setup.py build_ext --inplace

# Reinstall package
pip install -e .
```

#### 5. Test Changes
```bash
# Run tests to ensure correctness
python benchmark_cython.py

# Test with real queries
ENGINE_IP="your-host" EMAIL="your-email" PASSWORD="your-token" python -c "
from e6data_python_connector import ConnectionPool
# Test your changes...
"
```

#### 6. Benchmark Performance
```bash
# Compare performance before/after changes
python benchmark_cython.py > performance_report.txt
```

## Optimization Best Practices

### 1. Cython Code Guidelines

```cython
# Use type declarations for performance
cdef int size = vector.size
cdef list value_array = PyList_New(size)

# Minimize Python object creation
cdef object value
for row in range(size):
    value = data[row]
    Py_INCREF(value)
    PyList_SET_ITEM(value_array, row, value)

# Use fast null checking
if get_null_fast(vector, row):
    value = None

# Cache expensive operations
cdef object constant_value = process_expensive_operation()
```

### 2. Memory Management

```cython
# Pre-allocate arrays
cdef list value_array = PyList_New(size)

# Use proper reference counting
Py_INCREF(value)
PyList_SET_ITEM(value_array, row, value)

# Avoid memory leaks in exception handling
try:
    # risky operation
except:
    # cleanup allocated memory
    pass
```

### 3. Performance Tuning

```cython
# Compiler directives for maximum speed
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True
# cython: nonecheck=False

# Use fast loops
cdef int i
for i in range(size):  # Faster than for i in some_list

# Minimize Python API calls
cdef object cached_func = expensive_python_function
```

## Debugging and Troubleshooting

### Build Issues

#### Cython Compilation Errors
```bash
# Enable verbose compilation
BUILD_CYTHON=1 CYTHON_ANNOTATE=1 python setup.py build_ext --inplace

# Check generated C code
ls e6data_python_connector/cython_deserializer.c

# View optimization annotations (if CYTHON_ANNOTATE=1)
open e6data_python_connector/cython_deserializer.html
```

#### Missing Dependencies
```bash
# Check Cython version
python -c "import Cython; print(f'Cython: {Cython.__version__}')"

# Check NumPy version
python -c "import numpy; print(f'NumPy: {numpy.__version__}')"

# Test compiler
python setup_cython.py
```

### Runtime Issues

#### Import Errors
```python
# Test Cython import manually
try:
    from e6data_python_connector.cython_deserializer import fast_get_column_from_chunk
    print("✅ Cython extensions available")
except ImportError as e:
    print(f"❌ Cython extensions not available: {e}")
```

#### Performance Issues
```python
# Check optimization mode
from e6data_python_connector.fast_deserializer import get_optimization_info
info = get_optimization_info()
print(f"Current mode: {info['current_mode']}")

# Force different modes for testing
from e6data_python_connector.fast_deserializer import enable_fast_deserialization
enable_fast_deserialization(force_cython=True)   # Force Cython
enable_fast_deserialization(force_cython=False)  # Force Python optimized
```

#### Memory Leaks
```python
# Monitor memory usage
import psutil
import os

process = psutil.Process(os.getpid())
before = process.memory_info().rss / 1024 / 1024  # MB

# Run your code here

after = process.memory_info().rss / 1024 / 1024   # MB
print(f"Memory change: {after - before:.1f} MB")
```

## Environment Variables

### Build Configuration
- `BUILD_CYTHON=1` - Enable Cython extension building
- `CYTHON_ANNOTATE=1` - Generate HTML annotation files for debugging
- `CYTHON_THREADS=4` - Number of parallel compilation threads
- `CC=gcc` - Specify C compiler
- `CPPFLAGS="-O3"` - Additional compiler flags

### Runtime Configuration
- `E6DATA_FORCE_CYTHON=1` - Force Cython mode at runtime
- `E6DATA_DISABLE_OPTIMIZATIONS=1` - Disable all optimizations
- `E6DATA_DEBUG_OPTIMIZATIONS=1` - Enable optimization debug logging

## CI/CD Integration

### GitHub Actions Example
```yaml
name: Build with Cython
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'
    
    - name: Install dependencies
      run: |
        pip install cython numpy
        
    - name: Build Cython extensions
      run: |
        BUILD_CYTHON=1 pip install -e .
        
    - name: Test Cython extensions
      run: |
        python -c "
        from e6data_python_connector.fast_deserializer import get_optimization_info
        info = get_optimization_info()
        assert info['cython_available'], 'Cython not available'
        assert info['current_mode'] == 'cython', f'Wrong mode: {info[\"current_mode\"]}'
        print('✅ Cython extensions working')
        "
```

### Docker Example
```dockerfile
FROM python:3.11-slim

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install cython numpy
RUN pip install -r requirements.txt

# Copy and build application
COPY . .
RUN BUILD_CYTHON=1 pip install .

# Verify Cython build
RUN python -c "from e6data_python_connector.fast_deserializer import get_optimization_info; print(get_optimization_info())"

CMD ["python", "app.py"]
```

## Performance Monitoring

### Runtime Checks
```python
import logging
from e6data_python_connector.fast_deserializer import get_optimization_info

# Log optimization status at startup
info = get_optimization_info()
logging.info(f"e6data optimization mode: {info['current_mode']}")

if info['current_mode'] == 'cython':
    logging.info("🚀 High-performance Cython mode active")
elif info['current_mode'] == 'python_optimized':
    logging.info("⚡ Python optimized mode active")
else:
    logging.warning("⚠️  Using default mode, consider enabling optimizations")
```

### Benchmarking
```python
# Compare optimization modes
import time
from e6data_python_connector.fast_deserializer import enable_fast_deserialization

modes = ['cython', 'python_optimized', 'default']
results = {}

for mode in modes:
    if mode == 'cython':
        enable_fast_deserialization(force_cython=True)
    elif mode == 'python_optimized':
        enable_fast_deserialization(force_cython=False)
    else:
        disable_fast_deserialization()
    
    start = time.time()
    # Run your benchmark here
    end = time.time()
    
    results[mode] = end - start

# Compare results
baseline = results['default']
for mode, duration in results.items():
    improvement = baseline / duration
    print(f"{mode}: {duration:.3f}s ({improvement:.2f}x speedup)")
```

## Maintenance

### Regular Tasks
1. **Update when changing datainputstream.py**
2. **Rebuild after dependency updates**
3. **Test performance periodically**
4. **Monitor for memory leaks**

### Version Updates
```bash
# Check for Cython updates
pip list --outdated | grep cython

# Update and rebuild
pip install --upgrade cython numpy
BUILD_CYTHON=1 python setup.py build_ext --inplace
```

### Profiling
```bash
# Profile Cython code
pip install cython-profile
BUILD_CYTHON=1 CYTHON_PROFILE=1 python setup.py build_ext --inplace

# Run with profiling
python -m cProfile your_script.py
```

This guide ensures consistent and reliable Cython optimization builds for maximum performance.