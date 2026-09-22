"""Admission and ownership contracts using real standard-library futures."""

import asyncio
import concurrent.futures
import gc
import weakref
import os
import logging
from types import SimpleNamespace

import pytest

from e6data_python_connector.result_prefetch import PendingFetch, reserve_prefetch
from e6data_python_connector.server import e6x_engine_pb2 as pb
from e6data_python_connector import result_prefetch as prefetch


def test_continuous_stream_retains_more_than_four_envelopes_in_order():
    stream = prefetch.ContinuousResultStream(session_id='initial')
    responses = [pb.GetNextResultBatchV2Response(
        sessionId=str(i), resultBatches=[bytes([i])], endOfStream=i == 9)
        for i in range(10)]
    for i, response in enumerate(responses):
        stream.push(response, i / 10)
    assert stream.queued_count == 10
    assert stream.queued_bytes == sum(r.ByteSize() for r in responses)
    assert stream.session_id == '9'
    for i, response in enumerate(responses):
        assert stream.take() is response
        assert stream.elapsed == i / 10
        assert stream.session_id == '9'
    assert stream.queued_count == 0
    assert stream.queued_bytes == 0


def test_continuous_error_follows_downloaded_responses_without_wrapping():
    stream = prefetch.ContinuousResultStream()
    response = pb.GetNextResultBatchV2Response(resultBatches=[b'data'])
    error = ValueError('original transport failure')
    stream.push(response, .1)
    stream.fail(error, .2)
    stream.finish()
    assert stream.take() is response
    with pytest.raises(ValueError) as caught:
        stream.take()
    assert caught.value is error
    assert stream.elapsed == .2


def test_continuous_wait_wakes_on_response_and_times_out_without_one():
    import threading
    stream = prefetch.ContinuousResultStream()
    response = pb.GetNextResultBatchV2Response(endOfStream=True)
    thread = threading.Thread(target=lambda: stream.push(response, .1))
    thread.start()
    stream.wait(1)
    thread.join(1)
    assert stream.take() is response
    with pytest.raises(TimeoutError):
        stream.wait(0)


def test_continuous_retirement_releases_all_queued_payload_references():
    import sys
    stream = prefetch.ContinuousResultStream()
    response = pb.GetNextResultBatchV2Response(resultBatches=[b'payload'])
    initial_references = sys.getrefcount(response)
    for _ in range(10):
        stream.push(response, .1)
    assert sys.getrefcount(response) > initial_references
    stream.retire()
    assert stream.retired
    assert stream.queued_count == stream.queued_bytes == 0
    assert sys.getrefcount(response) == initial_references
    stream.push(response, .2)
    assert stream.queued_count == 0
    with pytest.raises(RuntimeError):
        stream.take()


def test_continuous_retirement_keeps_late_session_until_actual_settlement():
    stream = prefetch.ContinuousResultStream(session_id='initial')
    producer = concurrent.futures.Future()
    transport = concurrent.futures.Future()
    producer.set_running_or_notify_cancel()
    transport.set_running_or_notify_cancel()
    stream.set_handle(producer)
    stream.set_transport(transport)
    stream.retire()
    assert not stream.settled
    response = pb.GetNextResultBatchV2Response(sessionId='latest')
    transport.set_result(response)
    assert stream.session_id == 'latest'
    assert not stream.settled
    producer.set_result(None)
    assert stream.settled
    assert stream.queued_count == 0
    assert stream.handle is None


def test_continuous_retirement_before_handle_attachment_cancels_new_work():
    stream = prefetch.ContinuousResultStream()
    stream.retire()
    producer = concurrent.futures.Future()
    transport = concurrent.futures.Future()
    stream.set_handle(producer)
    stream.set_transport(transport)
    assert producer.cancelled()
    assert transport.cancelled()
    assert stream.settled


def test_continuous_finished_producer_does_not_discard_buffered_results():
    stream = prefetch.ContinuousResultStream()
    producer = concurrent.futures.Future()
    stream.set_handle(producer)
    response = pb.GetNextResultBatchV2Response(endOfStream=True, sessionId='latest')
    stream.push(response, .1)
    stream.finish()
    producer.set_result(None)
    assert stream.settled
    assert stream.ready
    assert stream.take() is response


