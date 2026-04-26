# main.ui Phase Report - 2026-04-24 - 06

This phase started Phase 4 of the `main.ui` migration by splitting `audio_story_mode` away from its runtime-heavy import path.

## Objective

Make the real `audio_story_mode` addon tab renderable without importing `engine.py` or creating playback runtime objects during addon initialization and tab build:

1. stop importing runtime-heavy modules at `audio_story_mode` controller module load time
2. stop constructing the controller during addon initialize
3. stop creating the media player in `build_tab()`

## Files Changed

- `addons/audio_story_mode/main.py`
- `addons/audio_story_mode/controller.py`
- `docs/main_ui_phase_2026-04-24_06.md`
- `docs/main_ui_plan_continuation_2026-04-23.md`
- `docs/main_ui_integration_status.md`
- `docs/main_ui_handover_2026-04-23.md`

## Changes Made

### 1. Deferred controller creation in the addon entrypoint

`addons/audio_story_mode/main.py` no longer loads the controller class or constructs the controller during addon initialize.

New behavior:

- addon initialize now registers the tab only
- the controller class is loaded lazily
- the controller instance is created only when a real runtime path needs it

Effect:

- the addon no longer pays the controller import cost during startup
- shell and future real-UI tab registration can happen before the runtime controller exists

### 2. Removed eager runtime-heavy imports from the controller module

`addons/audio_story_mode/controller.py` no longer imports these modules eagerly at module load:

- `engine`
- `shared_state`
- `core.chat_providers`

Instead, the controller now uses lazy module proxies.

Effect:

- loading the controller class no longer imports `engine.py`
- the renderable tab definition can load without pulling in Whisper, TTS, image-generation, or related runtime dependencies

### 3. Moved media-player creation out of `build_tab()`

`build_tab()` no longer calls `_ensure_player()`.

New behavior:

- the media player is created only when playback preparation actually begins
- tab rendering remains UI-only

Effect:

- building the tab no longer creates `QMediaPlayer` / `QAudioOutput`
- playback runtime stays lazy instead of being a tab-build side effect

### 4. Prevented teardown from importing `engine` after a render-only build

`shutdown()` now skips runtime prompt-sync cleanup when `engine` was never loaded.

Effect:

- a controller that only rendered its tab can now also shut down without importing `engine`

## Validation Run

Executed:

```powershell
python -m py_compile qt_app.py core\addons\qt_host_services.py addons\audio_story_mode\main.py addons\audio_story_mode\controller.py
python qt_app.py --validate-ui main.ui
python qt_app.py --ui-shell main.ui --shell-smoke
```

Additional targeted proof:

```powershell
python - <<'PY'
import sys
from addons.audio_story_mode import main as addon_main
print('engine_after_main_import=', 'engine' in sys.modules)
cls = addon_main._load_controller_class()
print('engine_after_controller_load=', 'engine' in sys.modules)
PY
```

and:

```powershell
python - <<'PY'
import os, sys
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6 import QtWidgets
from addons.audio_story_mode.main import _load_controller_class
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
controller = _load_controller_class()(None)
widget = controller.build_tab()
print(type(widget).__name__)
print('engine_after_build_tab=', 'engine' in sys.modules)
controller.shutdown()
print('engine_after_shutdown=', 'engine' in sys.modules)
PY
```

Observed result:

- controller class load does not import `engine`
- `build_tab()` does not import `engine`
- render-only shutdown does not import `engine`
- shell smoke still reports `Heavy engine imported: no`
- shell smoke still ends `Result: READY for the checked shell binding surface.`

Observed environment note in this pass:

- `nc.hotkeys` still failed to mount live in shell smoke because `keyboard` is unavailable
- shell smoke therefore still reported `Addon mount placeholders: left_tabs`

That remains separate from the Phase 4 `audio_story_mode` split completed in this pass.

## What Phase 4 Solved Here

- `audio_story_mode` can now register and load its controller class without importing runtime-heavy modules
- `audio_story_mode` can now build its tab widget without importing `engine`

## What Is Still Not Split Yet

- runtime transcription still lives in the controller
- runtime TTS render still lives in the controller
- runtime visual-generation still lives in the controller
- there is still no dedicated `qt.audio_story_mode` host-service boundary

Those are later runtime-workflow steps, not blockers for the renderable-tab boundary completed here.

## Next Phase

Next recommended target:

```text
Apply the same Phase 4 split to musetalk_preprocess so both priority runtime-heavy addons can render their tab surfaces without importing heavy runtime paths during load/build.
```
