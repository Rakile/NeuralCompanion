from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from addons.web_intelligence.client import WebSearchError
from addons.web_intelligence.mcp_http import (
    McpHttpError,
    StreamableHttpMcpClient,
    tool_result_json,
    tool_result_text,
)
from addons.web_intelligence.models import SearchBundle, SearchResult


class McpSearxngSearchClient:
    provider_id = "mcp_searxng"

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = 8.0,
        search_language: str = "en",
        transport: StreamableHttpMcpClient | None = None,
    ) -> None:
        self._transport = transport or StreamableHttpMcpClient(
            endpoint,
            timeout_seconds=timeout_seconds,
        )
        self._search_language = str(search_language or "en").strip().lower() or "en"

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        include_images: bool = False,
        include_videos: bool = False,
    ) -> SearchBundle:
        normalized = _clean(query, 500)
        if not normalized:
            return SearchBundle(query="")
        count = max(1, min(10, int(max_results)))
        web = self._category(normalized, "general", "web", count, required=True)
        images = self._category(normalized, "images", "image", count) if include_images else ()
        videos = self._category(normalized, "videos", "video", count) if include_videos else ()
        return SearchBundle(query=normalized, web=web, images=images, videos=videos)

    def fetch_url(self, url: str) -> str:
        try:
            result = self._transport.call_tool("web_url_read", {"url": str(url)})
        except McpHttpError:
            return ""
        return tool_result_text(result)[:8_000].strip()

    def _category(
        self,
        query: str,
        category: str,
        kind: str,
        count: int,
        *,
        required: bool = False,
    ) -> tuple[SearchResult, ...]:
        try:
            result = self._transport.call_tool(
                "searxng_web_search",
                {
                    "query": query,
                    "num_results": count,
                    "categories": category,
                    "language": self._search_language,
                    "safesearch": "1",
                    "response_format": "json",
                    "result_detail": "full",
                },
            )
            payload = tool_result_json(result)
            if payload is None:
                raise WebSearchError("unrecognized search response (expected JSON).")
            if not isinstance(payload.get("results"), (list, tuple)):
                raise WebSearchError("unrecognized search response (missing results list).")
            parsed = _parse_searxng_results(payload, kind, count)
            if payload["results"] and not parsed:
                raise WebSearchError("unrecognized search response (no usable result URLs).")
            return parsed
        except (McpHttpError, WebSearchError) as exc:
            if required:
                raise WebSearchError(f"mcp-searxng search failed: {exc}") from exc
            return ()


class McpDuckDuckGoSearchClient:
    provider_id = "duckduckgo_mcp"

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = 8.0,
        region: str = "wt-wt",
        transport: StreamableHttpMcpClient | None = None,
    ) -> None:
        self._transport = transport or StreamableHttpMcpClient(
            endpoint,
            timeout_seconds=timeout_seconds,
        )
        self._region = str(region or "wt-wt").strip() or "wt-wt"

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        include_images: bool = False,
        include_videos: bool = False,
    ) -> SearchBundle:
        del include_images, include_videos
        normalized = _clean(query, 500)
        if not normalized:
            return SearchBundle(query="")
        try:
            result = self._transport.call_tool(
                "search",
                {
                    "query": normalized,
                    "max_results": max(1, min(10, int(max_results))),
                    "region": self._region,
                },
            )
        except McpHttpError as exc:
            raise WebSearchError(f"DuckDuckGo MCP search failed: {exc}") from exc
        response_text = tool_result_text(result)
        web = _parse_duckduckgo_text(response_text, max_results)
        if not web:
            if re.match(r"\s*(?:no results\b|found\s+0\s+(?:search\s+)?results\b)", response_text, re.IGNORECASE):
                # The provider's own empty-result notice can also mean bot detection.
                raise WebSearchError(
                    "DuckDuckGo MCP: no results reported (no matches or possible blocking; "
                    "the provider did not distinguish the cause)."
                )
            raise WebSearchError("DuckDuckGo MCP: unrecognized search response (no usable result URLs).")
        return SearchBundle(query=normalized, web=web)

    def fetch_url(self, url: str) -> str:
        try:
            result = self._transport.call_tool(
                "fetch_content",
                {"url": str(url), "start_index": 0, "max_length": 8_000},
            )
        except McpHttpError:
            return ""
        return tool_result_text(result)[:8_000].strip()


