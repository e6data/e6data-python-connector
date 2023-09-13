"""DB-API implementation backed by HiveServer2 (Thrift API)
See http://www.python.org/dev/peps/pep-0249/
Many docstrings in this file are based on the PEP, which is in the public domain.
"""

from __future__ import absolute_import
from __future__ import unicode_literals

import datetime
# Make all exceptions visible in this e6xdb per DB-API
import logging
import re
import sys
from decimal import Decimal
from io import BytesIO
from ssl import CERT_NONE, CERT_OPTIONAL, CERT_REQUIRED

from e6data_python_connector.server import QueryEngineService
from thrift.protocol import TBinaryProtocol, TMultiplexedProtocol
from thrift.transport import TSocket
from thrift.transport import TTransport

from e6xdb.common import DBAPITypeObject, ParamEscaper, DBAPICursor
from e6xdb.constants import *
from e6xdb.datainputstream import DataInputStream, get_query_columns_info, read_rows_from_batch, read_values_from_array, read_rows_from_chunk
from e6xdb.typeId import *

apilevel = '2.0'
threadsafety = 2  # Threads may share the e6xdb and connections.
paramstyle = 'pyformat'  # Python extended format codes, e.g. ...WHERE name=%(name)s

_logger = logging.getLogger(__name__)

_TIMESTAMP_PATTERN = re.compile(r'(\d+-\d+-\d+ \d+:\d+:\d+(\.\d{,6})?)')

ssl_cert_parameter_map = {
    "none": CERT_NONE,
    "optional": CERT_OPTIONAL,
    "required": CERT_REQUIRED,
}


def _parse_timestamp(value):
    if value:
        match = _TIMESTAMP_PATTERN.match(value)
        if match:
            if match.group(2):
                format = '%Y-%m-%d %H:%M:%S.%f'
                # use the pattern to truncate the value
                value = match.group()
            else:
                format = '%Y-%m-%d %H:%M:%S'
            value = datetime.datetime.strptime(value, format)
        else:
            raise Exception(
                'Cannot convert "{}" into a datetime'.format(value))
    else:
        value = None
    return value


TYPES_CONVERTER = {"DECIMAL_TYPE": Decimal,
                   "TIMESTAMP_TYPE": _parse_timestamp}


class HiveParamEscaper(ParamEscaper):
    def escape_string(self, item):
        # backslashes and single quotes need to be escaped
        # TODO verify against parser
        # Need to decode UTF-8 because of old sqlalchemy.
        # Newer SQLAlchemy checks dialect.supports_unicode_binds before encoding Unicode strings
        # as byte strings. The old version always encodes Unicode as byte strings, which breaks
        # string formatting here.
        if isinstance(item, bytes):
            item = item.decode('utf-8')
        return "'{}'".format(
            item
            .replace('\\', '\\\\')
            .replace("'", "\\'")
            .replace('\r', '\\r')
            .replace('\n', '\\n')
            .replace('\t', '\\t')
        )


_escaper = HiveParamEscaper()


def connect(*args, **kwargs):
    """Constructor for creating a connection to the database. See class :py:class:`Connection` for
    arguments.
    :returns: a :py:class:`Connection` object.
    """
    return Connection(*args, **kwargs)


