"""Native QML Identity Relay import and artifact-inspection surface."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Mapping

from PySide6 import QtCore, QtGui

from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.native_contracts import (
    NativeChoice,
    NativeControl,
    NativeControlKind,
    NativeSurface,
)
from ui.qml_bridge.native_registry import NativeSurfaceAdapter


def _local_path(payload: object) -> str:
    values = list(payload or [])
    text = str(values[0] if values else "").strip()
    url = QtCore.QUrl(text)
    return url.toLocalFile() if url.isLocalFile() else text


class IdentityArtifactsNativeAdapter(NativeSurfaceAdapter):
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
        self._persist = persist
        self._revision = 0
        self._source_label = ""
        self._pasted_artifact = ""
        self._selected_ref = ""

    def _invoke(self, capability: str, payload=None) -> object:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id,
            capability,
            dict(payload or {}),
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "Identity Relay is unavailable."))
            )
        return result.value

    @staticmethod
    def _artifact_label(item: Mapping[str, object]) -> str:
        provider = str(item.get("provider_label") or "").strip()
        artifact_id = str(item.get("artifact_id") or item.get("artifact_ref") or "")
        status = str(item.get("status") or "unknown")
        version = str(item.get("format_version") or "")
        prefix = f"{provider} - " if provider else ""
        return f"{prefix}{artifact_id} [{status} v{version}]"

    def _snapshot_payload(self) -> dict[str, object]:
        value = self._invoke(
            "runtime.identity_artifacts.snapshot",
            {"selected_ref": self._selected_ref},
        )
        if not isinstance(value, Mapping):
            raise RuntimeError("Identity Relay snapshot is not a mapping.")
        return dict(value)

    def snapshot(self) -> NativeSurface:
        payload = self._snapshot_payload()
        artifacts = tuple(dict(item) for item in list(payload.get("artifacts") or []))
        selected = str(payload.get("selected_ref") or "")
        self._selected_ref = selected
        options = tuple(
            NativeChoice(
                str(item.get("artifact_ref") or item.get("artifact_id") or ""),
                self._artifact_label(item),
            )
            for item in artifacts
            if str(item.get("artifact_ref") or item.get("artifact_id") or "")
        )
        values: dict[str, object] = {
            "identity_relay_overview": (
                "Import source-native NC_IDENTITY_EXPORT artifacts, preserve the raw "
                "export, and inspect the best-effort structured extraction."
            ),
            "identity_relay_view_protocol": "",
            "identity_relay_protocol_status": str(payload.get("protocol_status") or ""),
            "identity_relay_owner_override": bool(payload.get("owner_override", False)),
            "identity_relay_owner_status": str(payload.get("owner_override_status") or ""),
            "identity_relay_source_label": self._source_label,
            "identity_relay_pasted_artifact": self._pasted_artifact,
            "identity_relay_artifacts": selected,
            "identity_relay_summary": str(payload.get("summary") or ""),
            "identity_relay_raw": str(payload.get("raw") or ""),
            "identity_relay_structured": str(payload.get("structured") or ""),
            "identity_relay_warnings": str(payload.get("warnings") or ""),
        }
        controls = []
        for control in self._surface.controls:
            updates: dict[str, object] = {
                "value": values.get(control.id, control.default_value)
            }
            if control.id == "identity_relay_artifacts":
                updates["choices"] = options or (NativeChoice("", "No artifacts"),)
            elif control.id == "identity_relay_view_protocol":
                updates["metadata"] = {
                    **dict(control.metadata),
                    "viewerText": str(payload.get("protocol") or ""),
                }
            controls.append(replace(control, **updates))
        return replace(
            self._surface,
            controls=apply_card_layout(controls),
            revision=self._revision,
        )

    def set_value(self, control_id: str, value: Any) -> None:
        key = str(control_id or "").strip()
        if key == "identity_relay_source_label":
            self._source_label = str(value or "")
        elif key == "identity_relay_pasted_artifact":
            self._pasted_artifact = str(value or "")
        elif key == "identity_relay_artifacts":
            self._selected_ref = str(value or "").strip()
        elif key == "identity_relay_owner_override":
            self._invoke(
                "runtime.identity_artifacts.set_owner_override",
                {"enabled": bool(value)},
            )
            if callable(self._persist):
                self._persist()
        else:
            raise KeyError(f"Unknown Identity Relay setting '{control_id}'.")
        self._revision += 1
        self.changed.emit()

    def trigger(self, control_id: str) -> None:
        self.trigger_with_payload(control_id, None)

    def trigger_with_payload(self, control_id: str, payload: Any) -> None:
        action = str(control_id or "").strip()
        if action == "identity_relay_view_protocol":
            return
        if action == "identity_relay_copy_protocol":
            protocol = str(self._snapshot_payload().get("protocol") or "")
            clipboard = QtGui.QGuiApplication.clipboard()
            if clipboard is None:
                raise RuntimeError("The system clipboard is unavailable.")
            clipboard.setText(protocol)
        else:
            names = {
                "identity_relay_import_pasted": "import_text",
                "identity_relay_import_file": "import_file",
                "identity_relay_refresh": "refresh",
                "identity_relay_reextract": "reextract",
                "identity_relay_delete": "delete",
            }
            name = names.get(action)
            if name is None:
                raise KeyError(f"Unknown Identity Relay action '{control_id}'.")
            request: dict[str, object] = {
                "selected_ref": self._selected_ref,
                "provider": self._source_label,
            }
            if name == "import_text":
                request["text"] = self._pasted_artifact
            elif name == "import_file":
                request["path"] = _local_path(payload)
            result = self._invoke(
                "runtime.identity_artifacts.action",
                {"action": name, "payload": request},
            )
            if isinstance(result, Mapping):
                self._selected_ref = str(result.get("selected_ref") or "")
            if name == "import_text":
                self._pasted_artifact = ""
        self._revision += 1
        self.changed.emit()


def build_identity_artifacts_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
) -> IdentityArtifactsNativeAdapter:
    surface = NativeSurface(
        id="identity_artifacts_tab",
        title="NC Identity Relay",
        addon_id="nc.identity_artifacts",
        sections=("Overview", "Create Identity Export", "Privacy", "Import", "Stored Artifacts"),
        description="Import and inspect identity-continuity artifacts without exposing them implicitly.",
        controls=(
            NativeControl("identity_relay_overview", "Overview", NativeControlKind.DISPLAY, "Overview"),
            NativeControl("identity_relay_view_protocol", "View Export Protocol", NativeControlKind.ACTION, "Create Identity Export", metadata={"execution": "ui", "textViewer": True, "dialogTitle": "ReflectAndExportIdentity v1.1 Protocol", "viewerDescription": "Send this complete protocol to the external LLM session you want to export from."}),
            NativeControl("identity_relay_copy_protocol", "Copy Export Protocol", NativeControlKind.ACTION, "Create Identity Export", metadata={"execution": "ui"}),
            NativeControl("identity_relay_protocol_status", "Protocol status", NativeControlKind.DISPLAY, "Create Identity Export"),
            NativeControl("identity_relay_owner_override", "Owner Override: allow selected records to external providers", NativeControlKind.BOOLEAN, "Privacy", default_value=False, metadata={"confirmOnEnable": True, "confirmationTitle": "Enable Identity Relay Owner Override?", "confirmationText": "This removes the provider-exposure barrier for identity records selected for a turn. Relevance, capacity, provenance, malformed-data, and quarantine checks still apply."}),
            NativeControl("identity_relay_owner_status", "Owner Override status", NativeControlKind.DISPLAY, "Privacy"),
            NativeControl("identity_relay_source_label", "Source label", NativeControlKind.TEXT, "Import"),
            NativeControl("identity_relay_pasted_artifact", "Pasted NC_IDENTITY_EXPORT artifact", NativeControlKind.MULTILINE, "Import"),
            NativeControl("identity_relay_import_pasted", "Import Pasted Artifact", NativeControlKind.ACTION, "Import"),
            NativeControl("identity_relay_import_file", "Import From File", NativeControlKind.ACTION, "Import", metadata={"execution": "ui", "filePicker": True, "dialogTitle": "Import identity artifact", "nameFilters": ["Identity artifacts (*.json *.txt)", "All files (*)"]}),
            NativeControl("identity_relay_refresh", "Refresh", NativeControlKind.ACTION, "Import"),
            NativeControl("identity_relay_artifacts", "Stored Artifacts", NativeControlKind.LIST, "Stored Artifacts", choices=(NativeChoice("", "No artifacts"),)),
            NativeControl("identity_relay_reextract", "Re-run Extraction", NativeControlKind.ACTION, "Stored Artifacts"),
            NativeControl("identity_relay_delete", "Delete Artifact", NativeControlKind.ACTION, "Stored Artifacts", metadata={"destructive": True}),
            NativeControl("identity_relay_summary", "Artifact summary", NativeControlKind.DISPLAY, "Stored Artifacts"),
            NativeControl("identity_relay_raw", "Raw Artifact", NativeControlKind.MULTILINE, "Stored Artifacts", metadata={"readOnly": True}),
            NativeControl("identity_relay_structured", "Structured Extraction", NativeControlKind.MULTILINE, "Stored Artifacts", metadata={"readOnly": True}),
            NativeControl("identity_relay_warnings", "Mechanical Warnings", NativeControlKind.MULTILINE, "Stored Artifacts", metadata={"readOnly": True}),
        ),
    )
    return IdentityArtifactsNativeAdapter(
        application_facade,
        surface,
        persist=persist,
    )


__all__ = ["IdentityArtifactsNativeAdapter", "build_identity_artifacts_adapter"]
