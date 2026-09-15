"""Pure SQL compilation, scalar conversion and production cursor/cache state."""
import copy
import datetime
from decimal import Decimal
import time

import pytest
from sqlalchemy import column, func, insert, table, types
from sqlalchemy.engine import make_url

from e6data_python_connector import Connection, e6data_grpc, strategy
from e6data_python_connector.dialect import E6dataDate, E6dataTimestamp, E6dataDecimal, E6dataDialect
from e6data_python_connector.exceptions import NotSupportedError, ProgrammingError


@pytest.mark.parametrize("typ,value,expected", [
    (E6dataDate, datetime.datetime(2001, 2, 3, 4, 5), datetime.date(2001, 2, 3)),
    (E6dataDate, datetime.date(2001, 2, 3), datetime.date(2001, 2, 3)),
    (E6dataDate, "2001-02-03", datetime.date(2001, 2, 3)),
    (E6dataTimestamp, datetime.datetime(2001, 2, 3, 4, 5), datetime.datetime(2001, 2, 3, 4, 5)),
    (E6dataTimestamp, "2001-02-03T04:05:06", datetime.datetime(2001, 2, 3, 4, 5, 6)),
    (E6dataDecimal, Decimal("123456789.00000000001"), Decimal("123456789.00000000001")),
    (E6dataDecimal, "123456789.00000000001", Decimal("123456789.00000000001")),
    (E6dataDate, None, None), (E6dataTimestamp, None, None), (E6dataDecimal, None, None),
])
def test_result_processors_preserve_scalar_types_and_precision(typ, value, expected):
    instance = typ()
    assert instance.result_processor(E6dataDialect(), None)(value) == expected
    assert isinstance(instance.adapt(types.String), type(instance.impl))
    with pytest.raises(NotImplementedError):
        instance.process_bind_param(value, E6dataDialect())


@pytest.mark.parametrize("typ,value,expected", [
    (E6dataDate, "2001-02-03", datetime.date(2001, 2, 3)),
    (E6dataTimestamp, "2001-02-03 04:05:06", datetime.datetime(2001, 2, 3, 4, 5, 6)),
    (E6dataDecimal, "1.00000000001", Decimal("1.00000000001")),
    (E6dataDecimal, None, None),
])
def test_direct_scalar_conversion(typ, value, expected):
    assert typ().process_result_value(value, E6dataDialect()) == expected


@pytest.mark.parametrize("typ,expected", [
    (types.INTEGER(), "INT"), (types.NUMERIC(), "DECIMAL"),
    (types.CHAR(), "STRING"), (types.VARCHAR(), "STRING"), (types.NCHAR(), "STRING"),
    (types.TEXT(), "STRING"), (types.CLOB(), "STRING"), (types.BLOB(), "BINARY"),
    (types.TIME(), "TIMESTAMP"), (types.DATE(), "DATE"), (types.DATETIME(), "TIMESTAMP"),
])
def test_sql_type_compilation(typ, expected):
    assert typ.compile(dialect=E6dataDialect()) == expected


def test_readonly_sql_compiler_functions_and_insert_rejection():
    dialect = E6dataDialect()
    name = column("name", types.String)
    expression = (name + column("suffix", types.String)).compile(dialect=dialect)
    assert str(expression) == 'concat("name", "suffix")'
    assert str(func.char_length(name).compile(dialect=dialect)) == 'length("name")'
    with pytest.raises(NotSupportedError):
        insert(table("items", name)).values(name="a").compile(dialect=dialect)


