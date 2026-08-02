# Audio Story Operation Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Audio Story Mode's generic project `Working...` label with a compact, animated, operation-specific status display.

**Architecture:** Keep the existing project worker pipeline unchanged and add a small status presenter to the addon controller. The GUI thread supplies frozen busy/success text when launching work, owns the color-cycle timer, and rejects stale delayed resets with a monotonically increasing status generation.

**Tech Stack:** Python 3, PySide6 (`QLabel`, `QTimer`), Qt Designer `.ui`, existing standalone Audio Story smoke-test scripts.

## Global Constraints

- Modify only files under `addons/audio_story_mode/`.
- Do not change core runtime, shared addon framework, providers, presets, or unrelated addons.
- Do not move filesystem validation or project mutations onto the Qt UI thread.
- Use exactly 420 logical pixels as the project-header maximum width.
- Cycle only active status text through `#28d17c`, `#ff5964`, and `#f5b942`.
- Keep success text visible for exactly 3,000 ms before returning to `Saved`.
- Never let a stale timer overwrite a newer operation, error, project switch, or shutdown state.
- Do not commit or push unless the user explicitly requests it after implementation.

---

## File Map

- `addons/audio_story_mode/controller.py`: owns status state, timer animation, operation copy, and generation-safe reset behavior.
- `addons/audio_story_mode/ui/audio_story_mode.ui`: bounds the existing header frame to 420 logical pixels.
- `addons/audio_story_mode/smoke_audio_story_workflow.py`: exercises live Qt status behavior, count-aware import copy, stale-reset rejection, and Designer geometry.
- `addons/audio_story_mode/docs/operation_status_design.md`: approved behavior and scope.
- `addons/audio_story_mode/docs/operation_status_plan.md`: test-first execution checklist.

### Task 1: Add a generation-safe status presenter

**Files:**
- Modify: `addons/audio_story_mode/smoke_audio_story_workflow.py`
- Modify: `addons/audio_story_mode/controller.py`

**Interfaces:**
- Produces: `AudioStoryModeController._set_story_project_autosave_text(text: str, *, state: str = "idle", reset_after_ms: int | None = None) -> int`
- Produces: `AudioStoryModeController._advance_story_project_status_color() -> None`
- Produces: `AudioStoryModeController._reset_story_project_status_if_current(generation: int) -> None`
- Consumes: existing `audio_story_project_autosave_label: QLabel`

- [ ] **Step 1: Write failing tests for active, success, error, and stale-reset states**

Add focused tests to `smoke_audio_story_workflow.py`:

```python
def test_project_header_status_animates_only_active_work() -> None:
    app = _qt_application()
    controller_module = _require_module("addons.audio_story_mode.controller")
    controller = controller_module.AudioStoryModeController(context=None)
    controller.audio_story_project_autosave_label = controller_module.QtWidgets.QLabel()
    try:
        controller._set_story_project_autosave_text(
            "Importing 3 audio files...", state="active"
        )
        first_style = controller.audio_story_project_autosave_label.styleSheet()
        assert controller._story_project_status_timer.isActive()
        controller._advance_story_project_status_color()
        second_style = controller.audio_story_project_autosave_label.styleSheet()
        assert first_style != second_style

        controller._set_story_project_autosave_text(
            "Imported 3 audio files", state="success", reset_after_ms=3000
        )
        assert not controller._story_project_status_timer.isActive()
        assert "#28d17c" in controller.audio_story_project_autosave_label.styleSheet()

        controller._set_story_project_autosave_text(
            "Project error: disk full", state="error"
        )
        assert not controller._story_project_status_timer.isActive()
        assert "#ff5964" in controller.audio_story_project_autosave_label.styleSheet()
    finally:
        controller.shutdown()
        app.processEvents()


def test_project_header_stale_success_reset_cannot_replace_new_work() -> None:
    _app = _qt_application()
    controller_module = _require_module("addons.audio_story_mode.controller")
    controller = controller_module.AudioStoryModeController(context=None)
    controller.audio_story_project_autosave_label = controller_module.QtWidgets.QLabel()
    try:
        old_generation = controller._set_story_project_autosave_text(
            "Imported 2 audio files", state="success", reset_after_ms=3000
        )
        controller._set_story_project_autosave_text(
            "Opening project...", state="active"
        )
        controller._reset_story_project_status_if_current(old_generation)
        assert controller.audio_story_project_autosave_label.text() == (
            "Opening project..."
        )
    finally:
        controller.shutdown()
```

