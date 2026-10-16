"""Optional tracing owned and configured by the calling application."""

import asyncio
from contextlib import contextmanager
from functools import partial


def capture_context(operation, enabled):
    """Carry caller context into one owned worker without retaining it on a pool."""
    if not enabled:
        return operation
    from contextvars import copy_context
    return partial(copy_context().run, operation)


def trace_headers(enabled):
    """Propagate only standard traceparent, never arbitrary baggage or identity."""
    if not enabled:
        return {}
    try:
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
        carrier = {}
        TraceContextTextMapPropagator().inject(carrier)
        return {key: value for key, value in carrier.items() if key == 'traceparent'}
    except Exception:
        return {}


@contextmanager
def token_acquisition(enabled):
    """Trace an actual exchange; cache hits and waiting callers create no span."""
    span = activation = None
    if enabled:
        try:
            from opentelemetry import trace
            span = trace.get_tracer('e6data.oauth').start_span(
                'oauth.token.acquire', kind=trace.SpanKind.CLIENT,
                attributes={'oauth.operation': 'token.acquire',
                            'oauth.grant_type': 'client_credentials',
                            'oauth.transport': 'http',
                            'oauth.reported_source': 'python'})
            activation = trace.use_span(span, record_exception=False,
                                        set_status_on_exception=False)
            activation.__enter__()
        except Exception:
            # Instrumentation must never prevent token acquisition.
            activation = None
    outcome, reason = 'success', None
    try:
        yield
    except BaseException as error:
        if isinstance(error, asyncio.CancelledError):
            outcome, reason = 'cancelled', 'cancelled'
        else:
            outcome = 'error'
            reason = 'timeout' if isinstance(error, TimeoutError) else 'exchange_failed'
        raise
    finally:
        if activation is not None:
            try:
                activation.__exit__(None, None, None)
            except Exception:
                pass
        if span is not None:
            try:
                span.set_attribute('oauth.outcome', outcome)
                if reason is not None:
                    span.set_attribute('oauth.reason', reason)
                    span.set_status(trace.StatusCode.ERROR)
                span.end()
            except Exception:
                pass
