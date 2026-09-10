"""Owned native HTTP token acquisition with bounded single-flight renewal."""
import asyncio
import base64
import json
import math
import os
import ssl
import threading
import time
import urllib.parse
import weakref

from e6data_python_connector.async_work import run_blocking
from e6data_python_connector.exceptions import OAuthError
from e6data_python_connector.oauth_common import (
    MAX_TOKEN_RESPONSE_BYTES, validate_token_endpoint, validate_positive_timeout,
    validate_token_response,
)

_LOOP_SLOTS = weakref.WeakKeyDictionary()


class AsyncClientCredentialsTokenProvider:
    def __init__(self, token_url, client_id, client_secret, scope=None,
                 client_auth_method='basic', timeout=10, refresh_leeway_seconds=60):
        validate_token_endpoint(token_url)
        if not client_id or not client_secret:
            raise ValueError('client_id and client_secret cannot be empty.')
        if client_auth_method not in ('basic', 'post'):
            raise ValueError("client_auth_method must be 'basic' or 'post'.")
        self._timeout = validate_positive_timeout(timeout)
        if (isinstance(refresh_leeway_seconds, bool)
                or not isinstance(refresh_leeway_seconds, (int, float))
                or not math.isfinite(refresh_leeway_seconds) or refresh_leeway_seconds < 0):
            raise ValueError('refresh_leeway_seconds must be finite and nonnegative.')
        self._token_url, self._client_id, self._client_secret = token_url, client_id, client_secret
        self._scope, self._client_auth_method = scope, client_auth_method
        self._refresh_leeway_seconds = refresh_leeway_seconds
        from .oauth_cache import get_state
        self._pid = os.getpid()
        self._state = get_state(token_url, client_id, client_secret, scope,
                                client_auth_method, self._timeout, refresh_leeway_seconds)
        self._waiters = 0
        self._callers = set()
        self._registrations = set()
        self._task, self._client, self._owner = None, None, None
        self._closed = False
        self._close_task = None

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

    @property
    def _generation(self):
        return self._state.generation

    def _bind(self):
        if os.getpid() != self._pid:
            raise OAuthError('OAuth provider belongs to another process.')
        owner = (os.getpid(), threading.get_ident(), asyncio.get_running_loop())
        if self._owner is None:
            self._owner = owner
        elif self._owner != owner:
            raise OAuthError('OAuth provider belongs to another process, thread or event loop.')
        return owner[2]

    async def get_token(self, force_refresh=False, deadline=None, rejected_token=None):
        loop = self._bind()
        if self._closed:
            raise OAuthError('OAuth provider is closed.')
        if deadline is not None and (isinstance(deadline, bool) or not isinstance(deadline, (int, float))
                                     or not math.isfinite(deadline)):
            raise ValueError('deadline must be a finite monotonic timestamp.')
        if deadline is not None and deadline <= time.monotonic():
            raise TimeoutError('OAuth caller deadline exceeded.')
        if deadline is None:
            deadline = time.monotonic() + self._timeout
        caller = asyncio.current_task()
        self._callers.add(caller)
        try:
            while True:
                selected = self._state.select(deadline, force_refresh=force_refresh,
                                              rejected_token=rejected_token, is_async=True)
                if selected.token is not None:
                    return selected.token
                flight = selected.flight
                self._waiters += 1
                if selected.waiter is not None:
                    self._registrations.add(selected.waiter)
                try:
                    if selected.owner:
                        exchange = self._refresh(flight)
                        try:
                            self._task = loop.create_task(exchange)
                        except BaseException:
                            exchange.close()
                            self._state.finish(flight, error=OAuthError('OAuth exchange could not start.'))
                            raise
                        task = self._task
                        task.add_done_callback(lambda done, owned=flight: self._exchange_done(owned, done))
                        def cancel_owned():
                            try:
                                loop.call_soon_threadsafe(task.cancel)
                            except RuntimeError:
                                self._state.finish(flight, error=OAuthError('OAuth owner loop closed.'))
                        self._state.install_cancel(flight, cancel_owned)
                    await self._wait_for_flight(flight, deadline, retiring=selected.retiring)
                    if selected.retiring:
                        continue
                    return flight.result()
                finally:
                    self._waiters -= 1
                    if selected.waiter is not None:
                        self._registrations.discard(selected.waiter)
                        self._state.detach(selected.waiter)
        finally:
            self._callers.discard(caller)

    async def _wait_for_flight(self, flight, deadline, *, retiring=False):
        loop = asyncio.get_running_loop()
        ready = loop.create_future()
        def deliver():
            if not ready.done():
                ready.set_result(None)
        def completed():
            try:
                loop.call_soon_threadsafe(deliver)
            except RuntimeError:
                pass  # A closed owner loop cannot consume completion.
        unsubscribe = flight.subscribe(completed)
        try:
            # A fresh caller may wait for an expired exchange to finish cleanup
            # before retrying; only active acquisition inherits its phase budget.
            wait_deadline = deadline if retiring else min(deadline, flight.deadline)
            remaining = max(0, wait_deadline - time.monotonic())
            async with asyncio.timeout(remaining):
                await ready
        finally:
            unsubscribe()

    def _exchange_done(self, flight, task):
        # A task cancelled before its coroutine starts never executes finally.
        error = OAuthError('OAuth exchange owner was cancelled.') if task.cancelled() else task.exception()
        if error is not None:
            self._state.finish(flight, error=error)

    @staticmethod
    def _observe(task):
        if not task.cancelled():
            task.exception()

    async def invalidate(self):
        self._bind()
        self._state.invalidate()

    async def close(self, *, deadline=None):
        loop = self._bind()
        if deadline is not None and (isinstance(deadline, bool) or not isinstance(deadline, (int, float))
                                     or not math.isfinite(deadline)):
            raise ValueError('deadline must be a finite monotonic timestamp.')
        budget = time.monotonic() + self._timeout
        if deadline is not None:
            budget = min(budget, deadline)
        if self._close_task is None:
            self._closed = True
            for waiter in tuple(self._registrations):
                self._state.detach(waiter)
            callers = tuple(self._callers)
            for caller in callers:
                caller.cancel()
            self._close_task = loop.create_task(self._dispose())
            self._close_task.add_done_callback(self._observe)
        async with asyncio.timeout(max(0, budget - time.monotonic())):
            await asyncio.shield(self._close_task)

    async def _dispose(self):
        if self._task is not None:
            try:
                await asyncio.shield(self._task)
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            except Exception:
                pass
        if self._client is not None:
            await self._client.aclose()

    async def _refresh(self, flight):
        deadline = flight.deadline
        loop = asyncio.get_running_loop()
        slots = _LOOP_SLOTS.setdefault(loop, asyncio.Semaphore(4))
        try:
            async with asyncio.timeout(max(0, deadline - time.monotonic())):
                async with slots:
                    started = time.monotonic()
                    payload = await self._fetch_token(deadline)
                    token, reusable_until = validate_token_response(
                        payload, started_at=started, now=time.monotonic(), leeway=self._refresh_leeway_seconds)
                    self._state.finish(flight, token=token, reusable_until=reusable_until)
        except BaseException as error:
            failure = OAuthError('OAuth exchange owner was cancelled.') if isinstance(error, asyncio.CancelledError) else error
            self._state.finish(flight, error=failure)
            raise

    async def _fetch_token(self, deadline):
        import httpx
        if self._client is None:
            context = await run_blocking(ssl.create_default_context, deadline=deadline)
            self._client = httpx.AsyncClient(verify=context, trust_env=False, follow_redirects=False,
                                            timeout=self._timeout, limits=httpx.Limits(max_connections=1))
        form = {'grant_type': 'client_credentials'}
        if self._scope:
            form['scope'] = self._scope
        headers = {'Accept': 'application/json'}
        if self._client_auth_method == 'basic':
            credentials = '{}:{}'.format(urllib.parse.quote_plus(self._client_id),
                                        urllib.parse.quote_plus(self._client_secret)).encode('utf-8')
            headers['Authorization'] = 'Basic ' + base64.b64encode(credentials).decode('ascii')
        else:
            form.update(client_id=self._client_id, client_secret=self._client_secret)
        try:
            async with self._client.stream('POST', self._token_url, data=form, headers=headers,
                                           timeout=max(.001, deadline - time.monotonic())) as response:
                if not 200 <= response.status_code < 300:
                    raise OAuthError('OAuth token endpoint rejected the request.')
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    if len(body) + len(chunk) > MAX_TOKEN_RESPONSE_BYTES:
                        raise OAuthError('OAuth token response exceeds size limit.')
                    body.extend(chunk)
                return json.loads(body.decode('utf-8'))
        except httpx.HTTPError:
            raise OAuthError('Could not reach the OAuth token endpoint.') from None
        except (ValueError, TypeError, UnicodeError):
            raise OAuthError('OAuth token endpoint did not return valid JSON.') from None
