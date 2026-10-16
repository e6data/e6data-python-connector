"""SDK contracts using the existing loopback HTTPS/gRPC protocol fixture.

The fixture provides synthetic credentials and service responses. All transport
and OpenTelemetry code is real; these tests add no transport or SDK test double.
"""

import asyncio
from contextvars import ContextVar
import gc
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import weakref

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from e6data_python_connector.async_oauth import AsyncClientCredentialsTokenProvider
from e6data_python_connector.async_connection import AsyncConnection
from e6data_python_connector.async_connection_pool import AsyncConnectionPool
from e6data_python_connector.e6data_grpc import Connection
from e6data_python_connector.exceptions import OAuthError
from e6data_python_connector.oauth import ClientCredentialsTokenProvider
from test.test_oauth_auto_resume import clean_strategies
from test.test_oauth_resume_integration import FixtureService, local_services
from test.unit.test_sync_result_prefetch import envelope, local_results


_output = io.StringIO()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(
    out=_output, formatter=lambda span: span.to_json(indent=None) + "\n")))
trace.set_tracer_provider(_provider)
_tracer = trace.get_tracer("simple-oauth-tracing-contract")


def _spans(parent):
    _provider.force_flush()
    trace_id = "0x{:032x}".format(parent.get_span_context().trace_id)
    return [span for line in _output.getvalue().splitlines()
            if (span := json.loads(line))["context"]["trace_id"] == trace_id]


def _requests(parent):
    return [span for span in _spans(parent)
            if span["name"] == "oauth.token.acquire"]


def _assert_safe(spans):
    serialized = json.dumps(spans)
    for private in ("fixture-id", "private-client-secret", "synthetic-token-",
                    "Authorization", "Bearer ", "private-sql-text", "/token"):
        assert private not in serialized
    assert all(not span["events"] for span in spans)


def test_sync_network_exchange_inherits_owner_context_cache_has_no_attempt():
    service = FixtureService()
    service.token_lifetime = 3600
    with local_services(service) as (_, token_url):
        provider = ClientCredentialsTokenProvider(
            token_url, "fixture-id", "private-client-secret", tracing=True)
        with _tracer.start_as_current_span("sync-caller") as parent:
            assert provider.get_token() == "synthetic-token-1"
            assert provider.get_token() == "synthetic-token-1"
        requests = _requests(parent)
        assert service.tokens == len(requests) == 1
        request = requests[0]
        assert request["parent_id"] == "0x{:016x}".format(
            parent.get_span_context().span_id)
        headers = {key.lower(): value for key, value in service.token_headers[0].items()}
        assert headers["traceparent"].split("-")[1:3] == [
            request["context"]["trace_id"][2:], request["context"]["span_id"][2:]]
        assert "baggage" not in headers
        assert request["attributes"] == {
            "oauth.operation": "token.acquire", "oauth.grant_type": "client_credentials",
            "oauth.transport": "http", "oauth.reported_source": "python",
            "oauth.outcome": "success",
        }
        assert request["end_time"] is not None
        _assert_safe(_spans(parent))


def test_forced_renewal_records_each_actual_exchange_once():
    service = FixtureService()
    service.token_lifetime = 3600
    with local_services(service) as (_, token_url):
        provider = ClientCredentialsTokenProvider(
            token_url, "fixture-id", "private-client-secret", tracing=True)
        with _tracer.start_as_current_span("renewal-caller") as parent:
            assert provider.get_token() == "synthetic-token-1"
            assert provider.get_token(force_refresh=True) == "synthetic-token-2"
        requests = _requests(parent)
        assert service.tokens == len(requests) == 2
        assert len({span["context"]["span_id"] for span in requests}) == 2
        assert all(span["end_time"] is not None for span in requests)
        _assert_safe(_spans(parent))


def test_async_shared_renewal_records_one_exchange_and_preserves_callers():
    service = FixtureService()
    service.token_lifetime = 3600
    service.token_delay_at = 1
    with local_services(service) as (_, token_url):
        async def run():
            provider = AsyncClientCredentialsTokenProvider(
                token_url, "fixture-id", "private-client-secret", tracing=True)
            try:
                with _tracer.start_as_current_span("async-caller") as parent:
                    assert await asyncio.gather(
                        provider.get_token(), provider.get_token()) == [
                            "synthetic-token-1", "synthetic-token-1"]
                    assert trace.get_current_span() is parent
                    assert await provider.get_token() == "synthetic-token-1"
                requests = _requests(parent)
                assert service.tokens == len(requests) == 1
                assert requests[0]["parent_id"] == "0x{:016x}".format(
                    parent.get_span_context().span_id)
                _assert_safe(_spans(parent))
            finally:
                await provider.close()
        asyncio.run(run())


