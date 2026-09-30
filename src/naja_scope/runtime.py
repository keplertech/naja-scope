# SPDX-License-Identifier: Apache-2.0
"""Serialize host and viewer access to the process-global raw naja universe."""
from functools import wraps
from threading import RLock

DESIGN_LOCK = RLock()
_listeners = []
_mutation_depth = 0


def add_change_listener(callback):
    _listeners.append(callback)


def serialized(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with DESIGN_LOCK:
            return fn(*args, **kwargs)
    return wrapped


def design_mutation(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        global _mutation_depth
        with DESIGN_LOCK:
            _mutation_depth += 1
            try:
                return fn(*args, **kwargs)
            finally:
                _mutation_depth -= 1
                # Failed loads can also leave a changed universe. Nested
                # re-elaboration sends just one notification on completion.
                if _mutation_depth == 0:
                    for callback in tuple(_listeners):
                        callback()
    return wrapped
