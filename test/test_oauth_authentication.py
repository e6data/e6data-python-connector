"""
Tests for OAuth 2.0 client-credentials authentication.

Two concerns are covered, and the second matters more than the first:

1. The OAuth path works -- tokens are fetched, cached, refreshed and sent on ``authenticate``.
2. **Nothing about the username/password path changed.** OAuth is strictly a second door here; the
   credential path is not deprecated, not flagged and not routed differently. The compatibility
   tests below are the gate on that claim.
"""

import base64
import json
import unittest
import urllib.error
from unittest.mock import Mock, patch

from e6data_python_connector.exceptions import OAuthError
from e6data_python_connector.oauth import (
    CLIENT_AUTH_BASIC,
    CLIENT_AUTH_POST,
    ClientCredentialsTokenProvider,
)
from e6data_python_connector.server import e6x_engine_pb2

TOKEN_URL = 'https://cp.example.com/oauth2/token'


class _FakeResponse(object):
    """Stands in for the object urlopen returns, which is used as a context manager."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode('utf-8')

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class TokenProviderTest(unittest.TestCase):

    def _provider(self, **kwargs):
        defaults = dict(token_url=TOKEN_URL, client_id='client-a', client_secret='shhh')
        defaults.update(kwargs)
        return ClientCredentialsTokenProvider(**defaults)

    @patch('e6data_python_connector.oauth.urllib.request.urlopen')
    def test_fetches_a_token_with_the_client_credentials_grant(self, urlopen):
        urlopen.return_value = _FakeResponse({'access_token': 'tok-1', 'expires_in': 3600})

        self.assertEqual(self._provider().get_token(), 'tok-1')

        request = urlopen.call_args[0][0]
        self.assertEqual(request.method, 'POST')
        self.assertEqual(request.full_url, TOKEN_URL)
        self.assertIn('grant_type=client_credentials', request.data.decode('utf-8'))

    @patch('e6data_python_connector.oauth.urllib.request.urlopen')
    def test_sends_client_credentials_as_basic_auth_by_default(self, urlopen):
        # client_secret_basic is what the e6data authorization server expects.
        urlopen.return_value = _FakeResponse({'access_token': 'tok-1', 'expires_in': 3600})

        self._provider().get_token()

        header = urlopen.call_args[0][0].get_header('Authorization')
        expected = 'Basic ' + base64.b64encode(b'client-a:shhh').decode('ascii')
        self.assertEqual(header, expected)

    @patch('e6data_python_connector.oauth.urllib.request.urlopen')
    def test_can_send_client_credentials_in_the_body_instead(self, urlopen):
        urlopen.return_value = _FakeResponse({'access_token': 'tok-1', 'expires_in': 3600})

        self._provider(client_auth_method=CLIENT_AUTH_POST).get_token()

        request = urlopen.call_args[0][0]
        self.assertIsNone(request.get_header('Authorization'))
        body = request.data.decode('utf-8')
        self.assertIn('client_id=client-a', body)
        self.assertIn('client_secret=shhh', body)

    @patch('e6data_python_connector.oauth.urllib.request.urlopen')
    def test_omits_scope_when_none_is_requested(self, urlopen):
        # An absent scope grants the client's full registered set; sending an empty one would be
        # asking for nothing at all.
        urlopen.return_value = _FakeResponse({'access_token': 'tok-1', 'expires_in': 3600})

        self._provider().get_token()

        self.assertNotIn('scope=', urlopen.call_args[0][0].data.decode('utf-8'))

    @patch('e6data_python_connector.oauth.urllib.request.urlopen')
    def test_caches_the_token_between_calls(self, urlopen):
        urlopen.return_value = _FakeResponse({'access_token': 'tok-1', 'expires_in': 3600})
        provider = self._provider()

        provider.get_token()
        provider.get_token()
        provider.get_token()

        self.assertEqual(urlopen.call_count, 1)

    @patch('e6data_python_connector.oauth.urllib.request.urlopen')
    def test_refreshes_before_the_token_actually_expires(self, urlopen):
        # expires_in of 30s with the default 60s leeway means the token is already considered stale,
        # so every call re-fetches rather than handing back something about to be rejected.
        urlopen.return_value = _FakeResponse({'access_token': 'tok-1', 'expires_in': 30})
        provider = self._provider()

        provider.get_token()
        provider.get_token()

        self.assertEqual(urlopen.call_count, 2)

    @patch('e6data_python_connector.oauth.urllib.request.urlopen')
    def test_force_refresh_bypasses_the_cache(self, urlopen):
        urlopen.side_effect = [
            _FakeResponse({'access_token': 'tok-1', 'expires_in': 3600}),
            _FakeResponse({'access_token': 'tok-2', 'expires_in': 3600}),
        ]
        provider = self._provider()

        self.assertEqual(provider.get_token(), 'tok-1')
        self.assertEqual(provider.get_token(force_refresh=True), 'tok-2')

    @patch('e6data_python_connector.oauth.urllib.request.urlopen')
    def test_assumes_a_short_lifetime_when_expires_in_is_missing(self, urlopen):
        # Caching a token past its expiry is an outage; refreshing one too often is a rounding
        # error. The default leans to the cheap failure.
        urlopen.return_value = _FakeResponse({'access_token': 'tok-1'})
        provider = self._provider()

        self.assertEqual(provider.get_token(), 'tok-1')
        self.assertEqual(provider.get_token(), 'tok-1')
        self.assertEqual(urlopen.call_count, 1)

    @patch('e6data_python_connector.oauth.urllib.request.urlopen')
    def test_reports_a_rejected_client_as_terminal(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError(
            TOKEN_URL, 401, 'Unauthorized', {},
            _BytesBody(json.dumps({'error': 'invalid_client'}).encode('utf-8')),
        )

        with self.assertRaises(OAuthError) as raised:
            self._provider().get_token()

        message = str(raised.exception)
        self.assertIn('invalid_client', message)
        self.assertIn('client_secret', message)

    @patch('e6data_python_connector.oauth.urllib.request.urlopen')
    def test_reports_a_server_error_as_worth_retrying(self, urlopen):
        # The e6data authorization server returns 503 temporarily_unavailable when it cannot confirm
        # a client's status. That is transient and must not read like bad credentials.
        urlopen.side_effect = urllib.error.HTTPError(
            TOKEN_URL, 503, 'Service Unavailable', {},
            _BytesBody(json.dumps({'error': 'temporarily_unavailable'}).encode('utf-8')),
        )

        with self.assertRaises(OAuthError) as raised:
            self._provider().get_token()

        self.assertIn('retry', str(raised.exception).lower())

    @patch('e6data_python_connector.oauth.urllib.request.urlopen')
    def test_reports_an_unreachable_endpoint(self, urlopen):
        urlopen.side_effect = urllib.error.URLError('connection refused')

        with self.assertRaises(OAuthError) as raised:
            self._provider().get_token()

        self.assertIn('Could not reach', str(raised.exception))

    @patch('e6data_python_connector.oauth.urllib.request.urlopen')
    def test_rejects_a_response_with_no_access_token(self, urlopen):
        urlopen.return_value = _FakeResponse({'token_type': 'Bearer'})

        with self.assertRaises(OAuthError):
            self._provider().get_token()

    def test_rejects_incomplete_configuration(self):
        with self.assertRaises(ValueError):
            ClientCredentialsTokenProvider(token_url='', client_id='a', client_secret='b')
        with self.assertRaises(ValueError):
            ClientCredentialsTokenProvider(token_url=TOKEN_URL, client_id='', client_secret='b')
        with self.assertRaises(ValueError):
            ClientCredentialsTokenProvider(
                token_url=TOKEN_URL, client_id='a', client_secret='b', client_auth_method='magic')


class _BytesBody(object):
    """Minimal stand-in for the file-like body an HTTPError carries."""

    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload

    def close(self):
        # HTTPError treats its body as a file and closes it during teardown. Without this the
        # tests pass but litter stderr with AttributeError from the garbage collector.
        pass


class AuthenticateRequestShapeTest(unittest.TestCase):
    """
    The generated message is what actually crosses the wire, so its behaviour is asserted directly
    rather than inferred from the .proto.
    """

    def test_the_message_carries_no_token_field(self):
        # The token travels in call metadata, so the message is wire-identical to what every
        # deployed client already speaks. Nothing here can break.
        names = [field.name for field in e6x_engine_pb2.AuthenticateRequest.DESCRIPTOR.fields]

        self.assertNotIn('bearerToken', names)
        self.assertFalse(any('token' in name.lower() for name in names))

    def test_pre_existing_fields_keep_their_numbers(self):
        # Renumbering any of these would break every deployed client, so pin them.
        numbers = {field.name: field.number for field in e6x_engine_pb2.AuthenticateRequest.DESCRIPTOR.fields}

        self.assertEqual(numbers['user'], 1)
        self.assertEqual(numbers['password'], 2)
        self.assertEqual(numbers['userNameForImpersonation'], 3)
        self.assertEqual(numbers['customIdentityClaim'], 4)

    def test_field_five_is_not_reused(self):
        # It briefly held an in-body token during development. Reserved in both copies of the proto
        # so nothing else can claim it and collide with a client built in that window.
        by_number = e6x_engine_pb2.AuthenticateRequest.DESCRIPTOR.fields_by_number

        self.assertIsNone(by_number.get(5))

    def test_bytes_from_an_older_client_still_parse(self):
        old_shape = e6x_engine_pb2.AuthenticateRequest(user='alice', password='secret')

        parsed = e6x_engine_pb2.AuthenticateRequest.FromString(old_shape.SerializeToString())

        self.assertEqual(parsed.user, 'alice')
        self.assertEqual(parsed.password, 'secret')


class ConnectionCredentialSelectionTest(unittest.TestCase):
    """
    Covers which credential shape a Connection accepts. The gRPC channel is stubbed out because none
    of this needs a server -- the decisions all happen in the constructor.
    """

    def _connect(self, **kwargs):
        from e6data_python_connector.e6data_grpc import Connection
        defaults = dict(host='localhost', port=80)
        defaults.update(kwargs)
        with patch.object(Connection, '_create_client', Mock(return_value=None)):
            return Connection(**defaults)

    def test_username_and_password_still_work_positionally(self):
        # The signature gained defaults and new keyword arguments, all appended after the existing
        # ones. Every call site that worked before must still work untouched.
        from e6data_python_connector.e6data_grpc import Connection
        with patch.object(Connection, '_create_client', Mock(return_value=None)):
            connection = Connection('localhost', 80, 'alice', 'secret')

        self.assertFalse(connection._uses_oauth)

    def test_a_credential_connection_builds_a_credential_request(self):
        connection = self._connect(username='alice', password='secret')

        request = connection._build_authenticate_request()

        self.assertEqual(request.user, 'alice')
        self.assertEqual(request.password, 'secret')

    @patch('e6data_python_connector.oauth.urllib.request.urlopen')
    def test_an_oauth_connection_sends_the_token_as_metadata(self, urlopen):
        urlopen.return_value = _FakeResponse({'access_token': 'tok-1', 'expires_in': 3600})
        connection = self._connect(
            client_id='client-a', client_secret='shhh', token_url=TOKEN_URL)

        request = connection._build_authenticate_request()
        metadata = dict(connection._authenticate_metadata())

        self.assertTrue(connection._uses_oauth)
        # Nothing in the message; the credential is entirely in metadata.
        self.assertEqual(request.user, '')
        self.assertEqual(request.password, '')
        self.assertEqual(metadata['authorization'], 'Bearer tok-1')

    def test_a_credential_connection_sends_no_authorization_metadata(self):
        connection = self._connect(username='alice', password='secret')

        metadata = dict(connection._authenticate_metadata())

        self.assertNotIn('authorization', metadata)

    def test_a_pre_obtained_token_is_used_as_given(self):
        connection = self._connect(access_token='minted-elsewhere')

        metadata = dict(connection._authenticate_metadata())

        self.assertTrue(connection._uses_oauth)
        self.assertEqual(metadata['authorization'], 'Bearer minted-elsewhere')

    def test_metadata_keeps_the_headers_the_connector_already_sent(self):
        # The authorization entry is appended to the existing metadata, never a replacement for it.
        connection = self._connect(access_token='tok', cluster_name='my-cluster')

        metadata = dict(connection._authenticate_metadata(strategy='blue'))

        self.assertEqual(metadata['cluster-name'], 'my-cluster')
        self.assertIn('authorization', metadata)

    def test_supplying_no_credentials_is_rejected(self):
        with self.assertRaises(ValueError) as raised:
            self._connect()

        self.assertIn('No credentials supplied', str(raised.exception))

    def test_mixing_credential_shapes_is_rejected_rather_than_ranked(self):
        # Preferring one silently is how a stale value in a config file ends up authenticating a
        # connection nobody meant it to.
        with self.assertRaises(ValueError) as raised:
            self._connect(username='alice', password='secret',
                          client_id='client-a', client_secret='shhh', token_url=TOKEN_URL)

        self.assertIn('exactly one', str(raised.exception))

    def test_mixing_a_token_with_credentials_is_rejected(self):
        with self.assertRaises(ValueError):
            self._connect(username='alice', password='secret', access_token='tok')

    def test_partial_oauth_configuration_is_rejected(self):
        with self.assertRaises(ValueError) as raised:
            self._connect(client_id='client-a', client_secret='shhh')

        self.assertIn('token_url', str(raised.exception))

    def test_a_username_without_a_password_is_still_rejected(self):
        # Pre-existing behaviour, preserved: the message changed shape but the rule did not.
        with self.assertRaises(ValueError):
            self._connect(username='alice')

    def test_host_and_port_are_still_required(self):
        from e6data_python_connector.e6data_grpc import Connection
        with patch.object(Connection, '_create_client', Mock(return_value=None)):
            with self.assertRaises(ValueError):
                Connection(host='', port=80, username='alice', password='secret')


class AuthenticationFailureMessageTest(unittest.TestCase):

    def _connect(self, **kwargs):
        from e6data_python_connector.e6data_grpc import Connection
        defaults = dict(host='localhost', port=80)
        defaults.update(kwargs)
        with patch.object(Connection, '_create_client', Mock(return_value=None)):
            return Connection(**defaults)

    def test_credential_failures_keep_their_original_error(self):
        connection = self._connect(username='alice', password='secret')

        self.assertIsInstance(connection._authentication_failure(), ValueError)

    def test_oauth_failures_name_both_possible_causes(self):
        # A pre-OAuth engine ignores the unknown field, sees empty credentials and refuses, which is
        # indistinguishable from a rejected token. The message must not pick one.
        from e6data_python_connector.exceptions import OAuthNotSupportedError
        connection = self._connect(access_token='tok')

        failure = connection._authentication_failure()

        self.assertIsInstance(failure, OAuthNotSupportedError)
        self.assertIn('predates OAuth support', str(failure))
        self.assertIn('OAUTH_ENABLED', str(failure))


if __name__ == '__main__':
    unittest.main()
