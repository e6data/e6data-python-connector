"""Synchronous V2 local-state and real unimplemented-service contracts.

Unissued handles exercise client ownership only. No fixture implements a
successful query engine, and serialized responses are codec inputs only.
"""

import logging
import math
import sys
import time

import grpc
import pytest
from sqlalchemy.engine import make_url

from e6data_python_connector import Connection
from e6data_python_connector import e6data_grpc as engine
from e6data_python_connector.dialect import E6dataDialect
from e6data_python_connector.exceptions import IncompleteResultError, ProgrammingError
from e6data_python_connector.server import e6x_engine_pb2 as pb
from test.unit.test_protobuf_wire_contract import generated_server
from test.unit.test_result_batch_v2 import encode_chunk, string_chunk, wire


def connection(**changes):
    options = dict(host="127.0.0.1", port=1, username="local-user", password="local-input",
                   require_fastbinary=False, auto_resume=False, enable_result_batch_v2=True)
    options.update(changes)
    return Connection(**options)


@pytest.fixture
def local_cursor():
    conn = connection()
    cursor = conn.cursor()
    conn.close()
    cursor._query_id = "unissued-local-query"
    cursor._engine_ip = "127.0.0.1"
    cursor._is_metadata_updated = True
    cursor._query_columns_description = ["value"]
    cursor._result_session_id = "unissued-local-session"
    return cursor


def response(values=(), terminal=False, session="", strategy=""):
    assert hasattr(pb, "GetNextResultBatchV2Response"), "V2 response binding is missing"
    return pb.GetNextResultBatchV2Response(
        resultBatches=[string_chunk(chunk) for chunk in values], endOfStream=terminal,
        sessionId=session, new_strategy=strategy,
    )


@pytest.mark.parametrize("value", [None, 0, 1, "true", "false", [], {}])
def test_direct_flag_rejects_non_booleans(value):
    with pytest.raises(ValueError):
        connection(enable_result_batch_v2=value)


def test_default_and_opted_in_flags_do_not_enter_grpc_channel_options():
    legacy = Connection("127.0.0.1", 1, username="local-user", password="local-input",
                        require_fastbinary=False)
    opted = connection(grpc_options={"max_receive_message_length": 4096})
    try:
        assert legacy.enable_result_batch_v2 is False
        assert opted.enable_result_batch_v2 is True
        assert dict(opted._get_grpc_options)["grpc.max_receive_message_length"] == 4096
        assert not any("enable_result_batch_v2" in key for key, _ in opted._get_grpc_options)
        assert dict(legacy._get_grpc_options)["grpc.max_receive_message_length"] == -1
    finally:
        legacy.close()
        opted.close()


@pytest.mark.parametrize("value", [None, 0, -1, True, False, "3", math.inf, -math.inf, math.nan])
def test_opted_in_timeout_validation_precedes_defaulting(value):
    with pytest.raises(ValueError):
        connection(grpc_options={"grpc_prepare_timeout": value})


@pytest.mark.parametrize("value", [0.25, 2])
def test_positive_finite_timeout_is_preserved(value):
    conn = connection(grpc_options={"grpc_prepare_timeout": value})
    try:
        assert conn.grpc_prepare_timeout == value
    finally:
        conn.close()


@pytest.mark.parametrize("text,expected", [("true", True), ("false", False)])
def test_dialect_routes_boolean_option_outside_grpc_options(text, expected):
    url = make_url("e6data://local-user:local-input@localhost:1/?catalog=local&enable_result_batch_v2=" + text)
    _, options = E6dataDialect().create_connect_args(url)
    assert options["enable_result_batch_v2"] is expected
    assert "enable_result_batch_v2" not in options["grpc_options"]


@pytest.mark.parametrize("text", ["1", "yes", "", "invalid"])
def test_dialect_rejects_ambiguous_boolean_option(text):
    url = make_url("e6data://local-user:local-input@localhost:1/?catalog=local").update_query_dict(
        {"enable_result_batch_v2": text})
    with pytest.raises(ValueError):
        E6dataDialect().create_connect_args(url)


