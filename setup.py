import os

import setuptools

envstring = lambda var: os.environ.get(var) or ""

VERSION = [1, 0, 0]


def get_long_desc():
    with open("README.md", "r") as fh:
        long_description = fh.read()
    return long_description


setuptools.setup(
    name="e6data-python-connector",
    version='.'.join('%d' % v for v in VERSION[0:3]),
    author="Uniphi, Inc.",
    author_email="info@e6data.com",
    description="Client for the e6data distributed SQL Engine.",
    long_description=get_long_desc(),
    long_description_content_type="text/markdown",
    url='https://github.com/e6x-labs/e6data-python-connector',
    packages=setuptools.find_packages(),
    include_package_data=True,
    install_requires=[
        'sqlalchemy>=1.0.0',
        'future',
        'python-dateutil',
        'pycryptodome',
        'pytz',
        'thrift',
    ],
    classifiers=[
        "Operating System :: POSIX :: Linux",
        "License :: OSI Approved :: MIT License",
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9'
    ],
    entry_points={
        'sqlalchemy.dialects': [
            'e6xdb = e6xdb.sqlalchemy_e6x:E6xDialect'
        ],
    }
)
