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
import time
from decimal import Decimal
from io import BytesIO
from ssl import CERT_NONE, CERT_OPTIONAL, CERT_REQUIRED

import grpc
from grpc._channel import _InactiveRpcError

from e6data_python_connector.cluster_manager import ClusterManager
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
                'Cannot convert "{}" into a datetime'.format(value)
            )
    else:
        value = None
    return value


TYPES_CONVERTER = {
    "DECIMAL_TYPE": Decimal,
    "TIMESTAMP_TYPE": _parse_timestamp
}


def re_auth(func):
    def wrapper(self, *args, **kwargs):
        max_retry = 5
        current_retry = 0
        while current_retry < max_retry:
            try:
                return func(self, *args, **kwargs)
            except _InactiveRpcError as e:
                current_retry += 1
                if current_retry == max_retry:
                    raise e
                if e.code() == grpc.StatusCode.INTERNAL and 'Access denied' in e.details():
                    time.sleep(0.2)
                    _logger.info(f'RE_AUTH: Function Name: {func}')
                    _logger.info(f'RE_AUTH: Error Found {e}')
                    self.connection.get_re_authenticate_session_id()
                else:
                    raise e

    return wrapper


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
            auto_resume: bool = False,
            grpc_options: dict = None,
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
            auto_resume: bool, Optional
                Flag to enable auto resume of the cluster before the query execution
            grpc_options: dict, Optional
                Specify gRPC configuration
                - keepalive_timeout_ms: This parameter defines the time, in milliseconds, that a gRPC connection should remain idle before sending a keepalive ping to check if the connection is still alive.
                - max_receive_message_length: This parameter sets the maximum allowed size (in bytes) for incoming messages on the gRPC server.
                - max_send_message_length: Similar to max_receive_message_length, this parameter sets the maximum allowed size (in bytes) for outgoing messages from the gRPC client
                - grpc_prepare_timeout: Timeout for prepare statement API call (default to 10 minutes).
                - keepalive_time_ms: This parameter defines the time, in milliseconds, Default to 30 seconds
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

        self._auto_resume = auto_resume

        self._grpc_options = grpc_options
        if self._grpc_options is None:
            self._grpc_options = dict()
        self.grpc_prepare_timeout = self._grpc_options.get('grpc_prepare_timeout') or 10 * 60  # 10 minutes
        self._create_client()

    @property
    def _get_grpc_options(self):
        """
        Property to get gRPC options for the connection.

        This method checks if the gRPC options are already cached. If not, it creates a copy of the
        provided gRPC options and merges them with the default options. The merged options are then
        cached for future use.

        Returns:
            list: A list of tuples containing gRPC options.
        """
        if not hasattr(self, '_cached_grpc_options'):
            grpc_options = self._grpc_options.copy()
            default_options = {
                "keepalive_timeout_ms": 900000,  # Time in milliseconds to keep the connection alive.
                "max_receive_message_length": -1,  # Maximum size of received messages.
                "max_send_message_length": 300 * 1024 * 1024,  # Maximum size of sent messages (300 MB).
                "grpc_prepare_timeout": self.grpc_prepare_timeout,  # Timeout for prepare statement API call.
                "keepalive_time_ms": 30000,  # Time in milliseconds between keep-alive pings.
                "keepalive_permit_without_calls": 1,  # Allow keep-alives with no active RPCs.
                "http2.max_pings_without_data": 0,  # Unlimited pings without data.
                "http2.min_time_between_pings_ms": 15000,  # Minimum time between pings (15 seconds).
                "http2.min_ping_interval_without_data_ms": 15000,  # Minimum interval between pings without data (15 seconds).
            }
            if grpc_options:
                for key, value in grpc_options.items():
                    default_options[key] = value

            self._cached_grpc_options = [(f'grpc.{key}', value) for key, value in default_options.items()]

        return self._cached_grpc_options

    def _create_client(self):
        """
        Creates a gRPC client for the connection.

        This method initializes a gRPC channel based on whether a secure channel is required or not.
        It then creates a client stub for the QueryEngineService.

        If the secure channel is enabled, it uses `grpc.secure_channel` with SSL credentials.
        Otherwise, it uses `grpc.insecure_channel`.

        The gRPC options are retrieved from the `_get_grpc_options` property.

        Raises:
            grpc.RpcError: If there is an error in creating the gRPC channel or client stub.
        """
        if self._secure_channel:
            self._channel = grpc.secure_channel(
                target='{}:{}'.format(self._host, self._port),
                options=self._get_grpc_options,
                credentials=grpc.ssl_channel_credentials()
            )
        else:
            self._channel = grpc.insecure_channel(
                target='{}:{}'.format(self._host, self._port),
                options=self._get_grpc_options
            )
        self._client = e6x_engine_pb2_grpc.QueryEngineServiceStub(self._channel)

    def get_re_authenticate_session_id(self):
        """
        Re-authenticates the session by closing the current connection and creating a new client.

        This method is used to re-establish the session ID by closing the existing gRPC channel,
        creating a new client, and then retrieving a new session ID.

        Returns:
            str: The new session ID after re-authentication.

        Raises:
            Exception: If there is an error during the re-authentication process.
        """
        self.close()
        self._create_client()
        return self.get_session_id

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
            except _InactiveRpcError as e:
                if self._auto_resume:
                    if e.code() == grpc.StatusCode.UNAVAILABLE and 'status: 503' in e.details():
                        status = ClusterManager(
                            host=self._host,
                            port=self._port,
                            user=self.__username,
                            password=self.__password,
                            secure_channel=self._secure_channel,
                            cluster_uuid=self.cluster_uuid
                        ).resume()
                        if status:
                            authenticate_request = e6x_engine_pb2.AuthenticateRequest(
                                user=self.__username,
                                password=self.__password
                            )
                            authenticate_response = self._client.authenticate(
                                authenticate_request,
                                metadata=_get_grpc_header(cluster=self.cluster_uuid)
                            )
                            self._session_id = authenticate_response.sessionId
                        else:
                            raise e
                    else:
                        raise e
                else:
                    raise e
            except Exception as e:
                self._channel.close()
                raise e
        return self._session_id

    def _set_session_id(self, refreshed_session_id):
        if refreshed_session_id:
            self._session_id = refreshed_session_id

    def _set_session_id_from_response(self, response):
        self._set_session_id(response.sessionId)

    def __enter__(self):
        """
        Enters the runtime context related to this object.

        This method is called when the execution flow enters the context of the `with` statement.

        Returns:
            Connection: The current instance of the connection.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exits the runtime context related to this object.

        This method is called when the execution flow exits the context of the `with` statement.

        Args:
            exc_type (Type[BaseException]): The type of exception raised (if any).
            exc_val (BaseException): The exception instance raised (if any).
            exc_tb (Traceback): The traceback object of the exception (if any).
        """
        self.close()

    def close(self):
        """
        Closes the gRPC channel and resets the session ID.

        This method ensures that the gRPC channel is properly closed and the session ID is reset to None.
        """
        if self._channel is not None:
            self._channel.close()
            self._channel = None
        self._session_id = None

    def check_connection(self):
        """
        Checks if the gRPC channel is still open.

        Returns:
            bool: True if the gRPC channel is open, False otherwise.
        """
        return self._channel is not None

    def clear(self, query_id, engine_ip=None):
        """
        Clears the query results from the server.

        Args:
            query_id (str): The ID of the query to be cleared.
            engine_ip (str, optional): The IP address of the engine. Defaults to None.
        """
        clear_request = e6x_engine_pb2.ClearRequest(
            sessionId=self.get_session_id,
            queryId=query_id,
            engineIP=engine_ip
        )
        clear_response = self._client.clear(
            clear_request,
            metadata=_get_grpc_header(engine_ip=engine_ip, cluster=self.cluster_uuid)
        )
        self._set_session_id_from_response(clear_response)

    def reopen(self):
        """
        Reopens the gRPC channel by closing the current channel and creating a new client.

        This method is useful for re-establishing the connection if it was previously closed.
        """
        self._channel.close()
        self._create_client()

    def query_cancel(self, engine_ip, query_id):
        """
        Cancels the execution of a query on the server.

        Args:
            engine_ip (str): The IP address of the engine.
            query_id (str): The ID of the query to be canceled.
        """
        cancel_query_request = e6x_engine_pb2.CancelQueryRequest(
            engineIP=engine_ip,
            sessionId=self.get_session_id,
            queryId=query_id
        )
        cancel_query_response = self._client.cancelQuery(
            cancel_query_request,
            metadata=_get_grpc_header(engine_ip=engine_ip, cluster=self.cluster_uuid)
        )
        self._set_session_id_from_response(cancel_query_response)

    def dry_run(self, query):
        """
        Performs a dry run of the query to validate its syntax and structure.

        Args:
            query (str): The SQL query to be validated.

        Returns:
            str: The result of the dry run validation.
        """
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
        """
        Retrieves the list of tables from the specified catalog and database.

        Args:
            catalog (str): The catalog name.
            database (str): The database name.

        Returns:
            list: A list of table names.
        """
        get_table_request = e6x_engine_pb2.GetTablesV2Request(
            sessionId=self.get_session_id,
            schema=database,
            catalog=catalog
        )
        get_table_response = self._client.getTablesV2(
            get_table_request,
            metadata=_get_grpc_header(cluster=self.cluster_uuid)
        )
        self._set_session_id_from_response(get_table_response)
        return list(get_table_response.tables)

    def get_columns(self, catalog, database, table):
        """
        Retrieves the list of columns for the specified table in the given catalog and database.

        Args:
            catalog (str): The catalog name.
            database (str): The database name.
            table (str): The table name.

        Returns:
            list: A list of dictionaries containing column information.
        """
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
        self._set_session_id_from_response(get_columns_response)
        return [{'fieldName': row.fieldName, 'fieldType': row.fieldType} for row in get_columns_response.fieldInfo]

    def get_schema_names(self, catalog):
        """
        Retrieves the list of schema names from the specified catalog.

        Args:
            catalog (str): The catalog name.

        Returns:
            list: A list of schema names.
        """
        get_schema_request = e6x_engine_pb2.GetSchemaNamesV2Request(
            sessionId=self.get_session_id,
            catalog=catalog
        )
        get_schema_response = self._client.getSchemaNamesV2(
            get_schema_request,
            metadata=_get_grpc_header(cluster=self.cluster_uuid)
        )
        self._set_session_id_from_response(get_schema_response)
        return list(get_schema_response.schemas)

    def commit(self):
        """
        Commits the current transaction.

        Note:
            This method does nothing as transactions are not supported.
        """
        pass

    def cursor(self, catalog_name=None, db_name=None):
        """
        Creates a new cursor object for executing queries.

        Args:
            catalog_name (str, optional): The catalog name. Defaults to None.
            db_name (str, optional): The database name. Defaults to None.

        Returns:
            Cursor: A new cursor object.
        """
        return Cursor(self, database=db_name, catalog_name=catalog_name)

    def rollback(self):
        """
        Rolls back the current transaction.

        Raises:
            Exception: Always raises an exception as transactions are not supported.
        """
        raise Exception("e6data does not support transactions")  # pragma: no cover

    @property
    def client(self):
        """
        Returns the gRPC client stub for interacting with the server.

        Returns:
            e6x_engine_pb2_grpc.QueryEngineServiceStub: The gRPC client stub.
        """
        return self._client


