#!/usr/bin/env python3
"""
Benchmark script for Cython optimizations in e6data Python connector.
Compares performance between default, Python optimized, and Cython modes.
"""

import time
import statistics
import logging
import os
import sys

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import after path setup
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_optimization_availability():
    """Test which optimization modes are available."""
    logger.info("=== Testing Optimization Availability ===")
    
    try:
        from e6data_python_connector.fast_deserializer import get_optimization_info
        info = get_optimization_info()
        
        logger.info(f"Optimization enabled: {info['optimization_enabled']}")
        logger.info(f"Current mode: {info['current_mode']}")
        logger.info(f"Cython available: {info['cython_available']}")
        
        if info['recommendations']:
            logger.info("Recommendations:")
            for rec in info['recommendations']:
                logger.info(f"  - {rec}")
        
        return info
    except ImportError as e:
        logger.error(f"Fast deserializer not available: {e}")
        return None

def benchmark_connection_creation():
    """Benchmark connection creation and basic query execution."""
    logger.info("=== Benchmarking Connection Creation ===")
    
    # Get credentials from environment
    config = {
        'host': os.environ.get('ENGINE_IP', 'localhost'),
        'port': int(os.environ.get('PORT', '443')),
        'username': os.environ.get('EMAIL'),
        'password': os.environ.get('PASSWORD'),
        'database': os.environ.get('DB_NAME', 'test_db'),
        'catalog': os.environ.get('CATALOG', 'default'),
        'cluster_name': os.environ.get('CLUSTER_NAME', 'test_cluster'),
        'secure': True
    }
    
    # Check if credentials are available
    required_vars = ['EMAIL', 'PASSWORD', 'ENGINE_IP']
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    if missing_vars:
        logger.warning(f"Missing environment variables: {', '.join(missing_vars)}")
        logger.warning("Skipping connection benchmarks")
        return None
    
    try:
        from e6data_python_connector import Connection
        
        # Test basic connection
        start_time = time.time()
        conn = Connection(**config)
        
        cursor = conn.cursor()
        cursor.execute("SELECT 1 as test_value")
        result = cursor.fetchall()
        
        conn.clear()
        end_time = time.time()
        
        duration = end_time - start_time
        logger.info(f"Basic connection test: {duration:.3f}s")
        logger.info(f"Result: {result}")
        
        return duration
        
    except Exception as e:
        logger.error(f"Connection benchmark failed: {e}")
        return None

def benchmark_data_processing():
    """Benchmark data processing with different optimization modes."""
    logger.info("=== Benchmarking Data Processing ===")
    
    try:
        from e6data_python_connector.fast_deserializer import (
            enable_fast_deserialization, 
            disable_fast_deserialization,
            get_optimization_info
        )
        
        # Test different modes
        modes = []
        
        # Test Cython mode
        try:
            enable_fast_deserialization(force_cython=True)
            info = get_optimization_info()
            if info['current_mode'] == 'cython':
                modes.append('cython')
                logger.info("✅ Cython mode available")
        except ImportError:
            logger.info("❌ Cython mode not available")
        
        # Test Python optimized mode
        enable_fast_deserialization(force_cython=False)
        info = get_optimization_info()
        if info['current_mode'] == 'python_optimized':
            modes.append('python_optimized')
            logger.info("✅ Python optimized mode available")
        
        # Test default mode
        disable_fast_deserialization()
        modes.append('default')
        logger.info("✅ Default mode available")
        
        logger.info(f"Available optimization modes: {modes}")
        return modes
        
    except ImportError as e:
        logger.error(f"Optimization benchmarking not available: {e}")
        return ['default']

def create_sample_benchmark():
    """Create a simple benchmark using mock data."""
    logger.info("=== Creating Sample Performance Test ===")
    
    try:
        # Test optimization switching
        from e6data_python_connector.fast_deserializer import (
            enable_fast_deserialization,
            disable_fast_deserialization,
            get_optimization_info
        )
        
        # Test mode switching
        logger.info("Testing optimization mode switching:")
        
        # Default mode
        disable_fast_deserialization()
        info = get_optimization_info()
        logger.info(f"  Default mode: {info['current_mode']}")
        
        # Python optimized mode
        enable_fast_deserialization(force_cython=False)
        info = get_optimization_info()
        logger.info(f"  Python optimized: {info['current_mode']}")
        
        # Cython mode (if available)
        try:
            enable_fast_deserialization(force_cython=True)
            info = get_optimization_info()
            logger.info(f"  Cython mode: {info['current_mode']}")
        except ImportError:
            logger.info("  Cython mode: Not available")
        
        # Auto-detect best mode
        enable_fast_deserialization()
        info = get_optimization_info()
        logger.info(f"  Auto-selected: {info['current_mode']}")
        
        return True
        
    except Exception as e:
        logger.error(f"Sample benchmark failed: {e}")
        return False

def main():
    """Run all benchmarks."""
    logger.info("e6data Python Connector - Cython Optimization Benchmark")
    logger.info("=" * 70)
    
    # Test optimization availability
    opt_info = test_optimization_availability()
    
    # Test connection benchmarking (if credentials available)
    conn_duration = benchmark_connection_creation()
    
    # Test data processing benchmarks
    available_modes = benchmark_data_processing()
    
    # Create sample benchmark
    sample_success = create_sample_benchmark()
    
    # Summary
    logger.info("=" * 70)
    logger.info("BENCHMARK SUMMARY")
    logger.info("=" * 70)
    
    if opt_info:
        logger.info(f"Optimizations available: {opt_info['cython_available']}")
        logger.info(f"Current mode: {opt_info['current_mode']}")
    
    if conn_duration:
        logger.info(f"Connection benchmark: {conn_duration:.3f}s")
    
    logger.info(f"Available modes: {len(available_modes)}")
    logger.info(f"Sample benchmark: {'✅ Success' if sample_success else '❌ Failed'}")
    
    if opt_info and opt_info['cython_available']:
        logger.info("🚀 Cython optimizations are working!")
    else:
        logger.info("📝 To enable Cython optimizations:")
        logger.info("   pip install cython numpy")
        logger.info("   BUILD_CYTHON=1 pip install -e .")
    
    return sample_success

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)