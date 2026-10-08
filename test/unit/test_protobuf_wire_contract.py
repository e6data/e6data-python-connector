"""Real protobuf runtimes and shipped gRPC base-servicer wire contracts.

The local server is the package's unmodified generated base servicer. It always
rejects unimplemented methods; it does not simulate query/cluster functionality.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys

import grpc
import grpc.experimental
from google.protobuf.message_factory import GetMessageClass
import pytest

from e6data_python_connector.cluster_server import cluster_pb2, cluster_pb2_grpc
from e6data_python_connector.server import e6x_engine_pb2, e6x_engine_pb2_grpc


def test_result_batch_v2_wire_contract():
    service = e6x_engine_pb2.DESCRIPTOR.services_by_name['QueryEngineService']
    assert 'getNextResultBatchV2' in service.methods_by_name
    method = service.methods_by_name['getNextResultBatchV2']
    assert method.input_type.full_name == e6x_engine_pb2.GetNextResultBatchRequest.DESCRIPTOR.full_name
    response = e6x_engine_pb2.GetNextResultBatchV2Response(
        resultBatches=[b'first', b'second'], sessionId='session',
        new_strategy='green', endOfStream=True,
    )
    restored = type(response).FromString(response.SerializeToString())
    assert list(restored.resultBatches) == [b'first', b'second']
    assert restored.endOfStream
    assert method.output_type.full_name == response.DESCRIPTOR.full_name
    assert {name: field.number for name, field in response.DESCRIPTOR.fields_by_name.items()} == {
        'resultBatches': 1, 'sessionId': 2, 'new_strategy': 3, 'endOfStream': 4,
    }
    assert response.HasField('new_strategy')
    assert not type(response)().HasField('new_strategy')
    assert e6x_engine_pb2.GetNextResultBatchResponse.DESCRIPTOR.fields_by_name['resultBatch'].number == 2


SERVICES = (
    (e6x_engine_pb2, e6x_engine_pb2_grpc, "QueryEngineService"),
    (cluster_pb2, cluster_pb2_grpc, "ClusterService"),
)
METHODS = [
    (module, generated, service, method)
    for module, generated, service in SERVICES
    for method in module.DESCRIPTOR.services_by_name[service].methods
]


@pytest.fixture(scope="module")
def generated_server():
    with ThreadPoolExecutor(max_workers=2) as executor:
        server = grpc.server(executor)
        for _, generated, service in SERVICES:
            getattr(generated, f"add_{service}Servicer_to_server")(
                getattr(generated, f"{service}Servicer")(), server
            )
        port = server.add_insecure_port("127.0.0.1:0")
        assert port > 0
        target = f"127.0.0.1:{port}"
        server.start()
        try:
            with grpc.insecure_channel(target) as channel:
                grpc.channel_ready_future(channel).result(timeout=5)
                yield target, channel
        finally:
            server.stop(0).wait(timeout=5)


@pytest.mark.parametrize("module,generated,service,method", METHODS,
                         ids=[f"{item[2]}.{item[3].name}" for item in METHODS])
@pytest.mark.parametrize("api", ["stub", "static"])
def test_each_shipped_rpc_preserves_unimplemented_status(generated_server, module, generated, service, method, api):
    target, channel = generated_server
    request = GetMessageClass(method.input_type)()
    with pytest.raises(grpc.RpcError) as error:
        if api == "stub":
            stub = getattr(generated, f"{service}Stub")(channel)
            getattr(stub, method.name)(request, timeout=2)
        else:
            getattr(getattr(generated, service), method.name)(request, target, insecure=True, timeout=2)
    assert error.value.code() is grpc.StatusCode.UNIMPLEMENTED
    assert error.value.details() == "Method not implemented!"


def test_python_and_native_protobuf_runtimes_have_identical_wire_contracts():
    probe = Path(__file__).with_name("protobuf_runtime_probe.py")
    results = {}
    for runtime in ("upb", "python"):
        env = dict(os.environ, PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=runtime)
        result = subprocess.run([sys.executable, str(probe)], env=env,
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        results[runtime] = json.loads(result.stdout)
        assert results[runtime]["runtime"] == runtime
        assert len(results[runtime]["wires"]) == 89
    assert results["python"]["wires"] == results["upb"]["wires"]
