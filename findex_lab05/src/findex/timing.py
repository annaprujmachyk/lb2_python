"""Nonintrusive timing decorator; instrumented at DEBUG logging level."""

import logging
from collections.abc import Callable
from functools import wraps
from time import perf_counter

LOGGER = logging.getLogger(__name__)


def timed[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        begin = perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            LOGGER.debug("%s took %.3f ms", function.__qualname__, (perf_counter() - begin) * 1000)

    return wrapper
