#!/usr/bin/env python3
"""Addon smoke checks for disabled-addon and lego-box regressions.

This is not a GUI runtime test. It is a fast guardrail for the class of bugs
where a pull starts failing because an addon import, manifest, mount, or disabled
permutation broke before the UI can even open.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import re
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from core.addons.contributions import ui_mount_for_area
from core.addons.manager import AddonManager
from core.addons.manifest import AddonManifest


STATIC_BOUNDARY_RE = re.compile(
    r"(^|\s)(?:import\s+shared_state|from\s+shared_state\s+import|import\s+engine(?:\s|$)|from\s+engine\s+import|from\s+addons\.|import\s+addons\.)"
)


class SmokeFailure(RuntimeError):
    pass


@dataclass
class MockProviderRegistry:
    providers: dict[str, dict[str, Any]] = field(default_factory=dict)

    def register_provider(self, provider_id: str, **kwargs):
        self.providers[str(provider_id or "").strip()] = dict(kwargs or {})

    def unregister_provider(self, provider_id: str):
        self.providers.pop(str(provider_id or "").strip(), None)

    def get_provider_setting(self, _provider_id: str, _field_id: str):
        return ""


@dataclass
class MockSensoryService(MockProviderRegistry):
    contributors: dict[str, dict[str, Any]] = field(default_factory=dict)

    def register_prompt_contributor(self, contributor_id: str = "", **kwargs):
        key = str(contributor_id or kwargs.get("provider_id") or kwargs.get("source_id") or "").strip()
        self.contributors[key] = dict(kwargs or {})

    def unregister_prompt_contributor(self, provider_id: str):
        self.contributors.pop(str(provider_id or "").strip(), None)


@dataclass
class MockRuntimeConfig:
    values: dict[str, Any] = field(default_factory=dict)

    def snapshot(self):
        return dict(self.values)

    def get(self, key: str, default=None):
        return self.values.get(str(key), default)

    def update(self, key: str, value):
        self.values[str(key)] = value

    def engine_attr(self, _name: str, default=None):
        return default


class NullService:
    def __bool__(self):
        return True

    def __getattr__(self, _name):
        def _noop(*_args, **_kwargs):
            return None

        return _noop


class _DummyQtMeta(type):
    def __getattr__(cls, _name):
        return 0


class _DummyQtObject(metaclass=_DummyQtMeta):
    Ignored = 0
    ReadOnly = 0
    Expanding = 0
    Preferred = 0
    Minimum = 0
    Fixed = 0

    def __init__(self, *_args, **_kwargs):
        pass

    def __getattr__(self, _name):
        return _DummyQtObject()

    def __call__(self, *_args, **_kwargs):
        return _DummyQtObject()

    def __bool__(self):
        return False

    def __int__(self):
        return 0

    def __index__(self):
        return 0


class _DummyQtNamespace:
    def __getattr__(self, _name):
        return 0


def _signal(*_args, **_kwargs):
    return _DummyQtObject()


def install_optional_dependency_stubs() -> None:
    """Install tiny stubs for heavy GUI/provider deps during non-GUI smoke runs."""
    pyside = types.ModuleType("PySide6")
    qtcore = types.ModuleType("PySide6.QtCore")
    qtgui = types.ModuleType("PySide6.QtGui")
    qtwidgets = types.ModuleType("PySide6.QtWidgets")
    qtuitools = types.ModuleType("PySide6.QtUiTools")
    for module in (qtcore, qtgui, qtwidgets, qtuitools):
        module.__getattr__ = lambda _name, _module=module: _DummyQtObject
    qtcore.Signal = _signal
    qtcore.Slot = lambda *_args, **_kwargs: (lambda fn: fn)
    qtcore.Property = lambda *_args, **_kwargs: property(lambda _self: None)
    qtcore.Qt = _DummyQtNamespace()
    qtcore.QIODevice = _DummyQtNamespace()
    qtwidgets.QApplication = _DummyQtObject
    qtwidgets.QWidget = _DummyQtObject
    qtwidgets.QDialog = _DummyQtObject
    qtwidgets.QMainWindow = _DummyQtObject
    qtwidgets.QDockWidget = _DummyQtObject
    qtgui.QPixmap = _DummyQtObject
    qtuitools.QUiLoader = _DummyQtObject
    pyside.QtCore = qtcore
    pyside.QtGui = qtgui
    pyside.QtWidgets = qtwidgets
    pyside.QtUiTools = qtuitools
    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui
    sys.modules["PySide6.QtWidgets"] = qtwidgets
    sys.modules["PySide6.QtUiTools"] = qtuitools

    shiboken = types.ModuleType("shiboken6")
    shiboken.isValid = lambda _obj: True
    sys.modules["shiboken6"] = shiboken

    openai = types.ModuleType("openai")
    openai.OpenAI = _DummyQtObject
    sys.modules["openai"] = openai

    torch = types.ModuleType("torch")
    torch.cuda = _DummyQtObject()
    torch.device = lambda value=None: value
    sys.modules["torch"] = torch

    torchaudio = types.ModuleType("torchaudio")
    sys.modules["torchaudio"] = torchaudio

    keyboard = types.ModuleType("keyboard")
    keyboard.is_pressed = lambda *_args, **_kwargs: False
    keyboard.add_hotkey = lambda *_args, **_kwargs: None
    keyboard.remove_hotkey = lambda *_args, **_kwargs: None
    sys.modules["keyboard"] = keyboard


class SmokeAddonManager(AddonManager):
    def __init__(self, *, disabled_addons=None, disabled_categories=None, **kwargs):
        self._smoke_registry_state = {
            "version": 1,
            "categories": {str(item): False for item in (disabled_categories or [])},
            "addons": {str(item): False for item in (disabled_addons or [])},
        }
        super().__init__(**kwargs)

    def _load_registry_state(self) -> dict[str, Any]:
        return dict(getattr(self, "_smoke_registry_state", {"version": 1, "categories": {}, "addons": {}}))

    def _save_registry_state(self) -> None:
        return None


def _snapshot() -> dict[str, Any]:
    return {}


def build_mock_host_services() -> dict[str, Any]:
    chat = MockProviderRegistry()
    avatar = MockProviderRegistry()
    sensory = MockSensoryService()
    runtime_config = MockRuntimeConfig(
        {
            "avatar_mode": "none",
            "tts_backend": "chatterbox",
            "chat_provider": "lmstudio",
            "sensory_feedback_source": "off",
        }
    )
    null = NullService()
    return {
        "qt.avatar_providers": avatar,
        "qt.chat_providers": chat,
        "qt.sensory": sensory,
        "qt.runtime_config": runtime_config,
        "qt.shell_preview": null,
        "qt.dialogs": null,
        "qt.shell": null,
        "qt.chat_replay": null,
        "qt.user_image_turns": null,
        "qt.visual_reply": null,
        "qt.hotkeys": null,
        "qt.musetalk_ui": null,
        "qt.vam_avatar": null,
        "qt.persona_avatar": null,
        "qt.audio_story_actions": null,
        "qt.shell_session_snapshot": lambda: {},
    }


def discover_manifests(app_root: Path) -> list[AddonManifest]:
    manifests = []
    for manifest_path in sorted((app_root / "addons").glob("*/addon.json")):
        manifests.append(AddonManifest.from_file(manifest_path))
    return manifests


def check_manifests(app_root: Path) -> list[AddonManifest]:
    manifests = discover_manifests(app_root)
    seen = set()
    for manifest in manifests:
        if manifest.id in seen:
            raise SmokeFailure(f"Duplicate addon id: {manifest.id}")
        seen.add(manifest.id)
        entry_path = manifest.root_dir / manifest.entry_point
        if not entry_path.exists():
            raise SmokeFailure(f"{manifest.id}: missing entry point {manifest.entry_point}")
        for entry in manifest.ui:
            area = str(entry.get("area") or "top_level").strip() or "top_level"
            if ui_mount_for_area(area) is None:
                raise SmokeFailure(f"{manifest.id}: unknown UI mount area {area!r}")
            ui_path = str(entry.get("ui_path") or "").strip()
            if ui_path and not (manifest.root_dir / ui_path).exists():
                raise SmokeFailure(f"{manifest.id}: missing UI file {ui_path}")
    return manifests


def run_manager_permutation(app_root: Path, *, disabled_addons=(), disabled_categories=()) -> dict[str, int]:
    manager = SmokeAddonManager(
        app_root=app_root,
        llm_snapshot_getter=_snapshot,
        tts_snapshot_getter=_snapshot,
        avatar_snapshot_getter=_snapshot,
        host_services=build_mock_host_services(),
        disabled_addons=disabled_addons,
        disabled_categories=disabled_categories,
    )
    try:
        records = manager.discover()
        manager.load_all()
        manager.initialize_all()
        failures = [record for record in records if record.state == "error"]
        if failures:
            details = "; ".join(f"{item.manifest.id}: {item.error}" for item in failures)
            raise SmokeFailure(details)
        disabled = [record for record in records if record.state == "disabled"]
        initialized = [record for record in records if record.state == "initialized"]
        return {"initialized": len(initialized), "disabled": len(disabled), "total": len(records)}
    finally:
        try:
            manager.unload_all()
        except Exception:
            logging.getLogger(__name__).exception("Addon manager unload failed during smoke test")


def check_static_boundaries(app_root: Path) -> int:
    roots = [app_root / "core", app_root / "ui", app_root / "engine.py", app_root / "qt_app.py"]
    violations = []
    for root in roots:
        files = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in files:
            if "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = path.read_text(encoding="utf-8", errors="ignore")
            for line_number, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if STATIC_BOUNDARY_RE.search(line):
                    # Allowed facades use importlib strings, not static imports.
                    violations.append(f"{path.relative_to(app_root)}:{line_number}: {stripped}")
    if violations:
        raise SmokeFailure("Static boundary violations:\n" + "\n".join(violations[:80]))
    return 0


def default_permutations() -> list[tuple[str, dict[str, Any]]]:
    return [
        ("all-enabled", {}),
        ("musetalk-disabled", {"disabled_addons": ["nc.musetalk_avatar", "nc.musetalk_preprocess"]}),
        ("vam-disabled", {"disabled_addons": ["nc.vam_avatar"]}),
        ("visual-reply-disabled", {"disabled_addons": ["nc.visual_reply", "nc.visual_story_settings"]}),
        ("audio-story-disabled", {"disabled_addons": ["nc.audio_story_mode"]}),
        ("tts-chatterbox-disabled", {"disabled_addons": ["nc.chatterbox_tts"]}),
        ("tts-pockettts-disabled", {"disabled_addons": ["nc.pockettts"]}),
        ("avatar-category-disabled", {"disabled_categories": ["avatar"]}),
        ("visuals-category-disabled", {"disabled_categories": ["visuals"]}),
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run addon manifest/import/disabled smoke checks.")
    parser.add_argument("--app-root", default=str(APP_ROOT), help="Repository root. Defaults to this script's parent repo.")
    parser.add_argument("--skip-static-boundary", action="store_true", help="Skip core/UI static import boundary scan.")
    parser.add_argument("--no-dependency-stubs", action="store_true", help="Do not stub optional GUI/provider modules missing in this environment.")
    parser.add_argument("--permutation", action="append", default=[], help="Only run named permutation(s). May be repeated.")
    args = parser.parse_args(argv)

    app_root = Path(args.app_root).resolve()
    logging.basicConfig(level=logging.ERROR)
    if not args.no_dependency_stubs:
        install_optional_dependency_stubs()

    manifests = check_manifests(app_root)
    print(f"manifest-check: ok ({len(manifests)} addon manifests)")

    if not args.skip_static_boundary:
        check_static_boundaries(app_root)
        print("static-boundary-check: ok")

    wanted = set(args.permutation or [])
    for name, kwargs in default_permutations():
        if wanted and name not in wanted:
            continue
        result = run_manager_permutation(app_root, **kwargs)
        print(
            f"permutation {name}: ok "
            f"(initialized={result['initialized']} disabled={result['disabled']} total={result['total']})"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeFailure as exc:
        print(f"addon-smoke: FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
