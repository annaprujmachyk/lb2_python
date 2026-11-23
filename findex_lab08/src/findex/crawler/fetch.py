"""Bounded asynchronous HTTP fetch with retries, timeouts and status records."""
from __future__ import annotations

import asyncio
import email.utils
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import httpx

LOG = logging.getLogger(__name__)
USER_AGENT = 'findex-student-crawler/0.6 (+https://github.com/rmalkevy/Programming-Practice-Projects)'


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str
    status: int | None
    body: bytes
    elapsed: float
    attempts: int
    error: str | None = None
    content_type: str = ''

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300


def retry_delay(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, min(120.0, float(value)))
    except ValueError:
        try:
            date = email.utils.parsedate_to_datetime(value)
            return max(0.0, min(120.0, (date - datetime.now(timezone.utc)).total_seconds()))
        except (ValueError, TypeError, OverflowError):
            return None


async def fetch(
    client: httpx.AsyncClient, url: str, *, timeout: float = 10.0,
    retries: int = 3, sleep: Callable[[float], object] | None = None,
) -> FetchResult:
    """Return response metadata. Only transient failures are retried.

    `retries` counts additional attempts, not the initial attempt.
    """
    if timeout <= 0 or retries < 0:
        raise ValueError('timeout must be positive and retries nonnegative')
    start = time.perf_counter()
    last_status: int | None = None
    last_error: str | None = None
    pause = sleep or asyncio.sleep
    for attempt in range(retries + 1):
        response: httpx.Response | None = None
        try:
            async with asyncio.timeout(timeout):
                response = await client.get(url, follow_redirects=False)
            last_status = response.status_code
            if response.status_code not in (429, 500, 502, 503, 504):
                return FetchResult(url, response.status_code, response.content, time.perf_counter()-start,
                                   attempt+1, content_type=response.headers.get('content-type', ''))
            last_error = f'HTTP {response.status_code}'
        except (httpx.RequestError, asyncio.TimeoutError, httpx.TooManyRedirects) as exc:
            last_error = type(exc).__name__ + ': ' + str(exc)
            LOG.warning('fetch %s attempt %d: %s', url, attempt+1, last_error)
        if attempt < retries:
            backoff = min(8.0, 0.2 * (2**attempt)) + random.uniform(0, 0.1)
            header_wait = retry_delay(response.headers.get('retry-after')) if response is not None and response.status_code == 429 else None
            await pause(max(backoff, header_wait or 0))  # type: ignore[misc]
    return FetchResult(url, last_status, b'', time.perf_counter()-start, retries+1, last_error)
