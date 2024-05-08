import logging
import struct
from datetime import datetime, timedelta

import pytz
from thrift.protocol import TBinaryProtocol
from thrift.transport import TTransport

from e6data_python_connector.e6x_vector.ttypes import Chunk, Vector, VectorType
from e6data_python_connector.constants import ZONE
from e6data_python_connector.date_time_utils import floor_div, floor_mod, timezone_from_offset

try:
    from thrift.protocol import fastbinary
except ImportError:
    raise Exception(
        """
        Failed to import fastbinary. 
        Did you install system dependencies?
        Please verify https://github.com/e6x-labs/e6data-python-connector#dependencies
        """
    )

_logger = logging.getLogger(__name__)


def get_null(vector: Vector, index: int):
    return vector.nullSet[0] if vector.isConstantVector else vector.nullSet[index]


class DataInputStream:
    def __init__(self, stream):
        self.stream = stream

    def read_boolean(self):
        return struct.unpack('?', self.stream.read(1))[0]

    def read_bytes(self, byte_array):
        for i in range(len(byte_array)):
            byte_array[i] = struct.unpack('B', self.stream.read(1))[0]
        return byte_array

    def read_int_96(self):
        return struct.unpack('B', self.stream.read(12))[0]

    def read_byte(self):
        return struct.unpack('b', self.stream.read(1))[0]

    def read_unsigned_byte(self):
        return struct.unpack('B', self.stream.read(1))[0]

    def read_char(self):
        return chr(struct.unpack('>H', self.stream.read(2))[0])

    def read_double(self):
        return struct.unpack('>d', self.stream.read(8))[0]

    def read_float(self):
        return struct.unpack('>f', self.stream.read(4))[0]

    def read_short(self):
        return struct.unpack('>h', self.stream.read(2))[0]

    def read_unsigned_short(self):
        return struct.unpack('>H', self.stream.read(2))[0]

    def read_long(self):
        return struct.unpack('>q', self.stream.read(8))[0]

    def read_utf(self):
        utf_length = struct.unpack('>H', self.stream.read(2))[0]
        return self.stream.read(utf_length)

    def read_int(self):
        return struct.unpack('>i', self.stream.read(4))[0]

    def read_unsigned_int(self):
        return struct.unpack('>I', self.stream.read(4))[0]


class FieldInfo:
    def __init__(self, name, field_type, date_format, zone):
        self.name = name
        self.field_type = field_type
        self.date_format = date_format
        self.zone = zone

    def get_zone(self):
        if self.field_type == 'DATE' or self.field_type == 'DATETIME':
            return self.zone
        return None

    def get_format(self):
        if self.field_type == 'DATE' or self.field_type == 'DATETIME':
            return self.date_format
        return None

    def get_field_type(self):
        return self.field_type

    def get_name(self):
        return self.name


def get_query_columns_info(buffer):
    result_meta_bytes = DataInputStream(buffer)
    rowcount = result_meta_bytes.read_long()
    field_count = result_meta_bytes.read_int()
    columns_description = list()

    for i in range(field_count):
        name = result_meta_bytes.read_utf().decode()
        field_type = result_meta_bytes.read_utf().decode()
        zone = result_meta_bytes.read_utf().decode()
        date_format = result_meta_bytes.read_utf().decode()
        field_info = FieldInfo(name, field_type, date_format, zone)
        columns_description.append(field_info)
    return rowcount, columns_description


def read_values_from_array(query_columns_description: list, dis: DataInputStream) -> list:
    value_array = list()
    for i in query_columns_description:
        dtype = i.get_field_type()
        isPresent = dis.read_byte()
        date_format = i.get_format()
        if isPresent == 0:
            value_array.append(None)
            continue
        try:
            if dtype == "LONG":
                value_array.append(dis.read_long())
            elif dtype == "DATE":
                epoch_seconds = floor_div(dis.read_long(), 1000_000)
                date = datetime.fromtimestamp(epoch_seconds, ZONE)
                value_array.append(date.strftime("%Y-%m-%d"))
            elif dtype == "DATETIME":
                epoch_micros = dis.read_long()
                epoch_seconds = floor_div(epoch_micros, 1000_000)
                micros_of_the_day = floor_mod(epoch_micros, 1000_000)
                date_time = datetime.fromtimestamp(epoch_seconds, ZONE)
                date_time = date_time + timedelta(microseconds=micros_of_the_day)
                value_array.append(date_time.strftime("%Y-%m-%d %H:%M:%S"))
            elif dtype == "STRING" or dtype == "ARRAY" or dtype == "MAP" or dtype == "STRUCT":
                value_array.append(dis.read_utf().decode())
            elif dtype == "INT":
                value_array.append(dis.read_int())
            elif dtype == "DOUBLE":
                value_array.append(dis.read_double())
            elif dtype == "BINARY":
                value_array.append(dis.read_utf())
            elif dtype == "FLOAT":
                value_array.append(dis.read_float())
            elif dtype == "CHAR":
                value_array.append(dis.read_char())
            elif dtype == "BOOLEAN":
                value_array.append(dis.read_boolean())
            elif dtype == "SHORT":
                value_array.append(dis.read_short())
            elif dtype == "BYTE":
                value_array.append(dis.read_byte())
            elif dtype == "INT96":
                julian_day = dis.read_int()
                time = dis.read_long()
                date_time = datetime.fromtimestamp((julian_day - 2440588) * 86400)
                date_time_with_nanos = date_time + timedelta(microseconds=(time / 1000))
                value_array.append(date_time_with_nanos)
            elif dtype == "INTEGER":
                value_array.append(dis.read_int())
        except Exception as e:
            _logger.error(e)
            value_array.append('Failed to parse.')

    return value_array


