class NotSupportedError(Exception):
    """Raised when op not supported by e6xdb"""
    pass

class ProgrammingError(Exception):
    """Raised when op not supported by e6xdb"""
    pass

class DataError(Exception):
    """Raised when there are inherent data issues"""
    pass

class OperationalError(Exception):
    """Raised when there are operational issues in Uniphi"""
    pass

class OAuthError(Exception):
    """Raised when an OAuth 2.0 access token cannot be obtained from the authorization server"""
    pass


class OAuthNotSupportedError(Exception):
    """Raised when OAuth authentication was requested but the engine did not accept it"""
    pass


class IncompleteResultError(OperationalError):
    """A consumed result cannot safely be replayed; retain the query for cleanup."""
    _reasons = frozenset(('ambiguous_result', 'decode_failed', 'aggregation_failed', 'cancelled_result'))

    def __init__(self, reason='ambiguous_result', query_id=None):
        self.reason = reason if reason in self._reasons else 'ambiguous_result'
        self.query_id = query_id
        super().__init__(self.reason)


class AmbiguousSubmissionError(OperationalError):
    """Submission may have reached the server; automatic replay is unsafe."""
    def __init__(self, reason='ambiguous_submission', query_id=None, parameter_index=None):
        self.reason = 'ambiguous_submission'
        self.query_id = query_id
        self.parameter_index = parameter_index
        super().__init__(self.reason)