def test_mixed_fetches_cross_chunk_boundaries_without_repeating_leftovers(local_cursor):
    local_cursor._result_batches.accept(
        [[[1], [2], [3]], [[4], [5], [6]], [[7], [8], [9]]], end_of_stream=True,
    )
    assert local_cursor.fetchone() == [[1]]
    assert local_cursor.fetchmany(3) == [[2], [3], [4]]
    assert local_cursor.fetch_batch() == [[5], [6]]
    assert next(local_cursor.fetchall_buffer()) == [[7], [8], [9]]
    assert local_cursor.fetchone() is None
    assert local_cursor.fetchall() == []


def test_fetchall_preserves_rows_and_remaining_original_chunks(local_cursor):
    local_cursor._result_batches.accept([[[1], [2]], [[3], [4]]], end_of_stream=True)
    assert local_cursor.fetchone() == [[1]]
    assert local_cursor.fetchall() == [[2], [3], [4]]
    assert local_cursor.fetch_batch() is None


def test_foreign_query_id_cannot_relabel_pending_rows(local_cursor):
    local_cursor._data = [[1]]
    local_cursor._result_batches.accept([[[2]]], end_of_stream=True)
    with pytest.raises(ValueError):
        next(local_cursor.fetchall_buffer(query_id="different-unissued-query"))
    assert local_cursor.query_id == "unissued-local-query"
    assert list(local_cursor.fetchall_buffer(query_id=local_cursor.query_id)) == [[[1]], [[2]]]


def test_valid_envelope_keeps_session_local_and_terminal_data_available(local_cursor):
    original_connection_session = local_cursor.connection._session_id
    local_cursor._accept_result_batch(response([["one"], ["two"]], True, "refreshed-local-session"),
                                      time.monotonic() + 1)
    assert local_cursor._result_session_id == "refreshed-local-session"
    assert local_cursor.connection._session_id == original_connection_session
    assert local_cursor.fetch_batch() == [["one"]]
    assert local_cursor.fetch_batch() == [["two"]]
    assert local_cursor.fetch_batch() is None


def test_empty_session_does_not_replace_query_session(local_cursor):
    local_cursor._accept_result_batch(response([], False), time.monotonic() + 1)
    assert local_cursor._result_session_id == "unissued-local-session"
    assert local_cursor._result_batches.needs_fetch
    assert not local_cursor._result_exhausted


def test_oauth_response_session_is_never_adopted():
    conn = connection(username=None, password=None, access_token="local-nonusable-input")
    cursor = conn.cursor()
    conn.close()
    cursor._query_columns_description = ["value"]
    cursor._accept_result_batch(response([], True, "not-oauth-identity"), time.monotonic() + 1)
    assert cursor._result_session_id in (None, "")


def test_v1_fallback_decoding_retains_query_local_session_and_eof(local_cursor):
    local_cursor._result_protocol = "v1"
    local_cursor._accept_result_batch(pb.GetNextResultBatchResponse(
        resultBatch=string_chunk(["one"]), sessionId="refreshed-local-session"), time.monotonic() + 1)
    assert local_cursor.fetch_batch() == [["one"]]
    assert local_cursor._result_session_id == "refreshed-local-session"
    local_cursor._accept_result_batch(pb.GetNextResultBatchResponse(), time.monotonic() + 1)
    assert local_cursor.fetch_batch() is None


def test_zero_row_chunk_in_nonterminal_v2_envelope_is_not_eof(local_cursor):
    value = response()
    value.resultBatches.append(encode_chunk(wire.Chunk(0, [])))
    local_cursor._accept_result_batch(value, time.monotonic() + 1)
    assert local_cursor._result_batches.needs_fetch
    assert not local_cursor._result_exhausted


