"""Actual Thrift wire roundtrips for every vector model, without a server."""
from importlib.metadata import version

import pytest
from thrift.Thrift import TType
from thrift.protocol import TBinaryProtocol, TCompactProtocol
from thrift.transport.TTransport import TMemoryBuffer

from e6data_python_connector.e6x_vector import ttypes as wire


VALUES = [
    wire.BoolData([False, True]), wire.Int32Data([-2147483648, 2147483647]),
    wire.Int64Data([-9223372036854775808, 9223372036854775807]),
    wire.DateData([-86400000000, 0, 86400000000]),
    wire.Float32Data([-1.5, 0.0, 1.25]), wire.Float64Data([-1.5, 0.0, 1e100]),
    wire.Decimal128Data([b'\x00\xff', b'', b'123.45'], scale=2),
    wire.VarcharData(['', 'quoted\'value', '日本語']),
    wire.BoolConstantData(False), wire.DateConstantData(-86400000000),
    wire.NullConstantData(-128), wire.NumericConstantData(9223372036854775807),
    wire.NumericDecimalConstantData(-12.5),
    wire.NumericDecimal128ConstantData(b'\x00\xff', scale=-2),
    wire.TemporalIntervalConstantData(127), wire.TimeConstantData(123000, '+05:30'),
    wire.VarcharConstantData('Unicode Ω'), wire.TimeData([0, 123000], ['Z', '+05:30']),
]
_DATA_FIELDS = [field for field in wire.Data.thrift_spec if field]
VALUES.append(wire.Data(**{field[2]: next(value for value in VALUES if type(value) is field[3][0])
                           for field in _DATA_FIELDS}))
VALUES.append(wire.Vector(size=2, vectorType=wire.VectorType.STRING,
                          nullSet=[False, True], data=VALUES[-1],
                          isConstantVector=False, zoneOffset='+05:30', format='yyyy'))
VALUES.append(wire.Chunk(size=2, vectors=[VALUES[-1]]))
PROTOCOLS = [TBinaryProtocol.TBinaryProtocol, TCompactProtocol.TCompactProtocol,
             TBinaryProtocol.TBinaryProtocolAccelerated, TCompactProtocol.TCompactProtocolAccelerated]


def encode(value, protocol):
    transport = TMemoryBuffer()
    value.write(protocol(transport))
    return transport.getvalue()


def decode(cls, payload, protocol):
    value = cls()
    value.read(protocol(TMemoryBuffer(payload)))
    return value


@pytest.mark.parametrize('protocol', PROTOCOLS)
@pytest.mark.parametrize('value', VALUES, ids=lambda value: type(value).__name__)
def test_all_fields_roundtrip_and_canonical_encoding(value, protocol):
    payload = encode(value, protocol)
    result = decode(type(value), payload, protocol)
    assert result == value
    assert result.__dict__ == value.__dict__
    assert not (result != value)
    assert result != None
    assert encode(result, protocol) == payload
    for field in value.thrift_spec:
        if field:
            assert field[2] + '=' in repr(result)
    assert result.validate() is None


@pytest.mark.parametrize('protocol', PROTOCOLS)
@pytest.mark.parametrize('value', VALUES, ids=lambda value: type(value).__name__)
def test_absent_optional_fields_remain_absent(value, protocol):
    empty = type(value)()
    result = decode(type(value), encode(empty, protocol), protocol)
    assert result == empty
    assert all(item is None for item in result.__dict__.values())
    assert result != value


@pytest.mark.parametrize('protocol', [TBinaryProtocol.TBinaryProtocol, TCompactProtocol.TCompactProtocol])
@pytest.mark.parametrize('value', VALUES, ids=lambda value: type(value).__name__)
def test_mismatched_field_types_and_unknown_fields_are_skipped(value, protocol):
    transport = TMemoryBuffer()
    output = protocol(transport)
    output.writeStructBegin(type(value).__name__)
    for field in value.thrift_spec:
        if not field:
            continue
        field_id, field_type, field_name, _, _ = field
        wrong_type = TType.I64 if field_type == TType.BOOL else TType.BOOL
        output.writeFieldBegin(field_name, wrong_type, field_id)
        if wrong_type == TType.I64:
            output.writeI64(123)
        else:
            output.writeBool(True)
        output.writeFieldEnd()
    output.writeFieldBegin('future_extension', TType.LIST, 300)
    output.writeListBegin(TType.STRING, 2)
    output.writeString('ignored')
    output.writeString('still ignored')
    output.writeListEnd()
    output.writeFieldEnd()
    output.writeFieldStop()
    output.writeStructEnd()
    result = decode(type(value), transport.getvalue(), protocol)
    assert result == type(value)()


@pytest.mark.parametrize('value', [value for value in VALUES if any(field and field[1] == TType.LIST for field in value.thrift_spec)], ids=lambda value:type(value).__name__)
@pytest.mark.parametrize('protocol', PROTOCOLS)
def test_empty_lists_are_distinct_from_absent(value, protocol):
    fields = {field[2]: [] for field in value.thrift_spec if field and field[1] == TType.LIST}
    empty_lists = type(value)(**fields)
    result = decode(type(value), encode(empty_lists, protocol), protocol)
    assert result == empty_lists
    assert result != type(value)()


@pytest.mark.parametrize('protocol', PROTOCOLS)
def test_truncated_thrift_struct_is_rejected(protocol):
    payload = encode(wire.Int64Data([1, 2, 3]), protocol)
    assert decode(wire.Int64Data, payload, protocol) == wire.Int64Data([1, 2, 3])
    with pytest.raises((EOFError, TypeError, SystemError)) as rejected:
        decode(wire.Int64Data, payload[:-2], protocol)
    if isinstance(rejected.value, SystemError):
        # THRIFT-5892: some native 0.20 builds reject truncated Binary/Compact data
        # with this error. Do not accept unrelated errors or newer regressions.
        # https://issues.apache.org/jira/browse/THRIFT-5892
        assert protocol in (TBinaryProtocol.TBinaryProtocolAccelerated,
                            TCompactProtocol.TCompactProtocolAccelerated)
        assert protocol(TMemoryBuffer())._fast_decode is not None
        assert version('thrift') == '0.20.0'
        assert str(rejected.value) == "PY_SSIZE_T_CLEAN macro must be defined for '#' formats"


def test_vector_enum_name_mapping_is_bijective():
    assert len(wire.VectorType._VALUES_TO_NAMES) == 17
    for value, name in wire.VectorType._VALUES_TO_NAMES.items():
        assert wire.VectorType._NAMES_TO_VALUES[name] == value
