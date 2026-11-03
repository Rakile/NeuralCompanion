from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SearchResult:
    kind: str
    title: str
    url: str
    snippet: str = ""
    source: str = ""
    published: str = ""
    media_url: str = ""
    thumbnail_url: str = ""


@dataclass(frozen=True, slots=True)
class SearchBundle:
    query: str
    web: tuple[SearchResult, ...] = ()
    images: tuple[SearchResult, ...] = ()
    videos: tuple[SearchResult, ...] = ()