def test_continuous_notifications_cover_data_failure_finish_and_retire():
    states = []
    stream = prefetch.ContinuousResultStream(notify=lambda: states.append(True))
    stream.push(pb.GetNextResultBatchV2Response(), .1)
    stream.fail(ValueError('failed'), .2)
    stream.finish()
    stream.retire()
    assert len(states) >= 4


def test_continuous_transport_completion_does_not_regress_newer_session():
    stream = prefetch.ContinuousResultStream(session_id='initial')
    one = concurrent.futures.Future()
    stream.set_transport(one)
    first = pb.GetNextResultBatchV2Response(sessionId='one')
    one.set_result(first)
    stream.push(first, .1)
    stream.clear_transport(one)
    two = concurrent.futures.Future()
    stream.set_transport(two)
    second = pb.GetNextResultBatchV2Response(sessionId='two')
    two.set_result(second)
    stream.push(second, .2)
    assert stream.take() is first
    assert stream.session_id == 'two'
    stream.retire()
    assert stream.session_id == 'two'


def test_continuous_rejects_two_unsettled_transports():
    stream = prefetch.ContinuousResultStream()
    one = concurrent.futures.Future()
    one.set_running_or_notify_cancel()
    stream.set_transport(one)
    with pytest.raises(RuntimeError):
        stream.set_transport(concurrent.futures.Future())
    stream.retire()
    one.set_result(pb.GetNextResultBatchV2Response())


def test_continuous_debug_reports_queue_size_without_payload(caplog):
    with caplog.at_level(logging.DEBUG):
        stream = prefetch.ContinuousResultStream(session_id='private-session')
        stream.push(pb.GetNextResultBatchV2Response(
            resultBatches=[b'private-row']), .1)
        stream.finish()
        stream.retire()
    assert any(hasattr(r, 'result_batch_queued_envelopes') for r in caplog.records)
    assert 'private-session' not in caplog.text
    assert 'private-row' not in caplog.text


def pending(future=None):
    future = future or concurrent.futures.Future()
    permit = reserve_prefetch()
    assert permit is not None
    return PendingFetch(future, permit, session_id='old', deadline=123), future


def test_completed_response_holds_capacity_until_taken():
    records = [pending() for _ in range(4)]
    try:
        assert reserve_prefetch() is None
        response = SimpleNamespace(sessionId='new')
        records[0][1].set_result(response)
        assert records[0][0].settled
        assert records[0][0].session_id == 'new'
        assert reserve_prefetch() is None
        assert records[0][0].take() is response
        permit = reserve_prefetch()
        assert permit is not None
        permit.release()
        with pytest.raises(RuntimeError):
            records[0][0].take()
    finally:
        for record, _ in records:
            record.retire()


@pytest.mark.parametrize('complete_first', [False, True])
def test_retirement_drops_transport_payload_before_releasing_capacity(complete_first):
    record, future = pending()
    future.set_running_or_notify_cancel()
    response = pb.GetNextResultBatchV2Response(
        resultBatches=[b'x' * 1024], sessionId='retired-session')
    transport_reference = weakref.ref(future)
    if complete_first:
        future.set_result(response)
    record.retire()
    if not complete_first:
        future.set_result(response)
    del future, response
    gc.collect()
    assert record.settled
    assert record.session_id == 'retired-session'
    assert record.handle is None
    assert transport_reference() is None
    permits = [reserve_prefetch() for _ in range(4)]
    try:
        assert all(permits)
    finally:
        for permit in permits:
            if permit is not None:
                permit.release()


def test_original_exception_is_raised_only_at_consumption():
    record, future = pending()
    error = ValueError('original')
    future.set_exception(error)
    assert record.settled
    with pytest.raises(ValueError) as caught:
        record.take()
    assert caught.value is error
    record.retire()


