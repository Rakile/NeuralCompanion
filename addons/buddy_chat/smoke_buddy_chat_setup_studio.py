from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from addons.buddy_chat.models import (
    BEHAVIOR_REPLY_LENGTHS,
    BuddySettings,
    ProviderOverride,
)
from addons.buddy_chat.setup_models import (
    GroupBehavior,
    WizardChoices,
    apply_setup_preview,
)
from addons.buddy_chat.setup_templates import (
    compose_wizard_preview,
    preview_for_preset,
    preset_previews,
)
from addons.buddy_chat.refinement import (
    RefinementPatch,
    RefinementRequest,
    apply_refinement_patch,
    build_refinement_messages,
    parse_refinement_result,
)


def test_four_presets_have_approved_roster_sizes() -> None:
    previews = preset_previews()

    assert [item.setup_id for item in previews] == [
        "reliable_guide",
        "supportive_duo",
        "expressive_circle",
        "magnetic_company",
    ]
    assert [len(item.personas) for item in previews] == [1, 2, 3, 2]


def test_every_preset_persona_is_complete_and_inherits_provider() -> None:
    for preview in preset_previews():
        ids = {persona.id for persona in preview.personas}
        assert len(ids) == len(preview.personas)
        for persona in preview.personas:
            assert persona.description
            assert persona.system_prompt
            assert persona.speaking_style
            assert persona.behavior is not None
            assert persona.behavior.reply_length in BEHAVIOR_REPLY_LENGTHS
            assert persona.provider.provider_id == "inherit"
            assert persona.voice.enabled is False


def test_wizard_builds_requested_count_with_complementary_roles() -> None:
    preview = compose_wizard_preview(
        WizardChoices(
            buddy_count=3,
            participation="balanced",
            traits=("practical", "warm", "playful", "honest"),
        )
    )

    assert len(preview.personas) == 3
    assert len({persona.role for persona in preview.personas}) == 3
    assert preview.group_behavior.max_speakers == 2


def test_apply_replaces_roster_and_preserves_unrelated_global_settings() -> None:
    current = BuddySettings.default()
    current.enabled = True
    current.reply_mode = "main_answer"
    current.llm_mode = "buddy"
    current.buddy_provider = ProviderOverride(
        provider_id="openai",
        model="test-model",
        api_key="keep-secret",
    )
    current.system_override_prompt = "Keep my custom group rules."

    updated = apply_setup_preview(
        current,
        preview_for_preset("supportive_duo"),
    )

    assert [item.display_name for item in updated.personas] == ["Sage", "Mira"]
    assert updated.enabled is True
    assert updated.reply_mode == "main_answer"
    assert updated.buddy_provider.api_key == "keep-secret"
    assert updated.system_override_prompt == "Keep my custom group rules."


def test_apply_does_not_mutate_current_settings() -> None:
    current = BuddySettings.default()
    original_names = [item.display_name for item in current.personas]

    apply_setup_preview(current, preview_for_preset("reliable_guide"))

    assert [item.display_name for item in current.personas] == original_names


def test_controller_can_undo_last_applied_setup_in_the_same_session() -> None:
    from addons.buddy_chat.controller import BuddyChatController
    from addons.buddy_chat.smoke_buddy_chat import _FakeContext

    temp_root = Path(tempfile.mkdtemp(prefix="nc-buddy-setup-undo-"))
    controller = BuddyChatController(
        _FakeContext(temp_root, app_root=temp_root),
        completion_handler=lambda *_args: "ok",
    )
    original = [item.display_name for item in controller.settings.personas]

    controller._apply_setup_preview(preview_for_preset("expressive_circle"))
    assert [item.display_name for item in controller.settings.personas] == [
        "Nova",
        "Rowan",
        "Lila",
    ]

    controller._undo_last_setup()
    assert [item.display_name for item in controller.settings.personas] == original


