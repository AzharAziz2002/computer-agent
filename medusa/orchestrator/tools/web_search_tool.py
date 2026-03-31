from medusa.orchestrator.tools.web_search_schema import WebSearch
from medusa.orchestrator.registry.views import ToolResult
from medusa.tool import Tool
from urllib.parse import urlparse
from html import unescape
import httpx
import time
import os

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
CACHE_TTL = 900  # 15 minutes
MAX_CACHE = 100
_cache: dict[str, tuple[float, str]] = {}


@Tool('Web Search', args_schema=WebSearch)
async def web_search(query: str, count: int = 5, country: str = None,
                     search_lang: str = None, freshness: str = None, **kwargs) -> str:
    '''
    Search the web using Brave Search and return relevant results.

    Use this tool to find current information, research topics, look up documentation,
    or answer questions that require up-to-date web data. Returns titles, URLs, and
    descriptions for each result.

    Prefer this over browser tool when you only need to find information or URLs.
    Use browser tool when you need to interact with a webpage (click, type, navigate).
    '''
    api_key = os.environ.get('BRAVE_API_KEY', '').strip()
    if not api_key:
        return ToolResult(is_success=False, error="BRAVE_API_KEY not set in environment. Add it to .env file.")

    # Cache check (delete expired entries on read)
    cache_key = f"{query}|{count}|{country}|{search_lang}|{freshness}".lower()
    if cache_key in _cache:
        expiry, cached = _cache[cache_key]
        if time.time() < expiry:
            return cached
        del _cache[cache_key]

    params = {"q": query, "count": count}
    if country:
        params["country"] = country
    if search_lang:
        params["search_lang"] = search_lang
    if freshness:
        params["freshness"] = freshness

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                BRAVE_ENDPOINT,
                params=params,
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        return ToolResult(is_success=False, error=f"Brave API error: {e.response.status_code} {e.response.text[:200]}")
    except (httpx.RequestError, ValueError) as e:
        return ToolResult(is_success=False, error=f"Request failed: {e}")

    results = data.get("web", {}).get("results", [])
    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        title = unescape(r.get("title", ""))
        url = r.get("url", "")
        desc = unescape(r.get("description", ""))
        age = r.get("age", "")
        entry = f"{i}. {title}\n   {url}\n   {desc}"
        if age:
            entry += f"\n   Published: {age}"
        lines.append(entry)

    output = "\n\n".join(lines)

    # Cache store (FIFO eviction)
    if len(_cache) >= MAX_CACHE:
        oldest = next(iter(_cache))
        del _cache[oldest]
    _cache[cache_key] = (time.time() + CACHE_TTL, output)

    return output
