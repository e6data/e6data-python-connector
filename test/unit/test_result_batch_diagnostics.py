"""Public diagnostics contracts using real gRPC failures and logging handlers.

The server fixture is the unmodified generated base service, not a query engine.
Unissued handles and serialized rows only exercise local cursor state.
"""

import asyncio
import logging
import subprocess
import sys

import grpc
import pytest

from e6data_python_connector import Connection
from e6data_python_connector import e6data_grpc
from e6data_python_connector.async_connection import AsyncConnection, QueryRoute
from e6data_python_connector.async_cursor import AsyncCursor, _log_result_batch
from e6data_python_connector.exceptions import IncompleteResultError
from e6data_python_connector.server import e6x_engine_pb2 as pb, e6x_engine_pb2_grpc as bindings
from test.unit.test_protobuf_wire_contract import generated_server


@pytest.mark.parametrize('async_api', [False, True])
@pytest.mark.parametrize('handler_level', [None, logging.INFO, logging.DEBUG])
def test_debug_true_shows_metrics_without_replacing_application_handlers(async_api, handler_level):
    # A separate Python process gives each case normal, untouched logging defaults.
    script = '''
import io
import logging
from e6data_python_connector import Connection
from e6data_python_connector.async_connection import AsyncConnection
from e6data_python_connector.async_cursor import _log_result_batch
from e6data_python_connector.e6data_grpc import _log_result_batch_fetch
from e6data_python_connector.server import e6x_engine_pb2 as pb, e6x_engine_pb2_grpc as bindings
stream = io.StringIO()
root = logging.getLogger()
handler = logging.StreamHandler(stream)
handler.setLevel(HANDLER_LEVEL or logging.NOTSET)
if HANDLER_LEVEL is not None:
    root.addHandler(handler)
root_level = root.level
before = tuple(root.handlers)
options = dict(host='127.0.0.1', port=1, username='local-user',
               password='local-input', auto_resume=False, require_fastbinary=False)
cls = AsyncConnection if ASYNC else Connection
conn = cls(debug=True, **options)
if ASYNC:
    _log_result_batch('v2', .25, 'ok', pb.GetNextResultBatchV2Response(resultBatches=[b'abc']), .125)
else:
    _log_result_batch_fetch('v2', .25, 1, 5, .125)
assert tuple(root.handlers) == before
assert root.level == root_level
assert handler.level == (HANDLER_LEVEL or logging.NOTSET)
assert not handler._closed
assert 'local-input' not in stream.getvalue()
print(stream.getvalue())
if not ASYNC:
    conn.close()
'''.replace('HANDLER_LEVEL', repr(handler_level)).replace('ASYNC', repr(async_api))
    completed = subprocess.run([sys.executable, '-c', script], text=True, capture_output=True)
    assert completed.returncode == 0, completed.stderr
    output = completed.stdout + completed.stderr
    for value in ('protocol=v2', 'rpc_seconds=0.250000', 'decode_seconds=0.125000',
                  'chunk_count=1', 'serialized_bytes=5', 'status=ok'):
        assert value in output
    assert 'local-input' not in output


@pytest.mark.parametrize('async_api', [False, True])
def test_default_logging_is_quiet_and_explicit_logging_still_works(async_api):
    script = '''
import logging
from e6data_python_connector import Connection
from e6data_python_connector.async_connection import AsyncConnection
from e6data_python_connector.async_cursor import _log_result_batch
from e6data_python_connector.e6data_grpc import _log_result_batch_fetch
options = dict(host='127.0.0.1', port=1, username='local-user',
               password='local-input', auto_resume=False, require_fastbinary=False)
conn = (AsyncConnection if ASYNC else Connection)(**options)
emit = (lambda: _log_result_batch('v1', .25, 'error')) if ASYNC else (lambda: _log_result_batch_fetch('v1', .25, status='error'))
emit()
logging.basicConfig(level=logging.DEBUG, format='%(message)s')
emit()
if not ASYNC:
    conn.close()
'''.replace('ASYNC', repr(async_api))
    completed = subprocess.run([sys.executable, '-c', script], text=True, capture_output=True)
    assert completed.returncode == 0, completed.stderr
    output = completed.stdout + completed.stderr
    assert output.count('protocol=v1') == 1
    assert 'rpc_seconds=0.250000' in output


