"""Offline regressions for recovery strictly before query admission."""
import struct
from types import SimpleNamespace
from unittest.mock import patch

import grpc
import pytest
from grpc._channel import _InactiveRpcError, _RPCState

from e6data_python_connector import e6data_grpc as connector
from e6data_python_connector import cluster_manager, strategy
from e6data_python_connector.server import e6x_engine_pb2 as engine_pb
from e6data_python_connector.cluster_server import cluster_pb2 as cluster_pb


def rpc_error(code=grpc.StatusCode.UNAVAILABLE, detail='status: 503, cluster is suspended'):
    return _InactiveRpcError(_RPCState((), (), (), code, detail))


class ScriptedRPC:
    """Record real connector boundary calls; never initiate network traffic."""
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, request, **kwargs):
        self.calls.append((request, kwargs))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.fixture(autouse=True)
def clean_strategies():
    connector._clear_strategy_cache()
    connector._local_strategy_cache['query_strategy_map'] = {}
    connector._local_strategy_cache['session_invalidated'] = False
    strategy._clear_strategy_cache()
    yield
    connector._clear_strategy_cache()
    connector._local_strategy_cache['query_strategy_map'] = {}
    strategy._clear_strategy_cache()


def make_connection(**kwargs):
    defaults = dict(host='fixture.invalid', port=443, access_token='synthetic-token',
                    cluster_name='test-cluster', require_fastbinary=False)
    defaults.update(kwargs)
    with patch.object(connector.Connection, '_create_client'):
        return connector.Connection(**defaults)


def query_client(catalog=None, prepare=None, execute=None, metadata=None):
    suffix = 'V2' if catalog else ''
    response = engine_pb.PrepareStatementResponse(queryId='new-query', engineIP='planner')
    client = SimpleNamespace()
    setattr(client, 'prepareStatement' + suffix, ScriptedRPC(*(prepare or [response])))
    setattr(client, 'executeStatement' + suffix, ScriptedRPC(*(execute or [SimpleNamespace()])))
    client.getResultMetadata = ScriptedRPC(*(metadata or [
        engine_pb.GetResultMetadataResponse(resultMetaData=struct.pack('>qi', 0, 0))]))
    return client


@pytest.mark.parametrize('catalog', [None, 'catalog'])
def test_suspended_prepare_resumes_and_executes_once(catalog):
    connection = make_connection(catalog=catalog)
    suffix = 'V2' if catalog else ''
    response = engine_pb.PrepareStatementResponse(queryId='new-query', engineIP='planner')
    connection._client = query_client(catalog, prepare=[rpc_error(), response])
    cluster = SimpleNamespace(status=ScriptedRPC(cluster_pb.ClusterStatusResponse(status='suspended'),
                                                 cluster_pb.ClusterStatusResponse(status='active')),
                              resume=ScriptedRPC(cluster_pb.ResumeResponse(status='resuming')))
    with patch.object(cluster_manager.ClusterManager, '_get_connection', new=property(lambda _: cluster)):
        assert connection.cursor().execute('SELECT 1') == 'new-query'
    assert len(getattr(connection._client, 'prepareStatement' + suffix).calls) == 2
    assert len(getattr(connection._client, 'executeStatement' + suffix).calls) == 1
    assert len(cluster.resume.calls) == 1
    for request, kwargs in cluster.status.calls + cluster.resume.calls:
        assert request.user == request.password == ''
        assert dict(kwargs['metadata'])['authorization'] == 'Bearer synthetic-token'
        assert 0 < kwargs['timeout'] <= 300


@pytest.mark.parametrize('catalog', [None, 'catalog'])
@pytest.mark.parametrize('code,detail', [
    (grpc.StatusCode.INTERNAL, 'Access denied'),
    (grpc.StatusCode.UNKNOWN, 'status: 456'),
    (grpc.StatusCode.UNAVAILABLE, 'status: 503, cluster is suspended'),
    (grpc.StatusCode.UNAUTHENTICATED, 'expired'),
])
@pytest.mark.parametrize('failure_stage', ['execute', 'metadata'])
def test_oauth_never_replays_after_prepare(catalog, code, detail, failure_stage):
    failure = rpc_error(code, detail)
    connection = make_connection(catalog=catalog)
    connection._client = query_client(catalog, **{failure_stage: [failure]})
    with patch.object(connection, 'get_re_authenticate_session_id') as reauth:
        with pytest.raises(grpc.RpcError) as raised:
            connection.cursor().execute('INSERT INTO t VALUES (1)')
    assert raised.value is failure
    suffix = 'V2' if catalog else ''
    assert len(getattr(connection._client, 'prepareStatement' + suffix).calls) == 1
    assert len(getattr(connection._client, 'executeStatement' + suffix).calls) == 1
    reauth.assert_not_called()


