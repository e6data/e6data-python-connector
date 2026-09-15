"""Generated legacy Thrift compatibility using actual codecs, clients and processors.

No endpoint or service double is involved. Constructed wire records test the
installed generated protocol contracts, not real-server compatibility.
"""
import inspect

import pytest
from thrift.Thrift import TType, TMessageType, TApplicationException
from thrift.protocol import TBinaryProtocol, TCompactProtocol
from thrift.transport import TTransport, TSocket

from e6data_python_connector.server import QueryEngineService as service, ttypes
from test.unit.thrift_contract_helpers import (
    METHODS, PROTOCOLS, PLAIN_PROTOCOLS, STRUCTS, QUERY_ERROR, DENIED,
    declared_errors, success_result, serialize, read_struct, frame,
)


@pytest.mark.parametrize('value', STRUCTS, ids=lambda value: type(value).__name__)
@pytest.mark.parametrize('protocol', PROTOCOLS, ids=lambda protocol: protocol.__name__)
def test_generated_struct_roundtrip_preserves_values_and_boundary(value, protocol):
    encoded = serialize(value, protocol)
    transport = TTransport.TMemoryBuffer(encoded + b'trailing-boundary')
    restored = read_struct(type(value), protocol(transport))
    assert restored == value
    assert not (restored != value)
    assert restored != object()
    assert vars(restored) == vars(value)
    assert repr(restored).startswith(type(value).__name__ + '(')
    assert restored.validate() is None
    assert transport.read(17) == b'trailing-boundary'
    plain = (TCompactProtocol.TCompactProtocol if 'Compact' in protocol.__name__
             else TBinaryProtocol.TBinaryProtocol)
    assert encoded == serialize(value, plain)


@pytest.mark.parametrize('value', STRUCTS, ids=lambda value: type(value).__name__)
@pytest.mark.parametrize('protocol', PROTOCOLS, ids=lambda protocol: protocol.__name__)
def test_generated_optional_fields_absent_roundtrip(value, protocol):
    absent = type(value)()
    assert absent.validate() is None  # This IDL generated no required-field checks.
    restored = read_struct(type(value), protocol(TTransport.TMemoryBuffer(serialize(absent, protocol))))
    assert restored == absent
    assert all(field is None for field in vars(restored).values())
    assert restored != value


@pytest.mark.parametrize('value', STRUCTS, ids=lambda value: type(value).__name__)
@pytest.mark.parametrize('protocol', PLAIN_PROTOCOLS, ids=lambda protocol: protocol.__name__)
def test_unknown_nested_fields_and_wrong_known_types_are_skipped(value, protocol):
    transport = TTransport.TMemoryBuffer()
    writer = protocol(transport)
    writer.writeStructBegin(type(value).__name__)
    for spec in type(value).thrift_spec:
        if spec is not None:
            field_id, field_type, name = spec[:3]
            assert field_type != TType.I32
            writer.writeFieldBegin(name, TType.I32, field_id)
            writer.writeI32(-2147483648)
            writer.writeFieldEnd()
    writer.writeFieldBegin('future_nested_extension', TType.MAP, 127)
    writer.writeMapBegin(TType.STRING, TType.LIST, 1)
    writer.writeString('future')
    writer.writeListBegin(TType.I64, 2)
    writer.writeI64(2 ** 40)
    writer.writeI64(-(2 ** 40))
    writer.writeListEnd()
    writer.writeMapEnd()
    writer.writeFieldEnd()
    writer.writeFieldStop()
    writer.writeStructEnd()
    value.write(writer)
    reader = protocol(TTransport.TMemoryBuffer(transport.getvalue()))
    assert read_struct(type(value), reader) == type(value)()
    assert read_struct(type(value), reader) == value
    assert reader.trans.read(1) == b''


@pytest.mark.parametrize('error', [QUERY_ERROR, DENIED], ids=lambda value: type(value).__name__)
def test_declared_exceptions_are_immutable_hashable_and_keep_diagnostics(error):
    restored = read_struct(type(error), TBinaryProtocol.TBinaryProtocol(TTransport.TMemoryBuffer(
        serialize(error, TBinaryProtocol.TBinaryProtocol))))
    assert hash(restored) == hash(error)
    assert {error: 'diagnostic'}[restored] == 'diagnostic'
    assert error.reason in str(error)
    with pytest.raises(TypeError, match='immutable'):
        error.reason = 'changed'
    with pytest.raises(TypeError, match='immutable'):
        del error.reason