class Cursor(DBAPICursor):
    """
    These objects represent a database cursor, which is used to manage the context of a fetch
    operation.
    Cursors are not isolated, i.e., any changes done to the database by a cursor are immediately
    visible by other cursors or connections.
    """

    def __init__(self, connection: Connection, array_size=1000, database=None, catalog_name=None):
        """
        Initialize a new Cursor object.

        Args:
            connection (Connection): The connection object to the database.
            array_size (int, optional): The number of rows to fetch at a time. Defaults to 1000.
            database (str, optional): The database name. Defaults to None.
            catalog_name (str, optional): The catalog name. Defaults to None.
        """
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
        """
        Get the gRPC metadata for the current query.

        Returns:
            list: A list of tuples containing gRPC metadata.
        """
        return _get_grpc_header(engine_ip=self._engine_ip, cluster=self.connection.cluster_uuid)

    @property
    def arraysize(self):
        """
        Get the array size for fetching rows.

        Returns:
            int: The number of rows to fetch at a time.
        """
        return self._arraysize

    @arraysize.setter
    def arraysize(self, value):
        """
        Set the array size for fetching rows.

        Args:
            value (int): The number of rows to fetch at a time.
        """
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
        """
        Enter the runtime context related to this object.

        Returns:
            Cursor: The current instance of the cursor.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exit the runtime context related to this object.

        Args:
            exc_type (Type[BaseException]): The type of exception raised (if any).
            exc_val (BaseException): The exception instance raised (if any).
            exc_tb (Traceback): The traceback object of the exception (if any).
        """
        self.close()

    def close(self):
        """
         Close the operation handle and reset the cursor state.
         """
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
        """
        Retrieve the list of tables from the current database.

        Returns:
            list: A list of table names.
        """
        schema = self.connection.database
        return self.connection.get_tables(catalog=self._catalog_name, database=schema)

    def get_columns(self, table):
        """
        Retrieve the list of columns for the specified table.

        Args:
            table (str): The table name.

        Returns:
            list: A list of dictionaries containing column information.
        """
        schema = self.connection.database
        return self.connection.get_columns(catalog=self._catalog_name, database=schema, table=table)

    def get_schema_names(self):
        """
         Retrieve the list of schema names from the current catalog.

         Returns:
             list: A list of schema names.
         """
        return self.connection.get_schema_names(catalog=self._catalog_name)

    def clear(self, query_id=None):
        """
        Clear the query results from the server.

        Args:
            query_id (str, optional): The ID of the query to be cleared. Defaults to None.
        """
        if not query_id:
            query_id = self._query_id
        clear_request = e6x_engine_pb2.ClearOrCancelQueryRequest(
            sessionId=self.connection.get_session_id,
            queryId=query_id,
            engineIP=self._engine_ip
        )
        clear_response = self.connection.client.clearOrCancelQuery(clear_request, metadata=self.metadata)
        self.connection._set_session_id_from_response(clear_response)
        return clear_response

    def cancel(self, query_id):
        """
        Cancel the execution of a query on the server.

        Args:
            query_id (str): The ID of the query to be canceled.
        """
        self.connection.query_cancel(engine_ip=self._engine_ip, query_id=query_id)

    def status(self, query_id):
        """
        Get the status of the specified query.

        Args:
            query_id (str): The ID of the query.

        Returns:
            StatusResponse: The status response of the query.
        """
        status_request = e6x_engine_pb2.StatusRequest(
            sessionId=self.connection.get_session_id,
            queryId=query_id,
            engineIP=self._engine_ip
        )
        status_response = self.connection.client.status(status_request, metadata=self.metadata)
        self.connection._set_session_id_from_response(status_response)
        return status_response

    @re_auth
    def execute(self, operation, parameters=None, **kwargs):
        """
        Prepare and execute a database operation (query or command).

        Args:
            operation (str): The SQL query or command to execute.
            parameters (dict, optional): The parameters to bind to the query. Defaults to None.

        Returns:
            str: The query ID of the executed query.
        """
        # Semicolon is now not supported. So removing it from query end.
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

            self.connection._set_session_id_from_response(prepare_statement_response)
            self._query_id = prepare_statement_response.queryId
            self._engine_ip = prepare_statement_response.engineIP

            execute_statement_request = e6x_engine_pb2.ExecuteStatementRequest(
                engineIP=self._engine_ip,
                sessionId=self.connection.get_session_id,
                queryId=self._query_id,
            )
            execute_statement_response = client.executeStatement(
                execute_statement_request,
                metadata=self.metadata
            )

            self.connection._set_session_id_from_response(execute_statement_response)
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
                timeout=self.connection.grpc_prepare_timeout
            )

            self.connection._set_session_id_from_response(prepare_statement_response)
            self._query_id = prepare_statement_response.queryId
            self._engine_ip = prepare_statement_response.engineIP

            execute_statement_request = e6x_engine_pb2.ExecuteStatementV2Request(
                engineIP=self._engine_ip,
                sessionId=self.connection.get_session_id,
                queryId=self._query_id
            )
            execute_statement_response = client.executeStatementV2(
                execute_statement_request,
                metadata=self.metadata
            )

            self.connection._set_session_id_from_response(execute_statement_response)
        self.update_mete_data()
        return self._query_id

    @property
    def rowcount(self):
        """
        Get the number of rows affected by the last execute operation.

        Returns:
            int: The number of rows affected.
        """
        self.update_mete_data()
        return self._rowcount

    def update_mete_data(self):
        """
        Update the metadata for the current query.
        """
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

        self.connection._set_session_id_from_response(get_result_metadata_response)
        self._rowcount, self._query_columns_description = get_query_columns_info(buffer)
        self._is_metadata_updated = True

    def _fetch_more(self):
        """
        Fetch more rows from the server.

        Returns:
            list: A list of rows fetched from the server.
        """
        batch_size = self._arraysize
        self._data = list()
        for i in range(batch_size):
            rows = self.fetch_batch()
            if rows is None:
                return
            self._data = self._data + rows
        return self._data

    def _fetch_all(self):
        """
        Fetch all rows from the server.

        Returns:
            list: A list of all rows fetched from the server.
        """
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
        """
        Fetch all rows from the server in a buffered manner.

        Args:
            query_id (str, optional): The ID of the query. Defaults to None.

        Yields:
            list: A list of rows fetched from the server.
        """
        if query_id:
            self._query_id = query_id
        while True:
            rows = self.fetch_batch()
            if not rows:
                return
            yield rows

    def fetch_batch(self):
        """
        Fetch a batch of rows from the server.

        Returns:
            list: A list of rows fetched from the server.
        """
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

        self.connection._set_session_id_from_response(get_next_result_batch_response)

        buffer = get_next_result_batch_response.resultBatch
        if not self._is_metadata_updated:
            self.update_mete_data()
        if not buffer or len(buffer) == 0:
            return None
        # one batch retrieves the predefined set of rows
        return read_rows_from_chunk(self._query_columns_description, buffer)

    def fetchall(self):
        """
         Fetch all rows from the server.

         Returns:
             list: A list of all rows fetched from the server.
         """
        return self._fetch_all()

    def fetchmany(self, size: int = None):
        """
        Fetch a specified number of rows from the server.

        Args:
            size (int, optional): The number of rows to fetch. Defaults to None.

        Returns:
            list: A list of rows fetched from the server.
        """
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
        """
        Fetch a single row from the server.

        Returns:
            list: A single row fetched from the server.
        """
        rows = self.fetchmany(1)
        if rows is None or len(rows) == 0:
            return None
        return rows

    def explain(self):
        """
        Get the execution plan for the current query.

        Returns:
            str: The execution plan of the query.
        """
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
        """
        Get the execution plan for the current query.

        Returns:
            dict: The execution plan of the query.
        """
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