"""Process-local credential state; transports and their resources remain private."""
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
import threading
import time
import weakref

from e6data_python_connector.exceptions import OAuthError

_SAFE_ERRORS = frozenset({
    'OAuth token endpoint redirects are prohibited.',
    'OAuth token response exceeds size limit.',
    'Could not reach the OAuth token endpoint.',
    'OAuth token endpoint did not return valid JSON.',
    'OAuth token endpoint temporarily unavailable; retry later.',
    'OAuth invalid_client or scope rejected; check client_id and client_secret.',
    'OAuth token endpoint rejected the request.',
    'Invalid OAuth token response shape.', 'Invalid OAuth access_token.',
    'OAuth token_type must be Bearer.', 'OAuth expires_in must be a positive integer.',
    'Invalid OAuth expiry arithmetic.', 'OAuth token expired during exchange.',
})

_registry = weakref.WeakValueDictionary()
_registry_lock = threading.Lock()
_digest_key = os.urandom(32)


def _after_fork():
    global _registry, _registry_lock, _digest_key
    _registry = weakref.WeakValueDictionary()
    _registry_lock = threading.Lock()
    _digest_key = os.urandom(32)


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)


def get_state(token_url, client_id, client_secret, scope, client_auth_method,
              timeout, refresh_leeway_seconds):
    settings = (token_url, client_id, client_secret, scope, client_auth_method,
                float(timeout), float(refresh_leeway_seconds))
    key = hmac.new(_digest_key, json.dumps(settings).encode(), hashlib.sha256).digest()
    with _registry_lock:
        state = _registry.get(key)
        if state is None:
            state = TokenState(timeout)
            _registry[key] = state
        return state


@dataclass(frozen=True)
class Selection:
    token: str = None
    flight: object = None
    waiter: object = None
    owner: bool = False
    retiring: bool = False


class Flight:
    def __init__(self, state, deadline, generation, is_async):
        self._state = state
        self.deadline = deadline
        self.generation = generation
        self.is_async = is_async
        self.thread_id = threading.get_ident()
        self.done = threading.Event()
        self.retiring = False
        self._cancel = None
        self._callbacks = {}
        self._token = None
        self._error = None

    def result(self):
        self._state._check_pid()
        with self._state._lock:
            if not self.done.is_set():
                raise RuntimeError('OAuth refresh is not complete.')
            error, token = self._error, self._token
        if error:
            category, message = error
            raise category(message) from None
        return token

    def subscribe(self, callback):
        self._state._check_pid()
        registration = object()
        with self._state._lock:
            ready = self.done.is_set()
            if not ready:
                self._callbacks[registration] = callback
        if ready:
            callback()

        def unsubscribe():
            self._state._check_pid()
            with self._state._lock:
                self._callbacks.pop(registration, None)
        return unsubscribe


class TokenState:
    def __init__(self, timeout):
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._timeout = timeout
        self._token = None
        self._expires_at = 0.0
        self._generation = 0
        self._flight = None
        self._waiters = {}

    def _check_pid(self):
        if os.getpid() != self._pid:
            raise OAuthError('OAuth provider cannot be used in another process.')

    @property
    def token(self):
        self._check_pid()
        with self._lock:
            return self._token

    @token.setter
    def token(self, value):
        self._check_pid()
        with self._lock:
            self._token = value

    @property
    def expires_at(self):
        self._check_pid()
        with self._lock:
            return self._expires_at

    @expires_at.setter
    def expires_at(self, value):
        self._check_pid()
        with self._lock:
            self._expires_at = value

    @property
    def generation(self):
        self._check_pid()
        with self._lock:
            return self._generation

    def select(self, caller_deadline, force_refresh=False, rejected_token=None, *, is_async=False):
        self._check_pid()
        with self._lock:
            now = time.monotonic()
            if now >= caller_deadline:
                raise TimeoutError('OAuth token deadline exceeded.')
            replaced = rejected_token is not None and self._token != rejected_token
            if (not force_refresh or replaced) and self._token and now < self._expires_at:
                return Selection(token=self._token)
            flight = self._flight
            if flight is not None:
                if not is_async and flight.is_async and flight.thread_id == threading.get_ident():
                    raise OAuthError('Cannot block the owning async refresh thread.')
                if flight.retiring:
                    return Selection(flight=flight, retiring=True)
            owner = flight is None
            if owner:
                self._token = None
                self._expires_at = 0.0
                flight = Flight(self, now + self._timeout, self._generation, is_async)
                self._flight = flight
            waiter = object()
            self._waiters[waiter] = flight
            return Selection(flight=flight, waiter=waiter, owner=owner)

    def detach(self, waiter):
        self._check_pid()
        callback = None
        with self._lock:
            flight = self._waiters.pop(waiter, None)
            if (flight is not None and self._flight is flight and not flight.retiring
                    and flight not in self._waiters.values()):
                flight.retiring = True
                callback, flight._cancel = flight._cancel, None
        if callback:
            callback()

    def install_cancel(self, flight, callback):
        self._check_pid()
        immediate = False
        with self._lock:
            if self._flight is flight:
                if flight.retiring:
                    immediate = True
                else:
                    flight._cancel = callback
        if immediate:
            callback()

    def finish(self, flight, token=None, reusable_until=0, error=None):
        self._check_pid()
        with self._lock:
            if self._flight is not flight or flight.done.is_set():
                return
            if error is not None:
                # Never retain owner exception objects, tracebacks, URLs or remote bodies.
                category = TimeoutError if isinstance(error, TimeoutError) else OAuthError
                message = 'OAuth refresh deadline exceeded.' if category is TimeoutError else 'OAuth token refresh failed.'
                if type(error) is OAuthError and str(error) in _SAFE_ERRORS:
                    message = str(error)
                flight._error = (category, message)
            elif flight.generation != self._generation or flight.retiring:
                flight._error = (OAuthError, 'OAuth exchange invalidated before completion.')
            elif time.monotonic() >= flight.deadline:
                flight._error = (TimeoutError, 'OAuth refresh deadline exceeded.')
            else:
                flight._token = token
                if reusable_until > time.monotonic():
                    self._token, self._expires_at = token, reusable_until
            self._flight = None
            self._waiters = {key: value for key, value in self._waiters.items() if value is not flight}
            flight._cancel = None
            callbacks = list(flight._callbacks.values())
            flight._callbacks.clear()
            flight.done.set()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                # A disposed subscriber must not strand other loops or threads.
                pass

    def invalidate(self):
        self._check_pid()
        with self._lock:
            self._generation += 1
            self._token = None
            self._expires_at = 0.0