@pytest.mark.parametrize('code,detail,auto_resume', [
    (grpc.StatusCode.UNAVAILABLE, 'status: 503', True),
    (grpc.StatusCode.UNAVAILABLE, 'connection reset', True),
    (grpc.StatusCode.PERMISSION_DENIED, 'status: 503, cluster is suspended', True),
    (grpc.StatusCode.DEADLINE_EXCEEDED, 'status: 503, cluster is suspended', True),
    (grpc.StatusCode.UNAVAILABLE, 'status: 503, cluster is suspended', False),
    (grpc.StatusCode.UNAVAILABLE, 'prefix status: 503, cluster is suspended suffix', True),
])
def test_only_exact_supported_suspension_recovers(code, detail, auto_resume):
    connection = make_connection(auto_resume=auto_resume)
    failure = rpc_error(code, detail)
    connection._client = query_client(prepare=[failure])
    with patch.object(cluster_manager.ClusterManager, '_get_connection') as cluster:
        with pytest.raises(grpc.RpcError) as raised:
            connection.cursor().execute('SELECT 1')
    assert raised.value is failure
    cluster.assert_not_called()


def test_second_suspension_stops_with_routing_error():
    connection = make_connection()
    connection._client = query_client(prepare=[rpc_error(), rpc_error()])
    cluster = SimpleNamespace(status=ScriptedRPC(cluster_pb.ClusterStatusResponse(status='active')))
    with patch.object(cluster_manager.ClusterManager, '_get_connection', new=property(lambda _: cluster)):
        with pytest.raises(Exception, match='routing.*ready'):
            connection.cursor().execute('SELECT 1')
    assert len(connection._client.prepareStatement.calls) == 2
    assert not connection._client.executeStatement.calls


def test_reused_cursor_prepares_new_query_on_successful_recovery_strategy():
    connector._set_active_strategy('blue')
    strategy._set_active_strategy('green')
    connector._register_query_strategy('old-query', 'blue')
    connection = make_connection()
    connection._client = query_client(prepare=[rpc_error(), engine_pb.PrepareStatementResponse(
        queryId='new-query', engineIP='new-planner')])
    cursor = connection.cursor()
    cursor._query_id, cursor._engine_ip = 'old-query', 'old-planner'
    cluster = SimpleNamespace(status=ScriptedRPC(rpc_error(grpc.StatusCode.UNKNOWN, 'status: 456'),
                                                 cluster_pb.ClusterStatusResponse(status='active')))
    with patch.object(cluster_manager.ClusterManager, '_get_connection', new=property(lambda _: cluster)):
        cursor.execute('SELECT 1')
    headers = [dict(kwargs['metadata']) for _, kwargs in connection._client.prepareStatement.calls]
    assert headers[0]['strategy'] == 'blue'
    assert headers[1]['strategy'] == 'green'
    assert all('plannerip' not in header for header in headers)
    assert connector._get_query_strategy('old-query') == 'blue'
    assert connector._get_query_strategy('new-query') == 'green'
    assert dict(connection._client.executeStatement.calls[0][1]['metadata'])['strategy'] == 'green'


