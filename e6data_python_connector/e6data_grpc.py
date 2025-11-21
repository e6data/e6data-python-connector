"""DB-API implementation backed by HiveServer2 (Thrift API)
See http://www.python.org/dev/peps/pep-0249/
Many docstrings in this file are based on the PEP, which is in the public domain.
"""

from __future__ import absolute_import
from __future__ import unicode_literals

import datetime
import logging
import os

import re
import sys
import time
from decimal import Decimal
from io import BytesIO
from ssl import CERT_NONE, CERT_OPTIONAL, CERT_REQUIRED
import threading
import multiprocessing

import grpc
from grpc._channel import _InactiveRpcError

from e6data_python_connector.cluster_manager import ClusterManager
from e6data_python_connector.strategy import _get_grpc_header as _get_strategy_header
from e6data_python_connector.common import DBAPITypeObject, ParamEscaper, DBAPICursor
from e6data_python_connector.constants import *
from e6data_python_connector.datainputstream import get_query_columns_info, read_rows_from_chunk, is_fastbinary_available
from e6data_python_connector.server import e6x_engine_pb2_grpc, e6x_engine_pb2
from e6data_python_connector.typeId import *

apilevel = '2.0'
threadsafety = 2  # Threads may share the e6xdb and connections.
paramstyle = 'pyformat'  # Python extended format codes, e.g. ...WHERE name=%(name)s

_TIMESTAMP_PATTERN = re.compile(r'(\d+-\d+-\d+ \d+:\d+:\d+(\.\d{,6})?)')

ssl_cert_parameter_map = {
    "none": CERT_NONE,
    "optional": CERT_OPTIONAL,
    "required": CERT_REQUIRED,
}


def _parse_timestamp(value):
    if value:
        match = _TIMESTAMP_PATTERN.match(value)
        if match:
            if match.group(2):
                format = '%Y-%m-%d %H:%M:%S.%f'
                # use the pattern to truncate the value
                value = match.group()
            else:
                format = '%Y-%m-%d %H:%M:%S'
            value = datetime.datetime.strptime(value, format)
        else:
            raise Exception(
                'Cannot convert "{}" into a datetime'.format(value)
            )
    else:
        value = None
    return value


TYPES_CONVERTER = {
    "DECIMAL_TYPE": Decimal,
    "TIMESTAMP_TYPE": _parse_timestamp
}


def re_auth(func):
    def wrapper(self, *args, **kwargs):
        max_retry = 5
        current_retry = 0
        while current_retry < max_retry:
            try:
                return func(self, *args, **kwargs)
            except _InactiveRpcError as e:
                current_retry += 1
                if current_retry == max_retry:
                    raise e
                if e.code() == grpc.StatusCode.INTERNAL and 'Access denied' in e.details():
                    time.sleep(0.2)
                    self.connection.get_re_authenticate_session_id()
                elif 'status: 456' in e.details():
                    # Strategy changed, clear cache and retry
                    _clear_strategy_cache()
                    # Force re-authentication which will detect new strategy
                    self.connection.get_re_authenticate_session_id()
                else:
                    raise e

    return wrapper


class HiveParamEscaper(ParamEscaper):
    def escape_string(self, item):
        # backslashes and single quotes need to be escaped
        # Need to decode UTF-8 because of old sqlalchemy.
        # Newer SQLAlchemy checks dialect.supports_unicode_binds before encoding Unicode strings
        # as byte strings. The old version always encodes Unicode as byte strings, which breaks
        # string formatting here.
        if isinstance(item, bytes):
            item = item.decode('utf-8')
        return "'{}'".format(
            item
            .replace('\\', '\\\\')
            .replace("'", "\\'")
            .replace('\r', '\\r')
            .replace('\n', '\\n')
            .replace('\t', '\\t')
        )


_escaper = HiveParamEscaper()

# Logger for the module
logger = logging.getLogger(__name__)

# Thread-safe and process-safe storage for active deployment strategy
_strategy_lock = threading.Lock()
_strategy_manager = None
_shared_strategy = None
_local_strategy_cache = {
    'active_strategy': None,
    'last_check_time': 0,
    'pending_strategy': None,  # Strategy to use for next query
    'query_strategy_map': {},  # Map of query_id to strategy used
    'last_transition_time': 0,  # Timestamp of last strategy transition
    'session_invalidated': False  # Flag to invalidate all sessions
}

# Strategy cache timeout in seconds (5 minutes)
STRATEGY_CACHE_TIMEOUT = 300

# Global set to track debug-enabled connections
_debug_connections = set()

def _strategy_debug_log(message):
    """Log strategy debug messages if any connection has debug enabled."""
    if _debug_connections:
        logger.info(f"[E6DATA_STRATEGY_DEBUG] {time.strftime('%Y-%m-%d %H:%M:%S')} - {message}")


def _get_shared_strategy():
    """Get or create the shared strategy storage."""
    return _local_strategy_cache


def _get_active_strategy():
    """Get the active deployment strategy (blue or green) from shared memory."""
    with _strategy_lock:
        shared_strategy = _get_shared_strategy()
        # current_time = time.time()
        # Check if strategy is cached and not expired
        # if (shared_strategy['active_strategy'] is not None and
        #     current_time - shared_strategy['last_check_time'] < STRATEGY_CACHE_TIMEOUT):
        if shared_strategy['active_strategy'] is not None:
            return shared_strategy['active_strategy']
        return None


def _set_active_strategy(strategy):
    """Set the active deployment strategy in shared memory."""
    if not strategy:
        return
    # Normalize strategy to lowercase and validate
    normalized_strategy = strategy.lower()
    if normalized_strategy not in ['blue', 'green']:
        return

    with _strategy_lock:
        shared_strategy = _get_shared_strategy()
        current_time = time.time()
        old_strategy = shared_strategy.get('active_strategy')

        # Only update transition time if strategy actually changed
        if old_strategy != normalized_strategy:
            shared_strategy['last_transition_time'] = current_time
            _strategy_debug_log(f"Setting active strategy: {old_strategy} -> {normalized_strategy}")
        else:
            _strategy_debug_log(f"Active strategy unchanged: {normalized_strategy}")

        shared_strategy['active_strategy'] = normalized_strategy
        shared_strategy['last_check_time'] = current_time


def _clear_strategy_cache():
    """Clear the cached strategy to force re-detection."""
    with _strategy_lock:
        shared_strategy = _get_shared_strategy()
        old_strategy = shared_strategy.get('active_strategy')
        if old_strategy:
            _strategy_debug_log(f"Clearing strategy cache (was: {old_strategy})")
        shared_strategy['active_strategy'] = None
        shared_strategy['last_check_time'] = 0
        shared_strategy['pending_strategy'] = None


