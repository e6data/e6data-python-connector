"""Calendar components survive the actual metadata, row and vector decoders."""
import struct
from io import BytesIO

import pytest
from thrift.protocol.TBinaryProtocol import TBinaryProtocol, TBinaryProtocolAccelerated
from thrift.transport.TTransport import TMemoryBuffer

from e6data_python_connector.calendar_interval import CalendarInterval
from e6data_python_connector.datainputstream import (
    DataInputStream, FieldInfo, get_column_from_chunk, get_query_columns_info,
    read_rows_from_chunk, read_values_from_array,
)
from e6data_python_connector.e6x_vector.ttypes import (
    CalendarIntervalData, Chunk, Data, NullConstantData, Vector, VectorType,
)


def encode(value, protocol=TBinaryProtocol):
    buffer = TMemoryBuffer()
    value.write(protocol(buffer))
    return buffer.getvalue()


@pytest.mark.parametrize('protocol', [TBinaryProtocol, TBinaryProtocolAccelerated])
def test_wire_to_rows_preserves_components_and_nulls(protocol):
    vector = Vector(size=3, vectorType=VectorType.CALENDAR_INTERVAL,
                    nullSet=[False, True, False], isConstantVector=False,
                    data=Data(calendarIntervalData=CalendarIntervalData(
                        [14, 0, -2147483648], [25, 0, 2147483647],
                        [18367500000, 0, -9223372036854775808])))
    rows = read_rows_from_chunk([FieldInfo('value', 'CALENDAR_INTERVAL', '', '')],
                               encode(Chunk(3, [vector]), protocol), strict=True)
    assert rows == [[CalendarInterval(14, 25, 18367500000)], [None],
                    [CalendarInterval(-2147483648, 2147483647, -9223372036854775808)]]
    assert str(rows[0][0]) == '1 years 2 months 25 days 5 hours 6 minutes 7.5 seconds'
    assert str(rows[2][0]) == '-178956970 years -8 months 2147483647 days -2562047788 hours -54.775808 seconds'


def test_constant_null_and_signed_fractional_values():
    vector = Vector(size=3, vectorType=VectorType.CALENDAR_INTERVAL,
                    nullSet=[False], isConstantVector=True,
                    data=Data(calendarIntervalData=CalendarIntervalData([-13], [2], [-60000001])))
    value = CalendarInterval(-13, 2, -60000001)
    assert get_column_from_chunk(vector, strict=True) == [value] * 3
    assert str(value) == '-1 years -1 months 2 days -1 minutes -0.000001 seconds'
    assert str(CalendarInterval(0, 0, 0)) == '0 seconds'
    assert str(CalendarInterval(0, 0, -1)) == '-0.000001 seconds'
    vector.nullSet = [True]
    vector.data = Data(nullConstantData=NullConstantData())
    assert get_column_from_chunk(vector, strict=True) == [None] * 3


@pytest.mark.parametrize('payload', [None, CalendarIntervalData([1], [], [1]),
                                     CalendarIntervalData(None, [1], [1])])
def test_incomplete_non_null_payload_obeys_decoder_error_policy(payload):
    vector = Vector(size=1, vectorType=VectorType.CALENDAR_INTERVAL,
                    nullSet=[False], isConstantVector=False, data=Data(calendarIntervalData=payload))
    with pytest.raises(ValueError, match='CALENDAR_INTERVAL'):
        get_column_from_chunk(vector, strict=True)
    assert get_column_from_chunk(vector) == ['Failed to parse.']


def test_metadata_and_legacy_row_decoder_keep_calendar_type():
    strings = ['value', 'CALENDAR_INTERVAL', '', '']
    metadata = struct.pack('>qi', 1, 1) + b''.join(
        struct.pack('>H', len(s.encode())) + s.encode() for s in strings)
    count, fields = get_query_columns_info(BytesIO(metadata))
    assert count == 1 and fields[0].get_field_type() == 'CALENDAR_INTERVAL'
    row = DataInputStream(BytesIO(b'\x01' + struct.pack('>iiq', 14, 25, 18367500000)))
    assert read_values_from_array(fields, row) == [CalendarInterval(14, 25, 18367500000)]
    assert read_values_from_array(fields, DataInputStream(BytesIO(b'\x00'))) == [None]
