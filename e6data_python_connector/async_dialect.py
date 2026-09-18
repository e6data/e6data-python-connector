"""SQLAlchemy 2.0 adaptation of the native asyncio connector.

Uses SQLAlchemy's AdaptedConnection/await_only greenlet boundary. SQLAlchemy
owns pooling. Credentials belong in connect_args or an async_creator.
"""
from collections import deque

import sqlalchemy
from sqlalchemy import types
from sqlalchemy.engine import AdaptedConnection, default
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlalchemy.util.concurrency import await_only

from . import exceptions
from .dialect import E6dataDialect, _type_map

if sqlalchemy.__version__.split('.')[:2] != ['2', '0']:
    raise ImportError('The async dialect requires SQLAlchemy >=2.0,<2.1.')


class AsyncAdaptE6dataCursor:
    """Buffer before returning to sync consumers; stream only inside greenlets."""
    def __init__(self, connection, server_side=False):
        self.connection = connection
        self.server_side = server_side
        self._cursor = connection.driver_connection.cursor()
        self._rows = deque()
        self._description = None
        self._rowcount = -1
        self._closed = False
        self._native_closed = False

    @property
    def description(self):
        return self._description

    @property
    def rowcount(self):
        return self._rowcount

    @property
    def arraysize(self):
        return self._cursor.arraysize

    @arraysize.setter
    def arraysize(self, value):
        self._cursor.arraysize = value

    async def _execute(self, operation, parameters, many=False):
        if self._closed:
            raise exceptions.ProgrammingError('Cursor is closed.')
        if self._native_closed:
            arraysize = self.arraysize
            self._cursor = self.connection.driver_connection.cursor()
            self._cursor.arraysize = arraysize
            self._native_closed = False
        if self._cursor.query_id is not None:
            await self._cursor.clear()
        self._rows.clear()
        method = self._cursor.executemany if many else self._cursor.execute
        succeeded = False
        try:
            result = await method(operation, parameters)
            self._description = self._cursor.description
            self._rowcount = self._cursor.rowcount
            if self._description and not self.server_side:
                self._rows.extend(await self._cursor.fetchall())
            succeeded = True
            return result
        finally:
            # Buffered Result.close may run outside the greenlet. Release its
            # native query here, while network I/O can still be awaited.
            if not self.server_side:
                await self._cursor.close()
                self._native_closed = True
                if self._cursor.cleanup_error is not None:
                    self.connection._cleanup_error = self._cursor.cleanup_error
                    if succeeded:
                        raise self._cursor.cleanup_error

    async def _async_soft_close(self):
        # SQLAlchemy awaits this before exposing a buffered Result. _execute
        # already closed the native cursor; retain local rows and metadata.
        return None

    def execute(self, operation, parameters=None):
        return await_only(self._execute(operation, parameters))

    def executemany(self, operation, parameters):
        return await_only(self._execute(operation, parameters, many=True))

    def fetchone(self):
        if self.server_side:
            rows = await_only(self._cursor.fetchone())
            return rows[0] if rows else None
        return self._rows.popleft() if self._rows else None

    def fetchmany(self, size=None):
        size = self.arraysize if size is None else size
        if self.server_side:
            return await_only(self._cursor.fetchmany(size))
        return [self._rows.popleft() for _ in range(min(size, len(self._rows)))]

    def fetchall(self):
        if self.server_side:
            return await_only(self._cursor.fetchall())
        rows = list(self._rows)
        self._rows.clear()
        return rows

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                return
            yield row

    def close(self):
        self._rows.clear()
        if not self._native_closed:
            await_only(self._cursor.close())
            self._native_closed = True
        self._closed = True
        if self._cursor.cleanup_error is not None:
            self.connection._cleanup_error = self._cursor.cleanup_error
            raise self._cursor.cleanup_error

    def setinputsizes(self, *sizes):
        return None

    def setoutputsize(self, size, column=None):
        return None


class AsyncAdaptE6dataConnection(AdaptedConnection):
    def __init__(self, connection):
        self._connection = connection
        self._cleanup_error = None

    def _unusable(self):
        native = self._connection
        return (self._cleanup_error is not None or native.cleanup_error is not None
                or bool(native._ambiguous_submissions) or not native.check_connection())

    def cursor(self, server_side=False):
        return AsyncAdaptE6dataCursor(self, server_side)

    def close(self):
        await_only(self._connection.close())

    def commit(self):
        await_only(self._connection.commit())

    def rollback(self):
        # No server transaction exists. Pool reset must still reject unresolved work.
        if self._unusable() or self._connection._routes:
            await_only(self._connection.close())
            raise exceptions.OperationalError('Native connection has unresolved query cleanup.') from self._cleanup_error
        return None

    def ping(self):
        # An authenticated metadata read, rather than a local channel flag.
        await_only(self._connection.get_schema_names(self._connection.catalog))
        return True


