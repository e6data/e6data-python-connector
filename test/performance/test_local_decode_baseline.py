"""Small real-wire tests for the synthetic decode baseline. No timing limits."""
import hashlib
import importlib
import importlib.util
import json
import subprocess
import sys
from decimal import Decimal

import pytest


def harness():
    assert importlib.util.find_spec("local_decode_baseline"), "baseline harness is missing"
    return importlib.import_module("local_decode_baseline")


def dataset(tmp_path):
    path = tmp_path / "dataset"
    harness().generate_dataset(path, rows_per_chunk=3, chunks=2, seed=7)
    return path


def change_manifest(path, edit, update_hash=True):
    manifest = json.loads((path / "manifest.json").read_text())
    edit(manifest)
    raw = json.dumps(manifest).encode()
    (path / "manifest.json").write_bytes(raw)
    if update_hash:
        (path / "manifest.sha256").write_text(hashlib.sha256(raw).hexdigest() + "\n")


def test_fixed_fixtures_have_literal_values_and_real_envelope_order(tmp_path):
    mod = harness()
    path = dataset(tmp_path)
    manifest, profile, payloads = mod.load_dataset(path, "mixed")
    decoded = mod.decode_result_batches(profile["columns"], payloads)
    assert decoded[0] == [
        [0, 0.25, None, "1970-01-01", Decimal("-9999.63"), "constant"],
        [1, 1.25, "row-00000001", "1970-01-02", Decimal("-9998.63"), "constant"],
        [2, 2.25, "row-00000002", "1970-01-03", Decimal("-9997.63"), "constant"],
    ]
    assert decoded[1][0][0] == 3
    assert type(decoded[0][0][0]) is int
    assert type(decoded[0][0][1]) is float
    assert type(decoded[0][0][4]) is Decimal
    assert str(decoded[0][0][4]) == "-9999.63"
    assert manifest["schema_version"] == 1
    assert manifest["seed"] == 7
    assert profile["row_count"] == 6
    assert profile["input_bytes"] == sum(map(len, payloads))
    _, numeric, raw = mod.load_dataset(path, "numeric")
    assert mod.decode_result_batches(numeric["columns"], raw)[0] == [
        [0, 0.25, 0, True], [1, 1.25, 1, False], [2, 2.25, 2, True],
    ]
    _, wide, raw = mod.load_dataset(path, "wide_strings")
    assert mod.decode_result_batches(wide["columns"], raw)[0][0] == [0,
        "f27036d7f5a30f84854245c45d9d155b608f12f3a5bddc4277102cc443697773",
        "9ebbfc59547ce6f5dc899d43c8d32515e37c6d478c2d9dd52071ddeb3d37d58c",
        "ad5cf2a9eca3876cc4c5bce669418d3f7184533003118353fd305b141b96df96",
        "316ef39321034608704db5751baad1e76ee00a0ae3d5c5e009ed1d4a211775c6",
    ]


def test_generation_is_byte_identical_and_refuses_overwrite(tmp_path):
    mod = harness()
    first = dataset(tmp_path)
    second = tmp_path / "second"
    mod.generate_dataset(second, rows_per_chunk=3, chunks=2, seed=7)
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {
        p.name: p.read_bytes() for p in second.iterdir()}
    with pytest.raises(FileExistsError):
        mod.generate_dataset(first)


@pytest.mark.parametrize("mutation", ["order", "null", "type", "count", "decimal"])
def test_validation_rejects_wrong_rows(mutation, tmp_path):
    mod = harness()
    _, profile, raw = mod.load_dataset(dataset(tmp_path), "mixed")
    decoded = mod.decode_result_batches(profile["columns"], raw)
    if mutation == "order":
        decoded.reverse()
    elif mutation == "null":
        decoded[0][0][2] = ""
    elif mutation == "type":
        decoded[0][0][0] = 0.0
    elif mutation == "count":
        decoded.pop()
    else:
        decoded[0][0][4] = Decimal("-9999.630")
    with pytest.raises(ValueError, match="validation"):
        mod.validate_rows(decoded, profile)


