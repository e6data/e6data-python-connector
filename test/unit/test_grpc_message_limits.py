"""Real loopback gRPC transport checks, without simulating an e6data engine.

The byte echo service exercises the connector-created channels and gRPC's
message-size enforcement. It does not implement query or cluster RPCs.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor

import grpc
import pytest

from e6data_python_connector import Connection
from e6data_python_connector.async_connection import AsyncConnection
from e6data_python_connector.cluster_manager import ClusterManager


@pytest.fixture
def echo_port():
    def echo(request, context):
        context.set_compression(grpc.Compression.Gzip)
        return request

    with ThreadPoolExecutor(max_workers=1) as executor:
        server = grpc.server(executor, options=[
            ('grpc.max_receive_message_length', -1),
            ('grpc.max_send_message_length', -1),
        ])
        server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(
            'transport', {'echo': grpc.unary_unary_rpc_method_handler(echo)},
        ),))
        port = server.add_insecure_port('127.0.0.1:0')
        assert port > 0
        server.start()
        try:
            yield port
        finally:
            assert server.stop(0).wait(timeout=5)


def round_trip(api, port, payload, limits, enabled=True):
    if api == 'cluster':
        manager = ClusterManager('127.0.0.1', port, 'local-user', 'local-input',
                                 grpc_options=[('grpc.' + key, value) for key, value in limits.items()])
        manager._get_connection
        try:
            return manager._channel.unary_unary('/transport/echo')(payload, timeout=20)
        finally:
            manager._channel.close()
    options = dict(
        host='127.0.0.1', port=port, username='local-user', password='local-input',
        auto_resume=False, enable_result_batch_v2=enabled,
    )
    if api == 'sync':
        with Connection(**options, require_fastbinary=False, grpc_options=limits) as conn:
            return conn._channel.unary_unary('/transport/echo')(payload, timeout=20)

    async def run():
        channel_options = dict(limits)
        receive_options = {}
        if 'max_receive_message_length' in channel_options:
            receive_options['max_receive_message_bytes'] = channel_options.pop('max_receive_message_length')
        async with AsyncConnection(**options, **receive_options, secure=False,
                                   grpc_options=channel_options) as conn:
            return await conn._channel.unary_unary('/transport/echo')(payload, timeout=20)

    return asyncio.run(run())


@pytest.mark.parametrize('api', ['sync', 'async', 'cluster'])
def test_default_channel_receives_compressed_message_above_64_mib(api, echo_port):
    payload = b'x' * (65 * 1024 * 1024)
    assert round_trip(api, echo_port, payload, {}) == payload


@pytest.mark.parametrize('api', ['sync', 'async', 'cluster'])
@pytest.mark.parametrize('option', ['max_receive_message_length', 'max_send_message_length'])
def test_explicit_message_limit_is_enforced_by_transport(api, option, echo_port):
    with pytest.raises(grpc.RpcError) as error:
        round_trip(api, echo_port, b'x' * 2048, {option: 1024})
    assert error.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED


@pytest.mark.parametrize('api', ['sync', 'async'])
@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('option', ['max_receive_message_length', 'max_send_message_length'])
@pytest.mark.parametrize('equal_alias', [False, True])
def test_prefixed_message_limit_is_enforced_with_either_feature_flag(api, enabled, option, equal_alias, echo_port):
    limits = {'grpc.' + option: 1024}
    if equal_alias:
        limits[option] = 1024
    original = dict(limits)
    with pytest.raises(grpc.RpcError) as error:
        round_trip(api, echo_port, b'x' * 2048, limits, enabled)
    assert error.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED
    assert limits == original


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('option', ['max_receive_message_length', 'max_send_message_length'])
def test_sync_rejects_conflicting_limit_aliases_with_either_feature_flag(enabled, option):
    with pytest.raises(ValueError, match='Conflicting gRPC options'):
        Connection(
            '127.0.0.1', 1, username='local-user', password='local-input',
            auto_resume=False, require_fastbinary=False,
            enable_result_batch_v2=enabled,
            grpc_options={option: 1024, 'grpc.' + option: 2048},
        )
