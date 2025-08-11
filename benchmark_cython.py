"""
Benchmark script for Cython optimization performance testing.

This script compares the performance of different deserialization modes:
1. Default (unoptimized)
2. Python optimized
3. Cython optimized (if available)

Run with: python benchmark_cython.py
"""

import time
import statistics
import sys
import os
from typing import List, Dict, Any
from unittest.mock import MagicMock, patch
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Generate test data
def generate_test_data(num_rows: int = 10000, num_cols: int = 10) -> tuple:
    """Generate mock test data for benchmarking."""
    import struct
    from datetime import datetime
    from decimal import Decimal
    import io
    
    # Create mock column descriptions
    columns = []
    from e6data_python_connector.datainputstream import FieldInfo
    
    # Mixed data types for realistic testing
    column_types = [
        ("id", "LONG"),
        ("name", "STRING"),
        ("price", "DOUBLE"),
        ("created_date", "DATE"),
        ("updated_at", "DATETIME"),
        ("is_active", "BOOLEAN"),
        ("score", "FLOAT"),
        ("category_id", "INTEGER"),
        ("amount", "DECIMAL128"),
        ("description", "STRING")
    ]
    
    for i in range(num_cols):
        col_name, col_type = column_types[i % len(column_types)]
        col_name = f"{col_name}_{i}"
        columns.append(FieldInfo(col_name, col_type, "", ""))
    
    # Create binary buffer with test data
    buffer = io.BytesIO()
    
    # Write row count and field count (metadata header)
    buffer.write(struct.pack('>q', num_rows))  # row count
    buffer.write(struct.pack('>i', len(columns)))  # field count
    
    # Write column metadata
    for col in columns:
        name_bytes = col.name.encode('utf-8')
        buffer.write(struct.pack('>H', len(name_bytes)))
        buffer.write(name_bytes)
        
        type_bytes = col.field_type.encode('utf-8')
        buffer.write(struct.pack('>H', len(type_bytes)))
        buffer.write(type_bytes)
        
        zone_bytes = "".encode('utf-8')
        buffer.write(struct.pack('>H', len(zone_bytes)))
        buffer.write(zone_bytes)
        
        format_bytes = "".encode('utf-8')
        buffer.write(struct.pack('>H', len(format_bytes)))
        buffer.write(format_bytes)
    
    # Create row data buffer
    row_buffer = io.BytesIO()
    
    for row in range(num_rows):
        for col_idx, col in enumerate(columns):
            # Write presence flag (1 = present, 0 = null)
            row_buffer.write(struct.pack('b', 1))
            
            # Write data based on type
            if col.field_type == "LONG":
                row_buffer.write(struct.pack('>q', row * 1000 + col_idx))
            elif col.field_type == "STRING":
                value = f"test_string_{row}_{col_idx}"
                value_bytes = value.encode('utf-8')
                row_buffer.write(struct.pack('>H', len(value_bytes)))
                row_buffer.write(value_bytes)
            elif col.field_type == "DOUBLE":
                row_buffer.write(struct.pack('>d', float(row + col_idx) * 1.5))
            elif col.field_type == "DATE":
                # Epoch microseconds
                row_buffer.write(struct.pack('>q', (1640995200 + row * 86400) * 1000000))
            elif col.field_type == "DATETIME":
                # Epoch microseconds with microsecond precision
                row_buffer.write(struct.pack('>q', (1640995200 + row * 86400) * 1000000 + row))
            elif col.field_type == "BOOLEAN":
                row_buffer.write(struct.pack('?', row % 2 == 0))
            elif col.field_type == "FLOAT":
                row_buffer.write(struct.pack('>f', float(row + col_idx) * 0.5))
            elif col.field_type == "INTEGER":
                row_buffer.write(struct.pack('>i', row + col_idx))
            elif col.field_type == "DECIMAL128":
                value = f"{row}.{col_idx:02d}"
                value_bytes = value.encode('utf-8')
                row_buffer.write(struct.pack('>H', len(value_bytes)))
                row_buffer.write(value_bytes)
    
    return buffer.getvalue(), row_buffer.getvalue(), columns


