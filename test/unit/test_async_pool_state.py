"""Pool invariants using local state and lazy native channels, no services."""
import asyncio

import pytest

from e6data_python_connector.async_connection_pool import AsyncConnectionPool, _PoolState
from e6data_python_connector.exceptions import OperationalError, ProgrammingError


def pool(**kwargs):
    options = dict(min_size=0, max_size=1, max_overflow=0, pre_ping=False,
                   host='localhost', port=1, username='unit-user', password='unit-input')
    options.update(kwargs)
    return AsyncConnectionPool(**options)


def test_reservation_state_exactly_once():
    state = _PoolState(2)
    first, second = state.reserve(), state.reserve()
    assert state.reserve() is None
    state.move(first, 'creating', 'leased')
    state.move(first, 'leased', 'retiring')
    state.remove(first)
    with pytest.raises(ProgrammingError):
        state.remove(first)
    state.remove(second)
    assert state.counts() == dict(idle=0, leased=0, creating=0, retiring=0)


def test_defaults_local_validation():
    p = AsyncConnectionPool(host='localhost', port=1, username='u', password='p')
    assert (p.min_size, p.max_size, p.max_overflow, p.timeout, p.recycle, p.pre_ping) == (2, 10, 5, 30, 3600, True)
    assert p._owner is None
    for options in ({'min_size': -1}, {'max_size': 0}, {'max_overflow': -1}, {'timeout': 0}, {'recycle': 0}, {'min_size': 3, 'max_size': 2}):
        with pytest.raises(ValueError):
            pool(**options)


def test_new_revision_stale_wrapper_cursor_and_double_return():
    async def run():
        async with pool() as p:
            old = await p.get_connection()
            cursor = old.cursor()
            assert cursor is not old.cursor()
            physical = old._connection
            await old.close()
            new = await p.get_connection()
            assert new is not old and new._connection is physical
            for operation in (lambda: old.commit(), old.close, cursor.close, cursor.fetchone):
                with pytest.raises(ProgrammingError):
                    await operation()
            with pytest.raises(ProgrammingError):
                old.cursor()
            await new.commit()
            await p.return_connection(new)
            with pytest.raises(ProgrammingError):
                await p.return_connection(new)
            assert p.get_statistics()['idle'] == 1
    asyncio.run(run())


def test_public_connection_aliases_cannot_escape_a_lease():
    async def run():
        async with pool() as p:
            old = await p.get_connection()
            cursor = old.cursor()
            aliases = (old.connection, cursor.connection, await old.open())
            await old.close()
            for alias in aliases:
                with pytest.raises(ProgrammingError):
                    await alias.commit()
            current = await p.get_connection()
            for alias in aliases:
                with pytest.raises(ProgrammingError):
                    await alias.close()
            assert current.check_connection()
            await current.close()
    asyncio.run(run())


def test_distinct_tasks_capacity_timeout_cancel_and_overflow():
    async def run():
        async with pool(max_size=1, max_overflow=1) as p:
            queue, release = asyncio.Queue(), asyncio.Event()
            async def hold():
                async with p.get_connection_context() as lease:
                    queue.put_nowait(lease)
                    await release.wait()
            tasks = [asyncio.create_task(hold()) for _ in range(2)]
            first, second = await queue.get(), await queue.get()
            assert first is not second
            assert p.get_statistics()['leased'] == 2
            with pytest.raises(ProgrammingError):
                await first.commit()
            with pytest.raises(OperationalError):
                await p.get_connection(timeout=.01)
            waiting = asyncio.create_task(p.get_connection())
            await asyncio.sleep(0)
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            assert p.get_statistics()['waiters'] == 0
            release.set()
            await asyncio.gather(*tasks)
            assert p.get_statistics()['total_connections'] == 1
    asyncio.run(run())


def test_shutdown_wakes_waiters_and_invalidates_late_returns():
    async def run():
        p = await pool().open()
        lease = await p.get_connection()
        waiting = asyncio.create_task(p.get_connection())
        await asyncio.sleep(0)
        await p.close_all()
        with pytest.raises(ProgrammingError):
            await waiting
        with pytest.raises(ProgrammingError):
            await lease.commit()
        await p.return_connection(lease)
        assert p.get_statistics()['total_connections'] == 0
        await p.close_all()
    asyncio.run(run())


def test_nested_context_return_once_and_cancelled_release():
    async def run():
        async with pool() as p:
            async with p.get_connection_context() as lease:
                async with lease:
                    await lease.commit()
            entered = asyncio.Event()
            async def task():
                async with p.get_connection_context() as lease:
                    lease.cursor()
                    entered.set()
                    await asyncio.Event().wait()
            active = asyncio.create_task(task())
            await entered.wait()
            active.cancel()
            with pytest.raises(asyncio.CancelledError):
                await active
            assert p.get_statistics()['idle'] == 1
    asyncio.run(run())


