"""Binary decoding contracts using real bytes, Thrift structs and protocols."""
import io
import struct
from datetime import datetime
from decimal import Decimal, localcontext

import pytest
from thrift.protocol.TBinaryProtocol import TBinaryProtocol
from thrift.transport.TTransport import TMemoryBuffer

from e6data_python_connector import datainputstream as decoder
from e6data_python_connector.e6x_vector import ttypes as wire


def utf(value):
    data = value.encode() if isinstance(value, str) else value
    return struct.pack('>H', len(data)) + data


@pytest.mark.parametrize('method,fmt,value', [
    ('read_boolean','?',True),('read_boolean','?',False),('read_byte','b',-128),
    ('read_unsigned_byte','B',255),('read_char','>H',ord('Ω')),
    ('read_double','>d',-12.5),('read_float','>f',1.25),
    ('read_short','>h',-32768),('read_unsigned_short','>H',65535),
    ('read_int','>i',-2147483648),('read_unsigned_int','>I',4294967295),
    ('read_long','>q',-9223372036854775808),
])
def test_fixed_width_values_and_truncation(method, fmt, value):
    payload = struct.pack(fmt, value)
    source = io.BytesIO(payload + b'end')
    result = getattr(decoder.DataInputStream(source), method)()
    assert result == (chr(value) if method == 'read_char' else value)
    assert source.read() == b'end'
    with pytest.raises(struct.error):
        getattr(decoder.DataInputStream(io.BytesIO(payload[:-1])), method)()


def test_byte_array_and_length_prefixed_utf_preserve_boundaries():
    stream = decoder.DataInputStream(io.BytesIO(b'\x00\xff' + utf('日本語') + b'end'))
    array = bytearray(2)
    assert stream.read_bytes(array) is array
    assert array == b'\x00\xff'
    assert stream.read_utf() == '日本語'.encode()
    assert stream.stream.read() == b'end'
    assert decoder.DataInputStream(io.BytesIO(utf(b''))).read_utf() == b''


def test_real_metadata_wire_describes_all_fields():
    columns=[('id','LONG','Z',''),('day','DATE','+05:30','yyyy'),('time','DATETIME','Z','HH')]
    payload=struct.pack('>qi',123,len(columns))+b''.join(utf(value) for column in columns for value in column)
    count,result=decoder.get_query_columns_info(io.BytesIO(payload))
    assert count==123
    assert [(value.get_name(),value.get_field_type()) for value in result]==[(row[0],row[1]) for row in columns]
    assert [(value.get_zone(),value.get_format()) for value in result]==[(None,None),('+05:30','yyyy'),('Z','HH')]
    assert decoder.get_query_columns_info(io.BytesIO(struct.pack('>qi',0,0)))==(0,[])
    with pytest.raises(struct.error):
        decoder.get_query_columns_info(io.BytesIO(payload[:8]))


ROW_CASES=[
 ('LONG',struct.pack('>q',-123),-123),('DATE',struct.pack('>q',0),'1970-01-01'),
 ('DATETIME',struct.pack('>q',123000),'1970-01-01 00:00:00'),
 ('STRING',utf('hello'),'hello'),('ARRAY',utf('[1]'),'[1]'),('MAP',utf('{a:1}'),'{a:1}'),
 ('STRUCT',utf('{a:1}'),'{a:1}'),('INT',struct.pack('>i',-1),-1),
 ('INTEGER',struct.pack('>i',42),42),('DOUBLE',struct.pack('>d',1.25),1.25),
 ('FLOAT',struct.pack('>f',-1.5),-1.5),('BINARY',utf(b'\x00\xff'),b'\x00\xff'),
 ('CHAR',struct.pack('>H',ord('Ω')),'Ω'),('BOOLEAN',b'\x01',True),
 ('SHORT',struct.pack('>h',-22),-22),('BYTE',b'\xff',-1),
 ('DECIMAL128',utf('1234567890.123456789'),'1234567890.123456789'),
]


@pytest.mark.parametrize('dtype,payload,expected',ROW_CASES)
def test_rowwise_decoder_types_nulls_and_truncation(dtype,payload,expected):
    field=decoder.FieldInfo('value',dtype,'','Z')
    result=decoder.read_values_from_array([field],decoder.DataInputStream(io.BytesIO(b'\x01'+payload)))
    assert result == [Decimal(expected) if dtype=='DECIMAL128' else expected]
    assert decoder.read_values_from_array([field],decoder.DataInputStream(io.BytesIO(b'\x00')))==[None]
    assert decoder.read_values_from_array([field],decoder.DataInputStream(io.BytesIO(b'\x01')))==['Failed to parse.']


