"""
Unit tests for code optimizations made to e6data-python-connector.

Tests cover:
1. SSL credentials utility function (get_ssl_credentials)
2. Constants usage
3. Strategy-related optimizations
"""

import unittest
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock
import grpc

# Import the modules we're testing
from e6data_python_connector.common import get_ssl_credentials
from e6data_python_connector import constants
from e6data_python_connector.strategy import _get_grpc_header


class TestSSLCredentialsUtility(unittest.TestCase):
    """Test cases for the get_ssl_credentials utility function."""

    def test_ssl_cert_none_returns_default_credentials(self):
        """Test that None returns system default CA bundle."""
        credentials = get_ssl_credentials(None)
        self.assertIsNotNone(credentials)
        # Should return grpc.ssl_channel_credentials() with no args

    def test_ssl_cert_with_valid_file_path(self):
        """Test that valid file path reads and returns credentials."""
        # Create a temporary certificate file
        cert_content = b"""-----BEGIN CERTIFICATE-----
MIIDXTCCAkWgAwIBAgIJAKL0UG+mRKKzMA0GCSqGSIb3DQEBCwUAMEUxCzAJBgNV
BAYTAkFVMRMwEQYDVQQIDApTb21lLVN0YXRlMSEwHwYDVQQKDBhJbnRlcm5ldCBX
-----END CERTIFICATE-----"""

        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.pem') as f:
            f.write(cert_content)
            cert_file_path = f.name

        try:
            credentials = get_ssl_credentials(cert_file_path)
            self.assertIsNotNone(credentials)
        finally:
            os.unlink(cert_file_path)

    def test_ssl_cert_with_invalid_file_path_raises_error(self):
        """Test that invalid file path raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            get_ssl_credentials('/nonexistent/path/to/cert.pem')

    def test_ssl_cert_with_bytes_content(self):
        """Test that certificate content as bytes works correctly."""
        cert_content = b"""-----BEGIN CERTIFICATE-----
