"""Native QML LAN and Internet controls for Main Chat Remote."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from addons.main_chat_remote.media_quality import PRESETS, load_quality, save_quality
from addons.main_chat_remote.idle_cache_settings import DEFAULT as IDLE_DEFAULT, load_settings, save_settings
from addons.main_chat_remote.traffic_usage import TrafficDashboard, empty
from typing import Any, Callable, Mapping

from PySide6 import QtGui

from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.adapters.config import RuntimeConfigNativeAdapter
from ui.qml_bridge.native_contracts import (
    NativeChoice,
    NativeControl,
    NativeControlKind,
    NativeSurface,
)
from ui.qml_bridge.native_registry import NativeSurfaceAdapter


_INTERNET_FIELDS = {
    "main_chat_internet_ddns": "ddns_hostname",
    "main_chat_internet_public_ip": "public_ip",
    "main_chat_internet_external_port": "external_port",
    "main_chat_internet_email": "account_email",
    "main_chat_internet_terms": "terms_accepted",
    "main_chat_internet_confirm_ip": "confirm_ip_changes",
    "main_chat_internet_gateway_port": "gateway_port",
    "main_chat_internet_acme_port": "acme_port",
}


class MainChatRemoteNativeAdapter(NativeSurfaceAdapter):
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
        self._internet_draft: dict[str, object] = {}
        self._internet_draft_ready = False
        self._selected_enrollment = ""
        self._selected_device = ""
        self._show_backend_command = False
        self._show_advanced_ports = False
        self._traffic = None
        self._media_root = None

    def _invoke(self, capability: str, payload=None) -> object:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id,
            capability,
            dict(payload or {}),
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "Main Chat Remote is unavailable."))
            )
        return result.value

    def _snapshot_payload(self) -> dict[str, object]:
        value = self._invoke("runtime.main_chat_remote.snapshot")
        if not isinstance(value, Mapping):
            raise RuntimeError("Main Chat Remote snapshot is not a mapping.")
        payload = dict(value)
        info = payload.get('bridge_info_path')
        if isinstance(info, str) and info:
            root = Path(info).parent
            if self._media_root != root:
                self._media_root = root
                self._traffic = TrafficDashboard(root)
        payload['traffic'] = self._traffic.snapshot() if self._traffic else empty()
        payload['media_quality'] = load_quality(self._media_root) if self._media_root else dict(preset='balanced', **PRESETS['balanced'])
        payload['idle_cache_settings'] = load_settings(self._media_root) if self._media_root else dict(IDLE_DEFAULT)
        return payload

    @staticmethod
    def _status_lines(payload: Mapping[str, object]) -> dict[str, str]:
        bridge = dict(payload.get("bridge") or {})
        backend = dict(payload.get("backend") or {})
        internet = dict(payload.get("internet") or {})
        gateway = dict(internet.get("gateway") or {})
        certificate = dict(internet.get("certificate") or {})
        settings = dict(internet.get("settings") or {})
        health = dict(backend.get("health") or {})
        delivery = dict(dict(dict(health.get("payload") or {}).get("remote") or {}).get("musetalk_delivery") or {})
        delivery_status = str(delivery.get("status") or "unknown") if backend.get("running") else "stopped"
        delivery_reason = str(delivery.get("reason") or "") if backend.get("running") else ""
        backend_task = str(payload.get("backend_task") or "")
        backend_message = str(backend.get("last_message") or "")
        certificate_status = str(certificate.get("status") or "not checked").replace("_", " ")
        bridge_status = (
            f"Desktop bridge: {'running' if bridge.get('running') else 'stopped'}\n"
            f"Local NC URL: {bridge.get('url', '')}"
        )
        backend_status = (
            f"Phone backend: {'running' if backend.get('running') else 'stopped'}"
            f"{' (' + backend_task + ')' if backend_task else ''}\n"
            f"Phone app URL: {backend.get('display_url', '')}\n"
            f"Connection health: {health.get('status', 'unknown')}"
            f"\nMuseTalk video delivery: {delivery_status}"
            f"{' — ' + delivery_reason if delivery_reason else ''}"
            f"{chr(10) + 'Last: ' + backend_message if backend_message else ''}"
        )
        internet_status = (
            f"Saved: {'enabled' if settings.get('enabled') else 'disabled'}\n"
            f"Public gateway: {'running' if gateway.get('running') else 'closed'}\n"
            f"Certificate: {certificate_status}"
        )
        certificate_text = (
            f"Verified helper: {'installed' if certificate.get('helper_installed') else 'not installed'}\n"
            f"Production certificate: {'active' if certificate.get('certificate_exists') else 'not active'}"
        )
        router = (
            f"Forward TCP {int(settings.get('external_port') or 443)} to this PC's TCP "
            f"{int(settings.get('gateway_port') or 8788)}. During certificate issue or "
            f"renewal, forward public TCP 80 to local TCP "
            f"{int(settings.get('acme_port') or 8780)}."
        )
        return {
            "bridge": bridge_status,
            "backend": backend_status,
            "internet": internet_status,
            "certificate": certificate_text,
            "router": router,
        }

    @staticmethod
    def _options(items: object, id_key: str, label_key: str) -> tuple[NativeChoice, ...]:
        result = []
        for raw in list(items or []):
            item = dict(raw or {})
            value = str(item.get(id_key) or "").strip()
            if not value:
                continue
            label = str(item.get(label_key) or "Unnamed phone")
            device_id = str(item.get("device_id") or "")
            if device_id and device_id not in label:
                label = f"{label} ({device_id})"
            if item.get("revoked"):
                label += " - revoked"
            result.append(NativeChoice(value, label))
        return tuple(result)

    def snapshot(self) -> NativeSurface:
        payload = self._snapshot_payload()
        bridge = dict(payload.get("bridge") or {})
        backend = dict(payload.get("backend") or {})
        internet = dict(payload.get("internet") or {})
        settings = dict(internet.get("settings") or {})
        if not self._internet_draft_ready:
            self._internet_draft = dict(settings)
            self._internet_draft_ready = True
        status = self._status_lines(payload)
        busy = bool(payload.get("backend_task"))
        ready = bool(bridge.get("running") and backend.get("running") and dict(backend.get("health") or {}).get("ok"))
        connection = dict(payload.get("connection_result") or {})
        connection_text = (
            str(payload["backend_task"]) + "…" if busy else
            "Ready to pair. Open the phone app and scan the QR code below." if ready else
            str(connection.get("message")) if connection.get("accepted") is False else
            "Connect your phone and PC to the same network, then select Connect phone."
        )
        setup_uri = str(payload.get("pairing_setup_uri") or "")
        enrollment_uri = str(internet.get("enrollment_setup_uri") or "")
        pending = self._options(
            internet.get("pending_enrollments"),
            "enrollment_id",
            "device_name",
        )
        devices = self._options(internet.get("devices"), "device_id", "device_name")
        if self._selected_enrollment not in {str(item.value) for item in pending}:
            self._selected_enrollment = str(pending[0].value) if pending else ""
        if self._selected_device not in {str(item.value) for item in devices}:
            self._selected_device = str(devices[0].value) if devices else ""
        values: dict[str, object] = {
            'main_chat_soundscape_preview': json.dumps(dict(payload.get('soundscape_import') or {}), ensure_ascii=False),
            'main_chat_soundscape_status': str(dict(payload.get('soundscape_import') or {}).get('message') or ''),
            "main_chat_remote_connection": connection_text,
            "main_chat_remote_lan_intro": "LAN-first phone bridge. Pair on the same network before enabling Internet access.",
            "main_chat_remote_enabled": bool(bridge.get("enabled", False)),
            "main_chat_remote_bridge_status": status["bridge"],
            "main_chat_remote_bridge_info": str(payload.get("bridge_info_path") or ""),
            "main_chat_remote_pairing_code": str(payload.get("pending_pairing_code") or ""),
            "main_chat_remote_backend_status": status["backend"],
            "main_chat_remote_pairing_setup": setup_uri or "Start the phone backend to create a setup link.",
            "main_chat_remote_pairing_qr": str(payload.get("pairing_qr_data_uri") or ""),
            "main_chat_remote_test_checklist": "Test text, TTS audio, Visual Reply, and MuseTalk after pairing.",
            "main_chat_remote_backend_command": str(payload.get("backend_command") or ""),
            "main_chat_remote_show_backend_command": self._show_backend_command,
            "main_chat_internet_intro": "Optional secure Internet access. LAN pairing remains unchanged.",
            "main_chat_internet_enabled": bool(settings.get("enabled", False)),
            "main_chat_internet_show_advanced": self._show_advanced_ports,
            "main_chat_internet_certificate": status["certificate"],
            "main_chat_internet_router": status["router"],
            "main_chat_internet_enrollment_uri": enrollment_uri,
            "main_chat_internet_pending": self._selected_enrollment,
            "main_chat_internet_devices": self._selected_device,
            "main_chat_internet_status": status["internet"],
        }
        for control_id, setting_key in _INTERNET_FIELDS.items():
            values[control_id] = self._internet_draft.get(setting_key, settings.get(setting_key))
        for key, value in payload['media_quality'].items():
            values['main_chat_remote_quality_' + key] = value
        for key,value in payload['idle_cache_settings'].items():
            values['main_chat_remote_idle_'+key]=value
        controls = []
        for control in self._surface.controls:
            updates: dict[str, object] = {
                "value": values.get(control.id, control.default_value)
            }
            if control.id == "main_chat_remote_traffic":
                updates['metadata'] = payload['traffic']
            elif control.id == "main_chat_relay_status":
                relay = dict(payload.get("relay") or {})
                # Keep connection intent separate from the control enabled flag.
                relay["internet_enabled"] = bool(relay.get("enabled", False))
                updates["value"] = str(relay.get("message") or "Sign in to NC Relay.")
                updates["metadata"] = relay
            elif control.id == "main_chat_internet_pending":
                updates["choices"] = pending
            elif control.id == "main_chat_internet_devices":
                updates["choices"] = devices
            elif control.id == "main_chat_remote_connection":
                updates["metadata"] = {"ready": ready, "busy": busy,
                    "stopping": str(payload.get("backend_task") or "").lower().startswith("stopping"),
                    "bridgeRunning": bool(bridge.get("running")),
                    "backendRunning": bool(backend.get("running")),
                    "needsAttention": not busy and not ready and connection.get("accepted") is False}
            if control.id in {"main_chat_remote_connect", "main_chat_remote_prepare_backend",
                              "main_chat_remote_start_backend", "main_chat_remote_stop_backend",
                              "main_chat_remote_start_bridge", "main_chat_remote_stop_bridge",
                              "main_chat_remote_enabled", "main_chat_remote_pairing_code",
                              "main_chat_remote_generate_code"}:
                updates["enabled"] = not busy
            if control.id == "main_chat_remote_stop":
                relay = dict(payload.get("relay") or {})
                updates["enabled"] = not busy and not relay.get("busy") and bool(
                    bridge.get("running") or backend.get("running") or relay.get("enabled") or relay.get("online")
                    or relay.get("worker_running"))
            controls.append(replace(control, **updates))
        return replace(
            self._surface,
            controls=apply_card_layout(controls),
            revision=self._revision,
        )

    def _persist_state(self) -> None:
        if callable(self._persist):
            self._persist()

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        control = self._controls.get(key)
        if control is None or bool(control.metadata.get("readOnly")) or control.kind in {
            NativeControlKind.ACTION,
            NativeControlKind.DISPLAY,
        }:
            raise KeyError(f"Unknown Main Chat Remote setting '{control_id}'.")
        normalized = RuntimeConfigNativeAdapter._normalize(control, value)
        if key.startswith('main_chat_remote_idle_'):
            self._snapshot_payload()
            if self._media_root is None: raise RuntimeError('Desktop runtime is not ready')
            save_settings(self._media_root,{key.removeprefix('main_chat_remote_idle_'):normalized})
        elif key.startswith('main_chat_remote_quality_'):
            self._snapshot_payload()
            if self._media_root is None:
                raise RuntimeError('Desktop runtime is not ready')
            if normalized != 'custom':
                save_quality(self._media_root, {key.removeprefix('main_chat_remote_quality_'): normalized})
        elif key == "main_chat_remote_enabled":
            self._invoke(
                "runtime.main_chat_remote.set_bridge_enabled",
                {"enabled": bool(normalized)},
            )
            self._persist_state()
        elif key == "main_chat_remote_pairing_code":
            self._invoke(
                "runtime.main_chat_remote.set_pairing_code",
                {"value": str(normalized)},
            )
        elif key == "main_chat_remote_show_backend_command":
            self._show_backend_command = bool(normalized)
        elif key == "main_chat_internet_show_advanced":
            self._show_advanced_ports = bool(normalized)
        elif key == "main_chat_internet_enabled":
            self._internet_draft["enabled"] = bool(normalized)
            self._invoke(
                "runtime.main_chat_remote.apply_internet_settings",
                {"settings": dict(self._internet_draft)},
            )
        elif key in _INTERNET_FIELDS:
            self._internet_draft[_INTERNET_FIELDS[key]] = normalized
        elif key == "main_chat_internet_pending":
            self._selected_enrollment = str(normalized or "")
        elif key == "main_chat_internet_devices":
            self._selected_device = str(normalized or "")
        else:
            raise KeyError(f"Unknown Main Chat Remote setting '{control_id}'.")
        self._revision += 1
        self.changed.emit()

    @staticmethod
    def _clipboard_text(text: object) -> None:
        clipboard = QtGui.QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(str(text or ""))

    def _copy_diagnostics(self, payload: Mapping[str, object]) -> None:
        internet = dict(payload.get("internet") or {})
        settings = {
            key: value
            for key, value in dict(internet.get("settings") or {}).items()
            if key != "account_email"
        }
        public = {
            "lan": {
                "bridge_running": bool(dict(payload.get("bridge") or {}).get("running")),
                "backend_running": bool(dict(payload.get("backend") or {}).get("running")),
                "backend_task": str(payload.get("backend_task") or ""),
                "health_status": str(dict(dict(payload.get("backend") or {}).get("health") or {}).get("status") or "unknown"),
                "returncode": dict(payload.get("backend") or {}).get("returncode"),
            },
            "settings": settings,
            "gateway": dict(internet.get("gateway") or {}),
            "certificate": dict(internet.get("certificate") or {}),
            "task": str(internet.get("task") or ""),
            "last_error": str(internet.get("last_error") or ""),
        }
        self._clipboard_text(json.dumps(public, indent=2, sort_keys=True))

    def trigger_with_payload(self, control_id: str, payload: Any) -> None:
        if control_id == 'main_chat_soundscape_import':
            self._invoke('runtime.main_chat_remote.action', {'action': 'soundscape_import', 'payload': dict(payload or {})})
            self._revision += 1
            self.changed.emit()
            return
        if control_id == "main_chat_relay_action":
            request = dict(payload or {})
            action = str(request.pop("action", ""))
            self._invoke("runtime.main_chat_remote.action", {"action": "relay_" + action, "payload": request})
            self._revision += 1
            self.changed.emit()
            return
        super().trigger_with_payload(control_id, payload)

    def trigger(self, control_id: str) -> None:
        action_id = str(control_id or "").strip()
        payload = self._snapshot_payload()
        if action_id == 'main_chat_remote_idle_clear':
            if self._media_root is None: raise RuntimeError('Desktop runtime is not ready')
            save_settings(self._media_root,{'clear':True})
        elif action_id == 'main_chat_remote_traffic_reset':
            if self._traffic:
                self._traffic.reset()
        elif action_id == "main_chat_remote_copy_setup":
            self._clipboard_text(payload.get("pairing_setup_uri"))
        elif action_id == "main_chat_internet_copy_diagnostics":
            self._copy_diagnostics(payload)
        elif action_id == "main_chat_internet_save":
            self._invoke(
                "runtime.main_chat_remote.apply_internet_settings",
                {"settings": dict(self._internet_draft)},
            )
            self._persist_state()
        else:
            action_map = {
                "main_chat_remote_connect": "connect_phone",
                "main_chat_remote_stop": "stop_remote",
                "main_chat_remote_start_bridge": "start_bridge",
                "main_chat_remote_stop_bridge": "stop_bridge",
                "main_chat_remote_refresh": "refresh",
                "main_chat_remote_generate_code": "generate_pairing_code",
                "main_chat_remote_prepare_backend": "prepare_backend",
                "main_chat_remote_start_backend": "start_backend",
                "main_chat_remote_stop_backend": "stop_backend",
                "main_chat_internet_detect_ip": "detect_public_ip",
                "main_chat_internet_install_helper": "install_helper",
                "main_chat_internet_staging_test": "staging_test",
                "main_chat_internet_issue_certificate": "issue_certificate",
                "main_chat_internet_create_enrollment": "create_enrollment",
                "main_chat_internet_approve": "approve_enrollment",
                "main_chat_internet_reject": "reject_enrollment",
                "main_chat_internet_revoke": "revoke_device",
            }
            action = action_map.get(action_id)
            if action is None:
                raise KeyError(f"Unknown Main Chat Remote action '{control_id}'.")
            action_payload: dict[str, object] = {}
            if action in {"start_backend", "connect_phone"}:
                action_payload["pairing_code"] = str(
                    payload.get("pending_pairing_code") or ""
                )
            elif action in {"approve_enrollment", "reject_enrollment"}:
                if not self._selected_enrollment:
                    raise ValueError("Select a pending phone first.")
                action_payload["id"] = self._selected_enrollment
            elif action == "revoke_device":
                if not self._selected_device:
                    raise ValueError("Select a paired device first.")
                action_payload["id"] = self._selected_device
            self._invoke(
                "runtime.main_chat_remote.action",
                {"action": action, "payload": action_payload},
            )
        self._revision += 1
        self.changed.emit()


def _action(key: str, label: str, section: str, *, destructive=False) -> NativeControl:
    return NativeControl(
        key,
        label,
        NativeControlKind.ACTION,
        section,
        metadata={"destructive": destructive},
    )


def _display(key: str, label: str, section: str) -> NativeControl:
    return NativeControl(key, label, NativeControlKind.DISPLAY, section)


def build_main_chat_remote_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
) -> MainChatRemoteNativeAdapter:
    lan = "LAN"
    internet = "Internet"
    controls = [
        _action('main_chat_soundscape_import', 'Import background sounds', 'Media'),
        _display('main_chat_soundscape_status', 'Sound library', 'Media'),
        _display('main_chat_soundscape_preview', 'Sound import selection', 'Media'),
        NativeControl('main_chat_remote_idle_enabled','Cache idle animations on phone',NativeControlKind.BOOLEAN,'Media',default_value=True),
        _action('main_chat_remote_idle_clear','Clear idle cache on phones','Media'),
        _display('main_chat_remote_traffic', 'Data usage', 'Media'),
        _action('main_chat_remote_traffic_reset', 'Reset statistics', 'Media'),
        NativeControl('main_chat_remote_quality_preset', 'Quality preset', NativeControlKind.CHOICE, 'Media',
            default_value='balanced', choices=tuple(NativeChoice(v, label) for v, label in
                [('low', 'Low data'), ('balanced', 'Balanced (current default)'), ('high', 'High quality'), ('custom', 'Custom')])),
        NativeControl('main_chat_remote_quality_opus_kbps', 'Opus (kbit/s)', NativeControlKind.INTEGER, 'Media', minimum=16, maximum=96, step=8),
        NativeControl('main_chat_remote_quality_video_kbps', 'H.264 target (kbit/s)', NativeControlKind.INTEGER, 'Media', minimum=100, maximum=2000, step=100),
        NativeControl('main_chat_remote_quality_video_width', 'Video maximum width (px)', NativeControlKind.INTEGER, 'Media', minimum=160, maximum=448, step=2),
        NativeControl('main_chat_remote_quality_video_fps', 'Video frames per second', NativeControlKind.CHOICE, 'Media',
            choices=tuple(NativeChoice(v, str(v)) for v in (6, 8, 12, 24))),
        _display("main_chat_relay_status", "NC Relay", internet),
        _action("main_chat_relay_action", "NC Relay account", internet),
        _display("main_chat_remote_connection", "Connection progress", lan),
        _action("main_chat_remote_connect", "Connect phone", lan),
        _action("main_chat_remote_stop", "Stop Main Chat Remote", lan),
        _display("main_chat_remote_lan_intro", "Phone bridge", lan),
        NativeControl("main_chat_remote_enabled", "Enable desktop bridge", NativeControlKind.BOOLEAN, lan, default_value=False),
        _display("main_chat_remote_bridge_status", "Desktop bridge status", lan),
        _display("main_chat_remote_bridge_info", "Bridge information file", lan),
        _action("main_chat_remote_start_bridge", "Start desktop bridge", lan),
        _action("main_chat_remote_stop_bridge", "Stop bridge", lan, destructive=True),
        _action("main_chat_remote_refresh", "Refresh status", lan),
        NativeControl("main_chat_remote_pairing_code", "Pairing code", NativeControlKind.TEXT, lan, default_value="", minimum=4, maximum=9),
        _action("main_chat_remote_generate_code", "Generate new code", lan),
        _display("main_chat_remote_backend_status", "Phone backend status", lan),
        _action("main_chat_remote_prepare_backend", "Prepare phone backend", lan),
        _action("main_chat_remote_start_backend", "Start phone backend", lan),
        _action("main_chat_remote_stop_backend", "Stop phone backend", lan, destructive=True),
        _display("main_chat_remote_pairing_setup", "Phone setup link", lan),
        NativeControl(
            "main_chat_remote_pairing_qr",
            "Pairing QR",
            NativeControlKind.IMAGE,
            lan,
            metadata={
                "readOnly": True,
                "imagePreferredWidth": 240,
                "imagePreferredHeight": 240,
                "imagePlaceholder": "Start the phone backend to generate the pairing QR code.",
            },
        ),
        _action("main_chat_remote_copy_setup", "Copy setup link", lan, ),
        _display("main_chat_remote_test_checklist", "Connection test", lan),
        NativeControl("main_chat_remote_show_backend_command", "Show advanced backend command", NativeControlKind.BOOLEAN, lan, default_value=False),
        NativeControl("main_chat_remote_backend_command", "Backend command", NativeControlKind.MULTILINE, lan, metadata={"readOnly": True}),
        _display("main_chat_internet_intro", "Internet Remote", internet),
        NativeControl("main_chat_internet_enabled", "Enable saved Internet Remote", NativeControlKind.BOOLEAN, internet, default_value=False),
        NativeControl("main_chat_internet_ddns", "Dynamic DNS hostname", NativeControlKind.TEXT, internet),
        NativeControl("main_chat_internet_public_ip", "Public IP", NativeControlKind.TEXT, internet),
        NativeControl("main_chat_internet_external_port", "Public HTTPS port", NativeControlKind.INTEGER, internet, minimum=1, maximum=65535, default_value=443),
        NativeControl("main_chat_internet_email", "ACME email", NativeControlKind.TEXT, internet),
        NativeControl("main_chat_internet_terms", "I accept the certificate authority terms", NativeControlKind.BOOLEAN, internet, default_value=False),
        NativeControl("main_chat_internet_confirm_ip", "Ask before accepting a changed public IP", NativeControlKind.BOOLEAN, internet, default_value=True),
        NativeControl("main_chat_internet_show_advanced", "Show advanced local ports", NativeControlKind.BOOLEAN, internet, default_value=False),
        NativeControl("main_chat_internet_gateway_port", "HTTPS gateway", NativeControlKind.INTEGER, internet, minimum=1, maximum=65535, default_value=8788),
        NativeControl("main_chat_internet_acme_port", "Certificate HTTP challenge", NativeControlKind.INTEGER, internet, minimum=1, maximum=65535, default_value=8780),
        _action("main_chat_internet_save", "Save Internet settings", internet),
        _action("main_chat_internet_detect_ip", "Detect public IP", internet),
        _display("main_chat_internet_certificate", "Certificate status", internet),
        _action("main_chat_internet_install_helper", "Install verified helper", internet),
        _action("main_chat_internet_staging_test", "Run staging test", internet),
        _action("main_chat_internet_issue_certificate", "Issue production certificate", internet),
        _display("main_chat_internet_router", "Router setup", internet),
        _action("main_chat_internet_create_enrollment", "Create enrollment QR", internet),
        NativeControl("main_chat_internet_enrollment_uri", "Enrollment setup link", NativeControlKind.TEXT, internet, metadata={"readOnly": True}),
        NativeControl("main_chat_internet_pending", "Pending phones", NativeControlKind.LIST, internet),
        _action("main_chat_internet_approve", "Approve selected phone", internet),
        _action("main_chat_internet_reject", "Reject selected phone", internet, destructive=True),
        NativeControl("main_chat_internet_devices", "Paired Internet devices", NativeControlKind.LIST, internet),
        _action("main_chat_internet_revoke", "Revoke selected device", internet, destructive=True),
        _display("main_chat_internet_status", "Internet status", internet),
        _action("main_chat_internet_copy_diagnostics", "Copy redacted diagnostics", internet),
    ]
    surface = NativeSurface(
        id="main_chat_remote_tab",
        title="Main Chat Remote",
        addon_id="nc.main_chat_remote",
        sections=(lan, internet, 'Media'),
        description=(
            "LAN phone bridge with an optional secure Internet gateway for the "
            "NeuralCompanion main chat runtime."
        ),
        controls=tuple(controls),
    )
    return MainChatRemoteNativeAdapter(
        application_facade,
        surface,
        persist=persist,
    )


__all__ = ["MainChatRemoteNativeAdapter", "build_main_chat_remote_adapter"]
