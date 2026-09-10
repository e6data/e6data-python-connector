"""Read-only authentication rejection against the configured real receiver."""
import asyncio

import grpc
import pytest

from e6data_python_connector.aio import AsyncConnection
from e6data_python_connector.server import e6x_engine_pb2 as pb


def test_real_discovery_rejects_missing_bearer(live_config):
    async def run():
        options = dict(live_config.connection_kwargs)
        options.update(auto_resume=False, operation_timeout=10, cleanup_timeout=5)
        async with asyncio.timeout(20):
            async with AsyncConnection(**options) as connection:
                # Use the actual TLS transport, intentionally omit authorization.
                metadata = [('strategy', connection._strategy)]
                if connection.cluster_name:
                    metadata.append(('cluster-name', connection.cluster_name))
                with pytest.raises(grpc.aio.AioRpcError) as rejected:
                    await connection._client.getSchemaNamesV2(
                        pb.GetSchemaNamesV2Request(catalog=connection.catalog or ''),
                        metadata=metadata, timeout=10,
                    )
                # This receiver preserves the legacy no-bearer session path,
                # which reports this exact denial as INTERNAL. Other INTERNAL
                # errors do not establish an authentication rejection.
                assert (
                    rejected.value.code() == grpc.StatusCode.UNAUTHENTICATED
                    or (rejected.value.code() == grpc.StatusCode.INTERNAL
                        and rejected.value.details() == 'Access denied')
                )
    asyncio.run(run())
