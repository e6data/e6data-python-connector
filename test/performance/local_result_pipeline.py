"""SYNTHETIC loopback gRPC fetch/decode benchmark using frozen Thrift fixtures.

Run in Linux, from a neutral working directory, with the intended connector
source first in PYTHONPATH and this directory second. Example:

  PYTHONPATH=/saved/source:/work/test/performance python -m local_result_pipeline \
      --dataset /artifacts/local-decode-baseline/fixtures --profile mixed \
      --server-delay-seconds 0.1 --output /artifacts/pipeline-before-mixed.json

The generated local service only implements result fetching. Unissued query and
session values are injected into a real Cursor; no engine, authentication or
customer endpoint is used. Each response repeats the exact frozen envelope.
Server delay is synthetic latency, not bandwidth or a customer replica.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import platform
import resource
import statistics
import threading
import time

import grpc

from e6data_python_connector import datainputstream, e6data_grpc, result_batch
from e6data_python_connector.server import e6x_engine_pb2 as pb
from e6data_python_connector.server import e6x_engine_pb2_grpc as rpc
if __package__:
    from .local_decode_baseline import _environment, _integer, _row_bytes, load_dataset
else:
    from local_decode_baseline import _environment, _integer, _row_bytes, load_dataset


QUERY_ID = "synthetic-unissued-query"
SESSION_ID = "synthetic-unissued-session"
ENGINE_IP = "127.0.0.1"


class SyntheticResultServer(rpc.QueryEngineServiceServicer):
    """Explicit test double transporting real, unchanged Thrift payloads."""

    def __init__(self, payloads, envelopes, delay):
        self.payloads = payloads
        self.envelopes = envelopes
        self.delay = delay
        self.samples = []

    def getNextResultBatchV2(self, request, context):
        started = time.perf_counter()
        headers = dict(context.invocation_metadata())
        valid = (request.queryId == QUERY_ID and request.sessionId == SESSION_ID
                 and request.engineIP == ENGINE_IP and headers.get("plannerip") == ENGINE_IP)
        if not valid:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Synthetic query identity changed")
        index = len(self.samples)
        if index >= self.envelopes:
            context.abort(grpc.StatusCode.OUT_OF_RANGE, "Fetch after synthetic terminal response")
        if self.delay:
            time.sleep(self.delay)
        terminal = index == self.envelopes - 1
        response = pb.GetNextResultBatchV2Response(
            resultBatches=self.payloads, sessionId=SESSION_ID, endOfStream=terminal)
        self.samples.append({"index": index, "terminal": terminal,
                             "query_identity_valid": valid,
                             "route_strategy": headers.get("strategy"),
                             "duration_seconds": time.perf_counter() - started})
        return response


class FetchMetrics(logging.Handler):
    """Collect the real connector's existing per-RPC diagnostic fields."""

    def __init__(self):
        super().__init__()
        self.samples = []

    def emit(self, record):
        fields = {key[len("result_batch_"):]: value for key, value in vars(record).items()
                  if key.startswith("result_batch_")}
        if fields:
            self.samples.append(fields)


class TransportMetrics:
    """Observe actual receive completion before any connector row decoding.

    This test-only RPC uses the generated serializer and Protobuf parser. The
    receive timestamp is recorded inside the response deserializer, before the
    gRPC Future becomes ready, so callback scheduling cannot move it past decode.
    """

    def __init__(self, channel):
        self.samples = []
        self._lock = threading.Lock()
        self._active = None
        self._call = channel.unary_unary(
            '/QueryEngineService/getNextResultBatchV2',
            request_serializer=pb.GetNextResultBatchRequest.SerializeToString,
            response_deserializer=self._received)

    def reset(self):
        with self._lock:
            if self._active is not None:
                raise ValueError('Previous synthetic transport is still running')
            self.samples.clear()

    def _start(self):
        with self._lock:
            if self._active is not None:
                raise ValueError('Overlapping consuming result RPCs')
            self._active = time.perf_counter()

    def _received(self, payload):
        response = pb.GetNextResultBatchV2Response.FromString(payload)
        completed = time.perf_counter()
        with self._lock:
            self.samples.append({
                'started_at': self._active, 'received_at': completed,
                'duration_seconds': completed - self._active,
                'serialized_bytes': len(payload), 'terminal': response.endOfStream})
            self._active = None
        return response

    def __call__(self, *args, **kwargs):
        self._start()
        return self._call(*args, **kwargs)

    def future(self, *args, **kwargs):
        self._start()
        return self._call.future(*args, **kwargs)


