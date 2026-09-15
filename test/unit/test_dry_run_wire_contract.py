"""Observe real protobuf requests on native closed channels, with no server double."""
import asyncio
import sys

import pytest

from e6data_python_connector import Connection
from e6data_python_connector.async_connection import AsyncConnection
from e6data_python_connector.server import e6x_engine_pb2 as pb


@pytest.mark.parametrize('native', [False, True])
@pytest.mark.parametrize('catalog', ['', 'configured-catalog'])
def test_dry_run_preserves_catalog_on_native_wire(native, catalog):
    observed = []
    def observe(frame, event, arg):
        if event == 'call':
            request = frame.f_locals.get('request')
            if isinstance(request, (pb.DryRunRequest, pb.DryRunRequestV2)):
                method = frame.f_locals.get('method')
                owner = frame.f_locals.get('self')
                method = getattr(owner, '_method', method)
                if method:
                    observed.append((method, type(request), request.SerializeToString()))

    async def run():
        options = dict(host='localhost', port=1, access_token='local-unusable-input',
                       secure=True, catalog=catalog, database='configured-schema', auto_resume=False)
        connection = (await AsyncConnection(**options).open()) if native else Connection(**options)
        if native:
            await connection._channel.close()
        else:
            connection._channel.close()
        previous = sys.getprofile()
        try:
            sys.setprofile(observe)
            with pytest.raises(Exception):
                if native:
                    await connection.dry_run('SELECT 17', timeout=.05)
                else:
                    connection.dry_run('SELECT 17')
        finally:
            sys.setprofile(previous)
            if native:
                await connection.close()
            else:
                connection.close()
        expected_type = pb.DryRunRequestV2 if catalog else pb.DryRunRequest
        expected_method = 'dryRunV2' if catalog else 'dryRun'
        assert observed
        for method, message_type, payload in observed:
            assert message_type is expected_type
            name = method.decode() if isinstance(method, bytes) else method
            assert name.rsplit('/', 1)[-1] == expected_method
            request = expected_type.FromString(payload)
            assert request.schema == 'configured-schema'
            assert request.queryString == 'SELECT 17'
            assert request.sessionId == ''
            if catalog:
                assert request.catalog == catalog
    asyncio.run(run())
