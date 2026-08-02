from __future__ import annotations

import copy

from PySide6 import QtCore, QtWidgets

from .models import (
    BEHAVIOR_REPLY_LENGTHS,
    DEFAULT_ADULT_NSFW_PROMPT,
    DEFAULT_NORMAL_INTIMACY_PROMPT,
    DEFAULT_SYSTEM_OVERRIDE_PROMPT,
    BuddyBehaviorProfile,
    BuddyPersona,
)
from .refinement import RefinementRequest, refinement_differences
from .setup_models import BuddySetupPreview, GroupBehavior, WizardChoices
from .setup_templates import (
    compose_wizard_preview,
    preset_previews,
    preview_for_preset,
)


_BEHAVIOR_FIELDS = (
    ("helpfulness", "Helpfulness"),
    ("warmth", "Warmth"),
    ("humor", "Humor"),
    ("expressiveness", "Expressiveness"),
    ("initiative", "Initiative"),
    ("directness", "Directness"),
    ("disagreement", "Willingness to disagree"),
    ("flirtation", "Flirtation"),
    ("participation_weight", "Participation weight"),
)


class BuddyCharacterEditor(QtWidgets.QDialog):
    def __init__(
        self,
        persona: BuddyPersona,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._baseline = BuddyPersona.from_dict(
            copy.deepcopy(persona.to_dict())
        )
        self.behavior_sliders: dict[str, QtWidgets.QSlider] = {}
        self.behavior_value_labels: dict[str, QtWidgets.QLabel] = {}
        self.setObjectName("buddy_character_editor")
        self.setWindowTitle(f"Edit Character - {persona.display_name}")
        self.resize(720, 760)
        self._build_ui()
        self._load_persona_into_controls(self._baseline)

    def _build_ui(self) -> None:
        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(10)

        heading = QtWidgets.QLabel("Character and behavior")
        heading_font = heading.font()
        heading_font.setPointSize(14)
        heading_font.setBold(True)
        heading.setFont(heading_font)
        hint = QtWidgets.QLabel(
            "Edit the complete character prompt and natural-response behavior. "
            "Voice, avatar, and provider settings stay unchanged."
        )
        hint.setWordWrap(True)
        root_layout.addWidget(heading)
        root_layout.addWidget(hint)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 8, 0)
        content_layout.setSpacing(12)

        character_box = QtWidgets.QGroupBox("Identity and complete prompt")
        character_layout = QtWidgets.QFormLayout(character_box)
        character_layout.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.AllNonFixedFieldsGrow
        )
        self.name_edit = QtWidgets.QLineEdit()
        self.role_edit = QtWidgets.QLineEdit()
        self.description_edit = QtWidgets.QPlainTextEdit()
        self.description_edit.setMinimumHeight(90)
        self.system_prompt_edit = QtWidgets.QPlainTextEdit()
        self.system_prompt_edit.setMinimumHeight(150)
        self.style_edit = QtWidgets.QLineEdit()
        character_layout.addRow(
            "Name",
            self._field_with_reset(self.name_edit, "display_name"),
        )
        character_layout.addRow(
            "Role",
            self._field_with_reset(self.role_edit, "role"),
        )
        character_layout.addRow(
            "Detailed description",
            self._field_with_reset(self.description_edit, "description"),
        )
        character_layout.addRow(
            "Complete system prompt",
            self._field_with_reset(self.system_prompt_edit, "system_prompt"),
        )
        character_layout.addRow(
            "Speaking style",
            self._field_with_reset(self.style_edit, "speaking_style"),
        )
        content_layout.addWidget(character_box)

        behavior_box = QtWidgets.QGroupBox("Natural response behavior")
        behavior_layout = QtWidgets.QFormLayout(behavior_box)
        behavior_layout.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.AllNonFixedFieldsGrow
        )
        for field_name, label in _BEHAVIOR_FIELDS:
            slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            slider.setObjectName(f"buddy_behavior_{field_name}")
            slider.setRange(0, 100)
            slider.setSingleStep(1)
            value_label = QtWidgets.QLabel("0")
            value_label.setMinimumWidth(30)
            value_label.setAlignment(
                QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
            )
            slider.valueChanged.connect(
                lambda value, target=value_label: target.setText(str(value))
            )
            self.behavior_sliders[field_name] = slider
            self.behavior_value_labels[field_name] = value_label
            row = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(slider, 1)
            row_layout.addWidget(value_label)
            reset_button = QtWidgets.QToolButton()
            reset_button.setText("Reset")
            reset_button.setToolTip(f"Reset {label.lower()} to this setup's value.")
            reset_button.clicked.connect(
                lambda _checked=False, key=field_name:
                self.reset_field(key)
            )
            row_layout.addWidget(reset_button)
            behavior_layout.addRow(label, row)

        self.reply_length_combo = QtWidgets.QComboBox()
        for value in BEHAVIOR_REPLY_LENGTHS:
            self.reply_length_combo.addItem(value.title(), value)
        behavior_layout.addRow(
            "Typical reply length",
            self._field_with_reset(
                self.reply_length_combo,
                "reply_length",
            ),
        )
        participation_hint = QtWidgets.QLabel(
            "Participation weight changes which unmentioned buddy is considered "
            "first. It never overrides a named buddy or the group speaker limit."
        )
        participation_hint.setWordWrap(True)
        behavior_layout.addRow("", participation_hint)
        content_layout.addWidget(behavior_box)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        root_layout.addWidget(scroll, 1)

        actions = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save
            | QtWidgets.QDialogButtonBox.Cancel
            | QtWidgets.QDialogButtonBox.Reset
        )
        reset_button = actions.button(QtWidgets.QDialogButtonBox.Reset)
        reset_button.setText("Reset Buddy")
        reset_button.setToolTip(
            "Restore all character and behavior fields to the setup baseline."
        )
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        reset_button.clicked.connect(self.reset_buddy)
        root_layout.addWidget(actions)

    def _field_with_reset(
        self,
        field: QtWidgets.QWidget,
        field_name: str,
    ) -> QtWidgets.QWidget:
        row = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(field, 1)
        reset_button = QtWidgets.QToolButton()
        reset_button.setText("Reset")
        reset_button.setToolTip("Restore this field to the setup baseline.")
        reset_button.clicked.connect(
            lambda _checked=False, key=field_name: self.reset_field(key)
        )
        row_layout.addWidget(reset_button)
        return row

    def persona(self) -> BuddyPersona:
        profile = BuddyBehaviorProfile(
            helpfulness=self.behavior_sliders["helpfulness"].value(),
            warmth=self.behavior_sliders["warmth"].value(),
            humor=self.behavior_sliders["humor"].value(),
            expressiveness=self.behavior_sliders["expressiveness"].value(),
            initiative=self.behavior_sliders["initiative"].value(),
            directness=self.behavior_sliders["directness"].value(),
            disagreement=self.behavior_sliders["disagreement"].value(),
            flirtation=self.behavior_sliders["flirtation"].value(),
            reply_length=str(
                self.reply_length_combo.currentData() or "balanced"
            ),
            participation_weight=self.behavior_sliders[
                "participation_weight"
            ].value(),
        )
        updated = BuddyPersona.from_dict(
            copy.deepcopy(self._baseline.to_dict())
        )
        updated.display_name = (
            self.name_edit.text().strip() or updated.display_name
        )
        updated.role = self.role_edit.text().strip()
        updated.description = self.description_edit.toPlainText().strip()
        updated.system_prompt = (
            self.system_prompt_edit.toPlainText().strip()
        )
        updated.speaking_style = self.style_edit.text().strip()
        updated.behavior = profile
        return updated

    def reset_field(self, field_name: str) -> None:
        baseline = self._baseline
        text_fields = {
            "display_name": (self.name_edit, baseline.display_name),
            "role": (self.role_edit, baseline.role),
            "speaking_style": (
                self.style_edit,
                baseline.speaking_style,
            ),
        }
        plain_fields = {
            "description": (
                self.description_edit,
                baseline.description,
            ),
            "system_prompt": (
                self.system_prompt_edit,
                baseline.system_prompt,
            ),
        }
        if field_name in text_fields:
            widget, value = text_fields[field_name]
            widget.setText(value)
            return
        if field_name in plain_fields:
            widget, value = plain_fields[field_name]
            widget.setPlainText(value)
            return
        profile = baseline.behavior or BuddyBehaviorProfile()
        if field_name in self.behavior_sliders:
            self.behavior_sliders[field_name].setValue(
                int(getattr(profile, field_name))
            )
            return
        if field_name == "reply_length":
            index = self.reply_length_combo.findData(profile.reply_length)
            self.reply_length_combo.setCurrentIndex(max(0, index))

    def reset_buddy(self) -> None:
        self._load_persona_into_controls(self._baseline)

    def _load_persona_into_controls(
        self,
        persona: BuddyPersona,
    ) -> None:
        self.name_edit.setText(persona.display_name)
        self.role_edit.setText(persona.role)
        self.description_edit.setPlainText(persona.description)
        self.system_prompt_edit.setPlainText(persona.system_prompt)
        self.style_edit.setText(persona.speaking_style)
        profile = persona.behavior or BuddyBehaviorProfile()
        for field_name, slider in self.behavior_sliders.items():
            slider.setValue(int(getattr(profile, field_name)))
        index = self.reply_length_combo.findData(profile.reply_length)
        self.reply_length_combo.setCurrentIndex(max(0, index))


class BuddyRefinementReview(QtWidgets.QDialog):
    def __init__(
        self,
        before: BuddySetupPreview,
        after: BuddySetupPreview,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("buddy_refinement_review")
        self.setWindowTitle("Review Buddy Chat refinement")
        self.resize(760, 680)
        self.field_checks: dict[str, QtWidgets.QCheckBox] = {}

        root_layout = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel("Review before applying")
        heading_font = heading.font()
        heading_font.setPointSize(14)
        heading_font.setBold(True)
        heading.setFont(heading_font)
        hint = QtWidgets.QLabel(
            "The LLM result has not changed the preview. Uncheck any fields "
            "you do not want, then apply the selected changes."
        )
        hint.setWordWrap(True)
        root_layout.addWidget(heading)
        root_layout.addWidget(hint)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 8, 0)
        differences = sorted(
            refinement_differences(before, after),
            key=lambda item: item.path,
        )
        for difference in differences:
            card = QtWidgets.QGroupBox()
            card_layout = QtWidgets.QVBoxLayout(card)
            checkbox = QtWidgets.QCheckBox(difference.label)
            checkbox.setChecked(True)
            checkbox.toggled.connect(self._update_apply_enabled)
            self.field_checks[difference.path] = checkbox
            comparison = QtWidgets.QPlainTextEdit()
            comparison.setReadOnly(True)
            comparison.setMinimumHeight(82)
            comparison.setPlainText(
                "Before:\n"
                f"{difference.before[:1600]}\n\n"
                "After:\n"
                f"{difference.after[:1600]}"
            )
            card_layout.addWidget(checkbox)
            card_layout.addWidget(comparison)
            content_layout.addWidget(card)
        if not differences:
            empty = QtWidgets.QLabel(
                "The model returned no visible changes."
            )
            empty.setWordWrap(True)
            content_layout.addWidget(empty)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        root_layout.addWidget(scroll, 1)

        self._buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Apply
            | QtWidgets.QDialogButtonBox.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        root_layout.addWidget(self._buttons)
        self._update_apply_enabled()

    def selected_fields(self) -> set[str]:
        return {
            path
            for path, checkbox in self.field_checks.items()
            if checkbox.isChecked()
        }

    def _update_apply_enabled(self, *_args: object) -> None:
        button = self._buttons.button(QtWidgets.QDialogButtonBox.Apply)
        button.setEnabled(bool(self.selected_fields()))


class SetupStudio(QtWidgets.QWidget):
    preview_changed = QtCore.Signal(object)
    apply_requested = QtCore.Signal(object)
    undo_requested = QtCore.Signal()
    adult_mode_requested = QtCore.Signal(bool)
    refinement_requested = QtCore.Signal(object)
    refinement_cancel_requested = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("buddy_setup_studio")
        self._preview: BuddySetupPreview | None = None
        self._trait_checks: dict[str, QtWidgets.QCheckBox] = {}
        self.group_mode_buttons: dict[str, QtWidgets.QPushButton] = {}
        self._prompt_layer_baseline = {
            "system_override_prompt": DEFAULT_SYSTEM_OVERRIDE_PROMPT,
            "normal_intimacy_prompt": DEFAULT_NORMAL_INTIMACY_PROMPT,
            "adult_nsfw_prompt": DEFAULT_ADULT_NSFW_PROMPT,
        }
        self._build_ui()
        self.set_preview(preview_for_preset("reliable_guide"))

    def _build_ui(self) -> None:
        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(12)

        header = QtWidgets.QWidget()
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        title_column = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel("Build your Buddy group")
        title_font = title.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        subtitle = QtWidgets.QLabel(
            "Use three guided choices or preview one of four complete groups."
        )
        subtitle.setWordWrap(True)
        subtitle.setProperty("muted", True)
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        self._adult_toggle = QtWidgets.QCheckBox("Adult / NSFW")
        self._adult_toggle.setObjectName("buddy_adult_nsfw_toggle")
        self._adult_toggle.setToolTip(
            "Allow the editable adult prompt layer for explicitly adult personas. "
            "The active model or provider may still impose restrictions."
        )
        self._adult_toggle.toggled.connect(self.adult_mode_requested.emit)
        header_layout.addLayout(title_column, 1)
        header_layout.addWidget(self._adult_toggle, 0, QtCore.Qt.AlignTop)
        root_layout.addWidget(header)

        body = QtWidgets.QWidget()
        body_layout = QtWidgets.QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)

        wizard = QtWidgets.QGroupBox("Build my group")
        wizard.setObjectName("buddy_setup_wizard")
        wizard_layout = QtWidgets.QFormLayout(wizard)
        wizard_layout.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.AllNonFixedFieldsGrow
        )
        self._buddy_count = QtWidgets.QComboBox()
        self._buddy_count.addItem("1 - Focused", 1)
        self._buddy_count.addItem("2 - Balanced", 2)
        self._buddy_count.addItem("3 - Lively", 3)
        self._buddy_count.setCurrentIndex(1)
        self._participation = QtWidgets.QComboBox()
        self._participation.addItem("Focused", "focused")
        self._participation.addItem("Balanced", "balanced")
        self._participation.addItem("Lively", "lively")
        self._participation.setCurrentIndex(1)
        wizard_layout.addRow("Buddies", self._buddy_count)
        wizard_layout.addRow("Participation", self._participation)

        traits_widget = QtWidgets.QWidget()
        traits_layout = QtWidgets.QGridLayout(traits_widget)
        traits_layout.setContentsMargins(0, 0, 0, 0)
        trait_specs = (
            ("practical", "Practical help"),
            ("warm", "Emotional warmth"),
            ("playful", "Playful energy"),
            ("expressive", "Expressiveness"),
            ("honest", "Honest disagreement"),
            ("creative", "Creativity"),
            ("flirtatious", "Flirtation"),
        )
        for index, (trait_id, label) in enumerate(trait_specs):
            checkbox = QtWidgets.QCheckBox(label)
            checkbox.setProperty("buddy_trait", trait_id)
            if trait_id in {"practical", "warm", "honest"}:
                checkbox.setChecked(True)
            self._trait_checks[trait_id] = checkbox
            traits_layout.addWidget(checkbox, index // 2, index % 2)
        wizard_layout.addRow("Character traits", traits_widget)
        build_button = QtWidgets.QPushButton("Preview guided group")
        build_button.setObjectName("buddy_setup_build_preview")
        build_button.clicked.connect(self._build_wizard_preview)
        wizard_layout.addRow("", build_button)
        body_layout.addWidget(wizard, 3)

        presets_box = QtWidgets.QGroupBox("Complete quick starts")
        presets_layout = QtWidgets.QVBoxLayout(presets_box)
        preset_hint = QtWidgets.QLabel(
            "Each setup includes complete prompts and editable behavior."
        )
        preset_hint.setWordWrap(True)
        preset_hint.setProperty("muted", True)
        presets_layout.addWidget(preset_hint)
        for preview in preset_previews():
            count = len(preview.personas)
            button = QtWidgets.QPushButton(
                f"{preview.title}\n{count} {'buddy' if count == 1 else 'buddies'}"
            )
            button.setObjectName(f"buddy_preset_{preview.setup_id}")
            button.setToolTip(preview.summary)
            button.setMinimumHeight(52)
            button.clicked.connect(
                lambda _checked=False, setup_id=preview.setup_id:
                self.set_preview(preview_for_preset(setup_id))
            )
            presets_layout.addWidget(button)
        presets_layout.addStretch(1)
        body_layout.addWidget(presets_box, 2)
        root_layout.addWidget(body)

        preview_box = QtWidgets.QGroupBox("Group preview")
        preview_layout = QtWidgets.QVBoxLayout(preview_box)
        self._preview_title = QtWidgets.QLabel()
        preview_title_font = self._preview_title.font()
        preview_title_font.setBold(True)
        self._preview_title.setFont(preview_title_font)
        self._preview_text = QtWidgets.QPlainTextEdit()
        self._preview_text.setObjectName("buddy_setup_preview_text")
        self._preview_text.setReadOnly(True)
        self._preview_text.setMinimumHeight(145)
        preview_layout.addWidget(self._preview_title)
        preview_layout.addWidget(self._preview_text)

        group_box = QtWidgets.QGroupBox("Group participation")
        group_layout = QtWidgets.QGridLayout(group_box)
        group_layout.addWidget(QtWidgets.QLabel("Quick balance"), 0, 0)
        group_modes = QtWidgets.QWidget()
        group_modes_layout = QtWidgets.QHBoxLayout(group_modes)
        group_modes_layout.setContentsMargins(0, 0, 0, 0)
        for mode in ("focused", "balanced", "lively"):
            button = QtWidgets.QPushButton(mode.title())
            button.setCheckable(True)
            button.setObjectName(f"buddy_group_mode_{mode}")
            button.clicked.connect(
                lambda _checked=False, selected=mode:
                self._apply_group_mode(selected)
            )
            self.group_mode_buttons[mode] = button
            group_modes_layout.addWidget(button)
        group_modes_layout.addStretch(1)
        group_layout.addWidget(group_modes, 0, 1, 1, 3)

        self.max_speakers_spin = QtWidgets.QSpinBox()
        self.max_speakers_spin.setObjectName("buddy_group_max_speakers")
        self.max_speakers_spin.setRange(1, 3)
        self.allow_buddy_to_buddy_check = QtWidgets.QCheckBox(
            "Allow buddies to react to each other"
        )
        self.allow_buddy_to_buddy_check.setObjectName(
            "buddy_group_allow_buddy_to_buddy"
        )
        self.natural_second_speaker_spin = QtWidgets.QSpinBox()
        self.natural_second_speaker_spin.setObjectName(
            "buddy_group_natural_second_speaker"
        )
        self.natural_second_speaker_spin.setRange(0, 100)
        self.natural_second_speaker_spin.setSpecialValueText("Off")
        self.forced_buddy_spin = QtWidgets.QSpinBox()
        self.forced_buddy_spin.setObjectName("buddy_group_forced_buddy")
        self.forced_buddy_spin.setRange(0, 100)
        self.forced_buddy_spin.setSpecialValueText("Off")
        group_layout.addWidget(QtWidgets.QLabel("Max speakers"), 1, 0)
        group_layout.addWidget(self.max_speakers_spin, 1, 1)
        group_layout.addWidget(
            self.allow_buddy_to_buddy_check,
            1,
            2,
            1,
            2,
        )
        group_layout.addWidget(
            QtWidgets.QLabel("Natural second speaker every N turns"),
            2,
            0,
        )
        group_layout.addWidget(self.natural_second_speaker_spin, 2, 1)
        group_layout.addWidget(
            QtWidgets.QLabel("Force a buddy every N replies"),
            2,
            2,
        )
        group_layout.addWidget(self.forced_buddy_spin, 2, 3)
        for control_signal in (
            self.max_speakers_spin.valueChanged,
            self.allow_buddy_to_buddy_check.toggled,
            self.natural_second_speaker_spin.valueChanged,
            self.forced_buddy_spin.valueChanged,
        ):
            control_signal.connect(self._on_group_controls_changed)
        preview_layout.addWidget(group_box)

        prompt_box = QtWidgets.QGroupBox("Editable group prompt layers")
        prompt_layout = QtWidgets.QFormLayout(prompt_box)
        prompt_layout.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.AllNonFixedFieldsGrow
        )
        prompt_hint = QtWidgets.QLabel(
            "These changes remain in the preview until Apply Group. "
            "Buddy names, exact speaker labels, and the adult-only rule are "
            "generated separately."
        )
        prompt_hint.setWordWrap(True)
        prompt_layout.addRow("", prompt_hint)
        self.shared_prompt_edit = QtWidgets.QPlainTextEdit()
        self.shared_prompt_edit.setObjectName("buddy_setup_shared_prompt")
        self.shared_prompt_edit.setMinimumHeight(100)
        self.normal_prompt_edit = QtWidgets.QPlainTextEdit()
        self.normal_prompt_edit.setObjectName("buddy_setup_normal_prompt")
        self.normal_prompt_edit.setMinimumHeight(80)
        self.adult_prompt_edit = QtWidgets.QPlainTextEdit()
        self.adult_prompt_edit.setObjectName("buddy_setup_adult_prompt")
        self.adult_prompt_edit.setMinimumHeight(80)
        prompt_layout.addRow(
            "Shared Buddy Chat override",
            self.shared_prompt_edit,
        )
        prompt_layout.addRow(
            "Normal intimacy layer",
            self.normal_prompt_edit,
        )
        prompt_layout.addRow(
            "Adult / NSFW layer",
            self.adult_prompt_edit,
        )
        for editor in (
            self.shared_prompt_edit,
            self.normal_prompt_edit,
            self.adult_prompt_edit,
        ):
            editor.textChanged.connect(self._on_prompt_layers_changed)
        preview_layout.addWidget(prompt_box)

        self._preview_persona_actions = QtWidgets.QWidget()
        self._preview_persona_actions_layout = QtWidgets.QHBoxLayout(
            self._preview_persona_actions
        )
        self._preview_persona_actions_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(self._preview_persona_actions)

        refinement_box = QtWidgets.QGroupBox("Optional LLM refinement")
        refinement_layout = QtWidgets.QGridLayout(refinement_box)
        self.refine_scope_combo = QtWidgets.QComboBox()
        self.refine_scope_combo.setObjectName("buddy_refine_scope")
        self.refine_scope_combo.addItem("Entire group", "group")
        self.refine_scope_combo.addItem("One buddy", "persona")
        self.refine_scope_combo.addItem("One field", "field")
        self.refine_persona_combo = QtWidgets.QComboBox()
        self.refine_persona_combo.setObjectName("buddy_refine_persona")
        self.refine_field_combo = QtWidgets.QComboBox()
        self.refine_field_combo.setObjectName("buddy_refine_field")
        field_specs = (
            ("Name", "display_name"),
            ("Role", "role"),
            ("Detailed description", "description"),
            ("Complete system prompt", "system_prompt"),
            ("Speaking style", "speaking_style"),
            ("Helpfulness", "behavior.helpfulness"),
            ("Warmth", "behavior.warmth"),
            ("Humor", "behavior.humor"),
            ("Expressiveness", "behavior.expressiveness"),
            ("Initiative", "behavior.initiative"),
            ("Directness", "behavior.directness"),
            ("Willingness to disagree", "behavior.disagreement"),
            ("Flirtation", "behavior.flirtation"),
            ("Typical reply length", "behavior.reply_length"),
            (
                "Participation weight",
                "behavior.participation_weight",
            ),
        )
        for label, field_name in field_specs:
            self.refine_field_combo.addItem(label, field_name)
        self.refine_instruction_edit = QtWidgets.QLineEdit()
        self.refine_instruction_edit.setObjectName(
            "buddy_refine_instruction"
        )
        self.refine_instruction_edit.setPlaceholderText(
            "Describe the change you want the LLM to propose."
        )
        self.refine_instruction_edit.setText(
            "Make the selected characters more natural, distinctive, and "
            "internally consistent while preserving their intended roles."
        )
        refinement_layout.addWidget(QtWidgets.QLabel("Scope"), 0, 0)
        refinement_layout.addWidget(self.refine_scope_combo, 0, 1)
        refinement_layout.addWidget(QtWidgets.QLabel("Buddy"), 0, 2)
        refinement_layout.addWidget(self.refine_persona_combo, 0, 3)
        refinement_layout.addWidget(QtWidgets.QLabel("Field"), 0, 4)
        refinement_layout.addWidget(self.refine_field_combo, 0, 5)
        refinement_layout.addWidget(QtWidgets.QLabel("Instruction"), 1, 0)
        refinement_layout.addWidget(
            self.refine_instruction_edit,
            1,
            1,
            1,
            5,
        )
        refinement_layout.setColumnStretch(1, 1)
        refinement_layout.setColumnStretch(3, 1)
        refinement_layout.setColumnStretch(5, 1)
        self.refine_scope_combo.currentIndexChanged.connect(
            self._refresh_refinement_controls
        )
        preview_layout.addWidget(refinement_box)

        actions = QtWidgets.QHBoxLayout()
        self._refine_button = QtWidgets.QPushButton("Refine with LLM")
        self._refine_button.setObjectName("buddy_setup_refine")
        self._refine_cancel_button = QtWidgets.QPushButton(
            "Cancel Refinement"
        )
        self._refine_cancel_button.setObjectName(
            "buddy_setup_refine_cancel"
        )
        self._refine_cancel_button.setVisible(False)
        self._apply_button = QtWidgets.QPushButton("Apply Group")
        self._apply_button.setObjectName("buddy_setup_apply")
        self._cancel_button = QtWidgets.QPushButton("Cancel Preview")
        self._cancel_button.setObjectName("buddy_setup_cancel")
        self._undo_button = QtWidgets.QPushButton("Undo Last Setup")
        self._undo_button.setObjectName("buddy_setup_undo")
        self._undo_button.setEnabled(False)
        self._refine_button.clicked.connect(self._emit_refinement)
        self._refine_cancel_button.clicked.connect(
            self.refinement_cancel_requested.emit
        )
        self._apply_button.clicked.connect(self._emit_apply)
        self._cancel_button.clicked.connect(self.clear_preview)
        self._undo_button.clicked.connect(self.undo_requested.emit)
        actions.addWidget(self._refine_button)
        actions.addWidget(self._refine_cancel_button)
        actions.addStretch(1)
        actions.addWidget(self._undo_button)
        actions.addWidget(self._cancel_button)
        actions.addWidget(self._apply_button)
        preview_layout.addLayout(actions)
        root_layout.addWidget(preview_box)

    def _build_wizard_preview(self) -> None:
        traits = tuple(
            trait_id
            for trait_id, checkbox in self._trait_checks.items()
            if checkbox.isChecked()
        )
        choices = WizardChoices(
            buddy_count=int(self._buddy_count.currentData() or 1),
            participation=str(
                self._participation.currentData() or "balanced"
            ),
            traits=traits,
        )
        self.set_preview(compose_wizard_preview(choices))

    def set_preview(self, preview: BuddySetupPreview) -> None:
        self._preview = copy.deepcopy(preview)
        self._refresh_preview()
        self.preview_changed.emit(self.current_preview())

    def current_preview(self) -> BuddySetupPreview | None:
        return copy.deepcopy(self._preview)

    def refinement_request(self) -> RefinementRequest | None:
        preview = self.current_preview()
        if preview is None:
            return None
        preview.system_override_prompt = (
            self.shared_prompt_edit.toPlainText().strip()
        )
        preview.normal_intimacy_prompt = (
            self.normal_prompt_edit.toPlainText().strip()
        )
        preview.adult_nsfw_prompt = (
            self.adult_prompt_edit.toPlainText().strip()
        )
        scope = str(
            self.refine_scope_combo.currentData() or "group"
        )
        persona_id = (
            str(self.refine_persona_combo.currentData() or "")
            if scope in {"persona", "field"}
            else ""
        )
        field_name = (
            str(self.refine_field_combo.currentData() or "")
            if scope == "field"
            else ""
        )
        instruction = (
            self.refine_instruction_edit.text().strip()
            or "Improve the selected Buddy Chat fields naturally."
        )
        return RefinementRequest(
            scope=scope,
            instruction=instruction,
            preview=preview,
            persona_id=persona_id,
            field_name=field_name,
        )

    def clear_preview(self) -> None:
        self._preview = None
        self._refresh_preview()
        self.preview_changed.emit(None)

    def replace_preview_persona(
        self,
        index: int,
        persona: BuddyPersona,
    ) -> None:
        if self._preview is None:
            return
        target_index = int(index)
        if target_index < 0 or target_index >= len(self._preview.personas):
            return
        self._preview.personas[target_index] = BuddyPersona.from_dict(
            copy.deepcopy(persona.to_dict())
        )
        self._refresh_preview()
        self.preview_changed.emit(self.current_preview())

    def set_undo_available(self, available: bool) -> None:
        self._undo_button.setEnabled(bool(available))

    def set_refinement_busy(self, busy: bool) -> None:
        active = bool(busy)
        self._refine_button.setEnabled(
            not active and self._preview is not None
        )
        self._refine_cancel_button.setVisible(active)
        self.refine_scope_combo.setEnabled(not active)
        self.refine_persona_combo.setEnabled(not active)
        self.refine_field_combo.setEnabled(not active)
        self.refine_instruction_edit.setEnabled(not active)
        if not active:
            self._refresh_refinement_controls()

    def set_adult_mode(self, enabled: bool) -> None:
        blocker = QtCore.QSignalBlocker(self._adult_toggle)
        self._adult_toggle.setChecked(bool(enabled))
        del blocker

    def adult_mode_enabled(self) -> bool:
        return bool(self._adult_toggle.isChecked())

    def set_prompt_layers(
        self,
        *,
        shared_prompt: str,
        normal_prompt: str,
        adult_prompt: str,
    ) -> None:
        self._prompt_layer_baseline = {
            "system_override_prompt": (
                str(shared_prompt or "").strip()
                or DEFAULT_SYSTEM_OVERRIDE_PROMPT
            ),
            "normal_intimacy_prompt": (
                str(normal_prompt or "").strip()
                or DEFAULT_NORMAL_INTIMACY_PROMPT
            ),
            "adult_nsfw_prompt": (
                str(adult_prompt or "").strip()
                or DEFAULT_ADULT_NSFW_PROMPT
            ),
        }
        self._load_prompt_layer_controls()

    def _refresh_preview(self) -> None:
        preview = self._preview
        available = preview is not None
        self._apply_button.setEnabled(available)
        self._refine_button.setEnabled(available)
        while self._preview_persona_actions_layout.count():
            item = self._preview_persona_actions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if preview is None:
            self._preview_title.setText("No setup selected")
            self._preview_text.clear()
            return
        self._load_group_controls(preview.group_behavior)
        self._load_prompt_layer_controls()
        self._refresh_refinement_personas()
        self._refresh_refinement_controls()
        self._render_preview_text()
        for index, persona in enumerate(preview.personas):
            edit_button = QtWidgets.QPushButton(
                f"Edit {persona.display_name}"
            )
            edit_button.setObjectName(
                f"buddy_setup_edit_persona_{index}"
            )
            edit_button.clicked.connect(
                lambda _checked=False, row_index=index:
                self._edit_preview_persona(row_index)
            )
            self._preview_persona_actions_layout.addWidget(edit_button)
        self._preview_persona_actions_layout.addStretch(1)

    def _render_preview_text(self) -> None:
        preview = self._preview
        if preview is None:
            return
        self._preview_title.setText(
            f"{preview.title} - {len(preview.personas)} "
            f"{'buddy' if len(preview.personas) == 1 else 'buddies'}"
        )
        lines = [preview.summary, ""]
        for persona in preview.personas:
            lines.append(f"{persona.display_name} - {persona.role}")
            lines.append(f"  {persona.description}")
        lines.extend(
            [
                "",
                f"Max speakers: {preview.group_behavior.max_speakers}",
                "Buddy-to-buddy: "
                + (
                    "On"
                    if preview.group_behavior.allow_buddy_to_buddy
                    else "Off"
                ),
                "Natural second speaker: "
                + (
                    f"every {preview.group_behavior.natural_second_speaker_every} turns"
                    if preview.group_behavior.natural_second_speaker_every
                    else "Off"
                ),
            ]
        )
        self._preview_text.setPlainText("\n".join(lines))

    def _load_group_controls(self, behavior: GroupBehavior) -> None:
        self.max_speakers_spin.setMaximum(
            max(1, len(self._preview.personas) if self._preview else 1)
        )
        controls = (
            self.max_speakers_spin,
            self.allow_buddy_to_buddy_check,
            self.natural_second_speaker_spin,
            self.forced_buddy_spin,
        )
        blockers = [QtCore.QSignalBlocker(control) for control in controls]
        self.max_speakers_spin.setValue(int(behavior.max_speakers))
        self.allow_buddy_to_buddy_check.setChecked(
            bool(behavior.allow_buddy_to_buddy)
        )
        self.natural_second_speaker_spin.setValue(
            int(behavior.natural_second_speaker_every)
        )
        self.forced_buddy_spin.setValue(int(behavior.forced_buddy_every))
        del blockers
        matching_mode = None
        count = max(1, len(self._preview.personas) if self._preview else 1)
        for mode in self.group_mode_buttons:
            candidate = compose_wizard_preview(
                WizardChoices(count, mode, ())
            ).group_behavior
            if candidate == behavior:
                matching_mode = mode
                break
        self._set_group_mode_highlight(matching_mode)

    def _load_prompt_layer_controls(self) -> None:
        preview = self._preview
        values = {
            "system_override_prompt": (
                preview.system_override_prompt
                if preview is not None
                and preview.system_override_prompt is not None
                else self._prompt_layer_baseline["system_override_prompt"]
            ),
            "normal_intimacy_prompt": (
                preview.normal_intimacy_prompt
                if preview is not None
                and preview.normal_intimacy_prompt is not None
                else self._prompt_layer_baseline["normal_intimacy_prompt"]
            ),
            "adult_nsfw_prompt": (
                preview.adult_nsfw_prompt
                if preview is not None
                and preview.adult_nsfw_prompt is not None
                else self._prompt_layer_baseline["adult_nsfw_prompt"]
            ),
        }
        editors = (
            (self.shared_prompt_edit, values["system_override_prompt"]),
            (self.normal_prompt_edit, values["normal_intimacy_prompt"]),
            (self.adult_prompt_edit, values["adult_nsfw_prompt"]),
        )
        blockers = [QtCore.QSignalBlocker(editor) for editor, _ in editors]
        for editor, value in editors:
            editor.setPlainText(str(value or ""))
        del blockers

    def _on_prompt_layers_changed(self) -> None:
        if self._preview is None:
            return
        self._preview.system_override_prompt = (
            self.shared_prompt_edit.toPlainText().strip()
        )
        self._preview.normal_intimacy_prompt = (
            self.normal_prompt_edit.toPlainText().strip()
        )
        self._preview.adult_nsfw_prompt = (
            self.adult_prompt_edit.toPlainText().strip()
        )
        self.preview_changed.emit(self.current_preview())

    def _set_group_mode_highlight(self, selected: str | None) -> None:
        for mode, button in self.group_mode_buttons.items():
            blocker = QtCore.QSignalBlocker(button)
            button.setChecked(mode == selected)
            del blocker

    def _refresh_refinement_personas(self) -> None:
        current = str(self.refine_persona_combo.currentData() or "")
        blocker = QtCore.QSignalBlocker(self.refine_persona_combo)
        self.refine_persona_combo.clear()
        if self._preview is not None:
            for persona in self._preview.personas:
                self.refine_persona_combo.addItem(
                    persona.display_name,
                    persona.id,
                )
        index = self.refine_persona_combo.findData(current)
        if index >= 0:
            self.refine_persona_combo.setCurrentIndex(index)
        del blocker

    def _refresh_refinement_controls(self, *_args: object) -> None:
        if not self.refine_scope_combo.isEnabled():
            return
        scope = str(
            self.refine_scope_combo.currentData() or "group"
        )
        self.refine_persona_combo.setEnabled(
            scope in {"persona", "field"}
        )
        self.refine_field_combo.setEnabled(scope == "field")

    def _on_group_controls_changed(self, *_args: object) -> None:
        if self._preview is None:
            return
        self._preview.group_behavior = GroupBehavior(
            max_speakers=int(self.max_speakers_spin.value()),
            allow_buddy_to_buddy=bool(
                self.allow_buddy_to_buddy_check.isChecked()
            ),
            natural_second_speaker_every=int(
                self.natural_second_speaker_spin.value()
            ),
            forced_buddy_every=int(self.forced_buddy_spin.value()),
        )
        self._set_group_mode_highlight(None)
        self._render_preview_text()
        self.preview_changed.emit(self.current_preview())

    def _apply_group_mode(self, mode: str) -> None:
        if self._preview is None or mode not in self.group_mode_buttons:
            return
        count = max(1, len(self._preview.personas))
        behavior = compose_wizard_preview(
            WizardChoices(count, mode, ())
        ).group_behavior
        self._preview.group_behavior = behavior
        self._load_group_controls(behavior)
        self._set_group_mode_highlight(mode)
        self._render_preview_text()
        self.preview_changed.emit(self.current_preview())

    def _edit_preview_persona(self, index: int) -> None:
        preview = self._preview
        if preview is None:
            return
        target_index = int(index)
        if target_index < 0 or target_index >= len(preview.personas):
            return
        editor = BuddyCharacterEditor(
            preview.personas[target_index],
            self,
        )
        if editor.exec() == QtWidgets.QDialog.Accepted:
            self.replace_preview_persona(target_index, editor.persona())

    def _emit_apply(self) -> None:
        preview = self.current_preview()
        if preview is not None:
            self.apply_requested.emit(preview)

    def _emit_refinement(self) -> None:
        request = self.refinement_request()
        if request is not None:
            self.refinement_requested.emit(request)


__all__ = [
    "BuddyCharacterEditor",
    "BuddyRefinementReview",
    "SetupStudio",
]