def test_applied_setup_syncs_existing_controls_before_later_ui_commit() -> None:
    from PySide6 import QtWidgets

    from addons.buddy_chat.controller import BuddyChatController
    from addons.buddy_chat.smoke_buddy_chat import _FakeContext

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    temp_root = Path(tempfile.mkdtemp(prefix="nc-buddy-setup-sync-"))
    controller = BuddyChatController(
        _FakeContext(temp_root, app_root=temp_root),
        completion_handler=lambda *_args: "ok",
    )
    tab = controller.build_tab()
    preview = preview_for_preset("expressive_circle")
    preview.group_behavior = GroupBehavior(
        max_speakers=3,
        allow_buddy_to_buddy=False,
        natural_second_speaker_every=7,
        forced_buddy_every=5,
    )
    preview.system_override_prompt = "Applied shared override."
    try:
        controller._apply_setup_preview(preview)
        assert controller._controls["max_speakers"].value() == 3
        assert controller._controls["forced_buddy_every"].value() == 5
        assert (
            controller._controls[
                "system_override_prompt"
            ].toPlainText()
            == "Applied shared override."
        )

        controller._commit_ui_settings()

        assert controller.settings.max_speakers == 3
        assert controller.settings.forced_buddy_every == 5
        assert (
            controller.settings.system_override_prompt
            == "Applied shared override."
        )
        assert controller.settings.allow_buddy_to_buddy is False
        assert controller.settings.natural_second_speaker_every == 7
    finally:
        tab.deleteLater()
        app.processEvents()


def test_setup_studio_exposes_wizard_presets_and_preview() -> None:
    from PySide6 import QtWidgets

    from addons.buddy_chat.setup_studio import SetupStudio

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = SetupStudio()
    try:
        assert studio.objectName() == "buddy_setup_studio"
        assert (
            studio.findChild(QtWidgets.QWidget, "buddy_setup_wizard")
            is not None
        )
        preset_buttons = [
            button
            for button in studio.findChildren(QtWidgets.QPushButton)
            if button.objectName().startswith("buddy_preset_")
        ]
        assert len(preset_buttons) == 4
        assert (
            studio.findChild(
                QtWidgets.QCheckBox,
                "buddy_adult_nsfw_toggle",
            )
            is not None
        )
        assert (
            studio.findChild(QtWidgets.QPushButton, "buddy_setup_apply")
            is not None
        )
    finally:
        studio.deleteLater()
        app.processEvents()


def test_setup_studio_keeps_an_independent_preview_copy() -> None:
    from PySide6 import QtWidgets

    from addons.buddy_chat.setup_studio import SetupStudio

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = SetupStudio()
    preview = preview_for_preset("reliable_guide")
    try:
        studio.set_preview(preview)
        preview.personas[0].display_name = "Mutated Outside"

        current = studio.current_preview()
        assert current is not None
        assert current.personas[0].display_name == "Alex"
    finally:
        studio.deleteLater()
        app.processEvents()


