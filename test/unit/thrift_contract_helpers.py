"""Actual Thrift protocol fixtures for generated wire-contract tests.

These are in-memory serialized messages, not RPC handlers or service doubles.
"""
from thrift.Thrift import TException, TMessageType
from thrift.protocol import TBinaryProtocol, TCompactProtocol
from thrift.transport import TTransport

from e6data_python_connector.server import QueryEngineService as service, ttypes

PROTOCOLS = [TBinaryProtocol.TBinaryProtocol, TBinaryProtocol.TBinaryProtocolAccelerated,
             TCompactProtocol.TCompactProtocol, TCompactProtocol.TCompactProtocolAccelerated]
PLAIN_PROTOCOLS = [TBinaryProtocol.TBinaryProtocol, TCompactProtocol.TCompactProtocol]

# Explicit public signatures and values independently pin field ordering, UTF-8,
# opaque binary data, false booleans, nested objects and 64-bit integer range.
SESSION = 'session-α'
QUERY = 'query-東京'
SCHEMA = 'schema-é'
CATALOG = 'catalog-雪'
SQL = "SELECT 'Ω'"
DENIED = ttypes.AccessDeniedException(reason='denied-权限')
QUERY_ERROR = ttypes.QueryProcessingException(reason='query-failed-é', queryId=QUERY)
FIELD = ttypes.TFieldInfo(fieldName='column-α', fieldType='varchar')
STATUS = ttypes.Status(status=False, rowCount=2 ** 40 + 17)
FAILED = ttypes.FailedSchemaElement(name='schema-é', type='catalog', reason='invalid-input')
CATALOG_RESULT = ttypes.AddCatalogsResponse(status='partial', failures=[FAILED])
BINARY = b'\x00\xff\x80thrift\x00'

METHODS = {
    'clear': ({'sessionId': SESSION, 'queryId': QUERY}, None),
    'cancelQuery': ({'sessionId': SESSION, 'queryId': QUERY}, None),
    'explain': ({'sessionId': SESSION, 'queryId': QUERY}, 'plan-α'),
    'dryRun': ({'sessionId': SESSION, 'sSchema': SCHEMA, 'sQueryString': SQL}, 'dry-α'),
    'dryRunV2': ({'sessionId': SESSION, 'catalogName': CATALOG, 'sSchema': SCHEMA, 'sQueryString': SQL}, 'dry-v2'),
    'explainAnalyze': ({'sessionId': SESSION, 'queryId': QUERY}, 'analysis-α'),
    'prepareStatement': ({'sessionId': SESSION, 'sSchemaName': SCHEMA, 'query': SQL}, QUERY),
    'prepareStatementV2': ({'sessionId': SESSION, 'catalogName': CATALOG, 'sSchemaName': SCHEMA, 'query': SQL}, QUERY),
    'executeStatement': ({'sessionId': SESSION, 'queryId': QUERY}, None),
    'getNextResultBatch': ({'sessionId': SESSION, 'queryId': QUERY}, BINARY),
    'getResultMetadata': ({'sessionId': SESSION, 'queryId': QUERY}, BINARY),
    'authenticate': ({'user': 'user-α', 'password': 'wire-test-input'}, SESSION),
    'getTables': ({'sessionId': SESSION, 'schema': SCHEMA}, ['table-α', 'table-雪']),
    'getTablesV2': ({'sessionId': SESSION, 'catalogName': CATALOG, 'schema': SCHEMA}, ['table-α', 'table-雪']),
    'getSchemaNames': ({'sessionId': SESSION}, [SCHEMA, 'other-schema']),
    'getSchemaNamesV2': ({'sessionId': SESSION, 'catalogName': CATALOG}, [SCHEMA, 'other-schema']),
    'getColumns': ({'sessionId': SESSION, 'schema': SCHEMA, 'table': 'table-雪'}, [FIELD]),
    'getColumnsV2': ({'sessionId': SESSION, 'catalogName': CATALOG, 'schema': SCHEMA, 'table': 'table-雪'}, [FIELD]),
    'updateUsers': ({'userInfo': BINARY}, None),
    'setProps': ({'sessionId': SESSION, 'propMap': '{"limit": 10}'}, None),
    'status': ({'sessionId': SESSION, 'queryId': QUERY}, STATUS),
    'addCatalogs': ({'sessionId': SESSION, 'jsonString': '{"catalog": "wire-test"}'}, None),
    'getAddCatalogsResponse': ({'sessionId': SESSION}, CATALOG_RESULT),
}


def declared_errors(method):
    if method == 'authenticate':
        return {'error': DENIED}
    if method == 'setProps':
        return {'error2': DENIED}
    return {'error1': QUERY_ERROR, 'error2': DENIED}


def success_result(method):
    success = METHODS[method][1]
    return getattr(service, method + '_result')(**({} if success is None else {'success': success}))


def struct_cases():
    values = [QUERY_ERROR, DENIED, FIELD,
              ttypes.UserAccessInfo(uuid='uuid-wire', userName='user-α', tokens=['opaque-one', 'opaque-雪']),
              STATUS, FAILED, CATALOG_RESULT]
    for method, (arguments, success) in METHODS.items():
        values.append(getattr(service, method + '_args')(**arguments))
        result_values = dict(declared_errors(method))
        if success is not None:
            result_values['success'] = success
        values.append(getattr(service, method + '_result')(**result_values))
    return values


STRUCTS = struct_cases()


def serialize(value, protocol):
    transport = TTransport.TMemoryBuffer()
    value.write(protocol(transport))
    return transport.getvalue()


def read_struct(cls, protocol):
    if issubclass(cls, TException):
        return cls.read(protocol)
    result = cls()
    result.read(protocol)
    return result


def frame(method, value, protocol, message_type=TMessageType.REPLY, sequence=0):
    transport = TTransport.TMemoryBuffer()
    writer = protocol(transport)
    writer.writeMessageBegin(method, message_type, sequence)
    value.write(writer)
    writer.writeMessageEnd()
    return transport.getvalue()
