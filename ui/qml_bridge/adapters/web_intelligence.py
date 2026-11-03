"""Native QML workspace for Web Intelligence and its local MCP backends."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from PySide6 import QtCore
from addons.web_intelligence.service import DEFAULT_EVIDENCE_PREFIX

from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.adapters.config import RuntimeConfigNativeAdapter
from ui.qml_bridge.native_contracts import (
    NativeChoice,
    NativeControl,
    NativeControlKind,
    NativeSurface,
)
from ui.qml_bridge.native_registry import NativeSurfaceAdapter


_SETTING_IDS = {
    "web_intelligence_enabled": "enabled",
    "web_intelligence_evidence_prefix": "evidence_prefix",
    "web_intelligence_mode": "mode",
    "web_intelligence_use_llm_context_intent": "use_llm_context_intent",
    "web_intelligence_max_results": "max_results",
    "web_intelligence_fetch_pages": "fetch_pages",
    "web_intelligence_include_page_text": "include_page_text",
    "web_intelligence_include_images": "include_images",
    "web_intelligence_include_videos": "include_videos",
}


class WebIntelligenceNativeAdapter(NativeSurfaceAdapter):
    def __init__(
        self,
        application_facade: Any,
        surface: NativeSurface,
        *,
        persist: Callable[[], object] | None = None,
        parent=None,
    ) -> None:
        super().__init__(surface.id, surface.addon_id, parent)
        self._application = application_facade
        self._surface = surface
        self._controls = {control.id: control for control in surface.controls}
        self._persist = persist
        self._revision = 0
        self._lock = threading.RLock()
        self._test_query = "latest NeuralCompanion information"
        self._action_result = "Use Check endpoints to inspect the local MCP servers."
        self._install_poll_remaining = 0
        self._install_poll_timer = QtCore.QTimer(self)
        self._install_poll_timer.setInterval(500)
        self._install_poll_timer.timeout.connect(self._poll_installation)

    def _invoke(self, capability: str, payload=None) -> object:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id,
            capability,
            dict(payload or {}),
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "Web Intelligence is unavailable."))
            )
        return result.value

    def _status(self) -> dict[str, object]:
        value = self._invoke("runtime.web_intelligence.status")
        if not isinstance(value, Mapping):
            raise RuntimeError("Web Intelligence status is not a mapping.")
        return dict(value)

    @staticmethod
    def _server_line(server: Mapping[str, object]) -> str:
        label = str(server.get("label") or "Search server")
        endpoint = str(server.get("endpoint") or "not configured")
        state = str(server.get("state") or "offline").capitalize()
        ownership = "NC-managed process" if server.get("managed_running") else "external or stopped"
        error = str(server.get("error") or "").strip()
        line = f"{state} — {endpoint}\nProcess: {ownership}"
        if error:
            line += f"\n{error}"
        if not server.get("launcher_available"):
            line += "\nLocal launcher is not installed. An externally started endpoint can still be used."
        elif server.get("installed_by_nc"):
            line += "\nLauncher: installed in addon-local storage."
        return f"{label}\n{line}"

    @staticmethod
    def _installation_line(installation: Mapping[str, object]) -> str:
        if installation.get("installing"):
            phase = str(installation.get("phase") or "Installing server runtimes").strip()
            return f"Installing in the background…\n{phase}"
        lines = [str(installation.get("message") or "No installation has run yet.").strip()]
        for server_id in ("mcp_searxng", "duckduckgo_mcp"):
            server = dict(dict(installation.get("servers") or {}).get(server_id) or {})
            message = str(server.get("message") or "").strip()
            if message:
                label = "SearXNG MCP" if server_id == "mcp_searxng" else "DuckDuckGo MCP"
                lines.append(f"{label}: {message}")
        return "\n".join(line for line in lines if line)

    def _poll_installation(self) -> None:
        self._install_poll_remaining -= 1
        try:
            status = self._status()
            installation = dict(dict(status.get("backend") or {}).get("installation") or {})
            installing = bool(installation.get("installing"))
        except (KeyError, RuntimeError, TypeError, ValueError):
            installing = self._install_poll_remaining > 0
        with self._lock:
            self._revision += 1
        self.changed.emit()
        if not installing or self._install_poll_remaining <= 0:
            self._install_poll_timer.stop()

    def _start_install_polling(self, seconds: int = 900) -> None:
        self._install_poll_remaining = max(
            self._install_poll_remaining,
            max(1, int(seconds) * 2),
        )
        if not self._install_poll_timer.isActive():
            self._install_poll_timer.start()

    def snapshot(self) -> NativeSurface:
        status = self._status()
        backend = dict(status.get("backend") or {})
        servers = dict(backend.get("servers") or {})
        searxng = dict(servers.get("mcp_searxng") or {})
        duck = dict(servers.get("duckduckgo_mcp") or {})
        online = int(backend.get("online_count") or 0)
        total = int(backend.get("server_count") or 2)
        installation = dict(backend.get("installation") or {})
        installing = bool(installation.get("installing"))
        mode = str(status.get("mode") or "auto")
        cache_entries = int(status.get("cache_entries") or 0)
        overall = (
            f"Web search: {'enabled' if status.get('enabled', True) else 'disabled globally'}. "
            f"Search mode: {mode}. Endpoints online: {online}/{total}. "
            f"Cached searches: {cache_entries}."
        )
        values: dict[str, object] = {
            "web_intelligence_enabled": bool(status.get("enabled", True)),
            "web_intelligence_evidence_prefix": status.get("evidence_prefix", DEFAULT_EVIDENCE_PREFIX),
            "web_intelligence_overall_status": overall,
            "web_intelligence_mode": mode,
            "web_intelligence_use_llm_context_intent": bool(status.get("use_llm_context_intent", False)),
            "web_intelligence_max_results": int(status.get("max_results") or 5),
            "web_intelligence_fetch_pages": int(status.get("fetch_pages") or 1),
            "web_intelligence_include_page_text": bool(status.get("include_page_text", True)),
            "web_intelligence_include_images": bool(status.get("include_images", True)),
            "web_intelligence_include_videos": bool(status.get("include_videos", True)),
            "web_intelligence_searxng_status": self._server_line(searxng),
            "web_intelligence_duck_status": self._server_line(duck),
            "web_intelligence_install_status": self._installation_line(installation),
        }
        with self._lock:
            values["web_intelligence_test_query"] = self._test_query
            values["web_intelligence_action_result"] = self._action_result
            revision = self._revision
        controls = tuple(
            replace(
                control,
                value=values.get(control.id, control.default_value),
                enabled=(
                    not installing
                    if control.id == "web_intelligence_install_servers"
                    else control.enabled
                ),
            )
            for control in self._surface.controls
        )
        return replace(
            self._surface,
            controls=apply_card_layout(controls),
            revision=revision,
        )

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        control = self._controls.get(key)
        if control is None or control.kind in {
            NativeControlKind.ACTION,
            NativeControlKind.DISPLAY,
        } or (control.kind is NativeControlKind.MULTILINE and control.metadata.get("readOnly", True)):
            raise KeyError(f"Unknown Web Intelligence setting '{control_id}'.")
        normalized = RuntimeConfigNativeAdapter._normalize(control, value)
        if key == "web_intelligence_test_query":
            with self._lock:
                self._test_query = str(normalized or "").strip()
                self._revision += 1
            self.changed.emit()
            return
        setting = _SETTING_IDS.get(key)
        if setting is None:
            raise KeyError(f"Unknown Web Intelligence setting '{control_id}'.")
        self._invoke(
            "runtime.web_intelligence.configure",
            {"settings": {setting: normalized}},
        )
        if callable(self._persist):
            self._persist()
        with self._lock:
            self._revision += 1
        self.changed.emit()

    def trigger(self, control_id: str) -> None:
        action_id = str(control_id or "").strip()
        if action_id == "web_intelligence_restore_evidence_prefix":
            self.set_value("web_intelligence_evidence_prefix", DEFAULT_EVIDENCE_PREFIX)
            return
        action_map = {
            "web_intelligence_install_servers": "install",
            "web_intelligence_start_servers": "start",
            "web_intelligence_stop_servers": "stop",
            "web_intelligence_refresh_servers": "refresh",
            "web_intelligence_clear_cache": "clear_cache",
            "web_intelligence_test_search": "test",
        }
        action = action_map.get(action_id)
        if action is None:
            raise KeyError(f"Unknown Web Intelligence action '{control_id}'.")
        payload: dict[str, object] = {}
        if action == "test":
            with self._lock:
                query = self._test_query
            if not query:
                raise ValueError("Enter a test search query first.")
            payload["query"] = query
        result = self._invoke(
            "runtime.web_intelligence.action",
            {"action": action, "payload": payload},
        )
        if action == "install":
            self._start_install_polling()
        if action == "test":
            response = dict(result or {})
            if response.get("ok", True):
                message = (
                    f"Provider: {response.get('provider', 'unknown')}\n"
                    f"{response.get('title', 'Untitled result')}\n"
                    f"{response.get('url', '')}\n"
                    f"{response.get('snippet', '')}"
                ).strip()
            else:
                message = str(
                    response.get("error")
                    or "The Web Search backend could not complete the test."
                ).strip()
        elif action == "install":
            installation = dict(dict(result or {}).get("installation") or {})
            message = self._installation_line(installation)
        elif action == "clear_cache":
            message = "The Web Intelligence search cache was cleared."
        else:
            backend = dict(result or {})
            message = (
                f"Endpoint check complete: {int(backend.get('online_count') or 0)}/"
                f"{int(backend.get('server_count') or 2)} online."
            )
        with self._lock:
            self._action_result = message
            self._revision += 1
        self.changed.emit()


def _action(
    control_id: str,
    label: str,
    section: str,
    description: str,
    *,
    destructive: bool = False,
) -> NativeControl:
    return NativeControl(
        control_id,
        label,
        NativeControlKind.ACTION,
        section,
        description=description,
        metadata={"destructive": destructive},
    )


def build_web_intelligence_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
) -> WebIntelligenceNativeAdapter:
    overview = "Overview"
    servers = "Servers"
    test = "Test"
    controls = (
        NativeControl(
            "web_intelligence_enabled",
            "Enable web search",
            NativeControlKind.BOOLEAN,
            overview,
            default_value=True,
            description=(
                "Global switch. Off immediately blocks search-intent model calls and all web searches, "
                "including Conversation, LocalRoom, /web requests, and test searches. "
                "Server settings and running servers are kept."
            ),
        ),
        NativeControl(
            "web_intelligence_overall_status",
            "Web search status",
            NativeControlKind.DISPLAY,
            overview,
            description="Current chat-search mode, endpoint readiness, and cache use.",
        ),
        NativeControl(
            "web_intelligence_mode",
            "Conversation search mode",
            NativeControlKind.CHOICE,
            overview,
            default_value="auto",
            choices=(
                NativeChoice("off", "Off"),
                NativeChoice("auto", "Automatically when current information is needed"),
                NativeChoice("always", "Every normal chat turn"),
            ),
            description="Off blocks normal-chat searches, including /web requests. Automatic mode searches only freshness-sensitive requests.",
        ),
        NativeControl(
            "web_intelligence_use_llm_context_intent",
            "Use LLM for context intent",
            NativeControlKind.BOOLEAN,
            overview,
            default_value=False,
            description=(
                "Provisional: in Automatic mode, ask the selected chat LLM whether to search "
                "and extract a focused query. Adds one model call per incoming turn when a search backend is available. "
                "Off keeps legacy keyword matching. Explicit /web and Every turn bypass this check."
            ),
        ),
        NativeControl(
            "web_intelligence_max_results",
            "Maximum search results",
            NativeControlKind.INTEGER,
            overview,
            default_value=5,
            minimum=1,
            maximum=10,
        ),
        NativeControl(
            "web_intelligence_fetch_pages",
            "Pages to read",
            NativeControlKind.INTEGER,
            overview,
            default_value=1,
            minimum=0,
            maximum=3,
        ),
        NativeControl(
            "web_intelligence_include_page_text",
            "Read result pages for grounded evidence",
            NativeControlKind.BOOLEAN,
            overview,
            default_value=True,
        ),
        NativeControl(
            "web_intelligence_include_images",
            "Allow image searches when requested",
            NativeControlKind.BOOLEAN,
            overview,
            default_value=True,
        ),
        NativeControl(
            "web_intelligence_include_videos",
            "Allow video searches when requested",
            NativeControlKind.BOOLEAN,
            overview,
            default_value=True,
        ),
        _action(
            "web_intelligence_clear_cache",
            "Clear search cache",
            overview,
            "Remove cached web evidence without changing provider settings.",
        ),
        NativeControl(
            "web_intelligence_evidence_prefix",
            "Search result instructions",
            NativeControlKind.MULTILINE,
            overview,
            default_value=DEFAULT_EVIDENCE_PREFIX,
            description="Prepended to web evidence sent to chat (up to 8,000 characters). The search query, backend, and sources are added automatically. Changes save when you leave the field.",
            metadata={"readOnly": False, "scrollable": True, "editorPreferredHeight": 260,
                      "groupKey": "evidence_guidance", "groupTitle": "Search result instructions", "groupColumnSpan": 2},
        ),
        NativeControl(
            "web_intelligence_restore_evidence_prefix",
            "Restore defaults",
            NativeControlKind.ACTION,
            overview,
            metadata={"groupKey": "evidence_guidance", "groupTitle": "Search result instructions", "groupColumnSpan": 2},
        ),
        NativeControl(
            "web_intelligence_searxng_status",
            "SearXNG MCP",
            NativeControlKind.MULTILINE,
            servers,
            metadata={"readOnly": True},
            description="Primary private metasearch MCP endpoint. It uses the configured local SearXNG instance.",
        ),
        NativeControl(
            "web_intelligence_duck_status",
            "DuckDuckGo MCP",
            NativeControlKind.MULTILINE,
            servers,
            metadata={"readOnly": True},
            description="No-key fallback MCP endpoint used when SearXNG is unavailable.",
        ),
        NativeControl(
            "web_intelligence_install_status",
            "Server installation",
            NativeControlKind.MULTILINE,
            servers,
            metadata={"readOnly": True},
            description=(
                "Installation progress and per-server results. Server packages are kept "
                "inside addon-local storage and do not modify NeuralCompanion's environment."
            ),
        ),
        _action(
            "web_intelligence_install_servers",
            "Install / repair search servers",
            servers,
            "Install the DuckDuckGo MCP server in a private Python environment and the optional SearXNG MCP bridge in private Node storage. Runs in the background with no console windows.",
        ),
        _action(
            "web_intelligence_start_servers",
            "Start local search servers",
            servers,
            "Launch the addon-local server packages after installation. Existing external endpoints are detected and left untouched.",
        ),
        _action(
            "web_intelligence_refresh_servers",
            "Check endpoints",
            servers,
            "Probe both configured loopback endpoints without starting anything.",
        ),
        _action(
            "web_intelligence_stop_servers",
            "Stop NC-managed servers",
            servers,
            "Stop only server processes started from this addon tab.",
            destructive=True,
        ),
        NativeControl(
            "web_intelligence_test_query",
            "Search query",
            NativeControlKind.TEXT,
            test,
            default_value="latest NeuralCompanion information",
            description="Runs a one-result backend test without sending a chat turn.",
        ),
        _action(
            "web_intelligence_test_search",
            "Run test search",
            test,
            "Verify the provider fallback chain and show the first result.",
        ),
        NativeControl(
            "web_intelligence_action_result",
            "Diagnostic result",
            NativeControlKind.MULTILINE,
            test,
            metadata={"readOnly": True},
        ),
    )
    surface = NativeSurface(
        id="web_intelligence_tab",
        title="Web Search",
        addon_id="nc.web_intelligence",
        sections=(overview, servers, test),
        description=(
            "Activate grounded web evidence for the existing main chat model and "
            "manage the local MCP search endpoints explicitly."
        ),
        controls=controls,
    )
    return WebIntelligenceNativeAdapter(
        application_facade,
        surface,
        persist=persist,
    )


__all__ = ["WebIntelligenceNativeAdapter", "build_web_intelligence_adapter"]