def test_character_editor_roundtrips_every_refinable_field() -> None:
    from PySide6 import QtWidgets

    from addons.buddy_chat.setup_studio import BuddyCharacterEditor

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    persona = preview_for_preset("magnetic_company").personas[0]
    editor = BuddyCharacterEditor(persona)
    try:
        editor.name_edit.setText("Edited Elara")
        editor.role_edit.setText("edited role")
        editor.description_edit.setPlainText("Edited detailed description")
        editor.system_prompt_edit.setPlainText("Edited complete prompt")
        editor.style_edit.setText("edited expressive style")
        editor.behavior_sliders["helpfulness"].setValue(72)
        editor.behavior_sliders["warmth"].setValue(91)
        editor.behavior_sliders["humor"].setValue(63)
        editor.behavior_sliders["expressiveness"].setValue(88)
        editor.behavior_sliders["initiative"].setValue(77)
        editor.behavior_sliders["directness"].setValue(69)
        editor.behavior_sliders["disagreement"].setValue(54)
        editor.behavior_sliders["flirtation"].setValue(84)
        editor.behavior_sliders["participation_weight"].setValue(81)
        editor.reply_length_combo.setCurrentText("Detailed")

        updated = editor.persona()

        assert updated.id == persona.id
        assert updated.display_name == "Edited Elara"
        assert updated.role == "edited role"
        assert updated.description == "Edited detailed description"
        assert updated.system_prompt == "Edited complete prompt"
        assert updated.speaking_style == "edited expressive style"
        assert updated.behavior is not None
        assert updated.behavior.helpfulness == 72
        assert updated.behavior.warmth == 91
        assert updated.behavior.humor == 63
        assert updated.behavior.expressiveness == 88
        assert updated.behavior.initiative == 77
        assert updated.behavior.directness == 69
        assert updated.behavior.disagreement == 54
        assert updated.behavior.flirtation == 84
        assert updated.behavior.participation_weight == 81
        assert updated.behavior.reply_length == "detailed"
        assert updated.provider.to_dict() == persona.provider.to_dict()
        assert updated.voice.to_dict() == persona.voice.to_dict()
        assert updated.avatar.to_dict() == persona.avatar.to_dict()
    finally:
        editor.deleteLater()
        app.processEvents()


def test_character_editor_resets_one_field_or_the_complete_buddy() -> None:
    from PySide6 import QtWidgets

    from addons.buddy_chat.setup_studio import BuddyCharacterEditor

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    persona = preview_for_preset("supportive_duo").personas[0]
    assert persona.behavior is not None
    editor = BuddyCharacterEditor(persona)
    try:
        editor.name_edit.setText("Temporary Name")
        editor.behavior_sliders["warmth"].setValue(3)

        editor.reset_field("display_name")

        assert editor.name_edit.text() == persona.display_name
        assert editor.behavior_sliders["warmth"].value() == 3

        editor.reset_buddy()
        reset = editor.persona()
        assert reset.to_dict() == persona.to_dict()
    finally:
        editor.deleteLater()
        app.processEvents()


def test_setup_studio_character_edit_changes_only_the_preview_copy() -> None:
    from PySide6 import QtWidgets

    from addons.buddy_chat.setup_studio import SetupStudio

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = SetupStudio()
    source = preview_for_preset("supportive_duo")
    try:
        studio.set_preview(source)
        edited = source.personas[0]
        edited.display_name = "Edited Sage"

        studio.replace_preview_persona(0, edited)

        current = studio.current_preview()
        assert current is not None
        assert current.personas[0].display_name == "Edited Sage"
        assert current.personas[1].display_name == "Mira"
        assert source.personas[1].display_name == "Mira"
    finally:
        studio.deleteLater()
        app.processEvents()


def test_setup_studio_group_controls_preserve_character_edits() -> None:
    from PySide6 import QtWidgets

    from addons.buddy_chat.setup_studio import SetupStudio

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = SetupStudio()
    source = preview_for_preset("supportive_duo")
    try:
        studio.set_preview(source)
        edited = source.personas[0]
        edited.display_name = "Edited Sage"
        studio.replace_preview_persona(0, edited)

        studio.max_speakers_spin.setValue(2)
        studio.allow_buddy_to_buddy_check.setChecked(False)
        studio.natural_second_speaker_spin.setValue(7)
        studio.forced_buddy_spin.setValue(5)

        current = studio.current_preview()
        assert current is not None
        assert current.personas[0].display_name == "Edited Sage"
        assert current.personas[1].display_name == "Mira"
        assert current.group_behavior.max_speakers == 2
        assert current.group_behavior.allow_buddy_to_buddy is False
        assert current.group_behavior.natural_second_speaker_every == 7
        assert current.group_behavior.forced_buddy_every == 5
    finally:
        studio.deleteLater()
        app.processEvents()