@pytest.mark.parametrize("level", ["outer", "chunk", "row"])
def test_validation_rejects_lazy_results_without_consuming_them(tmp_path, level):
    mod = harness()
    _, profile, raw = mod.load_dataset(dataset(tmp_path), "mixed")
    decoded = mod.decode_result_batches(profile["columns"], raw)
    consumed = []

    def delayed(values):
        for value in values:
            consumed.append(True)
            yield value

    if level == "outer":
        decoded = delayed(decoded)
    elif level == "chunk":
        decoded[0] = delayed(decoded[0])
    else:
        decoded[0][0] = delayed(decoded[0][0])
    with pytest.raises(ValueError, match="validation"):
        mod.validate_rows(decoded, profile)
    assert consumed == []


@pytest.mark.parametrize("mutation", ["coalesce", "split", "shift", "empty"])
def test_validation_requires_original_chunk_boundaries(tmp_path, mutation):
    mod = harness()
    _, profile, raw = mod.load_dataset(dataset(tmp_path), "mixed")
    decoded = mod.decode_result_batches(profile["columns"], raw)
    original_rows = [row for chunk in decoded for row in chunk]
    if mutation == "coalesce":
        decoded = [original_rows]
    elif mutation == "split":
        decoded = [decoded[0][:1], decoded[0][1:], decoded[1]]
    elif mutation == "shift":
        decoded = [decoded[0][:-1], decoded[0][-1:] + decoded[1]]
    else:
        decoded.insert(0, [])
    assert [row for chunk in decoded for row in chunk] == original_rows
    with pytest.raises(ValueError, match="validation"):
        mod.validate_rows(decoded, profile)


@pytest.mark.parametrize("level", ["outer", "chunk", "row"])
def test_validation_requires_real_decoder_list_shapes(tmp_path, level):
    mod = harness()
    _, profile, raw = mod.load_dataset(dataset(tmp_path), "mixed")
    decoded = mod.decode_result_batches(profile["columns"], raw)
    if level == "outer":
        decoded = tuple(decoded)
    elif level == "chunk":
        decoded[0] = tuple(decoded[0])
    else:
        decoded[0][0] = tuple(decoded[0][0])
    with pytest.raises(ValueError, match="validation"):
        mod.validate_rows(decoded, profile)


def test_fixture_corruption_fails_before_decode(tmp_path):
    path = dataset(tmp_path)
    chunk = path / "mixed-0000.thrift"
    chunk.write_bytes(chunk.read_bytes() + b"corrupt")
    with pytest.raises(ValueError, match="hash|size"):
        harness().load_dataset(path, "mixed")


@pytest.mark.parametrize("mutation", ["manifest_hash", "schema", "traversal", "absolute", "duplicate", "bytes", "rows", "column"])
def test_bad_manifest_is_rejected(tmp_path, mutation):
    path = dataset(tmp_path)

    def edit(manifest):
        profile = manifest["profiles"]["mixed"]
        if mutation == "schema":
            manifest["schema_version"] = 2
        elif mutation in ("traversal", "absolute"):
            profile["chunks"][0]["file"] = "../outside.thrift" if mutation == "traversal" else "/tmp/outside.thrift"
        elif mutation == "duplicate":
            profile["chunks"][1] = profile["chunks"][0]
        elif mutation == "bytes":
            profile["input_bytes"] += 1
        elif mutation == "rows":
            profile["row_count"] += 1
        elif mutation == "column":
            profile["columns"].reverse()
        else:
            manifest["seed"] = 8

    change_manifest(path, edit, update_hash=mutation != "manifest_hash")
    with pytest.raises(ValueError):
        harness().load_dataset(path, "mixed")


