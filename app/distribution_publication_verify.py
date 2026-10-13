"""Bounded public-page checks. Never use platform sessions or follow redirects."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import ipaddress
import re
import socket
import ssl
import time
import threading
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit

MAX_BYTES = 2_000_000
DEADLINE_SECONDS = 10
MAX_PARSE_DEPTH = 128
MAX_PARSE_EVENTS = 20_000
PARSE_SECONDS = 0.25
MEDIA_TAGS = frozenset(('img', 'svg', 'image', 'video', 'audio', 'iframe', 'object', 'embed', 'canvas', 'picture'))
_fetch_slots = threading.BoundedSemaphore(4)
_fetch_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='publication-public-read')


@dataclass(frozen=True)
class PublicPage:
    status: int
    media_type: str
    body: bytes


def fixed_target(platform, url):
    value = urlsplit(url)
    host = 'mp.weixin.qq.com' if platform == 'wechat-article' else 'www.xiaohongshu.com'
    pattern = r'/s/[A-Za-z0-9_-]+' if platform == 'wechat-article' else r'/explore/[a-f0-9]+'
    if (platform not in ('wechat-article', 'xiaohongshu-image') or value.scheme != 'https'
        or value.netloc != host or value.query or value.fragment or not re.fullmatch(pattern, value.path)):
        raise ValueError('Invalid public target')
    return host, value.path


def public_addresses(host):
    # Resolve once, reject the entire answer if any address is private, and pin
    # the TCP connection to these addresses while preserving hostname TLS/SNI.
    answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
    if not addresses or len(addresses) > 32 or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError('Non-public target')
    return addresses


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, addresses, deadline):
        super().__init__(host, timeout=DEADLINE_SECONDS, context=ssl.create_default_context())
        self.addresses, self.deadline = addresses, deadline

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Public page deadline')
        return remaining

    def connect(self):
        for address in self.addresses:
            raw = None
            try:
                raw = socket.create_connection((address, 443), timeout=self.remaining())
                raw.settimeout(self.remaining())
                self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
                self.sock.settimeout(self.remaining())
                return
            except (OSError, TimeoutError):
                if raw:
                    raw.close()
        raise OSError('Public page unavailable')


def fetch_public_page(platform, url):
    host, path = fixed_target(platform, url)
    deadline = time.monotonic() + DEADLINE_SECONDS
    connection = PinnedHTTPSConnection(host, public_addresses(host), deadline)
    try:
        connection.request('GET', path, headers={
            'Accept': 'text/html', 'Accept-Encoding': 'identity',
            'User-Agent': 'Snipers-Publication-Check/1.0', 'Connection': 'close',
        })
        connection.sock.settimeout(connection.remaining())
        wire = connection.sock
        response = connection.getresponse()
        media = response.getheader('Content-Type', '').split(';')[0].strip().lower()
        if response.status != 200:
            return PublicPage(response.status, media, b'')
        if media not in ('text/html', 'application/xhtml+xml') or response.getheader('Content-Encoding', 'identity') != 'identity':
            raise ValueError('Unsupported public page')
        length = response.getheader('Content-Length')
        if length and (not length.isdecimal() or int(length) > MAX_BYTES):
            raise ValueError('Public page too large')
        chunks, size = [], 0
        while True:
            wire.settimeout(connection.remaining())
            chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError('Public page too large')
            chunks.append(chunk)
        if length and size != int(length):
            raise ValueError('Incomplete public page')
        return PublicPage(200, media, b''.join(chunks))
    finally:
        connection.close()


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.fields = {'activity-name': [], 'js_content': []}
        self.counts = {'activity-name': 0, 'js_content': 0}
        self.text = []
        self.images = False
        self.content_images = False
        self.scripts = []
        self.events = 0
        self.deadline = time.monotonic() + PARSE_SECONDS

    def budget(self):
        self.events += 1
        if self.events > MAX_PARSE_EVENTS or time.monotonic() > self.deadline:
            raise ValueError('Public page parsing budget exceeded')

    def feed(self, data):
        if len(data) > MAX_BYTES:
            raise ValueError('Public page parsing size exceeded')
        self.budget()
        super().feed(data)
        self.budget()

    def handle_starttag(self, tag, attrs):
        self.budget()
        attrs = dict(attrs)
        parent = self.stack[-1] if self.stack else (None, None, False)
        field = attrs.get('id') if attrs.get('id') in self.fields else parent[1]
        if attrs.get('id') in self.counts:
            self.counts[attrs['id']] += 1
        hidden = (parent[2] or tag in ('script', 'style', 'noscript', 'template')
                  or 'hidden' in attrs or attrs.get('aria-hidden') == 'true'
                  or bool(re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden)', attrs.get('style', ''), re.I)))
        if tag in MEDIA_TAGS and not hidden:
            self.images = True
            if field == 'js_content': self.content_images = True
        if tag not in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'):
            if len(self.stack) >= MAX_PARSE_DEPTH:
                raise ValueError('Public page nesting exceeded')
            self.stack.append((tag, field, hidden))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'):
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        self.budget()
        for index in range(len(self.stack)-1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.budget()
        tag, field, hidden = self.stack[-1] if self.stack else (None, None, False)
        if tag == 'script' and field is None:
            self.scripts.append(data)
        if not hidden:
            self.text.append(data)
            if field:
                self.fields[field].append(data)

    def handle_comment(self, data):
        self.budget()

    def handle_decl(self, decl):
        self.budget()

    def unknown_decl(self, data):
        self.budget()

    def handle_pi(self, data):
        self.budget()


def normalized(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFC', text))


def content_text(body):
    parser = PageText()
    parser.feed(body)
    parser.close()
    return normalized(''.join(parser.text)), parser.images


def inspect_page(platform, page, content, expected_identity):
    if page.status != 200:
        return {'status': 'needs-human', 'code': 'PAGE_UNAVAILABLE'}
    if platform != 'wechat-article':
        return {'status': 'needs-human', 'code': 'CHANNEL_REQUIRES_HUMAN'}
    if page.media_type not in ('text/html', 'application/xhtml+xml') or len(page.body) > MAX_BYTES:
        return {'status': 'needs-human', 'code': 'PAGE_UNAVAILABLE'}
    try:
        html = page.body.decode('utf-8', errors='strict')
        parser = PageText()
        parser.feed(html)
        parser.close()
        body, embedded_images = content_text(content['body'])
    except (UnicodeError, ValueError):
        return {'status': 'needs-human', 'code': 'PAGE_UNAVAILABLE'}
    if any(count != 1 for count in parser.counts.values()):
        return {'status': 'needs-human', 'code': 'PAGE_LAYOUT_UNVERIFIED'}
    if not body or normalized(''.join(parser.fields['activity-name'])) != normalized(content['title']) or normalized(''.join(parser.fields['js_content'])) != body:
        return {'status': 'needs-human', 'code': 'CONTENT_MISMATCH'}
    identities = re.findall(r'^\s*var\s+user_name\s*=\s*["\'](gh_[A-Za-z0-9_]+)["\']\s*;\s*$', '\n'.join(parser.scripts), re.M)
    if len(identities) != 1 or identities[0] != expected_identity:
        return {'status': 'needs-human', 'code': 'ACCOUNT_UNVERIFIED'}
    if content['assets'] or embedded_images or parser.content_images:
        return {'status': 'needs-human', 'code': 'ASSETS_REQUIRE_HUMAN'}
    # Static HTML cannot prove CSS visibility, rendered media, or editor output.
    # Keep the text/account observation as an initial check, never a final seal.
    return {'status': 'needs-human', 'code': 'PUBLIC_TEXT_AND_ACCOUNT_MATCHED',
            'observed_digest': hashlib.sha256((normalized(content['title']) + '\n' + body).encode()).hexdigest()}


async def verify_publication(platform, url, content, expected_identity):
    fixed_target(platform, url)
    if platform != 'wechat-article':
        return {'status': 'needs-human', 'code': 'CHANNEL_REQUIRES_HUMAN'}
    if not _fetch_slots.acquire(blocking=False):
        return {'status': 'needs-human', 'code': 'PAGE_UNAVAILABLE'}
    def bounded_fetch():
        try: return fetch_public_page(platform, url)
        finally: _fetch_slots.release()
    try:
        # DNS resolution also runs in the bounded worker. The outer deadline
        # ensures a stalled resolver cannot hold an application request open.
        future = _fetch_pool.submit(bounded_fetch)
    except RuntimeError:
        _fetch_slots.release()
        return {'status': 'needs-human', 'code': 'PAGE_UNAVAILABLE'}
    try:
        page = await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)), DEADLINE_SECONDS + 1)
    except (OSError, ValueError, TimeoutError, http.client.HTTPException):
        return {'status': 'needs-human', 'code': 'PAGE_UNAVAILABLE'}
    return inspect_page(platform, page, content, expected_identity)
