"""Synthetic serial/process comparison including startup, IPC, CPU and RSS.

Run in Linux against the frozen local_decode_baseline dataset. File loading and
type-preserving digest validation stay outside each decode timer. Process RSS
is sampled, not a precise peak, and includes fixtures and validation objects.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import threading
import time

if __package__:
    from .local_decode_baseline import load_dataset, validate_rows, _environment, _integer
else:
    from local_decode_baseline import load_dataset, validate_rows, _environment, _integer

from e6data_python_connector import datainputstream, result_batch
from e6data_python_connector.result_batch import decode_result_batches


def _resources(pids):
    cpu, rss = {}, 0
    for pid in pids:
        try:
            fields = Path('/proc/{}/stat'.format(pid)).read_text().rsplit(')', 1)[1].split()
        except FileNotFoundError:
            continue
        cpu[pid] = (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK')
        rss += int(fields[21]) * os.sysconf('SC_PAGE_SIZE')
    return cpu, rss


def measure(dataset, profile, mode, repeats=7, warmups=1):
    _integer(repeats, 'repeats', minimum=3)
    _integer(warmups, 'warmups')
    if mode not in ('serial', 'parallel') or not Path('/proc/self/stat').is_file():
        raise ValueError('Choose serial or parallel and run in Linux.')
    manifest, selected, payloads = load_dataset(dataset, profile)
    lease = None
    if mode == 'parallel':
        from e6data_python_connector.result_decode import DecoderLease
        lease = DecoderLease()
    parent_pid = os.getpid()
    stop = threading.Event()
    peak_rss = [0]

    def pids():
        return (parent_pid,) + (lease.worker_pids if lease is not None else ())

    def sample():
        _, rss = _resources(pids())
        peak_rss[0] = max(peak_rss[0], rss)

    def monitor():
        while not stop.wait(.01):
            sample()

    sampler = threading.Thread(target=monitor, name='synthetic-rss-sampler', daemon=True)
    sampler.start()
    worker_pids = ()
    cpu_before, _ = _resources(pids())
    started = time.perf_counter()
    try:
        if lease is not None:
            lease.start(time.monotonic() + 30)
            worker_pids = lease.worker_pids
        startup = time.perf_counter() - started
        cpu_after, _ = _resources(pids())
        startup_cpu = sum(value - cpu_before.get(pid, 0) for pid, value in cpu_after.items())
        sample()

        def once():
            before, _ = _resources(pids())
            wall = time.perf_counter()
            if lease is None:
                chunks = decode_result_batches(selected['columns'], payloads)
            else:
                chunks = lease.decode(selected['columns'], payloads, time.monotonic() + 30, object())
            elapsed = time.perf_counter() - wall
            after, _ = _resources(pids())
            sample()
            correct = validate_rows(chunks, selected)
            return {'wall_seconds': elapsed,
                    'aggregate_cpu_seconds': sum(value - before.get(pid, 0) for pid, value in after.items()),
                    'correctness': correct}

        first = once()
        for _ in range(warmups):
            once()
        samples = [once() for _ in range(repeats)]
    finally:
        if lease is not None:
            lease.close(time.monotonic() + 10)
        stop.set()
        sampler.join(timeout=1)
    report = {
        'kind': 'synthetic-local-decode-comparison', 'mode': mode, 'profile': profile,
        'manifest_sha256': hashlib.sha256((Path(dataset) / 'manifest.json').read_bytes()).hexdigest(),
        'environment': _environment(), 'rows': selected['row_count'],
        'startup_seconds': startup, 'startup_aggregate_cpu_seconds': startup_cpu,
        'first_decode': first, 'samples': samples,
        'median_wall_seconds': statistics.median(item['wall_seconds'] for item in samples),
        'sampled_peak_aggregate_rss_bytes': peak_rss[0], 'rss_sample_interval_seconds': .01,
        'worker_pids': worker_pids,
        'workers_reaped': all(not Path('/proc/{}'.format(pid)).exists() for pid in worker_pids),
        'measurement_scope': 'eager decode plus IPC; digest/file IO outside timers; CPU uses proc clock ticks; RSS includes imports, input, verification and workers',
        'source': {
            'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'decoder_sha256': hashlib.sha256(Path(result_batch.__file__).read_bytes()).hexdigest(),
            'row_decoder_sha256': hashlib.sha256(Path(datainputstream.__file__).read_bytes()).hexdigest(),
        },
    }
    if lease is not None:
        from e6data_python_connector import result_decode, result_decode_worker
        report['source']['runtime_sha256'] = hashlib.sha256(Path(result_decode.__file__).read_bytes()).hexdigest()
        report['source']['worker_sha256'] = hashlib.sha256(Path(result_decode_worker.__file__).read_bytes()).hexdigest()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--profile', choices=['numeric', 'mixed', 'wide_strings'], required=True)
    parser.add_argument('--mode', choices=['serial', 'parallel'], required=True)
    parser.add_argument('--repeats', type=int, default=7)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    report = measure(args.dataset, args.profile, args.mode, args.repeats)
    Path(args.output).write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