def test_recycle_and_native_preping_failure_restore_capacity():
    async def run():
        async with pool(recycle=.001) as p:
            lease = await p.get_connection()
            old = lease._connection
            await lease.close()
            await asyncio.sleep(.003)
            fresh = await p.get_connection()
            assert fresh._connection is not old
            await fresh.close()
        async with pool(pre_ping=True, timeout=.02) as p:
            with pytest.raises(OperationalError):
                await p.get_connection()
            assert p.get_statistics()['total_connections'] == 0
    asyncio.run(run())


def test_cancel_native_creation_and_release_restore_once():
    async def run():
        async with pool(pre_ping=True) as p:
            creating = asyncio.create_task(p.get_connection())
            await asyncio.sleep(0)
            assert p.get_statistics()['creating'] == 1
            creating.cancel()
            with pytest.raises(asyncio.CancelledError):
                await creating
            assert p.get_statistics()['total_connections'] == 0
        async with pool() as p:
            lease = await p.get_connection()
            lease.cursor()
            asyncio.get_running_loop().call_soon(asyncio.current_task().cancel)
            with pytest.raises(asyncio.CancelledError):
                await lease.close()
            assert p.get_statistics()['idle'] == 1
    asyncio.run(run())


def test_shared_provider_and_manager_survive_child_disposal():
    async def run():
        p = AsyncConnectionPool(min_size=2, max_size=2, max_overflow=0, pre_ping=False,
            host='localhost', port=1, secure=True, client_id='unit-id',
            client_secret='unit-input', token_url='https://localhost/token')
        await p.open()
        first, second = await p.get_connection(), await p.get_connection()
        assert first._connection._token_provider is second._connection._token_provider is p._token_provider
        assert first._connection._cluster_manager is second._connection._cluster_manager is p._cluster_manager
        await first._connection.close()
        await first.close()
        assert not second._connection._token_provider._closed
        await second.close()
        await p.close_all()
        assert p._token_provider._closed
    asyncio.run(run())


def test_owner_rejection_and_failed_open_cleanup():
    p = pool()
    asyncio.run(p.open())
    async def wrong_loop():
        with pytest.raises(ProgrammingError):
            await p.get_connection()
        with pytest.raises(ProgrammingError):
            p.get_statistics()
    asyncio.run(wrong_loop())
    async def run():
        p = pool(min_size=1, pre_ping=True, timeout=.01)
        with pytest.raises(OperationalError):
            await p.open()
        assert p.get_statistics()['total_connections'] == 0
        with pytest.raises(ProgrammingError):
            await p.open()
        await p.close_all()
    asyncio.run(run())


def test_uncertain_submission_disposes_and_saved_method_revoked():
    async def run():
        async with pool() as p:
            lease = await p.get_connection()
            physical = lease._connection
            saved = lease.commit
            cursor = lease.cursor()
            cursor._state = 'SUBMISSION_UNKNOWN'  # Pure lifecycle state, no transport double.
            await lease.close()
            with pytest.raises(ProgrammingError):
                await saved()
            assert p.get_statistics()['total_connections'] == 0
            assert not physical.check_connection()
    asyncio.run(run())


def test_close_during_creation_and_repeated_close_before_open():
    async def run():
        unopened = pool()
        await unopened.close_all()
        await unopened.close_all()
        p = await pool(pre_ping=True).open()
        creating = asyncio.create_task(p.get_connection())
        await asyncio.sleep(0)
        await p.close_all()
        with pytest.raises(asyncio.CancelledError):
            await creating
        assert p.get_statistics()['total_connections'] == 0
    asyncio.run(run())


def test_repeated_cancellation_finishes_return_bookkeeping():
    async def run():
        async with pool() as p:
            entered = asyncio.Event()
            async def borrower():
                lease = await p.get_connection()
                entered.set()
                await lease.close()
            task = asyncio.create_task(borrower())
            await entered.wait()
            async with p._condition:
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert p.get_statistics()['idle'] == 1
    asyncio.run(run())


def test_detached_ambiguous_submission_marker_prevents_reuse():
    async def run():
        async with pool() as p:
            lease = await p.get_connection()
            cursor = lease.cursor()
            # The connection remembers ambiguity after cursor detachment.
            lease._connection._ambiguous_submissions.add(cursor)
            await cursor.close()
            await lease.close()
            assert p.get_statistics()['total_connections'] == 0
    asyncio.run(run())