@pytest.mark.parametrize('catalog', [None, 'catalog'])
@pytest.mark.parametrize('reuse_cursor', [True, False])
def test_recovered_strategy_survives_into_the_next_query(catalog, reuse_cursor):
    connector._set_active_strategy('blue')
    connector._register_query_strategy('old-query', 'blue')
    connection = make_connection(catalog=catalog)
    metadata = engine_pb.GetResultMetadataResponse(resultMetaData=struct.pack('>qi', 0, 0))
    connection._client = query_client(catalog, execute=[SimpleNamespace(), SimpleNamespace()],
                                      metadata=[metadata, metadata])
    prepare_calls = []
    def prepare(request, **kwargs):
        prepare_calls.append((request, kwargs))
        if len(prepare_calls) == 1:
            raise rpc_error()
        if dict(kwargs['metadata'])['strategy'] != 'green':
            raise rpc_error(grpc.StatusCode.UNKNOWN, 'status: 456')
        return engine_pb.PrepareStatementResponse(
            queryId='first-query' if len(prepare_calls) == 2 else 'second-query', engineIP='planner')
    suffix = 'V2' if catalog else ''
    setattr(connection._client, 'prepareStatement' + suffix, prepare)
    cluster = SimpleNamespace(status=ScriptedRPC(rpc_error(grpc.StatusCode.UNKNOWN, 'status: 456'),
        cluster_pb.ClusterStatusResponse(status='suspended'), cluster_pb.ClusterStatusResponse(status='active')),
        resume=ScriptedRPC(cluster_pb.ResumeResponse(status='resuming')))
    with patch.object(cluster_manager.ClusterManager, '_get_connection', new=property(lambda _: cluster)):
        first = connection.cursor()
        assert first.execute('SELECT 1') == 'first-query'
        second = first if reuse_cursor else connection.cursor()
        assert second.execute('SELECT 2') == 'second-query'
    assert [dict(kwargs['metadata'])['strategy'] for _, kwargs in prepare_calls] == ['blue', 'green', 'green']
    assert all('plannerip' not in dict(kwargs['metadata']) for _, kwargs in prepare_calls)
    assert len(getattr(connection._client, 'executeStatement' + suffix).calls) == 2
    assert len(cluster.resume.calls) == 1
    assert len(cluster.status.calls) == 3
    assert connector._get_query_strategy('old-query') == 'blue'
    assert connector._get_query_strategy('first-query') == 'green'
    assert connector._get_query_strategy('second-query') == 'green'
    # Recovery on this connection cannot reroute another connection's next query.
    assert connector._get_active_strategy() == 'blue'


@pytest.mark.parametrize('catalog', [None, 'catalog'])
@pytest.mark.parametrize('reuse_cursor', [True, False])
@pytest.mark.parametrize('delayed_mismatch', [False, True])
def test_recovered_strategy_corrects_later_transition_once(catalog, reuse_cursor, delayed_mismatch):
    connector._set_active_strategy('blue')
    connector._register_query_strategy('old-query', 'blue')
    connection = make_connection(catalog=catalog)
    metadata = engine_pb.GetResultMetadataResponse(resultMetaData=struct.pack('>qi', 0, 0))
    connection._client = query_client(catalog, execute=[SimpleNamespace(), SimpleNamespace()],
                                      metadata=[metadata, metadata])
    prepare_calls = []
    active = ['green']
    def prepare(request, **kwargs):
        prepare_calls.append((request, kwargs))
        if len(prepare_calls) == 1:
            raise rpc_error()
        if ((delayed_mismatch and len(prepare_calls) >= 3)
                or dict(kwargs['metadata'])['strategy'] != active[0]):
            raise rpc_error(grpc.StatusCode.UNKNOWN, 'status: 456')
        return engine_pb.PrepareStatementResponse(
            queryId='first-query' if len(prepare_calls) == 2 else 'second-query', engineIP='planner')
    suffix = 'V2' if catalog else ''
    setattr(connection._client, 'prepareStatement' + suffix, prepare)
    cluster = SimpleNamespace(status=ScriptedRPC(rpc_error(grpc.StatusCode.UNKNOWN, 'status: 456'),
        cluster_pb.ClusterStatusResponse(status='suspended'), cluster_pb.ClusterStatusResponse(status='active')),
        resume=ScriptedRPC(cluster_pb.ResumeResponse(status='resuming')))
    with patch.object(cluster_manager.ClusterManager, '_get_connection', new=property(lambda _: cluster)):
        first = connection.cursor()
        assert first.execute('SELECT 1') == 'first-query'
        connector._set_active_strategy('green')
        connector._set_pending_strategy('blue')
        connector._apply_pending_strategy()
        active[0] = 'blue'
        second = first if reuse_cursor else connection.cursor()
        if delayed_mismatch:
            with pytest.raises(grpc.RpcError) as raised:
                second.execute('SELECT 2')
            assert raised.value.code() == grpc.StatusCode.UNKNOWN
            assert raised.value.details() == 'status: 456'
        else:
            assert second.execute('SELECT 2') == 'second-query'
    assert [dict(kwargs['metadata'])['strategy'] for _, kwargs in prepare_calls] == [
        'blue', 'green', 'green', 'blue']
    assert all('plannerip' not in dict(kwargs['metadata']) for _, kwargs in prepare_calls)
    assert len(getattr(connection._client, 'executeStatement' + suffix).calls) == (1 if delayed_mismatch else 2)
    assert len(cluster.resume.calls) == 1
    assert len(cluster.status.calls) == 3
    assert connector._get_query_strategy('old-query') == 'blue'
    assert connector._get_query_strategy('first-query') == 'green'
    assert connector._get_shared_strategy()['query_strategy_map'].get('second-query') == (
        None if delayed_mismatch else 'blue')


