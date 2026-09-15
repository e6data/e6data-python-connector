"""Native asynchronous query lifecycle, with no replay of consumed results."""
import asyncio
from collections import deque
from contextlib import contextmanager
from io import BytesIO

import grpc

from .datainputstream import get_query_columns_info, read_rows_from_chunk
from .e6data_grpc import _escaper
from .exceptions import (AmbiguousSubmissionError, IncompleteResultError,
                         NotSupportedError, OperationalError, ProgrammingError, OAuthError)
from .server import e6x_engine_pb2 as pb


def _metadata_columns(payload):
    return get_query_columns_info(BytesIO(payload))


def _operational(error):
    if isinstance(error, (OperationalError, ProgrammingError, NotSupportedError, OAuthError)):
        return error
    return OperationalError('Query operation failed; inspect the chained cause.')


class AsyncCursor:
    """One ordinary operation at a time; different cursors may run concurrently."""
    def __init__(self, connection, array_size=1000, database=None, catalog_name=None, db_name=None):
        self._connection = connection
        self._public_connection = connection
        self._lease_guard = connection._lease_guard
        self._catalog = connection.catalog if catalog_name is None else catalog_name
        self._database = connection.database if database is None and db_name is None else (database if db_name is None else db_name)
        self.arraysize = array_size
        self._state = 'EMPTY'
        self._route = None
        self._rows = deque()
        self._columns = None
        self._description = None
        self._rowcount = -1
        self._rownumber = 0
        self._failure = None
        self._busy = False
        self._operation_task = None
        self._revision = 0
        self._active_call = None
        self._close_task = None
        self._cleanup_error = None
        connection._cursors.add(self)

    @property
    def connection(self):
        return self._public_connection

    @property
    def arraysize(self):
        return self._arraysize

    @arraysize.setter
    def arraysize(self, value):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError('arraysize must be a positive integer.')
        self._arraysize = value

    @property
    def rownumber(self):
        return self._rownumber

    @property
    def lastrowid(self):
        return None

    @property
    def rowcount(self):
        return self._rowcount

    @property
    def description(self):
        return self._description

    @property
    def query_id(self):
        return self._route.query_id if self._route else None

    @property
    def cleanup_error(self):
        return self._cleanup_error

    def _check(self, fetch=False):
        if self._lease_guard is not None:
            self._lease_guard(internal=False)
        self._connection._check_owner()
        if self._state == 'CLOSED':
            raise ProgrammingError('Cursor is closed.')
        if fetch and self._failure is not None:
            raise self._failure
        if fetch and self._state in ('EMPTY', 'SUBMISSION_UNKNOWN'):
            raise ProgrammingError('No complete query is available for fetching.')

    @contextmanager
    def _operation(self, fetch=False):
        self._check(fetch=fetch)
        if self._busy:
            raise ProgrammingError('A cursor permits one ordinary operation at a time.')
        self._busy = True
        self._operation_task = asyncio.current_task()
        try:
            yield
        finally:
            self._busy = False
            self._operation_task = None

    def _publish(self, revision):
        self._check()
        if revision != self._revision:
            raise asyncio.CancelledError()

    async def _call(self, name, request, deadline, *, safe=False, on_dispatch=None):
        revision = self._revision
        response_metadata = {}
        task = asyncio.create_task(self._connection._rpc(
            name, request, deadline=deadline, route=self._route,
            safe_retry=safe, _on_dispatch=on_dispatch, _response_metadata=response_metadata))
        self._active_call = task
        try:
            result = await task
            self._publish(revision)
            if name in ('prepareStatement', 'prepareStatementV2'):
                self._prepare_strategy = response_metadata['strategy']
            return result
        finally:
            if self._active_call is task:
                self._active_call = None

    def _fail_result(self, reason):
        if self._failure is None:
            self._failure = IncompleteResultError(reason, query_id=self.query_id)
        if self._state != 'CLOSED':
            self._state = 'RESULT_FAILED'
        return self._failure

    def _accept_rows(self, rows):
        self._rows.extend(rows)

    def _take_rows(self, size):
        rows = [self._rows.popleft() for _ in range(min(size, len(self._rows)))]
        self._rownumber += len(rows)
        return rows

    async def _query_request(self, cls, deadline):
        if self._route is None:
            raise ProgrammingError('No query handle is known.')
        session = await self._connection.get_session_id(deadline=deadline)
        return cls(sessionId=session, queryId=self.query_id, engineIP=self._route.engine_ip)

    async def _refresh_metadata(self, deadline):
        from .async_work import run_blocking
        request = await self._query_request(pb.GetResultMetadataRequest, deadline)
        revision = self._revision
        response = await self._call('getResultMetadata', request, deadline, safe=True)
        count, columns = await run_blocking(_metadata_columns, response.resultMetaData, deadline=deadline)
        self._publish(revision)
        description = [(column.get_name(), column.get_field_type(), None, None, None, None, True)
                       for column in columns]
        self._rowcount, self._columns, self._description = count, columns, description

    async def _execute(self, operation, parameters, deadline):
        from .async_connection import QueryRoute
        if self._state != 'EMPTY':
            raise ProgrammingError('Clear the previous query before executing another.')
        if not isinstance(operation, str) or not operation.strip():
            raise ProgrammingError('operation must be a nonempty SQL string.')
        sql = operation.strip().removesuffix(';')
        if parameters is not None:
            sql = sql % _escaper.escape_args(parameters)
        session = await self._connection.get_session_id(deadline=deadline)
        v2 = bool(self._catalog)
        request_type = pb.PrepareStatementV2Request if v2 else pb.PrepareStatementRequest
        fields = dict(sessionId=session, schema=self._database or '', queryString=sql)
        if v2:
            fields['catalog'] = self._catalog
        request = request_type(**fields)
        dispatched = False
        def mark_dispatch():
            nonlocal dispatched
            dispatched = True
        try:
            try:
                response = await self._call('prepareStatementV2' if v2 else 'prepareStatement',
                                            request, deadline, safe=True, on_dispatch=mark_dispatch)
            except grpc.RpcError as error:
                if (self._connection.auto_resume and error.code() == grpc.StatusCode.UNAVAILABLE
                        and error.details() == 'status: 503, cluster is suspended'):
                    # This exact response explicitly denies preparation admission.
                    dispatched = False
                    await self._connection._resume_cluster(deadline)
                    response = await self._call('prepareStatementV2' if v2 else 'prepareStatement',
                                                request, deadline, safe=True, on_dispatch=mark_dispatch)
                else:
                    raise
            if not response.queryId or not response.engineIP:
                raise OperationalError('Preparation returned an incomplete query handle.')
            route = QueryRoute(self._connection.target, response.queryId, response.engineIP,
                               self._prepare_strategy)
            self._connection._register_route(route)
            self._route = route
            self._state = 'ACTIVE'
            self._rows.clear()
            self._columns = self._description = None
            self._rowcount, self._rownumber = -1, 0
            dispatched = False
            execute_type = pb.ExecuteStatementV2Request if v2 else pb.ExecuteStatementRequest
            execute_request = await self._query_request(execute_type, deadline)
            await self._call('executeStatementV2' if v2 else 'executeStatement', execute_request,
                             deadline, on_dispatch=mark_dispatch)
            # Execution succeeded; subsequent metadata failure must retain this known query.
            dispatched = False
            await self._refresh_metadata(deadline)
            return self.query_id
        except asyncio.CancelledError:
            if dispatched:
                if self._state != 'CLOSED':
                    self._state = 'SUBMISSION_UNKNOWN'
                self._connection._ambiguous_submissions.add(self)
            raise
        except Exception as error:
            denied = isinstance(error, grpc.RpcError) and (
                error.code() in (grpc.StatusCode.UNAUTHENTICATED, grpc.StatusCode.PERMISSION_DENIED,
                                 grpc.StatusCode.INVALID_ARGUMENT)
                or (error.code() == grpc.StatusCode.UNKNOWN and error.details() == 'status: 456')
                or (error.code() == grpc.StatusCode.UNAVAILABLE and error.details() == 'status: 503, cluster is suspended'))
            if dispatched and not denied:
                if self._state != 'CLOSED':
                    self._state = 'SUBMISSION_UNKNOWN'
                self._connection._ambiguous_submissions.add(self)
                raise AmbiguousSubmissionError(query_id=self.query_id) from error
            if isinstance(error, (ProgrammingError, OperationalError, OAuthError)):
                raise
            raise _operational(error) from error

    async def execute(self, operation, parameters=None, *, timeout=None, **kwargs):
        if kwargs:
            raise ProgrammingError('Unsupported execute options.')
        with self._operation():
            return await self._execute(operation, parameters, self._connection._deadline(timeout))

    async def executemany(self, operation, seq_of_parameters, *, timeout=None):
        with self._operation():
            deadline = self._connection._deadline(timeout)
            for index, parameters in enumerate(seq_of_parameters):
                try:
                    if index:
                        await self._clear(deadline)
                    await self._execute(operation, parameters, deadline)
                except Exception as error:
                    error.parameter_index = index
                    raise

    async def _decode_batch(self, payload, reservation, revision):
        try:
            rows = await reservation.run(read_rows_from_chunk, self._columns, payload, True)
        except Exception as error:
            raise self._fail_result('decode_failed') from error
        self._publish(revision)
        if rows is None:
            self._state = 'EXHAUSTED'
        return rows

    async def _next_batch(self, deadline):
        from .async_work import reserve_work
        if self._state == 'EXHAUSTED':
            return None
        if self._columns is None:
            await self._refresh_metadata(deadline)
        request = await self._query_request(pb.GetNextResultBatchRequest, deadline)
        reservation = await reserve_work(deadline=deadline)
        consumed = False
        revision = self._revision
        def mark_dispatch():
            nonlocal consumed
            consumed = True
        try:
            response = await self._call('getNextResultBatch', request, deadline, on_dispatch=mark_dispatch)
            payload = response.resultBatch
            if not payload:
                self._state = 'EXHAUSTED'
                return None
            return await self._decode_batch(payload, reservation, revision)
        except asyncio.CancelledError:
            if consumed:
                self._fail_result('ambiguous_result')
            raise
        except IncompleteResultError:
            raise
        except Exception as error:
            if consumed:
                raise self._fail_result('ambiguous_result') from error
            raise
        finally:
            reservation.release()

    async def _fetchmany(self, size, deadline):
        while len(self._rows) < size and self._state != 'EXHAUSTED':
            rows = await self._next_batch(deadline)
            if rows is None:
                break
            try:
                self._accept_rows(rows)
            except Exception as error:
                raise self._fail_result('aggregation_failed') from error
        return self._take_rows(size)

    async def fetchmany(self, size=None, *, timeout=None):
        with self._operation(fetch=True):
            size = self.arraysize if size is None else size
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                raise ProgrammingError('Fetch size must be a nonnegative integer.')
            try:
                return await self._fetchmany(size, self._connection._deadline(timeout))
            except (asyncio.CancelledError, OperationalError, ProgrammingError, OAuthError):
                raise
            except Exception as error:
                raise _operational(error) from error

    async def fetchone(self, *, timeout=None):
        rows = await self.fetchmany(1, timeout=timeout)
        return rows or None

    async def fetch_batch(self, *, timeout=None):
        with self._operation(fetch=True):
            if self._rows:
                return self._take_rows(len(self._rows))
            try:
                rows = await self._next_batch(self._connection._deadline(timeout))
                if rows is not None:
                    self._rownumber += len(rows)
                return rows
            except (asyncio.CancelledError, OperationalError, ProgrammingError, OAuthError):
                raise
            except Exception as error:
                raise _operational(error) from error

    async def fetchall(self, *, timeout=None):
        with self._operation(fetch=True):
            deadline = self._connection._deadline(timeout)
            rows = []
            try:
                while True:
                    if self._rows:
                        rows.extend(self._take_rows(len(self._rows)))
                    batch = await self._next_batch(deadline)
                    if batch is None:
                        return rows
                    rows.extend(batch)
                    self._rownumber += len(batch)
            except asyncio.CancelledError:
                if rows:
                    self._fail_result('aggregation_failed')
                raise
            except Exception as error:
                if rows or self._failure is not None:
                    raise self._fail_result('aggregation_failed') from error
                raise _operational(error) from error

    async def fetchall_buffer(self, query_id=None, *, timeout=None):
        if query_id is not None and query_id != self.query_id:
            raise ProgrammingError('Query handle does not belong to this cursor.')
        while True:
            rows = await self.fetch_batch(timeout=timeout)
            if rows is None:
                return
            yield rows

    def __aiter__(self):
        return self

    async def __anext__(self):
        row = await self.fetchone()
        if row is None:
            raise StopAsyncIteration
        return row

    async def update_mete_data(self, *, timeout=None):
        with self._operation():
            try:
                await self._refresh_metadata(self._connection._deadline(timeout))
            except (asyncio.CancelledError, OperationalError, ProgrammingError, OAuthError):
                raise
            except Exception as error:
                raise _operational(error) from error

    refresh_metadata = update_mete_data

    async def get_rowcount(self, *, timeout=None):
        await self.update_mete_data(timeout=timeout)
        return self.rowcount

    async def get_description(self, *, timeout=None):
        await self.update_mete_data(timeout=timeout)
        return self.description

    async def get_rpc_metadata(self, *, timeout=None):
        with self._operation():
            return await self._connection._metadata(self._connection._deadline(timeout), self._route)

    async def _read_query(self, name, cls, timeout, query_id=None, safe=False):
        with self._operation():
            if query_id is not None and query_id != self.query_id:
                raise ProgrammingError('Query handle does not belong to this cursor.')
            deadline = self._connection._deadline(timeout)
            try:
                request = await self._query_request(cls, deadline)
                return await self._call(name, request, deadline, safe=safe)
            except (asyncio.CancelledError, OperationalError, ProgrammingError, OAuthError):
                raise
            except Exception as error:
                raise _operational(error) from error

    async def status(self, query_id=None, *, timeout=None):
        return await self._read_query('status', pb.StatusRequest, timeout, query_id, safe=True)

    async def explain(self, *, timeout=None):
        return (await self._read_query('explain', pb.ExplainRequest, timeout)).explain

    async def explain_analyse(self, *, timeout=None):
        response = await self._read_query('explainAnalyze', pb.ExplainAnalyzeRequest, timeout)
        return dict(is_cached=response.isCached, parsing_time=response.parsingTime,
                    queuing_time=response.queueingTime, planner=response.explainAnalyze)

    async def get_tables(self, *, timeout=None):
        with self._operation():
            return await self._connection.get_tables(self._catalog, self._database, timeout=timeout)

    async def get_columns(self, table, *, timeout=None):
        with self._operation():
            return await self._connection.get_columns(self._catalog, self._database, table, timeout=timeout)

    async def get_schema_names(self, *, timeout=None):
        with self._operation():
            return await self._connection.get_schema_names(self._catalog, timeout=timeout)

    async def _stop_active(self):
        self._revision += 1
        task = self._operation_task or self._active_call
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _clear(self, deadline, owned=False):
        await self._stop_active()
        if self._route is None:
            if self._state == 'SUBMISSION_UNKNOWN' or self in self._connection._ambiguous_submissions:
                raise AmbiguousSubmissionError()
            return None
        if owned:
            # Owned cleanup has no authority to mint a new legacy session silently.
            session = '' if self._connection._oauth_enabled else self._connection._session_id
            if session is None:
                raise OperationalError('Cleanup has no authenticated legacy session.')
        else:
            session = await self._connection.get_session_id(deadline=deadline)
        request = pb.ClearOrCancelQueryRequest(sessionId=session, queryId=self.query_id, engineIP=self._route.engine_ip)
        response = await self._connection._rpc('clearOrCancelQuery', request, deadline=deadline,
                                              route=self._route, _cleanup=owned)
        self._connection._release_route(self.query_id)
        self._connection._ambiguous_submissions.discard(self)
        self._route = None
        self._rows.clear()
        self._columns = self._description = None
        self._rowcount, self._rownumber = -1, 0
        self._failure = self._cleanup_error = None
        if self._state != 'CLOSED':
            self._state = 'EMPTY'
        return response

    async def clear(self, query_id=None, *, timeout=None):
        self._check()
        if query_id is not None and query_id != self.query_id:
            raise ProgrammingError('Query handle does not belong to this cursor.')
        deadline = self._connection._deadline(self._connection.cleanup_timeout if timeout is None else min(timeout, self._connection.cleanup_timeout))
        try:
            async with asyncio.timeout_at(deadline):
                return await self._clear(deadline)
        except (asyncio.CancelledError, OperationalError, ProgrammingError, OAuthError):
            raise
        except Exception as error:
            raise _operational(error) from error

    async def cancel(self, query_id=None, *, timeout=None):
        self._check()
        if query_id is not None and query_id != self.query_id:
            raise ProgrammingError('Query handle does not belong to this cursor.')
        if self._route is None:
            raise ProgrammingError('No query handle is known.')
        deadline = self._connection._deadline(timeout)
        try:
            async with asyncio.timeout_at(deadline):
                await self._stop_active()
                request = await self._query_request(pb.CancelQueryRequest, deadline)
                await self._connection._rpc('cancelQuery', request, deadline=deadline, route=self._route)
                self._fail_result('cancelled_result')
        except (asyncio.CancelledError, OperationalError, ProgrammingError, OAuthError):
            raise
        except Exception as error:
            raise _operational(error) from error

    async def _close_owned(self, deadline):
        if self._state == 'CLOSED':
            return
        unknown_without_handle = self._state == 'SUBMISSION_UNKNOWN' and self._route is None
        if unknown_without_handle:
            self._connection._ambiguous_submissions.add(self)
        self._state = 'CLOSED'
        try:
            async with asyncio.timeout_at(deadline):
                await self._stop_active()
                if self._route is None and self in self._connection._ambiguous_submissions:
                    raise AmbiguousSubmissionError()
                await self._clear(deadline, owned=True)
        except asyncio.CancelledError:
            self._cleanup_error = OperationalError('Query cleanup is unconfirmed.')
            raise
        except Exception:
            self._cleanup_error = OperationalError('Query cleanup is unconfirmed.')
        finally:
            self._rows.clear()
            self._connection._cursors.discard(self)

    async def close(self):
        if self._lease_guard is not None:
            self._lease_guard(internal=False)
        self._connection._check_owner(_cleanup=True)
        if self._state == 'CLOSED':
            return
        self._connection._check_owner()
        deadline = self._connection._deadline(self._connection.cleanup_timeout)
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close_owned(deadline))
        try:
            await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            await asyncio.shield(self._close_task)
            raise

    async def __aenter__(self):
        self._check()
        return self

    async def __aexit__(self, *exc):
        await self.close()

    def setinputsizes(self, sizes):
        return None

    def setoutputsize(self, size, column=None):
        return None

    async def poll(self, *args, **kwargs):
        raise NotSupportedError('Query polling is not implemented.')

    async def fetch_logs(self, *args, **kwargs):
        raise NotSupportedError('Query log retrieval is not implemented.')
