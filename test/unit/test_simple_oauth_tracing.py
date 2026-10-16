"""SDK contracts using the existing loopback HTTPS/gRPC protocol fixture.

The fixture provides synthetic credentials and service responses. All transport
and OpenTelemetry code is real; these tests add no transport or SDK test double.
"""

import asyncio
import io
import json
import socket
import time

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from e6data_python_connector.async_oauth import AsyncClientCredentialsTokenProvider
from e6data_python_connector.e6data_grpc import Connection
from e6data_python_connector.exceptions import OAuthError
from e6data_python_connector.oauth import ClientCredentialsTokenProvider
from test.test_oauth_auto_resume import clean_strategies
from test.test_oauth_resume_integration import FixtureService, local_services


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
            if span["name"] == "e6data.oauth.token_request"]


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