class Connection(object):
    """Wraps a http e6xdb session"""

    def __init__(
            self,
            host=None,
            port=None,
            scheme='e6data',
            username=None,
            database='default',
            auth=None,
            configuration=None,
            kerberos_service_name=None,
            password=None,
            check_hostname=None,
            ssl_cert=None,
            thrift_transport=None
    ):
        self.__username = username
        self.__password = password
        self._database = database
        self._session_id = None

        # service_name = 'E6x'  # E6x  QueryExecutor
        service_name = 'QueryEngine'  # E6x  QueryExecutor

        if not self.__username or not self.__password:
            raise ValueError("username or password cannot be empty.")
        if port is None:
            port = 9000
        self._transport = TSocket.TSocket(host, port)
        self._transport = TTransport.TBufferedTransport(self._transport)

        protocol = TBinaryProtocol.TBinaryProtocol(self._transport)
        protocol = TMultiplexedProtocol.TMultiplexedProtocol(protocol, service_name)
        self._client = QueryEngineService.Client(protocol)
        self._transport.open()

    @property
    def get_session_id(self):
        """
        To get the session id, if user is not authorised, first authenticate the user.
        """
        if not self._session_id:
            try:
                self._session_id = self._client.authenticate(self.__username, self.__password)
                if not self._session_id:
                    raise ValueError("Invalid credentials.")
                # self._client.setSchema(database)
            except Exception as e:
                self._transport.close()
                raise e
        return self._session_id

    def update_users(self, user_info):
        self.client.updateUsers(userInfo=user_info)

    def set_prop_map(self, prop_map: str):
        """
        To enable to disable the caches.
        :param prop_map: To set engine props
        """
        self._client.setProps(sessionId=self.get_session_id, propMap=prop_map)

    def __enter__(self):
        """Transport should already be opened by __init__"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Call close"""
        self.close()

    def close(self):
        self._transport.close()

    def check_connection(self):
        return self._transport.isOpen()

    def clear(self, query_id):
        self._client.clear(sessionId=self.get_session_id, queryId=query_id)
        self._session_id = None

    def reopen(self):
        self._transport.close()
        self._transport.open()

    def query_cancel(self, query_id):
        self._client.cancelQuery(sessionId=self.get_session_id, queryId=query_id)

    def dry_run(self, query):
        return self._client.dryRun(sessionId=self.get_session_id, sSchema=self._database, sQueryString=query)

    def dry_run_v2(self, catalog_name, query):
        return self._client.dryRunV2(
            sessionId=self.get_session_id,
            catalogName=catalog_name,
            sSchema=self._database,
            sQueryString=query
        )

    def get_tables(self, database):
        return self._client.getTables(sessionId=self.get_session_id, schema=database)

    def get_tables_v2(self, catalog_name, database):
        return self._client.getTablesV2(sessionId=self.get_session_id, catalogName=catalog_name, schema=database)

    def get_columns(self, database, table):
        return self._client.getColumns(sessionId=self.get_session_id, schema=database, table=table)

    def status(self, query_id):
        return self._client.status(sessionId=self.get_session_id, queryId=query_id)

    def get_add_catalog_response(self):
        """
        Response Type:
            AddCatalogsResponse(status='success', failures=[])
        Usage:
            response.status: success, in_progress, failed

        Error Usage:
            response = conn.get_add_catalog_response()
            if response.status == 'error'
                print(response.failures[0].reason)
        """
        return self._client.getAddCatalogsResponse(sessionId=self.get_session_id)

    def get_columns_v2(self, catalog_name, database, table):
        return self._client.getColumnsV2(
            sessionId=self.get_session_id,
            catalogName=catalog_name,
            schema=database,
            table=table
        )

    def get_schema_names(self):
        return self._client.getSchemaNames(sessionId=self.get_session_id)

    def get_schema_names_v2(self, catalog_name):
        return self._client.getSchemaNamesV2(sessionId=self.get_session_id, catalogName=catalog_name)

    def add_catalogs(self, catalogs_info):
        return self._client.addCatalogs(sessionId=self.get_session_id, jsonString=catalogs_info)

    def commit(self):
        """We do not support transactions, so this does nothing."""
        pass

    def cursor(self, db_name=None, catalog_name=None):
        """Return a new :py:class:`Cursor` object using the connection."""
        return Cursor(self, database=db_name, catalog_name=catalog_name)

    def rollback(self):
        raise Exception("e6xdb does not support transactions")  # pragma: no cover

    @property
    def client(self):
        return self._client


