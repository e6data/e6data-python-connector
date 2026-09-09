"""Loopback-only gRPC and token-service integration for the full connector flow."""
import json
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import grpc
import pytest

from e6data_python_connector.e6data_grpc import Connection
from e6data_python_connector.server import e6x_engine_pb2 as engine_pb
from e6data_python_connector.server import e6x_engine_pb2_grpc as engine_rpc
from e6data_python_connector.cluster_server import cluster_pb2 as cluster_pb
from e6data_python_connector.cluster_server import cluster_pb2_grpc as cluster_rpc
from test.test_oauth_auto_resume import clean_strategies


class FixtureService(engine_rpc.QueryEngineServiceServicer, cluster_rpc.ClusterServiceServicer):
    def __init__(self, post_prepare_error=None):
        self.calls = []
        self.state = 'suspended'
        self.tokens = 0
        self.post_prepare_error = post_prepare_error
        self.token_delay_at = None
        self.status_delay = 0
        self.final_prepare_delay = 0
        self.delayed_token_done = threading.Event()
        self.token_lifetime = 30
        self.reject_name = None
        self.reject_code = grpc.StatusCode.UNAUTHENTICATED
        self.rejections_left = 0
        self.suspended_at = None

    def record(self, name, request, context):
        headers = dict(context.invocation_metadata())
        self.calls.append((name, request, headers, context.time_remaining()))
        assert headers['authorization'] == 'Bearer synthetic-token-{}'.format(self.tokens)
        assert headers['cluster-name'] == 'fixture-cluster'
        if hasattr(request, 'sessionId'):
            assert request.sessionId == ''
        if hasattr(request, 'user'):
            assert request.user == request.password == ''
        if name == self.reject_name and self.rejections_left:
            self.rejections_left -= 1
            context.abort(self.reject_code, 'fixture-rejected')

    def prepareStatement(self, request, context):
        self.record('prepare', request, context)
        if self.state != 'active':
            self.suspended_at = time.monotonic()
            context.abort(grpc.StatusCode.UNAVAILABLE, 'status: 503, cluster is suspended')
        time.sleep(self.final_prepare_delay)
        assert dict(context.invocation_metadata())['strategy'] == 'blue'
        return engine_pb.PrepareStatementResponse(queryId='fixture-query', engineIP='fixture-planner')

    prepareStatementV2 = prepareStatement

    def executeStatement(self, request, context):
        self.record('execute', request, context)
        if self.post_prepare_error:
            context.abort(*self.post_prepare_error)
        return engine_pb.ExecuteStatementResponse()

    executeStatementV2 = executeStatement

    def getResultMetadata(self, request, context):
        self.record('metadata', request, context)
        return engine_pb.GetResultMetadataResponse(resultMetaData=struct.pack('>qi', 1, 0))

    def status(self, request, context):
        self.record('status', request, context)
        time.sleep(self.status_delay)
        if self.state == 'resuming':
            self.state = 'active'
        return cluster_pb.ClusterStatusResponse(status=self.state)

    def resume(self, request, context):
        self.record('resume', request, context)
        self.state = 'resuming'
        return cluster_pb.ResumeResponse(status=self.state)


