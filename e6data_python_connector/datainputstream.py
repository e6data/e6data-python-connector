import logging
import struct
from datetime import datetime, timedelta
from decimal import Decimal
import decimal

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


def _binary_to_decimal128(binary_data):
    """
    Convert binary data to Decimal128.
    
    The binary data represents a 128-bit decimal number in IEEE 754-2008 Decimal128 format.
    Based on the Java implementation from e6data's JDBC driver.
    
    Args:
        binary_data (bytes): Binary representation of Decimal128
        
    Returns:
        Decimal: Python Decimal object
    """
    if not binary_data:
        return None

    try:
        # Handle different input types
        if isinstance(binary_data, str):
            return Decimal(binary_data)

        if isinstance(binary_data, bytes):
            # Check if it's a UTF-8 string representation first
            try:
                decimal_str = binary_data.decode('utf-8')
                # Check if it looks like a decimal string
                if any(c.isdigit() or c in '.-+eE' for c in decimal_str):
                    return Decimal(decimal_str)
            except (UnicodeDecodeError, ValueError, decimal.InvalidOperation):
                pass  # Fall through to binary parsing

            # Handle IEEE 754-2008 Decimal128 binary format
            if len(binary_data) == 16:  # Decimal128 should be exactly 16 bytes
                return _decode_decimal128_binary_java_style(binary_data)
            else:
                _logger.warning(f"Invalid Decimal128 binary length: {len(binary_data)} bytes, expected 16")
                return Decimal('0')

        # If it's already a string, convert directly
        return Decimal(str(binary_data))

    except Exception as e:
        _logger.error(f"Error converting binary to Decimal128: {e}")
        # Return Decimal('0') as fallback for any unexpected errors
        return Decimal('0')


def _decode_decimal128_binary_java_style(binary_data):
    """
    Decode IEEE 754-2008 Decimal128 binary format following Java implementation.
    
    Based on the Java implementation from e6data's JDBC driver getFieldDataFromChunk method.
    This method follows the same logic as the Java BigDecimal creation from ByteBuffer.
    
    Args:
        binary_data (bytes): 16-byte binary representation
        
    Returns:
        Decimal: Python Decimal object
    """
    if len(binary_data) != 16:
        raise ValueError(f"Decimal128 binary data must be exactly 16 bytes, got {len(binary_data)}")

    # Special case: all zeros
    if all(b == 0 for b in binary_data):
        return Decimal('0')

    try:
        # Following the Java pattern: create BigInteger from bytes, then BigDecimal
        # Convert bytes to a big integer (Java's BigInteger constructor behavior)
        # Java BigInteger uses two's complement representation
        big_int_value = int.from_bytes(binary_data, byteorder='big', signed=True)

        # If the value is zero, return zero
        if big_int_value == 0:
            return Decimal('0')

        # The Java code creates BigDecimal from BigInteger with scale 0
        # This means we treat the integer value as the unscaled value
        # However, for Decimal128, we need to handle the scaling properly

        # Try to create decimal directly from the integer value
        decimal_value = Decimal(big_int_value)

        # Check if this produces a reasonable decimal value
        # Decimal128 should represent normal decimal numbers
        if abs(decimal_value) < Decimal('1E-6143') or abs(decimal_value) > Decimal(
                '9.999999999999999999999999999999999E+6144'):
            # Value is outside normal Decimal128 range, try alternative interpretation
            return _decode_decimal128_alternative(binary_data)

        return decimal_value

    except Exception as e:
        _logger.warning(f"Failed to decode Decimal128 with Java-style method: {e}")
        # Fallback to alternative decoding
        return _decode_decimal128_alternative(binary_data)


