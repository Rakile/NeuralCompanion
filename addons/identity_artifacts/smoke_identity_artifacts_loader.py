from __future__ import annotations

import sys
import tempfile
import shutil
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from addons.identity_artifacts import main as addon_main
from core.addons import AddonManager


MODULE_NAME = "nc_addon_identity_artifacts_controller"


def _load_from_source(source: str, *, previous_module: ModuleType | None = None):
    original_factory = addon_main.importlib.util.spec_from_file_location
    with tempfile.TemporaryDirectory(prefix="nc_identity_loader_source_") as temp_dir:
        controller_path = Path(temp_dir) / "controller.py"
        controller_path.write_text(source, encoding="utf-8")

        def redirected_factory(module_name, _controller_path):
            return original_factory(module_name, controller_path)

        if previous_module is None:
            sys.modules.pop(MODULE_NAME, None)
        else:
            sys.modules[MODULE_NAME] = previous_module
        addon_main.importlib.util.spec_from_file_location = redirected_factory
        try:
            return addon_main._load_controller_class()
        finally:
            addon_main.importlib.util.spec_from_file_location = original_factory


def test_dynamic_controller_loader_registers_module() -> None:
    sys.modules.pop(MODULE_NAME, None)

    controller_class = addon_main._load_controller_class()

    loaded_module = sys.modules.get(MODULE_NAME)
    assert loaded_module is not None
    assert controller_class.__module__ == MODULE_NAME
    assert loaded_module.IdentityArtifactsController is controller_class


def test_loader_removes_new_module_after_execution_failure() -> None:
    try:
        _load_from_source("raise RuntimeError('loader failure')\n")
    except RuntimeError as exc:
        assert str(exc) == "loader failure"
    else:
        raise AssertionError("controller execution failure was not raised")
    assert MODULE_NAME not in sys.modules


def test_loader_restores_previous_module_after_execution_failure() -> None:
    previous_module = ModuleType(MODULE_NAME)
    try:
        _load_from_source(
            "raise RuntimeError('loader failure')\n",
            previous_module=previous_module,
        )
    except RuntimeError as exc:
        assert str(exc) == "loader failure"
    else:
        raise AssertionError("controller execution failure was not raised")
    assert sys.modules.get(MODULE_NAME) is previous_module


def test_loader_restores_previous_module_after_contract_failure() -> None:
    previous_module = ModuleType(MODULE_NAME)
    try:
        _load_from_source("LOADED_WITHOUT_CONTROLLER = True\n", previous_module=previous_module)
    except AttributeError:
        pass
    else:
        raise AssertionError("missing controller class was not rejected")
    assert sys.modules.get(MODULE_NAME) is previous_module


def test_addon_manager_initializes_identity_artifacts() -> None:
    with tempfile.TemporaryDirectory(prefix="nc_identity_loader_") as temp_dir:
        app_root = Path(temp_dir)
        shutil.copytree(
            ROOT / "addons" / "identity_artifacts",
            app_root / "addons" / "identity_artifacts",
        )
        manager = AddonManager(
            app_root=app_root,
            llm_snapshot_getter=lambda: {},
            tts_snapshot_getter=lambda: {},
            avatar_snapshot_getter=lambda: {},
            host_services={},
        )

        records = manager.discover()
        assert len(records) == 1
        assert records[0].manifest.id == "nc.identity_artifacts"
        manager.load_all()
        initialized = manager.initialize_all()

        record = initialized[0]
        assert record.state == "initialized", record.error
        manager.unload_all()


if __name__ == "__main__":
    test_dynamic_controller_loader_registers_module()
    test_loader_removes_new_module_after_execution_failure()
    test_loader_restores_previous_module_after_execution_failure()
    test_loader_restores_previous_module_after_contract_failure()
    test_addon_manager_initializes_identity_artifacts()
    print("Identity Artifacts addon loader smoke passed.")
