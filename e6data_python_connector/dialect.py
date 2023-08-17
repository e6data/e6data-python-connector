"""Integration between SQLAlchemy and Hive.
Some code based on
https://github.com/zzzeek/sqlalchemy/blob/rel_0_5/lib/sqlalchemy/databases/sqlite.py
which is released under the MIT license.
"""

from __future__ import absolute_import
from __future__ import unicode_literals

import datetime
import decimal
import logging
import re
from decimal import Decimal

from dateutil.parser import parse
from sqlalchemy import exc
from sqlalchemy import processors
from sqlalchemy import types
from sqlalchemy import util
# TODO shouldn't use mysql type
from sqlalchemy.databases import mysql
from sqlalchemy.engine import default, Engine, Connection
from sqlalchemy.sql import compiler
from sqlalchemy.sql.compiler import SQLCompiler

from e6data_python_connector import e6data_grpc
from e6data_python_connector.common import UniversalSet
from e6data_python_connector.exceptions import *

_logger = logging.getLogger(__name__)


class E6dataStringTypeBase(types.TypeDecorator):
    """Translates strings returned by Thrift into something else"""
    impl = types.String

    def process_bind_param(self, value, dialect):
        raise NotImplementedError("Writing to Hive not supported")


class E6dataDate(E6dataStringTypeBase):
    """Translates date strings to date objects"""
    impl = types.DATE

    def process_result_value(self, value, dialect):
        return processors.str_to_date(value)

    def result_processor(self, dialect, coltype):
        def process(value):
            if isinstance(value, datetime.datetime):
                return value.date()
            elif isinstance(value, datetime.date):
                return value
            elif value is not None:
                return parse(value).date()
            else:
                return None

        return process

    def adapt(self, impltype, **kwargs):
        return self.impl


class E6dataTimestamp(E6dataStringTypeBase):
    """Translates timestamp strings to datetime objects"""
    impl = types.TIMESTAMP

    def process_result_value(self, value, dialect):
        return processors.str_to_datetime(value)

    def result_processor(self, dialect, coltype):
        def process(value):
            if isinstance(value, datetime.datetime):
                return value
            elif value is not None:
                return parse(value)
            else:
                return None

        return process

    def adapt(self, impltype, **kwargs):
        return self.impl


class E6dataDecimal(E6dataStringTypeBase):
    """Translates strings to decimals"""
    impl = types.DECIMAL

    def process_result_value(self, value, dialect):
        if value is not None:
            return decimal.Decimal(value)
        else:
            return None

    def result_processor(self, dialect, coltype):
        def process(value):
            if isinstance(value, Decimal):
                return value
            elif value is not None:
                return Decimal(value)
            else:
                return None

        return process

    def adapt(self, impltype, **kwargs):
        return self.impl


class E6dataIdentifierPreparer(compiler.IdentifierPreparer):
    # Just quote everything to make things simpler / easier to upgrade
    reserved_words = UniversalSet()

    def __init__(self, dialect):
        super(E6dataIdentifierPreparer, self).__init__(
            dialect,
            initial_quote='"',
        )


_type_map = {
    'boolean': types.Boolean,
    'tinyint': mysql.MSTinyInteger,
    'smallint': types.SmallInteger,
    'integer': types.Integer,
    'bigint': types.BigInteger,
    'float': types.Float,
    'double': types.Float,
    'string': types.String,
    'varchar': types.String,
    'char': types.String,
    'date': E6dataDate,
    'timestamp': E6dataTimestamp,
    'binary': types.String,
    'array': types.String,
    'map': types.String,
    'struct': types.String,
    'uniontype': types.String,
    'decimal': E6dataDecimal,
}


class E6dataCompiler(SQLCompiler):
    def visit_concat_op_binary(self, binary, operator, **kw):
        return "concat(%s, %s)" % (self.process(binary.left), self.process(binary.right))

    def visit_insert(self, *args, **kwargs):
        raise NotSupportedError()

    def visit_column(self, *args, **kwargs):
        result = super(E6dataCompiler, self).visit_column(*args, **kwargs)
        return result

    def visit_char_length_func(self, fn, **kw):
        return 'length{}'.format(self.function_argspec(fn, **kw))


class E6dataTypeCompiler(compiler.GenericTypeCompiler):
    def visit_INTEGER(self, type_, **kwargs):
        return 'INT'

    def visit_NUMERIC(self, type_, **kwargs):
        return 'DECIMAL'

    def visit_CHAR(self, type_, **kwargs):
        return 'STRING'

    def visit_VARCHAR(self, type_, **kwargs):
        return 'STRING'

    def visit_NCHAR(self, type_, **kwargs):
        return 'STRING'

    def visit_TEXT(self, type_, **kwargs):
        return 'STRING'

    def visit_CLOB(self, type_, **kwargs):
        return 'STRING'

    def visit_BLOB(self, type_, **kwargs):
        return 'BINARY'

    def visit_TIME(self, type_, **kwargs):
        return 'TIMESTAMP'

    def visit_DATE(self, type_, **kwargs):
        return 'DATE'

    def visit_DATETIME(self, type_, **kwargs):
        return 'TIMESTAMP'


