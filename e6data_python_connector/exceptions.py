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