def read_rows_from_chunk(query_columns_description: list, buffer):
    # Create a transport and protocol instance for deserialization
    transport = TTransport.TMemoryBuffer(buffer)
    protocol = TBinaryProtocol.TBinaryProtocolAccelerated(transport)

    # Create an instance of the Thrift struct and read from the protocol
    chunk = Chunk()
    chunk.read(protocol)

    if chunk.size <= 0:
        return None

    rows = list()
    columns = list()

    for col, colName in enumerate(query_columns_description):
        columns.append(get_column_from_chunk(chunk.vectors[col]))

    for rowIndex in range(chunk.size):
        value = list()
        for colIndex, colName in enumerate(query_columns_description):
            value.append(columns[colIndex][rowIndex])
        rows.append(value)

    return rows



def get_column_from_chunk(vector: Vector) -> list:
    value_array = list()
    d_type = vector.vectorType
    zone = pytz.UTC
    try:
        if d_type == VectorType.LONG:
            for row in range(vector.size):
                if get_null(vector, row):
                    value_array.append(None)
                    continue
                value_array.append(vector.data.int64Data.data[
                                       row] if not vector.isConstantVector else vector.data.numericConstantData.data)
        elif d_type == VectorType.DATE:
            for row in range(vector.size):
                if get_null(vector, row):
                    value_array.append(None)
                    continue
                epoch_seconds = floor_div(vector.data.dateData.data[
                                              row] if not vector.isConstantVector else vector.data.dateConstantData.data,
                                          1000_000)
                date = datetime.fromtimestamp(epoch_seconds, zone)
                value_array.append(date.strftime("%Y-%m-%d"))
        elif d_type == VectorType.DATETIME:
            for row in range(vector.size):
                if get_null(vector, row):
                    value_array.append(None)
                    continue
                epoch_micros = vector.data.timeData.data[
                    row] if not vector.isConstantVector else vector.data.timeConstantData.data
                epoch_seconds = floor_div(epoch_micros, 1000_000)
                micros_of_the_day = floor_mod(epoch_micros, 1000_000)
                date_time = datetime.fromtimestamp(epoch_seconds, zone)
                date_time = date_time + timedelta(microseconds=micros_of_the_day)
                value_array.append(date_time.isoformat(timespec='milliseconds'))
        elif d_type == VectorType.STRING or d_type == VectorType.ARRAY or d_type == VectorType.MAP or d_type == VectorType.STRUCT:
            for row in range(vector.size):
                if get_null(vector, row):
                    value_array.append(None)
                    continue
                value_array.append(vector.data.varcharData.data[
                                       row] if not vector.isConstantVector else vector.data.varcharConstantData.data)
        elif d_type == VectorType.DOUBLE:
            for row in range(vector.size):
                if get_null(vector, row):
                    value_array.append(None)
                    continue
                value_array.append(vector.data.float64Data.data[
                                       row] if not vector.isConstantVector else vector.data.numericDecimalConstantData.data)
        elif d_type == VectorType.BINARY:
            for row in range(vector.size):
                if get_null(vector, row):
                    value_array.append(None)
                    continue
                value_array.append(vector.data.varcharData.data[
                                       row] if not vector.isConstantVector else vector.data.varcharConstantData.data)
        elif d_type == VectorType.FLOAT:
            for row in range(vector.size):
                if get_null(vector, row):
                    value_array.append(None)
                    continue
                value_array.append(vector.data.float32Data.data[
                                       row] if not vector.isConstantVector else vector.data.numericDecimalConstantData.data)
        elif d_type == VectorType.BOOLEAN:
            for row in range(vector.size):
                if get_null(vector, row):
                    value_array.append(None)
                    continue
                value_array.append(vector.data.boolData.data[
                                       row] if not vector.isConstantVector else vector.data.boolConstantData.data)
        elif d_type == VectorType.INTEGER:
            for row in range(vector.size):
                if get_null(vector, row):
                    value_array.append(None)
                    continue
                value_array.append(vector.data.int32Data.data[
                                       row] if not vector.isConstantVector else vector.data.numericConstantData.data)
        elif d_type == VectorType.NULL:
            for row in range(vector.size):
                value_array.append(None)
        elif d_type == VectorType.TIMESTAMP_TZ:
            for row in range(vector.size):
                if get_null(vector, row):
                    value_array.append(None)
                    continue
                epoch_micros = vector.data.timeData.data[
                    row] if not vector.isConstantVector else vector.data.timeConstantData.data
                if ((vector.isConstantVector and vector.data.timeConstantData.zoneData is not None) or
                        (not vector.isConstantVector and vector.data.timeData.zoneData is not None)):
                    zone_id = vector.data.timeData.zoneData[
                        row] if not vector.isConstantVector else vector.data.timeConstantData.zoneData
                    zone = timezone_from_offset(zone_id)
                epoch_seconds = floor_div(epoch_micros, 1000_000)
                micros_of_the_day = floor_mod(epoch_micros, 1000_000)
                date_time = datetime.fromtimestamp(epoch_seconds, zone)
                date_time = date_time + timedelta(microseconds=micros_of_the_day)
                value_array.append(date_time.isoformat(timespec='milliseconds'))
        else:
            value_array.append(None)
    except Exception as e:
        _logger.error(e)
        value_array.append('Failed to parse.')
    return value_array
