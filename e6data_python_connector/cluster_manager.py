import threading
import time
import e6data_python_connector.cluster_server.cluster_pb2 as cluster_pb2
import e6data_python_connector.cluster_server.cluster_pb2_grpc as cluster_pb2_grpc
import grpc
from grpc._channel import _InactiveRpcError
import multiprocessing
import logging

# Import strategy management functions
from e6data_python_connector.strategy import _get_active_strategy, _set_active_strategy, _set_pending_strategy, _get_grpc_header as _get_strategy_header

# Set up logging
_logger = logging.getLogger(__name__)


def _get_grpc_header(engine_ip=None, cluster=None, strategy=None):
    """
    Generate gRPC metadata headers for the request.

    This function creates a list of metadata headers to be used in gRPC requests.
    It includes optional headers for the engine IP, cluster UUID, and deployment strategy.

    Args:
        engine_ip (str, optional): The IP address of the engine. Defaults to None.
        cluster (str, optional): The UUID of the cluster. Defaults to None.
        strategy (str, optional): The deployment strategy (blue/green). Defaults to None.

    Returns:
        list: A list of tuples representing the gRPC metadata headers.
    """
    # Use the strategy module's implementation
    return _get_strategy_header(engine_ip=engine_ip, cluster=cluster, strategy=strategy)


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

    def __init__(self, host: str, port: int, user: str, password: str, secure_channel: bool = False, timeout=60 * 5, cluster_uuid=None, grpc_options=None):
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
                defaults to 5 minutes.
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
        self._grpc_options = grpc_options
        if grpc_options is None:
            self._grpc_options = dict()

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
                options=self._grpc_options,
                credentials=grpc.ssl_channel_credentials()
            )
        else:
            self._channel = grpc.insecure_channel(
                target='{}:{}'.format(self._host, self._port),
                options=self._grpc_options
            )
        return cluster_pb2_grpc.ClusterServiceStub(self._channel)

    def _try_cluster_request(self, request_type, payload=None):
        """
        Execute a cluster request with strategy fallback for 456 errors.
        
        For efficiency:
        - If we have an active strategy, use it first
        - Only try authentication sequence (blue -> green) if no active strategy
        - On 456 error, switch to alternative strategy and update active strategy
        
        Args:
            request_type: Type of request ('status' or 'resume')
            payload: Request payload (optional, will be created if not provided)
            
        Returns:
            The response from the successful request
        """
        current_strategy = _get_active_strategy()
        
        # Create payload if not provided
        if payload is None:
            if request_type == "status":
                payload = cluster_pb2.ClusterStatusRequest(
                    user=self._user,
                    password=self._password
                )
            elif request_type == "resume":
                payload = cluster_pb2.ResumeRequest(
                    user=self._user,
                    password=self._password
                )
        
        # If we have an active strategy, use it first
        if current_strategy is not None:
            try:
                _logger.info(f"ClusterManager: Trying {request_type} with established strategy: {current_strategy}")
                
                if request_type == "status":
                    response = self._get_connection.status(
                        payload,
                        metadata=_get_grpc_header(cluster=self.cluster_uuid, strategy=current_strategy)
                    )
                elif request_type == "resume":
                    response = self._get_connection.resume(
                        payload,
                        metadata=_get_grpc_header(cluster=self.cluster_uuid, strategy=current_strategy)
                    )
                else:
                    raise ValueError(f"Unknown request type: {request_type}")
                
                # Check for new strategy in response
                if hasattr(response, 'new_strategy') and response.new_strategy:
                    new_strategy = response.new_strategy.lower()
                    if new_strategy != current_strategy:
                        _logger.info(f"ClusterManager: Server indicated new strategy during {request_type}: {new_strategy}")
                        _set_pending_strategy(new_strategy)
                
                return response
                
            except _InactiveRpcError as e:
                if e.code() == grpc.StatusCode.UNKNOWN and 'status: 456' in e.details():
                    # 456 error - switch to alternative strategy
                    alternative_strategy = 'green' if current_strategy == 'blue' else 'blue'
                    _logger.info(f"ClusterManager: {request_type} failed with 456 error on {current_strategy}, switching to: {alternative_strategy}")
                    
                    try:
                        if request_type == "status":
                            response = self._get_connection.status(
                                payload,
                                metadata=_get_grpc_header(cluster=self.cluster_uuid, strategy=alternative_strategy)
                            )
                        elif request_type == "resume":
                            response = self._get_connection.resume(
                                payload,
                                metadata=_get_grpc_header(cluster=self.cluster_uuid, strategy=alternative_strategy)
                            )
                        
                        # Update active strategy since the alternative worked
                        _set_active_strategy(alternative_strategy)
                        _logger.info(f"ClusterManager: {request_type} succeeded with alternative strategy: {alternative_strategy}")
                        
                        # Check for new strategy in response
                        if hasattr(response, 'new_strategy') and response.new_strategy:
                            new_strategy = response.new_strategy.lower()
                            if new_strategy != alternative_strategy:
                                _logger.info(f"ClusterManager: Server indicated new strategy during {request_type}: {new_strategy}")
                                _set_pending_strategy(new_strategy)
                        
                        return response
                        
                    except _InactiveRpcError as e2:
                        _logger.error(f"ClusterManager: Both strategies failed for {request_type}. Original error: {e}, Alternative error: {e2}")
                        raise e  # Raise the original error
                else:
                    # Non-456 error - don't retry
                    _logger.error(f"ClusterManager: {request_type} failed with non-456 error: {e}")
                    raise e
        
        # No active strategy - start with authentication logic (blue first, then green)
        _logger.info(f"ClusterManager: No active strategy, starting authentication sequence for {request_type}")
        strategies_to_try = ['blue', 'green']
        
        for i, strategy in enumerate(strategies_to_try):
            try:
                _logger.info(f"ClusterManager: Trying {request_type} with strategy: {strategy}")
                
                if request_type == "status":
                    response = self._get_connection.status(
                        payload,
                        metadata=_get_grpc_header(cluster=self.cluster_uuid, strategy=strategy)
                    )
                elif request_type == "resume":
                    response = self._get_connection.resume(
                        payload,
                        metadata=_get_grpc_header(cluster=self.cluster_uuid, strategy=strategy)
                    )
                else:
                    raise ValueError(f"Unknown request type: {request_type}")
                
                # Set the working strategy as active
                _set_active_strategy(strategy)
                _logger.info(f"ClusterManager: {request_type} succeeded with strategy: {strategy}")
                
                # Check for new strategy in response
                if hasattr(response, 'new_strategy') and response.new_strategy:
                    new_strategy = response.new_strategy.lower()
                    if new_strategy != strategy:
                        _logger.info(f"ClusterManager: Server indicated new strategy during {request_type}: {new_strategy}")
                        _set_pending_strategy(new_strategy)
                
                return response
                
            except _InactiveRpcError as e:
                if e.code() == grpc.StatusCode.UNKNOWN and 'status: 456' in e.details():
                    # 456 error - try next strategy
                    if i < len(strategies_to_try) - 1:
                        _logger.info(f"ClusterManager: {request_type} failed with 456 error on {strategy}, trying next strategy: {strategies_to_try[i + 1]}")
                        continue
                    else:
                        _logger.error(f"ClusterManager: {request_type} failed with 456 error on all strategies")
                        raise e
                else:
                    # Non-456 error - don't retry
                    _logger.error(f"ClusterManager: {request_type} failed with non-456 error: {e}")
                    raise e
        
        # If we get here, all strategies failed
        _logger.error(f"ClusterManager: All strategies failed for {request_type}")
        raise e

    def _check_cluster_status(self):
        while True:
            try:
                # Use the unified strategy-aware request method
                response = self._try_cluster_request("status")
                yield response.status
            except _InactiveRpcError:
                yield None

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

            # Retrieve the current cluster status with strategy header
            try:
                current_status = self._try_cluster_request("status")
            except _InactiveRpcError:
                return False
            if current_status.status == 'suspended':
                # Send the resume request with strategy header
                try:
                    response = self._try_cluster_request("resume")
                except _InactiveRpcError:
                    return False
            elif current_status.status == 'active':
                return True
            elif current_status.status != 'resuming':
                """
                 If cluster cannot be resumed due to its current state, 
                 or already in a process of resuming, terminate the operation.
                 """
                return False

            for status in self._check_cluster_status():
                if status == 'active':
                    return True
                elif status == 'failed' or time.time() > self._timeout:
                    return False
                # Wait for 5 seconds before the next status check
                time.sleep(5)
            return False

    def suspend(self):
        """
        Suspends the cluster operations (not implemented).

        Placeholder method to be implemented for suspending a cluster,
        typically interacting with the remote cluster service API.
        """
        pass
