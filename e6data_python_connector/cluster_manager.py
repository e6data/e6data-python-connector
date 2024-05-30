import threading
import time
import e6data_python_connector.cluster_server.cluster_pb2 as cluster_pb2
import e6data_python_connector.cluster_server.cluster_pb2_grpc as cluster_pb2_grpc
import grpc
from grpc._channel import _InactiveRpcError
import multiprocessing


class _StatusLock:
    _LOCK_TIMEOUT = 500

    def __init__(self):
        self._status_thread_lock = threading.Lock()
        self._status_multiprocessing_lock = multiprocessing.Semaphore()
        self._is_active = False

    @property
    def is_active(self) -> bool:
        return self._is_active

    def set_active(self):
        self._is_active = True

    def __enter__(self):
        self._status_thread_lock.acquire(timeout=self._LOCK_TIMEOUT)
        self._status_multiprocessing_lock.acquire(timeout=self._LOCK_TIMEOUT)
        print('Locked threads and processes.')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._status_thread_lock.release()
        self._status_multiprocessing_lock.release()
        print('Released threads and processes.')


status_lock = _StatusLock()


class ClusterManager:
    def __init__(self, host: str, port: int, user: str, password: str, secure_channel: bool = False, timeout=60 * 3):
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._timeout = time.time() + timeout
        self._secure_channel = secure_channel

    @property
    def _get_connection(self):
        if self._secure_channel:
            self._channel = grpc.secure_channel(
                target='{}:{}'.format(self._host, self._port),
                credentials=grpc.ssl_channel_credentials()
            )
        else:
            self._channel = grpc.insecure_channel(
                target='{}:{}'.format(self._host, self._port)
            )
        return cluster_pb2_grpc.ClusterServiceStub(self._channel)

    def resume(self) -> bool:
        """
        Return True if cluster came to active state else False.
        """
        with status_lock as lock:
            if lock.is_active:
                print('Cluster is already active')
                return True
            status_payload = cluster_pb2.ClusterStatusRequest(
                user=self._user,
                password=self._password
            )
            current_status = self._get_connection.status(status_payload)
            print('Current status', current_status)
            if current_status.status == 'suspended':
                payload = cluster_pb2.ResumeRequest(
                    user=self._user,
                    password=self._password
                )
                response = self._get_connection.resume(payload)
                print('resuming response', response.status)
            elif current_status.status == 'active':
                print('Cluster is already active.')
                return True
            elif current_status.status != 'resuming':
                """
                If cluster is in resuming state already, start watching for the status.
                Cluster is in different state, cannot resume.
                """
                print('Cluster is in different state, cannot resume.')
                return False
            while True:
                try:
                    status_payload = cluster_pb2.ClusterStatusRequest(
                        user=self._user,
                        password=self._password
                    )
                    response = self._get_connection.status(status_payload)
                    print(response)
                    if response.status == 'active':
                        lock.set_active()
                        print('Breaking because of status:', response.status)
                        return True
                    if response.status in ['suspended', 'failed']:
                        print('Breaking because of status:', response.status)
                        return False
                    if time.time() > self._timeout:
                        print('Breaking because of timeout')
                        return False
                except _InactiveRpcError as e:
                    print('On resume error', e)
                    print('Retrying')
                time.sleep(5)

    def suspend(self):
        pass