@contextmanager
def local_services(service):
    class TokenHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            assert self.path == '/token'
            body = self.rfile.read(int(self.headers['Content-Length']))
            assert body == b'grant_type=client_credentials'
            service.tokens += 1
            if service.tokens == service.token_delay_at:
                time.sleep(0.2)
            payload = json.dumps({'access_token': 'synthetic-token-{}'.format(service.tokens),
                                  'expires_in': service.token_lifetime}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except BrokenPipeError:
                pass  # The client deadline can close a token request already in flight.
            finally:
                if service.tokens == service.token_delay_at:
                    service.delayed_token_done.set()

    token_server = ThreadingHTTPServer(('127.0.0.1', 0), TokenHandler)
    thread = threading.Thread(target=token_server.serve_forever, daemon=True)
    thread.start()
    server = grpc.server(ThreadPoolExecutor(max_workers=4))
    engine_rpc.add_QueryEngineServiceServicer_to_server(service, server)
    cluster_rpc.add_ClusterServiceServicer_to_server(service, server)
    port = server.add_insecure_port('127.0.0.1:0')
    server.start()
    try:
        yield port, 'http://127.0.0.1:{}/token'.format(token_server.server_port)
    finally:
        server.stop(0).wait(2)
        token_server.shutdown()
        token_server.server_close()
        thread.join(2)


@pytest.mark.parametrize('catalog', [None, 'catalog'])
@pytest.mark.parametrize('post_prepare_error', [None, (grpc.StatusCode.INTERNAL, 'Access denied'),
                                              (grpc.StatusCode.UNKNOWN, 'status: 456'),
                                              (grpc.StatusCode.UNAUTHENTICATED, 'expired')])
def test_real_grpc_resume_authenticates_each_call_and_never_replays(catalog, post_prepare_error):
    service = FixtureService(post_prepare_error)
    with local_services(service) as (port, token_url):
        connection = Connection('127.0.0.1', port, client_id='fixture-id', client_secret='fixture-secret',
                                token_url=token_url, cluster_name='fixture-cluster', catalog=catalog,
                                require_fastbinary=False)
        try:
            if post_prepare_error:
                with pytest.raises(grpc.RpcError) as raised:
                    connection.cursor().execute('SELECT 1')
                assert raised.value.code() == post_prepare_error[0]
            else:
                assert connection.cursor().execute('SELECT 1') == 'fixture-query'
        finally:
            connection.close()
    names = [name for name, _, _, _ in service.calls]
    expected = ['prepare', 'status', 'resume', 'status', 'prepare', 'execute']
    if not post_prepare_error:
        expected.append('metadata')
    assert names == expected
    bearers = [headers['authorization'] for _, _, headers, _ in service.calls]
    assert len(set(bearers)) == len(service.calls)
    assert all(0 < timeout <= 301 for name, _, _, timeout in service.calls[1:5])


@pytest.mark.parametrize('stage', ['token', 'status', 'final_prepare'])
def test_recovery_deadline_stops_follow_up_work_on_real_transports(stage):
    service = FixtureService()
    if stage == 'token':
        service.token_delay_at = 2
    elif stage == 'status':
        service.status_delay = 0.2
    else:
        service.final_prepare_delay = 0.2
    with local_services(service) as (port, token_url):
        connection = Connection('127.0.0.1', port, client_id='fixture-id', client_secret='fixture-secret',
            token_url=token_url, cluster_name='fixture-cluster', require_fastbinary=False,
            grpc_options={'grpc_auto_resume_timeout_seconds': 0.05})
        start = time.monotonic()
        try:
            with pytest.raises((TimeoutError, grpc.RpcError)):
                connection.cursor().execute('SELECT 1')
            elapsed = time.monotonic() - start
            recovery_elapsed = time.monotonic() - service.suspended_at
            print('Recovery deadline fixture: stage={}, budget=0.05s, recovery={:.4f}s, '
                  'total_with_initial_prepare={:.4f}s'.format(stage, recovery_elapsed, elapsed))
            assert elapsed < 0.18
            assert recovery_elapsed < 0.12
            time.sleep(0.25)  # Observe late remote completion without local follow-up.
        finally:
            connection.close()
    names = [name for name, _, _, _ in service.calls]
    assert names == {'token': ['prepare'], 'status': ['prepare', 'status'],
        'final_prepare': ['prepare', 'status', 'resume', 'status', 'prepare']}[stage]


@pytest.mark.parametrize('name', ['prepare', 'status', 'resume'])
def test_explicit_auth_rejection_renews_the_real_provider_once(name):
    service = FixtureService()
    service.token_lifetime = 3600
    service.reject_name, service.rejections_left = name, 1
    with local_services(service) as (port, token_url):
        connection = Connection('127.0.0.1', port, client_id='fixture-id', client_secret='fixture-secret',
            token_url=token_url, cluster_name='fixture-cluster', require_fastbinary=False)
        try:
            assert connection.cursor().execute('SELECT 1') == 'fixture-query'
        finally:
            connection.close()
    assert service.tokens == 2
    assert sum(call[0] == 'execute' for call in service.calls) == 1


@pytest.mark.parametrize('code,rejections,expected_tokens', [
    (grpc.StatusCode.UNAUTHENTICATED, 2, 2), (grpc.StatusCode.PERMISSION_DENIED, 1, 1)])
def test_cluster_auth_failure_stops_without_mutation(code, rejections, expected_tokens):
    service = FixtureService()
    service.token_lifetime = 3600
    service.reject_name, service.reject_code, service.rejections_left = 'status', code, rejections
    with local_services(service) as (port, token_url):
        connection = Connection('127.0.0.1', port, client_id='fixture-id', client_secret='fixture-secret',
            token_url=token_url, cluster_name='fixture-cluster', require_fastbinary=False)
        try:
            with pytest.raises(grpc.RpcError) as raised:
                connection.cursor().execute('SELECT 1')
            assert raised.value.code() == code
        finally:
            connection.close()
    assert service.tokens == expected_tokens
    assert all(call[0] not in ('resume', 'execute') for call in service.calls)
