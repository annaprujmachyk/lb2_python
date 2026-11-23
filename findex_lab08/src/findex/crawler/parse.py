"""Standard-library HTML extraction and canonical URL handling."""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


def canonicalize(url: str) -> str:
    p = urlsplit(url.strip())
    if p.scheme.lower() not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError(f'Unsupported URL: {url!r}')
    host = p.hostname.lower().rstrip('.')
    try:
        port = p.port
    except ValueError as exc:
        raise ValueError(f'Bad port: {url}') from exc
    netloc = f'[{host}]' if ':' in host else host
    if port and not (p.scheme.lower() == 'https' and port == 443 or p.scheme.lower() == 'http' and port == 80):
        netloc += f':{port}'
    path = p.path or '/'
    if len(path) > 1:
        path = path.rstrip('/')
    query = urlencode(sorted(parse_qsl(p.query, keep_blank_values=True)))
    return urlunsplit((p.scheme.lower(), netloc, path, query, ''))


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.text_parts: list[str] = []
        self.title_parts: list[str] = []
        self.hidden = 0
        self.in_title = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.hidden += 1
        if tag == 'title':
            self.in_title += 1
        if tag == 'a':
            href = dict(attrs).get('href')
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.hidden = max(0, self.hidden-1)
        if tag == 'title':
            self.in_title = max(0, self.in_title-1)

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if not self.hidden and not self.in_title:
            self.text_parts.append(data)

    def extract(self, base: str) -> tuple[str, str, list[str]]:
        links = []
        for href in self.links:
            try:
                links.append(canonicalize(urljoin(base, href)))
            except ValueError:
                continue
        return (' '.join(' '.join(self.title_parts).split()),
                ' '.join(' '.join(self.text_parts).split()), links)