class E6dataDialect(default.DefaultDialect):
    preparer = E6dataIdentifierPreparer
    statement_compiler = E6dataCompiler
    supports_views = True
    supports_alter = True
    supports_pk_autoincrement = False
    supports_default_values = False
    supports_empty_insert = False
    supports_native_decimal = True
    supports_native_boolean = True
    supports_unicode_statements = True
    supports_unicode_binds = True
    returns_unicode_strings = True
    description_encoding = None
    supports_multivalues_insert = True
    type_compiler = E6dataTypeCompiler
    supports_sane_rowcount = False
    driver = b'thrift'
    name = b'E6data'
    scheme = 'e6data'
    catalog_name = None

    def _dialect_specific_select_one(self):
        return "NOOP"

    @classmethod
    def dbapi(cls):
        return e6data_grpc

    def create_connect_args(self, url):
        db = None
        if url.query.get("schema"):
            db = url.query.get("schema")
        self.catalog_name = url.query.get("catalog")
        if not self.catalog_name:
            raise Exception('Please specify catalog in query parameter.')
        kwargs = {
            "host": url.host,
            "port": url.port,
            "scheme": self.scheme,
            "username": url.username or None,
            "password": url.password or None,
            "database": db,
            "catalog": self.catalog_name
        }
        return [], kwargs

    def get_schema_names(self, connection, **kw):
        # Equivalent to SHOW DATABASES
        # Rerouting to view names
        engine = connection
        if isinstance(connection, Engine):
            cursor = connection.raw_connection().connection.cursor(catalog_name=self.catalog_name)
        elif isinstance(connection, Connection):
            cursor = connection.connection.cursor(catalog_name=self.catalog_name)
        else:
            raise Exception("Got type of object {typ}".format(typ=type(connection)))

        client = cursor.connection
        return client.get_schema_names()

    def get_view_names(self, connection, schema=None, **kw):
        return []

    def _get_table_columns(self, connection, table):
        try:
            if isinstance(connection, Engine):
                cursor = connection.raw_connection().connection.cursor(catalog_name=self.catalog_name)
            elif isinstance(connection, Connection):
                cursor = connection.connection.cursor(catalog_name=self.catalog_name)
            else:
                raise Exception("Got type of object {typ}".format(typ=type(connection)))

            client = cursor.connection
            columns = client.getColumns("default", table)
            rows = list()
            for column in columns:
                row = dict()
                row["col_name"] = column.fieldName
                row["data_type"] = column.fieldType
                rows.append(row)

            return rows
        except exc.OperationalError as e:
            # Does the table exist?
            raise e

    def has_table(self, connection, table_name, schema=None, **kwargs):
        try:
            self._get_table_columns(connection, table_name)
            return True
        except Exception:
            return False

    def get_columns(self, connection, table_name, schema=None, **kw):
        rows = self._get_table_columns(connection, table_name)
        # # Strip whitespace
        # rows = [[col.strip() if col else None for col in row] for row in rows]
        # Filter out empty rows and comment
        # rows = [row for row in rows if row[0] and row[0] != '# col_name']
        result = []
        for row in rows:
            col_name = row['col_name']
            col_type = row['data_type']
            # Take out the more detailed type information
            # e.g. 'map<int,int>' -> 'map'
            #      'decimal(10,1)' -> decimal
            col_type = re.search(r'^\w+', col_type).group(0)
            try:
                coltype = _type_map[col_type.lower()]
                _logger.info("Got column {column} with data type {dt}".format(column=col_name, dt=coltype))
            except KeyError:
                util.warn("Did not recognize type '%s' of column '%s'" % (col_type, col_name))
                coltype = types.NullType

            result.append({
                'name': col_name,
                'type': coltype,
                'nullable': True,
                'default': None,
            })
        return result

    def get_foreign_keys(self, connection, table_name, schema=None, **kw):
        # Hive has no support for foreign keys.
        return []

    def get_pk_constraint(self, connection, table_name, schema=None, **kw):
        # Hive has no support for primary keys.
        return []

    def get_indexes(self, connection, table_name, schema=None, **kw):
        return []

    def get_table_names(self, connection, schema=None, **kw):
        # Hive does not provide functionality to query tableType
        # This allows reflection to not crash at the cost of being inaccurate
        if isinstance(connection, Engine):
            cursor = connection.raw_connection().connection.cursor(catalog_name=self.catalog_name)
        elif isinstance(connection, Connection):
            cursor = connection.connection.cursor()
        else:
            raise Exception("Got type of object {typ}".format(typ=type(connection)))

        client = cursor.connection
        return client.getTables(schema)

    def do_rollback(self, dbapi_connection):
        # No transactions for Hive
        pass

    def _check_unicode_returns(self, connection, additional_tests=None):
        # We decode everything as UTF-8
        return True

    def _check_unicode_description(self, connection):
        # We decode everything as UTF-8
        return True

    def do_ping(self, connection):
        # We do not need the ping api as we are using http
        return True
