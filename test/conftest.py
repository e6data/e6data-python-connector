"""Fixtures shared by opt-in real-service integration tests."""

import pytest

from test.integration.support import IntegrationConfigError, load_integration_config


@pytest.fixture(scope="session")
def live_config(pytestconfig):
    """Return validated live settings only when an explicit path was supplied."""

    path = pytestconfig.getoption("--integration-config")
    if not path:
        pytest.skip("Real-service qualification requires --integration-config")
    try:
        return load_integration_config(path)
    except IntegrationConfigError as exc:
        raise pytest.UsageError(f"invalid --integration-config: {exc}") from exc
