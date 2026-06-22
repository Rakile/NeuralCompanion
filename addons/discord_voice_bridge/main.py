from __future__ import annotations

import copy
import audioop
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import wave
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.addons.base import BaseAddon
from addons.discord_voice_bridge.runtime_server import DiscordVoiceRuntimeServer
from addons.discord_voice_bridge.settings import (
    load_settings,
    load_settings_schema,
    redacted_settings,
)


ADDON_DIR = Path(__file__).resolve().parent
NODE_BRIDGE_DIR = ADDON_DIR / "node_bridge"
INSTANCE_SETTINGS_DIR = ADDON_DIR / "runtime_instances"
DEFAULT_TINY_MVP_BRIDGE_SCRIPT = ADDON_DIR.parent.parent.parent / "TinyMVP" / "tiny_voice_bridge.py"
NODE_BRIDGE_REQUIRED_PACKAGES = (
    "@discordjs/voice",
    "discord.js",
    "dotenv",
    "ffmpeg-static",
    "opusscript",
    "prism-media",
)


class BridgeInstance:
    def __init__(self, *, instance_id: str, settings: dict[str, Any], settings_path: Path, bridge_token: str):
        self.instance_id = instance_id
        self.settings = settings
        self.settings_path = settings_path
        self.status_path = INSTANCE_SETTINGS_DIR / f"{_safe_instance_id(instance_id)}.status.json"
        self.command_path = INSTANCE_SETTINGS_DIR / f"{_safe_instance_id(instance_id)}.commands.jsonl"
        self.bridge_token = bridge_token
        self.runtime_server = None
        self.process = None
        self.log_handle = None
        self.output_thread = None