def _source_file(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _drain(cursor, selected, envelopes):
    """Validate one chunk at a time, retaining no whole-result row collection."""
    started, cpu_started = time.perf_counter(), time.process_time()
    fetch_wait = validation_wall = validation_cpu = 0.0
    rows = chunks = envelope_rows = 0
    envelope_hash = hashlib.sha256()
    all_hash = hashlib.sha256()
    envelope_hashes = []
    iterator = iter(cursor.fetchall_buffer())
    while True:
        before = time.perf_counter()
        try:
            chunk = next(iterator)
        except StopIteration:
            fetch_wait += time.perf_counter() - before
            break
        fetch_wait += time.perf_counter() - before
        before, cpu_before = time.perf_counter(), time.process_time()
        expected = selected["chunks"][chunks % len(selected["chunks"])]
        if type(chunk) is not list or len(chunk) != expected["rows"]:
            raise ValueError("Decoded chunk shape validation failed")
        for row in chunk:
            if type(row) is not list or len(row) != len(selected["columns"]):
                raise ValueError("Decoded row shape validation failed")
            raw = _row_bytes(row)
            envelope_hash.update(raw)
            all_hash.update(raw)
        rows += len(chunk)
        envelope_rows += len(chunk)
        chunks += 1
        if chunks % len(selected["chunks"]) == 0:
            digest = envelope_hash.hexdigest()
            if envelope_rows != selected["row_count"] or digest != selected["ordered_sha256"]:
                raise ValueError("Decoded envelope count/digest validation failed")
            envelope_hashes.append(digest)
            envelope_hash, envelope_rows = hashlib.sha256(), 0
        validation_wall += time.perf_counter() - before
        validation_cpu += time.process_time() - cpu_before
    elapsed, cpu = time.perf_counter() - started, time.process_time() - cpu_started
    if rows != selected["row_count"] * envelopes or len(envelope_hashes) != envelopes:
        raise ValueError("Decoded complete result count validation failed")
    return {"end_to_end_seconds": elapsed, "fetch_wait_seconds": fetch_wait,
            "validation_seconds": validation_wall, "validation_process_cpu_seconds": validation_cpu,
            "parent_process_cpu_seconds": cpu,
            "parent_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "rows": rows, "chunks": chunks,
            "correctness": {"valid": True, "ordered_sha256": all_hash.hexdigest(),
                            "envelope_ordered_sha256": envelope_hashes}}


def run_pipeline(dataset, profile, envelopes=8, repeats=3, server_delay_seconds=0.0):
    _integer(envelopes, "envelopes", maximum=64)
    _integer(repeats, "repeats", maximum=20)
    if (isinstance(server_delay_seconds, bool) or not isinstance(server_delay_seconds, (int, float))
            or not math.isfinite(server_delay_seconds) or not 0 <= server_delay_seconds <= 10):
        raise ValueError("server_delay_seconds must be finite seconds from 0 to 10")
    if platform.system() != "Linux":
        raise RuntimeError("Run this benchmark in Linux for consistent RSS units")
    manifest, selected, payloads = load_dataset(dataset, profile)
    def aggregate_cpu():
        children = resource.getrusage(resource.RUSAGE_CHILDREN)
        return time.process_time() + children.ru_utime + children.ru_stime

    run_cpu_start = aggregate_cpu()
    worker_pids = ()
    peak_rss = [0]
    monitor_stop = threading.Event()
    def sample_rss():
        rss = 0
        for pid in (os.getpid(),) + worker_pids:
            try:
                fields = Path('/proc/{}/stat'.format(pid)).read_text().rsplit(')', 1)[1].split()
            except FileNotFoundError:
                continue
            rss += int(fields[21]) * os.sysconf('SC_PAGE_SIZE')
        peak_rss[0] = max(peak_rss[0], rss)
    def monitor():
        while not monitor_stop.wait(.01):
            sample_rss()
    sampler = threading.Thread(target=monitor, name='pipeline-rss-sampler', daemon=True)
    service = SyntheticResultServer(payloads, envelopes, server_delay_seconds)
    server = grpc.server(ThreadPoolExecutor(max_workers=1), options=[
        ("grpc.max_send_message_length", 128 * 1024 * 1024)])
    rpc.add_QueryEngineServiceServicer_to_server(service, server)
    port = server.add_insecure_port("127.0.0.1:0")
    if not port:
        raise RuntimeError("Cannot bind synthetic loopback server")
    server.start()
    metrics = FetchMetrics()
    logger = logging.getLogger(e6data_grpc.__name__)
    prior_level, prior_propagate = logger.level, logger.propagate
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.addHandler(metrics)
    connection = None
    trials = []
    startup_seconds = 0.0
    try:
        connection = e6data_grpc.Connection(
            host="127.0.0.1", port=port, username="synthetic-local-user",
            password="synthetic-unissued-input", auto_resume=False,
            enable_result_batch_v2=True, require_fastbinary=True,
            grpc_options={"grpc_prepare_timeout": 120})
        transport = TransportMetrics(connection._channel)
        connection.client.getNextResultBatchV2 = transport
        sampler.start()
        if hasattr(connection, '_start_result_decoder'):
            started = time.perf_counter()
            connection._start_result_decoder(time.monotonic() + 30)
            startup_seconds = time.perf_counter() - started
            worker_pids = connection._decoder_lease.worker_pids
        sample_rss()
        for index in range(repeats):
            service.samples.clear()
            metrics.samples.clear()
            transport.reset()
            cursor = connection.cursor()
            cursor._query_id, cursor._engine_ip = QUERY_ID, ENGINE_IP
            cursor._result_session_id = SESSION_ID
            cursor._is_metadata_updated = True
            cursor._query_columns_description = selected["columns"]
            trial = _drain(cursor, selected, envelopes)
            trial.update({"index": index, "server_rpc_samples": list(service.samples),
                          "client_rpc_samples": list(metrics.samples)})
            received = list(transport.samples)
            if len(received) != envelopes or not received[-1]["terminal"]:
                raise ValueError('Incomplete synthetic client receive sequence')
            trial["client_transport_samples"] = received
            trial["client_download_seconds"] = (
                received[-1]["received_at"] - received[0]["started_at"])
            trial["decode_seconds"] = sum(
                sample.get("decode_seconds", 0.0) for sample in metrics.samples)
            if len(service.samples) != envelopes:
                raise ValueError("Unexpected synthetic RPC count")
            # The injected query never existed on an engine and needs no clear RPC.
            cursor._query_id = None
            cursor.close()
            trials.append(trial)
    finally:
        if connection is not None:
            connection.close()
        monitor_stop.set()
        if sampler.ident is not None:
            sampler.join(timeout=1)
        server.stop(0).wait()
        logger.removeHandler(metrics)
        logger.setLevel(prior_level)
        logger.propagate = prior_propagate
    return {
        "schema_version": 1, "kind": "synthetic-local-grpc-result-pipeline",
        "optimized_sources": {name: _source_file(path) for name in ("result_decode.py", "result_decode_worker.py", "result_prefetch.py") if (path := Path(e6data_grpc.__file__).with_name(name)).is_file()},
        "worker_startup_seconds": startup_seconds,
        "worker_pids": worker_pids,
        "workers_reaped": all(not Path('/proc/{}'.format(pid)).exists() for pid in worker_pids),
        "aggregate_run_cpu_seconds": aggregate_cpu() - run_cpu_start,
        "sampled_peak_aggregate_rss_bytes": peak_rss[0],
        "aggregate_resource_scope": "parent plus decode workers, includes startup, verification, local server and cleanup; excludes resource tracker; RSS sampled every 10ms",
        "method": {
            "transport": "generated gRPC service on IPv4 loopback, same parent process",
            "consumer": "real Cursor.fetchall_buffer; ordered type-preserving SHA256 per row",
            "delay": "fixed server sleep per response; synthetic latency, not bandwidth",
            "end_to_end": "fetch drain plus row validation; excludes fixture load and server/connection setup",
            "fetch_wait": "sum of iterator next calls; excludes caller hashing; not total pipeline duration",
            "cpu": "parent process including local gRPC server, connector threads and caller validation",
            "rss": "parent process lifetime high-water mark, including fixtures and local server",
            "trials": "first drain followed by repeated drains in same process and connection; no discarded warmup",
        },
        "input": {"dataset": str(Path(dataset).resolve()), "profile": profile,
                  "manifest_sha256": hashlib.sha256((Path(dataset) / "manifest.json").read_bytes()).hexdigest(),
                  "seed": manifest["seed"], "envelopes": envelopes,
                  "rows_per_envelope": selected["row_count"],
                  "serialized_thrift_bytes_per_envelope": selected["input_bytes"],
                  "server_delay_seconds": server_delay_seconds,
                  "expected_envelope_ordered_sha256": selected["ordered_sha256"]},
        "source": {"e6data_grpc": _source_file(e6data_grpc.__file__),
                   "result_batch": _source_file(result_batch.__file__),
                   "datainputstream": _source_file(datainputstream.__file__),
                   "harness": _source_file(__file__)},
        "environment": _environment(), "trials": trials,
        "median": {key: statistics.median(trial[key] for trial in trials) for key in
                   ("end_to_end_seconds", "fetch_wait_seconds", "validation_seconds",
                    "parent_process_cpu_seconds", "parent_peak_rss_bytes")},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--profile", choices=["numeric", "mixed", "wide_strings"], required=True)
    parser.add_argument("--envelopes", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--server-delay-seconds", type=float, default=0.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run_pipeline(args.dataset, args.profile, args.envelopes, args.repeats,
                          args.server_delay_seconds)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "median": report["median"]}, sort_keys=True))


if __name__ == "__main__":
    main()
