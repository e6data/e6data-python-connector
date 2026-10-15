"""Deterministic admitted-work faults, using labeled local RPC test doubles."""
import asyncio
import time
import traceback
from types import SimpleNamespace
from unittest.mock import patch

import grpc
import pytest

from e6data_python_connector import cluster_manager
from e6data_python_connector.async_connection import AsyncConnection
from e6data_python_connector.exceptions import AmbiguousSubmissionError, ProgrammingError
from e6data_python_connector.oauth_cache import TokenState
from e6data_python_connector.cluster_server import cluster_pb2 as cluster_pb
from e6data_python_connector.server import e6x_engine_pb2 as pb
from test.test_oauth_auto_resume import (ScriptedRPC, clean_strategies, make_connection,
                                       query_client, rpc_error)


def active_cluster(events):
    def status(request, **kwargs):
        events.append('status')
        return cluster_pb.ClusterStatusResponse(status='active')
    return SimpleNamespace(status=status)


def test_sync_readiness_precedes_first_query_dispatch():
    events = []
    connection = make_connection(auto_resume=True)
    connection._client = query_client()
    original = connection._client.prepareStatement

    def prepare(request, **kwargs):
        events.append('prepare')
        return original(request, **kwargs)

    connection._client.prepareStatement = prepare
    with patch.object(cluster_manager.ClusterManager, '_get_connection',
                      new_callable=lambda: property(lambda self: active_cluster(events))):
        assert connection.cursor().execute('SELECT 1') == 'new-query'
    assert events == ['status', 'prepare']


@pytest.mark.parametrize('failure', [
    (grpc.StatusCode.UNAUTHENTICATED, 'expired'),
    (grpc.StatusCode.UNKNOWN, 'status: 456'),
    (grpc.StatusCode.UNAVAILABLE, 'status: 503, cluster is suspended'),
])
def test_sync_admitted_prepare_failure_never_resubmits_or_reuses_cursor(failure):
    events = []
    connection = make_connection(auto_resume=True, access_token=None,
                                 client_id='dispatch-client', client_secret='test-secret',
                                 token_url='https://issuer.invalid/token')
    provider = connection._token_provider
    provider._access_token = 'test-token'
    provider._expires_at = time.monotonic() + 300
    admitted = []
    connection._client = query_client()

    def prepare(request, **kwargs):
        admitted.append(request.queryString)
        if len(admitted) == 1:
            raise rpc_error(*failure)
        return pb.PrepareStatementResponse(queryId='duplicated-query', engineIP='planner')

    connection._client.prepareStatement = prepare
    cursor = connection.cursor()
    with patch.object(provider, '_fetch_token', return_value={
            'access_token': 'new-test-token', 'token_type': 'Bearer', 'expires_in': 300}), \
            patch.object(cluster_manager.ClusterManager, '_get_connection',
                         new_callable=lambda: property(lambda self: active_cluster(events))):
        with pytest.raises(AmbiguousSubmissionError):
            cursor.execute('INSERT INTO test_table VALUES (1)')
        with pytest.raises(ProgrammingError):
            cursor.execute('INSERT INTO test_table VALUES (1)')
    assert admitted == ['INSERT INTO test_table VALUES (1)']
    assert events == ['status']
    assert not connection._client.executeStatement.calls