def test_prepare_strategy_correction_keeps_auth_refresh_and_deadline_budget():
    connector._set_active_strategy('green')
    connection = make_connection(grpc_options={'grpc_prepare_timeout': 2})
    failure = rpc_error(grpc.StatusCode.UNAUTHENTICATED, 'still rejected')
    connection._client = query_client(prepare=[rpc_error(grpc.StatusCode.UNAUTHENTICATED, 'expired'),
        rpc_error(grpc.StatusCode.UNKNOWN, 'status: 456'), failure])
    metadata_calls = []
    def metadata(selected, deadline, rejected_token=None):
        metadata_calls.append((selected, deadline, rejected_token))
        return [('authorization', 'Bearer refreshed' if rejected_token else 'Bearer current'),
                ('strategy', selected)]
    with patch.object(connection, '_oauth_metadata', new=metadata):
        with pytest.raises(grpc.RpcError) as raised:
            connection.cursor().execute('SELECT 1')
    assert raised.value is failure
    assert [call[0] for call in metadata_calls] == ['green', 'green', 'blue']
    assert len({call[1] for call in metadata_calls}) == 1
    assert sum(call[2] is not None for call in metadata_calls) == 1
    assert not connection._client.executeStatement.calls


@pytest.mark.parametrize('catalog', [None, 'catalog'])
def test_late_strategy_rejection_cannot_schedule_a_prepare_after_deadline(catalog):
    import time
    connector._set_active_strategy('green')
    connection = make_connection(catalog=catalog, grpc_options={'grpc_prepare_timeout': 0.03})
    connection._client = query_client(catalog)
    calls = []
    def late_prepare(request, **kwargs):
        calls.append((request, kwargs))
        time.sleep(0.04)
        raise rpc_error(grpc.StatusCode.UNKNOWN, 'status: 456')
    suffix = 'V2' if catalog else ''
    setattr(connection._client, 'prepareStatement' + suffix, late_prepare)
    with pytest.raises(TimeoutError):
        connection.cursor().execute('SELECT 1')
    assert len(calls) == 1
    assert not getattr(connection._client, 'executeStatement' + suffix).calls


@pytest.mark.parametrize('catalog', [None, 'catalog'])
def test_initial_prepare_keeps_configured_deadline(catalog):
    connection = make_connection(catalog=catalog, grpc_options={'grpc_prepare_timeout': 7})
    connection._client = query_client(catalog)
    connection.cursor().execute('SELECT 1')
    suffix = 'V2' if catalog else ''
    assert 0 < getattr(connection._client, 'prepareStatement' + suffix).calls[0][1]['timeout'] <= 7


def test_static_access_token_is_not_retried_on_unauthenticated():
    connection = make_connection()
    failure = rpc_error(grpc.StatusCode.UNAUTHENTICATED, 'expired')
    connection._client = query_client(prepare=[failure])
    with pytest.raises(grpc.RpcError) as raised:
        connection.cursor().execute('SELECT 1')
    assert raised.value is failure
    assert len(connection._client.prepareStatement.calls) == 1


def test_cursor_reuse_allows_a_later_independent_recovery():
    connection = make_connection()
    response = engine_pb.PrepareStatementResponse(queryId='first-query', engineIP='planner')
    response2 = engine_pb.PrepareStatementResponse(queryId='second-query', engineIP='planner')
    metadata = engine_pb.GetResultMetadataResponse(resultMetaData=struct.pack('>qi', 0, 0))
    connection._client = query_client(prepare=[rpc_error(), response, rpc_error(), response2],
        execute=[SimpleNamespace(), SimpleNamespace()], metadata=[metadata, metadata])
    cluster = SimpleNamespace(status=ScriptedRPC(cluster_pb.ClusterStatusResponse(status='active'),
                                                 cluster_pb.ClusterStatusResponse(status='active')))
    with patch.object(cluster_manager.ClusterManager, '_get_connection', new=property(lambda _: cluster)):
        cursor = connection.cursor()
        assert cursor.execute('SELECT 1') == 'first-query'
        assert cursor.execute('SELECT 2') == 'second-query'
    assert len(connection._client.prepareStatement.calls) == 4
    assert len(connection._client.executeStatement.calls) == 2


