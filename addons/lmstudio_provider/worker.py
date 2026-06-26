from __future__ import annotations

import json
import sys
import urllib.error
from typing import Any, Iterable
from urllib.request import Request, urlopen


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
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _http_error_text(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""
    if body:
        return body[:2000]
    return str(exc)


def _native_reasoning_unsupported(error_text: str) -> bool:
    lowered = str(error_text or "").lower()
    return "reasoning" in lowered and "does not expose reasoning configuration" in lowered


def _extract_openai_message(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    if not choices:
        return ""
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(str(item.get("text")))
        return _strip_channel_blocks("".join(parts))
    return _strip_channel_blocks(content)


def _extract_openai_delta(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    if not choices:
        return ""
    choice = choices[0] if isinstance(choices[0], dict) else {}
    delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
    content = delta.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(str(item.get("text")))
        return "".join(parts)
    return str(content or "")


def _extract_native_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    output = payload.get("output")
    if isinstance(output, list):
        parts = []
        for item in output:
            if isinstance(item, dict) and str(item.get("type") or "").lower() == "message":
                parts.append(str(item.get("content") or ""))
        return _strip_channel_blocks("".join(parts))
    return _strip_channel_blocks(payload.get("content") or payload.get("text") or "")


def _stream_sse(url: str, payload: dict[str, Any], api_key: str, *, native: bool) -> Iterable[str]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=300.0) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            raw_payload = line[5:].strip()
            if not raw_payload or raw_payload == "[DONE]":
                continue
            try:
                event = json.loads(raw_payload)
            except Exception:
                continue
            if native:
                event_type = str(event.get("type") or "").strip()
                if event_type == "message.delta" and event.get("content"):
                    yield str(event.get("content"))
                elif event_type == "error":
                    message = str(event.get("message") or event.get("error") or "LM Studio native chat error")
                    raise RuntimeError(message)
            else:
                text = _extract_openai_delta(event)
                if text:
                    yield text


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
    with urlopen(request, timeout=300.0) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _run_request(config: dict[str, Any]) -> str:
    api_key = str(config.get("api_key") or "lm-studio")
    url = str(config.get("url") or "").strip()
    native = bool(config.get("native"))
    payload = dict(config.get("payload") or {})
    fallback_payload = config.get("fallback_payload") if isinstance(config.get("fallback_payload"), dict) else None
    emit_chunks = bool(config.get("emit_chunks"))
    force_non_stream = bool(config.get("force_non_stream"))
    stream = bool(config.get("stream", payload.get("stream", False))) and not force_non_stream
    if not url:
        raise RuntimeError("LM Studio worker received an empty request URL.")

    if not stream:
        try:
            response_payload = _post_json(url, payload, api_key)
        except urllib.error.HTTPError as exc:
            error_text = _http_error_text(exc)
            if not (native and fallback_payload and _native_reasoning_unsupported(error_text)):
                raise RuntimeError(error_text)
            response_payload = _post_json(url, fallback_payload, api_key)
        return _extract_native_text(response_payload) if native else _extract_openai_message(response_payload)

    parts: list[str] = []
    channel_filter = ChannelFilter()
    try:
        for chunk in _stream_sse(url, payload, api_key, native=native):
            parts.append(str(chunk))
            if emit_chunks:
                for filtered in channel_filter.feed(str(chunk)):
                    if filtered:
                        _emit({"chunk": filtered})
    except urllib.error.HTTPError as exc:
        error_text = _http_error_text(exc)
        if not (native and fallback_payload and _native_reasoning_unsupported(error_text)):
            raise RuntimeError(error_text)
        for chunk in _stream_sse(url, fallback_payload, api_key, native=native):
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
