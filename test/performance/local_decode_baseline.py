"""Frozen SYNTHETIC Thrift fixtures and a Linux whole-envelope decode baseline."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import sys
import time
from datetime import date, timedelta
from decimal import Decimal

from thrift.protocol.TBinaryProtocol import TBinaryProtocol, TBinaryProtocolAccelerated
from thrift.transport.TTransport import TMemoryBuffer
from e6data_python_connector import datainputstream, result_batch
from e6data_python_connector.e6x_vector import ttypes as wire
from e6data_python_connector.result_batch import decode_result_batches


SCHEMA_VERSION = 1
SEED = 20260922
COLUMNS = {
    "numeric": [("id", "LONG"), ("score", "DOUBLE"), ("count", "INTEGER"), ("flag", "BOOLEAN")],
    "mixed": [("id", "LONG"), ("score", "DOUBLE"), ("label", "STRING"),
              ("day", "DATE"), ("amount", "DECIMAL128"), ("constant", "STRING")],
    "wide_strings": [("id", "LONG")] + [("text_" + str(i), "STRING") for i in range(4)],
}


def _integer(value, name, minimum=1, maximum=2**31 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("%s must be an integer from %s to %s" % (name, minimum, maximum))


def _row_bytes(row):
    # Same ordered, type-preserving convention as RowVerifier, limited to fixture types.
    values = []
    for value in row:
        if isinstance(value, Decimal):
            value = {"$decimal": str(value)}
        elif value is not None and type(value) not in (bool, int, float, str):
            raise ValueError("Unsupported verification value type")
        values.append(value)
    return (json.dumps(values, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def logical_row(profile, index, seed):
    """Expected values from the documented recipe, with no decoder calls."""
    if profile == "numeric":
        return [index, (index % 1000) + 0.25, index % 10000, index % 2 == 0]
    if profile == "mixed":
        return [index, (index % 1000) + 0.25,
                None if index % 17 == 0 else "row-%08d" % index,
                (date(1970, 1, 1) + timedelta(days=index % 365)).isoformat(),
                Decimal(index % 20000 - 10000) + Decimal("0.37"), "constant"]
    if profile == "wide_strings":
        return [index] + [hashlib.sha256(("%s:%s:%s" % (seed, index, col)).encode()).hexdigest()
                          for col in range(4)]
    raise ValueError("Unknown synthetic profile")


def _serialize(profile, rows):
    vectors = []
    fields = {"LONG": ("int64Data", wire.Int64Data),
              "DOUBLE": ("float64Data", wire.Float64Data),
              "INTEGER": ("int32Data", wire.Int32Data),
              "BOOLEAN": ("boolData", wire.BoolData),
              "STRING": ("varcharData", wire.VarcharData),
              "DATE": ("dateData", wire.DateData)}
    for column, (name, kind) in enumerate(COLUMNS[profile]):
        values = [row[column] for row in rows]
        nulls = [value is None for value in values]
        constant = name == "constant"
        if constant:
            data = wire.Data(varcharConstantData=wire.VarcharConstantData("constant"))
            nulls = [False]
        elif kind == "DECIMAL128":
            raw = [int(value.scaleb(2)).to_bytes(16, "big", signed=True) for value in values]
            data = wire.Data(decimal128Data=wire.Decimal128Data(raw, 2))
        else:
            if kind == "DATE":
                values = [(date.fromisoformat(value) - date(1970, 1, 1)).days * 86400000000
                          for value in values]
            elif name == "label":
                values = ["row-%08d" % row[0] for row in rows]
            field, value_type = fields[kind]
            data = wire.Data(**{field: value_type(values)})
        vectors.append(wire.Vector(len(rows), getattr(wire.VectorType, kind), nulls, data, constant))
    transport = TMemoryBuffer()
    wire.Chunk(len(rows), vectors).write(TBinaryProtocol(transport))
    return transport.getvalue()


def generate_dataset(output, rows_per_chunk=8192, chunks=8, seed=SEED):
    """Generate once. Existing output directories are never overwritten."""
    _integer(rows_per_chunk, "rows_per_chunk", maximum=65536)
    _integer(chunks, "chunks", maximum=64)
    _integer(seed, "seed", minimum=0)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"schema_version": SCHEMA_VERSION, "kind": "synthetic-thrift-decode-fixtures",
                "digest_algorithm": "ordered-json-types-sha256-v1", "seed": seed,
                "generation": {"recipe_version": 1, "rows_per_chunk": rows_per_chunk,
                               "chunks": chunks, "wide_string_columns": 4, "wide_string_bytes": 64},
                "profiles": {}}
    for profile, columns in COLUMNS.items():
        entries, digest = [], hashlib.sha256()
        for chunk in range(chunks):
            rows = [logical_row(profile, index, seed)
                    for index in range(chunk * rows_per_chunk, (chunk + 1) * rows_per_chunk)]
            for row in rows:
                digest.update(_row_bytes(row))
            payload = _serialize(profile, rows)
            filename = "%s-%04d.thrift" % (profile, chunk)
            (output / filename).write_bytes(payload)
            entries.append({"file": filename, "sha256": hashlib.sha256(payload).hexdigest(),
                            "bytes": len(payload), "rows": len(rows)})
        manifest["profiles"][profile] = {"columns": [name for name, _ in columns],
            "column_types": [kind for _, kind in columns], "chunks": entries,
            "row_count": rows_per_chunk * chunks, "input_bytes": sum(item["bytes"] for item in entries),
            "ordered_sha256": digest.hexdigest()}
    raw = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    (output / "manifest.json").write_bytes(raw)
    (output / "manifest.sha256").write_text(hashlib.sha256(raw).hexdigest() + "\n")
    return manifest


def load_dataset(dataset, profile):
    """Validate the manifest and selected files, then preload all input bytes."""
    root = Path(dataset).resolve(strict=True)
    raw = (root / "manifest.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != (root / "manifest.sha256").read_text().strip():
        raise ValueError("Manifest hash mismatch")
    manifest = json.loads(raw)
    if (manifest["schema_version"] != SCHEMA_VERSION
            or manifest["kind"] != "synthetic-thrift-decode-fixtures"
            or manifest["digest_algorithm"] != "ordered-json-types-sha256-v1"):
        raise ValueError("Unsupported fixture manifest schema")
    if profile not in COLUMNS:
        raise ValueError("Unknown profile")
    generation = manifest["generation"]
    _integer(manifest["seed"], "seed", minimum=0)
    _integer(generation["rows_per_chunk"], "rows_per_chunk", maximum=65536)
    _integer(generation["chunks"], "chunks", maximum=64)
    if (generation["recipe_version"], generation["wide_string_columns"], generation["wide_string_bytes"]) != (1, 4, 64):
        raise ValueError("Unsupported generation recipe")
    selected = manifest["profiles"][profile]
    if (selected["columns"] != [name for name, _ in COLUMNS[profile]]
            or selected["column_types"] != [kind for _, kind in COLUMNS[profile]]):
        raise ValueError("Fixture column schema mismatch")
    entries = selected["chunks"]
    if len(entries) != generation["chunks"]:
        raise ValueError("Fixture chunk count mismatch")
    payloads = []
    for index, entry in enumerate(entries):
        expected = "%s-%04d.thrift" % (profile, index)
        path = root / entry["file"]
        if entry["file"] != expected or path.resolve().parent != root or path.is_symlink():
            raise ValueError("Invalid fixture path")
        payload = path.read_bytes()
        if len(payload) != entry["bytes"] or hashlib.sha256(payload).hexdigest() != entry["sha256"]:
            raise ValueError("Fixture size or hash mismatch")
        if entry["rows"] != generation["rows_per_chunk"]:
            raise ValueError("Fixture row count mismatch")
        payloads.append(payload)
    if (selected["input_bytes"] != sum(map(len, payloads))
            or selected["row_count"] != generation["rows_per_chunk"] * len(entries)):
        raise ValueError("Fixture total bytes or rows mismatch")
    return manifest, selected, payloads


def validate_rows(decoded, profile):
    # Exact lists match the real decoder and prevent lazy work after the timer.
    if type(decoded) is not list or len(decoded) != len(profile["chunks"]):
        raise ValueError("Decoded envelope shape validation failed")
    digest, count = hashlib.sha256(), 0
    for chunk, expected in zip(decoded, profile["chunks"]):
        if type(chunk) is not list or len(chunk) != expected["rows"]:
            raise ValueError("Decoded chunk shape validation failed")
        for row in chunk:
            if type(row) is not list or len(row) != len(profile["columns"]):
                raise ValueError("Decoded row shape validation failed")
            digest.update(_row_bytes(row))
            count += 1
    actual = digest.hexdigest()
    if count != profile["row_count"] or actual != profile["ordered_sha256"]:
        raise ValueError("Decoded row count/digest validation failed")
    return {"valid": True, "row_count": count, "ordered_sha256": actual}


def _environment():
    def cgroup(name):
        path = Path("/sys/fs/cgroup") / name
        return path.read_text().strip() if path.is_file() else None
    protocol = TBinaryProtocolAccelerated(TMemoryBuffer())
    return {"python": sys.version, "executable": sys.executable,
        "dependencies": {name: importlib.metadata.version(name) for name in ("thrift", "grpcio", "protobuf")},
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "cpu_count": os.cpu_count(), "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "cgroup_cpu_max": cgroup("cpu.max"), "cgroup_memory_max": cgroup("memory.max"),
        "thrift_fast_decode_available": getattr(protocol, "_fast_decode", None) is not None}


def run_baseline(dataset, profile, repeats=7, warmups=1):
    _integer(repeats, "repeats", minimum=3)
    _integer(warmups, "warmups")
    if platform.system() != "Linux":
        raise ValueError("Run this baseline inside the Linux container")
    manifest, selected, payloads = load_dataset(dataset, profile)
    environment = _environment()

    def decode_once():
        wall_start, cpu_start = time.perf_counter(), time.process_time()
        decoded = decode_result_batches(selected["columns"], payloads)
        cpu_seconds = time.process_time() - cpu_start
        wall_seconds = time.perf_counter() - wall_start
        validation = validate_rows(decoded, selected)
        del decoded
        return {"wall_seconds": wall_seconds, "cpu_seconds": cpu_seconds,
                "rows_per_second": selected["row_count"] / wall_seconds,
                "input_mib_per_second": selected["input_bytes"] / 1048576 / wall_seconds}, validation

    cold, _ = decode_once()
    warmup_samples = [decode_once()[0] for _ in range(warmups)]
    samples = []
    for _ in range(repeats):
        sample, validation = decode_once()
        samples.append(sample)
    peak_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    summary = {key: {"min": min(values), "median": statistics.median(values), "max": max(values)}
               for key in samples[0] for values in [[sample[key] for sample in samples]]}
    sources = (result_batch, datainputstream, wire)
    return {"schema_version": 1, "kind": "synthetic-local-decode-baseline",
        "parameters": {"dataset": str(Path(dataset).resolve()), "profile": profile,
                       "repeats": repeats, "warmups": warmups},
        "fixture": {"manifest_sha256": hashlib.sha256((Path(dataset) / "manifest.json").read_bytes()).hexdigest(),
                    "seed": manifest["seed"], "generation": manifest["generation"], **selected},
        "environment": environment,
        "decoder_source_sha256": {Path(module.__file__).name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                                  for module in sources},
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cold_sample": cold, "warmup_samples": warmup_samples, "samples": samples,
        "summary": summary, "validation": validation,
        "process_peak_rss": {"linux_ru_maxrss_kib": peak_kib, "bytes": peak_kib * 1024,
            "scope": "Process lifetime peak including imports, loaded input, warmup and validation; "
                     "not per-decode allocation or child-process aggregate"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="Generate a new frozen synthetic dataset once")
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--rows-per-chunk", type=int, default=8192)
    generate.add_argument("--chunks", type=int, default=8)
    generate.add_argument("--seed", type=int, default=SEED)
    run = commands.add_parser("run", help="Decode existing verified files; never generate input")
    run.add_argument("--dataset", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--profile", choices=COLUMNS, required=True)
    run.add_argument("--repeats", type=int, default=7)
    run.add_argument("--warmups", type=int, default=1)
    args = parser.parse_args()
    if args.command == "generate":
        generate_dataset(args.output, args.rows_per_chunk, args.chunks, args.seed)
    else:
        if args.output.exists():
            raise FileExistsError("Report already exists: %s" % args.output)
        report = run_baseline(args.dataset, args.profile, args.repeats, args.warmups)
        report["command"] = sys.argv
        with args.output.open("x") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")


if __name__ == "__main__":
    main()