def _set_pending_strategy(strategy):
    """Set the pending strategy to be used for the next query."""
    if not strategy:
        return
    # Normalize strategy to lowercase and validate
    normalized_strategy = strategy.lower()
    if normalized_strategy not in ['blue', 'green']:
        return

    with _strategy_lock:
        shared_strategy = _get_shared_strategy()
        current_active = shared_strategy['active_strategy']

        if normalized_strategy != current_active:
            shared_strategy['pending_strategy'] = normalized_strategy
            query_count = len(shared_strategy.get('query_strategy_map', {}))
            _strategy_debug_log(f"Setting pending strategy: {normalized_strategy} (current: {current_active}, active queries: {query_count})")


def _apply_pending_strategy():
    """Apply the pending strategy as the active strategy."""
    with _strategy_lock:
        shared_strategy = _get_shared_strategy()
        if shared_strategy['pending_strategy']:
            old_strategy = shared_strategy['active_strategy']
            new_strategy = shared_strategy['pending_strategy']
            current_time = time.time()

            _strategy_debug_log(f"Applying pending strategy: {old_strategy} -> {new_strategy}")
            
            shared_strategy['active_strategy'] = new_strategy
            shared_strategy['pending_strategy'] = None
            shared_strategy['last_check_time'] = current_time
            shared_strategy['last_transition_time'] = current_time
            shared_strategy['session_invalidated'] = True  # Invalidate all sessions
            
            _strategy_debug_log(f"Strategy transition complete. All sessions invalidated.")

            return new_strategy
        return None


def _invalidate_all_sessions():
    """Invalidate all existing sessions to force fresh connections with new strategy."""
    # This is a global flag that all connections will check
    shared_strategy = _get_shared_strategy()
    shared_strategy['session_invalidated'] = True


def _register_query_strategy(query_id, strategy):
    """Register the strategy used for a specific query."""
    if not query_id or not strategy:
        return
    # Normalize strategy to lowercase and validate
    normalized_strategy = strategy.lower()
    if normalized_strategy not in ['blue', 'green']:
        return

    with _strategy_lock:
        shared_strategy = _get_shared_strategy()
        query_map = shared_strategy.get('query_strategy_map', {})
        query_map[query_id] = normalized_strategy
        shared_strategy['query_strategy_map'] = query_map
        _strategy_debug_log(f"Query {query_id} registered with strategy: {normalized_strategy}")


def _get_query_strategy(query_id):
    """Get the strategy used for a specific query."""
    current_active_strategy = _get_active_strategy()
    if not query_id:
        return current_active_strategy
    with _strategy_lock:
        shared_strategy = _get_shared_strategy()
        query_map = shared_strategy.get('query_strategy_map', {})
        return query_map.get(query_id, current_active_strategy)


def _cleanup_query_strategy(query_id):
    """Remove the strategy mapping for a completed query."""
    if not query_id:
        return
    with _strategy_lock:
        shared_strategy = _get_shared_strategy()
        query_map = shared_strategy.get('query_strategy_map', {})
        if query_id in query_map:
            strategy = query_map[query_id]
            del query_map[query_id]
            shared_strategy['query_strategy_map'] = query_map
            remaining_queries = len(query_map)
            _strategy_debug_log(f"Query {query_id} completed (was using {strategy}). Remaining active queries: {remaining_queries}")


def _get_strategy_debug_info():
    """Get debug information about current strategy state."""
    with _strategy_lock:
        shared_strategy = _get_shared_strategy()
        return {
            'active_strategy': shared_strategy.get('active_strategy'),
            'pending_strategy': shared_strategy.get('pending_strategy'),
            'last_check_time': shared_strategy.get('last_check_time', 0),
            'last_transition_time': shared_strategy.get('last_transition_time', 0),
            'query_count': len(shared_strategy.get('query_strategy_map', {})),
            'current_time': time.time()
        }


def _get_grpc_header(engine_ip=None, cluster=None, strategy=None):
    """Generate gRPC metadata headers for the request."""
    # Use the strategy module's implementation
    return _get_strategy_header(engine_ip=engine_ip, cluster=cluster, strategy=strategy)


def connect(*args, **kwargs):
    """Constructor for creating a connection to the database. See class :py:class:`Connection` for
    arguments.
    :returns: a :py:class:`Connection` object.
    """
    return Connection(*args, **kwargs)


