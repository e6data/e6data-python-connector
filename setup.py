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

VERSION = [2, 1, 16]


def get_long_desc():
    with open("README.md", "r") as fh:
        long_description = fh.read()
    return long_description


setuptools.setup(
    name="e6data-python-connector",
    version='.'.join('%s' % v for v in VERSION),
    author="Uniphi, Inc.",
    author_email="info@e6data.com",
    description="Client for the e6data distributed SQL Engine.",
    long_description=get_long_desc(),
    long_description_content_type="text/markdown",
    url='https://github.com/e6x-labs/e6data-python-connector',
    packages=setuptools.find_packages(),
    license="Apache 2.0",
    include_package_data=True,
    install_requires=[
        'sqlalchemy>=1.0.0',
        'future',
        'python-dateutil',
        'pycryptodome',
        'pytz',
        'thrift',
        'grpcio',
        'grpcio-tools',
        'sqlalchemy'
    ],
    classifiers=[
        "Operating System :: POSIX :: Linux",
        "License :: OSI Approved :: Apache Software License",
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9'
    ],
    entry_points={
        'sqlalchemy.dialects': [
            'e6data = e6data_python_connector.dialect:E6dataDialect'
        ],
    }
)
