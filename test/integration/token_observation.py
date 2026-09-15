"""Count actual issuer exchange entries without replacing either transport."""
from contextlib import AbstractContextManager
import dis
import hashlib
import inspect
import sys
import threading

from e6data_python_connector.oauth import ClientCredentialsTokenProvider
from e6data_python_connector.async_oauth import AsyncClientCredentialsTokenProvider


def token_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


class FetchObservation(AbstractContextManager):
    def __init__(self):
        functions = (ClientCredentialsTokenProvider._fetch_token,
                     AsyncClientCredentialsTokenProvider._fetch_token)
        self._starts = {
            function.__code__: (
                {instruction.offset for instruction in dis.get_instructions(function)
                 if instruction.opname == 'RESUME' and instruction.arg == 0}
                if inspect.iscoroutinefunction(function) else None
            ) for function in functions
        }
        self._lock = threading.Lock()
        self.count = 0

    def _profile(self, frame, event, arg):
        if event != 'call' or frame.f_code not in self._starts:
            return
        starts = self._starts[frame.f_code]
        if starts is None or frame.f_lasti in starts:
            with self._lock:
                self.count += 1

    def __enter__(self):
        self._sys_profile = sys.getprofile()
        self._thread_profile = threading.getprofile()
        sys.setprofile(self._profile)
        threading.setprofile(self._profile)
        return self

    def __exit__(self, *args):
        sys.setprofile(self._sys_profile)
        threading.setprofile(self._thread_profile)


def provider_options(config):
    values = config.connection_kwargs
    return dict(token_url=values['token_url'], client_id=values['client_id'],
                client_secret=values['client_secret'], scope=values.get('oauth_scope'),
                client_auth_method=values.get('client_auth_method', 'basic'))
