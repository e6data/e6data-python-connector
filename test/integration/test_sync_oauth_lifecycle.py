"""Configured real-service sync control; never executes a credential script."""
from e6data_python_connector import Connection


def test_real_sync_query_and_buffer_continuity(live_config):
    kwargs = dict(live_config.connection_kwargs)
    kwargs['auto_resume'] = False
    with Connection(**kwargs) as connection:
        with connection.cursor() as cursor:
            assert cursor.execute(live_config.read_only_sql)
            first = cursor.fetchone() or []
            rest = cursor.fetchall()
            assert first + rest == live_config.expected_rows


def test_real_sync_metadata_control(live_config):
    kwargs = dict(live_config.connection_kwargs)
    kwargs['auto_resume'] = False
    with Connection(**kwargs) as connection:
        assert isinstance(connection.get_schema_names(connection.catalog_name), list)
