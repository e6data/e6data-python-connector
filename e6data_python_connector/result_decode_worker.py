"""Import-safe entry point for the connector's private decode processes."""

import decimal
import multiprocessing

WORKER_PREFIX = 'e6-result-decode-'


def is_decode_worker():
    """Identify only processes started by our explicit spawn runtime."""
    return multiprocessing.current_process().name.startswith(WORKER_PREFIX)


def decimal_context_signature():
    """Return value-affecting settings as plain immutable metadata."""
    context = decimal.getcontext()
    return (context.prec, context.rounding, context.Emin, context.Emax,
            context.capitals, context.clamp,
            tuple(sorted((signal.__name__, enabled) for signal, enabled in context.traps.items())))


def _decimal_flags():
    return tuple(signal.__name__ for signal, raised in decimal.getcontext().flags.items() if raised)


def decode_worker(channel):
    """Decode one serialized chunk at a time; receive no connector state."""
    # Imports happen after spawn establishes the owned process name. Package
    # imports therefore cannot allocate the normal cluster-manager semaphore.
    from e6data_python_connector.result_batch import decode_result_batches

    try:
        channel.send(('ready', decimal_context_signature()))
        while True:
            job = channel.recv()
            if job is None:
                return
            token, index, columns, payload = job
            decimal.getcontext().clear_flags()
            try:
                chunks = decode_result_batches(columns, [payload])
                channel.send(('result', token, index, chunks[0] if chunks else None, _decimal_flags()))
            except Exception as error:
                # Exception text can contain result data. Only a type name is
                # returned, and no partial chunk is returned after an error.
                channel.send(('error', token, index, type(error).__name__, _decimal_flags()))
    except (EOFError, OSError):
        return
    finally:
        channel.close()
