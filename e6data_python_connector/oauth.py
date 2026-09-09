"""
OAuth 2.0 client-credentials support for the e6data connector.

Obtains an access token from an authorization server and caches it until shortly before it expires.
The token travels as bearer metadata on every OAuth RPC, without creating a legacy session.

Deliberately built on the standard library. ``requests`` appears in ``requirements.txt`` but not in
``install_requires``, so it is a development dependency; reaching for it here would silently add a
runtime dependency for everyone installing the connector.
"""

import base64
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from e6data_python_connector.exceptions import OAuthError

_logger = logging.getLogger(__name__)

#: Seconds before actual expiry at which a cached token is considered stale. Covers clock skew
#: between us and the authorization server plus the round trip of whatever call the token is about
#: to be used for.
DEFAULT_REFRESH_LEEWAY_SECONDS = 60

#: Assumed lifetime when the authorization server omits ``expires_in``. Deliberately short: a token
#: refreshed too often is a small waste, whereas one cached past its expiry is an outage.
DEFAULT_ASSUMED_LIFETIME_SECONDS = 300

DEFAULT_TIMEOUT_SECONDS = 10

#: Send the client id and secret as HTTP Basic credentials (RFC 6749 section 2.3.1). This is the
#: default because it is what the e6data authorization server expects.
CLIENT_AUTH_BASIC = 'basic'

#: Send them in the request body instead, for authorization servers that require it.
CLIENT_AUTH_POST = 'post'