def test_retirement_keeps_capacity_until_transport_really_settles():
    records = [pending() for _ in range(4)]
    record, future = records[0]
    future.set_running_or_notify_cancel()
    record.retire()
    assert not record.settled
    assert reserve_prefetch() is None
    future.set_result(SimpleNamespace(sessionId='late'))
    assert record.settled
    assert record.session_id == 'late'
    with pytest.raises(RuntimeError):
        record.take()
    permit = reserve_prefetch()
    assert permit is not None
    permit.release()
    for item, _ in records:
        item.retire()


def test_cancel_before_start_and_repeated_retirement_release_once():
    record, future = pending()
    record.retire()
    record.retire()
    assert future.cancelled()
    assert record.settled
    permits = [reserve_prefetch() for _ in range(4)]
    assert all(permits)
    assert reserve_prefetch() is None
    for permit in permits:
        permit.release()
        permit.release()


def test_take_before_completion_does_not_lose_response():
    record, future = pending()
    with pytest.raises(RuntimeError):
        record.take()
    future.set_result(SimpleNamespace(sessionId=''))
    assert record.session_id == 'old'
    assert record.elapsed >= 0
    record.take()


def test_future_already_completed_is_captured_on_construction():
    future = concurrent.futures.Future()
    future.set_result(SimpleNamespace(sessionId='ready'))
    record, _ = pending(future)
    assert record.session_id == 'ready'
    record.take()


def test_foreground_record_needs_no_speculative_permit():
    future = concurrent.futures.Future()
    record = PendingFetch(future, None, session_id='old')
    response = SimpleNamespace(sessionId='new')
    future.set_result(response)
    assert record.take() is response
    record.retire()
    assert record.session_id == 'new'


def test_debug_metrics_report_retained_bytes_and_discard_without_payload(caplog):
    with caplog.at_level(logging.DEBUG):
        record, future = pending()
        response = pb.GetNextResultBatchV2Response(
            sessionId='private-session-marker', resultBatches=[b'private-row-marker'])
        future.set_result(response)
        record.retire()
    completed = next(item for item in caplog.records
                     if getattr(item, 'result_batch_prefetch_event', '') == 'completed')
    retired = next(item for item in caplog.records
                   if getattr(item, 'result_batch_prefetch_event', '') == 'retired')
    assert completed.result_batch_pending_protobuf_bytes == response.ByteSize()
    assert completed.result_batch_prefetch_inflight == 0
    assert completed.result_batch_prefetch_retained == 1
    assert retired.result_batch_prefetch_discarded == 1
    assert 'private-session-marker' not in caplog.text
    assert 'private-row-marker' not in caplog.text


def test_retired_late_failure_logs_settlement_without_exception_details(caplog):
    with caplog.at_level(logging.DEBUG):
        record, future = pending()
        future.set_running_or_notify_cancel()
        record.retire()
        future.set_exception(ValueError('private-error-marker'))
    completed = next(item for item in caplog.records
                     if getattr(item, 'result_batch_prefetch_event', '') == 'completed')
    assert completed.result_batch_prefetch_status == 'error'
    assert completed.result_batch_prefetch_retained == 0
    assert 'private-error-marker' not in caplog.text


def test_async_task_records_outcome_before_owner_consumes_it():
    async def run():
        gate = asyncio.Event()
        async def transport():
            await gate.wait()
            return SimpleNamespace(sessionId='async')
        task = asyncio.create_task(transport())
        record, _ = pending(task)
        gate.set()
        response = await task
        assert record.take() is response
        assert record.session_id == 'async'
    asyncio.run(run())


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='requires fork')
def test_inherited_record_fails_without_touching_parent_locks():
    record, _ = pending()
    pid = os.fork()
    if pid == 0:
        try:
            with pytest.raises(RuntimeError):
                record.retire()
            permits = [reserve_prefetch() for _ in range(4)]
            assert all(permits)
            for permit in permits:
                permit.release()
        except BaseException:
            os._exit(1)
        os._exit(0)
    _, status = os.waitpid(pid, 0)
    record.retire()
    assert os.waitstatus_to_exitcode(status) == 0
