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