def benchmark_deserialization_mode(mode: str, metadata_buffer: bytes, 
                                 row_buffer: bytes, columns: List, 
                                 iterations: int = 5) -> Dict[str, Any]:
    """Benchmark a specific deserialization mode."""
    from e6data_python_connector.fast_deserializer import (
        enable_fast_deserialization, 
        disable_fast_deserialization,
        get_optimization_info
    )
    
    # Configure mode
    if mode == "default":
        disable_fast_deserialization()
    elif mode == "python_optimized":
        enable_fast_deserialization(force_cython=False)
    elif mode == "cython":
        try:
            enable_fast_deserialization(force_cython=True)
        except ImportError:
            logger.warning("Cython not available, skipping cython benchmark")
            return None
    
    # Verify mode
    info = get_optimization_info()
    actual_mode = info['current_mode']
    
    if mode == "default" and actual_mode != "default":
        logger.warning(f"Expected default mode, got {actual_mode}")
    elif mode == "python_optimized" and actual_mode != "python_optimized":
        logger.warning(f"Expected python_optimized mode, got {actual_mode}")
    elif mode == "cython" and actual_mode != "cython":
        logger.warning(f"Expected cython mode, got {actual_mode}")
    
    times = []
    memory_usage = []
    
    for iteration in range(iterations):
        # Metadata parsing
        start_time = time.perf_counter()
        
        try:
            from e6data_python_connector.datainputstream import get_query_columns_info, DataInputStream
            
            # Test metadata parsing
            rowcount, parsed_columns = get_query_columns_info(metadata_buffer)
            
            # Test row data parsing
            row_stream = DataInputStream(io.BytesIO(row_buffer))
            from e6data_python_connector.datainputstream import read_values_from_array
            
            # Parse multiple rows to get meaningful timing
            total_rows = 0
            while total_rows < 1000:  # Parse at least 1000 rows
                try:
                    row_data = read_values_from_array(columns, row_stream)
                    total_rows += 1
                except:
                    break
                    
        except Exception as e:
            logger.error(f"Error in {mode} benchmark: {e}")
            continue
        
        end_time = time.perf_counter()
        times.append(end_time - start_time)
    
    if not times:
        return None
    
    return {
        'mode': actual_mode,
        'mean_time': statistics.mean(times),
        'std_dev': statistics.stdev(times) if len(times) > 1 else 0,
        'min_time': min(times),
        'max_time': max(times),
        'iterations': len(times),
        'rows_processed': total_rows * len(times)
    }


def run_comprehensive_benchmark():
    """Run comprehensive benchmarks across all modes."""
    print("="*80)
    print("e6data Python Connector - Cython Optimization Benchmark")
    print("="*80)
    
    # Generate test data
    print("\nGenerating test data...")
    metadata_buffer, row_buffer, columns = generate_test_data(num_rows=5000, num_cols=8)
    print(f"Generated data: {len(columns)} columns, ~{len(row_buffer)} bytes row data")
    
    # Test modes
    modes = ["default", "python_optimized", "cython"]
    results = {}
    
    print("\nRunning benchmarks...")
    for mode in modes:
        print(f"\nTesting {mode} mode...")
        result = benchmark_deserialization_mode(mode, metadata_buffer, row_buffer, columns, iterations=3)
        
        if result:
            results[mode] = result
            print(f"  Average time: {result['mean_time']:.4f}s")
            print(f"  Std dev: {result['std_dev']:.4f}s")
            print(f"  Rows processed: {result['rows_processed']}")
        else:
            print(f"  Skipped (not available)")
    
    # Print comparison
    print("\n" + "="*80)
    print("BENCHMARK RESULTS")
    print("="*80)
    
    if not results:
        print("No benchmark results available")
        return
    
    # Find baseline (default or slowest available)
    baseline_mode = "default" if "default" in results else min(results.keys(), key=lambda k: results[k]['mean_time'])
    baseline_time = results[baseline_mode]['mean_time']
    
    print(f"\n{'Mode':<20} {'Time (s)':<12} {'Std Dev':<12} {'Speedup':<10} {'Status'}")
    print("-" * 70)
    
    for mode in ["default", "python_optimized", "cython"]:
        if mode in results:
            result = results[mode]
            speedup = baseline_time / result['mean_time']
            status = "✓" if result['mean_time'] == min(r['mean_time'] for r in results.values()) else ""
            
            print(f"{mode:<20} {result['mean_time']:<12.4f} {result['std_dev']:<12.4f} {speedup:<10.2f}x {status}")
        else:
            print(f"{mode:<20} {'N/A':<12} {'N/A':<12} {'N/A':<10} {'Not available'}")
    
    # Recommendations
    print("\nRECOMMENDATIONS:")
    print("-" * 40)
    
    if "cython" in results:
        cython_speedup = baseline_time / results["cython"]["mean_time"]
        print(f"✓ Cython optimization provides {cython_speedup:.1f}x performance improvement")
        print("  Use: BUILD_CYTHON=1 pip install -e .")
    else:
        print("⚠ Cython optimization not available")
        print("  Install: pip install cython numpy")
        print("  Build: BUILD_CYTHON=1 pip install -e .")
    
    if "python_optimized" in results:
        py_speedup = baseline_time / results["python_optimized"]["mean_time"]
        if py_speedup > 1.2:
            print(f"✓ Python optimization provides {py_speedup:.1f}x improvement")
            print("  Automatically enabled when Cython not available")
    
    # System info
    print(f"\nSYSTEM INFO:")
    print(f"Python version: {sys.version}")
    print(f"Platform: {sys.platform}")
    
    try:
        from e6data_python_connector.fast_deserializer import get_optimization_info
        info = get_optimization_info()
        print(f"Current optimization mode: {info['current_mode']}")
        print(f"Cython available: {info['cython_available']}")
    except Exception as e:
        print(f"Could not get optimization info: {e}")


if __name__ == "__main__":
    try:
        run_comprehensive_benchmark()
    except KeyboardInterrupt:
        print("\nBenchmark interrupted by user")
    except Exception as e:
        logger.error(f"Benchmark failed: {e}")
        import traceback
        traceback.print_exc()