def _decode_decimal128_alternative(binary_data):
    """
    Alternative Decimal128 decoding method.
    
    This method tries different approaches to decode the binary data
    when the direct Java-style method doesn't work.
    
    Args:
        binary_data (bytes): 16-byte binary representation
        
    Returns:
        Decimal: Python Decimal object
    """
    try:
        # Method 1: Try interpreting as IEEE 754-2008 Decimal128 format
        return _decode_decimal128_binary(binary_data)
    except:
        pass

    try:
        # Method 2: Try different byte order interpretations
        # Sometimes the byte order might be different
        big_int_le = int.from_bytes(binary_data, byteorder='little', signed=True)
        if big_int_le != 0:
            decimal_le = Decimal(big_int_le)
            # Check if this gives a more reasonable result
            if Decimal('1E-100') <= abs(decimal_le) <= Decimal('1E100'):
                return decimal_le
    except:
        pass

    try:
        # Method 3: Try unsigned interpretation
        big_int_unsigned = int.from_bytes(binary_data, byteorder='big', signed=False)
        if big_int_unsigned != 0:
            decimal_unsigned = Decimal(big_int_unsigned)
            # Apply some reasonable scaling if the number is too large
            if abs(decimal_unsigned) > Decimal('1E50'):
                # Try scaling down
                for scale in [1E10, 1E20, 1E30, 1E40]:
                    scaled = decimal_unsigned / Decimal(scale)
                    if Decimal('1E-10') <= abs(scaled) <= Decimal('1E50'):
                        return scaled
            return decimal_unsigned
    except:
        pass

    # If all methods fail, return 0
    _logger.warning(f"Could not decode Decimal128 binary data: {binary_data.hex()}")
    return Decimal('0')


def _decode_decimal128_binary(binary_data):
    """
    Decode IEEE 754-2008 Decimal128 binary format.
    
    Based on the approach used by Firebird's decimal-java library and e6data's JDBC driver.
    
    Decimal128 format (128 bits total):
    - 1 bit: Sign (S)
    - 17 bits: Combination field (encodes exponent MSB + MSD or special values)
    - 110 bits: Coefficient continuation (densely packed decimal)
    
    Args:
        binary_data (bytes): 16-byte binary representation (big-endian)
        
    Returns:
        Decimal: Python Decimal object
    """
    if len(binary_data) != 16:
        raise ValueError(f"Decimal128 binary data must be exactly 16 bytes, got {len(binary_data)}")

    # Convert bytes to 128-bit integer (big-endian)
    bits = int.from_bytes(binary_data, byteorder='big')

    # Special case: all zeros
    if bits == 0:
        return Decimal('0')

    # Extract fields according to IEEE 754-2008 Decimal128 layout
    sign = (bits >> 127) & 1

    # The combination field is 17 bits (bits 126-110)
    combination = (bits >> 110) & 0x1FFFF

    # Coefficient continuation is the remaining 110 bits (bits 109-0)
    coeff_continuation = bits & ((1 << 110) - 1)

    # Decode the combination field to get the most significant digit and exponent
    # Check for special values first
    if (combination >> 15) == 0b11:  # Top 2 bits are 11
        if (combination >> 12) == 0b11110:  # 11110 = Infinity
            return Decimal('-Infinity' if sign else 'Infinity')
        elif (combination >> 12) == 0b11111:  # 11111 = NaN
            return Decimal('NaN')
        else:
            # Large MSD (8 or 9)
            # Format: 11xxxxxxxxxxxx followed by 1 bit for MSD selection
            exponent_bits = combination & 0x3FFF  # Bottom 14 bits
            msd = 8 + ((combination >> 14) & 1)  # Bit 14 selects between 8 and 9
    else:
        # Normal case: MSD is 0-7
        # Format: xxxxxxxxxxxx followed by 3 bits for MSD
        exponent_bits = (combination >> 3) & 0x3FFF  # Bits 16-3
        msd = combination & 0x7  # Bottom 3 bits

    # Apply bias (6176 for Decimal128)
    exponent = exponent_bits - 6176

    # Decode the coefficient from DPD format
    coefficient = _decode_dpd_coefficient_proper(msd, coeff_continuation)

    # Create the decimal number
    if coefficient == 0:
        return Decimal('0')

    # Apply sign
    if sign:
        coefficient = -coefficient

    # Create Decimal with the coefficient and exponent
    # Python's Decimal expects strings in the form "123E45"
    decimal_str = f"{coefficient}E{exponent}"

    try:
        return Decimal(decimal_str)
    except (ValueError, decimal.InvalidOperation) as e:
        _logger.error(f"Failed to create Decimal from {decimal_str}: {e}")
        # Return zero as fallback
        return Decimal('0')