def test_int96_row_encoding_uses_julian_day_and_nanoseconds():
    field=decoder.FieldInfo('timestamp','INT96','','')
    payload=b'\x01'+struct.pack('>iq',2440588,123000000)
    # Existing row-wise protocol interprets the Julian-day base in local time.
    expected=datetime.fromtimestamp(0).replace(microsecond=123000)
    assert decoder.read_values_from_array([field],decoder.DataInputStream(io.BytesIO(payload)))==[expected]


VECTOR_CASES=[
 (wire.VectorType.LONG,'int64Data',wire.Int64Data,'numericConstantData',wire.NumericConstantData,42,42),
 (wire.VectorType.INTEGER,'int32Data',wire.Int32Data,'numericConstantData',wire.NumericConstantData,-2,-2),
 (wire.VectorType.BOOLEAN,'boolData',wire.BoolData,'boolConstantData',wire.BoolConstantData,False,False),
 (wire.VectorType.FLOAT,'float32Data',wire.Float32Data,'numericDecimalConstantData',wire.NumericDecimalConstantData,1.25,1.25),
 (wire.VectorType.DOUBLE,'float64Data',wire.Float64Data,'numericDecimalConstantData',wire.NumericDecimalConstantData,-2.5,-2.5),
 (wire.VectorType.DATE,'dateData',wire.DateData,'dateConstantData',wire.DateConstantData,0,'1970-01-01'),
 (wire.VectorType.DATETIME,'timeData',wire.TimeData,'timeConstantData',wire.TimeConstantData,123000,'1970-01-01T00:00:00.123+00:00'),
]+[(kind,'varcharData',wire.VarcharData,'varcharConstantData',wire.VarcharConstantData,'hello','hello')
   for kind in (wire.VectorType.STRING,wire.VectorType.ARRAY,wire.VectorType.MAP,wire.VectorType.STRUCT,wire.VectorType.BINARY)]


@pytest.mark.parametrize('dtype,field,cls,constant_field,constant_cls,value,expected',VECTOR_CASES)
@pytest.mark.parametrize('constant',[False,True])
def test_vectors_regular_constant_nulls_and_chunk_transposition(dtype,field,cls,constant_field,constant_cls,value,expected,constant):
    values=wire.Data(**{constant_field:constant_cls(value)} if constant else {field:cls([value,value,value])})
    vector=wire.Vector(size=3,vectorType=dtype,nullSet=[False] if constant else [False,True,False],data=values,isConstantVector=constant)
    expected_column=[expected]*3 if constant else [expected,None,expected]
    assert decoder.get_column_from_chunk(vector)==expected_column
    transport=TMemoryBuffer()
    wire.Chunk(size=3,vectors=[vector,vector]).write(TBinaryProtocol(transport))
    assert decoder.read_rows_from_chunk(['first','second'],transport.getvalue())==[[item,item] for item in expected_column]
    vector.nullSet=[True]*3
    assert decoder.get_column_from_chunk(vector)==[None]*3


@pytest.mark.parametrize('constant',[False,True])
@pytest.mark.parametrize('zone,expected',[('+05:30','1970-01-01T05:30:00.000+05:30'),(None,'1970-01-01T00:00:00.000+00:00')])
def test_timezone_vectors(constant,zone,expected):
    data=(wire.Data(timeConstantData=wire.TimeConstantData(0,zone)) if constant else
          wire.Data(timeData=wire.TimeData([0,0],None if zone is None else [zone,zone])))
    vector=wire.Vector(2,wire.VectorType.TIMESTAMP_TZ,[False,False],data,constant)
    assert decoder.get_column_from_chunk(vector)==[expected,expected]
    vector.nullSet=[True,True]
    assert decoder.get_column_from_chunk(vector)==[None,None]


@pytest.mark.parametrize('constant',[False,True])
def test_decimal_vectors_use_signed_unscaled_big_integer_and_scale(constant):
    raw=(-12345).to_bytes(16,'big',signed=True)
    data=(wire.Data(numericDecimal128ConstantData=wire.NumericDecimal128ConstantData(raw,2)) if constant else
          wire.Data(decimal128Data=wire.Decimal128Data([raw,raw],2)))
    vector=wire.Vector(2,wire.VectorType.DECIMAL128,[False,False],data,constant)
    assert decoder.get_column_from_chunk(vector)==[Decimal('-123.45')]*2
    vector.nullSet=[True,True]
    assert decoder.get_column_from_chunk(vector)==[None,None]


