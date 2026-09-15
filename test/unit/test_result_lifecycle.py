"""Real cursor local-state regressions; no transport doubles or server calls."""
import pytest
import inspect

from e6data_python_connector import Connection
from e6data_python_connector import exceptions


@pytest.fixture
def cursor():
    # Lazy gRPC channel, closed before any operation: these tests must stay local.
    connection = Connection(host='localhost', port=1, access_token='unit-input', require_fastbinary=False)
    cursor = connection.cursor()
    connection.close()
    yield cursor


def test_incomplete_result_blocks_every_fetch_entry_point(cursor):
    assert hasattr(cursor, '_fail_result'), 'Cursor must retain terminal result failure'
    error = cursor._fail_result('ambiguous_result')
    for operation in (cursor.fetch_batch, cursor.fetchone, cursor.fetchmany,
                      cursor.fetchall, lambda: next(cursor.fetchall_buffer())):
        with pytest.raises(exceptions.IncompleteResultError) as caught:
            operation()
        assert caught.value is error


def test_fetchall_preserves_rows_buffered_before_eof(cursor):
    assert hasattr(cursor, '_result_exhausted'), 'EOF must be remembered without another RPC'
    cursor._result_exhausted = True
    cursor._data = [[1], [2], [3]]
    assert cursor.fetchone() == [[1]]
    assert cursor.fetchall() == [[2], [3]]
    assert cursor.fetchall() == []


def test_failure_preserves_known_handle_and_safe_category(cursor):
    assert hasattr(exceptions, 'IncompleteResultError')
    cursor._query_id = 'unit-query'
    error = cursor._fail_result('decode_failed')
    assert error.query_id == 'unit-query'
    assert cursor._query_id == 'unit-query'
    assert isinstance(error, exceptions.OperationalError)
    assert str(error) == 'decode_failed'


def test_exception_rejects_unbounded_reason_text():
    assert hasattr(exceptions, 'IncompleteResultError')
    error = exceptions.IncompleteResultError('arbitrary potentially sensitive server text', query_id='unit-query')
    assert 'sensitive' not in str(error)


def test_expired_clear_budget_keeps_handle_without_dispatch(cursor):
    assert 'timeout' in inspect.signature(cursor.clear).parameters
    cursor._query_id, cursor._engine_ip = 'unit-query', 'unit-planner'
    with pytest.raises(TimeoutError):
        cursor.clear(timeout=0)
    assert cursor._query_id == 'unit-query'
    assert cursor._engine_ip == 'unit-planner'


def test_expired_connection_clear_budget_does_not_touch_channel(cursor):
    assert 'timeout' in inspect.signature(cursor.connection.clear).parameters
    with pytest.raises(TimeoutError):
        cursor.connection.clear('unit-query', timeout=0)


def test_close_keeps_diagnostics_when_cleanup_cannot_finish(cursor):
    assert 'timeout' in inspect.signature(cursor.close).parameters
    cursor._query_id, cursor._engine_ip = 'unit-query', 'unit-planner'
    cursor.close(timeout=0)
    assert cursor.query_id == 'unit-query'
    assert cursor._engine_ip == 'unit-planner'
    assert cursor._cleanup_error is not None
    with pytest.raises(exceptions.ProgrammingError):
        cursor.fetchone()


def test_execute_cannot_abandon_a_failed_oauth_query(cursor):
    cursor._query_id = 'unit-query'
    cursor._fail_result('ambiguous_result')
    with pytest.raises(exceptions.IncompleteResultError):
        cursor.execute('select 1')
    assert cursor._query_id == 'unit-query'
