from __future__ import annotations

import importlib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

from PySide6 import QtWidgets

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_test_module(*parts: str):
    return importlib.import_module(".".join(parts))


controller_module = _load_test_module("addons", "identity_artifacts", "controller")
relay_state_module = _load_test_module("addons", "identity_artifacts", "relay_state")
storage_module = _load_test_module("addons", "identity_artifacts", "storage")

IdentityArtifactsController = controller_module.IdentityArtifactsController
IdentityRelayUiSnapshot = relay_state_module.IdentityRelayUiSnapshot
ARTIFACT_REF_RE = storage_module.ARTIFACT_REF_RE
ArtifactResolution = storage_module.ArtifactResolution


EXPECTED_OBJECTS = {
    "identity_relay_persona_row",
    "identity_relay_ref_label",
    "identity_relay_ref_combo",
    "identity_relay_chat_row",
    "identity_relay_toggle",
    "identity_relay_warning_label",
    "identity_relay_connection_status_label",
    "identity_relay_review_button",
    "identity_relay_status_label",
    "identity_relay_judging_label",
    "identity_relay_repair_button",
    "identity_relay_disable_button",
    "identity_relay_rebuild_index_button",
    "identity_relay_trace_button",
}


class _CountingCombo(QtWidgets.QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.clear_calls = 0

    def clear(self):
        self.clear_calls += 1
        super().clear()


def _build_widgets(*, counting_combo: bool = False):
    root = QtWidgets.QWidget()
    persona_row = QtWidgets.QWidget(root)
    persona_row.setObjectName("identity_relay_persona_row")
    combo_type = _CountingCombo if counting_combo else QtWidgets.QComboBox
    combo = combo_type(persona_row)
    combo.setObjectName("identity_relay_ref_combo")
    chat_row = QtWidgets.QWidget(root)
    chat_row.setObjectName("identity_relay_chat_row")
    toggle = QtWidgets.QCheckBox("Identity Relay", chat_row)
    toggle.setObjectName("identity_relay_toggle")
    warning = QtWidgets.QLabel(chat_row)
    warning.setObjectName("identity_relay_warning_label")
    connection_status = QtWidgets.QLabel(persona_row)
    connection_status.setObjectName("identity_relay_connection_status_label")
    review_button = QtWidgets.QPushButton("Review", persona_row)
    review_button.setObjectName("identity_relay_review_button")
    status = QtWidgets.QLabel(chat_row)
    status.setObjectName("identity_relay_status_label")
    judging = QtWidgets.QLabel(chat_row)
    judging.setObjectName("identity_relay_judging_label")
    repair_button = QtWidgets.QPushButton("Repair", chat_row)
    repair_button.setObjectName("identity_relay_repair_button")
    disable_button = QtWidgets.QPushButton("Disable", chat_row)
    disable_button.setObjectName("identity_relay_disable_button")
    rebuild_button = QtWidgets.QPushButton("Rebuild Index", chat_row)
    rebuild_button.setObjectName("identity_relay_rebuild_index_button")
    trace_button = QtWidgets.QPushButton("Trace", chat_row)
    trace_button.setObjectName("identity_relay_trace_button")
    persona_row.hide()
    chat_row.hide()
    return SimpleNamespace(
        root=root,
        persona_row=persona_row,
        combo=combo,
        chat_row=chat_row,
        toggle=toggle,
        warning=warning,
        connection_status=connection_status,
        review_button=review_button,
        status=status,
        judging=judging,
        repair_button=repair_button,
        disable_button=disable_button,
        rebuild_button=rebuild_button,
        trace_button=trace_button,
    )


def build_controller_and_widgets(*, counting_combo: bool = False):
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return IdentityArtifactsController(context=None), _build_widgets(counting_combo=counting_combo)


class _Bridge:
    def __init__(self, backend_widgets, frontend_widgets):
        self.backend_widgets = backend_widgets
        self.frontend_widgets = frontend_widgets

    @staticmethod
    def _lookup(widgets, name):
        mapping = {
            "identity_relay_persona_row": widgets.persona_row,
            "identity_relay_ref_combo": widgets.combo,
            "identity_relay_chat_row": widgets.chat_row,
            "identity_relay_toggle": widgets.toggle,
            "identity_relay_warning_label": widgets.warning,
            "identity_relay_connection_status_label": widgets.connection_status,
            "identity_relay_review_button": widgets.review_button,
            "identity_relay_status_label": widgets.status,
            "identity_relay_judging_label": widgets.judging,
            "identity_relay_repair_button": widgets.repair_button,
            "identity_relay_disable_button": widgets.disable_button,
            "identity_relay_rebuild_index_button": widgets.rebuild_button,
            "identity_relay_trace_button": widgets.trace_button,
        }
        return mapping.get(name)

    def _backend_widget(self, name):
        return self._lookup(self.backend_widgets, name)

    def _ui_object(self, name):
        return self._lookup(self.frontend_widgets, name)


class _RecordingController(IdentityArtifactsController):
    def __init__(self):
        super().__init__(context=None)
        self.persona_calls = []
        self.toggle_calls = []
        self.connection_requests = []

    def set_persona_identity_ref(self, artifact_ref: str, *, notify: bool = True):
        ref = str(artifact_ref or "")
        self.persona_calls.append(ref)
        resolution = ArtifactResolution(ref, ref[8:-5], "Continuity", None) if ref else None
        self.relay_model.set_connection(resolution)
        return self.relay_model.ui_snapshot()

    def set_relay_enabled(self, enabled: bool) -> bool:
        self.toggle_calls.append(bool(enabled))
        return self.relay_model.set_enabled(bool(enabled))

    def request_connection(self, artifact_ref: str, **kwargs):
        self.connection_requests.append((str(artifact_ref or ""), dict(kwargs)))


def test_designer_and_backend_have_matching_objects():
    designer_names = {node.attrib.get("name") for node in ET.parse(ROOT / "main.ui").iter("widget")}
    source = (ROOT / "ui/runtime/backend_workspace_builders.py").read_text(encoding="utf-8")
    source += (ROOT / "ui/runtime/backend_operational_panel.py").read_text(encoding="utf-8")
    assert EXPECTED_OBJECTS <= designer_names
    assert all(name in source for name in EXPECTED_OBJECTS)


def test_addon_disabled_defaults_both_rows_hidden():
    _controller, widgets = build_controller_and_widgets()
    assert widgets.persona_row.isHidden()
    assert widgets.chat_row.isHidden()

    tree = ET.parse(ROOT / "main.ui")
    by_name = {node.attrib.get("name"): node for node in tree.iter("widget")}
    for name in ("identity_relay_persona_row", "identity_relay_chat_row"):
        visible = by_name[name].find("./property[@name='visible']/bool")
        assert visible is not None and visible.text == "false"


def test_visibility_matrix_and_strict_combo_data():
    controller, widgets = build_controller_and_widgets()
    controller._apply_widget_state(
        IdentityRelayUiSnapshot(1, (("None", ""),), "", "none", True, ""), widgets
    )
    assert not widgets.persona_row.isHidden()
    assert widgets.chat_row.isHidden()
    assert widgets.combo.itemData(0) == ""

    ref = "library/" + "a" * 64 + ".json"
    controller._apply_widget_state(
        IdentityRelayUiSnapshot(
            2,
            (("None", ""), ("Imported Identity", ref)),
            ref,
            "available",
            False,
            "",
        ),
        widgets,
    )
    assert widgets.combo.currentData() == ref
    assert not widgets.chat_row.isHidden()
    assert not widgets.toggle.isHidden()
    assert widgets.toggle.isEnabled()
    assert not widgets.toggle.isChecked()
    assert widgets.warning.isHidden()

    controller._apply_widget_state(
        IdentityRelayUiSnapshot(
            3,
            (("None", ""), ("Unavailable Identity", ref)),
            ref,
            "unavailable",
            True,
            "Identity file is missing.",
        ),
        widgets,
    )
    assert widgets.chat_row.isHidden()
    assert widgets.toggle.isHidden()
    assert not widgets.warning.isHidden()
    assert widgets.warning.text() == "Identity file is missing."


def test_combo_rejects_every_non_strict_item_data_value():
    controller, widgets = build_controller_and_widgets()
    strict_ref = "library/" + "a" * 64 + ".json"
    controller._apply_widget_state(
        IdentityRelayUiSnapshot(
            1,
            (
                ("None", ""),
                ("Strict", strict_ref),
                ("Absolute", "C:/identity.json"),
                ("Backslash", "library\\" + "b" * 64 + ".json"),
                ("Traversal", "../" + strict_ref),
                ("Uppercase", "library/" + "A" * 64 + ".json"),
                ("Wrong suffix", "library/" + "b" * 64 + ".txt"),
            ),
            strict_ref,
            "available",
            True,
            "",
        ),
        widgets,
    )

    item_data = [str(widgets.combo.itemData(index) or "") for index in range(widgets.combo.count())]
    assert strict_ref in item_data
    assert all(not value or ARTIFACT_REF_RE.fullmatch(value) for value in item_data)


def test_mirror_defers_combo_rebuild_while_control_has_focus():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller, widgets = build_controller_and_widgets(counting_combo=True)
    first_ref = "library/" + "a" * 64 + ".json"
    second_ref = "library/" + "b" * 64 + ".json"
    controller._apply_widget_state(
        IdentityRelayUiSnapshot(1, (("First", first_ref),), first_ref, "available", True, ""),
        widgets,
    )
    initial_clear_calls = widgets.combo.clear_calls

    widgets.root.show()
    widgets.combo.setFocus()
    app.processEvents()
    assert widgets.combo.hasFocus()
    controller._apply_widget_state(
        IdentityRelayUiSnapshot(2, (("Second", second_ref),), second_ref, "available", True, ""),
        widgets,
    )
    assert widgets.combo.clear_calls == initial_clear_calls
    assert widgets.combo.currentData() == first_ref

    widgets.combo.clearFocus()
    app.processEvents()
    controller._apply_widget_state(
        IdentityRelayUiSnapshot(2, (("Second", second_ref),), second_ref, "available", True, ""),
        widgets,
    )
    assert widgets.combo.clear_calls == initial_clear_calls + 1
    assert widgets.combo.currentData() == second_ref
    widgets.root.close()


def test_user_changes_reach_controller_once_without_mirror_feedback():
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller = _RecordingController()
    backend = _build_widgets()
    frontend = _build_widgets()
    bridge = _Bridge(backend, frontend)
    first_ref = "library/" + "a" * 64 + ".json"
    second_ref = "library/" + "b" * 64 + ".json"
    controller.relay_model.set_options((("None", ""), ("First", first_ref), ("Second", second_ref)))
    controller.relay_model.set_connection(ArtifactResolution(first_ref, "a" * 64, "Continuity", None))

    assert controller.bind_runtime_controls({"bridge": bridge}) is True
    assert controller.bind_runtime_controls({"bridge": bridge}) is True
    controller.persona_calls.clear()
    controller.toggle_calls.clear()
    controller.connection_requests.clear()

    frontend.combo.setCurrentIndex(frontend.combo.findData(second_ref))
    assert [item[0] for item in controller.connection_requests] == [second_ref]
    assert controller.persona_calls == []
    assert controller.relay_model.ui_snapshot().connected_ref == first_ref
    frontend.toggle.setChecked(False)
    assert controller.toggle_calls == [False]
    assert frontend.status.text() == "Suspended: Relay disabled for next finalized turn"

    controller.mirror_runtime_widgets({"bridge": bridge, "force": True})
    assert [item[0] for item in controller.connection_requests] == [second_ref]
    assert controller.persona_calls == []
    assert controller.toggle_calls == [False]


def test_mirror_reads_only_cached_snapshot():
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller = IdentityArtifactsController(context=None)
    backend = _build_widgets()
    frontend = _build_widgets()
    bridge = _Bridge(backend, frontend)
    ref = "library/" + "a" * 64 + ".json"
    controller.relay_model.set_options((("Imported Identity", ref),))
    controller.relay_model.set_connection(ArtifactResolution(ref, "a" * 64, "Continuity", None))

    class _ExplodingStore:
        def __getattr__(self, name):
            raise AssertionError(f"mirror touched store.{name}")

    controller.store = _ExplodingStore()
    assert controller.mirror_runtime_widgets({"bridge": bridge}) is True
    assert frontend.combo.currentData() == ref
    assert not frontend.chat_row.isHidden()


def test_operational_status_is_mirrored_and_hidden_without_a_connection():
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller = IdentityArtifactsController(context=None)
    backend = _build_widgets()
    frontend = _build_widgets()
    bridge = _Bridge(backend, frontend)
    controller.bind_runtime_controls({"bridge": bridge})
    controller.update_runtime_transparency(
        status="blocked",
        reason="projection_too_large",
        judging=True,
        rebuild_required=True,
        trace_ids=("trace-123",),
    )
    assert frontend.chat_row.isHidden()

    ref = "library/" + "a" * 64 + ".json"
    controller.relay_model.set_options((("Imported Identity", ref),))
    controller.relay_model.set_connection(ArtifactResolution(ref, "a" * 64, "Continuity", None))
    controller.mirror_runtime_widgets({"bridge": bridge})
    assert not frontend.chat_row.isHidden()
    assert frontend.status.text() == "Blocked: projection_too_large"
    assert not frontend.judging.isHidden()
    assert not frontend.repair_button.isHidden()
    assert not frontend.disable_button.isHidden()
    assert not frontend.rebuild_button.isHidden()
    assert not frontend.trace_button.isHidden()

    frontend.disable_button.click()
    assert controller.relay_model.ui_snapshot().enabled is False
    assert frontend.status.text() == "Suspended: Relay disabled for next finalized turn"
    assert frontend.repair_button.isHidden()
    assert frontend.disable_button.isHidden()


def test_combo_request_preserves_connected_model_until_explicit_review():
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    controller = _RecordingController()
    backend = _build_widgets()
    frontend = _build_widgets()
    bridge = _Bridge(backend, frontend)
    first_ref = "library/" + "a" * 64 + ".json"
    second_ref = "library/" + "b" * 64 + ".json"
    controller.relay_model.set_options((("First", first_ref), ("Second", second_ref)))
    controller.relay_model.set_connection(ArtifactResolution(first_ref, "a" * 64, "Continuity", None))
    requests = []
    controller.request_connection = lambda ref, **kwargs: requests.append((ref, kwargs))
    controller.bind_runtime_controls({"bridge": bridge})

    frontend.combo.setCurrentIndex(frontend.combo.findData(second_ref))
    assert requests and requests[0][0] == second_ref
    assert controller.relay_model.ui_snapshot().connected_ref == first_ref
    assert frontend.combo.currentData() == first_ref


def main() -> int:
    test_designer_and_backend_have_matching_objects()
    test_addon_disabled_defaults_both_rows_hidden()
    test_visibility_matrix_and_strict_combo_data()
    test_combo_rejects_every_non_strict_item_data_value()
    test_mirror_defers_combo_rebuild_while_control_has_focus()
    test_user_changes_reach_controller_once_without_mirror_feedback()
    test_mirror_reads_only_cached_snapshot()
    test_operational_status_is_mirrored_and_hidden_without_a_connection()
    test_combo_request_preserves_connected_model_until_explicit_review()
    print("smoke_identity_relay_ui: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
