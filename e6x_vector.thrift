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
    ARRAY
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
    15: TimeStampConstantData timeStampConstantData
    16: VarcharConstantData varcharConstantData
    17: TimeData timeData
    18: TimeStampData timeStampData
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

struct TemporalIntervalConstantData
{
    1: i8 data
}

struct TimeConstantData
{
    1: i64 data
}

struct TimeStampConstantData
{
    1: i64 data
}

struct VarcharConstantData
{
    1: string data
}

struct TimeData
{
    1: list<i64> data
}

struct TimeStampData
{
    1: list<i64> data
}

struct Chunk
{
    1: i32 size,
    2: list <Vector> vectors
}

struct ChunkWrapper
{
    1: binary chunk // thrift srialized Chunk
    2: i32 size
}