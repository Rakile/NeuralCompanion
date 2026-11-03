from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any


MCP_PROTOCOL_VERSION = "2025-06-18"


class McpHttpError(RuntimeError):
    """A bounded failure while calling a Streamable HTTP MCP server."""


class StreamableHttpMcpClient:
    """Minimal synchronous MCP client for addon-local search tool calls.

    A fresh legacy-compatible MCP session is used for every tool call. This
    keeps lifecycle ownership local to the normal-chat worker and avoids a
    long-lived process, socket, or background thread inside the addon.
    """

    def __init__(self, endpoint: str, *, timeout_seconds: float = 8.0) -> None:
        self._endpoint = _validated_endpoint(endpoint)
        self._timeout_seconds = max(1.0, min(30.0, float(timeout_seconds)))
        self._request_lock = threading.Lock()
        self._next_request_id = 1

    @property
    def endpoint(self) -> str:
        return self._endpoint

    def call_tool(self, name: str, arguments: Mapping[str, object] | None = None) -> dict[str, Any]:
        tool_name = str(name or "").strip()
        if not tool_name:
            raise ValueError("MCP tool name is required.")
        session_id = ""
        try:
            initialize_id = self._request_id()
            initialize, session_id = self._post(
                {
                    "jsonrpc": "2.0",
                    "id": initialize_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {
                            "name": "neuralcompanion-web-intelligence",
                            "version": "0.2.0",
                        },
                    },
                }
            )
            _require_response(initialize, initialize_id, "MCP initialize")
            self._post(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                },
                session_id=session_id,
                response_required=False,
            )
            request_id = self._request_id()
            response, returned_session_id = self._post(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": dict(arguments or {}),
                    },
                },
                session_id=session_id,
            )
            if returned_session_id:
                session_id = returned_session_id
            message = _require_response(response, request_id, f"MCP tool {tool_name}")
            result = message.get("result")
            if not isinstance(result, Mapping):
                raise McpHttpError(f"MCP tool {tool_name} returned no result object.")
            normalized = dict(result)
            if bool(normalized.get("isError", False)):
                detail = tool_result_text(normalized) or "The MCP tool reported an error."
                raise McpHttpError(detail[:500])
            return normalized
        finally:
            if session_id:
                self._close_session(session_id)

    def _request_id(self) -> int:
        with self._request_lock:
            request_id = self._next_request_id
            self._next_request_id += 1
            return request_id

    def _post(
        self,
        payload: Mapping[str, object],
        *,
        session_id: str = "",
        response_required: bool = True,
    ) -> tuple[list[dict[str, Any]], str]:
        body = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
            "User-Agent": "NeuralCompanion-WebIntelligence/0.2",
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        request = urllib.request.Request(
            self._endpoint,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read(2_000_001)
                content_type = str(response.headers.get("Content-Type") or "").lower()
                returned_session_id = str(response.headers.get("Mcp-Session-Id") or "").strip()
        except urllib.error.HTTPError as exc:
            detail = _http_error_detail(exc)
            raise McpHttpError(f"MCP server returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            cause = getattr(exc, "reason", exc)
            detail = "request timed out" if isinstance(cause, TimeoutError) else "connection failed"
            raise McpHttpError(f"The configured MCP server is unavailable ({detail}).") from exc
        if len(raw) > 2_000_000:
            raise McpHttpError("The MCP server returned an unexpectedly large response.")
        if not raw.strip():
            if response_required:
                raise McpHttpError("The MCP server returned an empty response.")
            return [], returned_session_id or session_id
        messages = (
            _decode_sse(raw)
            if "text/event-stream" in content_type
            else _decode_json_messages(raw)
        )
        if response_required and not messages:
            raise McpHttpError("The MCP server returned no JSON-RPC message.")
        return messages, returned_session_id or session_id

    def _close_session(self, session_id: str) -> None:
        request = urllib.request.Request(
            self._endpoint,
            headers={
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
                "Mcp-Session-Id": str(session_id),
                "User-Agent": "NeuralCompanion-WebIntelligence/0.2",
            },
            method="DELETE",
        )
        try:
            with urllib.request.urlopen(request, timeout=min(2.0, self._timeout_seconds)):
                return
        except Exception:
            # Stateless servers commonly reject DELETE. Session cleanup is
            # best-effort and must never replace the useful tool result.
            return


def tool_result_text(result: Mapping[str, object] | None) -> str:
    payload = dict(result or {})
    parts: list[str] = []
    content = payload.get("content")
    if isinstance(content, (list, tuple)):
        for item in content:
            if not isinstance(item, Mapping):
                continue
            if str(item.get("type") or "").strip().lower() == "text":
                text = str(item.get("text") or "").strip()
                if text:
                    parts.append(text)
            resource = item.get("resource")
            if isinstance(resource, Mapping):
                text = str(resource.get("text") or "").strip()
                if text:
                    parts.append(text)
    if parts:
        return "\n\n".join(parts)
    structured = payload.get("structuredContent")
    if isinstance(structured, Mapping):
        return json.dumps(dict(structured), ensure_ascii=False)
    return ""


def tool_result_json(result: Mapping[str, object] | None) -> Mapping[str, Any] | None:
    payload = dict(result or {})
    structured = payload.get("structuredContent")
    if isinstance(structured, Mapping):
        candidate = dict(structured)
        nested = candidate.get("result")
        if isinstance(nested, Mapping):
            return dict(nested)
        return candidate
    text = tool_result_text(payload).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(decoded, Mapping):
        nested = decoded.get("result")
        return dict(nested) if isinstance(nested, Mapping) else dict(decoded)
    return None


def _require_response(
    messages: list[dict[str, Any]],
    request_id: object,
    label: str,
) -> dict[str, Any]:
    message = next((item for item in messages if item.get("id") == request_id), None)
    if message is None:
        raise McpHttpError(f"{label} returned no matching JSON-RPC response.")
    error = message.get("error")
    if isinstance(error, Mapping):
        detail = str(error.get("message") or "Unknown JSON-RPC error.").strip()
        raise McpHttpError(f"{label} failed: {detail[:500]}")
    return message


def _decode_json_messages(raw: bytes) -> list[dict[str, Any]]:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise McpHttpError("The MCP server returned invalid JSON.") from exc
    values = decoded if isinstance(decoded, list) else [decoded]
    return [dict(item) for item in values if isinstance(item, Mapping)]


def _decode_sse(raw: bytes) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise McpHttpError("The MCP server returned invalid SSE text.") from exc
    messages: list[dict[str, Any]] = []
    data_lines: list[str] = []
    for line in text.splitlines() + [""]:
        if not line:
            if data_lines:
                data = "\n".join(data_lines)
                try:
                    decoded = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise McpHttpError("The MCP server returned invalid SSE JSON.") from exc
                if isinstance(decoded, Mapping):
                    messages.append(dict(decoded))
                data_lines.clear()
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    return messages


def _validated_endpoint(endpoint: object) -> str:
    value = str(endpoint or "").strip()
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("MCP endpoint must be an HTTP(S) URL.")
    if parsed.username or parsed.password:
        raise ValueError("Credentials must not be embedded in an MCP endpoint URL.")
    return value


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read(1_001)
    except Exception:
        return str(exc.reason or "request failed")[:300]
    if len(body) > 1_000:
        return "response body was too large"
    return body.decode("utf-8", errors="replace").strip()[:300] or str(exc.reason or "request failed")[:300]
