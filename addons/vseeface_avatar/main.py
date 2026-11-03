from __future__ import annotations

import json
import weakref
import threading
from pathlib import Path

from core.addons.base import BaseAddon
from core import avatar_hand_state
from core.avatar_runtime import AvatarRuntimeContext
from addons.vseeface_avatar.body_profiles import complete_body_profile, complete_hand_calibration


PROVIDER_ID = "vseeface"


class Addon(BaseAddon):
    def __init__(self):
        super().__init__()
        self._bridge_lock = threading.RLock()
        self._bridge_generation = 0

    def initialize(self, context):
        super().initialize(context)
        app_root = getattr(context, "app_root", None)
        if app_root is None:
            app_root = Path(__file__).resolve().parents[2]
        self._app_root = Path(app_root)
        self._runtime_config = getattr(context.capabilities, "runtime_config", None)
        self._body_configs_dir = Path(app_root) / "body_configs"
        self._avatar_service = context.capabilities.avatar
        if self._avatar_service is None:
            context.logger.warning("VSeeFace avatar addon could not find qt.avatar_providers service.")
            return None

        self._avatar_service.register_provider(
            provider_id=PROVIDER_ID,
            label="VSeeFace",
            description="VSeeFace avatar control through VMC/OSC.",
            order=100,
            factory=self._create_adapter,
            construction_input_type=AvatarRuntimeContext,
            metadata={
                "kind": "avatar",
                "transport": "vmc_osc",
                "runtime_context": True,
                "native_qml": True,
            },
        )
        context.ui.register_manifest_designer_tab(
            id="vseeface_avatar_tab",
        )
        context.logger.info("VSeeFace avatar provider addon initialized.")
        return None

    def shutdown(self):
        self._disable_speech_bridge()
        avatar_service = getattr(self, "_avatar_service", None)
        if avatar_service is not None:
            try:
                avatar_service.unregister_provider(PROVIDER_ID)
            except Exception:
                pass
        return None

    def invoke_capability(self, capability, payload=None):
        capability = str(capability or "").strip()
        payload = dict(payload or {})
        if capability.startswith('runtime.speech_bridge.'):
            return self._speech_bridge_capability(capability.rsplit('.', 1)[1], payload)
        if capability == "runtime.estimate_overhead_gib":
            return 0.8
        if capability == "runtime.body_profiles.catalog":
            return self._body_profile_catalog()
        if capability == "runtime.body_profiles.load":
            return self._load_body_profile(payload.get("name"))
        if capability == "runtime.body_profiles.save":
            return self._save_body_profile(
                payload.get("name"),
                payload.get("profile") or {},
                payload.get("hands") or {},
            )
        if capability == "runtime.body_profiles.delete":
            return self._delete_body_profile(payload.get("name"))
        if capability == "runtime.hand.snapshot":
            return {
                "debug": dict(self._hand_debug_state()),
                "calibration": {
                    str(key): dict(value or {})
                    for key, value in self._hand_calibration_state().items()
                },
            }
        if capability == "runtime.hand.set_active":
            self._hand_debug_state()["active"] = bool(payload.get("active"))
            self._hand_debug_edited = True
            return bool(self._hand_debug_state()["active"])
        if capability == "runtime.hand.set_axis":
            key = str(payload.get("key") or "").strip()
            if key not in self._hand_debug_state() or key == "active":
                raise KeyError(f"Unknown hand debug axis: {key}")
            value = max(-180.0, min(180.0, float(payload.get("value", 0.0))))
            self._hand_debug_state()[key] = value
            self._hand_debug_edited = True
            return value
        if capability == "runtime.hand.load_preset":
            preset_id = str(payload.get("preset_id") or "").strip().lower()
            calibration = payload.get("calibration", self._hand_calibration_state())
            preset = complete_hand_calibration(calibration).get(preset_id)
            if not preset:
                raise KeyError(f"Unknown hand calibration preset: {preset_id}")
            self._hand_debug_state().update(dict(preset))
            self._hand_debug_state()["active"] = True
            self._hand_debug_edited = True
            return dict(self._hand_debug_state())
        if capability == "runtime.hand.save_preset":
            preset_id = str(payload.get("preset_id") or "").strip().lower()
            if preset_id not in {"relaxed", "fist"}:
                raise KeyError(f"Unknown hand calibration preset: {preset_id}")
            debug = self._hand_debug_state()
            values = {
                key: float(debug[key])
                for key in (
                    "finger_x", "finger_y", "finger_z",
                    "thumb_x", "thumb_y", "thumb_z",
                )
            }
            self._hand_calibration_state()[preset_id] = values
            return values
        if capability == "runtime.create_adapter":
            return self._create_adapter(runtime_context=payload.get("runtime_context"))
        return None

    @staticmethod
    def _safe_body_profile_name(value) -> str:
        name = str(value or "").strip()
        if not name or name in {".", "..", "No Configs"}:
            raise ValueError("A body profile name is required.")
        if Path(name).name != name or any(separator in name for separator in ("/", "\\")):
            raise ValueError("Body profile names cannot contain a path.")
        return name

    def _body_profile_catalog(self):
        directory = Path(self._body_configs_dir)
        if not directory.is_dir():
            return []
        return sorted(path.stem for path in directory.glob("*.json") if path.is_file())

    def _load_body_profile(self, value):
        name = self._safe_body_profile_name(value)
        path = Path(self._body_configs_dir) / f"{name}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "profile" in payload:
            profile = dict(payload.get("profile") or {})
            hands = dict(payload.get("hands") or {})
        else:
            profile = dict(payload or {})
            hands = {}
        return {"name": name, "profile": profile, "hands": hands}

    def _save_body_profile(self, value, profile, hands):
        name = self._safe_body_profile_name(value)
        directory = Path(self._body_configs_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.json"
        temporary = directory / f".{name}.json.tmp"
        temporary.write_text(
            json.dumps({"profile": dict(profile or {}), "hands": dict(hands or {})}, indent=4),
            encoding="utf-8",
        )
        temporary.replace(path)
        return {"name": name, "catalog": self._body_profile_catalog()}

    def _delete_body_profile(self, value):
        name = self._safe_body_profile_name(value)
        if name.lower() == "default":
            raise ValueError("The Default body profile cannot be deleted.")
        path = Path(self._body_configs_dir) / f"{name}.json"
        deleted = False
        if path.is_file():
            path.unlink()
            deleted = True
        return {"name": name, "deleted": deleted, "catalog": self._body_profile_catalog()}

    def _hand_debug_state(self):
        if not hasattr(self, "_runtime_hand_debug"):
            self._runtime_hand_debug = dict(avatar_hand_state.hand_debug())
        return self._runtime_hand_debug

    def _hand_calibration_state(self):
        if not hasattr(self, "_runtime_hand_calibration"):
            self._runtime_hand_calibration = complete_hand_calibration({})
        return self._runtime_hand_calibration

    def _bridge_controller(self):
        from addons.vseeface_avatar.bridge_installation import BridgeInstallation
        if not hasattr(self, '_bridge_installation'):
            self._bridge_installation = BridgeInstallation(getattr(self, '_app_root', Path(__file__).resolve().parents[2]))
        return self._bridge_installation

    def _disable_speech_bridge(self):
        with self._bridge_lock:
            self._bridge_generation += 1
            reference = getattr(self, '_active_adapter', None)
            adapter = reference() if reference else None
            if adapter is not None:
                adapter.disable_speech_bridge()

    def _publish_adapter(self, adapter, generation):
        with self._bridge_lock:
            config = getattr(self, '_runtime_config', None)
            explicitly_disabled = config is not None and config.get('vseeface_bridge_enabled', None) is False
            if generation != self._bridge_generation or explicitly_disabled:
                adapter.disable_speech_bridge()
            self._active_adapter = weakref.ref(adapter)
        return adapter

    def _configured_speech_bridge(self, runtime_context):
        from addons.vseeface_avatar.speech_bridge import SpeechBridge
        settings = dict(runtime_context.runtime_config) if runtime_context is not None else {}
        if not settings.get('vseeface_bridge_enabled') or not settings.get('vseeface_bridge_install_path'):
            return None
        try:
            controller = self._bridge_controller()
            state = controller.inspect(settings['vseeface_bridge_install_path'])
            self._bridge_status = state
            if state.get('can_adopt'):
                return SpeechBridge(controller.shared_directory)
        except (OSError, ValueError) as error:
            self._bridge_status = dict(state='unavailable', message=str(error))
        return None

    def _speech_bridge_capability(self, action, payload):
        config = getattr(self, '_runtime_config', None)
        selected = str(config.get('vseeface_bridge_install_path', '') if config else '')
        controller = self._bridge_controller()
        if action == 'launch':
            self._bridge_status = controller.launch(selected)
            self._bridge_plans = {}
            return dict(self._bridge_status)
        if action == 'disable':
            if config: config.update('vseeface_bridge_enabled', False)
            self._disable_speech_bridge()
            return {'enabled': False}
        if action == 'status':
            return dict(getattr(self, '_bridge_status', dict(state='not_checked', message='Choose a folder, then check setup.', installation=selected)),
                        plans=dict(getattr(self, '_bridge_plans', {})))
        if action == 'inspect':
            selected = str(payload.get('installation', selected))
            self._bridge_status = controller.status(selected)
            self._bridge_plans = {}
            for operation in ('install', 'adopt', 'repair', 'remove'):
                if self._bridge_status.get('can_'+operation):
                    self._bridge_plans[operation] = controller.prepare(operation, selected)
            return self._speech_bridge_capability('status', {})
        if action == 'prepare':
            operation = str(payload.get('action', ''))
            plan = controller.prepare(operation, selected)
            if not hasattr(self, '_bridge_plans'): self._bridge_plans = {}
            self._bridge_plans[operation] = plan
            return plan
        if action == 'execute':
            token = str(payload.get('approval_token', ''))
            plan = next((p for p in getattr(self, '_bridge_plans', {}).values() if p['approval_token']==token), None)
            if plan is None or not selected or not controller._same(plan['installation'], selected):
                raise ValueError('The selected installation changed. Check setup and approve the new action.')
            result = controller.execute(token)
            if plan['action'] == 'remove': self._disable_speech_bridge()
            if config:
                config.update('vseeface_bridge_enabled', plan['action'] != 'remove')
                config.update('vseeface_bridge_install_path', result['installation'])
            return self._speech_bridge_capability('inspect', {'installation': selected})
        raise KeyError('Unknown speech bridge action: '+action)

    def _create_adapter(self, runtime_context):
        from addons.vseeface_avatar.adapter import VSeeFaceAdapter

        with self._bridge_lock:
            generation = self._bridge_generation
        bridge = self._configured_speech_bridge(runtime_context)

        if runtime_context is None:
            adapter = VSeeFaceAdapter(
                avatar_profile=complete_body_profile({}),
                hand_debug=self._hand_debug_state(),
                hand_calibration=self._hand_calibration_state(),
                speech_bridge=bridge,
            )
            return self._publish_adapter(adapter, generation)

        # Initialize the authoritative owner as well as its live adapter mirrors.
        for key, callback_key, complete in (
            ("avatar_profile", "update_body_profile", complete_body_profile),
            ("hand_calibration", "update_hand_calibration", complete_hand_calibration),
        ):
            values = complete(runtime_context.get(key, {}))
            update = runtime_context.get(callback_key)
            if callable(update):
                update(values)
            else:
                runtime_context.get(key, {}).update(values)

        runtime_debug = runtime_context.get("hand_debug")
        if runtime_debug is not None:
            pending = dict(self._hand_debug_state()) if getattr(self, "_hand_debug_edited", False) else {}
            for key, value in avatar_hand_state.hand_debug().items():
                runtime_debug.setdefault(key, value)
            runtime_debug.update(pending)
            self._runtime_hand_debug = runtime_debug
        self._runtime_hand_calibration = runtime_context.get("hand_calibration", self._hand_calibration_state())

        adapter = VSeeFaceAdapter(
            avatar_profile=runtime_context.get("avatar_profile", {}),
            current_body_state=runtime_context.get("current_body_state", {}),
            edit_emotion_getter=runtime_context.get("edit_emotion_getter", lambda: "neutral"),
            force_edit_mode_getter=runtime_context.get("force_edit_mode_getter", lambda: False),
            hand_debug=self._hand_debug_state(),
            hand_calibration=self._hand_calibration_state(),
            speech_bridge=bridge,
        )
        return self._publish_adapter(adapter, generation)
