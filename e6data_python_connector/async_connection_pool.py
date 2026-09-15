"""Native asyncio pool with bounded capacity and revocable task-owned leases."""
import asyncio
import inspect
import os
import threading
from contextlib import asynccontextmanager
from functools import wraps

from .async_connection import AsyncConnection
from .exceptions import OperationalError, ProgrammingError
from .oauth_common import validate_positive_timeout


async def _finish(task):
    """Finish bounded finalization even if the waiter is cancelled repeatedly."""
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError()
    return result


class _PoolState:
    """Pure reservation ledger; callers serialize transitions on their owner loop."""
    def __init__(self, capacity):
        self.capacity = capacity
        self.slots = {}
        self.revision = 0

    def reserve(self):
        if len(self.slots) >= self.capacity:
            return None
        self.revision += 1
        self.slots[self.revision] = 'creating'
        return self.revision

    def move(self, slot, expected, target):
        if self.slots.get(slot) != expected:
            raise ProgrammingError('Invalid pool reservation transition.')
        self.slots[slot] = target

    def remove(self, slot):
        if slot not in self.slots:
            raise ProgrammingError('Pool reservation already released.')
        del self.slots[slot]

    def counts(self):
        return {name: sum(value == name for value in self.slots.values())
                for name in ('idle', 'leased', 'creating', 'retiring')}


class PooledConnection:
    """One checkout capability; retaining this wrapper never extends its lease."""
    def __init__(self, connection, pool, slot, revision):
        self._connection, self.pool = connection, pool
        self._slot, self._revision = slot, revision
        self._task = asyncio.current_task()
        self._active = True
        self._returned = False
        self._cleanup_task = None
        self._cursors = set()

    @property
    def connection(self):
        """The lease facade, never an unguarded physical connection."""
        return self

    def _guard(self, internal=False):
        self.pool._check_owner()
        if not self._active or self.pool._leases.get(self._slot) is not self:
            raise ProgrammingError('Connection lease is no longer active.')
        if not internal and asyncio.current_task() is not self._task:
            raise ProgrammingError('Connection lease belongs to another task.')

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        self._guard()
        value = getattr(self._connection, name)
        if inspect.iscoroutinefunction(value):
            @wraps(value)
            async def call(*args, **kwargs):
                self._guard()
                result = await value(*args, **kwargs)
                self._guard()
                return self if result is self._connection else result
            return call
        if callable(value):
            @wraps(value)
            def call(*args, **kwargs):
                self._guard()
                return value(*args, **kwargs)
            return call
        return value

    def cursor(self, catalog_name=None, db_name=None):
        self._guard()
        cursor = self._connection.cursor(catalog_name, db_name)
        cursor._public_connection = self
        self._cursors.add(cursor)
        return cursor

    async def close_cursor(self):
        self._guard()
        deadline = asyncio.get_running_loop().time() + self.pool.cleanup_timeout
        async with asyncio.timeout_at(deadline):
            for cursor in tuple(self._cursors):
                await cursor.close()
        self._cursors.clear()

    async def close(self):
        self._guard()
        await self.pool.return_connection(self)

    async def __aenter__(self):
        self._guard()
        return self

    async def __aexit__(self, *exc):
        if not self._returned:
            await self.pool.return_connection(self)