class Addon(BaseAddon):
    """Discord voice bridge addon with isolated NC voice-turn runtime."""

    def initialize(self, context):
        super().initialize(context)
        self.context = context
        from addons.discord_voice_bridge.controller import DiscordVoiceBridgeController

        self.controller = DiscordVoiceBridgeController(context, self)
        context.ui.register_manifest_designer_tab(
            id="discord_voice_bridge_tab",
            binder=self.controller.bind_widget,
            metadata={"runtime_role": "discord_voice_bridge"},
        )
        self._bridge_instances: list[BridgeInstance] = []
        self._tiny_mvp_mic_lock = threading.RLock()
        self._tiny_mvp_mic_stop: threading.Event | None = None
        self._tiny_mvp_mic_thread: threading.Thread | None = None
        self._tiny_mvp_mic_start_timer: threading.Timer | None = None
        settings = load_settings()
        self._start_instances_from_settings(settings, force=False, sync_tiny_mvp_mic=False)
        self._schedule_tiny_mvp_local_mic_sync(settings)
        context.logger.info("Discord Voice Bridge initialized (%s instance(s)).", len(self._bridge_instances))
        return None

    def shutdown(self):
        timer = getattr(self, "_tiny_mvp_mic_start_timer", None)
        if timer is not None:
            timer.cancel()
        self._tiny_mvp_mic_start_timer = None
        self._stop_tiny_mvp_local_mic()
        self.stop_bridge_instances()
        self.controller = None
        return None

    def invoke_capability(self, capability, payload=None):
        capability = str(capability or "").strip().lower()
        if capability == "discord_voice_bridge.node_bridge_dir":
            return str(NODE_BRIDGE_DIR)
        if capability == "discord_voice_bridge.status":
            return self.status_snapshot()
        if capability == "discord_voice_bridge.settings":
            return redacted_settings()
        if capability == "discord_voice_bridge.settings_schema":
            return load_settings_schema()
        if capability == "discord_voice_bridge.validate_settings":
            return self.validate_settings()
        return None

    def status_snapshot(self):
        settings = load_settings()
        instances = list(getattr(self, "_bridge_instances", []) or [])
        status_by_instance = {
            item.instance_id: _read_instance_status(item.status_path)
            for item in instances
        }
        return {
            "status": "ready",
            "node_bridge_dir": str(NODE_BRIDGE_DIR),
            "tiny_mvp_bridge_script": str(_tiny_mvp_bridge_script(settings)),
            "tiny_mvp_mic_running": self._tiny_mvp_local_mic_running(),
            "settings": redacted_settings(settings),
            "runtime_connected": any(item.process is not None and item.process.poll() is None for item in instances),
            "endpoint_running": any(item.runtime_server is not None and item.runtime_server.running for item in instances),
            "endpoint_url": instances[0].runtime_server.url if instances and instances[0].runtime_server is not None else "",
            "instances": [
                {
                    "id": item.instance_id,
                    "name": str(item.settings.get("name") or item.instance_id),
                    "discord_bot_tag": str(status_by_instance.get(item.instance_id, {}).get("bot_tag") or ""),
                    "discord_bot_id": str(status_by_instance.get(item.instance_id, {}).get("bot_id") or ""),
                    "guild_id": str(_get(item.settings, "discord.guild_id", "") or ""),
                    "guild_name": str(status_by_instance.get(item.instance_id, {}).get("guild_name") or ""),
                    "voice_channel_id": str(_get(item.settings, "discord.voice_channel_id", "") or ""),
                    "voice_channel_name": str(status_by_instance.get(item.instance_id, {}).get("voice_channel_name") or ""),
                    "token_env_var": str(_get(item.settings, "discord.token_env_var", "") or ""),
                    "runtime_port": _get(item.settings, "nc_runtime.port", ""),
                    "pid": item.process.pid if item.process is not None and item.process.poll() is None else "",
                    "settings_path": str(item.settings_path),
                    "status_path": str(item.status_path),
                    "command_path": str(item.command_path),
                    "log_path": str(ADDON_DIR / "runtime_logs" / f"discord_voice_bridge_{item.instance_id}.log"),
                    "runtime_connected": item.process is not None and item.process.poll() is None,
                    "endpoint_running": item.runtime_server is not None and item.runtime_server.running,
                    "endpoint_url": item.runtime_server.url if item.runtime_server is not None else "",
                    "node_status": status_by_instance.get(item.instance_id, {}),
                    "runtime_status": _runtime_server_status(item),
                }
                for item in instances
            ],
        }

    def start_bridge_instances(self):
        if getattr(self, "_bridge_instances", None):
            self._sync_tiny_mvp_local_mic(load_settings())
            return self.status_snapshot()
        return self._start_instances_from_settings(load_settings(), force=True)

    def stop_bridge_instances(self):
        self._stop_tiny_mvp_local_mic()
        for instance in list(getattr(self, "_bridge_instances", []) or []):
            self._stop_node_bridge(instance)
            self._stop_runtime_server(instance)
        self._bridge_instances = []
        return self.status_snapshot()

    def restart_bridge_instances(self):
        self.stop_bridge_instances()
        return self._start_instances_from_settings(load_settings(), force=True)

    def start_bridge_instance(self, instance_id: str):
        instance_id = _safe_instance_id(instance_id)
        if not instance_id:
            raise RuntimeError("No Discord bridge bot instance selected.")
        existing = self._find_instance(instance_id)
        if existing is not None and _bridge_instance_is_running(existing):
            return self.status_snapshot()
        instance = self._configured_instance(instance_id)
        if instance is None:
            raise RuntimeError(f"Discord bridge bot instance {instance_id!r} was not found in settings.")
        self._bridge_instances = [
            item for item in list(getattr(self, "_bridge_instances", []) or [])
            if item.instance_id != instance_id
        ]
        self._bridge_instances.append(instance)
        self._start_runtime_server(instance)
        self._start_node_bridge(instance)
        self._sync_tiny_mvp_local_mic(load_settings())
        return self.status_snapshot()

    def stop_bridge_instance(self, instance_id: str):
        instance = self._find_instance(instance_id)
        if instance is None:
            return self.status_snapshot()
        self._stop_node_bridge(instance)
        self._stop_runtime_server(instance)
        self._bridge_instances = [
            item for item in list(getattr(self, "_bridge_instances", []) or [])
            if item is not instance
        ]
        self._sync_tiny_mvp_local_mic(load_settings())
        return self.status_snapshot()

    def restart_bridge_instance(self, instance_id: str):
        instance_id = _safe_instance_id(instance_id)
        self.stop_bridge_instance(instance_id)
        return self.start_bridge_instance(instance_id)

    def send_instance_command(self, instance_id: str, action: str, payload: dict[str, Any] | None = None):
        instance = self._find_instance(_safe_instance_id(instance_id))
        if instance is None:
            raise RuntimeError(f"Discord bridge bot instance {instance_id!r} is not running.")
        command = {
            "id": secrets.token_urlsafe(12),
            "action": str(action or "").strip(),
            "payload": payload if isinstance(payload, dict) else {},
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if not command["action"]:
            raise RuntimeError("Discord bridge command action is empty.")
        INSTANCE_SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        with instance.command_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(command, ensure_ascii=True) + "\n")
        return self.status_snapshot()

    def reset_instance_context(self, instance_id: str):
        instance = self._find_instance(_safe_instance_id(instance_id))
        if instance is None:
            raise RuntimeError(f"Discord bridge bot instance {instance_id!r} is not running.")
        if instance.runtime_server is not None and hasattr(instance.runtime_server, "reset_history"):
            instance.runtime_server.reset_history()
        self.send_instance_command(instance.instance_id, "reset_context")
        return self.status_snapshot()

    def erase_instance_context(self, instance_id: str):
        instance_id = _safe_instance_id(instance_id)
        if not instance_id:
            raise RuntimeError("No Discord bridge bot instance selected.")
        instance = self._find_instance(instance_id)
        if instance is not None and instance.runtime_server is not None and hasattr(instance.runtime_server, "reset_history"):
            instance.runtime_server.reset_history()
        _delete_instance_history_file(instance_id)
        return self.status_snapshot()

    def erase_all_instance_contexts(self):
        settings = load_settings()
        instance_ids = {
            configured.instance_id
            for configured in _bridge_instances_from_settings(settings, force=True)
        }
        instance_ids.update(
            instance.instance_id
            for instance in list(getattr(self, "_bridge_instances", []) or [])
        )
        for instance in list(getattr(self, "_bridge_instances", []) or []):
            if instance.runtime_server is not None and hasattr(instance.runtime_server, "reset_history"):
                instance.runtime_server.reset_history()
        for instance_id in instance_ids:
            _delete_instance_history_file(instance_id)
        return self.status_snapshot()

    def apply_live_settings(
        self,
        instance_id: str | None = None,
        settings: dict[str, Any] | None = None,
        sections: tuple[str, ...] | list[str] | None = None,
    ):
        payload = settings if isinstance(settings, dict) else load_settings()
        section_names = tuple(str(item) for item in (sections or ()) if str(item or "").strip())
        targets = []
        requested = _safe_instance_id(instance_id) if str(instance_id or "").strip() else ""
        for configured in _bridge_instances_from_settings(payload, force=True):
            if requested and configured.instance_id != requested:
                continue
            running = self._find_instance(configured.instance_id)
            if running is None:
                continue
            if section_names:
                merged = copy.deepcopy(running.settings if isinstance(running.settings, dict) else configured.settings)
                for section in section_names:
                    value = configured.settings.get(section)
                    if isinstance(value, dict):
                        merged[section] = copy.deepcopy(value)
                running.settings = merged
            else:
                running.settings = configured.settings
            _write_instance_settings(running.instance_id, running.settings)
            if running.runtime_server is not None and hasattr(running.runtime_server, "apply_live_settings"):
                running.runtime_server.apply_live_settings(running.settings)
            self.send_instance_command(running.instance_id, "reload_settings")
            targets.append(running.instance_id)
        self._sync_tiny_mvp_local_mic(payload)
        if requested and not targets:
            raise RuntimeError(f"Discord bridge bot instance {requested!r} is not running.")
        return {"ok": True, "updated": targets, "status": self.status_snapshot()}

    def install_node_bridge_dependencies(self):
        logger = getattr(getattr(self, "context", None), "logger", None)
        running = [
            instance.instance_id
            for instance in list(getattr(self, "_bridge_instances", []) or [])
            if _bridge_instance_is_running(instance)
        ]
        if running:
            names = ", ".join(running[:5])
            extra = f" and {len(running) - 5} more" if len(running) > 5 else ""
            raise RuntimeError(f"Stop the Discord bridge before installing Node dependencies. Running instance(s): {names}{extra}.")
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("npm was not found on PATH. Install Node.js/npm before installing Discord bridge dependencies.")
        package_json = NODE_BRIDGE_DIR / "package.json"
        if not package_json.exists():
            raise RuntimeError(f"Node bridge package.json is missing: {package_json}")

        log_dir = ADDON_DIR / "runtime_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "discord_voice_bridge_npm_install.log"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if logger:
            logger.info("Discord Voice Bridge installing Node dependencies in %s", NODE_BRIDGE_DIR)
        try:
            result = subprocess.run(
                [npm, "install"],
                cwd=str(NODE_BRIDGE_DIR),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("npm install timed out after 10 minutes.") from exc

        output = _redact_runtime_log_text(result.stdout or "")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write("\n--- npm install ---\n")
            handle.write(output)
            if output and not output.endswith("\n"):
                handle.write("\n")
            handle.write(f"exit_code={result.returncode}\n")

        if result.returncode != 0:
            raise RuntimeError(f"npm install failed with exit code {result.returncode}. See {log_path}")
        if logger:
            logger.info("Discord Voice Bridge Node dependencies installed/updated. log=%s", log_path)
        return {"ok": True, "log_path": str(log_path)}

    def validate_settings(self, settings: dict[str, Any] | None = None, *, force: bool = True):
        payload = settings if isinstance(settings, dict) else load_settings()
        return _validate_bridge_settings(payload, force=force) + _transport_environment_issues(payload, require_install=True)

    def _start_instances_from_settings(self, settings: dict[str, Any], *, force: bool, sync_tiny_mvp_mic: bool = True):
        issues = _validate_bridge_settings(settings, force=force) + _transport_environment_issues(settings, require_install=True)
        errors = [item for item in issues if item.get("severity") == "error"]
        if errors:
            logger = getattr(getattr(self, "context", None), "logger", None)
            if logger:
                for issue in errors:
                    logger.warning("Discord Voice Bridge settings error: %s", issue.get("message"))
            self._bridge_instances = []
            return self.status_snapshot()
        self._bridge_instances = []
        for instance in _bridge_instances_from_settings(settings, force=force):
            self._bridge_instances.append(instance)
            self._start_runtime_server(instance)
            self._start_node_bridge(instance)
        if sync_tiny_mvp_mic:
            self._sync_tiny_mvp_local_mic(settings)
        return self.status_snapshot()

    def _start_runtime_server(self, instance: BridgeInstance):
        logger = getattr(getattr(self, "context", None), "logger", None)
        try:
            instance.runtime_server = DiscordVoiceRuntimeServer(
                settings=instance.settings,
                logger=logger,
                bridge_token=instance.bridge_token,
                addon_context=getattr(self, "context", None),
            )
            instance.runtime_server.start()
        except Exception as exc:
            instance.runtime_server = None
            if logger:
                logger.warning("Discord Voice Bridge %s failed to start runtime endpoint: %s", instance.instance_id, exc)

    def _stop_runtime_server(self, instance: BridgeInstance):
        server = instance.runtime_server
        if server is not None:
            try:
                server.stop()
            except Exception:
                pass
        instance.runtime_server = None

    def _start_node_bridge(self, instance: BridgeInstance):
        logger = getattr(getattr(self, "context", None), "logger", None)
        environment_errors = [
            item for item in _transport_environment_issues(instance.settings, require_install=True)
            if item.get("severity") == "error"
        ]
        if environment_errors:
            if logger:
                for issue in environment_errors:
                    logger.warning("Discord Voice Bridge could not start: %s", issue.get("message"))
            return
        bridge_mode = _bridge_mode(instance.settings)
        tiny_mode = bridge_mode == "tiny_mvp"
        executable = sys.executable if tiny_mode else shutil.which("node")
        script = _tiny_mvp_bridge_script(instance.settings) if tiny_mode else NODE_BRIDGE_DIR / "src" / "index.js"

        env = os.environ.copy()
        env["NC_DISCORD_BRIDGE_SETTINGS_JSON"] = str(instance.settings_path)
        env["NC_DISCORD_BRIDGE_STATUS_JSON"] = str(instance.status_path)
        env["NC_DISCORD_BRIDGE_COMMAND_JSONL"] = str(instance.command_path)
        if tiny_mode:
            capture_dir = NODE_BRIDGE_DIR / "captures"
            capture_dir.mkdir(parents=True, exist_ok=True)
            env["NC_DISCORD_BRIDGE_CAPTURE_DIR"] = str(capture_dir)
        if instance.bridge_token:
            env["NC_DISCORD_BRIDGE_TOKEN"] = instance.bridge_token
        discord = instance.settings.get("discord") if isinstance(instance.settings, dict) else {}
        if isinstance(discord, dict):
            token = str(discord.get("token") or "").strip()
            token_env_var = str(discord.get("token_env_var") or "DISCORD_TOKEN").strip() or "DISCORD_TOKEN"
            if _looks_like_discord_token(token_env_var) and not token:
                token = token_env_var
                token_env_var = "DISCORD_TOKEN"
            if token:
                env[token_env_var] = token

        log_dir = ADDON_DIR / "runtime_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"discord_voice_bridge_{instance.instance_id}.log"
        try:
            instance.status_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            instance.command_path.unlink(missing_ok=True)
        except Exception:
            pass
        instance.log_handle = log_path.open("a", encoding="utf-8")
        token_env_var = str(_get(instance.settings, "discord.token_env_var", "DISCORD_TOKEN") or "DISCORD_TOKEN")
        launched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        transport_label = "TinyMVP Voice Bridge" if tiny_mode else "Discord Voice Bridge"
        instance.log_handle.write(
            f"\n--- {transport_label} launch: {instance.instance_id} @ {launched_at} ---\n"
            f"settings={instance.settings_path}\n"
            f"bridge_mode={bridge_mode}\n"
            f"token_env_var={token_env_var}\n"
        )
        instance.log_handle.flush()

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            if tiny_mode:
                nc_runtime = instance.settings.get("nc_runtime") if isinstance(instance.settings, dict) else {}
                tiny_mvp = instance.settings.get("tiny_mvp") if isinstance(instance.settings.get("tiny_mvp"), dict) else {}
                tiny_url = str(tiny_mvp.get("url") or "http://127.0.0.1:8788").strip() or "http://127.0.0.1:8788"
                nc_turn_url = str(nc_runtime.get("http_endpoint") or "").strip()
                if not nc_turn_url:
                    host = str(nc_runtime.get("host") or "127.0.0.1").strip() or "127.0.0.1"
                    port = int(nc_runtime.get("port") or 8768)
                    nc_turn_url = f"http://{host}:{port}/turn"
                poll_seconds = float(tiny_mvp.get("poll_seconds") or 0.25)
                args = [
                    str(executable),
                    str(script),
                    "--bot-id",
                    instance.instance_id,
                    "--bot-name",
                    str(instance.settings.get("name") or instance.instance_id),
                    "--tiny-url",
                    tiny_url,
                    "--nc-turn-url",
                    nc_turn_url,
                    "--poll-seconds",
                    str(poll_seconds),
                ]
                cwd = str(script.parent)
            else:
                args = [str(executable), str(script)]
                cwd = str(NODE_BRIDGE_DIR)
            instance.process = subprocess.Popen(
                args,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            instance.output_thread = threading.Thread(
                target=self._forward_node_bridge_output,
                args=(instance,),
                name=f"DiscordVoiceBridgeOutput-{instance.instance_id}",
                daemon=True,
            )
            instance.output_thread.start()
        except Exception as exc:
            if logger:
                logger.warning("Discord Voice Bridge %s failed to start Node bridge: %s", instance.instance_id, exc)
            self._close_log_handle(instance)
            return

        if logger:
            logger.info("Discord Voice Bridge %s transport started: mode=%s, pid=%s, log=%s", instance.instance_id, bridge_mode, instance.process.pid, log_path)

    def _stop_node_bridge(self, instance: BridgeInstance):
        process = instance.process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        instance.process = None
        instance.output_thread = None
        self._close_log_handle(instance)

    def _forward_node_bridge_output(self, instance: BridgeInstance):
        logger = getattr(getattr(self, "context", None), "logger", None)
        process = instance.process
        stream = getattr(process, "stdout", None)
        if stream is None:
            return
        try:
            for line in stream:
                text = str(line or "").rstrip()
                if not text:
                    continue
                text = _redact_runtime_log_text(text)
                handle = instance.log_handle
                if handle is not None:
                    try:
                        handle.write(text + "\n")
                        handle.flush()
                    except Exception:
                        pass
                if logger:
                    logger.info("[DiscordBridge:%s] %s", instance.instance_id, text)
        except Exception as exc:
            if logger:
                logger.debug("Discord Voice Bridge %s output forwarding stopped: %s", instance.instance_id, exc)

    def _close_log_handle(self, instance: BridgeInstance):
        handle = instance.log_handle
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
        instance.log_handle = None

    def _find_instance(self, instance_id: str) -> BridgeInstance | None:
        wanted = _safe_instance_id(instance_id)
        for instance in list(getattr(self, "_bridge_instances", []) or []):
            if instance.instance_id == wanted:
                return instance
        return None

    def _configured_instance(self, instance_id: str) -> BridgeInstance | None:
        wanted = _safe_instance_id(instance_id)
        for instance in _bridge_instances_from_settings(load_settings(), force=True):
            if instance.instance_id == wanted:
                return instance
        return None

    def _tiny_mvp_local_mic_running(self) -> bool:
        thread = getattr(self, "_tiny_mvp_mic_thread", None)
        return bool(thread is not None and thread.is_alive())

    def _schedule_tiny_mvp_local_mic_sync(self, settings: dict[str, Any]) -> None:
        if _bridge_mode(settings) != "tiny_mvp" or not _get(settings, "tiny_mvp.capture_mic", False):
            return
        with self._tiny_mvp_mic_lock:
            existing = getattr(self, "_tiny_mvp_mic_start_timer", None)
            if existing is not None:
                existing.cancel()
            timer = threading.Timer(4.0, lambda: self._sync_tiny_mvp_local_mic(load_settings()))
            timer.daemon = True
            self._tiny_mvp_mic_start_timer = timer
            timer.start()

    def _sync_tiny_mvp_local_mic(self, settings: dict[str, Any]) -> None:
        tiny_mvp = settings.get("tiny_mvp") if isinstance(settings, dict) else {}
        enabled = (
            _bridge_mode(settings) == "tiny_mvp"
            and isinstance(tiny_mvp, dict)
            and bool(tiny_mvp.get("capture_mic"))
            and any(_bridge_mode(item.settings) == "tiny_mvp" and _bridge_instance_is_running(item) for item in list(getattr(self, "_bridge_instances", []) or []))
        )
        if enabled:
            self._start_tiny_mvp_local_mic(settings)
        else:
            self._stop_tiny_mvp_local_mic()

    def _start_tiny_mvp_local_mic(self, settings: dict[str, Any]) -> None:
        with self._tiny_mvp_mic_lock:
            if self._tiny_mvp_local_mic_running():
                return
            stop_event = threading.Event()
            self._tiny_mvp_mic_stop = stop_event
            thread = threading.Thread(
                target=self._tiny_mvp_local_mic_loop,
                args=(copy.deepcopy(settings), stop_event),
                name="DiscordTinyMVPLocalMic",
                daemon=True,
            )
            self._tiny_mvp_mic_thread = thread
            thread.start()

    def _stop_tiny_mvp_local_mic(self) -> None:
        with getattr(self, "_tiny_mvp_mic_lock", threading.RLock()):
            stop_event = getattr(self, "_tiny_mvp_mic_stop", None)
            thread = getattr(self, "_tiny_mvp_mic_thread", None)
            if stop_event is not None:
                stop_event.set()
            if thread is not None and thread.is_alive():
                thread.join(timeout=1.5)
            self._tiny_mvp_mic_stop = None
            self._tiny_mvp_mic_thread = None

    def _tiny_mvp_local_mic_loop(self, initial_settings: dict[str, Any], stop_event: threading.Event) -> None:
        logger = getattr(getattr(self, "context", None), "logger", None)
        # PyAudio can crash natively if opened while the Qt shell is still
        # enumerating devices during startup. This mic loop is nonessential to
        # bridge connection, so give UI startup a short window to finish first.
        if stop_event.wait(2.0):
            return
        try:
            import speech_recognition as sr  # type: ignore[import-not-found]
        except Exception as exc:
            if logger:
                logger.warning("TinyMVP NC microphone input needs speech_recognition/PyAudio: %s", exc)
            return

        settings = copy.deepcopy(initial_settings)
        tiny_mvp = settings.get("tiny_mvp") if isinstance(settings.get("tiny_mvp"), dict) else {}
        recognizer = sr.Recognizer()
        recognizer.dynamic_energy_threshold = True
        capture = settings.get("capture") if isinstance(settings.get("capture"), dict) else {}
        silence_ms = _float_setting(capture.get("silence_ms"), 1200.0)
        recognizer.pause_threshold = max(0.2, silence_ms / 1000.0)
        recognizer.non_speaking_duration = min(0.8, max(0.2, recognizer.pause_threshold / 2.0))
        device_index = self._tiny_mvp_mic_device_index(sr, str(tiny_mvp.get("mic_device") or "").strip())
        sample_rate = _int_setting(tiny_mvp.get("mic_sample_rate") or capture.get("wav_sample_rate"), 16000)
        capture_max = _float_setting(capture.get("max_turn_seconds"), -1.0)
        phrase_limit = capture_max if capture_max > 0 else -1.0
        if logger:
            phrase_label = f"{phrase_limit:.1f}s" if phrase_limit > 0 else "unlimited"
            logger.info("TinyMVP NC microphone input started (sample_rate=%s, phrase_limit=%s).", sample_rate, phrase_label)
        try:
            with sr.Microphone(device_index=device_index, sample_rate=sample_rate) as source:
                try:
                    recognizer.adjust_for_ambient_noise(source, duration=0.4)
                except Exception:
                    pass
                while not stop_event.is_set():
                    settings = load_settings()
                    if _bridge_mode(settings) != "tiny_mvp" or not _get(settings, "tiny_mvp.capture_mic", False):
                        break
                    try:
                        wav_path = self._capture_tiny_mvp_local_mic_wav(
                            source,
                            recognizer,
                            settings,
                            stop_event,
                            phrase_limit=phrase_limit,
                        )
                    except TimeoutError:
                        continue
                    except Exception as exc:
                        if logger:
                            logger.debug("TinyMVP NC microphone listen skipped: %s", exc)
                        time.sleep(0.25)
                        continue
                    if stop_event.is_set():
                        break
                    if wav_path is None:
                        continue
                    try:
                        self._submit_tiny_mvp_local_mic_wav(wav_path, settings)
                    except Exception as exc:
                        if logger:
                            logger.warning("TinyMVP NC microphone turn failed: %s", exc)
        except Exception as exc:
            if logger:
                logger.warning("TinyMVP NC microphone input stopped: %s", exc)
        finally:
            if logger:
                logger.info("TinyMVP NC microphone input stopped.")

    @staticmethod
    def _tiny_mvp_mic_device_index(sr_module, device_text: str) -> int | None:
        if not device_text:
            return None
        try:
            return int(device_text)
        except ValueError:
            pass
        try:
            names = sr_module.Microphone.list_microphone_names()
        except Exception:
            return None
        needle = device_text.lower()
        for index, name in enumerate(names):
            if needle in str(name or "").lower():
                return index
        return None

    def _capture_tiny_mvp_local_mic_wav(
        self,
        source,
        recognizer,
        settings: dict[str, Any],
        stop_event: threading.Event,
        *,
        phrase_limit: float,
    ) -> Path | None:
        chunk_size = int(getattr(source, "CHUNK", 1024) or 1024)
        sample_rate = int(getattr(source, "SAMPLE_RATE", 16000) or 16000)
        sample_width = int(getattr(source, "SAMPLE_WIDTH", 2) or 2)
        seconds_per_buffer = chunk_size / float(sample_rate or 16000)
        pause_seconds = max(0.2, float(getattr(recognizer, "pause_threshold", 0.8) or 0.8))
        non_speaking_seconds = max(0.1, float(getattr(recognizer, "non_speaking_duration", 0.5) or 0.5))
        pre_speech_buffers = max(1, int(non_speaking_seconds / seconds_per_buffer))
        pause_buffers = max(1, int(pause_seconds / seconds_per_buffer))
        energy_threshold = max(120.0, float(getattr(recognizer, "energy_threshold", 300.0) or 300.0))
        pre_roll: deque[bytes] = deque(maxlen=pre_speech_buffers)
        frames: list[bytes] = []
        quiet_after_voice = 0
        started_at = 0.0
        probe_done = False
        wait_started = time.monotonic()
        while not stop_event.is_set():
            data = self._read_tiny_mvp_source_chunk(source, chunk_size)
            if not data:
                continue
            energy = audioop.rms(data, sample_width)
            if not frames:
                if energy > energy_threshold:
                    started_at = time.monotonic()
                    frames.extend(pre_roll)
                    frames.append(data)
                    quiet_after_voice = 0
                else:
                    pre_roll.append(data)
                    if time.monotonic() - wait_started >= 0.5:
                        raise TimeoutError("no speech detected")
                continue

            frames.append(data)
            if energy > energy_threshold:
                quiet_after_voice = 0
            else:
                quiet_after_voice += 1

            elapsed = time.monotonic() - started_at
            if not probe_done and self._maybe_probe_tiny_mvp_interruption(
                frames,
                settings,
                duration_seconds=elapsed,
                sample_rate=sample_rate,
                sample_width=sample_width,
            ):
                probe_done = True
            if quiet_after_voice >= pause_buffers:
                break
            if phrase_limit > 0 and elapsed >= phrase_limit:
                break
        if not frames:
            return None
        return self._write_tiny_mvp_local_mic_frame_wav(
            frames,
            settings,
            sample_rate=sample_rate,
            sample_width=sample_width,
            suffix="final",
        )

    @staticmethod
    def _read_tiny_mvp_source_chunk(source, chunk_size: int) -> bytes:
        stream = getattr(source, "stream", None)
        if stream is None:
            return b""
        try:
            return stream.read(chunk_size, exception_on_overflow=False)
        except TypeError:
            return stream.read(chunk_size)

    def _write_tiny_mvp_local_mic_wav(self, audio, settings: dict[str, Any]) -> Path:
        capture = settings.get("capture") if isinstance(settings.get("capture"), dict) else {}
        tiny_mvp = settings.get("tiny_mvp") if isinstance(settings.get("tiny_mvp"), dict) else {}
        sample_rate = _int_setting(tiny_mvp.get("mic_sample_rate") or capture.get("wav_sample_rate"), 16000)
        wav_bytes = audio.get_wav_data(convert_rate=sample_rate, convert_width=2)
        capture_dir = NODE_BRIDGE_DIR / "captures"
        capture_dir.mkdir(parents=True, exist_ok=True)
        wav_path = capture_dir / f"tinymvp_nc_mic_{int(time.time() * 1000)}_{secrets.token_hex(4)}.wav"
        wav_path.write_bytes(wav_bytes)
        return wav_path

    def _write_tiny_mvp_local_mic_frame_wav(
        self,
        frames: list[bytes],
        settings: dict[str, Any],
        *,
        sample_rate: int,
        sample_width: int,
        suffix: str,
    ) -> Path:
        capture_dir = NODE_BRIDGE_DIR / "captures"
        capture_dir.mkdir(parents=True, exist_ok=True)
        wav_path = capture_dir / f"tinymvp_nc_mic_{suffix}_{int(time.time() * 1000)}_{secrets.token_hex(4)}.wav"
        with wave.open(str(wav_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(max(1, int(sample_width or 2)))
            handle.setframerate(max(8000, int(sample_rate or 16000)))
            handle.writeframes(b"".join(frames))
        return wav_path

    def _maybe_probe_tiny_mvp_interruption(
        self,
        frames: list[bytes],
        settings: dict[str, Any],
        *,
        duration_seconds: float,
        sample_rate: int,
        sample_width: int,
    ) -> bool:
        playback = settings.get("playback") if isinstance(settings.get("playback"), dict) else {}
        capture = settings.get("capture") if isinstance(settings.get("capture"), dict) else {}
        if not _bool_setting(playback.get("interrupt_reply_on_user_speech"), True):
            return False
        interrupt_after = _float_setting(playback.get("interrupt_after_seconds"), 4.0)
        min_turn = _float_setting(capture.get("min_turn_seconds"), 0.6)
        threshold = max(min_turn, interrupt_after)
        if threshold <= 0 or duration_seconds < threshold:
            return False
        tiny_url = str(_get(settings, "tiny_mvp.url", "http://127.0.0.1:8788") or "http://127.0.0.1:8788").rstrip("/")
        try:
            state = _http_json("GET", f"{tiny_url}/state", timeout=1.0)
        except Exception:
            return False
        if not str((state or {}).get("playback_owner_id") or "").strip():
            return False
        tiny_mvp = settings.get("tiny_mvp") if isinstance(settings.get("tiny_mvp"), dict) else {}
        user_id = str(tiny_mvp.get("mic_user_id") or "rakila").strip() or "rakila"
        if _tiny_mvp_current_speaker_blocks_user(state, user_id):
            return False
        if not self._tiny_mvp_reply_immunity_elapsed(state, playback):
            return False
        instance = self._tiny_mvp_route_instance()
        server = getattr(instance, "runtime_server", None) if instance is not None else None
        if server is None or not hasattr(server, "probe_transcript"):
            return False
        probe_path = self._write_tiny_mvp_local_mic_frame_wav(
            frames,
            settings,
            sample_rate=sample_rate,
            sample_width=sample_width,
            suffix="probe",
        )
        try:
            result = server.probe_transcript(
                {
                    "wav_path": str(probe_path),
                    "duration_seconds": duration_seconds,
                }
            )
            if bool(result.get("accepted")):
                _http_json("POST", f"{tiny_url}/stop", {"reason": f"nc microphone accepted {duration_seconds:.1f}s speech probe"})
                logger = getattr(getattr(self, "context", None), "logger", None)
                if logger:
                    logger.info("TinyMVP NC microphone interrupted playback after accepted %.1fs probe: %s", duration_seconds, result.get("input_text") or "")
        finally:
            self._cleanup_tiny_mvp_local_mic_wav(probe_path, settings)
        return True

    @staticmethod
    def _tiny_mvp_reply_immunity_elapsed(state: dict[str, Any], playback: dict[str, Any]) -> bool:
        immunity_seconds = _float_setting(playback.get("reply_immunity_seconds"), 0.0)
        if immunity_seconds <= 0:
            return True
        owner_id = str((state or {}).get("playback_owner_id") or "").strip()
        participants = (state or {}).get("participants")
        if not owner_id or not isinstance(participants, list):
            return True
        owner = next((item for item in participants if isinstance(item, dict) and str(item.get("id") or "") == owner_id), None)
        updated_at = str((owner or {}).get("updated_at") or "").strip()
        if not updated_at:
            return True
        try:
            started = datetime.fromisoformat(updated_at)
        except ValueError:
            return True
        now = datetime.now(started.tzinfo) if started.tzinfo is not None else datetime.now()
        return (now - started).total_seconds() >= immunity_seconds

    def _submit_tiny_mvp_local_mic_wav(self, wav_path: Path, settings: dict[str, Any]) -> None:
        logger = getattr(getattr(self, "context", None), "logger", None)
        instance = self._tiny_mvp_route_instance()
        if instance is None or instance.runtime_server is None:
            return
        tiny_url = str(_get(settings, "tiny_mvp.url", "http://127.0.0.1:8788") or "http://127.0.0.1:8788").rstrip("/")
        state = _http_json("GET", f"{tiny_url}/state")
        participants = list((state or {}).get("participants") or [])
        tiny_mvp = settings.get("tiny_mvp") if isinstance(settings.get("tiny_mvp"), dict) else {}
        user_id = str(tiny_mvp.get("mic_user_id") or "rakila").strip() or "rakila"
        speaker_name = str(tiny_mvp.get("mic_user_name") or "Rakila").strip() or "Rakila"
        if _tiny_mvp_participant_is_muted(state, user_id):
            if logger:
                logger.info("TinyMVP NC microphone ignored muted participant %s.", speaker_name)
            _http_json(
                "POST",
                f"{tiny_url}/decision",
                {"source_id": user_id, "target_id": "", "answer": False, "reason": "muted_speaker"},
            )
            self._cleanup_tiny_mvp_local_mic_wav(wav_path, settings)
            return
        if _tiny_mvp_current_speaker_blocks_user(state, user_id):
            if logger:
                logger.info("TinyMVP NC microphone ignored %s because the current speaker is protected.", speaker_name)
            _http_json(
                "POST",
                f"{tiny_url}/decision",
                {"source_id": user_id, "target_id": "", "answer": False, "reason": "current_speaker_protected"},
            )
            self._cleanup_tiny_mvp_local_mic_wav(wav_path, settings)
            return
        duration_seconds = _wav_duration_seconds(wav_path)
        capture = settings.get("capture") if isinstance(settings.get("capture"), dict) else {}
        min_turn_seconds = _float_setting(capture.get("min_turn_seconds"), 0.6)
        if duration_seconds < min_turn_seconds:
            if logger:
                logger.info("TinyMVP NC microphone ignored %.2fs capture below minimum %.2fs.", duration_seconds, min_turn_seconds)
            self._cleanup_tiny_mvp_local_mic_wav(wav_path, settings)
            return
        route_key = f"tinymvp_nc_mic_{user_id}_{int(time.time() * 1000)}_{secrets.token_hex(3)}"
        payload = {
            "route_key": route_key,
            "user_id": user_id,
            "speaker_name": speaker_name,
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "wav_path": str(wav_path),
            "duration_seconds": duration_seconds,
            "participants": participants,
            "room_context": _tiny_mvp_room_context(participants),
        }
        decision = instance.runtime_server.route_turn(payload)
        input_text = str(decision.get("input_text") or "").strip()
        speech_accepted = bool(decision.get("speech_accepted"))
        if input_text and speech_accepted:
            _http_json("POST", f"{tiny_url}/speech", {"speaker_id": user_id, "text": input_text, "reason": "nc microphone"})
            self._record_tiny_mvp_user_turn_for_all_instances(decision, route_key)
            self._maybe_stop_tiny_mvp_playback_for_user_speech(tiny_url, settings, duration_seconds)
        target_id = _safe_instance_id(decision.get("target_bot_id") or "")
        reason = str(decision.get("reason") or "nc microphone route").strip()
        if bool(decision.get("answer")) and target_id:
            _http_json("POST", f"{tiny_url}/route", {"target_id": target_id, "reason": reason})
            if logger:
                logger.info("TinyMVP NC microphone routed %s -> %s: %s", speaker_name, target_id, reason)
        else:
            _http_json(
                "POST",
                f"{tiny_url}/decision",
                {"source_id": user_id, "target_id": target_id, "answer": False, "reason": reason},
            )
            if input_text and speech_accepted:
                self._maybe_recover_tiny_mvp_dead_air(tiny_url, settings, reason)
            if logger:
                logger.info("TinyMVP NC microphone no-route for %s: %s", speaker_name, reason)
        self._cleanup_tiny_mvp_local_mic_wav(wav_path, settings)

    def _tiny_mvp_route_instance(self) -> BridgeInstance | None:
        for instance in list(getattr(self, "_bridge_instances", []) or []):
            if _bridge_mode(instance.settings) != "tiny_mvp":
                continue
            if instance.runtime_server is not None and getattr(instance.runtime_server, "running", False):
                return instance
        return None

    def _record_tiny_mvp_user_turn_for_all_instances(self, decision: dict[str, Any], route_key: str) -> None:
        context_text = str(decision.get("context_input_text") or "").strip()
        input_text = str(decision.get("input_text") or "").strip()
        speaker_name = str(decision.get("speaker_name") or "").strip()
        user_id = str(decision.get("user_id") or "").strip()
        captured_at = datetime.now().isoformat(timespec="seconds")
        selected_id = _safe_instance_id(decision.get("target_bot_id") or "") if bool(decision.get("answer")) else ""
        for instance in list(getattr(self, "_bridge_instances", []) or []):
            if selected_id and instance.instance_id == selected_id:
                continue
            server = getattr(instance, "runtime_server", None)
            if server is None or not hasattr(server, "record_user_turn"):
                continue
            try:
                server.record_user_turn(
                    {
                        "route_key": route_key,
                        "context_input_text": context_text,
                        "input_text": input_text,
                        "speaker_name": speaker_name,
                        "user_id": user_id,
                        "captured_at": captured_at,
                    }
                )
            except Exception:
                continue

    @staticmethod
    def _maybe_stop_tiny_mvp_playback_for_user_speech(tiny_url: str, settings: dict[str, Any], duration_seconds: float) -> None:
        playback = settings.get("playback") if isinstance(settings.get("playback"), dict) else {}
        capture = settings.get("capture") if isinstance(settings.get("capture"), dict) else {}
        min_turn = _float_setting(capture.get("min_turn_seconds"), 0.6)
        interrupt_after = _float_setting(playback.get("interrupt_after_seconds"), 4.0)
        if not _bool_setting(playback.get("interrupt_reply_on_user_speech"), True):
            return
        if duration_seconds < max(min_turn, interrupt_after):
            return
        _http_json("POST", f"{tiny_url}/stop", {"reason": f"nc microphone user speech {duration_seconds:.1f}s"})

    @staticmethod
    def _maybe_recover_tiny_mvp_dead_air(tiny_url: str, settings: dict[str, Any], reason: str) -> None:
        router = settings.get("room_router") if isinstance(settings.get("room_router"), dict) else {}
        recovery = router.get("dead_air_recovery") if isinstance(router.get("dead_air_recovery"), dict) else {}
        if not _bool_setting(recovery.get("enabled"), False):
            return
        trigger_mode = str(recovery.get("trigger_mode") or "no_route_after_bot_speech").strip().lower()
        if trigger_mode not in {"no_route_after_any_speech", "any_speech", "bot_or_human"}:
            return
        _http_json("POST", f"{tiny_url}/dead-air", {"reason": f"dead_air_recovery:{reason}"})

    @staticmethod
    def _cleanup_tiny_mvp_local_mic_wav(wav_path: Path, settings: dict[str, Any]) -> None:
        capture = settings.get("capture") if isinstance(settings.get("capture"), dict) else {}
        if _bool_setting(capture.get("save_captures"), True):
            return
        try:
            wav_path.unlink(missing_ok=True)
        except Exception:
            pass


def _should_start_bridge(settings):
    if not isinstance(settings, dict):
        return False
    return bool(settings.get("start_on_nc_launch") or settings.get("auto_start_bridge"))


def _bridge_instances_from_settings(settings: dict[str, Any], *, force: bool = False) -> list[BridgeInstance]:
    if not isinstance(settings, dict):
        return []
    bots = settings.get("bots")
    if isinstance(bots, list) and bots:
        base = copy.deepcopy(settings)
        base.pop("bots", None)
        router_candidates = _room_router_candidates_from_bots(bots)
        instances: list[BridgeInstance] = []
        for index, bot_settings in enumerate(bots):
            if not isinstance(bot_settings, dict):
                continue
            if bot_settings.get("enabled") is False:
                continue
            merged = _deep_merge(base, bot_settings)
            if not force and not _should_start_bridge(merged):
                continue
            instance_id = _safe_instance_id(bot_settings.get("id") or bot_settings.get("name") or f"bot_{index + 1}")
            _normalize_discord_settings(merged)
            _normalize_instance_runtime(merged, index, force_port_offset=not _bot_has_explicit_port(bot_settings))
            _attach_room_router_candidates(merged, router_candidates)
            settings_path = _write_instance_settings(instance_id, merged)
            instances.append(
                BridgeInstance(
                    instance_id=instance_id,
                    settings=merged,
                    settings_path=settings_path,
                    bridge_token=secrets.token_urlsafe(32),
                )
            )
        return instances

    if not force and not _should_start_bridge(settings):
        return []
    merged = copy.deepcopy(settings)
    _normalize_discord_settings(merged)
    _normalize_instance_runtime(merged, 0, force_port_offset=False)
    settings_path = _write_instance_settings("default", merged)
    return [
        BridgeInstance(
            instance_id="default",
            settings=merged,
            settings_path=settings_path,
            bridge_token=secrets.token_urlsafe(32),
        )
    ]


def _effective_bridge_settings(settings: dict[str, Any], *, force: bool = False) -> list[tuple[str, dict[str, Any], int]]:
    if not isinstance(settings, dict):
        return []
    bots = settings.get("bots")
    if isinstance(bots, list) and bots:
        base = copy.deepcopy(settings)
        base.pop("bots", None)
        results: list[tuple[str, dict[str, Any], int]] = []
        for index, bot_settings in enumerate(bots):
            if not isinstance(bot_settings, dict):
                continue
            if bot_settings.get("enabled") is False:
                continue
            merged = _deep_merge(base, bot_settings)
            if not force and not _should_start_bridge(merged):
                continue
            instance_id = _safe_instance_id(bot_settings.get("id") or bot_settings.get("name") or f"bot_{index + 1}")
            _normalize_discord_settings(merged)
            _normalize_instance_runtime(merged, index, force_port_offset=not _bot_has_explicit_port(bot_settings))
            results.append((instance_id, merged, index))
        router_candidates = _room_router_candidates_from_bots([item for _instance_id, item, _index in results])
        for _instance_id, item, _index in results:
            _attach_room_router_candidates(item, router_candidates)
        return results
    if not force and not _should_start_bridge(settings):
        return []
    merged = copy.deepcopy(settings)
    _normalize_discord_settings(merged)
    _normalize_instance_runtime(merged, 0, force_port_offset=False)
    return [("default", merged, 0)]


def _room_router_candidates_from_bots(bots: list[Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, bot_settings in enumerate(bots):
        if not isinstance(bot_settings, dict) or bot_settings.get("enabled") is False:
            continue
        instance_id = _safe_instance_id(bot_settings.get("id") or bot_settings.get("name") or f"bot_{index + 1}")
        persona = bot_settings.get("persona") if isinstance(bot_settings.get("persona"), dict) else {}
        response_filter = bot_settings.get("response_filter") if isinstance(bot_settings.get("response_filter"), dict) else {}
        call_names = str(bot_settings.get("call_names") or response_filter.get("bot_names") or bot_settings.get("name") or instance_id).strip()
        nc_runtime = bot_settings.get("nc_runtime") if isinstance(bot_settings.get("nc_runtime"), dict) else {}
        host = str(nc_runtime.get("host") or "127.0.0.1").strip() or "127.0.0.1"
        try:
            port = int(nc_runtime.get("port") or 0)
        except (TypeError, ValueError):
            port = 0
        http_endpoint = str(nc_runtime.get("http_endpoint") or "").strip()
        if not http_endpoint and port > 0:
            http_endpoint = f"http://{host}:{port}/turn"
        candidates.append(
            {
                "id": instance_id,
                "name": str(bot_settings.get("name") or instance_id).strip() or instance_id,
                "call_names": call_names,
                "persona_hint": _compact_router_persona_hint(str(persona.get("system_prompt") or "")),
                "nc_runtime": {
                    "host": host,
                    "port": port,
                    "http_endpoint": http_endpoint,
                },
            }
        )
    return candidates


def _attach_room_router_candidates(settings: dict[str, Any], candidates: list[dict[str, Any]]) -> None:
    room_router = settings.setdefault("room_router", {})
    if not isinstance(room_router, dict):
        room_router = {}
        settings["room_router"] = room_router
    room_router["candidate_bots"] = copy.deepcopy(candidates)


def _compact_router_persona_hint(text: str, *, limit: int = 500) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _validate_bridge_settings(settings: dict[str, Any], *, force: bool = False) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    effective = _effective_bridge_settings(settings, force=force)
    if not effective:
        issues.append({"severity": "warning", "scope": "general", "message": "No enabled Discord bot instances are configured to start."})
        return issues

    ports: dict[str, str] = {}
    instance_ids: dict[str, int] = {}
    for instance_id, item, _index in effective:
        tiny_mode = _bridge_mode(item) == "tiny_mvp"
        instance_ids[instance_id] = instance_ids.get(instance_id, 0) + 1
        if instance_ids[instance_id] > 1:
            issues.append(
                {
                    "severity": "error",
                    "scope": instance_id,
                    "message": f"{instance_id}: duplicate bot instance ID after normalization. Each enabled bot needs a unique Bot ID or name.",
                }
            )

        discord = item.get("discord") if isinstance(item.get("discord"), dict) else {}
        runtime = item.get("nc_runtime") if isinstance(item.get("nc_runtime"), dict) else {}
        if not tiny_mode:
            token = str(discord.get("token") or "").strip()
            token_env_var = str(discord.get("token_env_var") or "DISCORD_TOKEN").strip() or "DISCORD_TOKEN"
            if not token and not os.environ.get(token_env_var):
                issues.append(
                    {
                        "severity": "error",
                        "scope": instance_id,
                        "message": f"{instance_id}: Discord token not found. Set environment variable {token_env_var} or enter a local test token.",
                    }
                )
            if not str(discord.get("guild_id") or "").strip():
                issues.append({"severity": "error", "scope": instance_id, "message": f"{instance_id}: Discord guild/server ID is required."})
            if not str(discord.get("voice_channel_id") or "").strip():
                issues.append({"severity": "error", "scope": instance_id, "message": f"{instance_id}: Discord voice channel ID is required."})

        host = str(runtime.get("host") or "127.0.0.1").strip() or "127.0.0.1"
        allow_non_localhost = bool(runtime.get("allow_non_localhost"))
        if not _runtime_host_is_loopback(host):
            severity = "warning" if allow_non_localhost else "error"
            suffix = "localhost is recommended for security." if allow_non_localhost else "enable the advanced non-localhost override only on a trusted private network."
            issues.append(
                {
                    "severity": severity,
                    "scope": instance_id,
                    "message": f"{instance_id}: runtime host is {host!r}; {suffix}",
                }
            )
        try:
            port = int(runtime.get("port"))
        except (TypeError, ValueError):
            issues.append({"severity": "error", "scope": instance_id, "message": f"{instance_id}: runtime port is invalid."})
            continue
        if port < 1 or port > 65535:
            issues.append({"severity": "error", "scope": instance_id, "message": f"{instance_id}: runtime port must be between 1 and 65535."})
        port_key = f"{host}:{port}"
        if port_key in ports:
            issues.append(
                {
                    "severity": "error",
                    "scope": instance_id,
                    "message": f"{instance_id}: runtime port {port_key} is already used by {ports[port_key]}.",
                }
            )
        ports[port_key] = instance_id

        persona = item.get("persona") if isinstance(item.get("persona"), dict) else {}
        voice_clone_wav = str(persona.get("voice_clone_wav") or "").strip() if isinstance(persona, dict) else ""
        issues.extend(_voice_clone_wav_issues(voice_clone_wav, scope=instance_id))
    return issues


def _bridge_mode(settings: dict[str, Any] | None) -> str:
    return str((settings or {}).get("bridge_mode") or "mock").strip().lower()


def _tiny_mvp_bridge_script(settings: dict[str, Any] | None = None) -> Path:
    tiny_mvp = (settings or {}).get("tiny_mvp") if isinstance(settings, dict) else {}
    configured = ""
    if isinstance(tiny_mvp, dict):
        configured = str(tiny_mvp.get("bridge_script") or "").strip()
    if configured:
        return Path(configured).expanduser()
    for candidate in (
        DEFAULT_TINY_MVP_BRIDGE_SCRIPT,
        Path(r"D:\tools\python_scripts\TinyMVP\tiny_voice_bridge.py"),
    ):
        if candidate.exists():
            return candidate
    return DEFAULT_TINY_MVP_BRIDGE_SCRIPT


def _transport_environment_issues(
    settings: dict[str, Any],
    *,
    require_install: bool = False,
) -> list[dict[str, str]]:
    if _bridge_mode(settings) != "tiny_mvp":
        return _node_bridge_environment_issues(require_install=require_install)
    issues: list[dict[str, str]] = []
    script = _tiny_mvp_bridge_script(settings)
    if not script.exists():
        issues.append(
            {
                "severity": "error",
                "scope": "tiny_mvp",
                "message": f"TinyMVP bridge script is missing: {script}",
            }
        )
    if not shutil.which("python") and not Path(sys.executable).exists():
        issues.append(
            {
                "severity": "error",
                "scope": "tiny_mvp",
                "message": "Python was not found for TinyMVP bridge launch.",
            }
        )
    return issues


def _voice_clone_wav_issues(
    configured: str,
    *,
    scope: str,
    app_root: Path | None = None,
) -> list[dict[str, str]]:
    value = str(configured or "").strip()
    if not value:
        return []
    root = (app_root or ADDON_DIR.parent.parent).resolve()
    voices_root = (root / "voices").resolve()
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve()
        location_hint = str(resolved)
    else:
        resolved = (voices_root / candidate).resolve()
        location_hint = f"{value} in {voices_root}"
        try:
            if not resolved.is_relative_to(voices_root):
                return [
                    {
                        "severity": "warning",
                        "scope": scope,
                        "message": f"{scope}: voice clone WAV path should stay inside the root voices folder for relative names: {value}",
                    }
                ]
        except AttributeError:
            if os.path.commonpath([str(resolved), str(voices_root)]) != str(voices_root):
                return [
                    {
                        "severity": "warning",
                        "scope": scope,
                        "message": f"{scope}: voice clone WAV path should stay inside the root voices folder for relative names: {value}",
                    }
                ]
    if resolved.suffix.lower() != ".wav":
        return [
            {
                "severity": "warning",
                "scope": scope,
                "message": f"{scope}: voice clone file should be a .wav file: {value}",
            }
        ]
    if not resolved.is_file():
        return [
            {
                "severity": "warning",
                "scope": scope,
                "message": f"{scope}: voice clone WAV was not found ({location_hint}); the selected NC Persona voice will be used instead.",
            }
        ]
    return []


def _node_bridge_environment_issues(
    *,
    bridge_dir: Path = NODE_BRIDGE_DIR,
    require_install: bool = False,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not shutil.which("node"):
        issues.append(
            {
                "severity": "error",
                "scope": "node_bridge",
                "message": "Node.js was not found on PATH. Install Node.js or add node.exe to PATH before starting the Discord bridge.",
            }
        )

    script = bridge_dir / "src" / "index.js"
    if not script.exists():
        issues.append(
            {
                "severity": "error",
                "scope": "node_bridge",
                "message": f"Node bridge script is missing: {script}",
            }
        )

    package_json = bridge_dir / "package.json"
    if not package_json.exists():
        issues.append(
            {
                "severity": "error",
                "scope": "node_bridge",
                "message": f"Node bridge package.json is missing: {package_json}",
            }
        )
        return issues

    dependency_severity = "error" if require_install else "warning"
    node_modules = bridge_dir / "node_modules"
    install_hint = f"Run npm install in {bridge_dir}."
    if not node_modules.exists():
        issues.append(
            {
                "severity": dependency_severity,
                "scope": "node_bridge",
                "message": f"Node bridge dependencies are not installed. {install_hint}",
            }
        )
        return issues

    missing = [
        package
        for package in NODE_BRIDGE_REQUIRED_PACKAGES
        if not (node_modules / Path(*package.split("/"))).exists()
    ]
    if missing:
        issues.append(
            {
                "severity": dependency_severity,
                "scope": "node_bridge",
                "message": f"Node bridge dependencies are incomplete ({', '.join(missing)} missing). {install_hint}",
            }
        )
    return issues


def _write_instance_settings(instance_id: str, settings: dict[str, Any]) -> Path:
    INSTANCE_SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    payload = copy.deepcopy(settings)
    payload.pop("bots", None)
    discord = payload.get("discord")
    if isinstance(discord, dict):
        discord.pop("token", None)
    path = INSTANCE_SETTINGS_DIR / f"{_safe_instance_id(instance_id)}.settings.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)
        handle.write("\n")
    return path


def _read_instance_status(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _runtime_server_status(instance: BridgeInstance) -> dict[str, Any]:
    server = getattr(instance, "runtime_server", None)
    if server is None or not hasattr(server, "status_snapshot"):
        return {}
    try:
        status = server.status_snapshot()
    except Exception:
        return {}
    return status if isinstance(status, dict) else {}


def _bridge_instance_is_running(instance: BridgeInstance) -> bool:
    process = getattr(instance, "process", None)
    if process is not None and process.poll() is None:
        return True
    server = getattr(instance, "runtime_server", None)
    return bool(server is not None and getattr(server, "running", False))


def _delete_instance_history_file(instance_id: str) -> None:
    safe_id = _safe_instance_id(instance_id)
    for history_path in (
        INSTANCE_SETTINGS_DIR / f"{safe_id}.history.json",
        *INSTANCE_SETTINGS_DIR.glob(f"{safe_id}__channel_*.history.json"),
    ):
        history_path.unlink(missing_ok=True)


def _normalize_instance_runtime(settings: dict[str, Any], index: int, *, force_port_offset: bool) -> None:
    nc_runtime = settings.setdefault("nc_runtime", {})
    if not isinstance(nc_runtime, dict):
        nc_runtime = {}
        settings["nc_runtime"] = nc_runtime
    host = str(nc_runtime.get("host") or "127.0.0.1").strip() or "127.0.0.1"
    try:
        raw_port = nc_runtime.get("port")
        if raw_port in {None, ""}:
            endpoint_text = str(nc_runtime.get("http_endpoint") or nc_runtime.get("endpoint") or "")
            match = re.search(r":(\d+)(?:/|$)", endpoint_text)
            raw_port = match.group(1) if match else 8768
        base_port = int(raw_port)
    except (TypeError, ValueError):
        base_port = 8768
    port = 8768 + int(index) if force_port_offset else base_port
    nc_runtime["host"] = host
    nc_runtime["port"] = port
    nc_runtime["allow_non_localhost"] = bool(nc_runtime.get("allow_non_localhost"))
    nc_runtime["http_endpoint"] = f"http://{host}:{port}/turn"
    nc_runtime["endpoint"] = f"ws://{host}:{port}/discord-voice"
    nc_runtime["session_mode"] = "isolated_discord"


def _bot_has_explicit_port(bot_settings: dict[str, Any]) -> bool:
    nc_runtime = bot_settings.get("nc_runtime")
    return isinstance(nc_runtime, dict) and (
        "port" in nc_runtime
        or "http_endpoint" in nc_runtime
        or "endpoint" in nc_runtime
    )


def _normalize_discord_settings(settings: dict[str, Any]) -> None:
    discord = settings.get("discord")
    if not isinstance(discord, dict):
        return
    token_env_var = str(discord.get("token_env_var") or "").strip()
    token = str(discord.get("token") or "").strip()
    if _looks_like_discord_token(token_env_var) and not token:
        discord["token"] = token_env_var
        discord["token_env_var"] = "DISCORD_TOKEN"


def _safe_instance_id(value: Any) -> str:
    text = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "").strip()).strip("._-")
    return text.lower() or "bot"


def _looks_like_discord_token(value: str) -> bool:
    text = str(value or "").strip()
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{20,}", text))


def _runtime_host_is_loopback(value: str) -> bool:
    host = str(value or "").strip()
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _redact_runtime_log_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(
        r"([A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{5,}\.)[A-Za-z0-9_-]{20,}",
        r"\1<redacted>",
        value,
    )
    value = re.sub(r'("token"\s*:\s*")[^"]+', r'\1<redacted>', value, flags=re.IGNORECASE)
    value = re.sub(r"(authorization\s*:\s*bearer\s+)[^\s]+", r"\1<redacted>", value, flags=re.IGNORECASE)
    return value


def _http_json(method: str, url: str, payload: dict[str, Any] | None = None, *, timeout: float = 5.0) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(str(url), data=data, headers=headers, method=str(method or "GET").upper())
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    decoded = json.loads(raw or "{}")
    return decoded if isinstance(decoded, dict) else {}


def _wav_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            frames = handle.getnframes()
        return frames / float(rate) if rate else 0.0
    except Exception:
        return 0.0


def _tiny_mvp_room_context(participants: list[Any]) -> dict[str, Any]:
    return {
        "source": "TinyMVP NC microphone",
        "participants": [
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or item.get("id") or ""),
                "kind": str(item.get("kind") or item.get("type") or ""),
                "connected": bool(item.get("connected", True)),
                "current": bool(item.get("current")),
                "next": bool(item.get("next")),
            }
            for item in participants
            if isinstance(item, dict)
        ],
    }


def _tiny_mvp_participant_is_muted(state: dict[str, Any], participant_id: str) -> bool:
    participant_id = str(participant_id or "").strip()
    if not participant_id or not isinstance(state, dict):
        return False
    moderator_state = state.get("moderator_state") if isinstance(state.get("moderator_state"), dict) else {}
    participants = state.get("participants") if isinstance(state.get("participants"), list) else []
    participant = next(
        (item for item in participants if isinstance(item, dict) and str(item.get("id") or "").strip() == participant_id),
        {},
    )
    is_human = str((participant or {}).get("kind") or "").strip().lower() == "human"
    key = "muted_speaker_user_ids" if is_human else "muted_bot_ids"
    muted = {str(item or "").strip() for item in moderator_state.get(key, []) if str(item or "").strip()}
    return participant_id in muted


def _tiny_mvp_current_speaker_blocks_user(state: dict[str, Any], participant_id: str) -> bool:
    participant_id = str(participant_id or "").strip()
    if not participant_id or not isinstance(state, dict):
        return False
    active_id = str(state.get("playback_owner_id") or state.get("current_id") or "").strip()
    if not active_id or active_id == participant_id:
        return False
    moderator_state = state.get("moderator_state") if isinstance(state.get("moderator_state"), dict) else {}
    if "allow_current_interruption" not in moderator_state:
        return False
    return not _bool_setting(moderator_state.get("allow_current_interruption"), False)


def _bool_setting(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in {None, ""}:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _float_setting(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _int_setting(value: Any, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _get(payload: dict[str, Any], dotted: str, default: Any = None) -> Any:
    current: Any = payload
    for key in str(dotted or "").split("."):
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged
