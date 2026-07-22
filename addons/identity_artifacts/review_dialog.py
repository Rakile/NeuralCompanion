from __future__ import annotations

import json

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from PySide6 import QtCore, QtWidgets

from addons.identity_artifacts.attestations import ReviewDecision, SubjectClassificationProposal
from addons.identity_artifacts.normalized_model import (
    ReviewItem,
    ReviewKind,
    RuntimeLayer,
    SubjectClass,
    TransientRecord,
)


REVIEW_ACTIONS = ("approve", "reclassify", "narrow_use", "quarantine")
_ACTION_LABELS = {
    "approve": "Approve",
    "reclassify": "Reclassify",
    "narrow_use": "Narrow Use",
    "quarantine": "Quarantine",
}


@dataclass(frozen=True, slots=True)
class ReviewItemDecision:
    review_id: str
    action: str
    proposed_value: str = ""
    replacement_value: str = ""
    allowed_scope: str = ""
    source_reason: str = ""
    prior_state: str = "pending"


@dataclass(frozen=True, slots=True)
class ConnectionReviewResult:
    artifact_ref: str
    artifact_hash: str
    subject_class: SubjectClass
    approved: bool
    item_decisions: tuple[ReviewItemDecision, ...] = ()
    transient_active: bool | None = None


@dataclass(frozen=True, slots=True)
class ConnectionReviewModel:
    artifact_ref: str
    artifact_hash: str
    identity_label: str
    normalizer_revision: str
    schema_version: int
    subject_class: SubjectClass = SubjectClass.UNKNOWN
    proposal: SubjectClassificationProposal | None = None
    review_items: tuple[ReviewItem, ...] = ()
    transient_records: tuple[TransientRecord, ...] = ()
    migration_messages: tuple[str, ...] = ()
    policy_narrowing: tuple[str, ...] = ()
    index_status: str = ""
    trace_ids: tuple[str, ...] = ()
    source_text_by_record: Mapping[str, str] = field(default_factory=dict)
    attestation_normalizer_revision: str = ""
    attestation_approved: bool = False
    attestation_status: str = "not reviewed"
    prior_review_decisions: tuple[ReviewDecision, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_class", SubjectClass(self.subject_class))
        for name in (
            "review_items",
            "transient_records",
            "migration_messages",
            "policy_narrowing",
            "trace_ids",
            "prior_review_decisions",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        source_text = {
            str(record_id): str(text)
            for record_id, text in dict(self.source_text_by_record).items()
        }
        object.__setattr__(self, "source_text_by_record", MappingProxyType(source_text))


class ConnectionReviewDialog(QtWidgets.QDialog):
    reviewApplied = QtCore.Signal(object)
    reviewCancelled = QtCore.Signal()

    def __init__(self, model: ConnectionReviewModel, parent=None):
        super().__init__(parent)
        self.model = model
        self._is_disconnect = not bool(model.artifact_ref)
        self._item_decisions: dict[str, ReviewItemDecision] = {}
        self._transient_active: bool | None = None
        self.review_action_buttons: dict[str, dict[str, QtWidgets.QPushButton]] = {}
        self.review_value_edits: dict[str, QtWidgets.QLineEdit] = {}
        self.review_validation_labels: dict[str, QtWidgets.QLabel] = {}
        self.setObjectName("identity_relay_connection_review_dialog")
        self.setWindowTitle("Identity Relay Connection Review")
        self.setWindowModality(QtCore.Qt.WindowModal)
        self.setWindowFlag(QtCore.Qt.WindowCloseButtonHint, False)
        self.setMinimumSize(720, 320)
        self.resize(780, 380)
        self._build_ui()
        self._update_apply_enabled()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QtWidgets.QLabel(self.model.identity_label or "Identity Relay", self)
        title.setObjectName("identity_relay_review_title")
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        title.setWordWrap(True)
        layout.addWidget(title)

        self.proposal_label = QtWidgets.QLabel(self)
        self.proposal_label.setObjectName("identity_relay_subject_proposal_label")
        self.proposal_label.setWordWrap(True)
        self._show_proposal(self.model.proposal)
        self.proposal_label.setVisible(not self._is_disconnect)
        layout.addWidget(self.proposal_label)

        self.subject_row_widget = QtWidgets.QWidget(self)
        subject_row = QtWidgets.QHBoxLayout(self.subject_row_widget)
        subject_row.setContentsMargins(0, 0, 0, 0)
        subject_row.addWidget(QtWidgets.QLabel("Artifact subject", self.subject_row_widget))
        self.subject_combo = QtWidgets.QComboBox(self)
        self.subject_combo.setObjectName("identity_relay_subject_combo")
        for subject in SubjectClass:
            self.subject_combo.addItem(subject.value.replace("_", " ").title(), subject.value)
        self.subject_combo.setCurrentIndex(self.subject_combo.findData(self.model.subject_class.value))
        self.subject_combo.currentIndexChanged.connect(self._update_apply_enabled)
        subject_row.addWidget(self.subject_combo, 1)
        self.subject_row_widget.setVisible(not self._is_disconnect)
        layout.addWidget(self.subject_row_widget)

        self.review_summary = QtWidgets.QLabel(self._review_summary_text(), self)
        self.review_summary.setObjectName("identity_relay_review_summary")
        self.review_summary.setWordWrap(True)
        layout.addWidget(self.review_summary)

        advanced_content = QtWidgets.QWidget(self)
        advanced_layout = QtWidgets.QVBoxLayout(advanced_content)
        advanced_layout.setContentsMargins(0, 0, 8, 0)
        advanced_layout.setSpacing(10)

        self.review_text = QtWidgets.QTextEdit(advanced_content)
        self.review_text.setObjectName("identity_relay_authorized_review_text")
        self.review_text.setReadOnly(True)
        self.review_text.setPlainText(self._review_source_text())
        self.review_text.setMinimumHeight(150)
        advanced_layout.addWidget(self.review_text)

        self.review_items_widget = QtWidgets.QWidget(advanced_content)
        review_items_layout = QtWidgets.QVBoxLayout(self.review_items_widget)
        review_items_layout.setContentsMargins(0, 0, 0, 0)
        for item in self.model.review_items:
            review_items_layout.addWidget(self._review_item_row(item))
        self.review_items_widget.setVisible(bool(self.model.review_items))
        advanced_layout.addWidget(self.review_items_widget)

        transient_group = QtWidgets.QGroupBox("Transient continuity", advanced_content)
        transient_layout = QtWidgets.QVBoxLayout(transient_group)
        transient_summary = QtWidgets.QLabel(self._transient_text(), transient_group)
        transient_summary.setWordWrap(True)
        transient_layout.addWidget(transient_summary)
        transient_buttons = QtWidgets.QHBoxLayout()
        self.transient_activate_button = QtWidgets.QPushButton("Activate for this chat", transient_group)
        self.transient_activate_button.setObjectName("identity_relay_transient_activate_button")
        self.transient_activate_button.setCheckable(True)
        self.transient_inactive_button = QtWidgets.QPushButton("Keep inactive", transient_group)
        self.transient_inactive_button.setObjectName("identity_relay_transient_inactive_button")
        self.transient_inactive_button.setCheckable(True)
        transient_choice = QtWidgets.QButtonGroup(self)
        transient_choice.setExclusive(True)
        transient_choice.addButton(self.transient_activate_button)
        transient_choice.addButton(self.transient_inactive_button)
        self.transient_activate_button.clicked.connect(lambda: self._choose_transient(True))
        self.transient_inactive_button.clicked.connect(lambda: self._choose_transient(False))
        transient_buttons.addWidget(self.transient_activate_button)
        transient_buttons.addWidget(self.transient_inactive_button)
        transient_buttons.addStretch(1)
        transient_layout.addLayout(transient_buttons)
        transient_group.setVisible(bool(self.model.transient_records))
        advanced_layout.addWidget(transient_group)

        self.transparency_text = QtWidgets.QTextEdit(advanced_content)
        self.transparency_text.setObjectName("identity_relay_review_transparency")
        self.transparency_text.setReadOnly(True)
        self.transparency_text.setMaximumHeight(150)
        self.transparency_text.setPlainText(self._transparency_text())
        advanced_layout.addWidget(self.transparency_text)
        advanced_layout.addStretch(1)

        self.advanced_scroll = QtWidgets.QScrollArea(self)
        self.advanced_scroll.setObjectName("identity_relay_advanced_review_scroll")
        self.advanced_scroll.setWidgetResizable(True)
        self.advanced_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.advanced_scroll.setWidget(advanced_content)
        self.advanced_scroll.hide()
        layout.addWidget(self.advanced_scroll, 1)

        commands = QtWidgets.QHBoxLayout()
        self.cancel_button = QtWidgets.QPushButton("Cancel", self)
        self.cancel_button.setObjectName("identity_relay_review_cancel_button")
        self.cancel_button.clicked.connect(self.cancel_review)
        self.advanced_button = QtWidgets.QPushButton("Advanced Review", self)
        self.advanced_button.setObjectName("identity_relay_advanced_review_button")
        self.advanced_button.setCheckable(True)
        self.advanced_button.toggled.connect(self._set_advanced_visible)
        self.advanced_button.setVisible(not self._is_disconnect)
        apply_text = (
            "Disconnect Identity Relay"
            if self._is_disconnect
            else "Connect as Assistant Identity"
        )
        self.apply_button = QtWidgets.QPushButton(apply_text, self)
        self.apply_button.setObjectName("identity_relay_review_apply_button")
        if self._is_disconnect:
            self.apply_button.clicked.connect(self.accept_review)
        else:
            self.apply_button.clicked.connect(self.connect_as_assistant_identity)
        commands.addWidget(self.cancel_button)
        commands.addWidget(self.advanced_button)
        commands.addStretch(1)
        commands.addWidget(self.apply_button)
        layout.addLayout(commands)

    def _review_summary_text(self) -> str:
        if self._is_disconnect:
            return (
                "Disconnect Identity Relay from the current Persona. The imported "
                "artifact remains in the Identity Relay library."
            )
        review_count = len(self.model.review_items)
        transient_count = len(self.model.transient_records)
        if not review_count and not transient_count:
            return (
                "Connect as Assistant Identity binds this artifact as the current "
                "assistant's own continuity. No unresolved record decisions require "
                "review."
            )
        parts = []
        if review_count:
            parts.append(f"{review_count} ambiguous record decision(s)")
        if transient_count:
            parts.append(f"{transient_count} transient continuity item(s)")
        return (
            f"This artifact contains {' and '.join(parts)}. Connect Identity accepts "
            "untouched records within their existing permission limits and keeps "
            "transient continuity inactive. Use Advanced Review to reclassify, narrow, "
            "quarantine, or activate individual items."
        )

    @QtCore.Slot(bool)
    def _set_advanced_visible(self, visible: bool) -> None:
        self.advanced_scroll.setVisible(bool(visible))
        self.advanced_button.setText(
            "Hide Advanced Review" if visible else "Advanced Review"
        )
        if visible:
            self.resize(max(self.width(), 860), max(self.height(), 680))
        else:
            self.resize(max(self.minimumWidth(), 780), 380)

    def _review_item_row(self, item: ReviewItem) -> QtWidgets.QWidget:
        row = QtWidgets.QWidget(self.review_items_widget)
        layout = QtWidgets.QVBoxLayout(row)
        layout.setContentsMargins(0, 4, 0, 4)
        summary = QtWidgets.QLabel(
            f"{item.review_id}: {item.kind.value} - {item.reason or 'review required'}",
            row,
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        actions_layout = QtWidgets.QHBoxLayout()
        group = QtWidgets.QButtonGroup(row)
        group.setExclusive(True)
        buttons: dict[str, QtWidgets.QPushButton] = {}
        for action in REVIEW_ACTIONS:
            button = QtWidgets.QPushButton(_ACTION_LABELS[action], row)
            button.setObjectName(f"identity_relay_review_{item.review_id}_{action}_button")
            button.setCheckable(True)
            button.clicked.connect(
                lambda _checked=False, review_item=item, choice=action: self._choose_item_action(
                    review_item, choice
                )
            )
            group.addButton(button)
            actions_layout.addWidget(button)
            buttons[action] = button
        actions_layout.addStretch(1)
        layout.addLayout(actions_layout)
        value_edit = QtWidgets.QLineEdit(row)
        value_edit.setObjectName(f"identity_relay_review_{item.review_id}_value")
        value_edit.setPlaceholderText("Replacement classification or allowed runtime-use scope")
        value_edit.textChanged.connect(
            lambda _text, review_item=item: self._refresh_item_decision(review_item)
        )
        layout.addWidget(value_edit)
        validation_label = QtWidgets.QLabel(row)
        validation_label.setObjectName(
            f"identity_relay_review_{item.review_id}_validation"
        )
        validation_label.setWordWrap(True)
        unavailable_reason = str(
            item.details.get("narrow_use_unavailable_reason") or ""
        )
        if not self._supported_values(item, "narrow_use"):
            buttons["narrow_use"].setEnabled(False)
            validation_label.setText(
                unavailable_reason
                or "Narrow Use unavailable: no safely narrower runtime-use scope."
            )
        layout.addWidget(validation_label)
        self.review_value_edits[item.review_id] = value_edit
        self.review_validation_labels[item.review_id] = validation_label
        self.review_action_buttons[item.review_id] = buttons
        return row

    def _review_source_text(self) -> str:
        lines = ["Authorized source review"]
        for item in self.model.review_items:
            lines.append(f"\n{item.review_id} ({item.kind.value})")
            lines.append(f"Review state: {item.state}")
            lines.extend(f"Path: {path}" for path in item.source_paths)
            for record_id in item.record_ids:
                lines.append(f"Record: {record_id}")
                source_text = self.model.source_text_by_record.get(record_id, "")
                if source_text:
                    lines.append(source_text)
        for transient in self.model.transient_records:
            lines.append(f"\nTransient {transient.record_id}: {transient.source_text}")
        return "\n".join(lines)

    def _transient_text(self) -> str:
        lines = []
        for transient in self.model.transient_records:
            lines.append(
                f"{transient.record_id}: TTL={transient.ttl_hint or 'unspecified'}; "
                f"included={', '.join(transient.included_item_ids) or 'none'}; "
                f"confidence={transient.confidence}; staleness={transient.staleness_risk}"
            )
            lines.extend(transient.expiration_notes)
        return "\n".join(lines)

    def _transparency_text(self) -> str:
        lines = [
            f"Normalizer revision: {self.model.normalizer_revision or 'unknown'}",
            f"Normalized schema: {self.model.schema_version}",
            f"Attestation normalizer revision: {self.model.attestation_normalizer_revision or 'none'}",
            f"Attestation status: {self.model.attestation_status}; approved={self.model.attestation_approved}",
        ]
        for item in self.model.prior_review_decisions:
            try:
                details = json.loads(item.reason)
            except (TypeError, ValueError, json.JSONDecodeError):
                details = {"source_reason": item.reason}
            if not isinstance(details, Mapping):
                details = {"source_reason": item.reason}
            lines.extend(
                (
                    f"Prior review: {item.review_id} / {item.choice}",
                    f"Reviewer: {details.get('actor') or 'unknown'}",
                    f"Reviewed: {item.reviewed_at or 'unknown'}",
                    f"Revision: {item.revision}",
                    f"Source reason: {details.get('source_reason') or ''}",
                    f"Source proposed value: {details.get('proposed_value') or ''}",
                    f"Replacement classification: {details.get('replacement_value') or ''}",
                    f"Narrowed scope: {details.get('allowed_scope') or ''}",
                    f"Approved: {item.approved}",
                    f"Prior state: {details.get('prior_state') or ''}",
                )
            )
        lines.extend(f"Migration: {item}" for item in self.model.migration_messages)
        lines.extend(f"Policy narrowing: {item}" for item in self.model.policy_narrowing)
        if self.model.index_status:
            lines.append(f"Index: {self.model.index_status}")
        lines.extend(f"Trace ID: {item}" for item in self.model.trace_ids)
        return "\n".join(lines)

    def _show_proposal(self, proposal: SubjectClassificationProposal | None) -> None:
        if proposal is None:
            self.proposal_label.setText("No subject proposal is applied. Choose a subject explicitly.")
            return
        origin = " / ".join(value for value in (proposal.provider, proposal.model) if value)
        prefix = f"Active-model proposal ({origin})" if origin else "Subject proposal"
        self.proposal_label.setText(
            f"{prefix}: {proposal.proposed_class.value}. Reason: {proposal.reason} "
            "This proposal is not applied automatically."
        )

    def set_proposal(self, proposal: SubjectClassificationProposal) -> None:
        self._show_proposal(proposal)

    def set_proposal_unavailable(self, reason: str) -> None:
        self.proposal_label.setText(
            f"Active-model proposal unavailable: {reason}. Choose a subject explicitly."
        )

    def choose_subject(self, subject: str | SubjectClass) -> None:
        subject_class = SubjectClass(subject)
        index = self.subject_combo.findData(subject_class.value)
        if index >= 0:
            self.subject_combo.setCurrentIndex(index)

    def selected_subject(self) -> SubjectClass:
        return SubjectClass(str(self.subject_combo.currentData() or SubjectClass.UNKNOWN.value))

    def _choose_item_action(self, item: ReviewItem, action: str) -> None:
        user_value = self.review_value_edits[item.review_id].text().strip()
        self._item_decisions[item.review_id] = ReviewItemDecision(
            review_id=item.review_id,
            action=action,
            proposed_value=item.proposed_value,
            replacement_value=user_value if action == "reclassify" else "",
            allowed_scope=user_value if action == "narrow_use" else "",
            source_reason=item.reason,
            prior_state=item.state,
        )
        self._update_apply_enabled()

    def _refresh_item_decision(self, item: ReviewItem) -> None:
        decision = self._item_decisions.get(item.review_id)
        if decision is not None:
            self._choose_item_action(item, decision.action)
        else:
            self._update_apply_enabled()

    @staticmethod
    def _supported_values(item: ReviewItem, action: str) -> tuple[str, ...]:
        if action == "narrow_use":
            values = item.details.get("supported_runtime_use_scopes", ())
        elif item.kind == ReviewKind.SUBJECT_CLASS:
            values = tuple(
                subject.value for subject in SubjectClass if subject != SubjectClass.UNKNOWN
            )
        elif item.kind == ReviewKind.RUNTIME_LAYER:
            values = (RuntimeLayer.KERNEL.value, RuntimeLayer.RETRIEVABLE.value)
        else:
            values = item.details.get("supported_reclassifications", ())
        if not isinstance(values, (tuple, list)):
            return ()
        return tuple(str(value) for value in values if str(value))

    def _decision_value_valid(self, item: ReviewItem, decision: ReviewItemDecision) -> bool:
        if decision.action not in {"reclassify", "narrow_use"}:
            self.review_validation_labels[item.review_id].setText(
                str(item.details.get("narrow_use_unavailable_reason") or "")
            )
            return True
        value = decision.replacement_value or decision.allowed_scope
        supported = self._supported_values(item, decision.action)
        valid = bool(value) and value in supported
        unavailable_reason = str(
            item.details.get("narrow_use_unavailable_reason") or ""
        )
        if not valid:
            validation_text = "Invalid value. Choose a supported review value."
        elif decision.action != "narrow_use":
            validation_text = unavailable_reason
        else:
            validation_text = ""
        self.review_validation_labels[item.review_id].setText(validation_text)
        return valid

    def _choose_transient(self, active: bool) -> None:
        self._transient_active = bool(active)
        self._update_apply_enabled()

    def _update_apply_enabled(self, *_args) -> None:
        item_values_complete = all(
            self._decision_value_valid(item, self._item_decisions[item.review_id])
            for item in self.model.review_items
            if item.review_id in self._item_decisions
        )
        self.apply_button.setEnabled(item_values_complete)

    def _apply_safe_defaults(self) -> None:
        for item in self.model.review_items:
            if item.review_id in self._item_decisions:
                continue
            self._item_decisions[item.review_id] = ReviewItemDecision(
                review_id=item.review_id,
                action="approve",
                proposed_value=item.proposed_value,
                source_reason=item.reason,
                prior_state=item.state,
            )
            self.review_action_buttons[item.review_id]["approve"].setChecked(True)
        if self.model.transient_records and self._transient_active is None:
            self._transient_active = False
            self.transient_inactive_button.setChecked(True)

    @QtCore.Slot()
    def connect_as_assistant_identity(self) -> None:
        self.choose_subject(SubjectClass.ASSISTANT_SELF)
        self.accept_review()

    @QtCore.Slot()
    def accept_review(self) -> None:
        if not self.apply_button.isEnabled():
            return
        self._apply_safe_defaults()
        self._update_apply_enabled()
        if not self.apply_button.isEnabled():
            return
        result = ConnectionReviewResult(
            artifact_ref=self.model.artifact_ref,
            artifact_hash=self.model.artifact_hash,
            subject_class=self.selected_subject(),
            approved=True,
            item_decisions=tuple(
                self._item_decisions[item.review_id] for item in self.model.review_items
            ),
            transient_active=self._transient_active,
        )
        self.reviewApplied.emit(result)
        self.hide()

    @QtCore.Slot()
    def cancel_review(self) -> None:
        self.reviewCancelled.emit()
        self.hide()

    def reject(self) -> None:
        self.cancel_review()

    def closeEvent(self, event) -> None:
        event.ignore()