class AsyncConnectionPool:
    def __init__(self, min_size=2, max_size=10, max_overflow=5, timeout=30.0,
                 recycle=3600, debug=False, pre_ping=True, **connection_params):
        for name, value, minimum in (('min_size', min_size, 0), ('max_size', max_size, 1), ('max_overflow', max_overflow, 0)):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError('{} is invalid.'.format(name))
        if min_size > max_size:
            raise ValueError('min_size cannot exceed max_size.')
        self.min_size, self.max_size, self.max_overflow = min_size, max_size, max_overflow
        self.timeout = validate_positive_timeout(timeout)
        self.recycle = validate_positive_timeout(recycle)
        self.pre_ping = bool(pre_ping)
        self._params = dict(connection_params, debug=debug)
        # Validation only: no channel, HTTP client or event-loop object is created.
        config = AsyncConnection(**self._params)
        self.cleanup_timeout = config.cleanup_timeout
        self._owner = None
        self._status = 'new'
        self._condition = None
        self._ledger = _PoolState(max_size + max_overflow)
        self._connections, self._leases, self._created = {}, {}, {}
        self._overflow = set()
        self._creators, self._releases = set(), set()
        self._waiters = self._failures = self._lease_revision = 0
        self._token_provider = self._cluster_manager = self._close_task = None
        self._shutdown_deadline = None

    def _check_owner(self):
        if self._owner != (os.getpid(), threading.get_ident(), asyncio.get_running_loop()):
            raise ProgrammingError('Pool belongs to another process, thread or event loop.')

    async def _resume_metadata(self, strategy, deadline, rejected_token=None):
        token = self._params.get('access_token')
        if self._token_provider is not None:
            token = await self._token_provider.get_token(deadline=deadline,
                force_refresh=rejected_token is not None, rejected_token=rejected_token)
        metadata = [('authorization', 'Bearer ' + token), ('strategy', strategy)]
        if self._params.get('cluster_name'):
            metadata.append(('cluster-name', self._params['cluster_name']))
        return metadata

    async def open(self):
        if self._status != 'new':
            self._check_owner()
            if self._status != 'open':
                raise ProgrammingError('Pool is closed.')
            return self
        self._owner = (os.getpid(), threading.get_ident(), asyncio.get_running_loop())
        self._condition = asyncio.Condition()
        self._status = 'open'
        try:
            config = AsyncConnection(**self._params)
            if config.client_id:
                from .async_oauth import AsyncClientCredentialsTokenProvider
                self._token_provider = AsyncClientCredentialsTokenProvider(
                    client_id=config.client_id, client_secret=config.client_secret,
                    token_url=config.token_url, scope=config.oauth_scope,
                    client_auth_method=config.client_auth_method, timeout=config.oauth_timeout)
            from .async_cluster_manager import AsyncClusterManager
            self._cluster_manager = AsyncClusterManager(
                config.host, config.port, user=config.username or '', password=config.password or '',
                secure_channel=config.secure, ssl_cert=config.ssl_cert,
                cluster_uuid=config.cluster_name, initial_strategy='blue',
                metadata_provider=self._resume_metadata if config._oauth_enabled else None,
                auto_resume_timeout=config.auto_resume_timeout, cleanup_timeout=config.cleanup_timeout)
            # Populate through normal acquisition so reservations and failure cleanup are identical.
            initial = []
            try:
                for _ in range(self.min_size):
                    initial.append(await self.get_connection())
            finally:
                for lease in initial:
                    await self.return_connection(lease)
            return self
        except BaseException:
            await self.close_all()
            raise

    async def _ping(self, connection, deadline):
        async with asyncio.timeout_at(deadline):
            await connection._channel.channel_ready()
            if connection._oauth_enabled:
                await connection._metadata(deadline)
            else:
                await connection.get_session_id(deadline=deadline)

    async def _dispose(self, connection, deadline):
        # A detached physical connection has no public lease; old wrappers and
        # cursors retain their own revoked guard and cannot act on a new checkout.
        connection._lease_guard = None
        connection._state = 'closing'
        connection._close_task = asyncio.current_task()
        try:
            async with asyncio.timeout_at(deadline):
                await connection._dispose()
        except (Exception, asyncio.CancelledError):
            if connection._channel is not None:
                await connection._channel.close()
            connection._state = 'closed'
            connection._client = connection._channel = None

    async def get_connection(self, timeout=None):
        self._check_owner()
        deadline = asyncio.get_running_loop().time() + (self.timeout if timeout is None else validate_positive_timeout(timeout))
        slot = connection = None
        creator = asyncio.current_task()
        try:
            async with asyncio.timeout_at(deadline):
                while True:
                    async with self._condition:
                        if self._status != 'open':
                            raise ProgrammingError('Pool is closed.')
                        slot = next((key for key, value in self._ledger.slots.items() if value == 'idle'), None)
                        if slot is not None:
                            self._ledger.move(slot, 'idle', 'creating')
                            connection = self._connections[slot]
                        else:
                            overflow = len(self._ledger.slots) >= self.max_size
                            slot = self._ledger.reserve()
                            if slot is not None and overflow:
                                self._overflow.add(slot)
                        if slot is not None:
                            self._creators.add(creator)
                            break
                        self._waiters += 1
                        try:
                            await self._condition.wait()
                        finally:
                            self._waiters -= 1
                if connection is not None and asyncio.get_running_loop().time() - self._created[slot] >= self.recycle:
                    await self._dispose(connection, min(deadline, asyncio.get_running_loop().time() + self.cleanup_timeout))
                    connection = None
                if connection is None:
                    connection = AsyncConnection(**self._params)
                    connection._token_provider = self._token_provider
                    connection._owns_token_provider = False
                    connection._cluster_manager = self._cluster_manager
                    connection._owns_cluster_manager = False
                    self._connections[slot] = connection
                    await connection.open()
                    self._created[slot] = asyncio.get_running_loop().time()
                if self.pre_ping:
                    await self._ping(connection, deadline)
                async with self._condition:
                    if self._status != 'open':
                        raise ProgrammingError('Pool closed during connection creation.')
                    self._lease_revision += 1
                    lease = PooledConnection(connection, self, slot, self._lease_revision)
                    self._leases[slot] = lease
                    connection._lease_guard = lease._guard
                    self._ledger.move(slot, 'creating', 'leased')
                    self._creators.discard(creator)
                    slot = None
                    return lease
        except BaseException as error:
            if slot is not None:
                self._failures += 1
                try:
                    await _finish(asyncio.create_task(self._abandon(slot, connection)))
                finally:
                    self._creators.discard(creator)
            self._creators.discard(creator)
            if isinstance(error, TimeoutError):
                raise OperationalError('Pool acquisition deadline expired.') from error
            raise

    async def _abandon(self, slot, connection):
        if connection is not None:
            await self._dispose(connection, min(asyncio.get_running_loop().time() + self.cleanup_timeout,
                                                self._shutdown_deadline or float('inf')))
        async with self._condition:
            self._connections.pop(slot, None)
            self._created.pop(slot, None)
            self._overflow.discard(slot)
            self._ledger.remove(slot)
            self._condition.notify_all()

    async def _release(self, lease, deadline):
        connection, slot = lease._connection, lease._slot
        healthy = True
        try:
            async with asyncio.timeout_at(deadline):
                for call in tuple(connection._calls):
                    call.cancel()
                for cursor in tuple(connection._cursors):
                    healthy = healthy and cursor._state != 'SUBMISSION_UNKNOWN'
                    await cursor._close_owned(deadline)
                    healthy = healthy and cursor.cleanup_error is None
                healthy = (healthy and not connection._routes and not connection._ambiguous_submissions
                           and connection._state == 'open')
        except (Exception, asyncio.CancelledError):
            healthy = False
        dispose = not healthy or slot in self._overflow or self._status != 'open'
        if dispose:
            await self._dispose(connection, min(deadline, self._shutdown_deadline or deadline))
        async with self._condition:
            self._leases.pop(slot, None)
            if dispose:
                self._connections.pop(slot, None)
                self._created.pop(slot, None)
                self._overflow.discard(slot)
                self._ledger.remove(slot)
            else:
                connection._lease_guard = None
                self._ledger.move(slot, 'retiring', 'idle')
            self._condition.notify_all()

    async def return_connection(self, lease):
        self._check_owner()
        if not isinstance(lease, PooledConnection) or lease.pool is not self or asyncio.current_task() is not lease._task:
            raise ProgrammingError('Connection lease belongs to another pool or task.')
        if lease._returned:
            raise ProgrammingError('Connection lease already returned.')
        lease._returned = True
        if lease._cleanup_task is None:
            lease._guard()
            lease._active = False
            self._ledger.move(lease._slot, 'leased', 'retiring')
            lease._cleanup_task = asyncio.create_task(self._release(lease, asyncio.get_running_loop().time() + self.cleanup_timeout))
            self._releases.add(lease._cleanup_task)
            lease._cleanup_task.add_done_callback(self._releases.discard)
        await _finish(lease._cleanup_task)

    @asynccontextmanager
    async def get_connection_context(self, timeout=None):
        lease = await self.get_connection(timeout)
        try:
            yield lease
        finally:
            if not lease._returned:
                await self.return_connection(lease)

    def get_statistics(self):
        self._check_owner()
        counts = self._ledger.counts()
        return dict(counts, closing=counts['retiring'], total_connections=len(self._ledger.slots),
                    waiters=self._waiters, failures=self._failures)

    async def _shutdown(self, deadline):
        async with self._condition:
            self._condition.notify_all()
        creators = tuple(self._creators)
        for task in creators:
            task.cancel()
        jobs = list(self._releases)
        for slot, state in tuple(self._ledger.slots.items()):
            if state == 'leased':
                lease = self._leases[slot]
                lease._active = False
                self._ledger.move(slot, 'leased', 'retiring')
                lease._cleanup_task = asyncio.create_task(self._release(lease, deadline))
                jobs.append(lease._cleanup_task)
            elif state == 'idle':
                self._ledger.move(slot, 'idle', 'retiring')
                jobs.append(asyncio.create_task(self._retire_idle(slot, deadline)))
        try:
            if jobs or creators:
                async with asyncio.timeout_at(deadline):
                    await asyncio.gather(*jobs, *creators, return_exceptions=True)
        except TimeoutError:
            self._failures += 1
        finally:
            for resource in (self._cluster_manager, self._token_provider):
                if resource is not None:
                    try:
                        await resource.close(deadline=deadline)
                    except Exception:
                        self._failures += 1
            self._status = 'closed'

    async def _retire_idle(self, slot, deadline):
        await self._dispose(self._connections[slot], deadline)
        async with self._condition:
            self._connections.pop(slot, None)
            self._created.pop(slot, None)
            self._overflow.discard(slot)
            self._ledger.remove(slot)
            self._condition.notify_all()

    async def close_all(self):
        if self._owner is None and self._status in ('new', 'closed'):
            self._status = 'closed'
            return
        self._check_owner()
        if self._close_task is None:
            self._status = 'closing'
            self._shutdown_deadline = asyncio.get_running_loop().time() + self.cleanup_timeout
            self._close_task = asyncio.create_task(self._shutdown(self._shutdown_deadline))
        await _finish(self._close_task)

    async def __aenter__(self):
        return await self.open()

    async def __aexit__(self, *exc):
        await self.close_all()