@pytest.mark.parametrize('method', METHODS)
@pytest.mark.parametrize('protocol', PLAIN_PROTOCOLS, ids=lambda protocol: protocol.__name__)
def test_client_full_call_encodes_arguments_and_decodes_success(method, protocol):
    arguments, expected = METHODS[method]
    outgoing = TTransport.TMemoryBuffer()
    incoming = TTransport.TMemoryBuffer(frame(method, success_result(method), protocol))
    client = service.Client(protocol(incoming), protocol(outgoing))
    assert list(inspect.signature(getattr(client, method)).parameters) == list(arguments)
    assert getattr(client, method)(**arguments) == expected
    reader = protocol(TTransport.TMemoryBuffer(outgoing.getvalue()))
    assert reader.readMessageBegin() == (method, TMessageType.CALL, 0)
    decoded = read_struct(getattr(service, method + '_args'), reader)
    assert vars(decoded) == arguments
    reader.readMessageEnd()
    assert reader.trans.read(1) == b''
    assert incoming.read(1) == b''


ERROR_CASES = [(method, name, error) for method in METHODS for name, error in declared_errors(method).items()]


@pytest.mark.parametrize('method,field,error', ERROR_CASES, ids=[m + '-' + f for m, f, _ in ERROR_CASES])
@pytest.mark.parametrize('protocol', PLAIN_PROTOCOLS, ids=lambda protocol: protocol.__name__)
def test_client_declared_error_is_raised_with_wire_fields(method, field, error, protocol):
    result = getattr(service, method + '_result')(**{field: error})
    transport = TTransport.TMemoryBuffer(frame(method, result, protocol))
    with pytest.raises(type(error)) as caught:
        getattr(service.Client(protocol(transport)), 'recv_' + method)()
    assert caught.value == error
    assert transport.read(1) == b''


@pytest.mark.parametrize('method', METHODS)
def test_client_application_errors_are_not_converted_to_declared_errors(method):
    error = TApplicationException(TApplicationException.INTERNAL_ERROR, 'wire application failure')
    incoming = TTransport.TMemoryBuffer(frame(method, error, TBinaryProtocol.TBinaryProtocol, TMessageType.EXCEPTION))
    with pytest.raises(TApplicationException) as caught:
        getattr(service.Client(TBinaryProtocol.TBinaryProtocol(incoming)), 'recv_' + method)()
    assert caught.value.type == TApplicationException.INTERNAL_ERROR
    assert caught.value.message == 'wire application failure'
    assert incoming.read(1) == b''


@pytest.mark.parametrize('method', [method for method, (_, success) in METHODS.items() if success is not None])
def test_client_nonvoid_empty_reply_reports_missing_result(method):
    incoming = TTransport.TMemoryBuffer(frame(method, getattr(service, method + '_result')(), TBinaryProtocol.TBinaryProtocol))
    with pytest.raises(TApplicationException) as caught:
        getattr(service.Client(TBinaryProtocol.TBinaryProtocol(incoming)), 'recv_' + method)()
    assert caught.value.type == TApplicationException.MISSING_RESULT
    assert method in caught.value.message


