"""Native async cluster recovery with owner-scoped mutation tracking."""
import asyncio
import math
import os
import threading

import grpc

from .cluster_server import cluster_pb2 as pb, cluster_pb2_grpc as bindings
from .exceptions import OperationalError, ProgrammingError
from .oauth_common import validate_positive_timeout


def is_strategy_mismatch(error):
    return error.code() == grpc.StatusCode.UNKNOWN and error.details() == 'status: 456'


def is_suspended_error(error):
    return (error.code() == grpc.StatusCode.UNAVAILABLE
            and error.details() == 'status: 503, cluster is suspended')


def _remaining(deadline):
    result = deadline - asyncio.get_running_loop().time()
    if result <= 0:
        raise TimeoutError('Cluster recovery deadline exceeded; dispatched resume may still complete.')
    return result


def _read_certificate(path):
    with open(path, 'rb') as source:
        return source.read()


class _ResumeState:
    """Mutation state deliberately outlives any individual recovery flight."""
    def __init__(self):
        self.pending = None

    def observe(self, status):
        if status not in ('active', 'suspended', 'resuming'):
            raise RuntimeError('Cluster returned failed or unsupported status: {!r}'.format(status))
        if status == 'active':
            self.pending = None
        return status == 'suspended' and self.pending is None

    def dispatched(self):
        self.pending = 'unknown'

    def acknowledged(self):
        self.pending = 'acknowledged'


class _ResumeFlight:
    """One phase deadline, independently bounded shielded waiters."""
    def __init__(self, timeout):
        self.timeout = timeout
        self.task = None
        self.waiters = 0
        self.retiring = False

    @staticmethod
    def _consume_result(task):
        if not task.cancelled():
            task.exception()

    async def wait(self, work, deadline):
        # Last-waiter disposal must finish before a replacement can start.
        while self.retiring and self.task is not None:
            retiring_task = self.task
            try:
                async with asyncio.timeout_at(deadline):
                    await asyncio.shield(retiring_task)
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            except Exception:
                if not retiring_task.done():
                    raise
            if self.task is retiring_task and retiring_task.done():
                self.task = None
                self.retiring = False
        if deadline is not None:
            _remaining(deadline)
        if self.task is None or (self.task.done() and self.waiters == 0):
            phase_deadline = asyncio.get_running_loop().time() + self.timeout
            self.task = asyncio.create_task(work(phase_deadline))
            self.task.add_done_callback(self._consume_result)
        task = self.task
        self.waiters += 1
        try:
            async with asyncio.timeout_at(deadline):
                return await asyncio.shield(task)
        finally:
            self.waiters -= 1
            if self.waiters == 0 and not task.done():
                self.retiring = True
                task.cancel()