def test_group_convenience_button_updates_exact_underlying_values() -> None:
    from PySide6 import QtWidgets

    from addons.buddy_chat.setup_studio import SetupStudio

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = SetupStudio()
    try:
        studio.set_preview(preview_for_preset("expressive_circle"))
        expected = compose_wizard_preview(
            WizardChoices(
                buddy_count=3,
                participation="focused",
                traits=(),
            )
        ).group_behavior

        studio.group_mode_buttons["focused"].click()

        current = studio.current_preview()
        assert current is not None
        assert current.group_behavior == expected
        assert studio.max_speakers_spin.value() == expected.max_speakers
        assert (
            studio.allow_buddy_to_buddy_check.isChecked()
            is expected.allow_buddy_to_buddy
        )
        assert (
            studio.natural_second_speaker_spin.value()
            == expected.natural_second_speaker_every
        )
        assert (
            studio.forced_buddy_spin.value()
            == expected.forced_buddy_every
        )
    finally:
        studio.deleteLater()
        app.processEvents()


def test_controller_applies_character_editor_result_to_saved_roster() -> None:
    from addons.buddy_chat.controller import BuddyChatController
    from addons.buddy_chat.smoke_buddy_chat import _FakeContext

    temp_root = Path(tempfile.mkdtemp(prefix="nc-buddy-character-edit-"))
    controller = BuddyChatController(
        _FakeContext(temp_root, app_root=temp_root),
        completion_handler=lambda *_args: "ok",
    )
    edited = preview_for_preset("reliable_guide").personas[0]
    edited.display_name = "Edited Alex"

    controller._apply_character_edit(0, edited)

    assert controller.settings.personas[0].display_name == "Edited Alex"
    assert controller.settings.personas[0].behavior is not None


def test_cancelled_first_adult_acknowledgement_leaves_mode_disabled() -> None:
    from PySide6 import QtWidgets

    from addons.buddy_chat.controller import BuddyChatController
    from addons.buddy_chat.setup_studio import SetupStudio
    from addons.buddy_chat.smoke_buddy_chat import _FakeContext

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    temp_root = Path(tempfile.mkdtemp(prefix="nc-buddy-adult-cancel-"))
    controller = BuddyChatController(
        _FakeContext(temp_root, app_root=temp_root),
        completion_handler=lambda *_args: "ok",
    )
    controller._setup_studio = SetupStudio()
    controller.settings.adult_nsfw_enabled = False
    controller.settings.adult_nsfw_acknowledged = False
    try:
        with patch.object(
            QtWidgets.QMessageBox,
            "question",
            return_value=QtWidgets.QMessageBox.Cancel,
        ):
            controller._on_adult_mode_requested(True)

        assert controller.settings.adult_nsfw_enabled is False
        assert controller.settings.adult_nsfw_acknowledged is False
        assert controller._setup_studio.adult_mode_enabled() is False
    finally:
        controller._setup_studio.deleteLater()
        app.processEvents()


def test_confirmed_adult_acknowledgement_is_persisted_once() -> None:
    from PySide6 import QtWidgets

    from addons.buddy_chat.controller import BuddyChatController
    from addons.buddy_chat.setup_studio import SetupStudio
    from addons.buddy_chat.smoke_buddy_chat import _FakeContext

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    temp_root = Path(tempfile.mkdtemp(prefix="nc-buddy-adult-confirm-"))
    controller = BuddyChatController(
        _FakeContext(temp_root, app_root=temp_root),
        completion_handler=lambda *_args: "ok",
    )
    controller._setup_studio = SetupStudio()
    try:
        with patch.object(
            QtWidgets.QMessageBox,
            "question",
            return_value=QtWidgets.QMessageBox.Yes,
        ) as question:
            controller._on_adult_mode_requested(True)
            controller._on_adult_mode_requested(False)
            controller._on_adult_mode_requested(True)

        assert question.call_count == 1
        assert controller.settings.adult_nsfw_enabled is True
        assert controller.settings.adult_nsfw_acknowledged is True
        assert controller._setup_studio.adult_mode_enabled() is True
    finally:
        controller._setup_studio.deleteLater()
        app.processEvents()


