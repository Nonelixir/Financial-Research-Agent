"""Read-only public HTTPS retrieval with DNS-pinned transport and snapshots."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import ssl
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlsplit
from xml.etree import ElementTree


async def public_addresses(url: str) -> tuple[str, list[str]]:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
    ):
        raise ValueError("Only public HTTPS URLs on port 443, without credentials, are supported")
    host = parsed.hostname.encode("idna").decode()
    records = await asyncio.wait_for(
        asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM), timeout=10
    )
    addresses = list(dict.fromkeys(record[4][0] for record in records))
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Private, loopback, reserved and metadata addresses are forbidden")
    return host, addresses


class PinnedBackend:
    """httpcore connects only to validated IPs, preserving hostname for TLS SNI."""

    def __init__(self, host, addresses):
        from httpcore._backends.anyio import AnyIOBackend

        self.backend = AnyIOBackend()
        self.host, self.addresses = host, addresses

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if host != self.host or port != 443:
            raise ValueError("Unexpected outbound destination")
        last = None
        for address in self.addresses:
            try:
                return await self.backend.connect_tcp(
                    address,
                    port,
                    timeout,
                    local_address,
                    socket_options,
                )
            except OSError as exc:
                last = exc
        raise last or OSError("No destination")

    async def connect_unix_socket(self, *args, **kwargs):
        raise ValueError("Unix sockets are forbidden")

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


async def fetch_public(url: str, max_bytes: int = 2_097_152) -> tuple[str, str, str]:
    async with asyncio.timeout(45):
        return await _fetch_public(url, max_bytes)


async def _fetch_public(url: str, max_bytes: int) -> tuple[str, str, str]:
    import httpcore

    for _ in range(4):
        host, addresses = await public_addresses(url)
        async with (
            httpcore.AsyncConnectionPool(
                ssl_context=ssl.create_default_context(),
                network_backend=PinnedBackend(host, addresses),
            ) as pool,
            pool.stream(
                "GET",
                url,
                headers={"User-Agent": "FinancialResearch/0.1", "Accept-Encoding": "identity"},
                extensions={"timeout": {"connect": 10, "read": 15, "write": 15, "pool": 10}},
            ) as response,
        ):
            headers = {k.decode().lower(): v.decode() for k, v in response.headers}
            if response.status in {301, 302, 303, 307, 308}:
                if "location" not in headers:
                    raise ValueError("Redirect missing location")
                url = urljoin(url, headers["location"])
                continue
            if response.status != 200:
                raise ValueError(f"Public source returned HTTP {response.status}")
            if headers.get("content-encoding", "identity").lower() != "identity":
                raise ValueError("Compressed public responses are not supported")
            kind = headers.get("content-type", "").split(";")[0].lower()
            if kind not in {
                "text/html",
                "text/plain",
                "application/xhtml+xml",
                "application/xml",
                "text/xml",
                "application/rss+xml",
                "application/json",
            }:
                raise ValueError(f"Unsupported source content type: {kind}")
            content = bytearray()
            async for chunk in response.aiter_stream():
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise ValueError("Public document exceeds size limit")
            return url, bytes(content).decode("utf-8", errors="replace"), kind
    raise ValueError("Too many redirects")


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = 0
        self.in_title = False
        self.title = ""
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.ignored += 1
        if tag == "title":
            self.in_title = True
        if tag in {"p", "div", "br", "h1", "h2", "h3", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.ignored:
            self.ignored -= 1
        if tag == "title":
            self.in_title = False
        if tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.ignored:
            return
        if self.in_title:
            self.title += data
        else:
            self.parts.append(data)


def parse_page(body: str, kind: str) -> tuple[str, list[str]]:
    parser = PageParser()
    if "html" in kind:
        parser.feed(body)
        text = "".join(parser.parts)
    else:
        text = body
    paragraphs = []
    for line in text.splitlines():
        line = " ".join(line.split())
        if len(line) >= 30:
            paragraphs.extend(line[i : i + 1800] for i in range(0, len(line), 1600))
    return parser.title.strip(), paragraphs


class PublicWeb:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        with store.transaction() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS web_pages (
                    url TEXT PRIMARY KEY, title TEXT, content_sha256 TEXT, paragraphs_json TEXT,
                    fetched_at TEXT
                );
            """)

    async def read(self, url: str):
        url, body, kind = await fetch_public(url, self.settings.web_max_bytes)
        title, paragraphs = parse_page(body, kind)
        digest = sha256(body.encode()).hexdigest()
        self.store.put_source_cache(url, body, kind)
        fetched = datetime.now(UTC).isoformat()
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO web_pages VALUES (?,?,?,?,?)",
                (url, title, digest, json.dumps(paragraphs), fetched),
            )
        return {
            "url": url,
            "title": title,
            "content_sha256": digest,
            "paragraphs": paragraphs,
            "fetched_at": fetched,
        }

    async def search(self, query: str, limit: int):
        if not 1 <= len(query) <= 500 or not 1 <= limit <= 10:
            raise ValueError("query 1..500 characters and limit 1..10 required")
        url = "https://www.bing.com/search?" + urlencode({"format": "rss", "q": query})
        final, body, kind = await fetch_public(url, self.settings.web_max_bytes)
        self.store.put_source_cache(final, body, kind)
        root = ElementTree.fromstring(body)
        results = [
            {
                "title": item.findtext("title"),
                "url": item.findtext("link"),
                "snippet": item.findtext("description"),
            }
            for item in root.findall(".//item")
        ]
        return {
            "results": results[:limit],
            "provider": "bing_rss",
            "search_snapshot_sha256": sha256(body.encode()).hexdigest(),
            "warning": (
                "Experimental Bing RSS search; results may be irrelevant or incomplete. "
                "Inspect relevance and retry shorter/alternate queries. "
                "Snippets are leads, not registered evidence. Call read_web. "
                "Provider terms apply; not a licensed production search backend."
            ),
        }
