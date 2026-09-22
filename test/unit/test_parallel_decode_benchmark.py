"""Check the synthetic metrics harness with real small Thrift payloads."""

import importlib

import pytest

from test.performance.local_decode_baseline import generate_dataset


@pytest.mark.parametrize('mode', ['serial', 'parallel'])
def test_measurement_counts_all_rows_and_aggregate_resources(tmp_path, mode):
    harness = importlib.import_module('test.performance.parallel_decode_benchmark')
    generate_dataset(tmp_path / 'data', rows_per_chunk=3, chunks=2)
    result = harness.measure(tmp_path / 'data', 'mixed', mode, repeats=3)
    assert result['kind'] == 'synthetic-local-decode-comparison'
    assert result['mode'] == mode
    assert result['first_decode']['correctness']['row_count'] == 6
    assert len(result['samples']) == 3
    assert all(item['correctness']['valid'] for item in result['samples'])
    assert all(item['aggregate_cpu_seconds'] >= 0 for item in result['samples'])
    assert result['sampled_peak_aggregate_rss_bytes'] > 0
    assert result['startup_seconds'] >= 0
    assert len(result['worker_pids']) == (2 if mode == 'parallel' else 0)
    assert result['workers_reaped'] is True


def test_measurement_validates_frozen_hashes_before_starting_workers(tmp_path):
    harness = importlib.import_module('test.performance.parallel_decode_benchmark')
    generate_dataset(tmp_path / 'data', rows_per_chunk=3, chunks=2)
    path = tmp_path / 'data' / 'mixed-0000.thrift'
    path.write_bytes(path.read_bytes() + b'bad')
    with pytest.raises(ValueError, match='hash'):
        harness.measure(tmp_path / 'data', 'mixed', 'parallel', repeats=3)
