"""Exercise shipped protobuf messages in an isolated supported runtime.

These are data conformance checks, without service implementations or credentials.
The parent compares the native and Python runtimes' wire output for every message.
"""
import json

from google.protobuf.descriptor import FieldDescriptor as Field
from google.protobuf.internal import api_implementation
from google.protobuf.message import DecodeError
from google.protobuf.message_factory import GetMessageClass

from e6data_python_connector.cluster_server import cluster_pb2
from e6data_python_connector.server import e6x_engine_pb2


def scalar(field):
    if field.type == Field.TYPE_STRING:
        return "wire-value-\u03bb"
    if field.type == Field.TYPE_BYTES:
        return b"\x00\x01\xff"
    if field.type == Field.TYPE_BOOL:
        return True
    if field.type == Field.TYPE_ENUM:
        return field.enum_type.values[-1].number
    if field.type in (Field.TYPE_DOUBLE, Field.TYPE_FLOAT):
        return 1.25
    return 17


def populate(message):
    for field in message.DESCRIPTOR.fields:
        repeated = (field.is_repeated if hasattr(field, "is_repeated")
                    else field.label == Field.LABEL_REPEATED)
        if field.type == Field.TYPE_MESSAGE:
            value = getattr(message, field.name)
            if repeated and field.message_type.GetOptions().map_entry:
                key_field, value_field = field.message_type.fields
                key = scalar(key_field)
                if value_field.type == Field.TYPE_MESSAGE:
                    populate(value[key])
                else:
                    value[key] = scalar(value_field)
            else:
                populate(value.add() if repeated else value)
                if not repeated:
                    value.SetInParent()
        elif repeated:
            getattr(message, field.name).extend([scalar(field), scalar(field)])
        else:
            setattr(message, field.name, scalar(field))


def run():
    wires = {}
    for module in (cluster_pb2, e6x_engine_pb2):
        for name, descriptor in module.DESCRIPTOR.message_types_by_name.items():
            cls = GetMessageClass(descriptor)
            message = cls()
            populate(message)
            wire = message.SerializeToString(deterministic=True)
            restored = cls.FromString(wire)
            assert restored == message, name
            assert restored.ListFields() == message.ListFields(), name
            # Unknown proto3 fields survive an older client's parse/write cycle.
            unknown = b"\xc0\xa3\x09\x01"  # field 19000, varint value 1
            with_unknown = cls.FromString(wire + unknown)
            assert with_unknown.SerializeToString(deterministic=True) == wire + unknown, name
            with_unknown.DiscardUnknownFields()
            assert with_unknown == message, name
            try:
                cls.FromString(b"\x0a\x80")
            except DecodeError:
                pass
            else:
                raise AssertionError(f"{name} accepted a truncated field")
            wires[f"{module.__name__}.{name}"] = wire.hex()
    # Independent wire anchors pin field numbers, lengths and UTF-8 encoding.
    assert e6x_engine_pb2.AuthenticateRequest(user="a", password="b").SerializeToString() == b"\x0a\x01a\x12\x01b"
    assert cluster_pb2.ResumeRequest(user="a", password="b").SerializeToString() == b"\x0a\x01a\x12\x01b"
    assert cluster_pb2.ResumeResponse(status="ok").SerializeToString() == b"\x0a\x02ok"
    print(json.dumps({"runtime": api_implementation.Type(), "wires": wires}, sort_keys=True))


if __name__ == "__main__":
    run()