def _parse_searxng_results(
    payload: Mapping[str, Any],
    kind: str,
    limit: int,
) -> tuple[SearchResult, ...]:
    raw_results = payload.get("results")
    if not isinstance(raw_results, (list, tuple)):
        return ()
    parsed: list[SearchResult] = []
    for item in raw_results:
        if not isinstance(item, Mapping):
            continue
        url = _clean(item.get("url"), 2_000)
        if not _http_url(url):
            continue
        engines = item.get("engines")
        if isinstance(engines, (list, tuple)):
            source = ", ".join(_clean(value, 80) for value in engines if _clean(value, 80))
        else:
            source = _clean(item.get("engine"), 200)
        thumbnail = _clean(item.get("thumbnail"), 2_000)
        image_url = _clean(item.get("img_src") or item.get("image_url"), 2_000)
        parsed.append(
            SearchResult(
                kind=kind,
                title=_clean(item.get("title"), 300),
                url=url,
                snippet=_clean(item.get("content") or item.get("description"), 900),
                source=source,
                published=_clean(
                    item.get("publishedDate") or item.get("published_date"),
                    100,
                ),
                media_url=image_url if kind == "image" and _http_url(image_url) else "",
                thumbnail_url=thumbnail if _http_url(thumbnail) else "",
            )
        )
        if len(parsed) >= max(1, int(limit)):
            break
    return tuple(parsed)


def _parse_duckduckgo_text(text: str, limit: int) -> tuple[SearchResult, ...]:
    lines = [line.rstrip() for line in str(text or "").splitlines()]
    results: list[SearchResult] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        match = re.search(r"https?://[^\s<>\]\[)}]+", line)
        if match is None:
            continue
        url = match.group(0).rstrip(".,;:")
        if not _http_url(url) or url in seen:
            continue
        seen.add(url)
        title = _duckduckgo_title(lines, index, line, url)
        snippet_parts: list[str] = []
        for candidate in lines[index + 1 : index + 5]:
            if re.search(r"https?://", candidate):
                break
            cleaned = _strip_markdown(candidate)
            if cleaned and not cleaned.lower().startswith(("url:", "link:")):
                snippet_parts.append(cleaned)
        results.append(
            SearchResult(
                kind="web",
                title=title or urlsplit(url).hostname or url,
                url=url,
                snippet=_clean(" ".join(snippet_parts), 900),
                source=urlsplit(url).hostname or "DuckDuckGo",
            )
        )
        if len(results) >= max(1, int(limit)):
            break
    return tuple(results)


def _duckduckgo_title(lines: list[str], index: int, line: str, url: str) -> str:
    markdown_match = re.search(r"\[([^\]]+)\]\(" + re.escape(url) + r"\)", line)
    if markdown_match:
        return _clean(markdown_match.group(1), 300)
    same_line = _strip_markdown(line[: line.find(url)]).rstrip("-: ")
    if same_line and same_line.lower() not in {"url", "link"}:
        return _clean(same_line, 300)
    for candidate in reversed(lines[max(0, index - 3) : index]):
        cleaned = _strip_markdown(candidate)
        if cleaned and not cleaned.lower().startswith(("url:", "link:", "found ")):
            return _clean(cleaned, 300)
    return ""


def _strip_markdown(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"^\s*(?:URL|Link|Snippet|Description|Summary)\s*:\s*", "", text, flags=re.IGNORECASE).strip()


def _clean(value: object, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[: max(0, int(limit))]


def _http_url(value: object) -> bool:
    try:
        parsed = urlsplit(str(value or ""))
    except ValueError:
        return False
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)
