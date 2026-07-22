from __future__ import annotations

import ast
import importlib.abc
import sys
import tempfile
import threading
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_raises(expected_exception: type[BaseException], callback, message: str) -> None:
    try:
        callback()
    except expected_exception:
        return
    except Exception as exc:
        raise AssertionError(f"{message}; raised {type(exc).__name__}: {exc}") from exc
    raise AssertionError(message)


def main() -> None:
    from addons.companion_orb_overlay.companion_orb import reading_actions
    from addons.companion_orb_overlay.companion_orb import companion_orb_controller

    actions = reading_actions.READING_MENU_ACTIONS
    action_ids = [item.action_id for item in actions]
    assert_true(action_ids == [
        "read_clipboard",
        "select_area_read",
        "select_area_read_comment",
        "select_area_comment",
    ], f"Unexpected reading menu action ids: {action_ids!r}")

    labels = [item.label for item in actions]
    assert_true(labels == [
        "Read Clipboard",
        "Select Area to Read",
        "Select Area to Read + Comment",
        "Select Area + Comment",
    ], f"Unexpected reading menu labels: {labels!r}")
    controller_commands = companion_orb_controller._reading_menu_action_commands()
    assert_true(
        controller_commands == tuple(zip(action_ids, labels)),
        f"Controller reading menu commands should route by action id: {controller_commands!r}",
    )
    controller_source = Path(companion_orb_controller.__file__).read_text(encoding="utf-8")
    engine_source = (ROOT_DIR / "engine.py").read_text(encoding="utf-8")
    overlay_controller_source = (
        ROOT_DIR
        / "addons"
        / "companion_orb_overlay"
        / "controller.py"
    ).read_text(encoding="utf-8")
    controller_tree = ast.parse(controller_source)
    speak_function = next(
        node
        for class_node in controller_tree.body
        if isinstance(class_node, ast.ClassDef) and class_node.name == "CompanionOrbController"
        for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name == "_speak_reading_text"
    )
    speak_source = ast.get_source_segment(controller_source, speak_function) or ""
    assert_true(
        "speak_async(chunk)" not in speak_source,
        "Reading speech should not call speak_async once per chunk.",
    )
    assert_true(
        "text_iterable=chunks" in speak_source,
        "Reading speech should queue chunks through one text_iterable speak_async call.",
    )
    assert_true(
        "_interrupt_audio_for_reading_action" in speak_source
        and speak_source.index("_interrupt_audio_for_reading_action") < speak_source.index("ctrl = speak_async"),
        "Reading speech should interrupt competing playback before queueing the selected-text TTS.",
    )
    interrupt_function = next(
        node
        for class_node in controller_tree.body
        if isinstance(class_node, ast.ClassDef) and class_node.name == "CompanionOrbController"
        for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name == "_interrupt_audio_for_reading_action"
    )
    interrupt_source = ast.get_source_segment(controller_source, interrupt_function) or ""
    for fragment, description in {
        "cancel_llm_streams=True": "asks the engine to stop active streamed LLM speech",
        "stop_playback.set()": "sets the global playback stop flag",
        "getattr(engine, \"sd\").stop()": "stops active sounddevice playback",
        "pause_after_chunk.clear()": "clears pending pause-after-chunk state",
        "playback_paused.clear()": "clears paused playback state",
        "reading_audio_interrupted": "records a reading-specific debug event",
    }.items():
        assert_true(fragment in interrupt_source, f"Reading interrupt helper should {description}.")
    for fragment, description in {
        "_active_llm_stream_states": "track active streamed LLM replies",
        "cancel_llm_streams": "let reading speech cancel active streamed LLM replies",
        "state.cancel_requested.set()": "request active streamed LLM cancellation",
    }.items():
        assert_true(fragment in engine_source, f"Engine interrupt helper should {description}.")
    exclude_function = next(
        node
        for class_node in controller_tree.body
        if isinstance(class_node, ast.ClassDef) and class_node.name == "CompanionOrbController"
        for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name == "_reading_exclude_from_memory"
    )
    prompt_function = next(
        node
        for class_node in controller_tree.body
        if isinstance(class_node, ast.ClassDef) and class_node.name == "CompanionOrbController"
        for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name == "_reading_comment_prompt"
    )
    exclude_source = ast.get_source_segment(controller_source, exclude_function) or ""
    prompt_source = ast.get_source_segment(controller_source, prompt_function) or ""
    reader_exclude_key = "companion_orb_reader_exclude_from_memory"
    legacy_exclude_key = "companion_orb_reading_exclude_from_memory"
    reader_prompt_key = "companion_orb_reader_commentary_prompt"
    legacy_prompt_key = "companion_orb_reading_comment_prompt"
    assert_true(reader_exclude_key in exclude_source, "Controller should read the reader exclude-from-memory key.")
    assert_true(reader_prompt_key in prompt_source, "Controller should read the reader commentary prompt key.")
    assert_true(
        "READING_SETTINGS_DEFAULTS" in controller_source,
        "Controller should use reading_actions.READING_SETTINGS_DEFAULTS for reading defaults.",
    )
    if legacy_exclude_key in exclude_source:
        assert_true(
            exclude_source.index(reader_exclude_key) < exclude_source.index(legacy_exclude_key),
            "Controller should prefer the reader exclude-from-memory key before legacy fallback.",
        )
    if legacy_prompt_key in prompt_source:
        assert_true(
            prompt_source.index(reader_prompt_key) < prompt_source.index(legacy_prompt_key),
            "Controller should prefer the reader commentary prompt key before legacy fallback.",
        )

    expected_semantics = {
        "read_clipboard": ("clipboard", True, False, False, True),
        "select_area_read": ("selection", True, False, True, True),
        "select_area_read_comment": ("selection", True, True, True, True),
        "select_area_comment": ("selection", False, True, True, False),
    }
    for action in actions:
        text_source, speaks_text, requests_comment, requires_selection, reads_selected_text = expected_semantics[action.action_id]
        assert_true(action.text_source == text_source, f"{action.action_id} should use {text_source!r} text source.")
        assert_true(action.speaks_text is speaks_text, f"{action.action_id} has unexpected speaks_text flag.")
        assert_true(action.requests_comment is requests_comment, f"{action.action_id} has unexpected requests_comment flag.")
        assert_true(action.requires_selection is requires_selection, f"{action.action_id} has unexpected requires_selection flag.")
        assert_true(action.reads_selected_text is reads_selected_text, f"{action.action_id} has unexpected compatibility read flag.")

    assert_true(
        reading_actions.normalize_action_id("Select Area to Read + Comment") == "select_area_read_comment",
        "Menu label should normalize to the read+comment action id.",
    )
    assert_true(
        reading_actions.normalize_action_id("read_clipboard") == "read_clipboard",
        "Action ids should pass through normalization.",
    )

    reading_ui_fragments = {
        "from addons.companion_orb_overlay.companion_orb import reading_actions": "settings UI imports reading action defaults",
        "COMPANION_ORB_READING_SESSION_KEYS": "settings UI declares reading session keys",
        '"companion_orb_reader_exclude_from_memory"': "settings UI includes exclude-from-memory setting key",
        '"companion_orb_reader_exclude_from_memory_checkbox"': "settings UI exposes exclude-from-memory checkbox",
        '"companion_orb_reader_commentary_prompt"': "settings UI includes commentary prompt setting key",
        '"companion_orb_reader_commentary_prompt_edit"': "settings UI exposes commentary prompt editor",
        '"companion_orb_reading_max_chunk_chars"': "settings UI includes chunk-size setting key",
        '"companion_orb_reading_max_chunk_chars_spin"': "settings UI exposes chunk-size spin box",
        '"companion_orb_reading_keep_debug_crops"': "settings UI includes selected-area debug crop setting key",
        '"companion_orb_reading_keep_debug_crops_checkbox"': "settings UI exposes selected-area debug crop checkbox",
        '"Read Selected Text"': "settings UI adds the reading settings card",
        '"Right-click the orb to read clipboard text, read a marked area, or ask the orb to comment on marked text."': "settings UI explains right-click reading actions",
        '"Exclude selected text from memory"': "settings UI labels the privacy checkbox",
        '"Use Recommended"': "settings UI provides recommended prompt reset",
        "reading_actions.DEFAULT_COMMENTARY_PROMPT": "settings UI uses shared recommended prompt",
        "reading_actions.READING_SETTINGS_DEFAULTS": "settings UI uses shared reading defaults",
        '"Orb debug log"': "advanced debug toggle describes the shared orb debug log",
        '"Reading Diagnostics"': "advanced settings exposes reading diagnostics",
        "def _build_companion_orb_debug_diagnostics_card(self):": "advanced debug controls are built by a reusable diagnostics card",
        "advanced_page_layout.addWidget(self._build_companion_orb_debug_diagnostics_card())": "advanced debug controls are attached to the main Advanced tab",
        '"Open Debug Log Folder"': "advanced settings can open the debug log folder",
        '"Clear Debug Log"': "advanced settings can clear the debug log",
        '"Copy Debug Log Path"': "advanced settings can copy the debug log path",
        "selected-area reading/comment extraction": "advanced debug copy says selected-area reading/comment extraction is logged",
        "runtime/companion_orb/debug/reading_crops": "advanced debug copy shows where optional selected-area crops are kept",
    }
    missing_reading_ui = [
        description
        for fragment, description in reading_ui_fragments.items()
        if fragment not in overlay_controller_source
    ]
    assert_true(not missing_reading_ui, "Missing Companion Orb reading settings UI: " + ", ".join(missing_reading_ui))
    assert_true(
        "selected_text" not in overlay_controller_source,
        "Settings UI should not persist or mention selected-text payloads.",
    )

    cleaned = reading_actions.clean_readable_text("  hello\r\n\r\n   world  ")
    assert_true(cleaned == "hello\nworld", f"Unexpected cleaned text: {cleaned!r}")

    chunks = reading_actions.chunk_text_for_tts("one two three four five six seven", max_chars=12)
    assert_true(chunks == ["one two", "three four", "five six", "seven"], f"Unexpected chunks: {chunks!r}")

    long_token_chunks = reading_actions.chunk_text_for_tts("abcdefghijk", max_chars=4)
    assert_true(long_token_chunks == ["abcd", "efgh", "ijk"], f"Unexpected long-token chunks: {long_token_chunks!r}")
    assert_true(all(len(chunk) <= 4 for chunk in long_token_chunks), f"Long-token chunks exceeded max_chars: {long_token_chunks!r}")

    overlay_source = (
        ROOT_DIR
        / "addons"
        / "companion_orb_overlay"
        / "companion_orb"
        / "reading_overlay.py"
    ).read_text(encoding="utf-8")
    overlay_fragments = {
        "class ReadingRegionSelectionOverlay": "selection overlay class exists",
        "selection_completed = QtCore.Signal(list)": "selection emits selected bounds",
        "selection_cancelled = QtCore.Signal()": "selection emits cancellation",
        "QtCore.Qt.Key_Escape": "Esc cancels selection",
        "fade_out_and_close": "selection frame fades away after extraction",
        "def select_region": "module exposes region selection helper",
        "def capture_region_image": "module exposes selected region capture helper",
    }
    missing_overlay = [
        description
        for fragment, description in overlay_fragments.items()
        if fragment not in overlay_source
    ]
    assert_true(not missing_overlay, "Missing overlay support: " + ", ".join(missing_overlay))
    overlay_tree = ast.parse(overlay_source)
    overlay_functions = {
        node.name: node
        for class_node in overlay_tree.body
        if isinstance(class_node, ast.ClassDef) and class_node.name == "ReadingRegionSelectionOverlay"
        for node in class_node.body
        if isinstance(node, ast.FunctionDef)
    }
    mouse_release_source = ast.get_source_segment(overlay_source, overlay_functions["mouseReleaseEvent"]) or ""
    fade_source = ast.get_source_segment(overlay_source, overlay_functions["fade_out_and_close"]) or ""
    assert_true(
        "self.fade_out_and_close()" in mouse_release_source,
        "Valid region release should start fade-out before completing the dialog.",
    )
    assert_true(
        "self.accept()" not in mouse_release_source,
        "Region release should not accept the dialog before fade-out is visible.",
    )
    assert_true(
        "self.accept" in fade_source or "self.done" in fade_source,
        "Fade-out helper should complete the dialog after the animation.",
    )

    from addons.companion_orb_overlay.companion_orb import reading_overlay
    from PIL import Image

    original_select_region = reading_overlay.select_region
    try:
        selected_debug_events = []

        def fake_select_region(_parent=None):
            return [3, 4, 120, 60]

        reading_overlay.select_region = fake_select_region
        controller = companion_orb_controller.CompanionOrbController.__new__(
            companion_orb_controller.CompanionOrbController
        )
        controller._window = None
        controller._debug_event = lambda event_name, **payload: selected_debug_events.append((event_name, payload))
        selected_bounds = companion_orb_controller.CompanionOrbController._select_reading_region(
            controller,
            "select_area_read",
        )
        assert_true(selected_bounds == [3, 4, 120, 60], f"Unexpected selected reading bounds: {selected_bounds!r}")
        assert_true(
            any(
                name == "reading_region_selected"
                and payload.get("action_id") == "select_area_read"
                and payload.get("bounds") == [3, 4, 120, 60]
                for name, payload in selected_debug_events
            ),
            f"Selected-area selection should emit action-scoped debug bounds: {selected_debug_events!r}",
        )
    finally:
        reading_overlay.select_region = original_select_region

    original_virtual_desktop_rect = reading_overlay.virtual_desktop_rect
    try:
        reading_overlay.virtual_desktop_rect = lambda: reading_overlay.QtCore.QRect(0, 0, 100, 80)

        with tempfile.TemporaryDirectory() as temp_root:
            output_dir = Path(temp_root)
            grab_calls = []

            def fake_grabber(*, all_screens: bool):
                grab_calls.append(all_screens)
                return Image.new("RGB", (100, 80), color=(20, 40, 60))

            output_path = reading_overlay.capture_region_image(
                [10, 12, 30, 20],
                output_dir,
                grabber=fake_grabber,
            )
            assert_true(output_path.exists(), f"Expected cropped image to be written: {output_path}")
            with Image.open(output_path) as cropped:
                assert_true(cropped.size == (30, 20), f"Unexpected crop size: {cropped.size!r}")
            assert_true(grab_calls == [True], f"Fake grabber should be called for all screens: {grab_calls!r}")

            assert_raises(
                ValueError,
                lambda: reading_overlay.capture_region_image([150, 0, 20, 20], output_dir, grabber=fake_grabber),
                "Wholly out-of-bounds selected bounds should raise ValueError.",
            )

            invalid_bounds_cases = (
                None,
                [],
                [1, 2, 3],
                [1, 2, 3, 4, 5],
                [1, 2, 0, 20],
                [1, 2, 20, 0],
                123,
            )
            for invalid_bounds in invalid_bounds_cases:
                assert_raises(
                    ValueError,
                    lambda invalid_bounds=invalid_bounds: reading_overlay.capture_region_image(
                        invalid_bounds,
                        output_dir,
                        grabber=fake_grabber,
                    ),
                    f"Invalid selected bounds should raise ValueError: {invalid_bounds!r}",
                )

            class BlockImageGrabImport(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path, target=None):
                    if fullname == "PIL.ImageGrab":
                        raise AssertionError("ImageGrab should not be imported when a grabber is injected.")
                    return None

            import PIL

            sentinel = object()
            original_image_grab_module = sys.modules.pop("PIL.ImageGrab", None)
            original_image_grab_attr = getattr(PIL, "ImageGrab", sentinel)
            if original_image_grab_attr is not sentinel:
                delattr(PIL, "ImageGrab")
            blocker = BlockImageGrabImport()
            sys.meta_path.insert(0, blocker)
            try:
                reading_overlay.capture_region_image([0, 0, 10, 10], output_dir, grabber=fake_grabber)
            finally:
                sys.meta_path.remove(blocker)
                if original_image_grab_module is not None:
                    sys.modules["PIL.ImageGrab"] = original_image_grab_module
                if original_image_grab_attr is not sentinel:
                    setattr(PIL, "ImageGrab", original_image_grab_attr)
    finally:
        reading_overlay.virtual_desktop_rect = original_virtual_desktop_rect

    app = reading_overlay.QtWidgets.QApplication.instance()
    if app is None:
        app = reading_overlay.QtWidgets.QApplication([])
    overlay = reading_overlay.ReadingRegionSelectionOverlay(reading_overlay.QtCore.QRect(0, 0, 320, 240))
    cancelled = []
    overlay.selection_cancelled.connect(lambda: cancelled.append(True))

    class FakeRightClickEvent:
        def __init__(self):
            self.accepted = False

        def button(self):
            return reading_overlay.QtCore.Qt.RightButton

        def accept(self):
            self.accepted = True

    right_click_event = FakeRightClickEvent()
    overlay.mousePressEvent(right_click_event)
    assert_true(cancelled == [True], "Right-clicking the reading selection overlay should cancel selection.")
    assert_true(right_click_event.accepted, "Right-click cancellation should consume the mouse press.")
    overlay.deleteLater()

    messages = reading_actions.build_comment_messages(
        selected_text="A traceback says ValueError: bad path.",
        behavior_prompt=reading_actions.DEFAULT_COMMENTARY_PROMPT,
        response_style_label="Very friendly",
        exclude_from_memory=True,
        mode="select_area_comment",
    )
    assert_true(messages[0]["role"] == "system", "First comment message should be a system message.")
    assert_true("Do not store" in messages[0]["content"], "Privacy guard should be explicit in the system message.")
    assert_true(messages[1]["role"] == "user", "Second comment message should be an ephemeral user message.")
    assert_true("ValueError: bad path" in messages[1]["content"], "Selected text should be present only in the ephemeral user message.")

    from addons.companion_orb_overlay.companion_orb import snapshot_ocr

    non_ascii_text = "\u65e5\u672c\u8a9e"
    regions = [
        {"text": "Second line", "screen_bounds": [0, 30, 100, 20]},
        {"text": "Right side", "screen_bounds": [50, 20, 100, 20]},
        {"text": non_ascii_text, "screen_bounds": [0, 20, 100, 20]},
        {"text": "First line", "screen_bounds": [10, 0, 100, 20]},
        {"text": "First line", "screen_bounds": [0, 0, 100, 20]},
        {"text": "", "screen_bounds": [0, 60, 100, 20]},
    ]
    merged = snapshot_ocr.readable_text_from_regions(regions)
    expected_merged = f"First line\n{non_ascii_text}\nRight side\nSecond line"
    assert_true(merged == expected_merged, f"Unexpected merged OCR text: {merged!r}")
    assert_true(snapshot_ocr.readable_text_from_regions(123) == "", "Integer OCR input should return empty text.")
    assert_true(snapshot_ocr.readable_text_from_regions(object()) == "", "Object OCR input should return empty text.")

    original_extract = snapshot_ocr._extract_with_win32_window_text
    try:
        sentinel_regions = [{"text": "Window text", "screen_bounds": [1, 2, 3, 4]}]
        calls = []

        def fake_extract(screen_bounds, *, max_regions: int):
            calls.append((list(screen_bounds), max_regions))
            return sentinel_regions

        snapshot_ocr._extract_with_win32_window_text = fake_extract
        extracted = snapshot_ocr.extract_window_text_regions([1, 2, 3, 4], max_regions=5)
        assert_true(extracted is sentinel_regions, "Window text helper should return the delegated result.")
        assert_true(calls == [([1, 2, 3, 4], 5)], f"Unexpected window text extraction calls: {calls!r}")

        def raising_extract(_screen_bounds, *, max_regions: int):
            raise RuntimeError("synthetic win32 failure")

        snapshot_ocr._extract_with_win32_window_text = raising_extract
        missing = snapshot_ocr.extract_window_text_regions([1, 2, 3, 4], max_regions=5)
        assert_true(missing == [], "Window text extraction failures should return an empty list.")
    finally:
        snapshot_ocr._extract_with_win32_window_text = original_extract

    original_window_regions = snapshot_ocr.extract_window_text_regions
    original_capture_region_image = reading_overlay.capture_region_image
    original_snapshot_regions = snapshot_ocr.extract_snapshot_regions
    try:
        with tempfile.TemporaryDirectory() as temp_root:
            capture_calls = []
            ocr_calls = []

            def fake_window_regions(_bounds, *, max_regions: int = 80):
                return []

            def fake_capture_region_image(bounds, output_dir):
                capture_calls.append((list(bounds), Path(output_dir)))
                Path(output_dir).mkdir(parents=True, exist_ok=True)
                output_path = Path(output_dir) / "selected_area.jpg"
                output_path.write_bytes(b"fake image")
                return output_path

            def fake_snapshot_regions(image_path, *, screen_bounds=None, max_regions: int = 80):
                ocr_calls.append((Path(image_path), list(screen_bounds or []), max_regions))
                return {
                    "backend": "fake_ocr",
                    "regions": [
                        {
                            "text": "Raster text selected for reading",
                            "screen_bounds": [4, 5, 120, 18],
                        }
                    ],
                    "text": "Raster text selected for reading",
                }

            snapshot_ocr.extract_window_text_regions = fake_window_regions
            reading_overlay.capture_region_image = fake_capture_region_image
            snapshot_ocr.extract_snapshot_regions = fake_snapshot_regions

            controller = companion_orb_controller.CompanionOrbController.__new__(
                companion_orb_controller.CompanionOrbController
            )
            controller.context = type("Context", (), {"app_root": Path(temp_root)})()
            debug_events = []

            def fake_debug_event(event_name, **payload):
                debug_events.append((event_name, payload))

            controller._debug_event = fake_debug_event
            extracted = companion_orb_controller.CompanionOrbController._extract_selected_reading_text(
                controller,
                [10, 12, 240, 80],
                "select_area_read",
            )
            assert_true(
                extracted == "Raster text selected for reading",
                f"Selected-area reading should use OCR fallback text, got: {extracted!r}",
            )
            assert_true(capture_calls, "Selected-area reading should capture the selected pixels for OCR fallback.")
            assert_true(ocr_calls, "Selected-area reading should run snapshot OCR on the captured selected area.")
            assert_true(
                any(name == "reading_text_extracted" and payload.get("backend") == "fake_ocr" for name, payload in debug_events),
                f"Selected-area extraction should report the OCR backend in debug events: {debug_events!r}",
            )
            debug_event_names = {name for name, _payload in debug_events}
            for expected_event in (
                "reading_window_text_probe",
                "reading_ocr_capture_saved",
                "reading_ocr_extract_finished",
                "reading_text_extracted",
            ):
                assert_true(
                    expected_event in debug_event_names,
                    f"Selected-area extraction should emit {expected_event}: {debug_events!r}",
                )
            assert_true(
                any(
                    name == "reading_ocr_capture_saved"
                    and str(payload.get("image_path") or "").endswith("selected_area.jpg")
                    for name, payload in debug_events
                ),
                f"Selected-area OCR debug should include the captured image path: {debug_events!r}",
            )
            assert_true(
                all("selected_text" not in payload and "text" not in payload for _name, payload in debug_events),
                f"Selected-area debug payloads should avoid logging selected text contents: {debug_events!r}",
            )
            assert_true(
                not (Path(temp_root) / "runtime" / "companion_orb" / "reading_ocr" / "selected_area.jpg").exists(),
                "Selected-area OCR crop should be removed by default.",
            )
    finally:
        snapshot_ocr.extract_window_text_regions = original_window_regions
        reading_overlay.capture_region_image = original_capture_region_image
        snapshot_ocr.extract_snapshot_regions = original_snapshot_regions

    original_window_regions = snapshot_ocr.extract_window_text_regions
    original_capture_region_image = reading_overlay.capture_region_image
    original_snapshot_regions = snapshot_ocr.extract_snapshot_regions
    try:
        with tempfile.TemporaryDirectory() as temp_root:
            def fake_window_regions(_bounds, *, max_regions: int = 80):
                return []

            def fake_capture_region_image(bounds, output_dir):
                Path(output_dir).mkdir(parents=True, exist_ok=True)
                output_path = Path(output_dir) / "kept_debug_crop.jpg"
                output_path.write_bytes(b"fake image")
                return output_path

            def fake_snapshot_regions(image_path, *, screen_bounds=None, max_regions: int = 80):
                return {"backend": "fake_ocr", "regions": [{"text": "Debug crop text"}], "text": "Debug crop text"}

            snapshot_ocr.extract_window_text_regions = fake_window_regions
            reading_overlay.capture_region_image = fake_capture_region_image
            snapshot_ocr.extract_snapshot_regions = fake_snapshot_regions

            controller = companion_orb_controller.CompanionOrbController.__new__(
                companion_orb_controller.CompanionOrbController
            )
            controller.context = type("Context", (), {"app_root": Path(temp_root)})()
            controller._last_runtime_config = {
                "companion_orb_debug_enabled": True,
                "companion_orb_reading_keep_debug_crops": True,
            }
            debug_events = []
            controller._debug_event = lambda event_name, **payload: debug_events.append((event_name, payload))
            extracted = companion_orb_controller.CompanionOrbController._extract_selected_reading_text(
                controller,
                [10, 12, 240, 80],
                "select_area_read",
            )
            kept_path = Path(temp_root) / "runtime" / "companion_orb" / "debug" / "reading_crops" / "kept_debug_crop.jpg"
            assert_true(extracted == "Debug crop text", f"Unexpected kept-crop OCR text: {extracted!r}")
            assert_true(kept_path.exists(), "Selected-area OCR crop should be kept when debug crop retention is enabled.")
            assert_true(
                any(name == "reading_ocr_debug_crop_kept" and Path(payload.get("image_path")).name == "kept_debug_crop.jpg" for name, payload in debug_events),
                f"Keeping a selected-area debug crop should emit a debug event: {debug_events!r}",
            )
    finally:
        snapshot_ocr.extract_window_text_regions = original_window_regions
        reading_overlay.capture_region_image = original_capture_region_image
        snapshot_ocr.extract_snapshot_regions = original_snapshot_regions

    original_window_regions = snapshot_ocr.extract_window_text_regions
    original_capture_region_image = reading_overlay.capture_region_image
    original_snapshot_regions = snapshot_ocr.extract_snapshot_regions
    try:
        with tempfile.TemporaryDirectory() as temp_root:
            capture_calls = []
            ocr_calls = []

            def fake_window_regions(_bounds, *, max_regions: int = 80):
                return [
                    {"text": "OK", "screen_bounds": [10, 12, 30, 18]},
                    {"text": "Reply", "screen_bounds": [10, 34, 44, 18]},
                    {"text": "Send", "screen_bounds": [10, 56, 40, 18]},
                ]

            def fake_capture_region_image(bounds, output_dir):
                capture_calls.append((list(bounds), Path(output_dir)))
                Path(output_dir).mkdir(parents=True, exist_ok=True)
                output_path = Path(output_dir) / "selected_area_with_text.jpg"
                output_path.write_bytes(b"fake image")
                return output_path

            def fake_snapshot_regions(image_path, *, screen_bounds=None, max_regions: int = 80):
                ocr_calls.append((Path(image_path), list(screen_bounds or []), max_regions))
                text = "This is the complete selected paragraph from the marked area."
                return {
                    "backend": "fake_ocr",
                    "regions": [{"text": text, "screen_bounds": [10, 12, 220, 54]}],
                    "text": text,
                }

            snapshot_ocr.extract_window_text_regions = fake_window_regions
            reading_overlay.capture_region_image = fake_capture_region_image
            snapshot_ocr.extract_snapshot_regions = fake_snapshot_regions

            controller = companion_orb_controller.CompanionOrbController.__new__(
                companion_orb_controller.CompanionOrbController
            )
            controller.context = type("Context", (), {"app_root": Path(temp_root)})()
            debug_events = []

            def fake_debug_event(event_name, **payload):
                debug_events.append((event_name, payload))

            controller._debug_event = fake_debug_event
            extracted = companion_orb_controller.CompanionOrbController._extract_selected_reading_text(
                controller,
                [10, 12, 240, 80],
                "select_area_read",
            )
            assert_true(
                extracted == "This is the complete selected paragraph from the marked area.",
                f"Selected-area reading should prefer complete crop OCR text over short window labels, got: {extracted!r}",
            )
            assert_true(capture_calls, "Selected-area reading should still capture the selected pixels when window text is weak.")
            assert_true(ocr_calls, "Selected-area reading should still OCR the selected pixels when window text is weak.")
            assert_true(
                any(name == "reading_text_extracted" and payload.get("backend") == "fake_ocr" for name, payload in debug_events),
                f"Selected-area extraction should report the chosen OCR backend in debug events: {debug_events!r}",
            )
    finally:
        snapshot_ocr.extract_window_text_regions = original_window_regions
        reading_overlay.capture_region_image = original_capture_region_image
        snapshot_ocr.extract_snapshot_regions = original_snapshot_regions

    original_window_regions = snapshot_ocr.extract_window_text_regions
    original_capture_region_image = reading_overlay.capture_region_image
    original_snapshot_regions = snapshot_ocr.extract_snapshot_regions
    engine_sentinel = object()
    original_engine_module = sys.modules.get("engine", engine_sentinel)
    try:
        with tempfile.TemporaryDirectory() as temp_root:
            vision_calls = []

            def fake_window_regions(_bounds, *, max_regions: int = 80):
                return []

            def fake_capture_region_image(bounds, output_dir):
                Path(output_dir).mkdir(parents=True, exist_ok=True)
                output_path = Path(output_dir) / "selected_area_empty_local_ocr.jpg"
                output_path.write_bytes(b"fake image")
                return output_path

            def fake_snapshot_regions(_image_path, *, screen_bounds=None, max_regions: int = 80):
                return {"backend": "none", "regions": [], "text": ""}

            class FakeEngineModule:
                @staticmethod
                def extract_companion_orb_selected_text_from_image(*, image_path, screen_bounds=None):
                    vision_calls.append((Path(image_path), list(screen_bounds or [])))
                    return "Vision LLM extracted text"

            snapshot_ocr.extract_window_text_regions = fake_window_regions
            reading_overlay.capture_region_image = fake_capture_region_image
            snapshot_ocr.extract_snapshot_regions = fake_snapshot_regions
            sys.modules["engine"] = FakeEngineModule

            controller = companion_orb_controller.CompanionOrbController.__new__(
                companion_orb_controller.CompanionOrbController
            )
            controller.context = type("Context", (), {"app_root": Path(temp_root)})()
            controller._debug_event = lambda *_args, **_kwargs: None

            extracted = companion_orb_controller.CompanionOrbController._extract_selected_reading_text(
                controller,
                [10, 12, 240, 80],
                "select_area_read",
            )
            assert_true(
                extracted == "Vision LLM extracted text",
                f"Selected-area reading should use vision LLM text when local OCR is empty, got: {extracted!r}",
            )
            assert_true(vision_calls, "Selected-area reading should call the vision LLM fallback when local OCR is empty.")
    finally:
        snapshot_ocr.extract_window_text_regions = original_window_regions
        reading_overlay.capture_region_image = original_capture_region_image
        snapshot_ocr.extract_snapshot_regions = original_snapshot_regions
        if original_engine_module is engine_sentinel:
            sys.modules.pop("engine", None)
        else:
            sys.modules["engine"] = original_engine_module

    controller = companion_orb_controller.CompanionOrbController.__new__(
        companion_orb_controller.CompanionOrbController
    )
    speech_done = threading.Event()
    speech_started = threading.Event()
    comment_started = threading.Event()
    worker_finished = threading.Event()
    call_order = []

    class FakeSpeechController:
        done = speech_done

    controller._extract_selected_reading_text = lambda _bounds, _action_id: "Selected text to read"

    def fake_speak(text, *, action_id: str, phase: str):
        call_order.append(("speak", phase, text))
        speech_started.set()
        return FakeSpeechController()

    def fake_comment(selected_text, action):
        call_order.append(("comment", selected_text, action.action_id))
        comment_started.set()
        return "Comment after read"

    def fake_finish(action_id: str, *, reason: str = "finished"):
        call_order.append(("finish", action_id, reason))
        worker_finished.set()

    controller._speak_reading_text = fake_speak
    controller._generate_reading_comment = fake_comment
    controller._finish_reading_job = fake_finish
    controller._debug_event = lambda *_args, **_kwargs: None
    controller._log = lambda *_args, **_kwargs: None

    read_comment_action = reading_actions.action_for_id("select_area_read_comment")
    companion_orb_controller.CompanionOrbController._start_reading_worker(
        controller,
        read_comment_action,
        selected_text="",
        bounds=[1, 2, 300, 120],
    )
    assert_true(speech_started.wait(1.0), "Read+comment worker should queue selected text speech.")
    assert_true(
        not comment_started.wait(0.08),
        "Read+comment worker should wait for the selected text readout before generating the comment.",
    )
    speech_done.set()
    assert_true(worker_finished.wait(1.0), "Read+comment worker should finish after speech completes.")
    assert_true(
        call_order[:3] == [
            ("speak", "selected_text", "Selected text to read"),
            ("comment", "Selected text to read", "select_area_read_comment"),
            ("speak", "comment", "Comment after read"),
        ],
        f"Read+comment command should read first, then comment: {call_order!r}",
    )

    print("Companion Orb reading action helper smoke passed.")


if __name__ == "__main__":
    main()