@pytest.mark.parametrize("asynchronous", [False, True])
def test_network_failure_finishes_span_without_exporting_exception(asynchronous):
    # Reserve a closed local port. The real transport receives refusal or timeout.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    token_url = "https://127.0.0.1:{}/token".format(port)

    async def run_async():
        provider = AsyncClientCredentialsTokenProvider(
            token_url, "fixture-id", "private-client-secret", timeout=1, tracing=True)
        try:
            with pytest.raises((OAuthError, TimeoutError)):
                await provider.get_token()
        finally:
            await provider.close(deadline=time.monotonic() + 5)

    with _tracer.start_as_current_span("failure-caller") as parent:
        if asynchronous:
            asyncio.run(run_async())
        else:
            provider = ClientCredentialsTokenProvider(
                token_url, "fixture-id", "private-client-secret", timeout=1, tracing=True)
            with pytest.raises((OAuthError, TimeoutError)):
                provider.get_token()
    requests = _requests(parent)
    assert len(requests) == 1
    assert requests[0]["status"]["status_code"] == "ERROR"
    assert requests[0]["end_time"] is not None
    _assert_safe(_spans(parent))


def test_existing_grpc_calls_carry_current_context_without_query_replay(clean_strategies):
    service = FixtureService()
    service.token_lifetime = 3600
    with local_services(service) as (port, token_url):
        with _tracer.start_as_current_span("query-caller") as parent:
            connection = Connection(
                "127.0.0.1", port, client_id="fixture-id",
                client_secret="private-client-secret", token_url=token_url,
                cluster_name="fixture-cluster", require_fastbinary=False, tracing=True)
            try:
                assert connection.cursor().execute("SELECT 'private-sql-text'") == "fixture-query"
            finally:
                connection.close()
        expected_trace_id = "{:032x}".format(parent.get_span_context().trace_id)
        assert all(headers["traceparent"].split("-")[1] == expected_trace_id
                   for _, _, headers, _ in service.calls)
        assert sum(name == "execute" for name, *_ in service.calls) == 1
        assert all("baggage" not in headers for _, _, headers, _ in service.calls)
        _assert_safe(_spans(parent))


def test_opt_out_does_not_export_or_propagate_connector_context(clean_strategies):
    service = FixtureService()
    service.token_lifetime = 3600
    with local_services(service) as (port, token_url):
        with _tracer.start_as_current_span("disabled-caller") as parent:
            connection = Connection(
                "127.0.0.1", port, client_id="fixture-id",
                client_secret="private-client-secret", token_url=token_url,
                cluster_name="fixture-cluster", require_fastbinary=False, tracing=False)
            try:
                assert connection.cursor().execute("SELECT 1") == "fixture-query"
            finally:
                connection.close()
        assert [span["name"] for span in _spans(parent)] == ["disabled-caller"]
        assert all("traceparent" not in headers for _, _, headers, _ in service.calls)
        assert all("traceparent" not in {key.lower() for key in headers}
                   for headers in service.token_headers)


def test_cancelling_waiter_preserves_shared_exchange_and_other_caller_context():
    service = FixtureService()
    service.token_lifetime = 3600
    service.token_delay_at = 1
    with local_services(service) as (_, token_url):
        async def run():
            provider = AsyncClientCredentialsTokenProvider(
                token_url, "fixture-id", "private-client-secret", tracing=True)
            async def caller(name):
                with _tracer.start_as_current_span(name) as caller_span:
                    token = await provider.get_token()
                    assert trace.get_current_span() is caller_span
                    return token
            try:
                with _tracer.start_as_current_span("shared-renewal") as parent:
                    first = asyncio.create_task(caller("first-waiter"))
                    async with asyncio.timeout(2):
                        while service.tokens != 1:
                            await asyncio.sleep(.001)
                    second = asyncio.create_task(caller("second-waiter"))
                    async with asyncio.timeout(2):
                        while provider._waiters != 2:
                            await asyncio.sleep(.001)
                    first.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await first
                    assert await second == "synthetic-token-1"
                    assert trace.get_current_span() is parent
                requests = _requests(parent)
                assert service.tokens == len(requests) == 1
                assert requests[0]["attributes"]["oauth.outcome"] == "success"
                _assert_safe(requests)
            finally:
                await provider.close()
        asyncio.run(run())


