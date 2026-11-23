"""Fail-closed per-origin robots.txt cache."""
from __future__ import annotations

import asyncio
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from .fetch import USER_AGENT


class RobotsCache:
    def __init__(self, client: httpx.AsyncClient, *, user_agent: str = USER_AGENT) -> None:
        self.client = client
        self.user_agent = user_agent
        self._cache: dict[str, RobotFileParser | None] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname:
            return False
        origin = f'{parts.scheme}://{parts.netloc}'
        if origin not in self._cache:
            async with self._locks.setdefault(origin, asyncio.Lock()):
                if origin not in self._cache:
                    robots_url = f'{origin}/robots.txt'
                    try:
                        async with asyncio.timeout(10):
                            resp = await self.client.get(robots_url, follow_redirects=False)
                        if resp.status_code in (404, 410):
                            parser = RobotFileParser()
                            parser.parse([])
                            self._cache[origin] = parser
                        elif resp.status_code == 200:
                            parser = RobotFileParser()
                            parser.parse(resp.text.splitlines())
                            self._cache[origin] = parser
                        else:
                            self._cache[origin] = None  # network/server/redirect: deny safely
                    except (httpx.RequestError, asyncio.TimeoutError):
                        self._cache[origin] = None
        rule = self._cache[origin]
        return rule is not None and rule.can_fetch(self.user_agent, url)
