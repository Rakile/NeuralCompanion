from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path
from typing import Any, Iterable
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from addons.lmstudio_provider.responses import (
    decode_http_text,
    extract_response_text,
    http_error_text,
    iter_response_sse,
    response_charset,
)


CHANNEL_START = "<|channel>"
CHANNEL_END = "<channel|>"


def _strip_channel_blocks(text: Any) -> str:
    value = str(text or "")
    if CHANNEL_START not in value:
        return value.strip()
    parts: list[str] = []
    position = 0
    while position < len(value):
        start = value.find(CHANNEL_START, position)
        if start < 0:
            parts.append(value[position:])
            break
        parts.append(value[position:start])
        end = value.find(CHANNEL_END, start + len(CHANNEL_START))
        if end < 0:
            break
        position = end + len(CHANNEL_END)
    return "".join(parts).strip()


class ChannelFilter:
    def __init__(self) -> None:
        self.buffer = ""
        self.in_channel = False
        self.keep = max(len(CHANNEL_START), len(CHANNEL_END)) - 1

    def feed(self, chunk: str) -> Iterable[str]:
        self.buffer += str(chunk or "")
        while self.buffer:
            if self.in_channel:
                end = self.buffer.find(CHANNEL_END)
                if end < 0:
                    self.buffer = self.buffer[-self.keep :]
                    break
                self.buffer = self.buffer[end + len(CHANNEL_END) :]
                self.in_channel = False
                continue
            start = self.buffer.find(CHANNEL_START)
            if start >= 0:
                if start:
                    yield self.buffer[:start]
                self.buffer = self.buffer[start + len(CHANNEL_START) :]
                self.in_channel = True
                continue
            if len(self.buffer) <= self.keep:
                break
            yield self.buffer[:-self.keep]
            self.buffer = self.buffer[-self.keep :]
            break

    def flush(self) -> Iterable[str]:
        if self.buffer and not self.in_channel:
            yield self.buffer
        self.buffer = ""
        self.in_channel = False


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _stream_sse_lines(url: str, payload: dict[str, Any], api_key: str) -> Iterable[str]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=300.0) as response:
            charset = response_charset(response)
            for raw_line in response:
                yield decode_http_text(raw_line, charset)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(http_error_text(exc)) from exc


def _post_json(url: str, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=300.0) as response:
            return json.loads(decode_http_text(response.read(), response_charset(response)))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(http_error_text(exc)) from exc


def _run_request(config: dict[str, Any]) -> str:
    api_key = str(config.get("api_key") or "lm-studio")
    url = str(config.get("url") or "").strip()
    payload = dict(config.get("payload") or {})
    emit_chunks = bool(config.get("emit_chunks"))
    stream = bool(config.get("stream", payload.get("stream", False)))
    if not url:
        raise RuntimeError("LM Studio worker received an empty request URL.")

    if not stream:
        return _strip_channel_blocks(extract_response_text(_post_json(url, payload, api_key)))

    parts: list[str] = []
    channel_filter = ChannelFilter()
    for chunk in iter_response_sse(_stream_sse_lines(url, payload, api_key)):
        parts.append(str(chunk))
        if emit_chunks:
            for filtered in channel_filter.feed(str(chunk)):
                if filtered:
                    _emit({"chunk": filtered})
    if emit_chunks:
        for filtered in channel_filter.flush():
            if filtered:
                _emit({"chunk": filtered})
    return _strip_channel_blocks("".join(parts))


def main() -> int:
    try:
        config = json.loads(sys.stdin.read() or "{}")
        text = _run_request(config if isinstance(config, dict) else {})
        _emit({"ok": True, "text": text})
        return 0
    except Exception as exc:
        _emit({"ok": False, "error": str(exc) or repr(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