def test_symlink_chunk_cannot_escape_dataset(tmp_path):
    path = dataset(tmp_path)
    target = path / "mixed-0000.thrift"
    outside = tmp_path / "outside.thrift"
    target.rename(outside)
    target.symlink_to(outside)
    with pytest.raises(ValueError, match="path"):
        harness().load_dataset(path, "mixed")


@pytest.mark.parametrize("repeats", [0, 1, 2, -1, True, 3.5])
def test_invalid_or_too_few_repeats_fail(tmp_path, repeats):
    with pytest.raises(ValueError, match="repeats"):
        harness().run_baseline(tmp_path / "missing", "numeric", repeats=repeats)


@pytest.mark.parametrize("field,value", [("rows_per_chunk", 0), ("chunks", 0), ("seed", True)])
def test_invalid_generation_inputs_do_not_create_directory(tmp_path, field, value):
    path = tmp_path / "missing"
    with pytest.raises(ValueError):
        harness().generate_dataset(path, **{field: value})
    assert not path.exists()


def test_real_run_reports_samples_units_and_validity(tmp_path):
    report = harness().run_baseline(dataset(tmp_path), "mixed", repeats=3)
    assert report["kind"] == "synthetic-local-decode-baseline"
    assert report["validation"]["valid"] is True
    assert report["validation"]["row_count"] == 6
    assert len(report["samples"]) == 3
    assert len(report["warmup_samples"]) == 1
    assert report["cold_sample"]["wall_seconds"] >= 0
    for sample in report["samples"]:
        assert sample["wall_seconds"] > 0
        assert sample["cpu_seconds"] >= 0
        assert sample["rows_per_second"] == pytest.approx(6 / sample["wall_seconds"])
        assert sample["input_mib_per_second"] == pytest.approx(
            report["fixture"]["input_bytes"] / 1048576 / sample["wall_seconds"])
    walls = sorted(sample["wall_seconds"] for sample in report["samples"])
    assert report["summary"]["wall_seconds"] == {"min": walls[0], "median": walls[1], "max": walls[2]}
    assert report["process_peak_rss"]["bytes"] == report["process_peak_rss"]["linux_ru_maxrss_kib"] * 1024
    assert "validation" in report["process_peak_rss"]["scope"]
    assert report["environment"]["platform"]["system"] == "Linux"
    assert isinstance(report["environment"]["thrift_fast_decode_available"], bool)
    assert {"result_batch.py", "datainputstream.py", "ttypes.py"} <= set(report["decoder_source_sha256"])


def test_wrong_expected_digest_is_rejected_by_real_run(tmp_path):
    path = dataset(tmp_path)
    change_manifest(path, lambda m: m["profiles"]["mixed"].update(ordered_sha256="0" * 64))
    with pytest.raises(ValueError, match="validation"):
        harness().run_baseline(path, "mixed", repeats=3)


@pytest.mark.parametrize("warmups", [0, -1, True, 1.5])
def test_run_requires_at_least_one_valid_warmup(tmp_path, warmups):
    with pytest.raises(ValueError, match="warmups"):
        harness().run_baseline(tmp_path / "missing", "numeric", repeats=3, warmups=warmups)


def test_cli_generate_uses_explicit_recipe_and_refuses_existing_output(tmp_path):
    path = tmp_path / "generated"
    command = [sys.executable, harness().__file__, "generate", "--output", str(path),
               "--rows-per-chunk", "2", "--chunks", "1", "--seed", "7"]
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads((path / "manifest.json").read_text())["profiles"]["mixed"]["row_count"] == 2
    assert subprocess.run(command, capture_output=True).returncode != 0


def test_cli_writes_report_and_never_generates_on_run(tmp_path):
    mod = harness()
    output = tmp_path / "report.json"
    command = [sys.executable, mod.__file__, "run", "--dataset", str(dataset(tmp_path)),
               "--profile", "numeric", "--repeats", "3", "--output", str(output)]
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())["validation"]["row_count"] == 6
    missing = tmp_path / "missing"
    command[command.index("--dataset") + 1] = str(missing)
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert not missing.exists()