def test_empty_null_unsupported_and_malformed_vectors_are_explicit():
    assert decoder.get_column_from_chunk(wire.Vector(3,wire.VectorType.NULL))==[None]*3
    assert decoder.get_column_from_chunk(wire.Vector(1,999))==[None]
    broken=wire.Vector(3,wire.VectorType.LONG,[False]*3,wire.Data(int64Data=wire.Int64Data([1])),False)
    assert decoder.get_column_from_chunk(broken)==[1,'Failed to parse.','Failed to parse.']
    for dtype,field,cls in [(wire.VectorType.DATE,'dateData',wire.DateData),(wire.VectorType.DATETIME,'timeData',wire.TimeData),(wire.VectorType.TIMESTAMP_TZ,'timeData',wire.TimeData)]:
        vector=wire.Vector(2,dtype,[False,False],wire.Data(**{field:cls([0])}),False)
        assert decoder.get_column_from_chunk(vector)[1]=='Failed to parse.'
    empty=TMemoryBuffer()
    wire.Chunk(size=0,vectors=[]).write(TBinaryProtocol(empty))
    assert decoder.read_rows_from_chunk([],empty.getvalue()) is None
    with pytest.raises(EOFError):
        decoder.read_rows_from_chunk([],b'')


@pytest.mark.parametrize('value',[0,1,-1,12345,-12345,2**127-1,-2**127])
@pytest.mark.parametrize('scale',[None,0,2,-2])
def test_decimal128_java_style_signed_precision(value,scale):
    with localcontext() as context:
        context.prec=100
        raw=value.to_bytes(16,'big',signed=True)
        expected=Decimal(value) if scale is None else Decimal(value).scaleb(-scale)
        assert decoder._decode_decimal128_binary_java_style(raw,scale)==expected


@pytest.mark.parametrize('value,expected',[(None,None),(b'',None),('12.34',Decimal('12.34')),(b'12.34',Decimal('12.34')),(123,Decimal(123)),(b'\xff',Decimal(0)),('invalid',Decimal(0))])
def test_decimal_input_compatibility(value,expected):
    assert decoder._binary_to_decimal128(value)==expected


def test_decimal_binary_length_and_empty_constant():
    for length in (0,1,15,17):
        with pytest.raises(ValueError):
            decoder._decode_decimal128_binary_java_style(b'\x00'*length)
        with pytest.raises(ValueError):
            decoder._decode_decimal128_binary(b'\x00'*length)
    assert decoder._decode_decimal128_binary(bytes(16))==Decimal(0)
    vector=wire.Vector(2,wire.VectorType.DECIMAL128,[False],wire.Data(numericDecimal128ConstantData=wire.NumericDecimal128ConstantData(b'')),True)
    assert decoder.get_column_from_chunk(vector)==[Decimal(0),Decimal(0)]
    assert isinstance(decoder.is_fastbinary_available(),bool)


def corrupt_chunk(dtype):
    field,cls={wire.VectorType.LONG:('int64Data',wire.Int64Data),
               wire.VectorType.DATE:('dateData',wire.DateData),
               wire.VectorType.DATETIME:('timeData',wire.TimeData),
               wire.VectorType.TIMESTAMP_TZ:('timeData',wire.TimeData)}[dtype]
    vector=wire.Vector(2,dtype,[False,False],wire.Data(**{field:cls([0])}),False)
    transport=TMemoryBuffer()
    wire.Chunk(2,[vector]).write(TBinaryProtocol(transport))
    return transport.getvalue()


@pytest.mark.parametrize('dtype',[wire.VectorType.LONG,wire.VectorType.DATE,wire.VectorType.DATETIME,wire.VectorType.TIMESTAMP_TZ])
def test_strict_decoder_rejects_real_serialized_truncated_vectors(dtype):
    payload=corrupt_chunk(dtype)
    legacy=decoder.read_rows_from_chunk(['value'],payload)
    assert legacy[1]==['Failed to parse.']
    with pytest.raises(IndexError):
        decoder.read_rows_from_chunk(['value'],payload,strict=True)


@pytest.mark.parametrize('strict',[False,True])
def test_literal_failure_text_remains_valid_string_data(strict):
    vector=wire.Vector(1,wire.VectorType.STRING,[False],wire.Data(varcharData=wire.VarcharData(['Failed to parse.'])),False)
    transport=TMemoryBuffer()
    wire.Chunk(1,[vector]).write(TBinaryProtocol(transport))
    assert decoder.read_rows_from_chunk(['value'],transport.getvalue(),strict=strict)==[['Failed to parse.']]


