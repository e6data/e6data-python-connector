"""Local OAuth validation and dispatch safety; no live credentials or services."""
from unittest.mock import patch

import pytest

from e6data_python_connector.e6data_grpc import Connection


def construct(**options):
    with patch.object(Connection, '_create_client') as create_client:
        connection = Connection(host='fixture.invalid', port=443,
                                require_fastbinary=False, **options)
        return connection, create_client.call_count


@pytest.mark.parametrize('credentials', [
    {'access_token': 'test-token'},
    {'client_id': 'test-client', 'client_secret': 'test-secret',
     'token_url': 'https://issuer.invalid/oauth2/token'},
])
def test_sync_oauth_requires_tls_before_channel_creation(credentials):
    with patch.object(Connection, '_create_client') as create_client:
        with pytest.raises(ValueError, match='TLS'):
            Connection(host='fixture.invalid', port=443,
                       require_fastbinary=False, **credentials)
        create_client.assert_not_called()


@pytest.mark.parametrize('token', ['', 'raw token', 'Bearer token', 'a\nb', '\u00e9', 123])
def test_sync_static_token_rejects_invalid_header_value(token):
    with pytest.raises(ValueError):
        construct(access_token=token, secure=True)


@pytest.mark.parametrize('extra', [
    {'username': ''}, {'password': ''}, {'oauth_scope': ''},
])
def test_explicit_empty_credentials_cannot_hide_a_conflicting_mode(extra):
    with pytest.raises(ValueError, match='exactly one'):
        construct(access_token='test-token', secure=True, **extra)


@pytest.mark.parametrize('name', [
    'ssl_target_name_override', 'grpc.ssl_target_name_override',
    'default_authority', 'grpc.default_authority',
])
def test_oauth_tls_authority_override_is_rejected(name):
    with pytest.raises(ValueError, match='authority'):
        construct(access_token='test-token', secure=True,
                  grpc_options={name: 'other.invalid'})


def test_oauth_certificate_must_be_path_or_bytes():
    with pytest.raises(ValueError, match='ssl_cert'):
        construct(access_token='test-token', secure=True, ssl_cert=123)


def test_existing_legacy_insecure_mode_is_unchanged():
    connection, calls = construct(username='test-user', password='test-password')
    assert not connection._uses_oauth
    assert calls == 1


def test_valid_static_oauth_builds_one_secure_channel():
    connection, calls = construct(access_token='test-token', secure=True)
    assert connection._secure_channel
    assert connection._bearer_token() == 'test-token'
    assert calls == 1
