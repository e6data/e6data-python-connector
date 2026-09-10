"""Explicit optional native asyncio entry point (Python 3.11+)."""
import sys

if sys.version_info < (3, 11):
    raise RuntimeError('The async API requires Python 3.11 or newer.')
try:
    import httpx as _httpx
except ImportError:
    raise ImportError('Install e6data-python-connector[async] for the async API.') from None

from .async_connection import AsyncConnection

__all__ = ['connect', 'AsyncConnection', 'AsyncCursor', 'AsyncConnectionPool', 'AsyncClusterManager']


async def connect(*args, **kwargs):
    return await AsyncConnection(*args, **kwargs).open()


def __getattr__(name):
    modules = {'AsyncCursor': 'async_cursor', 'AsyncConnectionPool': 'async_connection_pool',
               'AsyncClusterManager': 'async_cluster_manager'}
    if name not in modules:
        raise AttributeError(name)
    from importlib import import_module
    return getattr(import_module('.' + modules[name], __package__), name)