@pytest.mark.parametrize('method', METHODS)
@pytest.mark.parametrize('outcome', ['success', 'application', 'truncated'])
def test_generated_processor_and_client_compose_wire_contracts(method, outcome):
    protocol = TBinaryProtocol.TBinaryProtocol
    arguments, expected = METHODS[method]
    downstream_output = TTransport.TMemoryBuffer()
    if outcome == 'success':
        downstream_bytes = frame(method, success_result(method), protocol)
    elif outcome == 'application':
        downstream_bytes = frame(method, TApplicationException(TApplicationException.INTERNAL_ERROR, 'wire failure'),
                                 protocol, TMessageType.EXCEPTION)
    else:
        downstream_bytes = b''  # Real protocol EOF, handled as an internal processor error.
    downstream = service.Client(protocol(TTransport.TMemoryBuffer(downstream_bytes)), protocol(downstream_output))
    processor = service.Processor(downstream)
    events = []
    processor.on_message_begin(lambda name, kind, sequence: events.append((name, kind, sequence)))
    request = frame(method, getattr(service, method + '_args')(**arguments), protocol, TMessageType.CALL, 57)
    output = TTransport.TMemoryBuffer()
    assert processor.process(protocol(TTransport.TMemoryBuffer(request)), protocol(output)) is True
    assert events == [(method, TMessageType.CALL, 57)]
    forwarded = protocol(TTransport.TMemoryBuffer(downstream_output.getvalue()))
    assert forwarded.readMessageBegin() == (method, TMessageType.CALL, 0)
    assert vars(read_struct(getattr(service, method + '_args'), forwarded)) == arguments
    response = protocol(TTransport.TMemoryBuffer(output.getvalue()))
    assert response.readMessageBegin() == (method, TMessageType.REPLY if outcome == 'success' else TMessageType.EXCEPTION, 57)
    if outcome == 'success':
        assert read_struct(getattr(service, method + '_result'), response) == success_result(method)
    else:
        error = TApplicationException()
        error.read(response)
        assert error.type == TApplicationException.INTERNAL_ERROR
        assert error.message == ('wire failure' if outcome == 'application' else 'Internal error')
    response.readMessageEnd()
    assert response.trans.read(1) == b''


@pytest.mark.parametrize('method,field,error', ERROR_CASES, ids=[m + '-' + f for m, f, _ in ERROR_CASES])
def test_processor_preserves_declared_exception_type_and_reply_sequence(method, field, error):
    protocol = TBinaryProtocol.TBinaryProtocol
    result = getattr(service, method + '_result')(**{field: error})
    downstream = service.Client(protocol(TTransport.TMemoryBuffer(frame(method, result, protocol))),
                                protocol(TTransport.TMemoryBuffer()))
    processor = service.Processor(downstream)
    request = frame(method, getattr(service, method + '_args')(**METHODS[method][0]), protocol, TMessageType.CALL, 91)
    output = TTransport.TMemoryBuffer()
    processor.process(protocol(TTransport.TMemoryBuffer(request)), protocol(output))
    reader = protocol(TTransport.TMemoryBuffer(output.getvalue()))
    assert reader.readMessageBegin() == (method, TMessageType.REPLY, 91)
    assert read_struct(type(result), reader) == result


@pytest.mark.parametrize('method', METHODS)
def test_processor_does_not_turn_real_transport_failure_into_application_reply(method):
    protocol = TBinaryProtocol.TBinaryProtocol
    unopened = TSocket.TSocket('localhost', 1)  # Never opened: no network access.
    downstream = service.Client(protocol(TTransport.TMemoryBuffer()),
                                protocol(TTransport.TBufferedTransport(unopened)))
    output = TTransport.TMemoryBuffer()
    request = frame(method, getattr(service, method + '_args')(**METHODS[method][0]), protocol, TMessageType.CALL)
    with pytest.raises(TTransport.TTransportException):
        service.Processor(downstream).process(protocol(TTransport.TMemoryBuffer(request)), protocol(output))
    assert output.getvalue() == b''
    assert not unopened.isOpen()


def test_unknown_processor_method_preserves_sequence_and_consumes_request():
    protocol = TBinaryProtocol.TBinaryProtocol
    downstream = service.Client(protocol(TTransport.TMemoryBuffer()))
    request = frame('futureMethod', service.clear_args(sessionId='wire-session'), protocol, TMessageType.CALL, 19)
    incoming, output = TTransport.TMemoryBuffer(request), TTransport.TMemoryBuffer()
    assert service.Processor(downstream).process(protocol(incoming), protocol(output)) is None
    assert incoming.read(1) == b''
    reader = protocol(TTransport.TMemoryBuffer(output.getvalue()))
    assert reader.readMessageBegin() == ('futureMethod', TMessageType.EXCEPTION, 19)
    error = TApplicationException()
    error.read(reader)
    assert error.type == TApplicationException.UNKNOWN_METHOD
    assert 'futureMethod' in error.message