def test_prompt_layer_edits_are_staged_until_setup_apply() -> None:
    from PySide6 import QtWidgets

    from addons.buddy_chat.setup_studio import SetupStudio

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    settings = BuddySettings.default()
    original_shared = settings.system_override_prompt
    original_normal = settings.normal_intimacy_prompt
    original_adult = settings.adult_nsfw_prompt
    studio = SetupStudio()
    try:
        studio.set_prompt_layers(
            shared_prompt=original_shared,
            normal_prompt=original_normal,
            adult_prompt=original_adult,
        )
        studio.shared_prompt_edit.setPlainText("Edited shared group prompt.")
        studio.normal_prompt_edit.setPlainText("Edited normal intimacy layer.")
        studio.adult_prompt_edit.setPlainText("Edited adult prompt layer.")

        assert settings.system_override_prompt == original_shared
        assert settings.normal_intimacy_prompt == original_normal
        assert settings.adult_nsfw_prompt == original_adult

        preview = studio.current_preview()
        assert preview is not None
        updated = apply_setup_preview(settings, preview)
        assert updated.system_override_prompt == "Edited shared group prompt."
        assert (
            updated.normal_intimacy_prompt
            == "Edited normal intimacy layer."
        )
        assert updated.adult_nsfw_prompt == "Edited adult prompt layer."
    finally:
        studio.deleteLater()
        app.processEvents()


def test_refinement_payload_contains_no_secrets_or_media_paths() -> None:
    preview = preview_for_preset("supportive_duo")
    preview.personas[0].provider.api_key = "never-send"
    preview.personas[0].voice.sample_path = "Q:/private/voice.wav"
    preview.personas[0].avatar.image_path = "Q:/private/avatar.png"
    request = RefinementRequest(
        scope="group",
        instruction="Make them more candid.",
        preview=preview,
    )

    serialized = json.dumps(build_refinement_messages(request))

    assert "never-send" not in serialized
    assert "private/voice.wav" not in serialized
    assert "private/avatar.png" not in serialized
    assert "short, balanced, or detailed" in serialized


def test_invalid_refinement_does_not_create_patch() -> None:
    request = RefinementRequest(
        scope="persona",
        persona_id="sage",
        instruction="Make Sage warmer.",
        preview=preview_for_preset("supportive_duo"),
    )

    assert (
        parse_refinement_result(
            '{"personas":[{"id":"unknown","api_key":"x"}]}',
            request,
        )
        is None
    )
    assert (
        parse_refinement_result(
            '{"personas":[{"id":"sage","description":"First"},'
            '{"id":"sage","description":"Second"}]}',
            request,
        )
        is None
    )


def test_selected_field_application_changes_only_selected_field() -> None:
    preview = preview_for_preset("supportive_duo")
    request = RefinementRequest(
        scope="persona",
        persona_id="sage",
        instruction="Refine.",
        preview=preview,
    )
    patch_result = parse_refinement_result(
        '{"personas":[{"id":"sage","description":"New description",'
        '"system_prompt":"New prompt"}]}',
        request,
    )
    assert patch_result is not None

    updated = apply_refinement_patch(
        preview,
        patch_result,
        selected_fields={"sage.description"},
    )

    sage = next(item for item in updated.personas if item.id == "sage")
    assert sage.description == "New description"
    assert sage.system_prompt != "New prompt"


def test_unselected_behavior_patch_does_not_create_legacy_profile() -> None:
    preview = preview_for_preset("reliable_guide")
    preview.personas[0].behavior = None
    patch_result = RefinementPatch(
        personas={
            "alex": {
                "description": "Selected description.",
                "behavior": {"warmth": 95},
            }
        }
    )

    updated = apply_refinement_patch(
        preview,
        patch_result,
        selected_fields={"alex.description"},
    )

    assert updated.personas[0].description == "Selected description."
    assert updated.personas[0].behavior is None


