"""Real HTTPX failure and disposal against a bound, non-listening local socket."""
import asyncio
import socket
import time

import pytest

from e6data_python_connector.async_oauth import AsyncClientCredentialsTokenProvider
from e6data_python_connector.exceptions import OAuthError


@pytest.mark.parametrize("method", ["basic", "post"])
def test_failed_real_https_exchange_can_retry_and_closes_owned_transport(method):
    # Reserving an ephemeral port prevents another process from serving it.
    # This socket never listens, accepts connections, or simulates an endpoint.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]

        async def run():
            provider = AsyncClientCredentialsTokenProvider(
                f"https://127.0.0.1:{port}/token", "unit-id", "unit-input",
                client_auth_method=method, scope="query:read", timeout=2,
            )
            try:
                tasks = []
                for _ in range(2):
                    with pytest.raises((OAuthError, TimeoutError)) as error:
                        await provider.get_token(deadline=time.monotonic() + 5)
                    # Some hosts reject a non-listening port immediately; others
                    # discard connection attempts. Both must fail within the owned
                    # exchange deadline and leave no reusable credential.
                    if isinstance(error.value, OAuthError):
                        assert str(error.value) == "Could not reach the OAuth token endpoint."
                        assert error.value.__suppress_context__
                    assert provider._access_token is None
                    assert provider._expires_at == 0
                    assert provider._waiters == 0
                    tasks.append(provider._task)
                    # Do not await transport cleanup before the next explicit
                    # attempt: a fresh caller must be able to wait for retirement
                    # without inheriting the previous phase's expired deadline.
                assert tasks[0] is not tasks[1]
                async with asyncio.timeout(1):
                    await asyncio.shield(asyncio.gather(*tasks, return_exceptions=True))
                assert all(task.done() for task in tasks)
                assert provider._state._flight is None
                assert not provider._state._waiters
                assert provider._client is not None
                assert not provider._client.is_closed
            finally:
                await provider.close(deadline=time.monotonic() + 5)
            assert provider._client.is_closed
            assert provider._close_task.done()
            await provider.close()
            with pytest.raises(OAuthError, match="closed"):
                await provider.get_token()

        asyncio.run(run())


def test_unknown_client_auth_method_rejected_before_creating_transport():
    with pytest.raises(ValueError, match="basic.*post"):
        AsyncClientCredentialsTokenProvider(
            "https://localhost/token", "unit-id", "unit-input", client_auth_method="invalid"
        )