class AsyncRPC:
    """Local test double recording dispatch before an injected server response."""
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, request, **kwargs):
        self.calls.append((request, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


@pytest.mark.parametrize('method', ['prepareStatement', 'prepareStatementV2',
                                   'getResultMetadata', 'status', 'getTablesV2',
                                   'getColumnsV2', 'getSchemaNamesV2', 'dryRun', 'dryRunV2'])
def test_async_query_rpc_does_not_retry_managed_auth_rejection(method):
    async def run():
        connection = AsyncConnection('fixture.invalid', 443, secure=True, auto_resume=False,
                                     client_id='async-dispatch-' + method,
                                     client_secret='test-secret',
                                     token_url='https://issuer.invalid/token')
        await connection.open()
        provider = connection._token_provider
        provider._access_token = 'test-token'
        provider._expires_at = time.monotonic() + 300
        rpc = AsyncRPC(rpc_error(grpc.StatusCode.UNAUTHENTICATED, 'expired'), SimpleNamespace())
        connection._client = SimpleNamespace(**{method: rpc})

        async def acquire(deadline):
            return {'access_token': 'replacement-token', 'token_type': 'Bearer', 'expires_in': 300}

        try:
            with patch.object(provider, '_fetch_token', side_effect=acquire):
                with pytest.raises(grpc.RpcError):
                    await connection._rpc(method, pb.StatusRequest(),
                                          deadline=connection._deadline(), safe_retry=True)
            assert len(rpc.calls) == 1
            assert provider._access_token is None
        finally:
            await connection.close()
    asyncio.run(run())


def test_async_readiness_precedes_prepare_and_rejection_retains_uncertainty():
    async def run():
        events = []
        connection = AsyncConnection('fixture.invalid', 443, access_token='test-token',
                                     secure=True, auto_resume=True)
        await connection.open()
        rpc = AsyncRPC(rpc_error(grpc.StatusCode.UNAUTHENTICATED, 'admitted then rejected'))
        connection._client = SimpleNamespace(prepareStatement=rpc)

        async def preflight(deadline):
            events.append('ready')
            assert not rpc.calls

        cursor = connection.cursor()
        try:
            with patch.object(connection, '_resume_cluster', side_effect=preflight):
                with pytest.raises(AmbiguousSubmissionError):
                    await cursor.execute('INSERT INTO test_table VALUES (1)')
                with pytest.raises(ProgrammingError):
                    await cursor.execute('INSERT INTO test_table VALUES (1)')
            assert events == ['ready']
            assert len(rpc.calls) == 1
            assert cursor in connection._ambiguous_submissions
        finally:
            await connection.close()
    asyncio.run(run())


def test_sync_execute_failure_keeps_unknown_submission_after_cleanup():
    connection = make_connection(access_token='test-token', auto_resume=False)
    connection._channel = None
    client = query_client()
    client.executeStatement = ScriptedRPC(rpc_error(grpc.StatusCode.UNAUTHENTICATED, 'accepted then rejected'))
    connection._client = client
    cursor = connection.cursor()
    try:
        with pytest.raises(AmbiguousSubmissionError):
            cursor.execute('INSERT INTO test_table VALUES (1)')
        assert cursor.query_id
        cursor.close()
        assert not connection._result_cleanup_safe
        with pytest.raises(ProgrammingError):
            cursor.execute('INSERT INTO test_table VALUES (1)')
        assert len(client.prepareStatement.calls) == 1
        assert len(client.executeStatement.calls) == 1
    finally:
        connection.close()


def test_sync_unknown_prepare_is_retained_after_close():
    connection = make_connection(access_token='test-token', auto_resume=False)
    connection._channel = None
    client = query_client()
    client.prepareStatement = ScriptedRPC(rpc_error(grpc.StatusCode.UNAVAILABLE, 'response lost'))
    connection._client = client
    cursor = connection.cursor()
    try:
        with pytest.raises(AmbiguousSubmissionError):
            cursor.execute('INSERT INTO test_table VALUES (1)')
        cursor.close()
        assert cursor in connection._result_cursors
        assert not connection._result_cleanup_safe
    finally:
        connection.close()


def test_sync_submission_exception_does_not_expose_raw_credential_details():
    secret = 'sentinel-secret-in-server-details'
    connection = make_connection(access_token='test-token', auto_resume=False)
    connection._channel = None
    client = query_client()
    client.prepareStatement = ScriptedRPC(rpc_error(grpc.StatusCode.UNAVAILABLE, secret))
    connection._client = client
    try:
        with pytest.raises(AmbiguousSubmissionError) as caught:
            connection.cursor().execute('INSERT INTO test_table VALUES (1)')
        assert secret not in ''.join(traceback.format_exception(caught.value))
    finally:
        connection.close()


def test_async_submission_exception_does_not_expose_raw_credential_details():
    async def run():
        secret = 'sentinel-secret-in-server-details'
        connection = AsyncConnection('fixture.invalid', 443, access_token='test-token',
                                     secure=True, auto_resume=False)
        await connection.open()
        rpc = AsyncRPC(rpc_error(grpc.StatusCode.UNAVAILABLE, secret))
        connection._client = SimpleNamespace(prepareStatement=rpc)
        try:
            with pytest.raises(AmbiguousSubmissionError) as caught:
                await connection.cursor().execute('INSERT INTO test_table VALUES (1)')
            assert secret not in ''.join(traceback.format_exception(caught.value))
        finally:
            await connection.close()
    asyncio.run(run())


def test_rejected_older_token_does_not_retire_newer_token():
    state = TokenState(timeout=1)
    state.token, state.expires_at = 'newer-token', time.monotonic() + 300
    state.reject_token('older-token')
    assert state.token == 'newer-token'
    state.reject_token('newer-token')
    assert state.token is None
    assert state.expires_at == 0


def test_sync_metadata_error_is_redacted_without_replaying_query():
    secret = 'metadata-credential-sentinel'
    connection = make_connection(access_token='test-token', auto_resume=False)
    connection._channel = None
    client = query_client(metadata=[rpc_error(grpc.StatusCode.PERMISSION_DENIED, secret)])
    connection._client = client
    try:
        with pytest.raises(grpc.RpcError) as caught:
            connection.cursor().execute('SELECT 1')
        assert caught.value.code() == grpc.StatusCode.PERMISSION_DENIED
        assert secret not in ''.join(traceback.format_exception(caught.value))
        assert len(client.prepareStatement.calls) == len(client.executeStatement.calls) == 1
        assert len(client.getResultMetadata.calls) == 1
    finally:
        connection.close()


def test_async_rpc_error_is_redacted_and_preserves_status_code():
    async def run():
        secret = 'metadata-credential-sentinel'
        connection = AsyncConnection('fixture.invalid', 443, access_token='test-token',
                                     secure=True, auto_resume=False)
        await connection.open()
        rpc = AsyncRPC(rpc_error(grpc.StatusCode.PERMISSION_DENIED, secret))
        connection._client = SimpleNamespace(status=rpc)
        try:
            with pytest.raises(grpc.RpcError) as caught:
                await connection._rpc('status', pb.StatusRequest(), deadline=connection._deadline())
            assert caught.value.code() == grpc.StatusCode.PERMISSION_DENIED
            assert secret not in ''.join(traceback.format_exception(caught.value))
            assert len(rpc.calls) == 1
        finally:
            await connection.close()
    asyncio.run(run())


def test_async_result_transport_error_does_not_expose_server_details():
    async def run():
        secret = 'result-credential-sentinel'
        connection = AsyncConnection('fixture.invalid', 443, access_token='test-token',
                                     secure=True, auto_resume=False)
        await connection.open()
        rpc = AsyncRPC(rpc_error(grpc.StatusCode.PERMISSION_DENIED, secret))
        connection._client = SimpleNamespace(getNextResultBatch=rpc)
        try:
            with pytest.raises(grpc.RpcError) as caught:
                await connection._raw_result_rpc('getNextResultBatch', pb.StatusRequest(),
                                                  [('authorization', 'Bearer test-token')],
                                                  connection._deadline())
            assert caught.value.code() == grpc.StatusCode.PERMISSION_DENIED
            assert secret not in ''.join(traceback.format_exception(caught.value))
            assert len(rpc.calls) == 1
        finally:
            await connection.close()
    asyncio.run(run())


def test_sync_result_rejection_does_not_fall_back_to_second_fetch():
    connection = make_connection(access_token='test-token', auto_resume=False,
                                 enable_result_batch_v2=True)
    connection._channel = None
    v2 = ScriptedRPC(rpc_error(grpc.StatusCode.UNIMPLEMENTED, 'admitted result'))
    v1 = ScriptedRPC(rpc_error(grpc.StatusCode.UNIMPLEMENTED, 'second fetch'))
    connection._client = SimpleNamespace(getNextResultBatchV2=v2, getNextResultBatch=v1)
    cursor = connection.cursor()
    cursor._query_id, cursor._engine_ip = 'unissued-local-query', 'planner'
    cursor._query_columns_description, cursor._is_metadata_updated = [], True
    try:
        with pytest.raises(grpc.RpcError):
            cursor.fetch_batch()
        assert len(v2.calls) == 1
        assert not v1.calls
        assert cursor._result_protocol == 'v2'
        assert cursor._result_failure is not None
    finally:
        connection.close()


def test_async_result_rejection_does_not_fall_back_to_second_fetch():
    from e6data_python_connector.async_connection import QueryRoute
    async def run():
        connection = AsyncConnection('fixture.invalid', 443, access_token='test-token',
                                     secure=True, auto_resume=False, enable_result_batch_v2=True)
        await connection.open()
        v2 = AsyncRPC(rpc_error(grpc.StatusCode.UNIMPLEMENTED, 'admitted result'))
        v1 = AsyncRPC(rpc_error(grpc.StatusCode.UNIMPLEMENTED, 'second fetch'))
        connection._client = SimpleNamespace(getNextResultBatchV2=v2, getNextResultBatch=v1)
        cursor = connection.cursor()
        cursor._route = connection._register_route(QueryRoute(connection.target, 'unissued-local-query',
                                                               'planner', connection.strategy))
        cursor._state, cursor._columns = 'ACTIVE', []
        try:
            with pytest.raises(grpc.RpcError):
                await cursor.fetch_batch()
            assert len(v2.calls) == 1
            assert not v1.calls
            assert cursor._result_protocol == 'v2'
            assert cursor._state == 'RESULT_FAILED'
        finally:
            await connection.close()
    asyncio.run(run())


def test_async_rejected_result_token_is_retired_without_another_fetch():
    async def run():
        connection = AsyncConnection('fixture.invalid', 443, secure=True, auto_resume=False,
                                     client_id='result-rejection-fixture', client_secret='test-secret',
                                     token_url='https://issuer.invalid/token')
        await connection.open()
        connection._token_provider._access_token = 'rejected-token'
        connection._token_provider._expires_at = time.monotonic() + 300
        rpc = AsyncRPC(rpc_error(grpc.StatusCode.UNAUTHENTICATED, 'expired'))
        connection._client = SimpleNamespace(getNextResultBatchV2=rpc)
        try:
            with pytest.raises(grpc.RpcError):
                await connection._raw_result_rpc('getNextResultBatchV2', pb.StatusRequest(),
                                                  [('authorization', 'Bearer rejected-token')],
                                                  connection._deadline())
            assert connection._token_provider._access_token is None
            assert len(rpc.calls) == 1
        finally:
            await connection.close()
    asyncio.run(run())


def test_sync_rejected_query_token_is_retired_without_another_rpc():
    connection = make_connection(access_token=None, client_id='query-rejection-fixture',
                                 client_secret='test-secret', token_url='https://issuer.invalid/token',
                                 auto_resume=False)
    connection._channel = None
    connection._token_provider._access_token = 'rejected-token'
    connection._token_provider._expires_at = time.monotonic() + 300
    rpc = ScriptedRPC(rpc_error(grpc.StatusCode.UNAUTHENTICATED, 'expired'))
    try:
        with pytest.raises(grpc.RpcError):
            connection._query_rpc(rpc, pb.StatusRequest(),
                                  metadata=[('authorization', 'Bearer rejected-token')])
        assert connection._token_provider._access_token is None
        assert len(rpc.calls) == 1
    finally:
        connection.close()


@pytest.mark.parametrize('stage', ['prepare', 'execute'])
def test_sync_interrupt_after_dispatch_retains_submission_uncertainty(stage):
    connection = make_connection(access_token='test-token', auto_resume=False)
    connection._channel = None
    client = query_client()
    method = 'prepareStatement' if stage == 'prepare' else 'executeStatement'
    setattr(client, method, ScriptedRPC(KeyboardInterrupt()))
    connection._client = client
    cursor = connection.cursor()
    try:
        with pytest.raises(KeyboardInterrupt):
            cursor.execute('INSERT INTO test_table VALUES (1)')
        assert cursor._submission_unknown
        cursor.close()
        assert not connection._result_cleanup_safe
        with pytest.raises(ProgrammingError):
            cursor.execute('INSERT INTO test_table VALUES (1)')
        assert len(getattr(client, method).calls) == 1
    finally:
        connection.close()


def test_sync_background_result_rejection_retires_matching_token_and_redacts_failure():
    from concurrent.futures import Future
    from e6data_python_connector.result_prefetch import ContinuousResultStream
    connection = make_connection(access_token=None, client_id='background-result-rejection-fixture',
                                 client_secret='test-secret', token_url='https://issuer.invalid/token',
                                 auto_resume=False, enable_result_batch_v2=True)
    connection._channel = None
    connection._token_provider._access_token = 'rejected-token'
    connection._token_provider._expires_at = time.monotonic() + 300
    secret = 'background-result-credential-sentinel'
    calls = []

    class FutureRPC:
        """Local future transport double, with the same metadata dispatch boundary."""
        def future(self, request, **options):
            calls.append((request, options))
            future = Future()
            future.set_exception(rpc_error(grpc.StatusCode.UNAUTHENTICATED, secret))
            return future

    connection._client = SimpleNamespace(getNextResultBatchV2=FutureRPC())
    cursor = connection.cursor()
    cursor._query_id, cursor._engine_ip = 'unissued-local-query', 'planner'
    stream = ContinuousResultStream(session_id='')
    completion = Future()
    completion.set_running_or_notify_cancel()
    try:
        cursor._download_result_stream(stream, completion, cursor._result_identity(), False)
        assert completion.done()
        assert len(calls) == 1
        assert connection._token_provider._access_token is None
        with pytest.raises(grpc.RpcError) as caught:
            stream.take()
        assert caught.value.code() == grpc.StatusCode.UNAUTHENTICATED
        assert secret not in ''.join(traceback.format_exception(caught.value))
    finally:
        connection.close()
