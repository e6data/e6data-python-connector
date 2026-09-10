"""Bounded synchronous client-credentials exchange and monotonic token cache."""
import base64
import json
import math
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from e6data_python_connector.exceptions import OAuthError
from e6data_python_connector.oauth_cache import get_state
from e6data_python_connector.oauth_common import (
    MAX_TOKEN_RESPONSE_BYTES, validate_positive_timeout,
    validate_token_endpoint, validate_token_response,
)

DEFAULT_REFRESH_LEEWAY_SECONDS = 60
DEFAULT_TIMEOUT_SECONDS = 10
CLIENT_AUTH_BASIC = 'basic'
CLIENT_AUTH_POST = 'post'

# A timed-out blocking exchange continues to own its slot until it actually exits.
_EXCHANGE_SLOTS = threading.BoundedSemaphore(4)


def _reset_exchange_slots_after_fork():
    # Parent workers do not survive fork, so their occupied slots cannot drain.
    global _EXCHANGE_SLOTS
    _EXCHANGE_SLOTS = threading.BoundedSemaphore(4)


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_reset_exchange_slots_after_fork)


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OAuthError('OAuth token endpoint redirects are prohibited.')


class ClientCredentialsTokenProvider:
    """Shareable provider with one publisher and no queued background workers."""

    def __init__(self, token_url, client_id, client_secret, scope=None,
                 client_auth_method=CLIENT_AUTH_BASIC, timeout=DEFAULT_TIMEOUT_SECONDS,
                 refresh_leeway_seconds=DEFAULT_REFRESH_LEEWAY_SECONDS):
        validate_token_endpoint(token_url)
        if not client_id or not client_secret:
            raise ValueError('client_id and client_secret cannot be empty.')
        if client_auth_method not in (CLIENT_AUTH_BASIC, CLIENT_AUTH_POST):
            raise ValueError("client_auth_method must be 'basic' or 'post'.")
        self._timeout = validate_positive_timeout(timeout)
        if (isinstance(refresh_leeway_seconds, bool)
                or not isinstance(refresh_leeway_seconds, (int, float))
                or not math.isfinite(refresh_leeway_seconds) or refresh_leeway_seconds < 0):
            raise ValueError('refresh_leeway_seconds must be finite and nonnegative.')
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope
        self._client_auth_method = client_auth_method
        self._refresh_leeway_seconds = refresh_leeway_seconds
        self._pid = os.getpid()
        self._state = get_state(token_url, client_id, client_secret, scope,
                                client_auth_method, self._timeout, refresh_leeway_seconds)
        # Ignore environment proxy configuration and never forward credentials on redirects.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _RejectRedirects())

    @property
    def _access_token(self):
        return self._state.token

    @_access_token.setter
    def _access_token(self, value):
        self._state.token = value

    @property
    def _expires_at(self):
        return self._state.expires_at

    @_expires_at.setter
    def _expires_at(self, value):
        self._state.expires_at = value

    def get_token(self, force_refresh=False, deadline=None, rejected_token=None):
        """Join matching credential renewal within this caller's own budget."""
        self._state._check_pid()
        budget = time.monotonic() + self._timeout
        if deadline is not None:
            if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
                raise ValueError('deadline must be a finite monotonic timestamp.')
            budget = min(budget, deadline)
        while True:
            selection = self._state.select(budget, force_refresh, rejected_token)
            if selection.token is not None:
                return selection.token
            flight = selection.flight
            if selection.retiring:
                if not flight.done.wait(self._remaining(budget)):
                    raise TimeoutError('OAuth token deadline exceeded waiting for retirement.')
                continue
            try:
                if selection.owner:
                    self._start_refresh(flight)
                if not flight.done.wait(self._remaining(budget)):
                    raise TimeoutError('OAuth token deadline exceeded during exchange.')
                self._remaining(budget)
                return flight.result()
            finally:
                self._state.detach(selection.waiter)

    def _start_refresh(self, flight):
        exchange_slots = _EXCHANGE_SLOTS
        if not exchange_slots.acquire(blocking=False):
            self._state.finish(flight, error=TimeoutError('OAuth exchange capacity exhausted.'))
            return

        def refresh():
            try:
                started = time.monotonic()
                payload = self._fetch_token(flight.deadline)
                token, until = validate_token_response(payload, started_at=started,
                    now=time.monotonic(), leeway=self._refresh_leeway_seconds)
                self._state.finish(flight, token, until)
            except BaseException as error:
                self._state.finish(flight, error=error)
            finally:
                exchange_slots.release()

        try:
            threading.Thread(target=refresh, daemon=True).start()
        except BaseException as error:
            exchange_slots.release()
            self._state.finish(flight, error=error)

    @staticmethod
    def _remaining(deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('OAuth token deadline exceeded.')
        return remaining

    def invalidate(self):
        """Invalidate the matching shared credential generation."""
        self._state.invalidate()

    def _fetch_token(self, deadline):
        form = {'grant_type': 'client_credentials'}
        if self._scope:
            form['scope'] = self._scope
        headers = {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'}
        if self._client_auth_method == CLIENT_AUTH_BASIC:
            credentials = '{}:{}'.format(urllib.parse.quote_plus(self._client_id),
                                        urllib.parse.quote_plus(self._client_secret)).encode('utf-8')
            headers['Authorization'] = 'Basic ' + base64.b64encode(credentials).decode('ascii')
        else:
            form['client_id'] = self._client_id
            form['client_secret'] = self._client_secret
        request = urllib.request.Request(self._token_url, data=urllib.parse.urlencode(form).encode('utf-8'),
                                         headers=headers, method='POST')
        try:
            with self._opener.open(request, timeout=self._remaining(deadline)) as response:
                body = response.read(MAX_TOKEN_RESPONSE_BYTES + 1)
                if len(body) > MAX_TOKEN_RESPONSE_BYTES:
                    raise OAuthError('OAuth token response exceeds size limit.')
                return json.loads(body.decode('utf-8'))
        except urllib.error.HTTPError as error:
            message = self._describe_http_error(error)
            error.close()
            raise OAuthError(message) from None
        except (urllib.error.URLError, OSError):
            raise OAuthError('Could not reach the OAuth token endpoint.') from None
        except (ValueError, TypeError):
            raise OAuthError('OAuth token endpoint did not return valid JSON.') from None

    @staticmethod
    def _describe_http_error(error):
        # Do not read untrusted error bodies or expose URLs, reasons or credentials.
        if error.code >= 500:
            return 'OAuth token endpoint temporarily unavailable; retry later.'
        if error.code in (400, 401):
            return 'OAuth invalid_client or scope rejected; check client_id and client_secret.'
        return 'OAuth token endpoint rejected the request.'
