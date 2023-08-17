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