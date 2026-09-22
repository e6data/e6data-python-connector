"""Small real-gRPC tests for the explicitly synthetic local benchmark."""

import importlib
import importlib.util
from pathlib import Path

import pytest


def harness():
    return importlib.import_module("test.performance.local_result_pipeline")


@pytest.mark.parametrize("profile", ["numeric", "mixed", "wide_strings"])
def test_real_cursor_drains_all_envelopes_and_checks_every_row(tmp_path, profile):
    pipeline = harness()
    from test.performance.local_decode_baseline import generate_dataset

    dataset = tmp_path / "fixtures"
    generate_dataset(dataset, rows_per_chunk=3, chunks=2, seed=7)
    report = pipeline.run_pipeline(dataset, profile, envelopes=3, repeats=1,
                                   server_delay_seconds=0.002)
    trial = report["trials"][0]
    assert report["kind"] == "synthetic-local-grpc-result-pipeline"
    assert report["input"]["envelopes"] == 3
    assert report["input"]["rows_per_envelope"] == 6
    assert trial["rows"] == 18
    assert trial["chunks"] == 6
    assert trial["correctness"]["valid"] is True
    assert len(trial["correctness"]["envelope_ordered_sha256"]) == 3
    assert len(set(trial["correctness"]["envelope_ordered_sha256"])) == 1
    assert len(trial["server_rpc_samples"]) == 3
    assert [sample["terminal"] for sample in trial["server_rpc_samples"]] == [False, False, True]
    assert all(sample["query_identity_valid"] for sample in trial["server_rpc_samples"])
    assert all(sample["duration_seconds"] >= 0.002 for sample in trial["server_rpc_samples"])
    assert trial["end_to_end_seconds"] >= trial["fetch_wait_seconds"] > 0
    assert 0 < trial["client_download_seconds"] <= trial["end_to_end_seconds"]
    assert len(trial["client_transport_samples"]) == 3
    assert [s["terminal"] for s in trial["client_transport_samples"]] == [False, False, True]
    assert all(s["serialized_bytes"] > 0 for s in trial["client_transport_samples"])
    assert trial["decode_seconds"] > 0
    assert trial["validation_seconds"] > 0
    assert trial["parent_process_cpu_seconds"] > 0
    assert trial["parent_peak_rss_bytes"] > 0
    assert report["worker_startup_seconds"] >= 0
    assert len(report["worker_pids"]) == 2
    assert report["aggregate_run_cpu_seconds"] > 0
    assert report["sampled_peak_aggregate_rss_bytes"] > 0
    assert report["workers_reaped"] is True
    assert Path(report["source"]["e6data_grpc"]["path"]).is_file()
    assert len(report["source"]["e6data_grpc"]["sha256"]) == 64
    assert len(report["source"]["harness"]["sha256"]) == 64


@pytest.mark.parametrize("arguments", [
    {"envelopes": 0}, {"repeats": 0}, {"server_delay_seconds": -0.1},
])
def test_invalid_run_sizes_fail_before_starting_server(tmp_path, arguments):
    pipeline = harness()
    with pytest.raises(ValueError):
        pipeline.run_pipeline(tmp_path / "missing", "mixed", **arguments)


def test_changed_fixture_is_rejected_before_fetching(tmp_path):
    pipeline = harness()
    from test.performance.local_decode_baseline import generate_dataset

    dataset = tmp_path / "fixtures"
    generate_dataset(dataset, rows_per_chunk=2, chunks=2, seed=7)
    path = dataset / "mixed-0000.thrift"
    path.write_bytes(path.read_bytes() + b"corruption")
    with pytest.raises(ValueError, match="checksum|hash|bytes"):
        pipeline.run_pipeline(dataset, "mixed", envelopes=2, repeats=1)
