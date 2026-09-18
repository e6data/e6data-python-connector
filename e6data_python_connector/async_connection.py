"""Native asyncio connection with connection-owned authentication and routing."""
import asyncio
import os
import sys
import threading
from functools import wraps
from dataclasses import dataclass
from types import MappingProxyType

import grpc

from .exceptions import NotSupportedError, OperationalError, ProgrammingError
from .oauth_common import validate_positive_timeout, validate_token_endpoint
from .server import e6x_engine_pb2 as pb, e6x_engine_pb2_grpc as bindings


@dataclass(frozen=True)
class QueryRoute:
    target: str
    query_id: str
    engine_ip: str
    strategy: str


def _read_certificate(path):
    with open(path, 'rb') as source:
        return source.read()


def is_strategy_mismatch(code, details, *, oauth):
    return code == grpc.StatusCode.UNKNOWN and (details == 'status: 456' if oauth else 'status: 456' in (details or ''))


def _public_errors(method):
    @wraps(method)
    async def operation(*args, **kwargs):
        try:
            return await method(*args, **kwargs)
        except (grpc.RpcError, TimeoutError) as error:
            raise OperationalError('Async connection operation failed.') from error
    return operation


class AsyncConnection:
    """Construct locally; await open before using the native generated client."""
    def __init__(self, host, port, username=None, password=None, catalog=None,
                 database=None, cluster_name=None, secure=False, ssl_cert=None,
                 auto_resume=True, scheme='e6data', grpc_options=None, debug=False,
                 require_fastbinary=True, client_id=None, client_secret=None,
                 token_url=None, oauth_scope=None, access_token=None,
                 client_auth_method='basic', *, operation_timeout=600.0,
                 oauth_timeout=10.0, cleanup_timeout=10.0, auto_resume_timeout=300.0,
                 max_receive_message_bytes=64 * 1024 * 1024,
                 enable_result_batch_v2=False):
        if sys.version_info < (3, 11):
            raise RuntimeError('The async API requires Python 3.11 or newer.')
        try:
            import httpx  # noqa: F401 - optional dependency checked only on async use
        except ImportError:
            raise ImportError('Install e6data-python-connector[async] for the async API.') from None
        if not isinstance(host, str) or not host or not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536:
            raise ValueError('host and a valid port are required.')
        modes = [username is not None or password is not None,
                 any(v is not None for v in (client_id, client_secret, token_url, oauth_scope)),
                 access_token is not None]
        if sum(modes) != 1:
            raise ValueError('Supply exactly one complete authentication method.')
        if modes[0] and (not username or not password):
            raise ValueError('username and password are required.')
        if modes[1]:
            if not client_id or not client_secret or not token_url:
                raise ValueError('client_id, client_secret and token_url are required.')
            validate_token_endpoint(token_url)
        if client_auth_method not in ('basic', 'post'):
            raise ValueError('client_auth_method must be basic or post.')
        if modes[2] and (not isinstance(access_token, str) or not access_token or not access_token.isascii() or any(ord(c) <= 32 or ord(c) == 127 for c in access_token)):
            raise ValueError('access_token must be a nonempty ASCII bearer token.')
        if not modes[0] and not secure:
            raise ValueError('Async OAuth requires verified TLS (secure=True).')
        if ssl_cert is not None and not isinstance(ssl_cert, (str, bytes)):
            raise ValueError('ssl_cert must be a certificate path or PEM bytes.')
        if not isinstance(enable_result_batch_v2, bool):
            raise ValueError('enable_result_batch_v2 must be a boolean.')
        settings = dict(host=host, port=port, username=username, password=password,
                        catalog=catalog, database=database, cluster_name=cluster_name,
                        secure=bool(secure), ssl_cert=ssl_cert, auto_resume=auto_resume,
                        scheme=scheme, debug=debug, require_fastbinary=require_fastbinary,
                        client_id=client_id, client_secret=client_secret, token_url=token_url,
                        oauth_scope=oauth_scope, access_token=access_token,
                        client_auth_method=client_auth_method,
                        enable_result_batch_v2=enable_result_batch_v2)
        for name, value in [('operation_timeout', operation_timeout), ('oauth_timeout', oauth_timeout),
                            ('cleanup_timeout', cleanup_timeout), ('auto_resume_timeout', auto_resume_timeout)]:
            settings[name] = validate_positive_timeout(value, name)
        if isinstance(max_receive_message_bytes, bool) or not isinstance(max_receive_message_bytes, int) or max_receive_message_bytes <= 0:
            raise ValueError('max_receive_message_bytes must be a positive integer.')
        options = dict(grpc_options or {})
        for name in ('max_receive_message_length', 'grpc.max_receive_message_length'):
            if name in options:
                if options[name] != max_receive_message_bytes:
                    raise ValueError('Set the finite receive limit using max_receive_message_bytes.')
                del options[name]
        # Authority overrides can disable meaningful server identity validation.
        if any(name.removeprefix('grpc.') in ('ssl_target_name_override', 'default_authority') for name in options):
            raise ValueError('TLS authority overrides are unsupported.')
        self.grpc_prepare_timeout = validate_positive_timeout(options.pop('grpc_prepare_timeout', operation_timeout))
        settings['grpc_options'] = MappingProxyType(options)
        settings['max_receive_message_bytes'] = max_receive_message_bytes
        self._config = MappingProxyType(settings)
        self._oauth_enabled = not modes[0]
        self._channel = self._client = self._token_provider = None
        self._owns_token_provider = True
        self._owner = None
        self._state = 'new'
        self._open_task = None
        self._open_waiters = 0
        self._session_id = None
        self._session_task = None
        self._session_waiters = 0
        self._session_retiring = False
        self._strategy = 'blue'
        self._pending_strategy = None
        self._routes = {}
        self._ambiguous_submissions = set()
        self._cursors = set()
        self._calls = set()
        self._lease_guard = None
        self._close_task = None
        self._cleanup_error = None
        self._cluster_manager = None
        self._owns_cluster_manager = True

    def __getattr__(self, name):
        config = self.__dict__.get('_config', {})
        if name in config:
            return config[name]
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name in self.__dict__.get('_config', {}):
            raise AttributeError('Connection configuration is read-only.')
        object.__setattr__(self, name, value)

    @property
    def target(self):
        host = '[{}]'.format(self.host) if ':' in self.host and not self.host.startswith('[') else self.host
        return '{}:{}'.format(host, self.port)

    @property
    def strategy(self):
        return self._strategy

    @property
    def cleanup_error(self):
        return self._cleanup_error

    @property
    def client(self):
        self._check_owner()
        return self._client

    def _check_owner(self, _cleanup=False, _internal=False):
        if self._owner != (os.getpid(), threading.get_ident(), asyncio.get_running_loop()):
            raise ProgrammingError('Connection belongs to another process, thread or event loop.')
        cleanup = _cleanup or (self._state == 'closing' and asyncio.current_task() is self._close_task)
        if self._state != 'open' and not cleanup:
            raise ProgrammingError('Connection is not open.')
        if self._lease_guard is not None and not cleanup:
            self._lease_guard(internal=_internal)

    def _deadline(self, timeout=None):
        self._check_owner()
        budget = self.operation_timeout if timeout is None else min(self.operation_timeout, validate_positive_timeout(timeout))
        return asyncio.get_running_loop().time() + budget

    @staticmethod
    def _remaining(deadline):
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError('Connection operation deadline expired.')
        return remaining

    async def open(self):
        owner = (os.getpid(), threading.get_ident(), asyncio.get_running_loop())
        if self._owner is not None and self._owner != owner:
            raise ProgrammingError('Connection belongs to another process, thread or event loop.')
        if self._state == 'open':
            self._check_owner()
            return self
        if self._state == 'new':
            self._owner = owner
            self._state = 'opening'
            deadline = asyncio.get_running_loop().time() + self.operation_timeout
            self._open_task = asyncio.create_task(self._initialize(deadline))
        elif self._state != 'opening':
            raise ProgrammingError('Use reopen explicitly for a closed connection.')
        task = self._open_task
        self._open_waiters += 1
        try:
            await asyncio.shield(task)
            self._check_owner()
            return self
        except asyncio.CancelledError:
            if not asyncio.current_task().cancelling() and self._state != 'closing':
                raise ProgrammingError('Connection initialization was cancelled; reopen explicitly.') from None
            raise
        finally:
            self._open_waiters -= 1
            if self._open_waiters == 0 and not task.done():
                # A cancelled last opener cannot leave an ownerless initialization.
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                if self._state == 'opening':
                    self._state = 'closed'

    async def _initialize(self, deadline):
        channel = None
        try:
            certificate = self.ssl_cert
            if isinstance(certificate, str):
                from .async_work import run_blocking
                certificate = await run_blocking(_read_certificate, certificate, deadline=deadline)
            self._remaining(deadline)
            if self._state != 'opening' or self._open_task is not asyncio.current_task():
                raise asyncio.CancelledError()
            options = [('grpc.' + key.removeprefix('grpc.'), value) for key, value in self.grpc_options.items()]
            options.append(('grpc.max_receive_message_length', self.max_receive_message_bytes))
            if self.secure:
                channel = grpc.aio.secure_channel(self.target, grpc.ssl_channel_credentials(root_certificates=certificate), options=options)
            else:
                channel = grpc.aio.insecure_channel(self.target, options=options)
            client = bindings.QueryEngineServiceStub(channel)
            if self.client_id and self._token_provider is None:
                from .async_oauth import AsyncClientCredentialsTokenProvider
                self._token_provider = AsyncClientCredentialsTokenProvider(
                    client_id=self.client_id, client_secret=self.client_secret,
                    token_url=self.token_url, scope=self.oauth_scope,
                    client_auth_method=self.client_auth_method, timeout=self.oauth_timeout)
            # No await between validation, construction and atomic publication.
            self._channel, self._client = channel, client
            self._state = 'open'
        except BaseException:
            if channel is not None:
                await channel.close()
            if self._state == 'opening':
                self._state = 'closed'
            raise

    async def __aenter__(self):
        return await self.open()

    async def __aexit__(self, *exc):
        await self.close()

    def check_connection(self):
        return self._state == 'open'

    def check_strategy_change(self):
        self._check_owner()
        return self._apply_pending_strategy()

    def _apply_pending_strategy(self):
        if not self._routes and self._pending_strategy:
            self._strategy, self._pending_strategy = self._pending_strategy, None
            self._session_id = None
        return self._strategy

    def _register_route(self, route):
        self._check_owner()
        if not isinstance(route, QueryRoute) or route.target != self.target or not route.query_id or route.strategy not in ('blue', 'green'):
            raise ProgrammingError('Invalid query route.')
        if route.query_id in self._routes and self._routes[route.query_id] != route:
            raise ProgrammingError('Query route is already registered.')
        self._routes[route.query_id] = route
        return route

    def _release_route(self, query_id):
        self._routes.pop(query_id, None)
        if self._state == 'open':
            self._apply_pending_strategy()

    def _route(self, query_id, engine_ip=None):
        self._check_owner()
        route = self._routes.get(query_id)
        if route is None or (engine_ip is not None and engine_ip != route.engine_ip):
            raise ProgrammingError('Query is not registered with this connection and engine.')
        return route

    async def _metadata(self, deadline, route=None, _cleanup=False):
        self._check_owner(_cleanup=_cleanup, _internal=True)
        self._remaining(deadline)
        if route is not None and self._routes.get(route.query_id) != route:
            raise ProgrammingError('Query route is not owned by this connection.')
        metadata = [('strategy', route.strategy if route else self._strategy)]
        if route and route.engine_ip:
            metadata.append(('plannerip', route.engine_ip))
        if self.cluster_name:
            metadata.append(('cluster-name', self.cluster_name))
        if self._oauth_enabled:
            token = self.access_token
            if self._token_provider is not None:
                token = await self._token_provider.get_token(deadline=deadline)
            metadata.append(('authorization', 'Bearer ' + token))
        self._check_owner(_cleanup=_cleanup, _internal=True)
        return metadata

    async def _rpc(self, method_name, request, *, deadline, route=None, safe_retry=False, _cleanup=False, _on_dispatch=None, _response_metadata=None):
        self._check_owner(_cleanup=_cleanup, _internal=True)
        refreshed = switched = False
        while True:
            metadata = await self._metadata(deadline, route, _cleanup=_cleanup)
            remaining = self._remaining(deadline)
            if _on_dispatch is not None:
                _on_dispatch()
            call = getattr(self._client, method_name)(request, metadata=metadata, timeout=remaining)
            self._calls.add(call)
            try:
                response = await call
                self._check_owner(_cleanup=_cleanup, _internal=True)
                if _response_metadata is not None:
                    _response_metadata.update(metadata)
                new_strategy = getattr(response, 'new_strategy', None)
                if new_strategy in ('blue', 'green'):
                    self._pending_strategy = new_strategy
                    if method_name not in ('prepareStatement', 'prepareStatementV2'):
                        self._apply_pending_strategy()
                return response
            except grpc.RpcError as error:
                if safe_retry and self._token_provider is not None and not refreshed and error.code() == grpc.StatusCode.UNAUTHENTICATED:
                    token = dict(metadata).get('authorization', '')[7:]
                    await self._token_provider.get_token(force_refresh=True, deadline=deadline, rejected_token=token)
                    refreshed = True
                    continue
                if safe_retry and route is None and not switched and is_strategy_mismatch(error.code(), error.details(), oauth=self._oauth_enabled):
                    self._strategy = 'green' if self._strategy == 'blue' else 'blue'
                    switched = True
                    continue
                raise
            finally:
                self._calls.discard(call)

    async def _resume_cluster(self, deadline):
        self._check_owner()
        if self._cluster_manager is None:
            from .async_cluster_manager import AsyncClusterManager

            async def metadata_provider(strategy, deadline, rejected_token=None):
                if rejected_token is not None and self._token_provider is not None:
                    await self._token_provider.get_token(force_refresh=True, deadline=deadline,
                                                         rejected_token=rejected_token)
                metadata = await self._metadata(deadline)
                return [(key, strategy if key == 'strategy' else value) for key, value in metadata]

            self._cluster_manager = AsyncClusterManager(
                self.host, self.port, user=self.username or '', password=self.password or '',
                secure_channel=self.secure, cluster_uuid=self.cluster_name,
                ssl_cert=self.ssl_cert, metadata_provider=metadata_provider if self._oauth_enabled else None,
                initial_strategy=self.strategy, auto_resume_timeout=self.auto_resume_timeout,
                cleanup_timeout=self.cleanup_timeout)
        result = await self._cluster_manager.resume(deadline=deadline)
        strategy = self._cluster_manager.last_successful_strategy
        if result and strategy in ('blue', 'green'):
            if strategy != self._strategy:
                self._session_id = None
            self._strategy, self._pending_strategy = strategy, None
        return result

    async def _authenticate(self):
        deadline = asyncio.get_running_loop().time() + self.operation_timeout
        response = await self._rpc('authenticate', pb.AuthenticateRequest(user=self.username, password=self.password), deadline=deadline, safe_retry=True)
        if not response.sessionId:
            raise OperationalError('Authentication returned an empty session.')
        self._session_id = response.sessionId
        return self._session_id

    @_public_errors
    async def get_session_id(self, *, timeout=None, deadline=None):
        self._check_owner()
        if self._oauth_enabled:
            return ''
        if self._session_id:
            return self._session_id
        deadline = self._deadline(timeout) if deadline is None else deadline
        while self._session_retiring and self._session_task is not None:
            retiring = self._session_task
            # Waiting for terminal state does not inherit that task's cancellation.
            done, _ = await asyncio.wait({retiring}, timeout=self._remaining(deadline))
            if not done:
                raise TimeoutError('Session retirement deadline expired.')
            self._check_owner()
            if self._session_task is retiring:
                self._session_task = None
                self._session_retiring = False
        if self._session_task is None:
            self._session_task = asyncio.create_task(self._authenticate())
        task = self._session_task
        self._session_waiters += 1
        try:
            async with asyncio.timeout_at(deadline):
                return await asyncio.shield(task)
        finally:
            self._session_waiters -= 1
            if self._session_waiters == 0:
                self._session_retiring = True
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                if self._session_task is task:
                    self._session_task = None
                    self._session_retiring = False

    @_public_errors
    async def get_re_authenticate_session_id(self, *, timeout=None):
        self._check_owner()
        self._session_id = None
        return await self.get_session_id(timeout=timeout)

    async def _discovery(self, method, message, timeout, **fields):
        deadline = self._deadline(timeout)
        fields['sessionId'] = await self.get_session_id(deadline=deadline)
        return await self._rpc(method, message(**fields), deadline=deadline, safe_retry=True)

    @_public_errors
    async def get_tables(self, catalog, database, *, timeout=None):
        response = await self._discovery('getTablesV2', pb.GetTablesV2Request, timeout, catalog=catalog or '', schema=database or '')
        return list(response.tables)

    @_public_errors
    async def get_columns(self, catalog, database, table, *, timeout=None):
        response = await self._discovery('getColumnsV2', pb.GetColumnsV2Request, timeout, catalog=catalog or '', schema=database or '', table=table)
        return [{'fieldName': item.fieldName, 'fieldType': item.fieldType} for item in response.fieldInfo]

    @_public_errors
    async def get_schema_names(self, catalog, *, timeout=None):
        response = await self._discovery('getSchemaNamesV2', pb.GetSchemaNamesV2Request, timeout, catalog=catalog or '')
        return list(response.schemas)

    @_public_errors
    async def dry_run(self, query, *, timeout=None):
        fields = dict(schema=self.database or '', queryString=query)
        if self.catalog:
            fields['catalog'] = self.catalog
        response = await self._discovery(
            'dryRunV2' if self.catalog else 'dryRun',
            pb.DryRunRequestV2 if self.catalog else pb.DryRunRequest, timeout, **fields)
        return response.dryrunValue

    @_public_errors
    async def clear(self, query_id, engine_ip=None, *, timeout=None):
        route = self._route(query_id, engine_ip)
        deadline = self._deadline(self.cleanup_timeout if timeout is None else min(self.cleanup_timeout, validate_positive_timeout(timeout)))
        session = await self.get_session_id(deadline=deadline)
        await self._rpc('clear', pb.ClearRequest(sessionId=session, queryId=query_id, engineIP=route.engine_ip), deadline=deadline, route=route)
        self._release_route(query_id)

    @_public_errors
    async def query_cancel(self, engine_ip, query_id, *, timeout=None):
        route = self._route(query_id, engine_ip)
        deadline = self._deadline(timeout)
        session = await self.get_session_id(deadline=deadline)
        await self._rpc('cancelQuery', pb.CancelQueryRequest(sessionId=session, queryId=query_id, engineIP=route.engine_ip), deadline=deadline, route=route)

    def cursor(self, catalog_name=None, db_name=None):
        self._check_owner()
        from .async_cursor import AsyncCursor
        cursor = AsyncCursor(self, catalog_name=catalog_name, db_name=db_name)
        self._cursors.add(cursor)
        return cursor

    async def commit(self):
        self._check_owner()

    async def rollback(self):
        self._check_owner()
        raise NotSupportedError('Transactions are not supported.')

    async def _dispose(self):
        deadline = asyncio.get_running_loop().time() + self.cleanup_timeout
        try:
            async with asyncio.timeout_at(deadline):
                if self._open_task is not None and not self._open_task.done():
                    self._open_task.cancel()
                    await asyncio.gather(self._open_task, return_exceptions=True)
                if self._session_task:
                    self._session_task.cancel()
                    await asyncio.gather(self._session_task, return_exceptions=True)
                for call in tuple(self._calls):
                    call.cancel()
                # One owner deadline bounds cleanup across every known cursor.
                for cursor in tuple(self._cursors):
                    try:
                        await cursor._close_owned(deadline)
                    except Exception:
                        pass
                for route in tuple(self._routes.values()):
                    try:
                        await self.clear(route.query_id, route.engine_ip,
                                         timeout=self._remaining(deadline))
                    except Exception:
                        pass
        except TimeoutError:
            self._cleanup_error = OperationalError('Connection cleanup deadline expired.')
        finally:
            # Native channel close with no grace cancels transports without waiting.
            if self._channel is not None:
                await self._channel.close()
            for resource, owned in ((self._cluster_manager, self._owns_cluster_manager),
                                    (self._token_provider, self._owns_token_provider)):
                if owned and resource is not None:
                    try:
                        await resource.close(deadline=deadline)
                    except Exception:
                        self._cleanup_error = OperationalError('Owned resource disposal is unconfirmed.')
            if self._routes or self._ambiguous_submissions:
                self._cleanup_error = OperationalError('Remote query cleanup is unconfirmed.')
            self._state = 'closed'
            self._client = self._channel = None

    async def close(self):
        if self._owner is not None:
            if self._owner != (os.getpid(), threading.get_ident(), asyncio.get_running_loop()):
                raise ProgrammingError('Connection belongs to another process, thread or event loop.')
            if self._lease_guard is not None:
                self._lease_guard(internal=False)
        if self._state in ('new', 'closed'):
            self._state = 'closed'
            return
        if self._close_task is None:
            if self._state != 'opening':
                self._check_owner()
            self._state = 'closing'
            self._close_task = asyncio.create_task(self._dispose())
        try:
            await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            await asyncio.shield(self._close_task)
            raise

    async def reopen(self):
        if self._routes or self._ambiguous_submissions:
            raise ProgrammingError('Cannot reopen while queries remain unresolved.')
        if self._owner is not None and self._owner != (os.getpid(), threading.get_ident(), asyncio.get_running_loop()):
            raise ProgrammingError('Connection belongs to another owner.')
        await self.close()
        self._state = 'new'
        self._session_id = self._session_task = self._close_task = self._open_task = None
        if self._owns_token_provider:
            self._token_provider = None
        if self._owns_cluster_manager:
            self._cluster_manager = None
        return await self.open()