class Connection(object):
    """Create connection to e6data """

    def __init__(
            self,
            host: str,
            port: int,
            username: str,
            password: str,
            catalog: str = None,
            database: str = None,
            cluster_name: str = None,
            secure: bool = False,
            ssl_cert = None,
            auto_resume: bool = True,
            scheme: str = 'e6data',
            grpc_options: dict = None,
            debug: bool = False,
            require_fastbinary: bool = True,
    ):
        """
        Parameters
        ----------
            host: str
                IP address or hostname of e6data cluster
            port: int
                Port of the e6data engine
            username: str
                Your e6data Email ID
            password: str
                Access Token generated in the e6data console
            catalog: str
                Catalog name
            database: str
                Database to perform the query on
            cluster_name: str
                Cluster's name
            secure: bool, Optional
                Flag to use a secure channel for data transfer
            ssl_cert: str or bytes, Optional
                Path to CA certificate file (PEM format) or certificate content as bytes for
                secure connections. If None, system default CA bundle is used.
            auto_resume: bool, Optional
                Flag to enable auto resume of the cluster before the query execution
            scheme: string, Optional
                e6data supported scheme
            grpc_options: dict, Optional
                Specify gRPC configuration
                - keepalive_timeout_ms: This parameter defines the time, in milliseconds, that a gRPC connection should remain idle before sending a keepalive ping to check if the connection is still alive.
                - max_receive_message_length: This parameter sets the maximum allowed size (in bytes) for incoming messages on the gRPC server.
                - max_send_message_length: Similar to max_receive_message_length, this parameter sets the maximum allowed size (in bytes) for outgoing messages from the gRPC client
                - grpc_prepare_timeout: Timeout for prepare statement API call (default to 10 minutes).
                - keepalive_time_ms: This parameter defines the time, in milliseconds, Default to 30 seconds
            debug: bool, Optional
                Flag to enable debug logging for blue-green deployment strategy changes
            require_fastbinary: bool, Optional
                Flag to require fastbinary module for Thrift deserialization. If True (default),
                raises an exception if fastbinary is not available. If False, logs a warning
                and continues with pure Python implementation (with reduced performance).
        """
        if not username or not password:
            raise ValueError("username or password cannot be empty.")
        if not host or not port:
            raise ValueError("host or port cannot be empty.")
        self.__username = username
        self.__password = password
        self.database = database
        self.cluster_name = cluster_name.lower() if cluster_name else cluster_name
        self._session_id = None
        self._host = host
        self._port = port

        self._secure_channel = secure
        self._ssl_cert = ssl_cert

        self.catalog_name = catalog

        self._auto_resume = auto_resume

        # Store require_fastbinary flag
        self._require_fastbinary = require_fastbinary

        # Check fastbinary availability at connection creation time
        if not is_fastbinary_available():
            if require_fastbinary:
                raise Exception(
                    """
                    Failed to import fastbinary.
                    Did you install system dependencies?
                    Please verify https://github.com/e6x-labs/e6data-python-connector#dependencies

                    To continue without fastbinary (with reduced performance), set require_fastbinary=False
                    in the connection parameters.
                    """
                )
            else:
                logger.warning(
                    "fastbinary module is not available. Using pure Python implementation. "
                    "Performance may be degraded. To enable fastbinary, install system dependencies: "
                    "https://github.com/e6x-labs/e6data-python-connector#dependencies"
                )

        self._grpc_options = grpc_options
        if self._grpc_options is None:
            self._grpc_options = dict()
        self.grpc_prepare_timeout = self._grpc_options.get('grpc_prepare_timeout') or 10 * 60  # 10 minutes
        self.grpc_auto_resume_timeout_seconds = 60 * 5  # 5 minutes
        if 'grpc_auto_resume_timeout_seconds' in self._grpc_options:
            """
            The default maximum time on client side to wait for the cluster to resume is 5 minutes.
            """
            self.grpc_auto_resume_timeout_seconds = self._grpc_options.pop('grpc_auto_resume_timeout_seconds')
        
        # Store debug flag and register with debug connections
        self._debug = debug
        if self._debug:
            _debug_connections.add(id(self))

        # Enable comprehensive debugging if debug flag is set
        if self._debug:
            # Configure root logger for DEBUG level
            logging.basicConfig(
                level=logging.DEBUG,
                format='[%(name)s] %(asctime)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S',
                force=True  # Force reconfiguration even if logging is already configured
            )

            # Note: gRPC C++ core tracing (GRPC_VERBOSITY and GRPC_TRACE) must be set
            # BEFORE the gRPC module is imported to take effect. Setting them at runtime
            # will not enable HTTP/2 frame logs or low-level tracing.
            #
            # To enable full gRPC network tracing, set these environment variables
            # before starting your Python script:
            #   export GRPC_VERBOSITY=DEBUG
            #   export GRPC_TRACE=client_channel,http2
            #
            # The following runtime settings only affect Python-level logging:

            # Enable gRPC Python logging (this works at runtime)
            os.environ['GRPC_PYTHON_LOG_LEVEL'] = 'DEBUG'
            os.environ['GRPC_PYTHON_LOG_STDERR'] = '1'

            # Ensure gRPC logger is at DEBUG level
            grpc_logger = logging.getLogger('grpc')
            grpc_logger.setLevel(logging.DEBUG)

            # Enable gRPC transport logger
            grpc_transport_logger = logging.getLogger('grpc._channel')
            grpc_transport_logger.setLevel(logging.DEBUG)

            # Enable gRPC server logger
            grpc_server_logger = logging.getLogger('grpc._server')
            grpc_server_logger.setLevel(logging.DEBUG)

            # Set e6data connector logger to DEBUG
            e6data_logger = logging.getLogger('e6data_python_connector')
            e6data_logger.setLevel(logging.DEBUG)

            _strategy_debug_log(f"Debug mode enabled for connection {id(self)}")
            _strategy_debug_log(f"GRPC_TRACE={os.environ.get('GRPC_TRACE')}")

        self._create_client()

    @property
    def _get_grpc_options(self):
        """
        Property to get gRPC options for the connection.

        This method checks if the gRPC options are already cached. If not, it creates a copy of the
        provided gRPC options and merges them with the default options. The merged options are then
        cached for future use.

        Returns:
            list: A list of tuples containing gRPC options.
        """
        if not hasattr(self, '_cached_grpc_options'):
            grpc_options = self._grpc_options.copy()
            default_options = {
                "keepalive_timeout_ms": 900000,  # Time in milliseconds to keep the connection alive.
                "max_receive_message_length": -1,  # Maximum size of received messages.
                "max_send_message_length": 300 * 1024 * 1024,  # Maximum size of sent messages (300 MB).
                "grpc_prepare_timeout": self.grpc_prepare_timeout,  # Timeout for prepare statement API call.
                "keepalive_time_ms": 30000,  # Time in milliseconds between keep-alive pings.
                "keepalive_permit_without_calls": 1,  # Allow keep-alives with no active RPCs.
                "http2.max_pings_without_data": 0,  # Unlimited pings without data.
                "http2.min_time_between_pings_ms": 15000,  # Minimum time between pings (15 seconds).
                "http2.min_ping_interval_without_data_ms": 15000,
                # Minimum interval between pings without data (15 seconds).
            }
            if grpc_options:
                for key, value in grpc_options.items():
                    default_options[key] = value

            self._cached_grpc_options = [(f'grpc.{key}', value) for key, value in default_options.items()]

        return self._cached_grpc_options

    def _get_ssl_credentials(self):
        """
        Get SSL credentials for secure gRPC channel.

        Handles three scenarios:
        1. ssl_cert is a string (file path): Read the PEM certificate from the file
        2. ssl_cert is bytes: Use the certificate content directly
        3. ssl_cert is None: Use system default CA bundle

        Returns:
            grpc.ChannelCredentials: SSL credentials for secure channel

        Raises:
            FileNotFoundError: If ssl_cert is a file path but the file doesn't exist
            IOError: If ssl_cert file cannot be read
        """
        if self._ssl_cert is None:
            # Use system default CA bundle
            return grpc.ssl_channel_credentials()
        elif isinstance(self._ssl_cert, str):
            # ssl_cert is a file path - read the certificate from file
            try:
                with open(self._ssl_cert, 'rb') as cert_file:
                    root_ca_cert = cert_file.read()
                return grpc.ssl_channel_credentials(root_certificates=root_ca_cert)
            except FileNotFoundError:
                logger.error(f"SSL certificate file not found: {self._ssl_cert}")
                raise
            except IOError as e:
                logger.error(f"Failed to read SSL certificate file {self._ssl_cert}: {e}")
                raise
        elif isinstance(self._ssl_cert, bytes):
            # ssl_cert is certificate content as bytes
            return grpc.ssl_channel_credentials(root_certificates=self._ssl_cert)
        else:
            # Invalid type - log warning and use system default
            logger.warning(f"Invalid ssl_cert type: {type(self._ssl_cert)}. Using system default CA bundle.")
            return grpc.ssl_channel_credentials()

    def _create_client(self):
        """
        Creates a gRPC client for the connection.

        This method initializes a gRPC channel based on whether a secure channel is required or not.
        It then creates a client stub for the QueryEngineService.

        If the secure channel is enabled, it uses `grpc.secure_channel` with SSL credentials.
        Otherwise, it uses `grpc.insecure_channel`.

        The gRPC options are retrieved from the `_get_grpc_options` property.

        Raises:
            grpc.RpcError: If there is an error in creating the gRPC channel or client stub.
        """

        if self._secure_channel:
            self._channel = grpc.secure_channel(
                target='{}:{}'.format(self._host, self._port),
                options=self._get_grpc_options,
                credentials=self._get_ssl_credentials()
            )
        else:
            self._channel = grpc.insecure_channel(
                target='{}:{}'.format(self._host, self._port),
                options=self._get_grpc_options
            )
        self._client = e6x_engine_pb2_grpc.QueryEngineServiceStub(self._channel)

    def get_re_authenticate_session_id(self):
        """
        Re-authenticates the session by closing the current connection and creating a new client.

        This method is used to re-establish the session ID by closing the existing gRPC channel,
        creating a new client, and then retrieving a new session ID.

        Returns:
            str: The new session ID after re-authentication.

        Raises:
            Exception: If there is an error during the re-authentication process.
        """
        self.close()
        self._create_client()
        return self.get_session_id

    @property
    def get_session_id(self):
        """
        To get the session id, if user is not authorised, first authenticate the user.
        Also detects the active deployment strategy (blue/green) on first authentication.
        """
        # Check if we need a fresh connection due to strategy change
        shared_strategy = _get_shared_strategy()
        pending_strategy = shared_strategy.get('pending_strategy')
        active_strategy = shared_strategy.get('active_strategy')
        session_invalidated = shared_strategy.get('session_invalidated', False)

        # Check if session was invalidated globally
        if self._session_id and session_invalidated:
            self._session_id = None
            self.close()
            self._create_client()
            # Clear the invalidation flag
            shared_strategy['session_invalidated'] = False

        # Only create fresh connection if we have no active queries
        elif self._session_id and pending_strategy and pending_strategy != active_strategy:
            query_map = shared_strategy.get('query_strategy_map', {})
            if len(query_map) == 0:
                # Apply the pending strategy immediately since no queries are active
                _apply_pending_strategy()
                # Force complete reconnection with new strategy
                self._session_id = None
                self.close()
                self._create_client()

        if not self._session_id:
            try:
                authenticate_request = e6x_engine_pb2.AuthenticateRequest(
                    user=self.__username,
                    password=self.__password
                )

                # Check if we have a cached strategy
                active_strategy = _get_active_strategy()
                shared_strategy = _get_shared_strategy()
                pending_strategy = shared_strategy.get('pending_strategy')

                if active_strategy and not pending_strategy:
                    # Use cached strategy only if there's no pending strategy
                    _strategy_debug_log(f"Authenticating with cached strategy: {active_strategy}")
                    try:
                        authenticate_response = self._client.authenticate(
                            authenticate_request,
                            metadata=_get_grpc_header(cluster=self.cluster_name, strategy=active_strategy)
                        )
                        self._session_id = authenticate_response.sessionId
                        if not self._session_id:
                            raise ValueError("Invalid credentials.")
                        # Check for new strategy in authenticate response
                        if hasattr(authenticate_response, 'new_strategy') and authenticate_response.new_strategy:
                            new_strategy = authenticate_response.new_strategy.lower()
                            if new_strategy != active_strategy:
                                _set_pending_strategy(new_strategy)
                                _apply_pending_strategy()
                                self._session_id = None
                                self.close()
                                self._create_client()
                                return self.get_session_id
                    except _InactiveRpcError as e:
                        if e.code() == grpc.StatusCode.UNKNOWN and 'status: 456' in e.details():
                            # Strategy changed, clear cache and retry
                            _strategy_debug_log(f"Got 456 error with strategy {active_strategy}, clearing cache and retrying")
                            _clear_strategy_cache()
                            active_strategy = None
                        else:
                            if self._perform_auto_resume(e):
                                # Cluster resumed, retry with cached strategy
                                _strategy_debug_log(f"Cluster resumed, retrying with cached strategy {active_strategy}")
                                active_strategy = None  # Force retry
                            else:
                                raise e
                elif pending_strategy:
                    # If there's a pending strategy, force re-authentication with new strategy
                    active_strategy = None

                if not active_strategy:
                    # Check if we have a pending strategy to use
                    if pending_strategy:
                        # Use pending strategy and apply it immediately
                        _apply_pending_strategy()
                        active_strategy = _get_active_strategy()
                        strategies = [active_strategy]
                    else:
                        # Always try blue first, then green if it fails with 456
                        strategies = ['blue', 'green']
                        _strategy_debug_log(f"No cached strategy, will try strategies in order: {strategies}")
                    last_error = None
                    for strategy in strategies:
                        _strategy_debug_log(f"Attempting authentication with strategy: {strategy}.")
                        try:
                            authenticate_response = self._client.authenticate(
                                authenticate_request,
                                metadata=_get_grpc_header(cluster=self.cluster_name, strategy=strategy)
                            )
                            self._session_id = authenticate_response.sessionId
                            if self._session_id:
                                # Success! Cache this strategy
                                _strategy_debug_log(f"Authentication successful with strategy: {strategy}")
                                _set_active_strategy(strategy)

                                # Check for new strategy in authenticate response
                                if hasattr(authenticate_response, 'new_strategy') and authenticate_response.new_strategy:
                                    new_strategy = authenticate_response.new_strategy.lower()
                                    if new_strategy != strategy:
                                        _set_pending_strategy(new_strategy)
                                        _apply_pending_strategy()
                                        self.close()
                                        self._create_client()
                                        self._session_id = None
                                        return self.get_session_id
                                break
                        except _InactiveRpcError as e:
                            if e.code() == grpc.StatusCode.UNKNOWN and 'status: 456' in e.details():
                                # Wrong strategy, try the next one
                                _strategy_debug_log(f"Strategy {strategy} failed with 456 error, trying next")
                                last_error = e
                                continue
                            else:
                                if self._perform_auto_resume(e):
                                    # Cluster resumed successfully, retry authentication with current strategy
                                    _strategy_debug_log(f"Cluster resumed, retrying authentication with {strategy}")
                                    continue
                                else:
                                    # Auto-resume failed, raise the error
                                    raise e

                    if not self._session_id and last_error:
                        # Neither strategy worked
                        raise last_error

                if not self._session_id:
                    raise ValueError("Invalid credentials.")
            except _InactiveRpcError as e:
                self._perform_auto_resume(e)
            except Exception as e:
                self._channel.close()
                raise e
        return self._session_id

    def _perform_auto_resume(self, e: _InactiveRpcError):
        if self._auto_resume:
            if e.code() == grpc.StatusCode.UNAVAILABLE and 'status: 503' in e.details():
                status = ClusterManager(
                    host=self._host,
                    port=self._port,
                    user=self.__username,
                    password=self.__password,
                    secure_channel=self._secure_channel,
                    cluster_uuid=self.cluster_name,
                    timeout=self.grpc_auto_resume_timeout_seconds,
                    debug=self._debug,
                    ssl_cert=self._ssl_cert
                ).resume()
                return status  # Return boolean status directly
            else:
                return False  # Non-503 error, cannot auto-resume
        else:
            return False  # Auto-resume disabled

    def __enter__(self):
        """
        Enters the runtime context related to this object.

        This method is called when the execution flow enters the context of the `with` statement.

        Returns:
            Connection: The current instance of the connection.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exits the runtime context related to this object.

        This method is called when the execution flow exits the context of the `with` statement.

        Args:
            exc_type (Type[BaseException]): The type of exception raised (if any).
            exc_val (BaseException): The exception instance raised (if any).
            exc_tb (Traceback): The traceback object of the exception (if any).
        """
        self.close()

    def close(self):
        """
        Closes the gRPC channel and resets the session ID.

        This method ensures that the gRPC channel is properly closed and the session ID is reset to None.
        """
        if self._channel is not None:
            self._channel.close()
            self._channel = None
        self._session_id = None
        
        # Remove from debug connections if debug was enabled
        if self._debug:
            _debug_connections.discard(id(self))
            _strategy_debug_log(f"Debug mode disabled for connection {id(self)}")

    def check_connection(self):
        """
        Checks if the gRPC channel is still open.

        Returns:
            bool: True if the gRPC channel is open, False otherwise.
        """
        return self._channel is not None

    def check_strategy_change(self):
        """
        Checks if there's a pending strategy change and applies it if no queries are active.
        
        Returns:
            bool: True if strategy was changed, False otherwise.
        """
        shared_strategy = _get_shared_strategy()
        pending_strategy = shared_strategy.get('pending_strategy')
        active_strategy = shared_strategy.get('active_strategy')
        query_map = shared_strategy.get('query_strategy_map', {})

        if pending_strategy and pending_strategy != active_strategy and len(query_map) == 0:
            _apply_pending_strategy()
            # Force new authentication with new strategy
            self._session_id = None
            return True
        return False

    def _should_create_new_connection(self):
        """
        Determines if a new connection should be created based on strategy changes.
        
        Returns:
            bool: True if a new connection should be created.
        """
        shared_strategy = _get_shared_strategy()
        pending_strategy = shared_strategy.get('pending_strategy')
        active_strategy = shared_strategy.get('active_strategy')
        query_map = shared_strategy.get('query_strategy_map', {})

        # Create new connection if:
        # 1. No session exists
        # 2. There's a pending strategy change and no active queries
        return (not self._session_id or
                (pending_strategy and pending_strategy != active_strategy and len(query_map) == 0))

    def clear(self, query_id, engine_ip=None):
        """
        Clears the query results from the server.

        Args:
            query_id (str): The ID of the query to be cleared.
            engine_ip (str, optional): The IP address of the engine. Defaults to None.
        """
        clear_request = e6x_engine_pb2.ClearRequest(
            sessionId=self.get_session_id,
            queryId=query_id,
            engineIP=engine_ip
        )
        clear_response = self._client.clear(
            clear_request,
            metadata=_get_grpc_header(engine_ip=engine_ip, cluster=self.cluster_name, strategy=_get_active_strategy())
        )

        # Check for new strategy in clear response
        if hasattr(clear_response, 'new_strategy') and clear_response.new_strategy:
            _set_pending_strategy(clear_response.new_strategy)

    def reopen(self):
        """
        Reopens the gRPC channel by closing the current channel and creating a new client.

        This method is useful for re-establishing the connection if it was previously closed.
        """
        self._channel.close()
        self._create_client()

    def query_cancel(self, engine_ip, query_id):
        """
        Cancels the execution of a query on the server.

        Args:
            engine_ip (str): The IP address of the engine.
            query_id (str): The ID of the query to be canceled.
        """
        cancel_query_request = e6x_engine_pb2.CancelQueryRequest(
            engineIP=engine_ip,
            sessionId=self.get_session_id,
            queryId=query_id
        )
        cancel_response = self._client.cancelQuery(
            cancel_query_request,
            metadata=_get_grpc_header(engine_ip=engine_ip, cluster=self.cluster_name, strategy=_get_active_strategy())
        )

        # Check for new strategy in cancel response
        if hasattr(cancel_response, 'new_strategy') and cancel_response.new_strategy:
            _set_pending_strategy(cancel_response.new_strategy)

    def dry_run(self, query):
        """
        Performs a dry run of the query to validate its syntax and structure.

        Args:
            query (str): The SQL query to be validated.

        Returns:
            str: The result of the dry run validation.
        """
        dry_run_request = e6x_engine_pb2.DryRunRequest(
            sessionId=self.get_session_id,
            schema=self.database,
            queryString=query
        )
        dry_run_response = self._client.dryRun(
            dry_run_request,
            metadata=_get_grpc_header(cluster=self.cluster_name, strategy=_get_active_strategy())
        )
        return dry_run_response.dryrunValue

    def get_tables(self, catalog, database):
        """
        Retrieves the list of tables from the specified catalog and database.

        Args:
            catalog (str): The catalog name.
            database (str): The database name.

        Returns:
            list: A list of table names.
        """
        get_table_request = e6x_engine_pb2.GetTablesV2Request(
            sessionId=self.get_session_id,
            schema=database,
            catalog=catalog
        )
        get_table_response = self._client.getTablesV2(
            get_table_request,
            metadata=_get_grpc_header(cluster=self.cluster_name, strategy=_get_active_strategy())
        )

        # Check for new strategy in get tables response
        if hasattr(get_table_response, 'new_strategy') and get_table_response.new_strategy:
            _set_pending_strategy(get_table_response.new_strategy)
        return list(get_table_response.tables)

    def get_columns(self, catalog, database, table):
        """
        Retrieves the list of columns for the specified table in the given catalog and database.

        Args:
            catalog (str): The catalog name.
            database (str): The database name.
            table (str): The table name.

        Returns:
            list: A list of dictionaries containing column information.
        """
        get_columns_request = e6x_engine_pb2.GetColumnsV2Request(
            sessionId=self.get_session_id,
            schema=database,
            table=table,
            catalog=catalog
        )
        get_columns_response = self._client.getColumnsV2(
            get_columns_request,
            metadata=_get_grpc_header(cluster=self.cluster_name, strategy=_get_active_strategy())
        )

        # Check for new strategy in get columns response
        if hasattr(get_columns_response, 'new_strategy') and get_columns_response.new_strategy:
            _set_pending_strategy(get_columns_response.new_strategy)
        return [{'fieldName': row.fieldName, 'fieldType': row.fieldType} for row in get_columns_response.fieldInfo]

    def get_schema_names(self, catalog):
        """
        Retrieves the list of schema names from the specified catalog.

        Args:
            catalog (str): The catalog name.

        Returns:
            list: A list of schema names.
        """
        get_schema_request = e6x_engine_pb2.GetSchemaNamesV2Request(
            sessionId=self.get_session_id,
            catalog=catalog
        )
        get_schema_response = self._client.getSchemaNamesV2(
            get_schema_request,
            metadata=_get_grpc_header(cluster=self.cluster_name, strategy=_get_active_strategy())
        )

        # Check for new strategy in get schema names response
        if hasattr(get_schema_response, 'new_strategy') and get_schema_response.new_strategy:
            _set_pending_strategy(get_schema_response.new_strategy)

        return list(get_schema_response.schemas)

    def commit(self):
        """
        Commits the current transaction.

        Note:
            This method does nothing as transactions are not supported.
        """
        pass

    def cursor(self, catalog_name=None, db_name=None):
        """
        Creates a new cursor object for executing queries.

        Args:
            catalog_name (str, optional): The catalog name. Defaults to None.
            db_name (str, optional): The database name. Defaults to None.

        Returns:
            Cursor: A new cursor object.
        """
        return Cursor(self, database=db_name, catalog_name=catalog_name)

    def rollback(self):
        """
        Rolls back the current transaction.

        Raises:
            Exception: Always raises an exception as transactions are not supported.
        """
        raise Exception("e6data does not support transactions")  # pragma: no cover

    @property
    def client(self):
        """
        Returns the gRPC client stub for interacting with the server.

        Returns:
            e6x_engine_pb2_grpc.QueryEngineServiceStub: The gRPC client stub.
        """
        return self._client