def test_malformed_later_payload_is_terminal_and_discards_undelivered_rows(local_cursor):
    value = response([["one"]], True)
    value.resultBatches.append(b"")
    local_cursor._data = [["old-buffered-row"]]
    with pytest.raises(IncompleteResultError) as caught:
        local_cursor._accept_result_batch(value, time.monotonic() + 1)
    assert caught.value.reason == "decode_failed"
    assert local_cursor._data is None
    assert local_cursor._result_batches.pop() is None
    assert local_cursor.query_id == "unissued-local-query"


def test_expired_post_response_budget_cannot_publish_data(local_cursor):
    with pytest.raises(IncompleteResultError):
        local_cursor._accept_result_batch(response([["one"]], True), time.monotonic() - 1)
    assert local_cursor._result_batches.pop() is None
    assert local_cursor.query_id == "unissued-local-query"


def test_legacy_opt_in_failure_blocks_every_fetch_and_preserves_handle(local_cursor):
    local_cursor._data = [[1]]
    local_cursor._result_batches.accept([[[2]]], end_of_stream=True)
    failure = local_cursor._fail_result("ambiguous_result")
    for action in (local_cursor.fetch_batch, local_cursor.fetchone, local_cursor.fetchmany,
                   local_cursor.fetchall, lambda: next(local_cursor.fetchall_buffer())):
        with pytest.raises(IncompleteResultError) as caught:
            action()
        assert caught.value is failure
    assert local_cursor._data is None
    assert local_cursor._result_batches.pop() is None
    assert local_cursor.query_id == "unissued-local-query"


def test_failed_cleanup_prevents_query_replacement_and_retains_buffers(local_cursor):
    local_cursor._result_batches.accept([[[1]]], end_of_stream=False)
    with pytest.raises((ValueError, grpc.RpcError)):
        local_cursor.execute("select 1")
    assert local_cursor.query_id == "unissued-local-query"
    assert local_cursor._result_batches.pop() == [[1]]


def test_expired_clear_budget_keeps_legacy_query_handle(local_cursor):
    with pytest.raises(TimeoutError):
        local_cursor.clear(timeout=0)
    assert local_cursor.query_id == "unissued-local-query"
    assert local_cursor._engine_ip == "127.0.0.1"


def test_close_with_unconfirmed_cleanup_discards_rows_and_keeps_handle(local_cursor):
    local_cursor._result_batches.accept([[[1]]], end_of_stream=False)
    local_cursor.close(timeout=0)
    assert local_cursor.query_id == "unissued-local-query"
    assert local_cursor._cleanup_error is not None
    assert local_cursor._result_batches.pop() is None
    with pytest.raises(ProgrammingError):
        local_cursor.fetchone()


def test_real_unimplemented_v2_falls_back_once_then_failure_is_terminal(generated_server, caplog):
    target, _ = generated_server
    host, port = target.rsplit(":", 1)
    conn = connection(host=host, port=int(port), grpc_options={"grpc_prepare_timeout": 1})
    cursor = conn.cursor()
    cursor._query_id = "unissued-local-query"
    cursor._engine_ip = "127.0.0.1"
    cursor._is_metadata_updated = True
    cursor._query_columns_description = ["value"]
    cursor._result_session_id = "unissued-local-session"
    try:
        with caplog.at_level(logging.DEBUG, logger=engine.__name__):
            with pytest.raises(IncompleteResultError) as caught:
                cursor.fetch_batch()
            assert cursor._result_protocol == "v1"
            with pytest.raises(IncompleteResultError) as repeated:
                cursor.fetch_batch()
        assert repeated.value is caught.value
        attempts = [record for record in caplog.records if hasattr(record, "result_batch_status")]
        assert [record.result_batch_protocol for record in attempts] == ["v2", "v1"]
        assert [record.result_batch_status for record in attempts] == ["unimplemented", "unimplemented"]
        assert all(record.result_batch_rpc_seconds >= 0 for record in attempts)
        assert all(record.result_batch_serialized_bytes == record.result_batch_chunk_count == 0 for record in attempts)
        assert sum(bool(getattr(record, "result_batch_fallback", False)) for record in caplog.records) == 1
        assert cursor.query_id == "unissued-local-query"
    finally:
        conn.close()


