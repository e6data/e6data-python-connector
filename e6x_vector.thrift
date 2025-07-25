namespace java io.e6x.query.engine.vectors

enum VectorType
{
    BINARY,
    BOOLEAN,
    DOUBLE,
    FLOAT,
    INT96,
    INTEGER,
    LONG,
    STRING,
    DATE,
    DATETIME,
    TIMESTAMP,
    STRUCT,
    MAP,
    ARRAY,
    NULL,
    TIMESTAMP_TZ,
    DECIMAL128
}

struct Vector
{
    1: i32 size,
    2: VectorType vectorType,
    3: list<bool> nullSet,
    4: Data data,
    5: bool isConstantVector,
    6: string zoneOffset,
    7: string format
}

union Data
{
    1: BoolData boolData
    2: Int32Data int32Data
    3: Int64Data int64Data
    4: DateData dateData
    5: Float32Data float32Data
    6: Float64Data float64Data
    7: VarcharData varcharData
    8: BoolConstantData boolConstantData
    9: DateConstantData dateConstantData
    10: NullConstantData nullConstantData
    11: NumericConstantData numericConstantData
    12: NumericDecimalConstantData numericDecimalConstantData
    13: TemporalIntervalConstantData temporalIntervalConstantData
    14: TimeConstantData timeConstantData
    15: VarcharConstantData varcharConstantData
    16: TimeData timeData
    17: Decimal128Data decimal128Data
    18: NumericDecimal128ConstantData numericDecimal128ConstantData
}

struct BoolData
{
    1: list<bool> data
}

struct Int32Data
{
    1: list<i32> data
}

struct Int64Data
{
    1: list<i64> data
}

struct DateData
{
    1: list<i64> data
}

struct Float32Data
{
    1: list<double> data
}

struct Float64Data
{
    1: list<double> data
}

// TODO: Is binary (or two longs and convert it to BigInt or BigDecimal in the JDBC end) the right representation for Decimal128?
struct Decimal128Data
{
    1: list<binary> data
}

struct VarcharData
{
    1: list<string> data
}

struct BoolConstantData
{
    1: bool data
}

struct DateConstantData
{
    1: i64 data
}

struct NullConstantData
{
    1: i8 data
}

struct NumericConstantData
{
    1: i64 data
}

struct NumericDecimalConstantData
{
    1: double data
}

struct NumericDecimal128ConstantData
{
    1: binary data
}

struct TemporalIntervalConstantData
{
    1: i8 data
}

struct TimeConstantData
{
    1: i64 data
    2: optional string zoneData
}

struct VarcharConstantData
{
    1: string data
}

struct TimeData
{
    1: list<i64> data
    2: optional list<string> zoneData
}

struct Chunk
{
    1: i32 size,
    2: list <Vector> vectors
}
