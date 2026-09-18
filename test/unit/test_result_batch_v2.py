"""V2 envelope contracts using real Thrift bytes and production buffer state."""

import importlib
import importlib.util

import pytest
from thrift.protocol.TBinaryProtocol import TBinaryProtocol
from thrift.transport.TTransport import TMemoryBuffer

from e6data_python_connector.e6x_vector import ttypes as wire


def result_batch_module():
    name = "e6data_python_connector.result_batch"
    assert importlib.util.find_spec(name) is not None, "V2 envelope codec and buffer are missing"
    return importlib.import_module(name)


def encode_chunk(chunk):
    transport = TMemoryBuffer()
    chunk.write(TBinaryProtocol(transport))
    return transport.getvalue()


def string_chunk(values):
    vector = wire.Vector(
        len(values), wire.VectorType.STRING, [False] * len(values),
        wire.Data(varcharData=wire.VarcharData(values)),
    )
    return encode_chunk(wire.Chunk(len(values), [vector]))


def test_decodes_independent_chunks_in_original_order():
    module = result_batch_module()
    assert module.decode_result_batches(
        ["value"], [string_chunk(["alpha", "beta"]), string_chunk(["gamma"])],
    ) == [[["alpha"], ["beta"]], [["gamma"]]]


def test_valid_zero_row_chunks_do_not_discard_following_data():
    module = result_batch_module()
    empty = encode_chunk(wire.Chunk(0, []))
    assert module.decode_result_batches(
        ["value"], [empty, string_chunk(["one"]), empty, string_chunk(["two"])],
    ) == [[["one"]], [["two"]]]


def test_empty_envelope_decodes_to_no_chunks():
    assert result_batch_module().decode_result_batches(["value"], []) == []


def test_zero_row_serialized_chunk_decodes_to_no_chunks():
    empty = encode_chunk(wire.Chunk(0, []))
    assert result_batch_module().decode_result_batches(["value"], [empty]) == []


@pytest.mark.parametrize("later", [False, True])
def test_zero_length_bytes_are_malformed_even_after_valid_data(later):
    payloads = [string_chunk(["one"]), b""] if later else [b""]
    with pytest.raises(ValueError):
        result_batch_module().decode_result_batches(["value"], payloads)


def test_corrupt_later_chunk_cannot_publish_a_partial_envelope():
    module = result_batch_module()
    buffer = module.ResultBatchBuffer()
    mismatched_vector = wire.Vector(
        2, wire.VectorType.STRING, [False, False],
        wire.Data(varcharData=wire.VarcharData(["two", "three"])),
    )
    malformed = encode_chunk(wire.Chunk(1, [mismatched_vector]))
    with pytest.raises(ValueError):
        chunks = module.decode_result_batches(["value"], [string_chunk(["one"]), malformed])
        buffer.accept(chunks, end_of_stream=True)
    assert buffer.needs_fetch
    assert not buffer.finished
    assert buffer.pop() is None


def test_terminal_marker_waits_for_all_pending_chunks_to_be_delivered():
    buffer = result_batch_module().ResultBatchBuffer()
    buffer.accept([[[1], [2]], [[3]]], end_of_stream=True)
    assert not buffer.needs_fetch
    assert not buffer.finished
    assert buffer.pop() == [[1], [2]]
    assert not buffer.needs_fetch
    assert not buffer.finished
    assert buffer.pop() == [[3]]
    assert buffer.finished
    assert not buffer.needs_fetch
    assert buffer.pop() is None
    assert buffer.finished


def test_draining_nonterminal_envelope_allows_the_next_envelope():
    buffer = result_batch_module().ResultBatchBuffer()
    assert buffer.needs_fetch
    assert not buffer.finished
    assert buffer.pop() is None
    buffer.accept([[[1]], [[2]]], end_of_stream=False)
    assert buffer.pop() == [[1]]
    assert not buffer.needs_fetch
    assert buffer.pop() == [[2]]
    assert buffer.needs_fetch
    assert not buffer.finished
    buffer.accept([[[3]]], end_of_stream=True)
    assert buffer.pop() == [[3]]
    assert buffer.finished


@pytest.mark.parametrize("terminal", [False, True])
def test_empty_envelope_respects_explicit_terminal_marker(terminal):
    buffer = result_batch_module().ResultBatchBuffer()
    buffer.accept([], end_of_stream=terminal)
    assert buffer.pop() is None
    assert buffer.finished is terminal
    assert buffer.needs_fetch is not terminal


@pytest.mark.parametrize("terminal", [False, True])
def test_accept_cannot_replace_pending_chunks_or_change_their_terminal_state(terminal):
    buffer = result_batch_module().ResultBatchBuffer()
    buffer.accept([[[1]], [[2]]], end_of_stream=terminal)
    assert buffer.pop() == [[1]]
    with pytest.raises(ValueError):
        buffer.accept([[[99]]], end_of_stream=not terminal)
    assert buffer.pop() == [[2]]
    assert buffer.finished is terminal
    assert buffer.needs_fetch is not terminal


@pytest.mark.parametrize("chunks", [[], [[[1]]]])
def test_terminal_stream_rejects_another_envelope_until_clear(chunks):
    buffer = result_batch_module().ResultBatchBuffer()
    buffer.accept(chunks, end_of_stream=True)
    if chunks:
        assert buffer.pop() == [[1]]
    with pytest.raises(ValueError):
        buffer.accept([[[2]]], end_of_stream=False)
    assert buffer.finished
    assert buffer.pop() is None


@pytest.mark.parametrize("terminal", [False, True])
def test_clear_discards_pending_chunks_and_resets_terminal_state(terminal):
    buffer = result_batch_module().ResultBatchBuffer()
    buffer.accept([[[1]], [[2]]], end_of_stream=terminal)
    buffer.clear()
    assert buffer.needs_fetch
    assert not buffer.finished
    assert buffer.pop() is None
    buffer.accept([[[3]]], end_of_stream=True)
    assert buffer.pop() == [[3]]
    assert buffer.finished
    buffer.clear()
    buffer.clear()
    assert buffer.needs_fetch
    assert not buffer.finished