def test_cancelling_only_async_caller_finishes_owned_exchange_span():
    service = FixtureService()
    service.token_delay_at = 1
    with local_services(service) as (_, token_url):
        async def run():
            provider = AsyncClientCredentialsTokenProvider(
                token_url, "fixture-id", "private-client-secret", tracing=True)
            with _tracer.start_as_current_span("cancelled-caller") as parent:
                task = asyncio.create_task(provider.get_token())
                async with asyncio.timeout(2):
                    while service.tokens != 1:
                        await asyncio.sleep(.001)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                await provider.close()
                assert trace.get_current_span() is parent
            requests = _requests(parent)
            assert len(requests) == 1
            assert requests[0]["attributes"]["oauth.outcome"] == "cancelled"
            assert requests[0]["status"]["status_code"] == "ERROR"
            assert requests[0]["end_time"] is not None
            _assert_safe(requests)
        asyncio.run(run())


def test_background_result_fetch_preserves_current_query_context(local_results):
    with _tracer.start_as_current_span("fetch-caller") as parent:
        service, connection, cursor = local_results(
            [envelope([[1], [2]]), envelope([[3]], terminal=True)], tracing=True)
        try:
            assert cursor.fetchall() == [[1], [2], [3]]
        finally:
            cursor.clear(timeout=2)
            connection.close()
    assert len(service.request_metadata) == 2
    assert all(headers["traceparent"].split("-")[1] ==
               "{:032x}".format(parent.get_span_context().trace_id)
               for headers in service.request_metadata)


def test_tracing_without_optional_dependency_is_a_noop_in_clean_interpreter():
    helper = Path(__file__).resolve().parents[2] / "e6data_python_connector" / "tracing.py"
    # -S removes site packages. Exercise the real standalone optional helper.
    code = """
import runpy, sys
assert 'opentelemetry' not in sys.modules
helper = runpy.run_path(sys.argv[1])
with helper['token_acquisition'](True):
    assert helper['trace_headers'](True) == {}
assert 'opentelemetry' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-S", "-c", code, str(helper)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_real_exporter_io_failure_does_not_change_token_acquisition():
    service = FixtureService()
    service.token_lifetime = 3600
    with local_services(service) as (_, token_url):
        code = """
import io, sys
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from e6data_python_connector.oauth import ClientCredentialsTokenProvider
output = io.StringIO()
output.close()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=output)))
trace.set_tracer_provider(provider)
token_provider = ClientCredentialsTokenProvider(
    sys.argv[1], 'fixture-id', 'private-client-secret', tracing=True)
assert token_provider.get_token() == 'synthetic-token-1'
assert token_provider.get_token() == 'synthetic-token-1'
"""
        result = subprocess.run([sys.executable, "-c", code, token_url],
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert "Exception while exporting Span" in result.stderr
        assert service.tokens == 1


@pytest.mark.parametrize("enabled", [False, True])
def test_async_connection_and_pool_keep_each_callers_current_context(enabled):
    async def run():
        connection = AsyncConnection(
            '127.0.0.1', 1, access_token='synthetic-static-token', secure=True,
            tracing=enabled)
        assert connection.tracing is enabled
        async with connection:
            for name in ('first-async-query', 'second-async-query'):
                with _tracer.start_as_current_span(name) as parent:
                    metadata = dict(await connection._metadata(time.monotonic() + 2))
                    assert ('traceparent' in metadata) is enabled
                    if enabled:
                        assert metadata['traceparent'].split('-')[1] == '{:032x}'.format(
                            parent.get_span_context().trace_id)
        async with AsyncConnectionPool(
                min_size=0, max_size=1, host='127.0.0.1', port=1,
                access_token='synthetic-static-token', secure=True,
                tracing=enabled) as pool:
            for name in ('first-pool-caller', 'second-pool-caller'):
                with _tracer.start_as_current_span(name) as parent:
                    metadata = dict(await pool._resume_metadata('blue', time.monotonic() + 2))
                    assert ('traceparent' in metadata) is enabled
                    if enabled:
                        assert metadata['traceparent'].split('-')[1] == '{:032x}'.format(
                            parent.get_span_context().trace_id)
    asyncio.run(run())


def test_finished_result_worker_releases_objects_from_copied_context(local_results):
    class ContextObject:
        pass

    service, connection, cursor = local_results(
        [envelope([[1]], terminal=True)], tracing=True)
    service.response_delay = .2
    current = ContextVar('oauth-tracing-worker-lifetime')
    value = ContextObject()
    reference = weakref.ref(value)
    token = current.set(value)
    existing = set(threading.enumerate())
    try:
        cursor._start_prefetch(time.monotonic() + 2)
    finally:
        current.reset(token)
    del value, token
    assert service.entered[0].wait(2)
    worker = next(thread for thread in threading.enumerate()
                  if thread not in existing and thread.name == 'e6-result-download')
    worker.join(2)
    assert not worker.is_alive()
    gc.collect()
    assert reference() is None
    assert cursor.fetchall() == [[1]]
    cursor.clear(timeout=2)
    connection.close()