@pytest.mark.parametrize("oauth", [False, True])
def test_default_v1_real_rpc_failure_has_metrics_without_fallback(generated_server, caplog, oauth):
    target, _ = generated_server
    host, port = target.rsplit(":", 1)
    auth = dict(username=None, password=None, access_token="local-nonusable-input") if oauth else {}
    conn = connection(host=host, port=int(port), enable_result_batch_v2=False, **auth)
    conn._session_id = "unissued-local-session"
    cursor = conn.cursor()
    cursor._query_id = "unissued-local-query"
    cursor._engine_ip = "127.0.0.1"
    cursor._query_columns_description = ["value"]
    cursor._is_metadata_updated = True
    try:
        with caplog.at_level(logging.DEBUG, logger=engine.__name__):
            with pytest.raises(IncompleteResultError if oauth else grpc.RpcError):
                cursor.fetch_batch()
        attempts = [record for record in caplog.records if hasattr(record, "result_batch_status")]
        assert len(attempts) == 1
        assert attempts[0].result_batch_protocol == "v1"
        assert attempts[0].result_batch_status == "unimplemented"
        assert attempts[0].result_batch_chunk_count == 0
        assert not any(getattr(record, "result_batch_fallback", False) for record in caplog.records)
    finally:
        conn.close()


def test_real_metadata_failure_happens_before_result_consumption(generated_server, caplog):
    target, _ = generated_server
    host, port = target.rsplit(":", 1)
    conn = connection(host=host, port=int(port))
    cursor = conn.cursor()
    cursor._query_id = "unissued-local-query"
    cursor._engine_ip = "127.0.0.1"
    cursor._result_session_id = "unissued-local-session"
    try:
        with caplog.at_level(logging.DEBUG, logger=engine.__name__):
            with pytest.raises(grpc.RpcError):
                cursor.fetch_batch()
        assert cursor._result_failure is None
        assert cursor._result_protocol == "v2"
        assert not any(hasattr(record, "result_batch_status") for record in caplog.records)
    finally:
        conn.close()


def test_result_state_reset_clears_fallback_session_and_pending_data(local_cursor):
    local_cursor._result_protocol = "v1"
    local_cursor._result_batches.accept([[[1]]], end_of_stream=True)
    local_cursor._reset_result_batch_state()
    assert local_cursor._result_protocol == "v2"
    assert local_cursor._result_session_id is None
    assert local_cursor._result_batches.needs_fetch
    assert local_cursor._result_batches.pop() is None


def test_query_option_is_snapshotted_until_result_state_resets(local_cursor):
    local_cursor.connection.enable_result_batch_v2 = False
    assert local_cursor._result_batch_v2_enabled
    local_cursor._reset_result_batch_state()
    assert not local_cursor._result_batch_v2_enabled
    assert local_cursor._result_protocol == "v1"


def test_connection_clear_enforces_opted_in_deadline_before_authentication(local_cursor):
    with pytest.raises(TimeoutError):
        local_cursor.connection.clear(local_cursor.query_id, timeout=0)


def test_cancel_discards_pending_data_even_when_remote_cancel_is_unconfirmed(local_cursor):
    local_cursor._data = [[1]]
    local_cursor._result_batches.accept([[[2]]], end_of_stream=True)
    with pytest.raises(Exception):
        local_cursor.cancel(local_cursor.query_id)
    assert local_cursor._result_failure.reason == "cancelled_result"
    assert local_cursor._result_batches.pop() is None
    assert local_cursor._data is None
    assert local_cursor.query_id == "unissued-local-query"


