"""Pure state and real asyncio coordination contracts; no transport doubles."""
import asyncio
import unittest

from e6data_python_connector.async_cluster_manager import AsyncClusterManager, _ResumeState, _ResumeFlight


class ResumeStateTests(unittest.TestCase):
    def test_oauth_requires_tls_before_channel_creation(self):
        with self.assertRaises(ValueError):
            AsyncClusterManager('localhost', 443, metadata_provider=lambda: None)

    def test_pending_resume_survives_suspended_until_ready(self):
        state = _ResumeState()
        self.assertTrue(state.observe('suspended'))
        state.dispatched()
        self.assertEqual(state.pending, 'unknown')
        self.assertFalse(state.observe('suspended'))
        state.acknowledged()
        self.assertEqual(state.pending, 'acknowledged')
        self.assertFalse(state.observe('resuming'))
        self.assertFalse(state.observe('active'))
        self.assertIsNone(state.pending)
        self.assertTrue(state.observe('suspended'))

    def test_unsupported_states_fail_closed(self):
        for value in ('failed', 'ready', 'ACTIVE', '', None):
            with self.assertRaises(RuntimeError):
                _ResumeState().observe(value)


class FlightTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_waiter_does_not_shorten_phase(self):
        flight = _ResumeFlight(.5)
        entered, release = asyncio.Event(), asyncio.Event()
        deadlines = []
        async def work(deadline):
            deadlines.append(deadline)
            entered.set()
            await release.wait()
            return True
        short = asyncio.create_task(flight.wait(work, asyncio.get_running_loop().time() + .03))
        await entered.wait()
        long = asyncio.create_task(flight.wait(work, asyncio.get_running_loop().time() + .4))
        with self.assertRaises(TimeoutError):
            await short
        release.set()
        self.assertTrue(await long)
        self.assertEqual(len(deadlines), 1)

    async def test_last_waiter_cancels_before_replacement(self):
        flight = _ResumeFlight(.5)
        entered, disposed = asyncio.Event(), asyncio.Event()
        async def work(deadline):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                disposed.set()
        task = asyncio.create_task(flight.wait(work, None))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        async def replacement(deadline):
            self.assertTrue(disposed.is_set())
            return True
        self.assertTrue(await flight.wait(replacement, None))

    async def test_long_first_short_second_and_individual_cancellation(self):
        flight = _ResumeFlight(.5)
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def work(deadline):
            calls.append(deadline)
            entered.set()
            await release.wait()
            return True
        first = asyncio.create_task(flight.wait(work, asyncio.get_running_loop().time() + .4))
        await entered.wait()
        with self.assertRaises(TimeoutError):
            await flight.wait(work, asyncio.get_running_loop().time() + .01)
        cancelled = asyncio.create_task(flight.wait(work, None))
        await asyncio.sleep(0)
        cancelled.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await cancelled
        release.set()
        self.assertTrue(await first)
        self.assertEqual(len(calls), 1)

    async def test_pending_mutation_survives_cancelled_flight(self):
        state, flight = _ResumeState(), _ResumeFlight(.5)
        entered = asyncio.Event()
        async def work(deadline):
            state.dispatched()
            entered.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(flight.wait(work, None))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        async def replacement(deadline):
            self.assertFalse(state.observe('suspended'))
            self.assertEqual(state.pending, 'unknown')
            state.observe('active')
            return True
        self.assertTrue(await flight.wait(replacement, None))

    async def test_native_local_channel_failure_and_close(self):
        import socket
        import grpc
        from e6data_python_connector.exceptions import OperationalError
        # Bound non-listening local socket prevents a service from owning the port.
        with socket.socket() as socket_guard:
            socket_guard.bind(('127.0.0.1', 0))
            manager = AsyncClusterManager('127.0.0.1', socket_guard.getsockname()[1], user='unit', password='unit', timeout=.1)
            try:
                with self.assertRaises(OperationalError) as raised:
                    await manager.resume()
                self.assertIsInstance(raised.exception.__cause__, (grpc.RpcError, TimeoutError))
                self.assertIsNone(manager._mutation.pending)
            finally:
                await manager.close()
                await manager.close()

    async def test_cross_loop_misuse_and_closed_manager(self):
        from e6data_python_connector.exceptions import ProgrammingError
        manager = AsyncClusterManager('localhost', 443, user='unit', password='unit')
        manager._check_owner()
        async def wrong_loop():
            with self.assertRaises(ProgrammingError):
                await manager.resume()
        await asyncio.to_thread(lambda: asyncio.run(wrong_loop()))
        await manager.close()
        with self.assertRaises(ProgrammingError):
            await manager.resume()

    async def test_exact_supported_error_signals(self):
        import grpc
        from e6data_python_connector.async_cluster_manager import is_strategy_mismatch, is_suspended_error
        error = grpc.aio.AioRpcError(grpc.StatusCode.UNKNOWN, (), (), 'status: 456')
        self.assertTrue(is_strategy_mismatch(error))
        error = grpc.aio.AioRpcError(grpc.StatusCode.UNKNOWN, (), (), 'other status: 456')
        self.assertFalse(is_strategy_mismatch(error))
        error = grpc.aio.AioRpcError(grpc.StatusCode.UNAVAILABLE, (), (), 'status: 503, cluster is suspended')
        self.assertTrue(is_suspended_error(error))
        error = grpc.aio.AioRpcError(grpc.StatusCode.UNAVAILABLE, (), (), 'status: 503')
        self.assertFalse(is_suspended_error(error))

    async def test_constructor_validation_and_deadlines(self):
        from e6data_python_connector.async_cluster_manager import _remaining
        base = dict(host='localhost', port=443, user='unit', password='unit')
        invalid = [dict(host=''), dict(port=True), dict(port=0),
                   dict(user=''), dict(initial_strategy='red'), dict(ssl_cert=1),
                   dict(timeout=-1), dict(cleanup_timeout=0),
                   dict(grpc_options={'grpc.ssl_target_name_override': 'localhost'}),
                   dict(grpc_options={'grpc.max_receive_message_length': -1}),
                   dict(secure_channel=True, metadata_provider=lambda: None)]
        for extra in invalid:
            with self.assertRaises(ValueError):
                AsyncClusterManager(**(base | extra))
        manager = AsyncClusterManager(**base, cluster_uuid='unit-cluster')
        for deadline in (float('inf'), True, 'bad'):
            with self.assertRaises(ValueError):
                await manager.resume(deadline=deadline)
        from e6data_python_connector.exceptions import OperationalError
        with self.assertRaises(OperationalError) as raised:
            await manager.resume(deadline=asyncio.get_running_loop().time() - 1)
        self.assertIsInstance(raised.exception.__cause__, TimeoutError)
        with self.assertRaises(ValueError):
            await manager.resume(timeout=0)
        with self.assertRaises(TimeoutError):
            _remaining(asyncio.get_running_loop().time() - 1)
        metadata = await manager._metadata('green', asyncio.get_running_loop().time() + 1)
        self.assertEqual(dict(metadata), {'strategy': 'green', 'cluster-name': 'unit-cluster'})
        await manager.close()

    async def test_native_secure_channel_and_certificate_loading(self):
        import socket
        import tempfile
        import grpc
        from e6data_python_connector.exceptions import OperationalError
        async def static_metadata(strategy, deadline, rejected_token=None):
            if rejected_token is not None:
                return None
            return [('strategy', strategy), ('authorization', 'Bearer unit')]
        with socket.socket() as guard, tempfile.NamedTemporaryFile() as certificate:
            guard.bind(('127.0.0.1', 0))
            manager = AsyncClusterManager('127.0.0.1', guard.getsockname()[1],
                                          secure_channel=True, metadata_provider=static_metadata,
                                          ssl_cert=certificate.name, timeout=.1)
            deadline = asyncio.get_running_loop().time() + 1
            self.assertIsNone(await manager._metadata('blue', deadline, 'unit'))
            try:
                with self.assertRaises(OperationalError) as raised:
                    await manager.resume(timeout=.3)
                self.assertIsInstance(raised.exception.__cause__, (grpc.RpcError, TimeoutError))
            finally:
                await manager.close()