class AsyncE6dataDBAPI:
    paramstyle = 'pyformat'
    apilevel = '2.0'
    threadsafety = 1
    # Existing connector errors do not share a common DBAPI base class.
    Error = (exceptions.OperationalError, exceptions.ProgrammingError,
             exceptions.NotSupportedError, exceptions.DataError,
             exceptions.OAuthError, exceptions.OAuthNotSupportedError)
    OperationalError = exceptions.OperationalError
    ProgrammingError = exceptions.ProgrammingError
    NotSupportedError = exceptions.NotSupportedError
    DataError = exceptions.DataError

    def connect(self, *args, **kwargs):
        from .aio import connect
        creator = kwargs.pop('async_creator_fn', connect)
        connection = await_only(creator(*args, **kwargs))
        if connection._lease_guard is not None:
            raise exceptions.ProgrammingError('SQLAlchemy must own connection pooling.')
        return AsyncAdaptE6dataConnection(connection)


class E6dataAsyncExecutionContext(default.DefaultExecutionContext):
    def create_server_side_cursor(self):
        return self._dbapi_connection.cursor(server_side=True)


class E6dataAsyncDialect(E6dataDialect):
    driver = 'asyncio'
    name = 'e6data'
    is_async = True
    supports_statement_cache = False
    supports_server_side_cursors = True
    execution_ctx_cls = E6dataAsyncExecutionContext

    @classmethod
    def import_dbapi(cls):
        return AsyncE6dataDBAPI()

    def get_driver_connection(self, connection):
        return connection.driver_connection

    @classmethod
    def get_pool_class(cls, url):
        return AsyncAdaptedQueuePool

    def create_connect_args(self, url):
        if url.username is not None or url.password is not None:
            raise ValueError('Pass credentials through connect_args or async_creator.')
        aliases = {'schema': 'database', 'cluster-name': 'cluster_name',
                   'cluster-uuid': 'cluster_name', 'auto-resume': 'auto_resume'}
        strings = {'catalog', 'database', 'cluster_name', 'ssl_cert'}
        booleans = {'secure', 'auto_resume', 'debug', 'require_fastbinary',
                    'enable_result_batch_v2'}
        floats = {'operation_timeout', 'cleanup_timeout', 'oauth_timeout', 'auto_resume_timeout'}
        options = {}
        if url.host is not None:
            options['host'] = url.host
        if url.port is not None:
            options['port'] = url.port
        if url.database:
            options['database'] = url.database
        grpc_options = {}
        for key, value in url.query.items():
            name = aliases.get(key, key)
            if name in strings:
                options[name] = value
            elif name in booleans:
                if value not in ('true', 'false'):
                    raise ValueError('Boolean URL options require true or false.')
                options[name] = value == 'true'
            elif name in floats:
                options[name] = float(value)
            elif name == 'max_receive_message_bytes':
                options[name] = int(value)
            elif key.startswith('grpc.'):
                grpc_options[key] = int(value) if value.lstrip('-').isdigit() else value
            else:
                raise ValueError('Unsupported URL option; use connect_args for connector configuration.')
        if grpc_options:
            options['grpc_options'] = grpc_options
        return [], options

    @staticmethod
    def _native(connection):
        return connection.connection.dbapi_connection.driver_connection

    def _get_default_schema_name(self, connection):
        return self._native(connection).database

    def get_schema_names(self, connection, **kw):
        native = self._native(connection)
        return await_only(native.get_schema_names(native.catalog))

    def get_table_names(self, connection, schema=None, **kw):
        native = self._native(connection)
        return await_only(native.get_tables(native.catalog, schema or native.database))

    def _get_table_columns(self, connection, schema, table):
        native = self._native(connection)
        columns = await_only(native.get_columns(native.catalog, schema or native.database, table))
        return [{'col_name': col['fieldName'], 'data_type': col['fieldType']} for col in columns]

    def get_columns(self, connection, table_name, schema=None, **kw):
        columns = self._get_table_columns(connection, schema, table_name)
        return [{'name': col['col_name'],
                 'type': _type_map.get(str(col['data_type']).lower().split('(', 1)[0].split('<', 1)[0].strip(), types.String)(),
                 'nullable': True, 'default': None} for col in columns]

    def do_ping(self, dbapi_connection):
        return dbapi_connection.ping()

    def do_rollback(self, dbapi_connection):
        return dbapi_connection.rollback()

    def is_disconnect(self, error, connection, cursor):
        # Preserve the original DBAPI exception/cause; signal pool invalidation
        # from native ownership state rather than parsing server error strings.
        return connection is not None and connection._unusable()
