# main.ui Phase Report - 2026-04-24 - 07

This phase continued Phase 4 of the `main.ui` migration by splitting `musetalk_preprocess` away from its runtime-heavy import path.

## Objective

Make the real `musetalk_preprocess` addon tab renderable without importing `engine.py`, `cv2`, or the MuseTalk bridge during addon initialization and tab build:

1. stop importing runtime-heavy modules at `musetalk_preprocess` controller module load time
2. stop constructing the controller during addon initialize
3. keep initial tab rendering on file/UI state only

## Files Changed

- `addons/musetalk_preprocess/main.py`
- `addons/musetalk_preprocess/controller.py`
- `docs/main_ui_phase_2026-04-24_07.md`
- `docs/main_ui_plan_continuation_2026-04-23.md`
- `docs/main_ui_integration_status.md`
- `docs/main_ui_handover_2026-04-23.md`

## Changes Made

### 1. Deferred controller creation in the addon entrypoint

`addons/musetalk_preprocess/main.py` no longer loads the controller class or constructs the controller during addon initialize.

New behavior:

- addon initialize now registers the tab and event hooks only
- the controller class is loaded lazily
- the controller instance is created only when a real runtime path needs it

Effect:

- addon startup no longer pays the preprocess-controller import cost
- tab registration remains available before the runtime controller exists

### 2. Removed eager runtime-heavy imports from the controller module

`addons/musetalk_preprocess/controller.py` no longer imports these modules eagerly at module load:

- `engine`
- `cv2`
- `musetalk_bridge`

Instead, the controller now uses lazy module proxies.

Effect:

- loading the controller class no longer imports `engine.py`
- loading the controller class no longer imports OpenCV
- loading the controller class no longer imports the MuseTalk bridge

### 3. Added engine-free fallbacks for initial tab rendering

The first render path still populates pack/avatar UI, but it now does so without forcing runtime config to load:

- pack selection falls back to `Standalone Avatars` when runtime config is unavailable
- pack discovery falls back to empty legacy maps/transitions when `engine` is not loaded
- enabled-emotion selection falls back to an empty stored map when `engine` is not loaded

Effect:

- `build_tab()` can render the real MuseTalk preprocess surface from file/UI state only
- runtime-heavy modules stay unloaded until a real preprocess/debug/count action needs them

## Validation Run

Executed:

```powershell
python -m py_compile qt_app.py core\addons\qt_host_services.py addons\musetalk_preprocess\main.py addons\musetalk_preprocess\controller.py
python qt_app.py --validate-ui main.ui
python qt_app.py --ui-shell main.ui --shell-smoke
```

Additional targeted proof:

```powershell
python - <<'PY'
import sys
from addons.musetalk_preprocess import main as addon_main
print('engine_after_main_import=', 'engine' in sys.modules)
print('cv2_after_main_import=', 'cv2' in sys.modules)
print('bridge_after_main_import=', 'musetalk_bridge' in sys.modules)
cls = addon_main._load_controller_class()
print('engine_after_controller_load=', 'engine' in sys.modules)
print('cv2_after_controller_load=', 'cv2' in sys.modules)
print('bridge_after_controller_load=', 'musetalk_bridge' in sys.modules)
PY
```

and:

```powershell
python - <<'PY'
import os, sys
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6 import QtWidgets
from addons.musetalk_preprocess.main import _load_controller_class
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
controller = _load_controller_class()(None)
widget = controller.build_tab()
print(type(widget).__name__)
print('engine_after_build_tab=', 'engine' in sys.modules)
print('cv2_after_build_tab=', 'cv2' in sys.modules)
print('bridge_after_build_tab=', 'musetalk_bridge' in sys.modules)
controller._stop_cached_musetalk_tool_bridge()
print('engine_after_teardown=', 'engine' in sys.modules)
print('cv2_after_teardown=', 'cv2' in sys.modules)
print('bridge_after_teardown=', 'musetalk_bridge' in sys.modules)
PY
```

Observed result:

- `--validate-ui main.ui` still reports `Result: READY for the checked Phase 1 binding prerequisites.`
- controller class load does not import `engine`
- controller class load does not import `cv2`
- controller class load does not import `musetalk_bridge`
- `build_tab()` does not import any of those modules
- render-only teardown does not import any of those modules
- shell smoke still reports `Heavy engine imported: no`
- shell smoke still ends `Result: READY for the checked shell binding surface.`

Observed environment note in this pass:

- `nc.hotkeys` still failed to mount live in shell smoke because `keyboard` is unavailable
- shell smoke therefore still reported `Addon mount placeholders: left_tabs`

That remains separate from the Phase 4 `musetalk_preprocess` split completed in this pass.

## What Phase 4 Solved Here

- `musetalk_preprocess` can now register and load its controller class without importing runtime-heavy modules
- `musetalk_preprocess` can now build its tab widget without importing `engine`, `cv2`, or the MuseTalk bridge

## What Is Still Not Split Yet

- runtime preprocess workers still live in the controller
- runtime debug-frame flows still live in the controller
- there is still no dedicated `qt.musetalk_preprocess` host-service boundary

Those are later runtime-workflow steps, not blockers for the renderable-tab boundary completed here.

## Next Phase

Next recommended target:

```text
Begin Phase 5 by introducing an opt-in --ui-real main.ui path on top of the now-split addon/controller boundaries.
```