class ClientCredentialsTokenProvider(object):
    """
    Fetches and caches an OAuth 2.0 access token using the client-credentials grant.

    Safe to share between threads: the connector's connection pool hands one provider to several
    connections, and without the lock they would stampede the authorization server the moment a
    token expires.
    """

    def __init__(
            self,
            token_url: str,
            client_id: str,
            client_secret: str,
            scope: str = None,
            client_auth_method: str = CLIENT_AUTH_BASIC,
            timeout: int = DEFAULT_TIMEOUT_SECONDS,
            refresh_leeway_seconds: int = DEFAULT_REFRESH_LEEWAY_SECONDS,
    ):
        """
        Parameters
        ----------
            token_url: str
                The authorization server's token endpoint.
            client_id: str
                Client identifier issued by the authorization server.
            client_secret: str
                Client secret issued alongside the id.
            scope: str, Optional
                Space-delimited scopes to request. Omit to receive the client's full registered set.
            client_auth_method: str, Optional
                How to present the client credentials -- ``basic`` (default) or ``post``.
            timeout: int, Optional
                Per-request timeout in seconds.
            refresh_leeway_seconds: int, Optional
                How long before expiry a cached token is refreshed.
        """
        if not token_url:
            raise ValueError('token_url cannot be empty.')
        if not client_id or not client_secret:
            raise ValueError('client_id and client_secret cannot be empty.')
        if client_auth_method not in (CLIENT_AUTH_BASIC, CLIENT_AUTH_POST):
            raise ValueError(
                "client_auth_method must be '{}' or '{}'.".format(CLIENT_AUTH_BASIC, CLIENT_AUTH_POST)
            )

        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope
        self._client_auth_method = client_auth_method
        self._timeout = timeout
        self._refresh_leeway_seconds = refresh_leeway_seconds

        self._lock = threading.Lock()
        self._access_token = None
        self._expires_at = 0.0

    def get_token(self, force_refresh: bool = False, deadline=None, rejected_token=None) -> str:
        """
        Returns a usable access token, fetching a new one if the cached token is missing, stale or
        explicitly discarded.

        Parameters
        ----------
            force_refresh: bool, Optional
                Fetch a new token even if the cache is fresh.
            deadline: float, Optional
                Absolute monotonic caller deadline, including lock wait and exchange.
                An already dispatched HTTP exchange can finish after the caller times out;
                its result is discarded and cannot schedule any further RPC.
            rejected_token: str, Optional
                Token rejected by an explicit UNAUTHENTICATED response. Reuse a valid
                replacement another thread already obtained instead of refreshing again.

        Returns
        -------
            str: the access token.

        Raises
        ------
            OAuthError: if the authorization server refuses or cannot be reached.
        """
        if deadline is None:
            self._lock.acquire()
        elif not self._lock.acquire(timeout=self._remaining(deadline)):
            raise TimeoutError('OAuth token deadline exceeded waiting for refresh lock.')
        transferred = False
        try:
            replaced = rejected_token is not None and self._access_token != rejected_token
            if (not force_refresh or replaced) and self._access_token and time.time() < self._expires_at:
                return self._access_token
            if deadline is None:
                return self._refresh_token()

            # urllib's socket timeout does not bound DNS or a sequence of reads. Bound
            # the waiting caller too. The worker retains the refresh lock until the
            # in-flight exchange ends and never publishes a token after its deadline.
            # Python cannot forcibly cancel a blocking DNS/read in another thread.
            completed = threading.Event()
            result = []
            def refresh():
                try:
                    result.append(self._refresh_token(deadline))
                except BaseException as error:
                    result.append(error)
                finally:
                    self._lock.release()
                    completed.set()

            worker = threading.Thread(target=refresh, daemon=True)
            worker.start()
            transferred = True
            if not completed.wait(self._remaining(deadline)):
                raise TimeoutError('OAuth token deadline exceeded during exchange.')
            self._remaining(deadline)
            if isinstance(result[0], BaseException):
                raise result[0]
            return result[0]
        finally:
            if not transferred:
                self._lock.release()

    @staticmethod
    def _remaining(deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('OAuth token deadline exceeded.')
        return remaining

    def _refresh_token(self, deadline=None):
        access_token, expires_in = self._fetch_token(deadline)
        if deadline is not None:
            self._remaining(deadline)
        self._access_token = access_token
        self._expires_at = time.time() + max(expires_in - self._refresh_leeway_seconds, 0)
        return access_token

    def invalidate(self):
        """Drops the cached token so the next call fetches a fresh one."""
        with self._lock:
            self._access_token = None
            self._expires_at = 0.0

    def _fetch_token(self, deadline=None):
        """Performs the client-credentials exchange. Caller holds the lock."""
        form = {'grant_type': 'client_credentials'}
        if self._scope:
            form['scope'] = self._scope

        headers = {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'}
        if self._client_auth_method == CLIENT_AUTH_BASIC:
            credentials = '{}:{}'.format(self._client_id, self._client_secret).encode('utf-8')
            headers['Authorization'] = 'Basic ' + base64.b64encode(credentials).decode('ascii')
        else:
            form['client_id'] = self._client_id
            form['client_secret'] = self._client_secret

        request = urllib.request.Request(
            self._token_url,
            data=urllib.parse.urlencode(form).encode('utf-8'),
            headers=headers,
            method='POST',
        )

        try:
            timeout = self._timeout if deadline is None else min(self._timeout, self._remaining(deadline))
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as error:
            raise OAuthError(self._describe_http_error(error)) from error
        except urllib.error.URLError as error:
            raise OAuthError(
                'Could not reach the token endpoint {}: {}'.format(self._token_url, error.reason)
            ) from error
        except (ValueError, TypeError) as error:
            raise OAuthError(
                'Token endpoint {} did not return valid JSON.'.format(self._token_url)
            ) from error

        access_token = payload.get('access_token')
        if not access_token:
            raise OAuthError(
                'Token endpoint {} returned no access_token.'.format(self._token_url)
            )

        expires_in = payload.get('expires_in')
        try:
            expires_in = int(expires_in)
        except (TypeError, ValueError):
            _logger.warning(
                'Token endpoint %s returned no usable expires_in; assuming %s seconds.',
                self._token_url, DEFAULT_ASSUMED_LIFETIME_SECONDS,
            )
            expires_in = DEFAULT_ASSUMED_LIFETIME_SECONDS

        return access_token, expires_in

    def _describe_http_error(self, error) -> str:
        """
        Turns an HTTP failure into a message that says what to do about it.

        The distinction that matters is transient versus terminal: a 5xx (the e6data authorization
        server returns 503 ``temporarily_unavailable`` when it cannot confirm a client's status) is
        worth retrying, whereas a 401 ``invalid_client`` means the credentials are wrong and
        retrying will not help.
        """
        oauth_error = ''
        try:
            body = json.loads(error.read().decode('utf-8'))
            oauth_error = body.get('error') or ''
        except Exception:  # noqa: BLE001 - the body is best-effort context, never load-bearing
            pass

        detail = ' ({})'.format(oauth_error) if oauth_error else ''
        if error.code >= 500:
            return (
                'Token endpoint {} is temporarily unavailable: HTTP {}{}. This is usually transient '
                '- retry.'.format(self._token_url, error.code, detail)
            )
        if error.code in (400, 401):
            return (
                'Token endpoint {} rejected the client credentials: HTTP {}{}. Check client_id, '
                'client_secret and the requested scope.'.format(self._token_url, error.code, detail)
            )
        return 'Token endpoint {} returned HTTP {}{}.'.format(self._token_url, error.code, detail)