MIIDXTCCAkWgAwIBAgIJAKL0UG+mRKKzMA0GCSqGSIb3DQEBCwUAMEUxCzAJBgNV
BAYTAkFVMRMwEQYDVQQIDApTb21lLVN0YXRlMSEwHwYDVQQKDBhJbnRlcm5ldCBX
-----END CERTIFICATE-----"""

        credentials = get_ssl_credentials(cert_content)
        self.assertIsNotNone(credentials)

    def test_ssl_cert_with_invalid_type_returns_default(self):
        """Test that invalid type (not str/bytes/None) returns default credentials with warning."""
        # Should log warning and return default credentials
        with patch('e6data_python_connector.common._logger') as mock_logger:
            credentials = get_ssl_credentials(12345)  # Invalid type
            self.assertIsNotNone(credentials)
            # Verify warning was logged
            mock_logger.warning.assert_called()

    def test_ssl_cert_with_unreadable_file_raises_io_error(self):
        """Test that unreadable file raises IOError."""
        # Create a file and make it unreadable
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.pem') as f:
            f.write(b"test cert")
            cert_file_path = f.name

        try:
            os.chmod(cert_file_path, 0o000)  # Remove all permissions
            with self.assertRaises(IOError):
                get_ssl_credentials(cert_file_path)
        finally:
            os.chmod(cert_file_path, 0o644)  # Restore permissions
            os.unlink(cert_file_path)


class TestConstants(unittest.TestCase):
    """Test cases for constants module."""

    def test_retry_constants_exist(self):
        """Test that retry-related constants are defined."""
        self.assertTrue(hasattr(constants, 'MAX_RETRY_ATTEMPTS'))
        self.assertTrue(hasattr(constants, 'RETRY_SLEEP_SECONDS'))
        self.assertIsInstance(constants.MAX_RETRY_ATTEMPTS, int)
        self.assertIsInstance(constants.RETRY_SLEEP_SECONDS, (int, float))

    def test_timeout_constants_exist(self):
        """Test that timeout-related constants are defined."""
        self.assertTrue(hasattr(constants, 'STRATEGY_CACHE_TIMEOUT_SECONDS'))
        self.assertTrue(hasattr(constants, 'DEFAULT_GRPC_PREPARE_TIMEOUT_SECONDS'))
        self.assertTrue(hasattr(constants, 'DEFAULT_AUTO_RESUME_TIMEOUT_SECONDS'))
        self.assertTrue(hasattr(constants, 'CLUSTER_STATUS_CHECK_SLEEP_SECONDS'))
        self.assertTrue(hasattr(constants, 'LOCK_TIMEOUT_MS'))

    def test_connection_pool_constants_exist(self):
        """Test that connection pool constants are defined."""
        self.assertTrue(hasattr(constants, 'POOL_GET_TIMEOUT_SECONDS'))
        self.assertTrue(hasattr(constants, 'POOL_RETRY_SLEEP_SECONDS'))
        self.assertIsInstance(constants.POOL_GET_TIMEOUT_SECONDS, (int, float))
        self.assertIsInstance(constants.POOL_RETRY_SLEEP_SECONDS, (int, float))

    def test_strategy_constants_exist(self):
        """Test that strategy-related constants are defined."""
        self.assertTrue(hasattr(constants, 'STRATEGY_BLUE'))
        self.assertTrue(hasattr(constants, 'STRATEGY_GREEN'))
        self.assertTrue(hasattr(constants, 'VALID_STRATEGIES'))

        self.assertEqual(constants.STRATEGY_BLUE, 'blue')
        self.assertEqual(constants.STRATEGY_GREEN, 'green')
        self.assertIsInstance(constants.VALID_STRATEGIES, set)
        self.assertIn('blue', constants.VALID_STRATEGIES)
        self.assertIn('green', constants.VALID_STRATEGIES)

    def test_grpc_error_constants_exist(self):
        """Test that gRPC error message constants are defined."""
        self.assertTrue(hasattr(constants, 'GRPC_ERROR_STRATEGY_MISMATCH'))
        self.assertTrue(hasattr(constants, 'GRPC_ERROR_SERVICE_UNAVAILABLE'))
        self.assertTrue(hasattr(constants, 'GRPC_ERROR_ACCESS_DENIED'))

        self.assertEqual(constants.GRPC_ERROR_STRATEGY_MISMATCH, 'status: 456')
        self.assertEqual(constants.GRPC_ERROR_SERVICE_UNAVAILABLE, 'status: 503')
        self.assertEqual(constants.GRPC_ERROR_ACCESS_DENIED, 'Access denied')

    def test_constant_values_are_sensible(self):
        """Test that constant values are sensible/reasonable."""
        # Retry attempts should be positive
        self.assertGreater(constants.MAX_RETRY_ATTEMPTS, 0)

        # Timeouts should be positive
        self.assertGreater(constants.STRATEGY_CACHE_TIMEOUT_SECONDS, 0)
        self.assertGreater(constants.DEFAULT_GRPC_PREPARE_TIMEOUT_SECONDS, 0)
        self.assertGreater(constants.DEFAULT_AUTO_RESUME_TIMEOUT_SECONDS, 0)

        # Sleep durations should be positive
        self.assertGreater(constants.RETRY_SLEEP_SECONDS, 0)
        self.assertGreater(constants.CLUSTER_STATUS_CHECK_SLEEP_SECONDS, 0)


class TestGrpcHeaderFunction(unittest.TestCase):
    """Test cases for _get_grpc_header function (ensure no duplicate wrappers)."""

    def test_get_grpc_header_imports_correctly(self):
        """Test that _get_grpc_header is imported from strategy module."""
        # This should work without errors
        from e6data_python_connector.strategy import _get_grpc_header
        self.assertTrue(callable(_get_grpc_header))

    def test_get_grpc_header_basic_call(self):
        """Test basic functionality of _get_grpc_header."""
        headers = _get_grpc_header()
        self.assertIsInstance(headers, list)

    def test_get_grpc_header_with_engine_ip(self):
        """Test _get_grpc_header with engine IP."""
        headers = _get_grpc_header(engine_ip='192.168.1.1')
        self.assertIsInstance(headers, list)
        # Should contain plannerip header (actual header name used)
        header_keys = [h[0] for h in headers]
        self.assertIn('plannerip', header_keys)

    def test_get_grpc_header_with_cluster(self):
        """Test _get_grpc_header with cluster UUID."""
        headers = _get_grpc_header(cluster='test-cluster-uuid')
        self.assertIsInstance(headers, list)
        # Should contain cluster-name header (actual header name used)
        header_keys = [h[0] for h in headers]
        self.assertIn('cluster-name', header_keys)

    def test_get_grpc_header_with_strategy(self):
        """Test _get_grpc_header with strategy."""
        headers = _get_grpc_header(strategy='blue')
        self.assertIsInstance(headers, list)
        # Should contain strategy header
        header_keys = [h[0] for h in headers]
        self.assertIn('strategy', header_keys)

    def test_get_grpc_header_with_all_params(self):
        """Test _get_grpc_header with all parameters."""
        headers = _get_grpc_header(
            engine_ip='192.168.1.1',
            cluster='test-cluster',
            strategy='green'
        )
        self.assertIsInstance(headers, list)
        header_keys = [h[0] for h in headers]
        self.assertIn('plannerip', header_keys)  # Actual header name
        self.assertIn('cluster-name', header_keys)  # Actual header name
        self.assertIn('strategy', header_keys)


class TestReAuthDecorator(unittest.TestCase):
    """Test cases for re_auth decorator with constants."""

    def test_reauth_decorator_source_uses_constants(self):
        """Test that re_auth decorator source code uses constant names."""
        from e6data_python_connector.e6data_grpc import re_auth
        import inspect

        # Get the source code of the re_auth decorator
        source = inspect.getsource(re_auth)

        # Verify it uses the constant names instead of magic numbers
        self.assertIn('MAX_RETRY_ATTEMPTS', source)
        self.assertIn('RETRY_SLEEP_SECONDS', source)
        self.assertIn('GRPC_ERROR_ACCESS_DENIED', source)
        self.assertIn('GRPC_ERROR_STRATEGY_MISMATCH', source)

        # Verify it doesn't have hardcoded values
        self.assertNotIn('max_retry = 5', source)
        self.assertNotIn('time.sleep(0.2)', source,
                        "Should use RETRY_SLEEP_SECONDS constant instead of hardcoded 0.2")

    def test_reauth_error_messages_use_constants(self):
        """Test that error message checks use constants."""
        from e6data_python_connector.e6data_grpc import re_auth
        import inspect

        source = inspect.getsource(re_auth)

        # Should use constants for error message matching
        # Instead of 'Access denied' or 'status: 456'
        self.assertIn('GRPC_ERROR_ACCESS_DENIED', source)
        self.assertIn('GRPC_ERROR_STRATEGY_MISMATCH', source)

        # Should not have hardcoded error strings
        self.assertNotIn("'Access denied'", source,
                        "Should use GRPC_ERROR_ACCESS_DENIED constant")
        self.assertNotIn("'status: 456'", source,
                        "Should use GRPC_ERROR_STRATEGY_MISMATCH constant")


class TestCodeDuplicationRemoval(unittest.TestCase):
    """Test that code duplication has been properly removed."""

    def test_no_duplicate_get_ssl_credentials_in_e6data_grpc(self):
        """Test that get_ssl_credentials is not duplicated in e6data_grpc module."""
        import e6data_python_connector.e6data_grpc as grpc_module

        # Should not have its own _get_ssl_credentials method
        # It should use the one from common
        self.assertFalse(hasattr(grpc_module.Connection, '_get_ssl_credentials'))

    def test_no_duplicate_get_ssl_credentials_in_cluster_manager(self):
        """Test that get_ssl_credentials is not duplicated in cluster_manager module."""
        import e6data_python_connector.cluster_manager as cm_module

        # Should not have its own _get_ssl_credentials method
        self.assertFalse(hasattr(cm_module.ClusterManager, '_get_ssl_credentials'))

    def test_no_duplicate_get_grpc_header_in_e6data_grpc(self):
        """Test that _get_grpc_header wrapper is not duplicated in e6data_grpc."""
        import e6data_python_connector.e6data_grpc as grpc_module
        import inspect

        # Should import from strategy, not define its own
        source = inspect.getsource(grpc_module)

        # Should have import statement
        self.assertIn('from e6data_python_connector.strategy import _get_grpc_header', source)

        # Should NOT have its own definition (wrapper function)
        # Look for function definition pattern
        self.assertNotIn('def _get_grpc_header(engine_ip=None, cluster=None, strategy=None):', source)

    def test_no_duplicate_get_grpc_header_in_cluster_manager(self):
        """Test that _get_grpc_header wrapper is not duplicated in cluster_manager."""
        import e6data_python_connector.cluster_manager as cm_module
        import inspect

        source = inspect.getsource(cm_module)

        # Should have import statement
        self.assertIn('from e6data_python_connector.strategy import', source)
        self.assertIn('_get_grpc_header', source)

        # Should NOT have its own wrapper definition
        self.assertNotIn('def _get_grpc_header(engine_ip=None, cluster=None, strategy=None):', source)


class TestConstantsIntegration(unittest.TestCase):
    """Integration tests to ensure constants are used throughout codebase."""

    def test_e6data_grpc_imports_constants(self):
        """Test that e6data_grpc imports and uses constants."""
        import e6data_python_connector.e6data_grpc as grpc_module
        import inspect

        source = inspect.getsource(grpc_module)

        # Should import constants
        self.assertIn('from e6data_python_connector.constants import', source)

        # Should use the constants
        self.assertIn('MAX_RETRY_ATTEMPTS', source)
        self.assertIn('RETRY_SLEEP_SECONDS', source)
        self.assertIn('GRPC_ERROR_STRATEGY_MISMATCH', source)
        self.assertIn('GRPC_ERROR_ACCESS_DENIED', source)

    def test_constants_values_match_expected(self):
        """Test that constant values match expected values from original code."""
        # These should match the original hardcoded values
        self.assertEqual(constants.MAX_RETRY_ATTEMPTS, 5)
        self.assertEqual(constants.RETRY_SLEEP_SECONDS, 0.2)
        self.assertEqual(constants.STRATEGY_CACHE_TIMEOUT_SECONDS, 300)
        self.assertEqual(constants.DEFAULT_GRPC_PREPARE_TIMEOUT_SECONDS, 600)
        self.assertEqual(constants.DEFAULT_AUTO_RESUME_TIMEOUT_SECONDS, 300)


if __name__ == '__main__':
    unittest.main()