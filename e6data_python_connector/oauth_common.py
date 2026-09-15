"""Pure OAuth validation shared by synchronous and asynchronous transports."""
import math
import urllib.parse

from e6data_python_connector.exceptions import OAuthError

MAX_TOKEN_RESPONSE_BYTES = 65536


def validate_token_endpoint(url):
    """Require an HTTPS endpoint without embedded credentials or a fragment."""
    try:
        if not isinstance(url, str) or any(ord(c) <= 32 or ord(c) == 127 for c in url):
            raise ValueError
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.fragment or '#' in url):
            raise ValueError
        parsed.port
    except (ValueError, TypeError):
        raise ValueError('token_url must be an HTTPS URL without credentials or fragment.') from None
    return url


def validate_positive_timeout(value, name='timeout'):
    """Reject values that could disable a total time bound."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('{} must be finite and positive.'.format(name))
    try:
        value = float(value)
    except (ValueError, OverflowError):
        raise ValueError('{} must be finite and positive.'.format(name)) from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError('{} must be finite and positive.'.format(name))
    return value


def validate_token_response(payload, *, started_at, now, leeway):
    """Return the token and its conservative monotonic cache deadline.

    A token still valid but already inside its renewal interval is usable for
    this exchange only. Expiry starts before HTTP dispatch, never at receipt.
    """
    if not isinstance(payload, dict):
        raise OAuthError('Invalid OAuth token response shape.')
    token = payload.get('access_token')
    token_type = payload.get('token_type')
    lifetime = payload.get('expires_in')
    if (not isinstance(token, str) or not token or not token.isascii()
            or any(ord(c) <= 32 or ord(c) == 127 for c in token)):
        raise OAuthError('Invalid OAuth access_token.')
    if not isinstance(token_type, str) or token_type.lower() != 'bearer':
        raise OAuthError('OAuth token_type must be Bearer.')
    if isinstance(lifetime, bool) or not isinstance(lifetime, int) or lifetime <= 0:
        raise OAuthError('OAuth expires_in must be a positive integer.')
    try:
        expiry = started_at + lifetime
        reusable_until = expiry - leeway
        valid = all(math.isfinite(v) for v in (started_at, now, leeway, expiry, reusable_until))
    except (OverflowError, ValueError, TypeError):
        valid = False
    if not valid or leeway < 0 or now < started_at:
        raise OAuthError('Invalid OAuth expiry arithmetic.')
    if now >= expiry:
        raise OAuthError('OAuth token expired during exchange.')
    return token, reusable_until
