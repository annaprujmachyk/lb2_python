"""Offline crawler regression tests. Real sites are never accessed."""
import asyncio
import json
from pathlib import Path

import httpx

from findex.crawler.fetch import fetch, retry_delay, USER_AGENT
from findex.crawler.robots import RobotsCache
from findex.crawler.parse import canonicalize
from findex.crawler.crawl import crawl, CrawlStats
from findex.crawler.command import run_crawl


def run(coro):
    return asyncio.run(coro)


def test_canonical():
    assert canonicalize('HTTPS://Example.COM:443/a/?z=1&a=2#frag') == 'https://example.com/a?a=2&z=1'
    assert canonicalize('https://EXAMPLE.com') == 'https://example.com/'
    assert canonicalize('http://example.com:80/hello/') == 'http://example.com/hello'


def test_invalid_urls():
    import pytest
    for url in ('file:///tmp/a', 'javascript:alert(1)', 'https://a:b@example.com'):
        with pytest.raises(ValueError):
            canonicalize(url)


def test_retry_after():
    assert retry_delay('2') == 2
    assert retry_delay('bogus') is None
    assert retry_delay('-10') == 0


def test_fetch_retry_and_no_retry_on_404():
    async def inner():
        calls = []
        waits = []
        def handler(req):
            calls.append(str(req.url))
            if req.url.path == '/missing':
                return httpx.Response(404)
            if len(calls) == 1:
                return httpx.Response(429, headers={'Retry-After': '3'})
            return httpx.Response(200, text='ok', headers={'content-type': 'text/html'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async def sleeper(n): waits.append(n)
            response = await fetch(client, 'https://site.test/', sleep=sleeper)
            assert response.status == 200 and response.attempts == 2
            assert waits[0] >= 3
            missing = await fetch(client, 'https://site.test/missing', sleep=sleeper)
            assert missing.status == 404 and missing.attempts == 1
    run(inner())


def test_fetch_503_exhaustion():
    async def inner():
        attempts = 0
        def handler(req):
            nonlocal attempts
            attempts += 1
            return httpx.Response(503)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async def sleeper(n): pass
            response = await fetch(client, 'https://site.test/', retries=2, sleep=sleeper)
            assert response.status == 503 and response.attempts == 3 and attempts == 3
    run(inner())


def test_robots_disallow_and_cache():
    async def inner():
        calls = 0
        def handler(req):
            nonlocal calls
            calls += 1
            return httpx.Response(200, text='User-agent: *\nDisallow: /private\n')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            robots = RobotsCache(client)
            assert await robots.allowed('https://a.test/public')
            assert not await robots.allowed('https://a.test/private')
            assert calls == 1
    run(inner())


def test_robots_fail_closed():
    async def inner():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(500))) as client:
            assert not await RobotsCache(client).allowed('https://example.test/')
    run(inner())


def mock_site(n=8):
    def handler(req):
        if req.url.path == '/robots.txt':
            return httpx.Response(200, text='User-agent: *\nDisallow: /private\n')
        page = int(req.url.path.strip('/') or '0') if req.url.path.strip('/').isdigit() else -1
        if page < 0 or page >= n:
            return httpx.Response(404)
        links = ''.join(f'<a href="/{i}">Link {i}</a>' for i in range(n))
        return httpx.Response(200, headers={'content-type':'text/html'}, text=f'<html><title>Title {page}</title><body>Hello {page}{links}<a href="https://other.test/">offsite</a><a href="/private">private</a></body></html>')
    return httpx.MockTransport(handler)


def test_crawl_limits_and_no_duplicates():
    async def inner():
        stats = CrawlStats()
        log = []
        async with httpx.AsyncClient(transport=mock_site()) as client:
            pages = [p async for p in crawl(['https://site.test/0', 'https://site.test/0'], max_pages=5,
                 concurrency=4, per_host=2, delay=0, client=client, stats=stats, status_callback=log.append)]
        assert len(pages) <= 5
        assert len({p.url for p in pages}) == len(pages)
        assert all(p.title.startswith('Title') for p in pages)
        assert all(p.url.startswith('https://site.test/') for p in pages)
        assert stats.fetched == len(pages)
        assert len(log) <= 5
    run(inner())


def test_crawl_allowed_domains():
    async def inner():
        async with httpx.AsyncClient(transport=mock_site()) as client:
            pages = [p async for p in crawl(['https://site.test/0'], max_pages=3,
                       allowed_domains=['other.test'], client=client)]
            return pages
    import pytest
    with pytest.raises(ValueError):
        run(inner())


def test_crawl_zero():
    async def inner():
        return [p async for p in crawl(['https://site.test/0'], max_pages=0)]
    assert run(inner()) == []


def test_stream_output_and_cli_compat(tmp_path):
    async def inner():
        async with httpx.AsyncClient(transport=mock_site(3)) as client:
            pages = [p async for p in crawl(['https://site.test/0'], max_pages=3, delay=0,
                          concurrency=3, client=client)]
        assert pages
        from findex.crawler.crawl import page_json
        for p in pages:
            assert json.loads(page_json(p))['text'].startswith('Hello')
    run(inner())


def test_async_debug_mode():
    async def inner():
        async with httpx.AsyncClient(transport=mock_site(2)) as client:
            return [p async for p in crawl(['https://site.test/0'], max_pages=2,
                                          delay=0, client=client)]
    result = asyncio.run(inner(), debug=True)
    assert len(result) == 2