class AsyncClusterManager:
    """Local constructor; channels belong to the first invoking loop/thread/process.

    Sharing this explicit object shares recovery only within its target and auth
    owner. OAuth metadata providers must be async and own their refresh policy.
    """
    def __init__(self, host, port, user='', password='', secure_channel=False,
                 timeout=300, cluster_uuid=None, grpc_options=None, debug=False,
                 ssl_cert=None, metadata_provider=None, initial_strategy=None,
                 auto_resume_timeout=None, cleanup_timeout=5):
        if not isinstance(host, str) or not host or isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
            raise ValueError('host and a valid port are required.')
        if metadata_provider is not None and not secure_channel:
            raise ValueError('Async OAuth cluster recovery requires verified TLS.')
        if metadata_provider is not None and (user or password):
            raise ValueError('OAuth and password authentication cannot be combined.')
        if metadata_provider is None and (not user or not password):
            raise ValueError('user and password are required for legacy recovery.')
        if initial_strategy not in (None, 'blue', 'green'):
            raise ValueError('initial_strategy must be blue or green.')
        if ssl_cert is not None and not isinstance(ssl_cert, (str, bytes)):
            raise ValueError('ssl_cert must be a certificate path or PEM bytes.')
        options = dict(grpc_options or {})
        if any(key.removeprefix('grpc.') in ('ssl_target_name_override', 'default_authority') for key in options):
            raise ValueError('TLS authority overrides are unsupported.')
        limit = options.get('grpc.max_receive_message_length', 64 * 1024 * 1024)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError('A finite positive receive limit is required.')
        options['grpc.max_receive_message_length'] = limit
        self._host, self._port = host, port
        self._user, self._password = user, password
        self._secure_channel, self._ssl_cert = secure_channel, ssl_cert
        self._grpc_options = tuple(options.items())
        self.cluster_uuid = cluster_uuid
        self._metadata_provider = metadata_provider
        self.last_successful_strategy = initial_strategy
        self._timeout = validate_positive_timeout(timeout if auto_resume_timeout is None else auto_resume_timeout)
        self._cleanup_timeout = validate_positive_timeout(cleanup_timeout)
        self._flight = _ResumeFlight(self._timeout)
        self._mutation = _ResumeState()
        self._owner = None
        self._closed = False

    def _check_owner(self):
        owner = (os.getpid(), threading.get_ident(), asyncio.get_running_loop())
        if self._owner is None:
            self._owner = owner
        elif self._owner != owner:
            raise ProgrammingError('AsyncClusterManager cannot cross loops, threads or processes.')
        if self._closed:
            raise ProgrammingError('AsyncClusterManager is closed.')

    async def resume(self, *, timeout=None, deadline=None):
        self._check_owner()
        if deadline is not None and (isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline)):
            raise ValueError('deadline must be finite.')
        if timeout is not None:
            bound = asyncio.get_running_loop().time() + validate_positive_timeout(timeout)
            deadline = bound if deadline is None else min(bound, deadline)
        try:
            if deadline is not None:
                _remaining(deadline)
            return await self._flight.wait(self._recover, deadline)
        except (TimeoutError, grpc.RpcError) as error:
            raise OperationalError('Cluster recovery failed; a dispatched resume may still complete.') from error

    async def _metadata(self, strategy, deadline, rejected_token=None):
        _remaining(deadline)
        if self._metadata_provider is not None:
            async with asyncio.timeout_at(deadline):
                if rejected_token is None:
                    return await self._metadata_provider(strategy, deadline)
                return await self._metadata_provider(strategy, deadline, rejected_token=rejected_token)
        values = [('strategy', strategy)]
        if self.cluster_uuid:
            values.append(('cluster-name', self.cluster_uuid))
        return values

    async def _request(self, client, operation, deadline):
        request_type = pb.ClusterStatusRequest if operation == 'status' else pb.ResumeRequest
        request = request_type() if self._metadata_provider else request_type(user=self._user, password=self._password)
        first = self.last_successful_strategy or 'blue'
        refreshed = False
        for strategy in (first, 'green' if first == 'blue' else 'blue'):
            metadata = await self._metadata(strategy, deadline)
            while True:
                try:
                    remaining = _remaining(deadline)
                    if operation == 'resume':
                        self._mutation.dispatched()
                    response = await getattr(client, operation)(request, metadata=metadata, timeout=remaining)
                    if operation == 'resume':
                        self._mutation.acknowledged()
                    self.last_successful_strategy = strategy
                    return response
                except grpc.RpcError as error:
                    if (error.code() == grpc.StatusCode.UNAUTHENTICATED and not refreshed
                            and self._metadata_provider is not None):
                        refreshed = True
                        rejected = dict(metadata).get('authorization', '')[len('Bearer '):]
                        replacement = await self._metadata(strategy, deadline, rejected)
                        if replacement is not None:
                            metadata = replacement
                            continue
                    if strategy == first and is_strategy_mismatch(error):
                        break
                    raise

    async def _recover(self, deadline):
        channel = None
        try:
            async with asyncio.timeout_at(deadline):
                certificate = self._ssl_cert
                if isinstance(certificate, str):
                    from .async_work import run_blocking
                    certificate = await run_blocking(_read_certificate, certificate, deadline=deadline)
                target = '{}:{}'.format(self._host, self._port)
                if self._secure_channel:
                    channel = grpc.aio.secure_channel(target, grpc.ssl_channel_credentials(root_certificates=certificate), options=self._grpc_options)
                else:
                    channel = grpc.aio.insecure_channel(target, options=self._grpc_options)
                client = bindings.ClusterServiceStub(channel)
                while True:
                    response = await self._request(client, 'status', deadline)
                    should_resume = self._mutation.observe(response.status)
                    if response.status == 'active':
                        return True
                    if should_resume:
                        try:
                            result = await self._request(client, 'resume', deadline)
                            self._mutation.observe(result.status)
                            # Only a status read resolves readiness, even if resume says active.
                            self._mutation.acknowledged()
                        except grpc.RpcError as error:
                            if error.code() not in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED, grpc.StatusCode.CANCELLED):
                                raise
                        continue
                    await asyncio.sleep(min(1.0, _remaining(deadline)))
        finally:
            if channel is not None:
                async with asyncio.timeout(self._cleanup_timeout):
                    await channel.close()

    async def close(self, *, deadline=None):
        if self._owner is not None:
            owner = (os.getpid(), threading.get_ident(), asyncio.get_running_loop())
            if self._owner != owner:
                raise ProgrammingError('AsyncClusterManager cannot cross loops, threads or processes.')
        if self._closed and (self._flight.task is None or self._flight.task.done()):
            return
        if not self._closed:
            self._check_owner()
        self._closed = True
        bound = asyncio.get_running_loop().time() + self._cleanup_timeout
        deadline = bound if deadline is None else min(bound, deadline)
        task = self._flight.task
        if task is not None:
            task.cancel()
            try:
                async with asyncio.timeout_at(deadline):
                    await asyncio.shield(task)
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
            except Exception:
                if not task.done():
                    raise