class Cursor(DBAPICursor):
    """
    These objects represent a database cursor, which is used to manage the context of a fetch
    operation.
    Cursors are not isolated, i.e., any changes done to the database by a cursor are immediately
    visible by other cursors or connections.
    """

    def __init__(self, connection: Connection, array_size=1000, database=None, catalog_name=None):
        """
        Initialize a new Cursor object.

        Args:
            connection (Connection): The connection object to the database.
            array_size (int, optional): The number of rows to fetch at a time. Defaults to 1000.
            database (str, optional): The database name. Defaults to None.
            catalog_name (str, optional): The catalog name. Defaults to None.
        """
        super(Cursor, self).__init__()
        self._array_size = array_size
        self.connection = connection
        self._data = None
        self._query_columns_description = None
        self._is_metadata_updated = False
        self._description = None
        self._query_id = None
        self._engine_ip = None
        self._batch = list()
        self._rowcount = 0
        self._database = self.connection.database if database is None else database
        self._catalog_name = catalog_name if catalog_name else self.connection.catalog_name

    def _reset_state(self):
        """Reset state about the previous query in preparation for running another query"""
        pass

    @property
    def metadata(self):
        """
        Get the gRPC metadata for the current query.

        Returns:
            list: A list of tuples containing gRPC metadata.
        """
        # Use query-specific strategy if available, otherwise use active strategy
        strategy = _get_query_strategy(self._query_id) if self._query_id else _get_active_strategy()
        return _get_grpc_header(engine_ip=self._engine_ip, cluster=self.connection.cluster_name, strategy=strategy)

    @property
    def arraysize(self):
        """
        Get the array size for fetching rows.

        Returns:
            int: The number of rows to fetch at a time.
        """
        return self._arraysize

    @arraysize.setter
    def arraysize(self, value):
        """
        Set the array size for fetching rows.

        Args:
            value (int): The number of rows to fetch at a time.
        """
        default_arraysize = 1000
        try:
            self._arraysize = int(value) or default_arraysize
        except TypeError:
            self._arraysize = default_arraysize

    @property
    def description(self):
        """This read-only attribute is a sequence of 7-item sequences.
        Each of these sequences contains information describing one result column:
        - name
        - type_code
        - display_size (None in current implementation)
        - internal_size (None in current implementation)
        - precision (None in current implementation)
        - scale (None in current implementation)
        - null_ok (always True in current implementation)
        This attribute will be ``None`` for operations that do not return rows or if the cursor has
        not had an operation invoked via the :py:meth:`execute` method yet.
        The ``type_code`` can be interpreted by comparing it to the Type Objects specified in the
        section below.
        """
        if self._description is None:
            self._description = []
            for col in self._query_columns_description:
                type_code = col.get_field_type()
                column_name = col.get_name()
                self._description.append((
                    column_name,
                    type_code,
                    None, None, None, None, True
                ))
        return self._description

    def __enter__(self):
        """
        Enter the runtime context related to this object.

        Returns:
            Cursor: The current instance of the cursor.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exit the runtime context related to this object.

        Args:
            exc_type (Type[BaseException]): The type of exception raised (if any).
            exc_val (BaseException): The exception instance raised (if any).
            exc_tb (Traceback): The traceback object of the exception (if any).
        """
        self.close()

    def close(self):
        """
         Close the operation handle and reset the cursor state.
         """
        try:
            self.clear()
        except:
            pass
        self._arraysize = None
        self.connection = None
        self._data = None
        self._engine_ip = None
        self._query_columns_description = None
        self._description = None
        self._query_id = None
        self._batch = None
        self._rowcount = None
        self._database = None

    def get_tables(self):
        """
        Retrieve the list of tables from the current database.

        Returns:
            list: A list of table names.
        """
        schema = self.connection.database
        return self.connection.get_tables(catalog=self._catalog_name, database=schema)

    def get_columns(self, table):
        """
        Retrieve the list of columns for the specified table.

        Args:
            table (str): The table name.

        Returns:
            list: A list of dictionaries containing column information.
        """
        schema = self.connection.database
        return self.connection.get_columns(catalog=self._catalog_name, database=schema, table=table)

    def get_schema_names(self):
        """
         Retrieve the list of schema names from the current catalog.

         Returns:
             list: A list of schema names.
         """
        return self.connection.get_schema_names(catalog=self._catalog_name)

    def clear(self, query_id=None):
        """
        Clear the query results from the server.

        Args:
            query_id (str, optional): The ID of the query to be cleared. Defaults to None.
        """
        if not query_id:
            query_id = self._query_id

        clear_request = e6x_engine_pb2.ClearOrCancelQueryRequest(
            sessionId=self.connection.get_session_id,
            queryId=query_id,
            engineIP=self._engine_ip
        )
        # Get fresh client after session access (may have been invalidated)
        client = self.connection.client
        clear_response = client.clearOrCancelQuery(clear_request, metadata=self.metadata)

        # Check for new strategy in clear response
        if hasattr(clear_response, 'new_strategy') and clear_response.new_strategy:
            _set_pending_strategy(clear_response.new_strategy)

        # Clean up query strategy mapping
        if query_id:
            _cleanup_query_strategy(query_id)

        # Check if this was the last query and we have a pending strategy
        shared_strategy = _get_shared_strategy()
        pending_strategy = shared_strategy.get('pending_strategy')
        query_map = shared_strategy.get('query_strategy_map', {})

        if pending_strategy and len(query_map) == 0:
            _strategy_debug_log(f"Last query cleared, triggering pending strategy transition")
            _apply_pending_strategy()

        return clear_response

    def cancel(self, query_id):
        """
        Cancel the execution of a query on the server.

        Args:
            query_id (str): The ID of the query to be canceled.
        """
        # Clean up query strategy mapping for cancelled query
        self.connection.query_cancel(engine_ip=self._engine_ip, query_id=query_id)

        if query_id:
            _cleanup_query_strategy(query_id)

        # Check if this was the last query and we have a pending strategy
        shared_strategy = _get_shared_strategy()
        pending_strategy = shared_strategy.get('pending_strategy')
        query_map = shared_strategy.get('query_strategy_map', {})

        if pending_strategy and len(query_map) == 0:
            _strategy_debug_log(f"Last query cleared, triggering pending strategy transition")
            _apply_pending_strategy()

    def status(self, query_id):
        """
        Get the status of the specified query.

        Args:
            query_id (str): The ID of the query.

        Returns:
            StatusResponse: The status response of the query.
        """
        status_request = e6x_engine_pb2.StatusRequest(
            sessionId=self.connection.get_session_id,
            queryId=query_id,
            engineIP=self._engine_ip
        )
        status_response = self.connection.client.status(status_request, metadata=self.metadata)

        # Check for new strategy in status response
        if hasattr(status_response, 'new_strategy') and status_response.new_strategy:
            _set_pending_strategy(status_response.new_strategy)

        return status_response

    @re_auth
    def execute(self, operation, parameters=None, **kwargs):
        """
        Prepare and execute a database operation (query or command).

        Args:
            operation (str): The SQL query or command to execute.
            parameters (dict, optional): The parameters to bind to the query. Defaults to None.

        Returns:
            str: The query ID of the executed query.
        """
        # Semicolon is now not supported. So removing it from query end.
        operation = operation.strip()  # Remove leading and trailing whitespaces.
        if operation.endswith(';'):
            operation = operation[:-1]

        # Prepare statement
        if parameters is None:
            sql = operation
        else:
            sql = operation % _escaper.escape_args(parameters)

        if not self._catalog_name:
            prepare_statement_request = e6x_engine_pb2.PrepareStatementRequest(
                sessionId=self.connection.get_session_id,
                schema=self._database,
                queryString=sql
            )
            # Get fresh client after session access (may have been invalidated)
            client = self.connection.client
            prepare_statement_response = client.prepareStatement(
                prepare_statement_request,
                metadata=self.metadata
            )

            self._query_id = prepare_statement_response.queryId
            self._engine_ip = prepare_statement_response.engineIP

            # Check for new strategy in prepare response
            if hasattr(prepare_statement_response, 'new_strategy') and prepare_statement_response.new_strategy:
                new_strategy = prepare_statement_response.new_strategy.lower()
                if new_strategy != _get_active_strategy():
                    _set_pending_strategy(new_strategy)

            # Register this query with the current strategy
            current_strategy = _get_active_strategy()
            if current_strategy:
                _register_query_strategy(self._query_id, current_strategy)

            execute_statement_request = e6x_engine_pb2.ExecuteStatementRequest(
                engineIP=self._engine_ip,
                sessionId=self.connection.get_session_id,
                queryId=self._query_id,
            )
            # Get fresh client after session access (may have been invalidated)
            client = self.connection.client
            execute_response = client.executeStatement(
                execute_statement_request,
                metadata=self.metadata
            )

            # Check for new strategy in execute response
            if hasattr(execute_response, 'new_strategy') and execute_response.new_strategy:
                new_strategy = execute_response.new_strategy.lower()
                if new_strategy != _get_active_strategy():
                    _set_pending_strategy(new_strategy)
        else:
            prepare_statement_request = e6x_engine_pb2.PrepareStatementV2Request(
                sessionId=self.connection.get_session_id,
                schema=self._database,
                catalog=self._catalog_name,
                queryString=sql
            )
            # Get fresh client after session access (may have been invalidated)
            client = self.connection.client
            prepare_statement_response = client.prepareStatementV2(
                prepare_statement_request,
                metadata=self.metadata,
                timeout=self.connection.grpc_prepare_timeout
            )

            self._query_id = prepare_statement_response.queryId
            self._engine_ip = prepare_statement_response.engineIP

            # Check for new strategy in prepare response
            if hasattr(prepare_statement_response, 'new_strategy') and prepare_statement_response.new_strategy:
                new_strategy = prepare_statement_response.new_strategy.lower()
                if new_strategy != _get_active_strategy():
                    _set_pending_strategy(new_strategy)

            # Register this query with the current strategy
            current_strategy = _get_active_strategy()

            if current_strategy:
                _register_query_strategy(self._query_id, current_strategy)

            execute_statement_request = e6x_engine_pb2.ExecuteStatementV2Request(
                engineIP=self._engine_ip,
                sessionId=self.connection.get_session_id,
                queryId=self._query_id
            )
            # Get fresh client after session access (may have been invalidated)
            client = self.connection.client
            execute_response = client.executeStatementV2(
                execute_statement_request,
                metadata=self.metadata
            )

            # Check for new strategy in execute response
            if hasattr(execute_response, 'new_strategy') and execute_response.new_strategy:
                new_strategy = execute_response.new_strategy.lower()
                if new_strategy != _get_active_strategy():
                    _set_pending_strategy(new_strategy)
        self.update_mete_data()
        return self._query_id

    @property
    def rowcount(self):
        """
        Get the number of rows affected by the last execute operation.

        Returns:
            int: The number of rows affected.
        """
        self.update_mete_data()
        return self._rowcount

    def update_mete_data(self):
        """
        Update the metadata for the current query.
        """
        result_meta_data_request = e6x_engine_pb2.GetResultMetadataRequest(
            engineIP=self._engine_ip,
            sessionId=self.connection.get_session_id,
            queryId=self._query_id
        )
        # Get fresh client after session access (may have been invalidated)
        client = self.connection.client
        get_result_metadata_response = client.getResultMetadata(
            result_meta_data_request,
            metadata=self.metadata
        )

        # Check for new strategy in metadata response
        if hasattr(get_result_metadata_response, 'new_strategy') and get_result_metadata_response.new_strategy:
            new_strategy = get_result_metadata_response.new_strategy.lower()
            if new_strategy != _get_active_strategy():
                _set_pending_strategy(new_strategy)

        buffer = BytesIO(get_result_metadata_response.resultMetaData)
        self._rowcount, self._query_columns_description = get_query_columns_info(buffer)
        self._is_metadata_updated = True

    def _fetch_more(self):
        """
        Fetch more rows from the server.

        Returns:
            list: A list of rows fetched from the server.
        """
        batch_size = self._arraysize
        self._data = list()
        for i in range(batch_size):
            rows = self.fetch_batch()
            if rows is None:
                return
            self._data = self._data + rows
        return self._data

    def _fetch_all(self):
        """
        Fetch all rows from the server.

        Returns:
            list: A list of all rows fetched from the server.
        """
        self._data = list()
        while True:
            rows = self.fetch_batch()
            if rows is None:
                break
            self._data = self._data + rows
        rows = self._data
        self._data = None
        return rows

    def fetchall_buffer(self, query_id=None):
        """
        Fetch all rows from the server in a buffered manner.

        Args:
            query_id (str, optional): The ID of the query. Defaults to None.

        Yields:
            list: A list of rows fetched from the server.
        """
        if query_id:
            self._query_id = query_id
        while True:
            rows = self.fetch_batch()
            if not rows:
                return
            yield rows

    def fetch_batch(self):
        """
        Fetch a batch of rows from the server.

        Returns:
            list: A list of rows fetched from the server.
        """
        get_next_result_batch_request = e6x_engine_pb2.GetNextResultBatchRequest(
            engineIP=self._engine_ip,
            sessionId=self.connection.get_session_id,
            queryId=self._query_id
        )
        # Get fresh client after session access (may have been invalidated)
        client = self.connection.client
        get_next_result_batch_response = client.getNextResultBatch(
            get_next_result_batch_request,
            metadata=self.metadata
        )

        # Check for new strategy in batch response
        if hasattr(get_next_result_batch_response, 'new_strategy') and get_next_result_batch_response.new_strategy:
            new_strategy = get_next_result_batch_response.new_strategy.lower()
            if new_strategy != _get_active_strategy():
                _set_pending_strategy(new_strategy)

        buffer = get_next_result_batch_response.resultBatch
        if not self._is_metadata_updated:
            self.update_mete_data()
        if not buffer or len(buffer) == 0:
            return None
        # one batch retrieves the predefined set of rows
        return read_rows_from_chunk(
            self._query_columns_description,
            buffer
        )

    def fetchall(self):
        """
         Fetch all rows from the server.

         Returns:
             list: A list of all rows fetched from the server.
         """
        return self._fetch_all()

    def fetchmany(self, size: int = None):
        """
        Fetch a specified number of rows from the server.

        Args:
            size (int, optional): The number of rows to fetch. Defaults to None.

        Returns:
            list: A list of rows fetched from the server.
        """
        if size is None:
            size = self.arraysize
        if self._data is None:
            self._data = list()
        while len(self._data) < size:
            rows = self.fetch_batch()
            if rows is None:
                break
            self._data += rows
        if len(self._data) <= size:
            rows = self._data
            self._data = None
            return rows
        rows = self._data[:size]
        self._data = self._data[size:]
        return rows

    def fetchone(self):
        """
        Fetch a single row from the server.

        Returns:
            list: A single row fetched from the server.
        """
        rows = self.fetchmany(1)
        if rows is None or len(rows) == 0:
            return None
        return rows

    def explain(self):
        """
        Get the execution plan for the current query.

        Returns:
            str: The execution plan of the query.
        """
        explain_request = e6x_engine_pb2.ExplainRequest(
            engineIP=self._engine_ip,
            sessionId=self.connection.get_session_id,
            queryId=self._query_id
        )
        explain_response = self.connection.client.explain(
            explain_request,
            metadata=self.metadata
        )
        return explain_response.explain

    def explain_analyse(self):
        """
        Get the execution plan for the current query.

        Returns:
            dict: The execution plan of the query.
        """
        explain_analyze_request = e6x_engine_pb2.ExplainAnalyzeRequest(
            engineIP=self._engine_ip,
            sessionId=self.connection.get_session_id,
            queryId=self._query_id
        )
        # Get fresh client after session access (may have been invalidated)
        client = self.connection.client
        explain_analyze_response = client.explainAnalyze(
            explain_analyze_request,
            metadata=self.metadata
        )

        # Check for new strategy in explain analyze response
        if hasattr(explain_analyze_response, 'new_strategy') and explain_analyze_response.new_strategy:
            _set_pending_strategy(explain_analyze_response.new_strategy)

        return dict(
            is_cached=explain_analyze_response.isCached,
            parsing_time=explain_analyze_response.parsingTime,
            queuing_time=explain_analyze_response.queueingTime,
            planner=explain_analyze_response.explainAnalyze,
        )


def poll(self, get_progress_update=True):
    """Poll for and return the raw status data provided by the Hive Thrift REST API.
    :returns: ``ttypes.TGetOperationStatusResp``
    :raises: ``ProgrammingError`` when no query has been started
    .. note::
        This is not a part of DB-API.
    """
    pass


def fetch_logs(self):
    """Retrieve the logs produced by the execution of the query.
    Can be called multiple times to fetch the logs produced after the previous call.
    :returns: list<str>
    :raises: ``ProgrammingError`` when no query has been started
    .. note::
        This is not a part of DB-API.
    """
    pass


class Error(Exception):
    pass


#
# Type Objects and Constructors
#

for type_id in PRIMITIVE_TYPES:
    name = TypeId._VALUES_TO_NAMES[type_id]
    setattr(sys.modules[__name__], name, DBAPITypeObject([name]))
