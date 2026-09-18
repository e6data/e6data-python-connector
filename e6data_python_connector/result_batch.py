"""Decode complete V2 result envelopes and retain their original chunk order."""

from collections import deque

from e6data_python_connector.datainputstream import read_rows_from_chunk


def decode_result_batches(columns, payloads):
    """Return all nonempty chunks only after every payload decodes successfully."""
    chunks = []
    for payload in payloads:
        if not payload:
            raise ValueError("Empty serialized result chunk.")
        rows = read_rows_from_chunk(columns, payload, strict=True)
        if rows:
            chunks.append(rows)
    return chunks


class ResultBatchBuffer:
    """Keep one decoded envelope until its chunks have been delivered."""

    def __init__(self):
        self._chunks = deque()
        self._end_of_stream = False

    def accept(self, chunks, end_of_stream):
        """Accept an envelope only after a nonterminal predecessor is drained."""
        if self._chunks or self._end_of_stream:
            raise ValueError("Cannot replace pending chunks or a terminal result stream.")
        self._chunks = deque(chunks)
        self._end_of_stream = end_of_stream

    def pop(self):
        """Return the next original chunk, or None when none remain."""
        return self._chunks.popleft() if self._chunks else None

    def clear(self):
        """Release pending chunks and reset the buffer for another query."""
        self._chunks.clear()
        self._end_of_stream = False

    @property
    def needs_fetch(self):
        return not self._chunks and not self._end_of_stream

    @property
    def finished(self):
        return not self._chunks and self._end_of_stream
