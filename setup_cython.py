"""
Setup configuration for building Cython extensions.

This module configures the Cython extensions for optimized data deserialization.
"""

from setuptools import Extension
from Cython.Build import cythonize
import numpy as np

def get_cython_extensions():
    """
    Get the list of Cython extensions to build.
    
    Returns:
        list: List of Extension objects for Cython modules
    """
    extensions = [
        Extension(
            "e6data_python_connector.cython_deserializer",
            ["e6data_python_connector/cython_deserializer.pyx"],
            include_dirs=[np.get_include()],
            language="c++",
            extra_compile_args=[
                "-O3",  # Maximum optimization
                "-march=native",  # Use native CPU features
                "-ffast-math",  # Fast math operations
                "-funroll-loops",  # Unroll loops for performance
            ],
            extra_link_args=["-O3"],
            define_macros=[
                ("NPY_NO_DEPRECATED_API", "NPY_1_7_API_VERSION"),
            ],
        )
    ]
    
    return cythonize(
        extensions,
        compiler_directives={
            'language_level': '3',
            'boundscheck': False,
            'wraparound': False,
            'cdivision': True,
            'profile': False,
            'linetrace': False,
            'nonecheck': False,
            'overflowcheck': False,
            'initializedcheck': False,
        }
    )