"""Safe loading for explicitly supplied real-service test configuration.

Credential values are named environment-variable references in JSON, for example
``{"env": "E6_TEST_CLIENT_SECRET"}``. The loader resolves them only when the
integration fixture is requested.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class IntegrationConfigError(ValueError):
    """The integration configuration is absent or unsafe to use."""


_REQUIRED_FIELDS = (
    "target_id",
    "package_id",
    "connection_kwargs",
    "read_only_sql",
    "expected_rows",
)

_CONNECTION_SETTINGS = frozenset(
    {
        "host",
        "port",
        "username",
        "password",
        "catalog",
        "database",
        "cluster_name",
        "secure",
        "ssl_cert",
        "auto_resume",
        "scheme",
        "grpc_options",
        "debug",
        "require_fastbinary",
        "client_id",
        "client_secret",
        "token_url",
        "oauth_scope",
        "access_token",
        "client_auth_method",
        "enable_result_batch_v2",
    }
)

_CREDENTIAL_SETTINGS = frozenset({"password", "client_id", "client_secret", "access_token"})
_READ_ONLY_SQL = re.compile(r"^\s*(?:select|with|show|describe|desc|explain)\b", re.IGNORECASE)


@dataclass(frozen=True, repr=False)
class LiveConfig:
    """Validated values used by opt-in real-service integration tests."""

    connection_kwargs: Mapping[str, Any]
    read_only_sql: str
    expected_rows: list[Any]
    fault_proxy_config: Mapping[str, Any] | None
    target_id: str
    package_id: str
    target_version: str | None = None
    package_version: str | None = None
    schema_name: str | None = None

    @property
    def target_metadata(self) -> Mapping[str, str | None]:
        return {"id": self.target_id, "version": self.target_version}

    @property
    def package_metadata(self) -> Mapping[str, str | None]:
        return {"id": self.package_id, "version": self.package_version}

    def __repr__(self) -> str:
        return (
            "LiveConfig("
            f"target_id={self.target_id!r}, package_id={self.package_id!r}, "
            f"target_version={self.target_version!r}, package_version={self.package_version!r}, "
            "connection_kwargs=<redacted>)"
        )


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntegrationConfigError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _nonempty_string(value, field)


def _environment_reference(value: Any, field: str, environ: Mapping[str, str]) -> str:
    if not isinstance(value, dict) or set(value) != {"env"}:
        raise IntegrationConfigError(f"connection_kwargs.{field} must use an environment reference")
    variable = _nonempty_string(value["env"], f"connection_kwargs.{field}.env")
    resolved = environ.get(variable)
    if not resolved:
        raise IntegrationConfigError(f"environment variable {variable} is required")
    return resolved


def _connection_kwargs(raw: Any, environ: Mapping[str, str]) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw:
        raise IntegrationConfigError("connection_kwargs must be a non-empty object")
    unknown = sorted(set(raw) - _CONNECTION_SETTINGS)
    if unknown:
        raise IntegrationConfigError(f"connection_kwargs contains unsupported setting: {unknown[0]}")

    resolved: dict[str, Any] = {}
    for key, value in raw.items():
        if key in _CREDENTIAL_SETTINGS:
            resolved[key] = _environment_reference(value, key, environ)
        elif isinstance(value, dict) and set(value) == {"env"}:
            resolved[key] = _environment_reference(value, key, environ)
        else:
            resolved[key] = value
    if not resolved.get("host") or not resolved.get("port"):
        raise IntegrationConfigError("connection_kwargs requires host and port")
    if "enable_result_batch_v2" in resolved and not isinstance(resolved["enable_result_batch_v2"], bool):
        raise IntegrationConfigError("enable_result_batch_v2 must be a boolean")
    return resolved


def load_integration_config(
    path: str | os.PathLike[str], environ: Mapping[str, str] | None = None
) -> LiveConfig:
    """Load and validate one explicit JSON path without initiating network I/O."""

    if not path:
        raise IntegrationConfigError("an explicit integration config path is required")
    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise IntegrationConfigError(f"cannot read integration config path: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise IntegrationConfigError("integration config is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise IntegrationConfigError("integration config must be a JSON object")
    for field in _REQUIRED_FIELDS:
        if field not in raw:
            raise IntegrationConfigError(f"integration config is missing {field}")

    query = _nonempty_string(raw["read_only_sql"], "read_only_sql")
    if not _READ_ONLY_SQL.match(query):
        raise IntegrationConfigError("read_only_sql must start with a read-only SQL operation")
    expected_rows = raw["expected_rows"]
    if not isinstance(expected_rows, list):
        raise IntegrationConfigError("expected_rows must be an array")
    fault_proxy = raw.get("fault_proxy")
    if fault_proxy is not None and not isinstance(fault_proxy, dict):
        raise IntegrationConfigError("fault_proxy must be an object")

    source_environment = os.environ if environ is None else environ
    return LiveConfig(
        connection_kwargs=_connection_kwargs(raw["connection_kwargs"], source_environment),
        read_only_sql=query,
        expected_rows=expected_rows,
        fault_proxy_config=None if fault_proxy is None else dict(fault_proxy),
        target_id=_nonempty_string(raw["target_id"], "target_id"),
        package_id=_nonempty_string(raw["package_id"], "package_id"),
        target_version=_optional_string(raw.get("target_version"), "target_version"),
        package_version=_optional_string(raw.get("package_version"), "package_version"),
        schema_name=_optional_string(raw.get("schema_name"), "schema_name"),
    )
