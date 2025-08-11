# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import setuptools
import sys
import os

VERSION = (2, 3, 10,)

# Check if Cython is available and user wants to build extensions
BUILD_CYTHON = os.environ.get('BUILD_CYTHON', '0') == '1'
CYTHON_AVAILABLE = False

if BUILD_CYTHON:
    try:
        from Cython.Build import cythonize
        import numpy as np
        CYTHON_AVAILABLE = True
        print("Cython extensions will be built")
    except ImportError:
        print("Warning: Cython or NumPy not available. Skipping Cython extensions.")
        BUILD_CYTHON = False


def get_long_desc():
    """
    Reads the `README.md` file to provide a detailed description of the package.

    Returns:
        str: The content of the README.md file as a string.
    """
    try:
        with open("README.md", "r", encoding="utf-8") as fh:  # Explicitly specifying encoding.
            return fh.read()
    except FileNotFoundError:
        # Fallback if README.md is missing.
        return "Client for the e6data distributed SQL Engine."


def get_extensions():
    """Get Cython extensions if enabled."""
    extensions = []
    if BUILD_CYTHON and CYTHON_AVAILABLE:
        from setup_cython import get_cython_extensions
        extensions = get_cython_extensions()
    return extensions


setup_kwargs = {
    "name": "e6data-python-connector",
    "version": ".".join(map(str, VERSION)),  # More Pythonic way to convert tuple to string.
    "author": "e6data, Inc.",
    "author_email": "info@e6data.com",
    "description": "Client for the e6data distributed SQL Engine.",
    "long_description": get_long_desc(),
    "long_description_content_type": "text/markdown",
    "url": 'https://github.com/e6x-labs/e6data-python-connector',
    "packages": setuptools.find_packages(),  # Automatically detects all packages in the source tree.
    "license": "Apache 2.0",
    "include_package_data": True,  # Includes non-Python files specified in MANIFEST.in.
    "python_requires": '>=3.9',
    "install_requires": [
        'sqlalchemy>=2.0.42',
        'future==1.0.0',
        'python-dateutil==2.9.0.post0',
        'pycryptodome==3.23.0',
        'pytz==2025.2',
        'thrift==0.22.0',
        'grpcio>=1.74.0',
        'grpcio-tools>=1.74.0',
    ],
    "classifiers": [
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS",
        "Operating System :: Microsoft :: Windows",
        "License :: OSI Approved :: Apache Software License",
        'Programming Language :: Python :: 3.9',
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Topic :: Database",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    "entry_points": {
        'sqlalchemy.dialects': [
            'e6data = e6data_python_connector.dialect:E6dataDialect'
        ],
    }
}

# Add Cython extensions if enabled
extensions = get_extensions()
if extensions:
    setup_kwargs["ext_modules"] = extensions
    # Add optional dependencies for Cython builds
    setup_kwargs["install_requires"].extend([
        'cython>=0.29.0',
        'numpy>=1.19.0',
    ])

setuptools.setup(**setup_kwargs)
