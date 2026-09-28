"""Subprocess fault injection for real worker bootstrap and reaping tests."""
import multiprocessing
import os
import sys
import threading
import time

# Faults happen in real spawned children before the worker ready handshake.
if multiprocessing.current_process().name.startswith('e6-result-decode-'):
    if sys.argv[-1] == 'partial_start' and multiprocessing.current_process().name.endswith('1'):
        os._exit(7)
    if sys.argv[-1] in ('startup_timeout', 'close_during_start'):
        time.sleep(5)


def daemon_start():
    from e6data_python_connector.result_decode import DecoderLease
    try:
        DecoderLease().start(time.monotonic() + 1)
    except ValueError as error:
        assert 'daemon' in str(error)
        return
    raise AssertionError('Daemon unexpectedly started decode workers')


def main():
    from e6data_python_connector.result_decode import DecoderLease
    scenario = sys.argv[-1]
    if scenario == 'daemon':
        process = multiprocessing.get_context('spawn').Process(target=daemon_start, daemon=True)
        process.start()
        process.join(4)
        assert process.exitcode == 0
        process.close()
    else:
        lease = DecoderLease()
        errors = []
        def start():
            try:
                lease.start(time.monotonic() + (.25 if scenario == 'startup_timeout' else 4))
            except (ValueError, TimeoutError) as error:
                errors.append(error)
        thread = threading.Thread(target=start)
        thread.start()
        if scenario == 'close_during_start':
            end = time.monotonic() + 2
            while not lease.worker_pids:
                assert time.monotonic() < end
                time.sleep(.001)
            lease.close(time.monotonic() + .2)
        thread.join(6)
        assert not thread.is_alive()
        assert errors
        if scenario in ('partial_start', 'startup_timeout'):
            try:
                lease.start(time.monotonic() + 1)
            except (ValueError, TimeoutError):
                pass
            else:
                raise AssertionError('Bootstrap failure must not silently become sequential fallback')
        lease.close(time.monotonic() + 3)
        end = time.monotonic() + 3
        while any(p.name.startswith('e6-result-decode-') for p in multiprocessing.active_children()):
            assert time.monotonic() < end
            time.sleep(.01)
        assert not any(t.name.startswith('e6-result-decode-io-') for t in threading.enumerate())
    print('PROBE_OK')


if __name__ == '__main__':
    main()