@pytest.mark.parametrize('dtype',[wire.VectorType.LONG,wire.VectorType.DATE,wire.VectorType.DATETIME,wire.VectorType.TIMESTAMP_TZ])
def test_strict_decoder_propagates_original_error_through_native_worker(dtype):
    import asyncio
    from e6data_python_connector.async_work import reserve_work

    async def run():
        reservation=await reserve_work(deadline=asyncio.get_running_loop().time()+5)
        try:
            with pytest.raises(IndexError):
                await reservation.run(decoder.read_rows_from_chunk,['value'],corrupt_chunk(dtype),True)
        finally:
            reservation.release()
    asyncio.run(run())


def encode_chunk(chunk):
    transport=TMemoryBuffer()
    chunk.write(TBinaryProtocol(transport))
    return transport.getvalue()


@pytest.mark.parametrize('constant',[False,True])
@pytest.mark.parametrize('payload',[b'',b'\xff',b'not a decimal'])
def test_strict_decimal_rejects_invalid_nonnull_wire_payload(constant,payload):
    data=(wire.Data(numericDecimal128ConstantData=wire.NumericDecimal128ConstantData(payload,2)) if constant else
          wire.Data(decimal128Data=wire.Decimal128Data([payload],2)))
    vector=wire.Vector(1,wire.VectorType.DECIMAL128,[False],data,constant)
    encoded=encode_chunk(wire.Chunk(1,[vector]))
    expected=None if not constant and payload==b'' else Decimal(0)
    assert decoder.read_rows_from_chunk(['value'],encoded)==[[expected]]
    with pytest.raises(ValueError):
        decoder.read_rows_from_chunk(['value'],encoded,strict=True)


@pytest.mark.parametrize('constant',[False,True])
@pytest.mark.parametrize('payload',[b'123.45',(12345).to_bytes(16,'big',signed=True)])
def test_strict_decimal_preserves_valid_text_and_scaled_binary(constant,payload):
    data=(wire.Data(numericDecimal128ConstantData=wire.NumericDecimal128ConstantData(payload,2)) if constant else
          wire.Data(decimal128Data=wire.Decimal128Data([payload],2)))
    vector=wire.Vector(1,wire.VectorType.DECIMAL128,[False],data,constant)
    assert decoder.read_rows_from_chunk(['value'],encode_chunk(wire.Chunk(1,[vector])),strict=True)==[[Decimal('123.45')]]


def test_strict_null_column_and_null_constant_need_no_decimal_payload():
    null_vector=wire.Vector(3,wire.VectorType.NULL)
    null_decimal=wire.Vector(3,wire.VectorType.DECIMAL128,[True],None,True)
    for vector in [null_vector,null_decimal]:
        assert decoder.read_rows_from_chunk(['value'],encode_chunk(wire.Chunk(3,[vector])),strict=True)==[[None]]*3


@pytest.mark.parametrize('dtype',[999,wire.VectorType.TIMESTAMP,wire.VectorType.INT96])
def test_strict_unsupported_vector_type_is_not_fabricated_null(dtype):
    encoded=encode_chunk(wire.Chunk(1,[wire.Vector(1,dtype)]))
    assert decoder.read_rows_from_chunk(['value'],encoded)==[[None]]
    with pytest.raises(ValueError):
        decoder.read_rows_from_chunk(['value'],encoded,strict=True)


def test_strict_decimal_arithmetic_failure_cannot_use_alternate_decoder():
    import decimal
    with localcontext() as context:
        context.Emax=9
        context.traps[decimal.Overflow]=True
        raw=(42).to_bytes(16,'big',signed=True)
        with pytest.raises(decimal.Overflow):
            decoder._binary_to_decimal128(raw,scale=10,strict=True)


@pytest.mark.parametrize('chunk,columns',[
    (wire.Chunk(-1,[]),[]),
    (wire.Chunk(1,[wire.Vector(2,wire.VectorType.NULL)]),['value']),
    (wire.Chunk(1,[wire.Vector(1,wire.VectorType.NULL)]),[]),
    (wire.Chunk(1,[]),['value']),
    (wire.Chunk(None,[]),[]),
])
def test_strict_chunk_shape_cannot_silently_truncate_or_signal_eof(chunk,columns):
    with pytest.raises(ValueError):
        decoder.read_rows_from_chunk(columns,encode_chunk(chunk),strict=True)


