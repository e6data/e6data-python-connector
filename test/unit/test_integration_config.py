import json

import pytest

from test.conftest import live_config as live_config_fixture
from test.integration.support import IntegrationConfigError, load_integration_config


def write_config(tmp_path, **overrides):
    config = {
        "target_id": "qualification-cluster",
        "package_id": "connector-candidate",
        "target_version": "target-build-1",
        "package_version": "1.2.3",
        "connection_kwargs": {
            "host": "query.example.test",
            "port": 443,
            "client_id": {"env": "E6_TEST_CLIENT_ID"},
            "client_secret": {"env": "E6_TEST_CLIENT_SECRET"},
        },
        "read_only_sql": "SELECT 1",
        "expected_rows": [[1]],
        "fault_proxy": {"listen_host": "127.0.0.1", "listen_port": 0},
    }
    config.update(overrides)
    path = tmp_path / "integration.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_loads_public_live_config_and_resolves_external_credentials(tmp_path):
    path = write_config(tmp_path)

    live = load_integration_config(
        path,
        environ={
            "E6_TEST_CLIENT_ID": "operator-client",
            "E6_TEST_CLIENT_SECRET": "operator-secret",
        },
    )

    assert live.target_id == "qualification-cluster"
    assert live.package_id == "connector-candidate"
    assert live.target_metadata == {"id": "qualification-cluster", "version": "target-build-1"}
    assert live.package_metadata == {"id": "connector-candidate", "version": "1.2.3"}
    assert live.connection_kwargs == {
        "host": "query.example.test",
        "port": 443,
        "client_id": "operator-client",
        "client_secret": "operator-secret",
    }
    assert live.read_only_sql == "SELECT 1"
    assert live.expected_rows == [[1]]
    assert live.fault_proxy_config == {
        "listen_host": "127.0.0.1",
        "listen_port": 0,
    }


@pytest.mark.parametrize(
    "missing_key",
    (
        "target_id",
        "package_id",
        "connection_kwargs",
        "read_only_sql",
        "expected_rows",
    ),
)
def test_rejects_missing_required_values_before_use(tmp_path, missing_key):
    path = write_config(tmp_path)
    config = json.loads(path.read_text(encoding="utf-8"))
    del config[missing_key]
    path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(IntegrationConfigError, match=missing_key):
        load_integration_config(path, environ={})


def test_fault_proxy_is_optional_for_ordinary_live_qualification(tmp_path):
    path = write_config(tmp_path)
    config = json.loads(path.read_text(encoding="utf-8"))
    del config["fault_proxy"]
    path.write_text(json.dumps(config), encoding="utf-8")

    live = load_integration_config(
        path,
        environ={
            "E6_TEST_CLIENT_ID": "operator-client",
            "E6_TEST_CLIENT_SECRET": "operator-secret",
        },
    )

    assert live.fault_proxy_config is None


def test_rejects_missing_credential_environment_variable(tmp_path):
    path = write_config(tmp_path)

    with pytest.raises(IntegrationConfigError) as raised:
        load_integration_config(path, environ={"E6_TEST_CLIENT_ID": "present"})

    assert "E6_TEST_CLIENT_SECRET" in str(raised.value)
    assert "operator-client" not in str(raised.value)


@pytest.mark.parametrize("key", ("password", "access_token", "client_secret"))
def test_rejects_literal_credentials_in_repository_config(tmp_path, key):
    path = write_config(
        tmp_path,
        connection_kwargs={"host": "query.example.test", key: "literal-secret"},
    )

    with pytest.raises(IntegrationConfigError) as raised:
        load_integration_config(path, environ={})

    assert key in str(raised.value)
    assert "literal-secret" not in str(raised.value)


def test_loaded_config_representation_does_not_disclose_credentials(tmp_path):
    path = write_config(tmp_path)

    live = load_integration_config(
        path,
        environ={
            "E6_TEST_CLIENT_ID": "operator-client",
            "E6_TEST_CLIENT_SECRET": "operator-secret",
        },
    )

    rendered = repr(live)
    assert "operator-client" not in rendered
    assert "operator-secret" not in rendered
    assert "qualification-cluster" in rendered


def test_rejects_unknown_connection_setting(tmp_path):
    path = write_config(
        tmp_path,
        connection_kwargs={
            "host": "query.example.test",
            "port": 443,
            "invented_setting": True,
        },
    )

    with pytest.raises(IntegrationConfigError, match="invented_setting"):
        load_integration_config(path, environ={})


@pytest.mark.parametrize(
    ("read_only_sql", "message"),
    (("DELETE FROM t", "read_only_sql"), ("", "read_only_sql")),
)
def test_rejects_non_read_only_or_empty_sql(tmp_path, read_only_sql, message):
    path = write_config(tmp_path, read_only_sql=read_only_sql)

    with pytest.raises(IntegrationConfigError, match=message):
        load_integration_config(path, environ={})


class OptionConfig:
    def __init__(self, integration_config):
        self.integration_config = integration_config

    def getoption(self, name):
        assert name == "--integration-config"
        return self.integration_config


def test_live_fixture_skips_without_explicit_path():
    with pytest.raises(pytest.skip.Exception, match="requires --integration-config"):
        live_config_fixture.__wrapped__(OptionConfig(None))


def test_live_fixture_reports_invalid_config_as_usage_error(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(pytest.UsageError, match="invalid --integration-config"):
        live_config_fixture.__wrapped__(OptionConfig(path))


def test_rejects_non_object_json_without_echoing_file_contents(tmp_path):
    path = tmp_path / "integration.json"
    path.write_text(json.dumps(["sensitive-test-input"]), encoding="utf-8")

    with pytest.raises(IntegrationConfigError) as raised:
        load_integration_config(path, environ={})

    assert "JSON object" in str(raised.value)
    assert "sensitive-test-input" not in str(raised.value)


@pytest.mark.parametrize("enabled", [False, True])
def test_result_batch_v2_option_reaches_live_connection(tmp_path, enabled):
    path = write_config(tmp_path, connection_kwargs={
        "host": "localhost", "port": 1, "enable_result_batch_v2": enabled,
    })
    assert load_integration_config(path, environ={}).connection_kwargs["enable_result_batch_v2"] is enabled


@pytest.mark.parametrize("enabled", ["true", 1, None])
def test_result_batch_v2_live_option_requires_actual_boolean(tmp_path, enabled):
    path = write_config(tmp_path, connection_kwargs={
        "host": "localhost", "port": 1, "enable_result_batch_v2": enabled,
    })
    with pytest.raises(IntegrationConfigError, match="boolean"):
        load_integration_config(path, environ={})
