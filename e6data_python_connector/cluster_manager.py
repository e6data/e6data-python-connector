import threading
import time
import e6data_python_connector.cluster_server.cluster_pb2 as cluster_pb2
import e6data_python_connector.cluster_server.cluster_pb2_grpc as cluster_pb2_grpc
import grpc
from grpc._channel import _InactiveRpcError
import multiprocessing


def _get_grpc_header(engine_ip=None, cluster=None):
    metadata = []
    if engine_ip:
        metadata.append(('plannerip', engine_ip))
    if cluster:
        metadata.append(('cluster-uuid', cluster))
    return metadata


class _StatusLock:
    """
    A thread-safe and process-safe lock manager designed for managing
    concurrent access protection in multithreaded and multiprocessing environments.

    This class encapsulates locking mechanisms using threading and multiprocessing
    modules to ensure an operation's atomicity and handle shared resources safely.

    Attributes:
       _LOCK_TIMEOUT (int): The maximum timeout (in milliseconds) to try
           acquiring a lock before raising an error.
       _status_thread_lock (threading.Lock): A thread-level lock to synchronize
           access among threads in the same process.
       _status_multiprocessing_lock (multiprocessing.Semaphore): A
           process-level lock to synchronize access across different processes.
       _is_active (bool): A boolean flag indicating whether the lock
           is currently active (True) or not (False).
    """

    _LOCK_TIMEOUT = 500

    def __init__(self):
        """
        Initializes the _StatusLock instance with its respective
        thread and multiprocessing locks and sets the active flag to False.
        """
        self._status_thread_lock = threading.Lock()
        self._status_multiprocessing_lock = multiprocessing.Semaphore()
        self._is_active = False

    @property
    def is_active(self) -> bool:
        """
        Checks if the lock is currently active.

        Returns:
            bool: True if the lock is active, False otherwise.
        """

        return self._is_active

    def set_active(self):
        """
        Activates the lock by setting the `_is_active` flag to True.
        This can be used for manually marking the state of the lock
        as active during synchronization operations.
        """

        self._is_active = True

    def __enter__(self):
        """
        Enters a context-managed locking block.

        Acquires both the thread-level lock and process-level semaphore
        to ensure the current operation can safely access shared resources.

        Raises:
           TimeoutError: If the lock cannot be acquired within the timeout period.

        Returns:
           _StatusLock: The current instance of the lock, used for context management.
        """

        self._status_thread_lock.acquire(timeout=self._LOCK_TIMEOUT)
        self._status_multiprocessing_lock.acquire(timeout=self._LOCK_TIMEOUT)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exits a context-managed locking block.

        Releases both the thread-level lock and process-level semaphore
        to allow other operations to acquire the lock. Handles cleanup
        regardless of whether an exception occurred.

        Args:
            exc_type (Type[BaseException]): The type of exception raised (if any).
            exc_val (BaseException): The exception instance raised (if any).
            exc_tb (Traceback): The traceback object of the exception (if any).
        """

        self._status_thread_lock.release()
        self._status_multiprocessing_lock.release()


status_lock = _StatusLock()


class ClusterManager:
    """
    A manager for handling operations and connections with a remote cluster infrastructure.
    Provides methods to manage cluster states, such as resuming or suspending its activity,
    by interacting with a gRPC-based remote service.

    Attributes:
        _host (str): The hostname or IP address of the cluster service.
        _port (int): The port number used to connect to the cluster service.
        _user (str): The username for authentication with the cluster service.
        _password (str): The password for authentication with the cluster service.
        _timeout (float): The timeout threshold (as an epoch timestamp) for operations,
            defaulting to 3 minutes from initialization.
        _secure_channel (bool): Indicates whether a secure gRPC channel
            (SSL/TLS) should be used for communication; defaults to False.
        cluster_uuid (str): The unique identifier for the target cluster.
    """

    def __init__(self, host: str, port: int, user: str, password: str, secure_channel: bool = False, timeout=60 * 3, cluster_uuid=None):
        """
        Initializes a new instance of the ClusterManager class.

        Args:
            host (str): The hostname or IP address of the cluster service.
            port (int): The port number for accessing the cluster service.
            user (str): The username used for connecting to the cluster service.
            password (str): The password used for connecting to the cluster service.
            secure_channel (bool, optional): Whether to use a secure
                gRPC channel for communication; defaults to False.
            timeout (int, optional): The timeout duration (in seconds) for operations;
                defaults to 3 minutes.
            cluster_uuid (str, optional): The unique identifier for the target cluster;
                defaults to None.
        """

        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._timeout = time.time() + timeout
        self._secure_channel = secure_channel
        self.cluster_uuid = cluster_uuid

    @property
    def _get_connection(self):
        """
        Dynamically establishes a gRPC connection to the cluster service.

        Returns:
            cluster_pb2_grpc.ClusterServiceStub: A gRPC client stub
                for interacting with the cluster service methods.
        """

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
        Resumes the cluster if it is currently suspended or not in the 'active' state.

        This method interacts with the remote cluster service to verify its current
        status. If suspended, it sends a resume request and monitors
        the cluster's state until it becomes active or fails.

        The operation uses a locking mechanism (`status_lock`) to ensure thread-safe
        and process-safe state transitions.

        Returns:
            bool: True if the cluster resumes successfully and becomes active;
                  False if the cluster cannot be resumed, remains suspended, or fails.

        Raises:
            _InactiveRpcError: An exception raised if there is a communication error
                while interacting with the remote cluster service.

        Notes:
            - If the cluster is already active, this method completes successfully
              without further actions.
            - If the cluster is in a 'resuming' state, this method waits for the
              cluster to transition to 'active' or any terminal state (e.g., 'failed').
            - The operation is subject to the `_timeout` threshold;
              if the timeout expires, the method returns False.
        """

        with status_lock as lock:
            if lock.is_active:
                return True

            # Retrieve the current cluster status
            status_payload = cluster_pb2.ClusterStatusRequest(
                user=self._user,
                password=self._password
            )
            current_status = self._get_connection.status(
                status_payload,
                metadata=_get_grpc_header(cluster=self.cluster_uuid)
            )
            if current_status.status == 'suspended':
                # Send the resume request
                payload = cluster_pb2.ResumeRequest(
                    user=self._user,
                    password=self._password
                )
                response = self._get_connection.resume(
                    payload,
                    metadata=_get_grpc_header(cluster=self.cluster_uuid)
                )
            elif current_status.status == 'active':
                return True
            elif current_status.status != 'resuming':
                """
                 If cluster cannot be resumed due to its current state, 
                 or already in a process of resuming, terminate the operation.
                 """
                return False

            # Wait for the cluster to become active
            while True:
                try:
                    status_payload = cluster_pb2.ClusterStatusRequest(
                        user=self._user,
                        password=self._password
                    )
                    response = self._get_connection.status(
                        status_payload,
                        metadata=_get_grpc_header(cluster=self.cluster_uuid)
                    )
                    if response.status == 'active':
                        lock.set_active()
                        return True
                    if response.status in ['failed']:
                        return False
                    if time.time() > self._timeout:
                        return False
                except _InactiveRpcError as e:
                    pass
                time.sleep(5)

    def suspend(self):
        """
        Suspends the cluster operations (not implemented).

        Placeholder method to be implemented for suspending a cluster,
        typically interacting with the remote cluster service API.
        """
        pass
