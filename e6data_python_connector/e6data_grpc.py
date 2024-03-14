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

import grpc

from e6data_python_connector.common import DBAPITypeObject, ParamEscaper, DBAPICursor
from e6data_python_connector.constants import *
from e6data_python_connector.datainputstream import get_query_columns_info, read_rows_from_chunk
from e6data_python_connector.server import e6x_engine_pb2_grpc, e6x_engine_pb2
from e6data_python_connector.typeId import *

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


def _get_grpc_header(engine_ip=None, cluster=None):
    metadata = []
    if engine_ip:
        metadata.append(('plannerip', engine_ip))
    if cluster:
        metadata.append(('cluster-uuid', cluster))
    return metadata


def connect(*args, **kwargs):
    """Constructor for creating a connection to the database. See class :py:class:`Connection` for
    arguments.
    :returns: a :py:class:`Connection` object.
    """
    return Connection(*args, **kwargs)


class Connection(object):
    """Create connection to e6data """

    def __init__(
            self,
            host: str,
            port: int,
            username: str,
            password: str,
            scheme: str = 'e6data',
            catalog: str = None,
            database: str = None,
            cluster_uuid: str = None,
            secure: bool = False,
            grpc_options: str = None,
    ):
        """
        Parameters
        ----------
            host: str
                IP address or hostname of e6data cluster
            port: int
                Port of the e6data engine
            username: str
                Your e6data Email ID
            password: str
                Access Token generated in the e6data console
            scheme: str
                e6data
            catalog: str
                Catalog name
            database: str
                Database to perform the query on
            cluster_uuid: str
                Cluster's uuid
            secure: bool, Optional
                Flag to use a secure channel for data transfer
            grpc_options: dict, Optional
                Specify gRPC configuration
                - keepalive_timeout_ms: This parameter defines the time, in milliseconds, that a gRPC connection should remain idle before sending a keepalive ping to check if the connection is still alive.
                - max_receive_message_length: This parameter sets the maximum allowed size (in bytes) for incoming messages on the gRPC server.
                - max_send_message_length: Similar to max_receive_message_length, this parameter sets the maximum allowed size (in bytes) for outgoing messages from the gRPC client
        """
        if not username or not password:
            raise ValueError("username or password cannot be empty.")
        if not host or not port:
            raise ValueError("host or port cannot be empty.")
        self.__username = username
        self.__password = password
        self.database = database
        self.cluster_uuid = cluster_uuid
        self._session_id = None
        self._host = host
        self._port = port

        self._secure_channel = secure

        self.catalog_name = catalog

        self._keepalive_timeout_ms = 900000
        self._max_receive_message_length = -1
        self._max_send_message_length = 300 * 1024 * 1024  # mb
        self._grpc_prepare_timeout = 10 * 60  # 10 minutes

        if type(grpc_options) == dict:
            self._keepalive_timeout_ms = grpc_options.get('keepalive_timeout_ms') or self._keepalive_timeout_ms
            self._max_receive_message_length = grpc_options.get(
                'max_receive_message_length') or self._max_receive_message_length
            self._max_send_message_length = grpc_options.get('max_send_message_length') or self._max_send_message_length
            self._grpc_prepare_timeout = grpc_options.get('grpc_prepare_timeout') or self._grpc_prepare_timeout
        self._create_client()

    def _create_client(self):
        if self._secure_channel:
            self._channel = grpc.secure_channel(
                target='{}:{}'.format(self._host, self._port),
                options=[
                    ("grpc.keepalive_timeout_ms", self._keepalive_timeout_ms),
                    ('grpc.max_send_message_length', self._max_send_message_length),
                    ('grpc.max_receive_message_length', self._max_receive_message_length)
                ],
                credentials=grpc.ssl_channel_credentials()
            )
        else:
            self._channel = grpc.insecure_channel(
                target='{}:{}'.format(self._host, self._port),
                options=[
                    ("grpc.keepalive_timeout_ms", self._keepalive_timeout_ms),
                    ('grpc.max_send_message_length', self._max_send_message_length),
                    ('grpc.max_receive_message_length', self._max_receive_message_length)
                ]
            )
        self._client = e6x_engine_pb2_grpc.QueryEngineServiceStub(self._channel)

    @property
    def get_session_id(self):
        """
        To get the session id, if user is not authorised, first authenticate the user.
        """
        if not self._session_id:
            try:
                authenticate_request = e6x_engine_pb2.AuthenticateRequest(
                    user=self.__username,
                    password=self.__password
                )
                authenticate_response = self._client.authenticate(
                    authenticate_request,
                    metadata=_get_grpc_header(cluster=self.cluster_uuid)
                )
                self._session_id = authenticate_response.sessionId
                if not self._session_id:
                    raise ValueError("Invalid credentials.")
            except Exception as e:
                self._channel.close()
                raise e
        return self._session_id

    def update_users(self, user_info):
        self.client.updateUsers(userInfo=user_info)

    def set_prop_map(self, prop_map: str):
        """
        To enable to disable the caches.
        :param prop_map: To set engine props
        """
        set_props_request = e6x_engine_pb2.SetPropsRequest(sessionId=self.get_session_id, props=prop_map)
        self._client.setProps(set_props_request)

    def __enter__(self):
        """Transport should already be opened by __init__"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Call close"""
        self.close()

    def close(self):
        if self._channel is not None:
            self._channel.close()
            self._channel = None

    def check_connection(self):
        return self._channel is not None

    def clear(self, query_id, engine_ip=None):
        clear_request = e6x_engine_pb2.ClearRequest(
            sessionId=self.get_session_id,
            queryId=query_id,
            engineIP=engine_ip
        )
        self._client.clear(
            clear_request,
            metadata=_get_grpc_header(engine_ip=engine_ip, cluster=self.cluster_uuid)
        )
        self._session_id = None

    def reopen(self):
        self._channel.close()
        self._create_client()

    def query_cancel(self, engine_ip, query_id):
        cancel_query_request = e6x_engine_pb2.CancelQueryRequest(
            engineIP=engine_ip,
            sessionId=self.get_session_id,
            queryId=query_id
        )
        self._client.cancelQuery(
            cancel_query_request,
            metadata=_get_grpc_header(engine_ip=engine_ip, cluster=self.cluster_uuid)
        )

    def dry_run(self, query):
        dry_run_request = e6x_engine_pb2.DryRunRequest(
            sessionId=self.get_session_id,
            schema=self.database,
            queryString=query
        )
        dry_run_response = self._client.dryRun(
            dry_run_request,
            metadata=_get_grpc_header(cluster=self.cluster_uuid)
        )
        return dry_run_response.dryrunValue

    def get_tables(self, catalog, database):
        get_table_request = e6x_engine_pb2.GetTablesV2Request(
            sessionId=self.get_session_id,
            schema=database,
            catalog=catalog
        )
        get_table_response = self._client.getTablesV2(
            get_table_request,
            metadata=_get_grpc_header(cluster=self.cluster_uuid)
        )
        return list(get_table_response.tables)

    def get_columns(self, catalog, database, table):
        get_columns_request = e6x_engine_pb2.GetColumnsV2Request(
            sessionId=self.get_session_id,
            schema=database,
            table=table,
            catalog=catalog
        )
        get_columns_response = self._client.getColumnsV2(
            get_columns_request,
            metadata=_get_grpc_header(cluster=self.cluster_uuid)
        )
        return [{'fieldName': row.fieldName, 'fieldType': row.fieldType} for row in get_columns_response.fieldInfo]

    def get_schema_names(self, catalog):
        get_schema_request = e6x_engine_pb2.GetSchemaNamesV2Request(
            sessionId=self.get_session_id,
            catalog=catalog
        )
        get_schema_response = self._client.getSchemaNamesV2(
            get_schema_request,
            metadata=_get_grpc_header(cluster=self.cluster_uuid)
        )
        return list(get_schema_response.schemas)

    def commit(self):
        """We do not support transactions, so this does nothing."""
        pass

    def cursor(self, catalog_name=None, db_name=None):
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

    def __init__(self, connection: Connection, array_size=1000, database=None, catalog_name=None):
        super(Cursor, self).__init__()
        self._array_size = array_size
        self.connection = connection
        self._data = None
        self._query_columns_description = None
        self._is_metadata_updated = False
        self._description = None
        self._query_id = None
        self._engine_ip = None
        self._batch = list()
        self._rowcount = 0
        self._database = self.connection.database if database is None else database
        self._catalog_name = catalog_name if catalog_name else self.connection.catalog_name

    def _reset_state(self):
        """Reset state about the previous query in preparation for running another query"""
        pass

    @property
    def metadata(self):
        return _get_grpc_header(engine_ip=self._engine_ip, cluster=self.connection.cluster_uuid)

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
        # self.connection.close()
        try:
            self.clear()
        except:
            pass
        self._arraysize = None
        self.connection = None
        self._data = None
        self._engine_ip = None
        self._query_columns_description = None
        self._description = None
        self._query_id = None
        self._batch = None
        self._rowcount = None
        self._database = None

    def get_tables(self):
        schema = self.connection.database
        return self.connection.get_tables(catalog=self._catalog_name, database=schema)

    def get_columns(self, table):
        schema = self.connection.database
        return self.connection.get_columns(catalog=self._catalog_name, database=schema, table=table)

    def get_schema_names(self):
        return self.connection.get_schema_names(catalog=self._catalog_name)

    def clear(self, query_id=None):
        if not query_id:
            query_id = self._query_id
        clear_request = e6x_engine_pb2.ClearRequest(
            sessionId=self.connection.get_session_id,
            queryId=query_id,
            engineIP=self._engine_ip
        )
        return self.connection.client.clear(clear_request, metadata=self.metadata)

    def cancel(self, query_id):
        self.connection.query_cancel(engine_ip=self._engine_ip, query_id=query_id)

    def status(self, query_id):
        status_request = e6x_engine_pb2.StatusRequest(
            sessionId=self.connection.get_session_id,
            queryId=query_id,
            engineIP=self._engine_ip
        )
        return self.connection.client.status(status_request, metadata=self.metadata)

    def execute(self, operation, parameters=None, **kwargs):
        """Prepare and execute a database operation (query or command).
        Return values are not defined.
        """
        """
        Semicolon is now not supported. So removing it from query end.
        """
        operation = operation.strip()  # Remove leading and trailing whitespaces.
        if operation.endswith(';'):
            operation = operation[:-1]

        # Prepare statement
        if parameters is None:
            sql = operation
        else:
            sql = operation % _escaper.escape_args(parameters)

        client = self.connection.client
        if not self._catalog_name:
            prepare_statement_request = e6x_engine_pb2.PrepareStatementRequest(
                sessionId=self.connection.get_session_id,
                schema=self._database,
                queryString=sql
            )
            prepare_statement_response = client.prepareStatement(
                prepare_statement_request,
                metadata=self.metadata
            )

            self._query_id = prepare_statement_response.queryId
            self._engine_ip = prepare_statement_response.engineIP
            execute_statement_request = e6x_engine_pb2.ExecuteStatementRequest(
                engineIP=self._engine_ip,
                sessionId=self.connection.get_session_id,
                queryId=self._query_id,
            )
            client.executeStatement(
                execute_statement_request,
                metadata=self.metadata
            )
        else:
            prepare_statement_request = e6x_engine_pb2.PrepareStatementV2Request(
                sessionId=self.connection.get_session_id,
                schema=self._database,
                catalog=self._catalog_name,
                queryString=sql
            )
            prepare_statement_response = client.prepareStatementV2(
                prepare_statement_request,
                metadata=self.metadata,
                timeout=self._grpc_prepare_timeout
            )

            self._query_id = prepare_statement_response.queryId
            self._engine_ip = prepare_statement_response.engineIP
            execute_statement_request = e6x_engine_pb2.ExecuteStatementV2Request(
                engineIP=self._engine_ip,
                sessionId=self.connection.get_session_id,
                queryId=self._query_id
            )
            client.executeStatementV2(
                execute_statement_request,
                metadata=self.metadata
            )
        self.update_mete_data()
        return self._query_id

    @property
    def rowcount(self):
        self.update_mete_data()
        return self._rowcount

    def update_mete_data(self):
        result_meta_data_request = e6x_engine_pb2.GetResultMetadataRequest(
            engineIP=self._engine_ip,
            sessionId=self.connection.get_session_id,
            queryId=self._query_id
        )
        get_result_metadata_response = self.connection.client.getResultMetadata(
            result_meta_data_request,
            metadata=self.metadata
        )
        buffer = BytesIO(get_result_metadata_response.resultMetaData)
        self._rowcount, self._query_columns_description = get_query_columns_info(buffer)
        self._is_metadata_updated = True

    def _fetch_more(self):
        batch_size = self._arraysize
        self._data = list()
        for i in range(batch_size):
            rows = self.fetch_batch()
            if rows is None:
                return
            self._data = self._data + rows
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

    def fetch_batch(self):
        client = self.connection.client
        get_next_result_batch_request = e6x_engine_pb2.GetNextResultBatchRequest(
            engineIP=self._engine_ip,
            sessionId=self.connection.get_session_id,
            queryId=self._query_id
        )
        get_next_result_batch_response = client.getNextResultBatch(
            get_next_result_batch_request,
            metadata=self.metadata
        )
        buffer = get_next_result_batch_response.resultBatch
        if not self._is_metadata_updated:
            self.update_mete_data()
        if not buffer or len(buffer) == 0:
            return None
        # one batch retrieves the predefined set of rows
        return read_rows_from_chunk(self._query_columns_description, buffer)

    def fetchall(self):
        return self._fetch_all()

    def fetchmany(self, size: int = None):
        # _logger.info("fetching all from overriden method")
        if size is None:
            size = self.arraysize
        if self._data is None:
            self._data = list()
        while len(self._data) < size:
            rows = self.fetch_batch()
            if rows is None:
                break
            self._data += rows
        if len(self._data) <= size:
            rows = self._data
            self._data = None
            return rows
        rows = self._data[:size]
        self._data = self._data[size:]
        return rows

    def fetchone(self):
        # _logger.info("fetch One returning the batch itself which is limited by predefined no.of rows")
        rows = self.fetchmany(1)
        if rows is None or len(rows) == 0:
            return None
        return rows

    def explain(self):
        explain_request = e6x_engine_pb2.ExplainRequest(
            engineIP=self._engine_ip,
            sessionId=self.connection.get_session_id,
            queryId=self._query_id
        )
        explain_response = self.connection.client.explain(
            explain_request,
            metadata=self.metadata
        )
        return explain_response.explain

    def explain_analyse(self):
        explain_analyze_request = e6x_engine_pb2.ExplainAnalyzeRequest(
            engineIP=self._engine_ip,
            sessionId=self.connection.get_session_id,
            queryId=self._query_id
        )
        explain_analyze_response = self.connection.client.explainAnalyze(
            explain_analyze_request,
            metadata=self.metadata
        )
        return dict(
            is_cached=explain_analyze_response.isCached,
            parsing_time=explain_analyze_response.parsingTime,
            queuing_time=explain_analyze_response.queueingTime,
            planner=explain_analyze_response.explainAnalyze,
        )


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