def test_sync_url_defaults_and_explicit_options():
    dialect = E6dataDialect()
    with pytest.raises(Exception, match="specify catalog"):
        dialect.create_connect_args(make_url("e6data://localhost"))
    args, options = dialect.create_connect_args(make_url("e6data://localhost:443?catalog=cat"))
    assert args == []
    assert options == dict(host="localhost", port=443, scheme="e6data", username=None,
                           password=None, database=None, catalog="cat", cluster_name=None,
                           secure=False, auto_resume=True, grpc_options={}, debug=False)
    _, options = dialect.create_connect_args(make_url(
        "e6data://user:unit-input@localhost:443?catalog=cat&schema=db&secure=true&auto-resume=false&grpc.keepalive_time_ms=123"))
    assert options["database"] == "db"
    assert options["username"] == "user"
    assert options["password"] == "unit-input"
    assert options["secure"] is True
    assert options["auto_resume"] is False
    assert options["grpc_options"] == {"grpc.keepalive_time_ms": "123"}


@pytest.mark.parametrize("module", [strategy, e6data_grpc])
def test_strategy_cleanup_waits_for_last_query_before_adopting_pending(module):
    shared = module._get_shared_strategy()
    original = copy.deepcopy(dict(shared))
    try:
        module._clear_strategy_cache()
        module._set_active_strategy("BLUE")
        module._register_query_strategy("one", "blue")
        module._register_query_strategy("two", "blue")
        module._set_pending_strategy("GREEN")
        before = time.time()
        if module is strategy:
            module._unregister_query_strategy("one")
            module._apply_pending_strategy()
        else:
            module._finish_query_cleanup("one", "GREEN", time.monotonic() + 1)
        assert module._get_active_strategy() == "blue"
        assert module._get_query_strategy("two") == "blue"
        assert shared["pending_strategy"] == "green"
        if module is strategy:
            module._unregister_query_strategy("absent")
            module._unregister_query_strategy("two")
            module._apply_pending_strategy()
        else:
            module._finish_query_cleanup("absent", "invalid", time.monotonic() + 1)
            module._finish_query_cleanup("two", None, time.monotonic() + 1)
        assert module._get_active_strategy() == "green"
        assert shared["pending_strategy"] is None
        assert shared["query_strategy_map"] == {}
        assert shared["session_invalidated"] is True
        assert before <= shared["last_transition_time"] <= time.time()
        module._set_pending_strategy("green")
        assert shared["pending_strategy"] is None
        module._set_pending_strategy("invalid")
        module._set_active_strategy("invalid")
        assert shared["pending_strategy"] is None
        assert module._get_active_strategy() == "green"
        module._set_pending_strategy(None)
        module._set_active_strategy(None)
        # The standalone manager accepts None as reset; the sync RPC cache
        # ignores absent hints and has a separate explicit reset operation.
        assert module._get_active_strategy() == (None if module is strategy else "green")
        module._clear_strategy_cache()
        assert module._get_active_strategy() is None
    finally:
        shared.clear()
        shared.update(original)


def test_oauth_buffered_cursor_consumes_once_without_dispatch():
    connection = Connection(host="localhost", port=1, access_token="unit-input", require_fastbinary=False)
    cursor = connection.cursor()
    connection.close()  # A subsequent accidental dispatch would fail this test.
    cursor.arraysize = "3"
    assert cursor.arraysize == 3
    with pytest.raises(ValueError):
        cursor.arraysize = "invalid"
    assert cursor.arraysize == 3
    for size in (None, 0):
        cursor.arraysize = size
        assert cursor.arraysize == 1000
    cursor._result_exhausted, cursor._query_id = True, "query-one"
    cursor._data = [[1], [2]]
    with pytest.raises(ValueError, match="Cannot replace"):
        list(cursor.fetchall_buffer(query_id="query-two"))
    assert cursor._query_id == "query-one"
    assert cursor._data == [[1], [2]]
    assert list(cursor.fetchall_buffer(query_id="query-one")) == [[[1], [2]]]
    assert list(cursor.fetchall_buffer()) == []
    assert cursor._data is None
    cursor._query_id = None
    assert cursor.clear(timeout=1) is None
    cursor.close(timeout=1)
    cursor.close(timeout=1)
    with pytest.raises(ProgrammingError):
        cursor.fetchone()