class Cursor(DBAPICursor):
    """These objects represent a database cursor, which is used to manage the context of a fetch
    operation.
    Cursors are not isolated, i.e., any changes done to the database by a cursor are immediately
    visible by other cursors or connections.
    """
    rows_count = 0

    def __init__(self, connection, catalog_name=None, arraysize=1000, database=None):
        super(Cursor, self).__init__()
        self._catalog_name = catalog_name
        self._arraysize = arraysize
        self.connection = connection
        self._data = None
        self._query_columns_description = None
        self._is_metadata_updated: bool = False
        self._description = None
        self._query_id = None
        self._batch = list()
        self._rowcount = 0
        self._database = self.connection.database if database is None else database

    def _reset_state(self):
        """Reset state about the previous query in preparation for running another query"""
        pass

    @property
    def arraysize(self):
        return self._arraysize

    @arraysize.setter
    def arraysize(self, value):
        """Array size cannot be None, and should be an integer"""
        default_arraysize = 1000
        try:
            self._arraysize = int(value) or default_arraysize
        except TypeError:
            self._arraysize = default_arraysize

    @property
    def description(self):
        """This read-only attribute is a sequence of 7-item sequences.
        Each of these sequences contains information describing one result column:
        - name
        - type_code
        - display_size (None in current implementation)
        - internal_size (None in current implementation)
        - precision (None in current implementation)
        - scale (None in current implementation)
        - null_ok (always True in current implementation)
        This attribute will be ``None`` for operations that do not return rows or if the cursor has
        not had an operation invoked via the :py:meth:`execute` method yet.
        The ``type_code`` can be interpreted by comparing it to the Type Objects specified in the
        section below.
        """
        if self._description is None:
            self._description = []
            for col in self._query_columns_description:
                type_code = col.get_field_type()
                column_name = col.get_name()
                self._description.append((
                    column_name,
                    type_code,
                    None, None, None, None, True
                ))
        return self._description

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close the operation handle"""
        self.connection.close()
        self._arraysize = None
        self.connection = None
        self._data = None
        self._query_columns_description = None
        self._description = None
        self._query_id = None
        self._batch = None
        self._rowcount = None
        self._database = None

    def get_tables(self):
        schema = self.connection.database
        return self.connection.get_tables(database=schema)

    def get_columns(self, table):
        schema = self.connection.database
        return self.connection.get_columns(database=schema, table=table)

    def clear(self):
        """Clears the tmp data"""
        self.connection.clear(self._query_id)

    def cancel(self, query_id):
        _logger.info("Cancelling query")
        self.connection.query_cancel(query_id)

    def execute(self, operation, parameters=None, **kwargs):
        """Prepare and execute a database operation (query or command).
        Return values are not defined.
        """
        """
        Semicolon is now not supported. So removing it from query end.
        """
        operation = operation.strip()
        if operation.endswith(';'):
            operation = operation[:-1]

        # Prepare statement
        if parameters is None:
            sql = operation
        else:
            sql = operation % _escaper.escape_args(parameters)

        client = self.connection.client
        if self._catalog_name:
            self._query_id = client.prepareStatementV2(
                self.connection.get_session_id,
                self._catalog_name,
                self._database,
                sql
            )
        else:
            self._query_id = client.prepareStatement(
                self.connection.get_session_id,
                self._database,
                sql
            )
        client.executeStatement(self.connection.get_session_id, self._query_id)
        self.update_mete_data()
        return self._query_id

    def rowcount(self):
        return self._rowcount

    def update_mete_data(self):
        buffer = self.connection.client.getResultMetadata(self.connection.get_session_id, self._query_id)
        buffer = BytesIO(buffer)
        self._rowcount, self._query_columns_description = get_query_columns_info(buffer)

    def _fetch_more(self):
        # _logger.info("fetching batch")
        batch_size = self._arraysize
        self._data = list()
        for i in range(batch_size):
            rows = self.fetch_batch()
            if rows is None:
                return
            self._data = self._data + rows

        # _logger.info("fetched batch of {num}".format(num=len(self._data)))
        return self._data

    def _fetch_all(self):
        self._data = list()
        while True:
            rows = self.fetch_batch()
            if rows is None:
                break
            self._data = self._data + rows
        rows = self._data
        self._data = None
        return rows

    def fetchall_buffer(self, query_id=None):
        if query_id:
            self._query_id = query_id
        while True:
            rows = self.fetch_batch()
            if not rows:
                return
            yield rows

    # Look at this as well
    def fetch_batch(self):
        # _logger.debug("fetching next batch from e6data")
        client = self.connection.client
        buffer = client.getNextResultBatch(self.connection.get_session_id, self._query_id)
        if not self._is_metadata_updated:
            self.update_mete_data()
            self._is_metadata_updated = True
        if not buffer:
            return None
        return read_rows_from_chunk(self._query_columns_description, buffer)
        # dis = DataInputStream(buffer)
        # one batch retrieves the predefined set of rows
        # return read_rows_from_batch(self._query_columns_description, dis)

    def fetchall(self, query_id=None):
        if query_id:
            self._query_id = query_id
        return self._fetch_all()

    def fetchmany(self, size=None, query_id=None):
        # _logger.info("fetching all from overriden method")
        if query_id:
            self._query_id = query_id
        if size is None:
            size = self.arraysize
        if self._data is None:
            self._data = list()
        while len(self._data) < size:
            # _logger.info("fetching next batch from fetch many")
            rows = self.fetch_batch()
            if rows is None:
                break
            self._data += rows
        _logger.info(len(self._data))
        if len(self._data) <= size:
            rows = self._data
            self._data = None
            return rows
        rows = self._data[:size]
        self._data = self._data[size:]
        return rows

    def fetchone(self):
        # _logger.info("fetch One returning the batch itself which is limited by predefined no.of rows")
        rows_to_return = []
        client = self.connection.client
        buffer = client.getNextResultRow(self.connection.get_session_id, self._query_id)
        if not self._is_metadata_updated:
            self.update_mete_data()
            self._is_metadata_updated = True
        if not buffer:
            return None
        buffer = BytesIO(buffer)
        dis = DataInputStream(buffer)
        rows_to_return.append(read_values_from_array(self._query_columns_description, dis))
        return rows_to_return

    def explain(self):
        return self.connection.client.explain(self.connection.get_session_id, self._query_id)

    def explain_analyse(self):
        return self.connection.client.explainAnalyze(self.connection.get_session_id, self._query_id)


def poll(self, get_progress_update=True):
    """Poll for and return the raw status data provided by the Hive Thrift REST API.
    :returns: ``ttypes.TGetOperationStatusResp``
    :raises: ``ProgrammingError`` when no query has been started
    .. note::
        This is not a part of DB-API.
    """
    pass


def fetch_logs(self):
    """Retrieve the logs produced by the execution of the query.
    Can be called multiple times to fetch the logs produced after the previous call.
    :returns: list<str>
    :raises: ``ProgrammingError`` when no query has been started
    .. note::
        This is not a part of DB-API.
    """
    pass


class Error(Exception):
    pass


#
# Type Objects and Constructors
#

for type_id in PRIMITIVE_TYPES:
    name = TypeId._VALUES_TO_NAMES[type_id]
    setattr(sys.modules[__name__], name, DBAPITypeObject([name]))
