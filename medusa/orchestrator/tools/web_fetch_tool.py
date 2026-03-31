from medusa.orchestrator.tools.web_fetch_schema import WebFetch
from medusa.orchestrator.registry.views import ToolResult
from medusa.tool import Tool
from urllib.parse import urlparse
from readability import Document
from markdownify import markdownify
import httpx
import ipaddress
import os
import re
import socket
import time

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
FIRECRAWL_ENDPOINT = "https://api.firecrawl.dev/v2/scrape"
MAX_DOWNLOAD = 2 * 1024 * 1024  # 2MB
CACHE_TTL = 900  # 15 minutes
MAX_CACHE = 100
_cache: dict[str, tuple[float, str]] = {}

ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal")
FETCHABLE_CONTENT_TYPES = {"text/html", "text/plain", "text/markdown", "application/xhtml+xml", "application/xml", "text/xml"}

PRIVATE_NETS = [
    ipaddress.ip_network("0.0.0.0/8"),       # current network
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),    # shared address space (CGNAT)
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
    ipaddress.ip_network("fc00::/7"),         # IPv6 unique local
]


def _is_url_safe(url: str) -> str | None:
    """Validate URL scheme, hostname, and IP. Returns error message or None if safe."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return f"URL scheme '{parsed.scheme}' not allowed (only http/https)"
    hostname = parsed.hostname
    if not hostname:
        return "Invalid URL: no hostname"
    hostname_lower = hostname.lower()
    if hostname_lower in BLOCKED_HOSTNAMES:
        return f"URL blocked: {hostname} is a blocked hostname"
    if any(hostname_lower.endswith(s) for s in BLOCKED_SUFFIXES):
        return f"URL blocked: {hostname} matches blocked suffix"
    try:
        for info in socket.getaddrinfo(hostname, None):
            addr = ipaddress.ip_address(info[4][0])
            if any(addr in net for net in PRIVATE_NETS):
                return f"URL blocked: {hostname} resolves to private address"
    except (socket.gaierror, ValueError):
        return f"URL blocked: cannot resolve {hostname}"
    return None


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting, returning plain text."""
    text = re.sub(r'#{1,6}\s+', '', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)
    return text.strip()


def _check_content_type(content_type: str) -> str | None:
    """Extract base content type and check if it's fetchable. Returns base type or None."""
    base = content_type.split(";")[0].strip().lower()
    if not base:
        return "text/html"  # assume HTML if missing
    for allowed in FETCHABLE_CONTENT_TYPES:
        if base == allowed:
            return base
    return None


async def _fetch_readability(url: str, extract_mode: str) -> tuple[str, str]:
    """Fetch URL and extract content using readability-lxml. Returns (content, title)."""
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, max_redirects=3) as client:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()

        ct = resp.headers.get("content-type", "")
        base_ct = _check_content_type(ct)
        if base_ct is None:
            raise ValueError(f"Unsupported content type: {ct.split(';')[0].strip()}")

        if len(resp.content) > MAX_DOWNLOAD:
            raise ValueError("Response too large (>2MB)")

        # Re-check SSRF: final URL after redirects may differ from original
        final_hostname = urlparse(str(resp.url)).hostname
        if final_hostname:
            error = _is_url_safe(str(resp.url))
            if error:
                raise ValueError(f"Redirect target blocked: {error}")

        html = resp.text

    # If response is already markdown (e.g. Cloudflare llms.txt)
    if base_ct == "text/markdown":
        return html, ""

    # Plain text — return as-is
    if base_ct == "text/plain":
        return html, ""

    doc = Document(html)
    title = doc.title() or ""
    article_html = doc.summary()

    if not article_html or len(article_html.strip()) < 50:
        raise ValueError("Readability extracted no meaningful content")

    content = markdownify(article_html, strip=['img', 'script', 'style'])
    if extract_mode == "text":
        content = _strip_markdown(content)

    return content.strip(), title


async def _fetch_firecrawl(url: str, api_key: str) -> tuple[str, str]:
    """Fetch URL content via Firecrawl API. Returns (content, title)."""
    async with httpx.AsyncClient(timeout=35) as client:
        resp = await client.post(
            FIRECRAWL_ENDPOINT,
            json={
                "url": url,
                "formats": ["markdown"],
                "onlyMainContent": True,
                "timeout": 30000,
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()

    content = data.get("data", {}).get("markdown", "")
    title = data.get("data", {}).get("metadata", {}).get("title", "")
    if not content:
        raise ValueError("Firecrawl returned no content")
    return content, title


@Tool('Web Fetch', args_schema=WebFetch)
async def web_fetch(url: str, extract_mode: str = 'markdown',
                    max_chars: int = 50000, **kwargs) -> str:
    '''
    Fetch a webpage and extract its content as clean markdown or plain text.

    Use this tool to read articles, documentation, blog posts, or any web page content
    without needing to open a browser. Returns the main content with ads, navigation,
    and sidebars stripped out.

    Use web_search first to find URLs, then web_fetch to read their content.
    Use browser tool instead when you need to interact with a page (login, click, fill forms).
    '''
    # Validate URL: scheme, hostname, blocked names, private IPs
    error = _is_url_safe(url)
    if error:
        return ToolResult(is_success=False, error=error)

    # Cache check (delete expired entries on read)
    cache_key = f"{url}|{extract_mode}|{max_chars}"
    if cache_key in _cache:
        expiry, cached = _cache[cache_key]
        if time.time() < expiry:
            return cached
        del _cache[cache_key]

    content, title, extractor = "", "", ""

    # Step 1: Readability (free, local)
    try:
        content, title = await _fetch_readability(url, extract_mode)
        extractor = "readability"
    except Exception:
        pass

    # Step 2: Firecrawl fallback (commercial, only if readability failed)
    if not content:
        firecrawl_key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
        if firecrawl_key:
            try:
                content, title = await _fetch_firecrawl(url, firecrawl_key)
                extractor = "firecrawl"
                if extract_mode == "text":
                    content = _strip_markdown(content)
            except Exception:
                pass

    if not content:
        return ToolResult(is_success=False, error=f"Failed to extract content from {url}")

    # Truncate if needed
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars] + "\n\n[Content truncated]"

    # Build output
    header = f"URL: {url}"
    if title:
        header += f"\nTitle: {title}"
    header += f"\nExtractor: {extractor}"
    output = f"{header}\n\n{content}"

    # Cache store (FIFO eviction)
    if len(_cache) >= MAX_CACHE:
        oldest = next(iter(_cache))
        del _cache[oldest]
    _cache[cache_key] = (time.time() + CACHE_TTL, output)

    return output