@pytest.mark.parametrize('async_api', [False, True])
def test_metrics_keep_structured_attributes_and_show_values_in_message(caplog, async_api):
    with caplog.at_level(logging.DEBUG, logger='e6data_python_connector'):
        if async_api:
            _log_result_batch('v2', .25, 'ok', pb.GetNextResultBatchV2Response(resultBatches=[b'abc']), .125)
        else:
            e6data_grpc._log_result_batch_fetch('v2', .25, 1, 5, .125)
    record = caplog.records[-1]
    expected = dict(protocol='v2', rpc_seconds=.25, chunk_count=1,
                    serialized_bytes=5, decode_seconds=.125, status='ok')
    for key, value in expected.items():
        assert getattr(record, 'result_batch_' + key) == value
        assert key + '=' in record.getMessage()


def sync_cursor(target, *, oauth=False):
    host, port = target.rsplit(':', 1)
    options = dict(host=host, port=int(port), auto_resume=False, require_fastbinary=False,
                   grpc_options={'grpc_prepare_timeout': .25})
    if oauth:
        options.update(access_token='local-input', secure=True, enable_result_batch_v2=False)
    else:
        options.update(username='local-user', password='local-input', enable_result_batch_v2=True)
    conn = Connection(**options)
    cursor = conn.cursor()
    cursor._query_id = 'unissued-local-query'
    cursor._engine_ip = '127.0.0.1'
    cursor._is_metadata_updated = True
    cursor._query_columns_description = ['value']
    cursor._result_session_id = 'unissued-local-session'
    return conn, cursor


SYNC_FETCHES = ['fetch_batch', 'fetchone', 'fetchmany', 'fetchall', 'fetchall_buffer']


@pytest.mark.parametrize('name', SYNC_FETCHES)
@pytest.mark.parametrize('oauth', [False, True])
def test_sync_fetch_preserves_rpc_error_and_blocks_later_fetches(generated_server, name, oauth, caplog):
    conn, cursor = sync_cursor(generated_server[0], oauth=oauth)
    try:
        with caplog.at_level(logging.DEBUG, logger=e6data_grpc.__name__):
            with pytest.raises(grpc.RpcError) as caught:
                value = cursor.fetchmany(2) if name == 'fetchmany' else getattr(cursor, name)()
                if name == 'fetchall_buffer':
                    next(value)
            assert caught.value.code() == (grpc.StatusCode.UNAVAILABLE if oauth else grpc.StatusCode.UNIMPLEMENTED)
            assert caught.value.details()
            assert caught.value.trailing_metadata() == ()
            if not oauth:
                assert caught.value.details() == 'Method not implemented!'
                assert cursor._result_protocol == 'v1'
            attempts = len([r for r in caplog.records if hasattr(r, 'result_batch_status')])
            with pytest.raises(IncompleteResultError):
                cursor.fetchone()
            assert len([r for r in caplog.records if hasattr(r, 'result_batch_status')]) == attempts
            assert cursor._data is None
            assert cursor._result_batches.pop() is None
            assert cursor.query_id == 'unissued-local-query'
    finally:
        conn.close()


@pytest.mark.parametrize('name', ['fetchmany', 'fetchall'])
@pytest.mark.parametrize('oauth', [False, True])
def test_sync_failed_aggregate_discards_buffered_rows(generated_server, name, oauth):
    conn, cursor = sync_cursor(generated_server[0], oauth=oauth)
    cursor._data = [[123]]
    try:
        with pytest.raises(grpc.RpcError):
            getattr(cursor, name)(2) if name == 'fetchmany' else cursor.fetchall()
        assert cursor._data is None
        assert cursor._result_batches.pop() is None
        with pytest.raises(IncompleteResultError):
            cursor.fetch_batch()
    finally:
        conn.close()


ASYNC_FETCHES = ['fetch_batch', 'fetchone', 'fetchmany', 'fetchall', 'fetchall_buffer', '__anext__']


@pytest.mark.parametrize('name', ASYNC_FETCHES)
@pytest.mark.parametrize('v2', [False, True])
def test_async_fetch_preserves_rpc_error_and_blocks_later_fetches(generated_server, name, v2, caplog):
    async def run():
        host, port = generated_server[0].rsplit(':', 1)
        async with AsyncConnection(host=host, port=int(port), username='local-user', password='local-input',
                                   auto_resume=False, require_fastbinary=False, enable_result_batch_v2=v2,
                                   operation_timeout=.5, cleanup_timeout=.05) as conn:
            conn._session_id = 'unissued-local-session'
            cursor = AsyncCursor(conn)
            cursor._state = 'ACTIVE'
            cursor._columns = []
            cursor._route = conn._register_route(QueryRoute(conn.target, 'unissued-local-query', '', conn.strategy))
            with pytest.raises(grpc.aio.AioRpcError) as caught:
                if name == 'fetchall_buffer':
                    await anext(cursor.fetchall_buffer())
                else:
                    await getattr(cursor, name)()
            assert caught.value.code() == grpc.StatusCode.UNIMPLEMENTED
            assert caught.value.details() == 'Method not implemented!'
            assert tuple(caught.value.trailing_metadata()) == ()
            assert cursor._result_protocol == 'v1'
            attempts = len([r for r in caplog.records if hasattr(r, 'result_batch_status')])
            with pytest.raises(IncompleteResultError):
                await cursor.fetchone()
            assert len([r for r in caplog.records if hasattr(r, 'result_batch_status')]) == attempts
            assert cursor._state == 'RESULT_FAILED'
            assert not cursor._rows
            assert cursor._result_batches.pop() is None
    with caplog.at_level(logging.DEBUG, logger='e6data_python_connector.async_cursor'):
        asyncio.run(run())