Register both tests in the script's bottom test tuple.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python addons/audio_story_mode/smoke_audio_story_workflow.py
```

Expected: failure because `_story_project_status_timer`,
`_advance_story_project_status_color`, and the extended status method do not
exist.

- [ ] **Step 3: Implement the minimal UI-thread presenter**

In `AudioStoryModeController.__init__`, initialize:

```python
self._story_project_status_generation = 0
self._story_project_status_color_index = 0
self._story_project_status_timer = QtCore.QTimer(self)
self._story_project_status_timer.setInterval(420)
self._story_project_status_timer.timeout.connect(
    self._advance_story_project_status_color
)
```

Replace the existing setter with generation-aware behavior:

```python
def _set_story_project_autosave_text(
    self,
    text: str,
    *,
    state: str = "idle",
    reset_after_ms: int | None = None,
) -> int:
    self._story_project_status_generation += 1
    generation = self._story_project_status_generation
    self._story_project_status_timer.stop()
    self._story_project_status_color_index = 0
    label = getattr(self, "audio_story_project_autosave_label", None)
    if label is not None:
        label.setText(str(text or "").strip())
    if state == "active":
        self._apply_story_project_status_color("#28d17c")
        self._story_project_status_timer.start()
    elif state == "error":
        self._apply_story_project_status_color("#ff5964")
    else:
        self._apply_story_project_status_color("#28d17c")
    if reset_after_ms is not None:
        QtCore.QTimer.singleShot(
            int(reset_after_ms),
            lambda owner=generation: self._reset_story_project_status_if_current(
                owner
            ),
        )
    return generation
```

Add `_apply_story_project_status_color`, `_advance_story_project_status_color`,
and `_reset_story_project_status_if_current`. The reset method must return
without changes when shutdown is active or `generation` differs from
`_story_project_status_generation`; otherwise it calls the setter with
`"Saved"`.

Stop `_story_project_status_timer` in `shutdown()` beside the existing rebuild
and theme timers.

- [ ] **Step 4: Run the workflow suite and verify GREEN**

Run:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python addons/audio_story_mode/smoke_audio_story_workflow.py
```

Expected: every workflow test, including the two new status tests, prints
`PASS` and the process exits `0`.

- [ ] **Step 5: Review the task diff without committing**

Run:

```powershell
git diff -- addons/audio_story_mode/controller.py addons/audio_story_mode/smoke_audio_story_workflow.py
```

Confirm no worker thread accesses the label and no path outside the addon is
modified.

### Task 2: Report exact project and audio-import operations

**Files:**
- Modify: `addons/audio_story_mode/smoke_audio_story_projects.py`
- Modify: `addons/audio_story_mode/controller.py`

**Interfaces:**
- Extends: `_launch_story_project_job(..., busy_text: str | None = None, success_text: str | None = None) -> None`
- Extends: `_run_story_project_mutation(operation: str, mutation, *, busy_text: str | None = None, success_text: str | None = None) -> None`
- Consumes: Task 1's `_set_story_project_autosave_text`

- [ ] **Step 1: Write failing tests for count-aware import phases**

Add a controller test that replaces `_launch_story_project_job` with a capture
function, calls `_import_story_project_audio_paths(("one.wav", "two.wav"))`, and
asserts:

```python
assert operation == "import-review"
assert kwargs["busy_text"] == "Checking 2 audio files..."
```

Add a completion-path test with a review containing two valid files. Capture
`_run_story_project_mutation` and assert:

```python
assert operation == "import"
assert kwargs["busy_text"] == "Importing 2 audio files..."
assert kwargs["success_text"] == "Imported 2 audio files"
```

Use a singular review in the same test helper to assert `1 audio file`, not
`1 audio files`.

- [ ] **Step 2: Run the project suite and verify RED**

Run:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python addons/audio_story_mode/smoke_audio_story_projects.py
```

Expected: captured kwargs do not yet contain `busy_text` or `success_text`.

- [ ] **Step 3: Add frozen operation copy to the existing launcher**

Add a pure helper:

```python
@staticmethod
def _story_project_operation_busy_text(operation: str) -> str:
    return {
        "list": "Refreshing projects...",
        "create": "Creating project...",
        "open": "Opening project...",
        "rename": "Renaming project...",
        "close": "Closing project...",
        "delete": "Deleting project...",
        "import-review": "Checking audio files...",
        "import": "Importing audio files...",
        "relink": "Relinking chapter audio...",
        "archive": "Archiving chapter...",
        "restore": "Restoring chapter...",
        "reorder": "Reordering chapters...",
        "legacy-migration-preview": "Checking current story...",
        "legacy-migration-commit": "Saving current story...",
    }.get(str(operation or ""), "Updating project...")