def test_refinement_clamps_behavior_and_rejects_unknown_keys() -> None:
    preview = preview_for_preset("reliable_guide")
    request = RefinementRequest(
        scope="group",
        instruction="Refine.",
        preview=preview,
    )

    patch_result = parse_refinement_result(
        '{"personas":[{"id":"alex","behavior":'
        '{"warmth":180,"reply_length":"detailed"}}]}',
        request,
    )
    assert patch_result is not None
    updated = apply_refinement_patch(preview, patch_result)
    assert updated.personas[0].behavior is not None
    assert updated.personas[0].behavior.warmth == 100
    assert updated.personas[0].behavior.reply_length == "detailed"
    assert (
        parse_refinement_result(
            '{"personas":[{"id":"alex","provider":{"api_key":"x"}}]}',
            request,
        )
        is None
    )


def test_setup_studio_builds_scoped_refinement_request() -> None:
    from PySide6 import QtWidgets

    from addons.buddy_chat.setup_studio import SetupStudio

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = SetupStudio()
    try:
        studio.set_preview(preview_for_preset("supportive_duo"))
        studio.refine_scope_combo.setCurrentIndex(
            studio.refine_scope_combo.findData("field")
        )
        studio.refine_persona_combo.setCurrentIndex(
            studio.refine_persona_combo.findData("sage")
        )
        studio.refine_field_combo.setCurrentIndex(
            studio.refine_field_combo.findData("behavior.warmth")
        )
        studio.refine_instruction_edit.setText("Make Sage warmer.")

        request = studio.refinement_request()

        assert request is not None
        assert request.scope == "field"
        assert request.persona_id == "sage"
        assert request.field_name == "behavior.warmth"
        assert request.instruction == "Make Sage warmer."
        assert request.preview.personas[0].id == "sage"
    finally:
        studio.deleteLater()
        app.processEvents()


def test_refinement_review_lists_before_after_and_selected_fields() -> None:
    from PySide6 import QtWidgets

    from addons.buddy_chat.setup_studio import BuddyRefinementReview

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    before = preview_for_preset("supportive_duo")
    patch_result = RefinementPatch(
        personas={
            "sage": {
                "description": "A more candid Sage.",
                "behavior": {"warmth": 93},
            }
        }
    )
    after = apply_refinement_patch(before, patch_result)
    review = BuddyRefinementReview(before, after)
    try:
        assert set(review.field_checks) == {
            "sage.description",
            "sage.behavior.warmth",
        }
        review.field_checks["sage.behavior.warmth"].setChecked(False)
        assert review.selected_fields() == {"sage.description"}
    finally:
        review.deleteLater()
        app.processEvents()


def test_cancelled_refinement_ignores_late_worker_result() -> None:
    from PySide6 import QtWidgets

    from addons.buddy_chat.controller import BuddyChatController
    from addons.buddy_chat.setup_studio import SetupStudio
    from addons.buddy_chat.smoke_buddy_chat import _FakeContext

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    temp_root = Path(tempfile.mkdtemp(prefix="nc-buddy-refine-cancel-"))
    controller = BuddyChatController(
        _FakeContext(temp_root, app_root=temp_root),
        completion_handler=lambda *_args: "ok",
    )
    controller._setup_studio = SetupStudio()
    original = controller._setup_studio.current_preview()
    assert original is not None
    request = RefinementRequest(
        scope="persona",
        persona_id=original.personas[0].id,
        instruction="Change the description.",
        preview=original,
    )
    patch_result = RefinementPatch(
        personas={
            original.personas[0].id: {
                "description": "A late result that must be ignored."
            }
        }
    )
    try:
        controller._refinement_active_token = 9
        controller._cancel_setup_refinement()
        controller._on_refinement_finished(
            9,
            request,
            patch_result,
            "",
        )

        current = controller._setup_studio.current_preview()
        assert current is not None
        assert current.personas[0].description == (
            original.personas[0].description
        )
    finally:
        controller._setup_studio.deleteLater()
        app.processEvents()


