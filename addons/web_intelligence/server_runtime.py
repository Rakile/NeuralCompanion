"""Explicit lifecycle control for Web Intelligence's local MCP servers.

The search service can use independently managed MCP endpoints. This module
owns only processes and addon-local installers explicitly started from the Web
Search workspace; endpoints started elsewhere remain externally owned.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from addons.web_intelligence.server_installer import (
    WebSearchServerInstaller,
    server_paths,
)


_SERVER_IDS = ("mcp_searxng", "duckduckgo_mcp")


@dataclass(frozen=True, slots=True)
class _ServerSpec:
    server_id: str
    label: str
    endpoint: str
    executable_names: tuple[str, ...]
    arguments: tuple[str, ...]
    environment: Mapping[str, str]


@dataclass(slots=True)
class _ManagedProcess:
    process: Any
    command: tuple[str, ...]
    started_at: float


def _endpoint_reachable(endpoint: str, timeout: float = 0.4) -> bool:
    parsed = urlsplit(str(endpoint or "").strip())
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=max(0.1, float(timeout))):
            return True
    except OSError:
        return False


def _hidden_process_options() -> dict[str, object]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return {
        "creationflags": (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        ),
        "startupinfo": startupinfo,
    }


class WebSearchServerRuntime:
    """Start, stop, and inspect the two loopback MCP search endpoints."""

    def __init__(
        self,
        settings_provider: Callable[[], Any],
        *,
        environ: Mapping[str, str] | None = None,
        executable_resolver: Callable[[str], str | None] = shutil.which,
        process_factory: Callable[..., Any] = subprocess.Popen,
        endpoint_probe: Callable[[str], bool] = _endpoint_reachable,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        install_root: Path | None = None,
        tasks: Any | None = None,
        installer: Any | None = None,
    ) -> None:
        self._settings_provider = settings_provider
        self._environ = dict(os.environ if environ is None else environ)
        self._resolve_executable = executable_resolver
        self._process_factory = process_factory
        self._endpoint_probe = endpoint_probe
        self._clock = clock
        self._sleep = sleep
        self._install_root = Path(install_root).resolve() if install_root else None
        self._tasks = tasks
        self._installer = installer
        self._lock = threading.RLock()
        self._processes: dict[str, _ManagedProcess] = {}
        self._reachable: dict[str, bool] = {server_id: False for server_id in _SERVER_IDS}
        self._errors: dict[str, str] = {server_id: "" for server_id in _SERVER_IDS}
        self._last_checked_at = 0.0
        self._installing = False
        self._install_phase = ""
        self._installation: dict[str, object] = {
            "ok": False,
            "partial": False,
            "cancelled": False,
            "completed": False,
            "installed_count": 0,
            "server_count": len(_SERVER_IDS),
            "message": "Search server launchers have not been installed by NC yet.",
            "servers": {},
        }

    def _specs(self) -> tuple[_ServerSpec, ...]:
        settings = self._settings_provider()
        searxng_endpoint = str(settings.mcp_searxng_url or "").strip()
        duck_endpoint = str(settings.duckduckgo_mcp_url or "").strip()
        searxng_port = urlsplit(searxng_endpoint).port or 3000
        duck_port = urlsplit(duck_endpoint).port or 8000
        local_paths = server_paths(self._install_root) if self._install_root else None
        if local_paths:
            searxng_launchers = (str(local_paths.searxng_launcher),)
            searxng_arguments: tuple[str, ...] = ()
            duck_launchers = (str(local_paths.duck_launcher),)
            duck_arguments = (
                "--transport",
                "streamable-http",
                "--host",
                "127.0.0.1",
                "--port",
                str(duck_port),
            )
        else:
            searxng_launchers = ("npx.cmd", "npx")
            searxng_arguments = ("-y", "mcp-searxng")
            duck_launchers = ("uvx.exe", "uvx")
            duck_arguments = (
                "--with",
                "duckduckgo-mcp-server[browser]",
                "duckduckgo-mcp-server",
                "--transport",
                "streamable-http",
                "--host",
                "127.0.0.1",
                "--port",
                str(duck_port),
            )
        return (
            _ServerSpec(
                "mcp_searxng",
                "SearXNG MCP",
                searxng_endpoint,
                searxng_launchers,
                searxng_arguments,
                {
                    "MCP_HTTP_PORT": str(searxng_port),
                    "SEARXNG_URL": str(
                        self._environ.get("SEARXNG_URL")
                        or self._environ.get("NC_SEARXNG_URL")
                        or "http://127.0.0.1:8080"
                    ),
                },
            ),
            _ServerSpec(
                "duckduckgo_mcp",
                "DuckDuckGo MCP",
                duck_endpoint,
                duck_launchers,
                duck_arguments,
                {},
            ),
        )

    def _resolve(self, spec: _ServerSpec) -> str:
        for name in spec.executable_names:
            if name and Path(name).is_file():
                return str(Path(name))
            resolved = self._resolve_executable(name)
            if resolved:
                return str(resolved)
        return ""

    @staticmethod
    def _running(managed: _ManagedProcess | None) -> bool:
        return managed is not None and managed.process.poll() is None

    def refresh(self) -> dict[str, object]:
        results: dict[str, bool] = {}
        for spec in self._specs():
            try:
                results[spec.server_id] = bool(self._endpoint_probe(spec.endpoint))
            except Exception as error:
                results[spec.server_id] = False
                with self._lock:
                    self._errors[spec.server_id] = f"Endpoint check failed: {error}"
        with self._lock:
            self._reachable.update(results)
            self._last_checked_at = self._clock()
        return self.snapshot()

    def start(self, *, readiness_timeout: float = 15.0) -> dict[str, object]:
        self.refresh()
        started_any = False
        for spec in self._specs():
            with self._lock:
                managed = self._processes.get(spec.server_id)
                already_reachable = self._reachable.get(spec.server_id, False)
            if already_reachable or self._running(managed):
                continue
            executable = self._resolve(spec)
            if not executable:
                with self._lock:
                    self._errors[spec.server_id] = (
                        f"Launcher not found ({' or '.join(spec.executable_names)})."
                    )
                continue
            command = (executable, *spec.arguments)
            environment = dict(self._environ)
            environment.update(spec.environment)
            options: dict[str, object] = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "env": environment,
            }
            options.update(_hidden_process_options())
            try:
                process = self._process_factory(command, **options)
            except Exception as error:
                with self._lock:
                    self._errors[spec.server_id] = f"Could not start server: {error}"
                continue
            with self._lock:
                self._processes[spec.server_id] = _ManagedProcess(
                    process=process,
                    command=command,
                    started_at=self._clock(),
                )
                self._errors[spec.server_id] = ""
            started_any = True

        if started_any:
            deadline = self._clock() + max(0.0, float(readiness_timeout))
            while self._clock() < deadline:
                snapshot = self.refresh()
                servers = dict(snapshot.get("servers") or {})
                if all(
                    bool(dict(servers.get(server_id) or {}).get("reachable"))
                    or not bool(dict(servers.get(server_id) or {}).get("managed_running"))
                    for server_id in _SERVER_IDS
                ):
                    break
                self._sleep(0.25)
        return self.refresh()

    def install(self) -> dict[str, object]:
        """Start the addon-owned installer without blocking the UI caller."""

        with self._lock:
            if self._installing:
                return self.snapshot()
            if self._install_root is None or self._tasks is None:
                self._installation = {
                    **self._installation,
                    "ok": False,
                    "message": "The addon runtime did not provide installer storage or task ownership.",
                }
                return self.snapshot()
            self._installing = True
            self._install_phase = "Preparing addon-local server environments"
            self._installation = {
                **self._installation,
                "ok": False,
                "partial": False,
                "cancelled": False,
                "message": "Web Search server installation is starting.",
            }

        def worker(cancel) -> None:
            try:
                installer = self._installer or WebSearchServerInstaller(
                    self._install_root,
                    tasks=self._tasks,
                    environ=self._environ,
                )
                report = installer.install(cancel, progress=self._set_install_phase)
            except Exception as error:
                report = {
                    "ok": False,
                    "partial": False,
                    "cancelled": bool(getattr(cancel, "cancelled", False)),
                    "completed": True,
                    "installed_count": 0,
                    "server_count": len(_SERVER_IDS),
                    "message": f"Web Search server installation failed: {error}",
                    "servers": {},
                }
            with self._lock:
                self._installation = {**dict(report), "completed": True}
                self._installing = False
                self._install_phase = ""

        try:
            self._tasks.spawn("install-search-servers", worker)
        except Exception as error:
            with self._lock:
                self._installing = False
                self._install_phase = ""
                self._installation = {
                    **self._installation,
                    "message": f"Could not start the Web Search installer: {error}",
                }
        return self.snapshot()

    def _set_install_phase(self, message: str) -> None:
        with self._lock:
            self._install_phase = str(message or "").strip()

    def stop(self, *, refresh: bool = True) -> dict[str, object]:
        with self._lock:
            managed_items = tuple(self._processes.items())
            self._processes.clear()
        for server_id, managed in managed_items:
            process = managed.process
            if process.poll() is not None:
                continue
            try:
                process.terminate()
                process.wait(timeout=3.0)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=2.0)
                except Exception as error:
                    with self._lock:
                        self._errors[server_id] = f"Could not stop managed server: {error}"
        if refresh:
            return self.refresh()
        with self._lock:
            self._reachable = {server_id: False for server_id in _SERVER_IDS}
        return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        servers: dict[str, dict[str, object]] = {}
        online = 0
        for spec in self._specs():
            with self._lock:
                managed = self._processes.get(spec.server_id)
                reachable = bool(self._reachable.get(spec.server_id, False))
                error = str(self._errors.get(spec.server_id, "") or "")
                last_checked_at = self._last_checked_at
            managed_running = self._running(managed)
            if reachable:
                state = "online"
                online += 1
            elif managed_running:
                state = "starting"
            else:
                state = "offline"
            servers[spec.server_id] = {
                "id": spec.server_id,
                "label": spec.label,
                "endpoint": spec.endpoint,
                "state": state,
                "reachable": reachable,
                "managed_running": managed_running,
                "launcher_available": bool(self._resolve(spec)),
                "installed_by_nc": self._installed_by_nc(spec.server_id),
                "error": error,
            }
        with self._lock:
            installation = dict(self._installation)
            installation["installing"] = self._installing
            installation["phase"] = self._install_phase
        installed_count = sum(
            bool(server.get("installed_by_nc")) for server in servers.values()
        )
        if not installation.get("installing") and not installation.get("completed"):
            installation.update(
                {
                    "ok": installed_count == len(servers) and bool(servers),
                    "partial": 0 < installed_count < len(servers),
                    "installed_count": installed_count,
                    "server_count": len(servers),
                    "message": (
                        "Both Web Search server launchers are installed."
                        if installed_count == len(servers) and servers
                        else f"Detected {installed_count}/{len(servers)} addon-local server launchers."
                        if installed_count
                        else "Search server launchers have not been installed by NC yet."
                    ),
                }
            )
        return {
            "servers": servers,
            "online_count": online,
            "server_count": len(servers),
            "last_checked_at": last_checked_at,
            "installation": installation,
        }

    def _installed_by_nc(self, server_id: str) -> bool:
        if self._install_root is None:
            return False
        paths = server_paths(self._install_root)
        if server_id == "mcp_searxng":
            return paths.searxng_launcher.is_file()
        if server_id == "duckduckgo_mcp":
            return paths.duck_launcher.is_file()
        return False

    def shutdown(self) -> None:
        self.stop(refresh=False)


__all__ = ["WebSearchServerRuntime"]