```

Extend `_launch_story_project_job` with keyword-only `busy_text` and
`success_text`. Before starting its worker, call:

```python
self._set_story_project_autosave_text(
    busy_text or self._story_project_operation_busy_text(operation),
    state="active",
)
```

Freeze `success_text` into the emitted payload. Do not derive UI text or touch a
widget in `worker()`.

Extend `_run_story_project_mutation` to forward both optional strings. In
`_on_story_project_job_finished`, use the owned `success_text` for the final
project result:

```python
if success_text:
    self._set_story_project_autosave_text(
        success_text, state="success", reset_after_ms=3000
    )
else:
    self._set_story_project_autosave_text("Saved")
```

Pass count-aware text from both audio-import phases using one pure pluralization
helper:

```python
@staticmethod
def _audio_file_count_text(count: int) -> str:
    return f"{count} audio file" + ("" if count == 1 else "s")
```

Mark project-job and autosave failures with `state="error"`. Preserve all
existing main status messages and project ownership checks.

- [ ] **Step 4: Run project and workflow suites and verify GREEN**

Run:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python addons/audio_story_mode/smoke_audio_story_projects.py
python addons/audio_story_mode/smoke_audio_story_workflow.py
```

Expected: all tests print `PASS`; both processes exit `0`.

- [ ] **Step 5: Review the task diff without committing**

Run:

```powershell
git diff --check
git diff -- addons/audio_story_mode/controller.py addons/audio_story_mode/smoke_audio_story_projects.py addons/audio_story_mode/smoke_audio_story_workflow.py
```

Confirm the old hard-coded project-launcher `Working...` string is absent and
existing worker ownership fields remain unchanged.

### Task 3: Make the Designer header compact

**Files:**
- Modify: `addons/audio_story_mode/smoke_audio_story_workflow.py`
- Modify: `addons/audio_story_mode/ui/audio_story_mode.ui`

**Interfaces:**
- Consumes: existing widget `audio_story_project_header_frame`
- Produces: a header with `maximumWidth() == 420`

- [ ] **Step 1: Write the failing Designer geometry test**

Extend `test_designer_ui_exposes_story_project_controls` or add a focused loaded
UI test:

```python
header = root.findChild(QtWidgets.QFrame, "audio_story_project_header_frame")
assert header is not None
assert header.maximumWidth() == 420
root.resize(1200, 900)
root.show()
app.processEvents()
assert header.width() <= 420
```

Close and delete the loaded root in `finally`.

- [ ] **Step 2: Run the workflow suite and verify RED**

Run:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python addons/audio_story_mode/smoke_audio_story_workflow.py
```

Expected: the header maximum width is still Qt's unrestricted default, not
`420`.

- [ ] **Step 3: Apply the minimal Designer constraint**

Add this property to `audio_story_project_header_frame`:

```xml
<property name="maximumSize">
 <size>
  <width>420</width>
  <height>16777215</height>
 </size>
</property>
```

Do not recreate the header in Python and do not change the surrounding page,
navigation row, or project controls.

- [ ] **Step 4: Run the workflow suite and verify GREEN**

Run:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python addons/audio_story_mode/smoke_audio_story_workflow.py
```

Expected: the compact-header test and every existing workflow test pass.

- [ ] **Step 5: Inspect the loaded UI manually**

Load the Audio Story tab in NeuralCompanion and verify:

- the header remains under the introduction and aligns to the left;
- long project/status text does not overlap;
- the navigation tiles retain their existing geometry;
- an import visibly transitions from checking to importing to imported to saved.

### Task 4: Full addon verification and scope audit

**Files:**
- Verify only; no new production files.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: verification evidence for the complete addon-only patch.

- [ ] **Step 1: Compile every changed Python file**

Run:

```powershell
python -m py_compile `
  addons/audio_story_mode/controller.py `
  addons/audio_story_mode/smoke_audio_story_projects.py `
  addons/audio_story_mode/smoke_audio_story_workflow.py
```

Expected: exit `0` with no output.

- [ ] **Step 2: Run all four Audio Story smoke suites**

Run:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python addons/audio_story_mode/smoke_audio_story_mode.py
python addons/audio_story_mode/smoke_audio_story_projects.py
python addons/audio_story_mode/smoke_audio_story_tts_queue.py
python addons/audio_story_mode/smoke_audio_story_workflow.py
```

Expected: every test prints `PASS`; all four commands exit `0`.

- [ ] **Step 3: Audit repository scope and whitespace**

Run:

```powershell
git status --short
git diff --name-only
git diff --check
rg -n 'Working\\.\\.\\.' addons/audio_story_mode/controller.py
```

Expected:

- every changed path is under `addons/audio_story_mode/`;
- `git diff --check` exits `0`;
- no generic project-launcher `Working...` remains;
- no core/runtime files are changed.

- [ ] **Step 4: Report without committing**

Summarize changed files, exact active/success/error behavior, relevant test
counts, manual UI validation still recommended, and confirmation that core
runtime files were untouched.