def test_resumed_prepare_cannot_outlive_recovery_budget():
    import time
    connection = make_connection(grpc_options={'grpc_auto_resume_timeout_seconds': 0.03})
    connection._client = query_client(prepare=[rpc_error()])
    def slow_status(request, **kwargs):
        time.sleep(0.04)
        return cluster_pb.ClusterStatusResponse(status='active')
    cluster = SimpleNamespace(status=slow_status)
    with patch.object(cluster_manager.ClusterManager, '_get_connection', new=property(lambda _: cluster)):
        with pytest.raises(TimeoutError):
            connection.cursor().execute('SELECT 1')
    assert len(connection._client.prepareStatement.calls) == 1
    assert not connection._client.executeStatement.calls


@pytest.mark.parametrize('cached,active', [
    ('blue', 'blue'), ('green', 'green'), (None, 'green'),
    pytest.param(None, 'blue', marks=pytest.mark.xfail(strict=True,
        reason='Existing no-cache legacy authentication advances to green after resuming blue.')),
])
def test_legacy_suspend_resume_baseline(cached, active):
    connector._set_active_strategy(cached)
    state = ['suspended']
    seen = []
    connection = make_connection(access_token=None, username='fixture-user', password='fixture-password')
    def authenticate(request, metadata):
        assert request.user == 'fixture-user'
        assert request.password == 'fixture-password'
        headers = dict(metadata)
        assert 'authorization' not in headers
        seen.append(headers['strategy'])
        if state[0] == 'suspended':
            raise rpc_error()
        if headers['strategy'] != active:
            raise rpc_error(grpc.StatusCode.UNKNOWN, 'status: 456')
        return engine_pb.AuthenticateResponse(sessionId='legacy-session')
    def resume(_):
        state[0] = 'active'
        return True
    connection._client = SimpleNamespace(authenticate=authenticate)
    connection._channel = SimpleNamespace(close=lambda: None)
    with patch.object(cluster_manager.ClusterManager, 'resume', new=resume):
        assert connection.get_session_id == 'legacy-session'
    assert state[0] == 'active'
    assert seen[-1] == active


@pytest.mark.parametrize('catalog', [None, 'catalog'])
@pytest.mark.parametrize('cached', [None, 'blue', 'green'])
def test_legacy_prepare_and_execute_keep_session_and_routing(catalog, cached):
    connector._set_active_strategy(cached)
    connection = make_connection(access_token=None, username='fixture-user', password='fixture-password',
                                 catalog=catalog, grpc_options={'grpc_prepare_timeout': 7})
    connection._client = query_client(catalog)
    connection._client.authenticate = ScriptedRPC(engine_pb.AuthenticateResponse(sessionId='legacy-session'))
    assert connection.cursor().execute('SELECT 1') == 'new-query'
    suffix = 'V2' if catalog else ''
    prepare = getattr(connection._client, 'prepareStatement' + suffix)
    execute = getattr(connection._client, 'executeStatement' + suffix)
    for request, kwargs in prepare.calls + execute.calls + connection._client.getResultMetadata.calls:
        assert request.sessionId == 'legacy-session'
        assert 'authorization' not in dict(kwargs['metadata'])
        assert dict(kwargs['metadata'])['strategy'] == (cached or 'blue')
    if catalog:
        assert prepare.calls[0][1]['timeout'] == 7
    else:
        assert 'timeout' not in prepare.calls[0][1]


@pytest.mark.parametrize('code,details', [(grpc.StatusCode.INTERNAL, 'Access denied'),
                                       (grpc.StatusCode.UNKNOWN, 'status: 456')])
def test_legacy_re_auth_behavior_is_preserved(code, details):
    connection = make_connection(access_token=None, username='fixture-user', password='fixture-password')
    connection._session_id = 'legacy-session'
    prepared = engine_pb.PrepareStatementResponse(queryId='new-query', engineIP='planner')
    connection._client = query_client(prepare=[prepared, prepared],
        execute=[rpc_error(code, details), SimpleNamespace()])
    with patch.object(connection, 'get_re_authenticate_session_id') as reauth:
        assert connection.cursor().execute('SELECT 1') == 'new-query'
    assert len(connection._client.prepareStatement.calls) == 2
    assert len(connection._client.executeStatement.calls) == 2
    reauth.assert_called_once()