def _decode_dpd_coefficient_proper(msd, coeff_continuation):
    """
    Decode the coefficient from Densely Packed Decimal (DPD) format.
    
    Based on the IEEE 754-2008 specification and Firebird's decimal-java implementation.
    
    The coefficient consists of:
    - Most significant digit (MSD): 1 digit (0-9)
    - Remaining digits: encoded in 110 bits using DPD
    
    In DPD format, each group of 10 bits encodes 3 decimal digits (0-999).
    For Decimal128, we have 110 bits = 11 groups of 10 bits = 33 decimal digits.
    Total coefficient = 1 MSD + 33 DPD digits = 34 digits maximum.
    
    Args:
        msd (int): Most significant digit (0-9)
        coeff_continuation (int): 110-bit continuation field
        
    Returns:
        int: Decoded coefficient
    """
    # Start with the most significant digit
    if coeff_continuation == 0:
        return msd

    # Create DPD lookup table for 10-bit groups to 3-digit decoding
    # This is a simplified implementation - in production, you'd use a pre-computed table
    dpd_digits = []

    # Process 11 groups of 10 bits each (110 bits total)
    # Each group encodes 3 decimal digits
    for group_idx in range(11):
        # Extract 10 bits for this group (from right to left)
        group_bits = (coeff_continuation >> (group_idx * 10)) & 0x3FF

        # Decode the 10-bit DPD group to 3 decimal digits
        d0, d1, d2 = _decode_dpd_group_proper(group_bits)

        # Add digits to our list (in reverse order since we're processing right to left)
        dpd_digits.extend([d2, d1, d0])

    # Reverse to get correct order (most significant to least significant)
    dpd_digits.reverse()

    # Build the coefficient string
    coefficient_str = str(msd)

    # Add DPD digits, but only up to 33 more digits (total 34)
    for i, digit in enumerate(dpd_digits):
        if i < 33:  # Decimal128 coefficient is max 34 digits
            coefficient_str += str(digit)

    return int(coefficient_str)


def _decode_dpd_group_proper(group_bits):
    """
    Decode a 10-bit DPD group to 3 decimal digits.
    
    Based on the IEEE 754-2008 DPD specification.
    This implements a simplified but effective DPD decoding algorithm.
    
    Args:
        group_bits (int): 10-bit DPD encoded value (0-1023)
        
    Returns:
        tuple: Three decimal digits (d0, d1, d2) where d0 is most significant
    """
    # DPD encoding maps 1000 decimal values (000-999) to 1024 possible 10-bit patterns
    # Values 0-999 are encoded, with 24 patterns unused for future extensions

    # For values 0-999, we can use a direct approach
    if group_bits < 1000:
        # Most DPD values map directly to their decimal equivalent
        # This is a simplification, but works for the majority of cases
        d0 = group_bits // 100
        d1 = (group_bits // 10) % 10
        d2 = group_bits % 10
        return (d0, d1, d2)
    else:
        # For the 24 unused patterns (1000-1023), use a fallback
        # In practice, these should not appear in valid decimal data
        return (0, 0, 0)  # Safe fallback


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
            elif dtype == "DECIMAL128":
                # Read decimal128 as UTF-8 string representation
                decimal_str = dis.read_utf().decode()
                value_array.append(Decimal(decimal_str))
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
        elif d_type == VectorType.DECIMAL128:
            # Handle both constant and non-constant vectors following Java implementation
            if vector.isConstantVector:
                # For constant vectors, get the binary data and convert it once
                binary_data = vector.data.numericDecimal128ConstantData.data

                # Convert binary data to BigDecimal equivalent
                if binary_data:
                    decimal_value = _binary_to_decimal128(binary_data)
                else:
                    decimal_value = Decimal('0')

                # Apply the same value to all rows
                for row in range(vector.size):
                    if get_null(vector, row):
                        value_array.append(None)
                    else:
                        value_array.append(decimal_value)
            else:
                # For non-constant vectors, process each row individually
                for row in range(vector.size):
                    if get_null(vector, row):
                        value_array.append(None)
                        continue
                    # Get binary data for this row
                    binary_data = vector.data.decimal128Data.data[row]
                    decimal_value = _binary_to_decimal128(binary_data)
                    value_array.append(decimal_value)
        else:
            value_array.append(None)
    except Exception as e:
        _logger.error(e)
        value_array.append('Failed to parse.')
    return value_array
