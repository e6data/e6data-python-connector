class TypeId(object):
    BOOLEAN_TYPE = 0
    TINYINT_TYPE = 1
    SMALLINT_TYPE = 2
    INT_TYPE = 3
    BIGINT_TYPE = 4
    FLOAT_TYPE = 5
    DOUBLE_TYPE = 6
    STRING_TYPE = 7
    TIMESTAMP_TYPE = 8
    BINARY_TYPE = 9
    ARRAY_TYPE = 10
    MAP_TYPE = 11
    STRUCT_TYPE = 12
    UNION_TYPE = 13
    USER_DEFINED_TYPE = 14
    DECIMAL_TYPE = 15
    NULL_TYPE = 16
    DATE_TYPE = 17
    VARCHAR_TYPE = 18
    CHAR_TYPE = 19
    INTERVAL_YEAR_MONTH_TYPE = 20
    INTERVAL_DAY_TIME_TYPE = 21

    _VALUES_TO_NAMES = {
        0: "BOOLEAN_TYPE",
        1: "TINYINT_TYPE",
        2: "SMALLINT_TYPE",
        3: "INT_TYPE",
        4: "BIGINT_TYPE",
        5: "FLOAT_TYPE",
        6: "DOUBLE_TYPE",
        7: "STRING_TYPE",
        8: "TIMESTAMP_TYPE",
        9: "BINARY_TYPE",
        10: "ARRAY_TYPE",
        11: "MAP_TYPE",
        12: "STRUCT_TYPE",
        13: "UNION_TYPE",
        14: "USER_DEFINED_TYPE",
        15: "DECIMAL_TYPE",
        16: "NULL_TYPE",
        17: "DATE_TYPE",
        18: "VARCHAR_TYPE",
        19: "CHAR_TYPE",
        20: "INTERVAL_YEAR_MONTH_TYPE",
        21: "INTERVAL_DAY_TIME_TYPE",
    }

    _NAMES_TO_VALUES = {
        "BOOLEAN_TYPE": 0,
        "TINYINT_TYPE": 1,
        "SMALLINT_TYPE": 2,
        "INT_TYPE": 3,
        "BIGINT_TYPE": 4,
        "FLOAT_TYPE": 5,
        "DOUBLE_TYPE": 6,
        "STRING_TYPE": 7,
        "TIMESTAMP_TYPE": 8,
        "BINARY_TYPE": 9,
        "ARRAY_TYPE": 10,
        "MAP_TYPE": 11,
        "STRUCT_TYPE": 12,
        "UNION_TYPE": 13,
        "USER_DEFINED_TYPE": 14,
        "DECIMAL_TYPE": 15,
        "NULL_TYPE": 16,
        "DATE_TYPE": 17,
        "VARCHAR_TYPE": 18,
        "CHAR_TYPE": 19,
        "INTERVAL_YEAR_MONTH_TYPE": 20,
        "INTERVAL_DAY_TIME_TYPE": 21,
    }