def test_refinement_provider_work_does_not_block_the_ui_thread() -> None:
    from PySide6 import QtWidgets

    from addons.buddy_chat.controller import BuddyChatController
    from addons.buddy_chat.setup_studio import SetupStudio
    from addons.buddy_chat.smoke_buddy_chat import _FakeContext

    started = threading.Event()
    model_lookup_started = threading.Event()
    release = threading.Event()

    def slow_model_lookup() -> str:
        model_lookup_started.set()
        release.wait(timeout=2.0)
        return "test-model"

    def slow_completion(*_args: object, **_kwargs: object) -> str:
        started.set()
        release.wait(timeout=2.0)
        return '{"personas":[{"id":"alex","description":"Refined"}]}'

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    temp_root = Path(tempfile.mkdtemp(prefix="nc-buddy-refine-thread-"))
    controller = BuddyChatController(
        _FakeContext(temp_root, app_root=temp_root),
        completion_handler=slow_completion,
    )
    controller._setup_studio = SetupStudio()
    preview = controller._setup_studio.current_preview()
    assert preview is not None
    request = RefinementRequest(
        scope="persona",
        persona_id="alex",
        instruction="Refine Alex.",
        preview=preview,
    )
    controller._current_model_name = slow_model_lookup
    try:
        begin = time.perf_counter()
        controller._start_setup_refinement(request)
        elapsed = time.perf_counter() - begin

        assert elapsed < 0.25
        assert model_lookup_started.wait(timeout=1.0)
        controller._cancel_setup_refinement()
        release.set()
        assert started.wait(timeout=1.0)
    finally:
        release.set()
        controller._setup_studio.deleteLater()
        app.processEvents()


def run_all() -> None:
    test_four_presets_have_approved_roster_sizes()
    test_every_preset_persona_is_complete_and_inherits_provider()
    test_wizard_builds_requested_count_with_complementary_roles()
    test_apply_replaces_roster_and_preserves_unrelated_global_settings()
    test_apply_does_not_mutate_current_settings()
    test_controller_can_undo_last_applied_setup_in_the_same_session()
    test_applied_setup_syncs_existing_controls_before_later_ui_commit()
    test_setup_studio_exposes_wizard_presets_and_preview()
    test_setup_studio_keeps_an_independent_preview_copy()
    test_character_editor_roundtrips_every_refinable_field()
    test_character_editor_resets_one_field_or_the_complete_buddy()
    test_setup_studio_character_edit_changes_only_the_preview_copy()
    test_setup_studio_group_controls_preserve_character_edits()
    test_group_convenience_button_updates_exact_underlying_values()
    test_controller_applies_character_editor_result_to_saved_roster()
    test_cancelled_first_adult_acknowledgement_leaves_mode_disabled()
    test_confirmed_adult_acknowledgement_is_persisted_once()
    test_prompt_layer_edits_are_staged_until_setup_apply()
    test_refinement_payload_contains_no_secrets_or_media_paths()
    test_invalid_refinement_does_not_create_patch()
    test_selected_field_application_changes_only_selected_field()
    test_unselected_behavior_patch_does_not_create_legacy_profile()
    test_refinement_clamps_behavior_and_rejects_unknown_keys()
    test_setup_studio_builds_scoped_refinement_request()
    test_refinement_review_lists_before_after_and_selected_fields()
    test_cancelled_refinement_ignores_late_worker_result()
    test_refinement_provider_work_does_not_block_the_ui_thread()


if __name__ == "__main__":
    run_all()
    print("smoke_buddy_chat_setup_studio: ok")