@pytest.mark.parametrize('name', ['fetchmany', 'fetchall'])
@pytest.mark.parametrize('v2', [False, True])
def test_async_failed_aggregate_discards_buffered_rows(generated_server, name, v2):
    async def run():
        host, port = generated_server[0].rsplit(':', 1)
        async with AsyncConnection(host=host, port=int(port), username='local-user', password='local-input',
                                   auto_resume=False, require_fastbinary=False, enable_result_batch_v2=v2,
                                   operation_timeout=.5, cleanup_timeout=.05) as conn:
            conn._session_id = 'unissued-local-session'
            cursor = AsyncCursor(conn)
            cursor._state = 'ACTIVE'
            cursor._columns = []
            cursor._route = conn._register_route(QueryRoute(conn.target, 'unissued-local-query', '', conn.strategy))
            cursor._rows.append([123])
            with pytest.raises(grpc.aio.AioRpcError):
                await cursor.fetchmany(2) if name == 'fetchmany' else await cursor.fetchall()
            assert not cursor._rows
            assert cursor._result_batches.pop() is None
            with pytest.raises(IncompleteResultError):
                await cursor.fetch_batch()
    asyncio.run(run())


class ObserveSyncErrors(grpc.UnaryUnaryClientInterceptor):
    """Observe errors from the real transport without replacing its response."""

    def __init__(self):
        self.errors = []

    def intercept_unary_unary(self, continuation, call_details, request):
        call = continuation(call_details, request)
        error = call.exception()
        if error is not None:
            self.errors.append(error)
        return call


def test_sync_fetch_returns_the_same_transport_exception(generated_server):
    conn, cursor = sync_cursor(generated_server[0])
    observer = ObserveSyncErrors()
    channel = grpc.intercept_channel(generated_server[1], observer)
    conn._client = bindings.QueryEngineServiceStub(channel)
    try:
        with pytest.raises(grpc.RpcError) as caught:
            cursor.fetch_batch()
        assert len(observer.errors) == 2  # V2 UNIMPLEMENTED, then V1 UNIMPLEMENTED.
        assert caught.value is observer.errors[-1]
        with pytest.raises(IncompleteResultError):
            cursor.fetch_batch()
        assert len(observer.errors) == 2
    finally:
        conn.close()


class ObserveAsyncErrors(grpc.aio.UnaryUnaryClientInterceptor):
    """Observe errors from the real async transport without replacing them."""

    def __init__(self):
        self.errors = []

    async def intercept_unary_unary(self, continuation, call_details, request):
        call = await continuation(call_details, request)
        try:
            return await call
        except grpc.RpcError as error:
            self.errors.append(error)
            raise


@pytest.mark.parametrize('v2', [False, True])
def test_async_fetch_returns_the_same_transport_exception(generated_server, v2):
    async def run():
        host, port = generated_server[0].rsplit(':', 1)
        observer = ObserveAsyncErrors()
        async with grpc.aio.insecure_channel(generated_server[0], interceptors=[observer]) as channel:
            async with AsyncConnection(host=host, port=int(port), username='local-user', password='local-input',
                                       auto_resume=False, require_fastbinary=False, enable_result_batch_v2=v2,
                                       operation_timeout=.5, cleanup_timeout=.05) as conn:
                conn._client = bindings.QueryEngineServiceStub(channel)
                conn._session_id = 'unissued-local-session'
                cursor = AsyncCursor(conn)
                cursor._state = 'ACTIVE'
                cursor._columns = []
                cursor._route = conn._register_route(QueryRoute(conn.target, 'unissued-local-query', '', conn.strategy))
                with pytest.raises(grpc.aio.AioRpcError) as caught:
                    await cursor.fetchall()
                assert len(observer.errors) == (2 if v2 else 1)
                assert caught.value is observer.errors[-1]
                with pytest.raises(IncompleteResultError):
                    await cursor.fetch_batch()
                assert len(observer.errors) == (2 if v2 else 1)
    asyncio.run(run())