def test_nonempty_result_session_is_needed_without_reauthentication(local_cursor):
    local_cursor._result_session_id = None
    with pytest.raises(ProgrammingError):
        local_cursor._fetch_session_id()
    assert local_cursor._result_failure is None


@pytest.mark.parametrize("request_type", [pb.ClearOrCancelQueryRequest, pb.CancelQueryRequest,
    pb.StatusRequest, pb.GetResultMetadataRequest, pb.ExplainRequest, pb.ExplainAnalyzeRequest])
@pytest.mark.parametrize("rail", ["v2", "v1", "oauth"])
def test_query_owned_requests_select_the_correct_session(request_type, rail):
    auth = dict(username=None, password=None, access_token="local-nonusable-input") if rail == "oauth" else {}
    conn = connection(enable_result_batch_v2=rail != "v1", **auth)
    conn._session_id = "unissued-connection-session"
    cursor = conn.cursor()
    cursor._query_id, cursor._engine_ip = "unissued-query", "127.0.0.1"
    cursor._result_session_id = "unissued-refreshed-session"
    try:
        request = cursor._query_request(request_type)
        expected = "" if rail == "oauth" else (
            "unissued-refreshed-session" if rail == "v2" else "unissued-connection-session")
        assert request.sessionId == expected
        assert request.queryId == cursor.query_id
        assert request.engineIP == cursor._engine_ip
        assert conn._session_id == "unissued-connection-session"
    finally:
        conn.close()


@pytest.mark.parametrize("protocol", ["v2", "v1"])
@pytest.mark.parametrize("failure", ["corrupt", "expired"])
def test_received_session_survives_decode_failure_for_cleanup(local_cursor, protocol, failure):
    local_cursor._result_protocol = protocol
    value = (pb.GetNextResultBatchV2Response(resultBatches=[b"corrupt"], sessionId="refreshed")
             if protocol == "v2" else
             pb.GetNextResultBatchResponse(resultBatch=b"corrupt", sessionId="refreshed"))
    deadline = time.monotonic() + (1 if failure == "corrupt" else -1)
    with pytest.raises(IncompleteResultError):
        local_cursor._accept_result_batch(value, deadline)
    assert local_cursor._result_session_id == "refreshed"
    assert local_cursor._result_batches.pop() is None
    assert local_cursor._query_request(pb.ClearOrCancelQueryRequest).sessionId == "refreshed"


@pytest.mark.parametrize("protocol", ["v2", "v1"])
def test_cancel_uses_retained_session_without_reauthenticating(generated_server, protocol):
    target, _ = generated_server
    host, port = target.rsplit(":", 1)
    conn = connection(host=host, port=int(port))
    cursor = conn.cursor()
    cursor._query_id, cursor._engine_ip = "unissued-query", "127.0.0.1"
    cursor._result_protocol = protocol
    cursor._result_session_id = "unissued-refreshed-session"
    assert conn._session_id is None
    requests = []
    def observe_rpc(frame, event, arg):
        # Observe the unmodified real gRPC call, without replacing its transport.
        request = frame.f_locals.get("request") if event == "call" else None
        if frame.f_code.co_name == "__call__" and isinstance(request, pb.CancelQueryRequest):
            requests.append(pb.CancelQueryRequest.FromString(request.SerializeToString()))
    previous_profile = sys.getprofile()
    try:
        sys.setprofile(observe_rpc)
        with pytest.raises(grpc.RpcError) as caught:
            cursor.cancel(cursor.query_id)
        sys.setprofile(previous_profile)
        assert caught.value.code() == grpc.StatusCode.UNIMPLEMENTED
        assert [request.sessionId for request in requests] == ["unissued-refreshed-session"]
        assert conn._session_id is None
        assert cursor._result_failure.reason == "cancelled_result"
        assert cursor._result_session_id == "unissued-refreshed-session"
    finally:
        sys.setprofile(previous_profile)
        conn.close()
