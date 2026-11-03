from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from html.parser import HTMLParser
from typing import Any

from addons.web_intelligence.models import SearchBundle, SearchResult


BRAVE_API_ROOT = "https://api.search.brave.com/res/v1"
USER_AGENT = "NeuralCompanion-WebIntelligence/0.1"


class WebSearchError(RuntimeError):
    """A safe, user-displayable web search failure."""


class BraveSearchClient:
    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 5.0,
        country: str = "",
        search_language: str = "en",
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        key = str(api_key or "").strip()
        if not key:
            raise ValueError("A Brave Search API key is required.")
        self._api_key = key
        self._timeout_seconds = max(1.0, min(15.0, float(timeout_seconds)))
        self._country = str(country or "").strip().upper()
        self._search_language = str(search_language or "en").strip().lower() or "en"
        self._opener = opener

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
        web_payload = self._get_json("web/search", normalized, count)
        image_payload = self._optional_json("images/search", normalized, count) if include_images else {}
        video_payload = self._optional_json("videos/search", normalized, count) if include_videos else {}
        return SearchBundle(
            query=normalized,
            web=_parse_web_results(web_payload, count),
            images=_parse_image_results(image_payload, count),
            videos=_parse_video_results(video_payload, count),
        )

    def _get_json(self, endpoint: str, query: str, count: int) -> Mapping[str, Any]:
        parameters = {
            "q": query,
            "count": str(count),
            "safesearch": "moderate",
            "search_lang": self._search_language,
        }
        if self._country:
            parameters["country"] = self._country
        url = f"{BRAVE_API_ROOT}/{endpoint}?{urllib.parse.urlencode(parameters)}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": USER_AGENT,
                "X-Subscription-Token": self._api_key,
            },
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                payload = response.read(2_000_001)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise WebSearchError("Brave Search rejected the configured API key.") from exc
            if exc.code == 429:
                raise WebSearchError("Brave Search rate limit reached.") from exc
            raise WebSearchError(f"Brave Search returned HTTP {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise WebSearchError("Brave Search is temporarily unavailable.") from exc
        if len(payload) > 2_000_000:
            raise WebSearchError("Brave Search returned an unexpectedly large response.")
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebSearchError("Brave Search returned invalid JSON.") from exc
        return decoded if isinstance(decoded, Mapping) else {}

    def _optional_json(self, endpoint: str, query: str, count: int) -> Mapping[str, Any]:
        try:
            return self._get_json(endpoint, query, count)
        except WebSearchError:
            # Media lookup is additive. Preserve useful web evidence when an
            # image or video endpoint is temporarily unavailable.
            return {}


def _parse_web_results(payload: Mapping[str, Any], limit: int) -> tuple[SearchResult, ...]:
    web = payload.get("web")
    raw_results = web.get("results") if isinstance(web, Mapping) else ()
    return tuple(
        SearchResult(
            kind="web",
            title=_clean(item.get("title"), 300),
            url=_clean(item.get("url"), 2_000),
            snippet=_clean(item.get("description"), 900),
            source=_clean(item.get("profile", {}).get("long_name"), 200)
            if isinstance(item.get("profile"), Mapping)
            else "",
            published=_clean(item.get("age") or item.get("page_age"), 100),
        )
        for item in _mapping_items(raw_results, limit)
        if _http_url(item.get("url"))
    )


def _parse_image_results(payload: Mapping[str, Any], limit: int) -> tuple[SearchResult, ...]:
    results = []
    for item in _mapping_items(payload.get("results"), limit):
        properties = item.get("properties")
        thumbnail = item.get("thumbnail")
        page_url = _clean(item.get("url") or item.get("source"), 2_000)
        media_url = (
            _clean(properties.get("url"), 2_000)
            if isinstance(properties, Mapping)
            else ""
        )
        thumbnail_url = (
            _clean(thumbnail.get("src"), 2_000)
            if isinstance(thumbnail, Mapping)
            else ""
        )
        if not _http_url(page_url) and not _http_url(media_url):
            continue
        results.append(
            SearchResult(
                kind="image",
                title=_clean(item.get("title"), 300),
                url=page_url if _http_url(page_url) else media_url,
                source=_clean(item.get("source"), 200),
                media_url=media_url if _http_url(media_url) else "",
                thumbnail_url=thumbnail_url if _http_url(thumbnail_url) else "",
            )
        )
    return tuple(results)


def _parse_video_results(payload: Mapping[str, Any], limit: int) -> tuple[SearchResult, ...]:
    results = []
    for item in _mapping_items(payload.get("results"), limit):
        url = _clean(item.get("url"), 2_000)
        if not _http_url(url):
            continue
        thumbnail = item.get("thumbnail")
        video = item.get("video")
        creator = item.get("creator")
        source = ""
        if isinstance(creator, Mapping):
            source = _clean(creator.get("name"), 200)
        if not source:
            source = _clean(item.get("source"), 200)
        duration = _clean(video.get("duration"), 60) if isinstance(video, Mapping) else ""
        snippet = _clean(item.get("description"), 700)
        if duration:
            snippet = f"{snippet} Duration: {duration}.".strip()
        results.append(
            SearchResult(
                kind="video",
                title=_clean(item.get("title"), 300),
                url=url,
                snippet=snippet,
                source=source,
                published=_clean(item.get("age") or item.get("page_age"), 100),
                thumbnail_url=(
                    _clean(thumbnail.get("src"), 2_000)
                    if isinstance(thumbnail, Mapping)
                    and _http_url(thumbnail.get("src"))
                    else ""
                ),
            )
        )
    return tuple(results)


class _TextExtractor(HTMLParser):
    _BLOCK_TAGS = frozenset(
        {"article", "br", "div", "h1", "h2", "h3", "h4", "li", "main", "p", "section", "td"}
    )
    _IGNORED_TAGS = frozenset({"canvas", "noscript", "script", "style", "svg", "template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        name = tag.lower()
        if name in self._IGNORED_TAGS:
            self._ignored_depth += 1
        elif not self._ignored_depth and name in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in self._IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
        elif not self._ignored_depth and name in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self._parts.append(data)

    def text(self, limit: int) -> str:
        joined = html.unescape("".join(self._parts))
        lines = [re.sub(r"\s+", " ", line).strip() for line in joined.splitlines()]
        compact = "\n".join(line for line in lines if len(line) >= 2)
        return compact[: max(0, int(limit))].strip()


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, resolver: Callable[..., Iterable[tuple[Any, ...]]]) -> None:
        super().__init__()
        self._resolver = resolver

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        ensure_safe_public_url(newurl, resolver=self._resolver)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class SafePageFetcher:
    def __init__(
        self,
        *,
        timeout_seconds: float = 4.0,
        max_bytes: int = 750_000,
        max_text_chars: int = 5_000,
        resolver: Callable[..., Iterable[tuple[Any, ...]]] = socket.getaddrinfo,
        opener: Any | None = None,
    ) -> None:
        self._timeout_seconds = max(1.0, min(10.0, float(timeout_seconds)))
        self._max_bytes = max(50_000, min(2_000_000, int(max_bytes)))
        self._max_text_chars = max(500, min(20_000, int(max_text_chars)))
        self._resolver = resolver
        self._opener = opener or urllib.request.build_opener(_SafeRedirectHandler(resolver))

    def fetch(self, url: str) -> str:
        try:
            target = ensure_safe_public_url(url, resolver=self._resolver)
        except ValueError:
            return ""
        request = urllib.request.Request(
            target,
            headers={
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
                "Accept-Encoding": "identity",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                content_type = str(response.headers.get_content_type() or "").lower()
                if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                    return ""
                payload = response.read(self._max_bytes + 1)
                charset = response.headers.get_content_charset() or "utf-8"
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError):
            return ""
        if len(payload) > self._max_bytes:
            return ""
        text = payload.decode(charset, errors="replace")
        if content_type == "text/plain":
            return re.sub(r"\s+", " ", text).strip()[: self._max_text_chars]
        parser = _TextExtractor()
        try:
            parser.feed(text)
            parser.close()
        except Exception:
            return ""
        return parser.text(self._max_text_chars)


def ensure_safe_public_url(
    url: object,
    *,
    resolver: Callable[..., Iterable[tuple[Any, ...]]] = socket.getaddrinfo,
) -> str:
    target = _clean(url, 2_000)
    parsed = urllib.parse.urlsplit(target)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public HTTP(S) URLs can be fetched.")
    if parsed.username or parsed.password:
        raise ValueError("Authenticated URLs are not allowed.")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("Non-standard URL ports are not allowed.")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
        raise ValueError("Local URLs are not allowed.")
    try:
        direct_ip = ipaddress.ip_address(hostname)
    except ValueError:
        direct_ip = None
    addresses = [direct_ip] if direct_ip is not None else []
    if direct_ip is None:
        try:
            resolved = resolver(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ValueError("The page hostname could not be resolved.") from exc
        for entry in resolved:
            try:
                addresses.append(ipaddress.ip_address(entry[4][0].split("%", 1)[0]))
            except (IndexError, TypeError, ValueError):
                continue
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Private or non-routable URLs are not allowed.")
    return target


def _mapping_items(value: object, limit: int) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value[: max(0, int(limit))] if isinstance(item, Mapping))


def _clean(value: object, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[: max(0, int(limit))]


def _http_url(value: object) -> bool:
    try:
        return urllib.parse.urlsplit(str(value or "")).scheme.lower() in {"http", "https"}
    except ValueError:
        return False