def test_strict_nonnull_constant_decimal_rejects_absent_value():
    vector=wire.Vector(1,wire.VectorType.DECIMAL128,[False],
                       wire.Data(numericDecimal128ConstantData=wire.NumericDecimal128ConstantData(scale=2)),True)
    encoded=encode_chunk(wire.Chunk(1,[vector]))
    assert decoder.read_rows_from_chunk(['value'],encoded)==[[Decimal(0)]]
    with pytest.raises(ValueError):
        decoder.read_rows_from_chunk(['value'],encoded,strict=True)


def test_strict_serialized_empty_chunk_remains_eof_with_known_metadata():
    encoded=encode_chunk(wire.Chunk(0,[]))
    assert decoder.read_rows_from_chunk(['known-column'],encoded) is None
    assert decoder.read_rows_from_chunk(['known-column'],encoded,strict=True) is None


def decode_phase_payload(case):
    if case=='eof':
        return encode_chunk(wire.Chunk(0,[]))
    if case=='corrupt':
        return corrupt_chunk(wire.VectorType.LONG)
    vector=wire.Vector(1,wire.VectorType.STRING,[False],wire.Data(varcharData=wire.VarcharData(['Failed to parse.'])),False)
    return encode_chunk(wire.Chunk(1,[vector]))


@pytest.mark.parametrize('case',['eof','corrupt','valid'])
def test_sync_oauth_actual_decode_phase_preserves_handle_and_terminal_state(case):
    from e6data_python_connector import Connection
    from e6data_python_connector.exceptions import IncompleteResultError
    connection=Connection('localhost',1,access_token='local-nonusable-input',secure=True)
    cursor=connection.cursor()
    connection.close()
    cursor._query_id='unissued-local-query'
    cursor._engine_ip='unissued-local-planner'
    cursor._query_columns_description=['value']
    if case=='corrupt':
        with pytest.raises(IncompleteResultError) as caught:
            cursor._decode_batch_oauth(decode_phase_payload(case))
        assert isinstance(caught.value.__cause__,IndexError)
        assert caught.value.__cause__ is not caught.value
        assert caught.value.query_id==cursor.query_id
        with pytest.raises(IncompleteResultError) as again:
            cursor.fetchone()
        assert again.value is caught.value
    else:
        result=cursor._decode_batch_oauth(decode_phase_payload(case))
        assert result==(None if case=='eof' else [['Failed to parse.']])
        assert cursor._result_exhausted==(case=='eof')
        if case=='eof':
            assert cursor.fetch_batch() is None
            assert cursor.fetchone() is None
    assert cursor.query_id=='unissued-local-query'
    assert cursor._engine_ip=='unissued-local-planner'


@pytest.mark.parametrize('case',['eof','corrupt','valid'])
def test_async_actual_decode_phase_preserves_handle_and_terminal_state(case):
    import asyncio
    from e6data_python_connector.async_connection import AsyncConnection,QueryRoute
    from e6data_python_connector.async_cursor import AsyncCursor
    from e6data_python_connector.async_work import reserve_work
    from e6data_python_connector.exceptions import IncompleteResultError

    async def run():
        connection=await AsyncConnection('localhost',1,access_token='local-nonusable-input',secure=True,cleanup_timeout=.05).open()
        cursor=AsyncCursor(connection)
        route=QueryRoute(connection.target,'unissued-local-query','unissued-local-planner','blue')
        cursor._route=connection._register_route(route)
        cursor._state='ACTIVE'
        cursor._columns=['value']
        reservation=await reserve_work(deadline=connection._deadline())
        try:
            if case=='corrupt':
                with pytest.raises(IncompleteResultError) as caught:
                    await cursor._decode_batch(decode_phase_payload(case),reservation,cursor._revision)
                assert isinstance(caught.value.__cause__,IndexError)
                assert caught.value.__cause__ is not caught.value
                assert cursor._state=='RESULT_FAILED'
                await connection._channel.close()
                with pytest.raises(IncompleteResultError) as again:
                    await cursor.fetchone()
                assert again.value is caught.value
                assert caught.value.query_id==cursor.query_id
            else:
                result=await cursor._decode_batch(decode_phase_payload(case),reservation,cursor._revision)
                assert result==(None if case=='eof' else [['Failed to parse.']])
                assert cursor._state==('EXHAUSTED' if case=='eof' else 'ACTIVE')
                await connection._channel.close()
                if case=='eof':
                    assert await cursor.fetch_batch() is None
                    assert await cursor.fetchone() is None
            assert cursor.query_id=='unissued-local-query'
            assert connection._routes[cursor.query_id]==route
        finally:
            reservation.release()
            await connection._channel.close()
            await connection.close()
    asyncio.run(run())
