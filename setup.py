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

VERSION = (2, 2, 3, 'rc2')


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


setuptools.setup(
    name="e6data-python-connector",
    version=".".join(map(str, VERSION)),  # More Pythonic way to convert tuple to string.
    author="e6data, Inc.",
    author_email="info@e6data.com",
    description="Client for the e6data distributed SQL Engine.",
    long_description=get_long_desc(),
    long_description_content_type="text/markdown",
    url='https://github.com/e6x-labs/e6data-python-connector',
    packages=setuptools.find_packages(),  # Automatically detects all packages in the source tree.
    license="Apache 2.0",
    include_package_data=True,  # Includes non-Python files specified in MANIFEST.in.
    install_requires=[
        'sqlalchemy>=1.0.0',
        'future==1.0.0',
        'python-dateutil==2.9.0.post0',
        'pycryptodome==3.19.1',
        'pytz==2024.1',
        'thrift==0.20.0',
        'grpcio==1.65.1',
        'grpcio-tools',
    ],
    classifiers=[
        "Operating System :: POSIX :: Linux",
        "License :: OSI Approved :: Apache Software License",
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    entry_points={
        'sqlalchemy.dialects': [
            'e6data = e6data_python_connector.dialect:E6dataDialect'
        ],
    }
)
