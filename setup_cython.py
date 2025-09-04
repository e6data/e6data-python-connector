"""
Cython build configuration for e6data Python connector.
Handles compilation of Cython extensions with optimizations.
"""

import os
import sys
from distutils.extension import Extension

def get_cython_extensions():
    """
    Get Cython extension configurations.
    
    Returns:
        list: List of Extension objects for Cython compilation
    """
    
    # Check if we should build Cython extensions
    if not os.environ.get('BUILD_CYTHON'):
        return []
    
    try:
        from Cython.Build import cythonize
        import numpy as np
    except ImportError as e:
        print(f"Warning: Cython or NumPy not available, skipping Cython build: {e}")
        return []
    
    # Compiler directives for optimization
    compiler_directives = {
        'language_level': 3,
        'boundscheck': False,
        'wraparound': False,
        'cdivision': True,
        'nonecheck': False,
        'profile': False,
        'linetrace': False,
    }
    
    # Base compilation arguments
    extra_compile_args = ['-O3']
    extra_link_args = []
    
    # Platform-specific optimizations
    if sys.platform.startswith('linux'):
        extra_compile_args.extend([
            '-march=native',
            '-ffast-math',
            '-funroll-loops',
            '-fno-strict-aliasing'
        ])
    elif sys.platform == 'darwin':  # macOS
        extra_compile_args.extend([
            '-march=native' if 'arm64' not in os.uname().machine else '-mcpu=native',
            '-ffast-math',
            '-funroll-loops'
        ])
    elif sys.platform.startswith('win'):
        extra_compile_args = ['/O2', '/favor:AMD64']
    
    # Define extensions
    extensions = [
        Extension(
            "e6data_python_connector.cython_deserializer",
            ["e6data_python_connector/cython_deserializer.pyx"],
            include_dirs=[np.get_include()],
            extra_compile_args=extra_compile_args,
            extra_link_args=extra_link_args,
            language="c++"
        )
    ]
    
    # Apply Cython compilation
    try:
        return cythonize(
            extensions,
            compiler_directives=compiler_directives,
            annotate=bool(os.environ.get('CYTHON_ANNOTATE')),  # Generate HTML annotation files
            nthreads=int(os.environ.get('CYTHON_THREADS', '0')),  # Parallel compilation
        )
    except Exception as e:
        print(f"Warning: Failed to cythonize extensions: {e}")
        return []

def check_cython_requirements():
    """
    Check if all requirements for Cython compilation are available.
    
    Returns:
        tuple: (bool, list) - (requirements_met, missing_items)
    """
    missing = []
    
    # Check for Cython
    try:
        import Cython
        cython_version = Cython.__version__
        print(f"Found Cython {cython_version}")
    except ImportError:
        missing.append("cython>=0.29.0")
    
    # Check for NumPy
    try:
        import numpy as np
        numpy_version = np.__version__
        print(f"Found NumPy {numpy_version}")
    except ImportError:
        missing.append("numpy>=1.19.0")
    
    # Check for C compiler
    try:
        import distutils.util
        import distutils.spawn
        
        if sys.platform.startswith('win'):
            # Windows: check for Visual Studio
            compiler = distutils.spawn.find_executable('cl')
            if not compiler:
                missing.append("Visual Studio Build Tools or Visual Studio with C++ support")
        else:
            # Unix: check for GCC/Clang
            gcc = distutils.spawn.find_executable('gcc')
            clang = distutils.spawn.find_executable('clang')
            if not (gcc or clang):
                missing.append("C compiler (gcc, clang, or build-essential)")
    except Exception:
        missing.append("C compiler")
    
    return len(missing) == 0, missing

def print_build_info():
    """Print information about the build environment."""
    print("=" * 60)
    print("e6data Python Connector - Cython Build Information")
    print("=" * 60)
    
    print(f"Python version: {sys.version}")
    print(f"Platform: {sys.platform}")
    print(f"BUILD_CYTHON: {os.environ.get('BUILD_CYTHON', 'Not set')}")
    
    requirements_met, missing = check_cython_requirements()
    
    if requirements_met:
        print("✅ All Cython build requirements satisfied")
    else:
        print("❌ Missing Cython build requirements:")
        for item in missing:
            print(f"   - {item}")
        print("\nTo install missing dependencies:")
        if 'cython' in str(missing).lower():
            print("   pip install cython>=0.29.0")
        if 'numpy' in str(missing).lower():
            print("   pip install numpy>=1.19.0")
        if 'compiler' in str(missing).lower():
            if sys.platform.startswith('linux'):
                print("   sudo apt-get install build-essential python3-dev")
            elif sys.platform == 'darwin':
                print("   xcode-select --install")
            elif sys.platform.startswith('win'):
                print("   Install Visual Studio Build Tools")
    
    print("=" * 60)

if __name__ == "__main__":
    print_build_info()