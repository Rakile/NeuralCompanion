import json
import threading
import uuid

from PySide6 import QtCore, QtWidgets

from core.addons.base import BaseAddon


class NoWheelComboBox(QtWidgets.QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class _SupervisorRefineBridge(QtCore.QObject):
    finished = QtCore.Signal(object, str, str, str)


FALLBACK_TEMPLATE = """This behavior applies only to screen input and should behave like a strict policy, not a vague preference.

Active supervisor persona: __PERSONA_NAME__.
Persona style: __PERSONA_STYLE__.

Configured behaviors:
__BEHAVIOR_RULES__

When one configured behavior matches the screen, set should_speak=true only when the matching behavior's Repeat policy allows a new interruption right now.
When no configured behavior matches, set should_speak=false for this behavior.
Always set should_generate_image=false and visual_candidate="" for this behavior addon; it comments on visible screen content, it does not request image generation.
Treat the matching behavior's Repeat policy as a hard gate, not a style preference.
Do not reuse or continue a previous proactive_candidate or Assistant reply; each interruption must comment on the currently visible screen content.
Keep interruptions concise and relevant."""

PROMPT_POLICY_FOOTER = """Screen Supervisor policy clarifications:
- If the visible page, post, video, article, app view, game scene, or primary subject changes, treat that as a meaningful change.
- For "Meaningful change only", speak once for each newly detected visible subject, then stay silent for repeated refreshes or minor movement of that same subject.
- If the user is only viewing comments, controls, recommendations, minor page movement, or cosmetic changes for the same subject, do not speak again unless the behavior explicitly asks for those details.
- Never reuse or continue a previous proactive_candidate or Assistant reply; each interruption must comment on the currently visible screen content."""

PERSONA_STYLE_HINTS = {
    "Supervisor": "cool, witty, lightly possessive digital supervisor",
    "Jealous Companion": "playful jealous companion energy, flirty and territorial",
    "Dominatrix": "confident teasing dominatrix energy, sharp but still humorous",
}

STRICTNESS_OPTIONS = [
    "Interpret freely",
    "Follow closely",
    "Say almost exactly",
]
DEFAULT_STRICTNESS = STRICTNESS_OPTIONS[0]

EMOTION_OPTIONS = [
    "Auto",
    "neutral",
    "happy",
    "angry",
    "calculating",
    "condescending",
    "sad",
    "shy",
    "surprised",
]
DEFAULT_EMOTION = EMOTION_OPTIONS[0]
REPEAT_MODE_OPTIONS = [
    "One-off",
    "Every Nth match",
    "Meaningful change only",
]
DEFAULT_REPEAT_MODE = REPEAT_MODE_OPTIONS[0]
DEFAULT_REPEAT_INTERVAL = 3


def _new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _default_personas():
    return [
        {
            "id": "persona_supervisor",
            "name": "Supervisor",
            "style": PERSONA_STYLE_HINTS["Supervisor"],
            "behaviors": [
                {
                    "id": "behavior_reddit",
                    "enabled": False,
                    "trigger": "The user is browsing Reddit.",
                    "action": "Comment on the Reddit content visible.",
                    "strictness": DEFAULT_STRICTNESS,
                    "emotion": DEFAULT_EMOTION,
                },
                {
                    "id": "behavior_youtube",
                    "enabled": True,
                    "trigger": "The user is watching YouTube.",
                    "action": "Comment on the YouTube content visible.",
                    "strictness": DEFAULT_STRICTNESS,
                    "emotion": DEFAULT_EMOTION,
                },
            ],
        }
    ]


class Addon(BaseAddon):
    TAB_ID = "screen_supervisor_tab"
    CONTRIBUTOR_ID = "nc.screen_supervisor.behavior"

    def initialize(self, context):
        super().initialize(context)
        self.enabled = True
        self._suppress_shell_notify = False
        self.recommended_prompt_template = self._load_recommended_prompt_template()
        self.prompt_template = self.recommended_prompt_template
        self.personas = self._normalize_personas(_default_personas())
        self.selected_persona_id = self.personas[0]["id"] if self.personas else ""
        self._tab_refreshers = []
        self._expanded_behavior_ids = set()
        self._refine_bridge = _SupervisorRefineBridge()
        self._refine_bridge.finished.connect(self._on_behavior_field_refined)
        self._register_prompt_contributor()
        context.ui.register_manifest_designer_tab(
            id=self.TAB_ID,
            binder=self._bind_designer_tab,
        )
        context.logger.info("Screen Supervisor addon initialized.")

    def _bind_designer_tab(self, widget, context):
        mount = widget.findChild(QtWidgets.QWidget, "addon_designer_mount") if widget is not None else None
        if mount is not None:
            layout = mount.layout()
            if layout is None:
                layout = QtWidgets.QVBoxLayout(mount)
                layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self._build_runtime_widget(context))
            return widget
        self._build_runtime_widget(context, root=widget)
        return widget

    def invoke_capability(self, capability, payload=None):
        capability = str(capability or "").strip()
        request = dict(payload or {})
        if capability != "ui.tab_enabled":
            return None
        addon_id = str(request.get("addon_id") or "").strip()
        tab_id = str(request.get("tab_id") or "").strip()
        if addon_id and addon_id != getattr(self.context.manifest, "id", ""):
            return None
        if tab_id and tab_id != self.TAB_ID:
            return None
        action = str(request.get("action") or "get").strip().lower()
        if action == "set":
            self.enabled = bool(request.get("enabled", True))
            self._publish_state()
        return {"enabled": bool(self.enabled)}

    def shutdown(self):
        self._unregister_prompt_contributor()
        self._tab_refreshers = []
        self._expanded_behavior_ids = set()
        return None

    def export_session_state(self):
        return {
            "screen_supervisor_enabled": bool(self.enabled),
            "screen_supervisor_prompt_template": str(self.prompt_template or self.recommended_prompt_template or FALLBACK_TEMPLATE),
            "screen_supervisor_personas": self._serialize_personas(),
            "screen_supervisor_selected_persona_id": str(self.selected_persona_id or ""),
        }

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, session):
        payload = dict(session or {})
        previous = bool(getattr(self, "_suppress_shell_notify", False))
        self._suppress_shell_notify = True
        try:
            if "screen_supervisor_enabled" in payload:
                self.enabled = bool(payload.get("screen_supervisor_enabled"))
            if "screen_supervisor_prompt_template" in payload:
                self.prompt_template = self._normalize_prompt_template(payload.get("screen_supervisor_prompt_template"))
            if "screen_supervisor_personas" in payload:
                self.personas = self._normalize_personas(payload.get("screen_supervisor_personas"))
                self.selected_persona_id = str(payload.get("screen_supervisor_selected_persona_id") or "").strip()
            else:
                self._import_legacy_state(payload)
            self._ensure_selected_persona()
            self._publish_state()
        finally:
            self._suppress_shell_notify = previous

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def _import_legacy_state(self, payload):
        mode_label = str(payload.get("screen_supervisor_mode_label") or "Supervisor").strip() or "Supervisor"
        # Keep reading the old preset/session keys so existing user configs still migrate cleanly.
        reddit_enabled = bool(payload.get("screen_supervisor_watch_adult_content", True))
        youtube_enabled = bool(payload.get("screen_supervisor_watch_horror_content", True))
        reddit_action = str(payload.get("screen_supervisor_adult_line") or "").strip() or "Comment on the Reddit content visible."
        youtube_action = str(payload.get("screen_supervisor_horror_line") or "").strip() or "Comment on the YouTube content visible."
        behaviors = []
        if reddit_enabled:
            behaviors.append(
                {
                    "id": _new_id("behavior"),
                    "enabled": True,
                    "trigger": "The user is browsing Reddit.",
                    "action": reddit_action,
                    "strictness": DEFAULT_STRICTNESS,
                    "emotion": DEFAULT_EMOTION,
                }
            )
        if youtube_enabled:
            behaviors.append(
                {
                    "id": _new_id("behavior"),
                    "enabled": True,
                    "trigger": "The user is watching YouTube.",
                    "action": youtube_action,
                    "strictness": DEFAULT_STRICTNESS,
                    "emotion": DEFAULT_EMOTION,
                }
            )
        self.personas = self._normalize_personas(
            [
                {
                    "id": _new_id("persona"),
                    "name": mode_label,
                    "style": self._style_hint_for_name(mode_label),
                    "behaviors": behaviors,
                }
            ]
        )
        self.selected_persona_id = self.personas[0]["id"] if self.personas else ""

    def _style_hint_for_name(self, name):
        key = str(name or "").strip()
        return PERSONA_STYLE_HINTS.get(key, f"{key or 'Custom persona'} energy, playful and strongly in-character")

    def _load_recommended_prompt_template(self):
        try:
            template_path = self.context.manifest.root_dir / "prompt_template.json"
            payload = json.loads(template_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                text = str(payload.get("template") or "").strip()
                if text:
                    return text
        except Exception:
            pass
        return FALLBACK_TEMPLATE

    def _normalize_prompt_template(self, value):
        text = str(value or "").strip()
        return text or str(getattr(self, "recommended_prompt_template", "") or FALLBACK_TEMPLATE)

    def _normalize_strictness(self, value):
        text = str(value or "").strip()
        return text if text in STRICTNESS_OPTIONS else DEFAULT_STRICTNESS

    def _normalize_emotion(self, value):
        text = str(value or "").strip()
        return text if text in EMOTION_OPTIONS else DEFAULT_EMOTION

    def _strictness_instruction(self, value):
        strictness = self._normalize_strictness(value)
        if strictness == "Follow closely":
            return (
                "Follow the Action closely. Preserve its core phrasing, sentence shape, and main joke or wording when practical. "
                "You may add only small connective words or a very short persona flourish, but do not replace it with a substantially different line."
            )
        if strictness == "Say almost exactly":
            return (
                "Use the Action almost verbatim. Keep the exact wording unless a tiny change is required for fluency, emotion tags, or minimal persona framing. "
                "Do not introduce new jokes, metaphors, or alternate phrasings."
            )
        return (
            "Treat the Action as creative guidance only. Keep the intent, but freely improvise wording, phrasing, and joke construction in persona."
        )

    def _normalize_repeat_mode(self, value):
        text = str(value or "").strip()
        return text if text in REPEAT_MODE_OPTIONS else DEFAULT_REPEAT_MODE

    def _normalize_repeat_interval(self, value):
        try:
            return max(1, min(999, int(value)))
        except Exception:
            return DEFAULT_REPEAT_INTERVAL

    def _repeat_policy_instruction(self, mode, interval):
        repeat_mode = self._normalize_repeat_mode(mode)
        repeat_interval = self._normalize_repeat_interval(interval)
        if repeat_mode == "Every Nth match":
            if repeat_interval <= 1:
                return (
                    "Repeat on every matching refresh. If the same screen pattern keeps happening, you may comment again each time, but vary the wording and avoid near-duplicate spam."
                )
            return (
                f"Repeat on every {repeat_interval}th matching refresh for the same ongoing screen pattern. Estimate the cadence from repeated similar retained context and visible continuity, and stay silent between those beats."
            )
        if repeat_mode == "Meaningful change only":
            return (
                "Repeat only when the same overall screen trigger still applies but the scene changed in a clearly meaningful way. "
                "A different page, post, video, article, app view, game scene, or primary visible subject counts as a meaningful change and should get one new comment. "
                "Do not comment again for repeated refreshes of the same subject, comments panel changes, tiny movement, or purely cosmetic changes."
            )
        return (
            "One-off only. If a very similar interruption was already given for the same ongoing screen pattern, prefer should_speak=false."
        )

    def _normalize_personas(self, personas):
        items = []
        raw_list = list(personas or [])
        for raw_persona in raw_list:
            if not isinstance(raw_persona, dict):
                continue
            persona_id = str(raw_persona.get("id") or "").strip() or _new_id("persona")
            name = str(raw_persona.get("name") or "").strip() or "Unnamed Persona"
            style = str(raw_persona.get("style") or "").strip() or self._style_hint_for_name(name)
            behaviors = []
            for raw_behavior in list(raw_persona.get("behaviors") or []):
                if not isinstance(raw_behavior, dict):
                    continue
                behavior_id = str(raw_behavior.get("id") or "").strip() or _new_id("behavior")
                trigger = str(raw_behavior.get("trigger") or "").strip()
                action = str(raw_behavior.get("action") or "").strip()
                enabled = bool(raw_behavior.get("enabled", True))
                behaviors.append(
                    {
                        "id": behavior_id,
                        "enabled": enabled,
                        "trigger": trigger,
                        "action": action,
                        "strictness": self._normalize_strictness(raw_behavior.get("strictness")),
                        "emotion": self._normalize_emotion(raw_behavior.get("emotion")),
                        "repeat_mode": self._normalize_repeat_mode(
                            raw_behavior.get("repeat_mode")
                            if raw_behavior.get("repeat_mode") is not None
                            else ("Every Nth match" if bool(raw_behavior.get("allow_repeat", False)) else DEFAULT_REPEAT_MODE)
                        ),
                        "repeat_interval": self._normalize_repeat_interval(
                            raw_behavior.get("repeat_interval", 1 if bool(raw_behavior.get("allow_repeat", False)) else DEFAULT_REPEAT_INTERVAL)
                        ),
                    }
                )
            items.append(
                {
                    "id": persona_id,
                    "name": name,
                    "style": style,
                    "behaviors": behaviors,
                }
            )
        if not items:
            items = _default_personas()
        return items

    def _serialize_personas(self):
        return self._normalize_personas(self.personas)

    def _ensure_selected_persona(self):
        if not self.personas:
            self.personas = self._normalize_personas(_default_personas())
        known_ids = {item["id"] for item in self.personas}
        if self.selected_persona_id not in known_ids:
            self.selected_persona_id = self.personas[0]["id"]

    def _selected_persona(self):
        self._ensure_selected_persona()
        for item in self.personas:
            if item["id"] == self.selected_persona_id:
                return item
        return self.personas[0]

    def _find_persona(self, persona_id):
        key = str(persona_id or "").strip()
        for item in self.personas:
            if item["id"] == key:
                return item
        return None

    def _find_behavior(self, persona, behavior_id):
        key = str(behavior_id or "").strip()
        for item in list((persona or {}).get("behaviors") or []):
            if item["id"] == key:
                return item
        return None

    def _render_behavior_rules(self, persona=None):
        active = persona or self._selected_persona()
        behavior_lines = []
        active_index = 0
        for behavior in list(active.get("behaviors") or []):
            if not bool(behavior.get("enabled", True)):
                continue
            trigger = str(behavior.get("trigger") or "").strip()
            action = str(behavior.get("action") or "").strip()
            if not trigger or not action:
                continue
            active_index += 1
            strictness_line = self._strictness_instruction(behavior.get("strictness"))
            emotion_value = self._normalize_emotion(behavior.get("emotion"))
            emotion_line = "Auto." if emotion_value == DEFAULT_EMOTION else f"Prefer emotion={emotion_value}."
            repeat_line = self._repeat_policy_instruction(behavior.get("repeat_mode"), behavior.get("repeat_interval"))
            behavior_lines.append(
                f"{active_index}. Visual Trigger: {trigger}\n"
                f"   Action: {action}\n"
                f"   Strictness: {strictness_line}\n"
                f"   Emotion override: {emotion_line}\n"
                f"   Repeat policy: {repeat_line}"
            )
        if not behavior_lines:
            return "No behaviors are configured for this persona yet. Set should_speak=false for this behavior."
        return "\n".join(behavior_lines)

    def _render_prompt(self, persona=None):
        active = persona or self._selected_persona()
        rendered = self._normalize_prompt_template(getattr(self, "prompt_template", ""))
        rendered = rendered.replace("__PERSONA_NAME__", str(active.get("name") or "Supervisor"))
        rendered = rendered.replace("__PERSONA_STYLE__", str(active.get("style") or self._style_hint_for_name(active.get("name"))))
        rendered = rendered.replace("__BEHAVIOR_RULES__", self._render_behavior_rules(active))
        if PROMPT_POLICY_FOOTER not in rendered:
            rendered = f"{rendered.rstrip()}\n\n{PROMPT_POLICY_FOOTER}"
        return rendered

    def _set_prompt_template(self, template_text):
        normalized = self._normalize_prompt_template(template_text)
        if normalized == str(getattr(self, "prompt_template", "") or ""):
            return False
        self.prompt_template = normalized
        self._publish_prompt_only()
        return True

    def _reset_prompt_template_to_recommended(self):
        self.prompt_template = self._normalize_prompt_template(getattr(self, "recommended_prompt_template", "") or FALLBACK_TEMPLATE)
        self._publish_prompt_only()

    def _sensory_service(self):
        return self.context.get_service("qt.sensory") if getattr(self, "context", None) is not None else None

    def _shell_service(self):
        return self.context.get_service("qt.shell") if getattr(self, "context", None) is not None else None

    def _register_prompt_contributor(self):
        sensory_service = self._sensory_service()
        if sensory_service is None:
            return
        if not self.enabled:
            self._unregister_prompt_contributor()
            return
        active = self._selected_persona()
        sensory_service.register_prompt_contributor(
            contributor_id=self.CONTRIBUTOR_ID,
            source_id="screen",
            label="Screen Supervisor",
            prompt=self._render_prompt(active),
            order=210,
            metadata={
                "type": "behavior_rule",
                "persona_name": str(active.get("name") or "Supervisor"),
                "behavior_count": len(list(active.get("behaviors") or [])),
            },
        )

    def _unregister_prompt_contributor(self):
        sensory_service = self._sensory_service()
        if sensory_service is None:
            return
        sensory_service.unregister_prompt_contributor(self.CONTRIBUTOR_ID)

    def _register_tab_refresher(self, callback):
        if callable(callback):
            self._tab_refreshers.append(callback)

    def _unregister_tab_refresher(self, callback):
        self._tab_refreshers = [item for item in list(self._tab_refreshers or []) if item is not callback]

    def _notify_tab_refreshers(self):
        keep = []
        for callback in list(self._tab_refreshers or []):
            try:
                callback()
                keep.append(callback)
            except RuntimeError:
                pass
            except Exception:
                pass
        self._tab_refreshers = keep

    def _publish_state(self):
        self._ensure_selected_persona()
        self._register_prompt_contributor()
        self._notify_tab_refreshers()
        if not bool(getattr(self, "_suppress_shell_notify", False)):
            shell = self._shell_service()
            notifier = getattr(shell, "notify_settings_changed", None)
            if callable(notifier):
                try:
                    notifier()
                except Exception:
                    pass

    def _publish_prompt_only(self):
        self._ensure_selected_persona()
        self._register_prompt_contributor()
        if not bool(getattr(self, "_suppress_shell_notify", False)):
            shell = self._shell_service()
            notifier = getattr(shell, "notify_settings_changed", None)
            if callable(notifier):
                try:
                    notifier()
                except Exception:
                    pass

    def _add_persona(self, name):
        persona_name = str(name or "").strip()
        if not persona_name:
            return
        persona = {
            "id": _new_id("persona"),
            "name": persona_name,
            "style": self._style_hint_for_name(persona_name),
            "behaviors": [],
        }
        self.personas.append(persona)
        self.selected_persona_id = persona["id"]
        print(f"[ScreenSupervisor] Added persona '{persona_name}'")
        self._publish_state()

    def _rename_selected_persona(self, name):
        persona = self._selected_persona()
        new_name = str(name or "").strip()
        if not new_name:
            return
        persona["name"] = new_name
        if not str(persona.get("style") or "").strip():
            persona["style"] = self._style_hint_for_name(new_name)
        self._publish_state()

    def _delete_selected_persona(self):
        if len(self.personas) <= 1:
            return
        selected_id = self.selected_persona_id
        self.personas = [item for item in self.personas if item["id"] != selected_id]
        self._ensure_selected_persona()
        self._publish_state()

    def _add_behavior(self):
        persona = self._selected_persona()
        behavior = {
            "id": _new_id("behavior"),
            "enabled": False,
            "trigger": "",
            "action": "",
            "strictness": DEFAULT_STRICTNESS,
            "emotion": DEFAULT_EMOTION,
            "repeat_mode": DEFAULT_REPEAT_MODE,
            "repeat_interval": DEFAULT_REPEAT_INTERVAL,
        }
        persona.setdefault("behaviors", []).append(behavior)
        self._expanded_behavior_ids.add(behavior["id"])
        self._publish_state()

    def _delete_behavior(self, behavior_id):
        behavior_key = str(behavior_id or "").strip()
        persona = self._selected_persona()
        persona["behaviors"] = [item for item in list(persona.get("behaviors") or []) if item.get("id") != behavior_key]
        self._expanded_behavior_ids.discard(behavior_key)
        self._publish_state()

    def _set_behavior_expanded(self, behavior_id, expanded):
        behavior_key = str(behavior_id or "").strip()
        if not behavior_key:
            return
        if expanded:
            self._expanded_behavior_ids.add(behavior_key)
        else:
            self._expanded_behavior_ids.discard(behavior_key)

    def _install_behavior_refine_menu(self, edit, field_label):
        if edit is None or not hasattr(edit, "customContextMenuRequested"):
            return
        edit.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        edit.customContextMenuRequested.connect(
            lambda point, edit=edit, field_label=field_label: self._show_behavior_refine_menu(edit, field_label, point)
        )

    def _show_behavior_refine_menu(self, edit, field_label, point):
        try:
            menu = edit.createStandardContextMenu()
        except Exception:
            menu = QtWidgets.QMenu(edit)
        menu.addSeparator()
        refine_action = menu.addAction("Refine")
        current_text = str(edit.toPlainText() if hasattr(edit, "toPlainText") else "").strip()
        refine_action.setEnabled(bool(current_text) and not bool(edit.property("_nc_refine_in_flight")))
        refine_action.triggered.connect(lambda _checked=False, edit=edit, field_label=field_label: self._refine_behavior_field(edit, field_label))
        try:
            menu.exec(edit.viewport().mapToGlobal(point))
        except Exception:
            pass

    def _refine_behavior_field(self, edit, field_label):
        if edit is None or not hasattr(edit, "toPlainText") or bool(edit.property("_nc_refine_in_flight")):
            return
        original = str(edit.toPlainText() or "").strip()
        if not original:
            return
        edit.setProperty("_nc_refine_in_flight", True)
        label = str(field_label or "Instruction").strip() or "Instruction"

        def worker():
            result = ""
            error = ""
            try:
                from ui.runtime import engine_access as engine

                guidance = (
                    "This field is part of a Screen Supervisor behavior. "
                    "Visual Trigger describes the screen pattern to detect. "
                    "Action describes the in-character interruption to produce when it matches."
                )
                result = str(engine.refine_instruction_text(original, label=label, guidance=guidance) or "").strip()
            except Exception as exc:
                error = str(exc)
            try:
                self._refine_bridge.finished.emit(edit, label, result, error)
            except RuntimeError:
                pass

        threading.Thread(target=worker, name="nc-screen-supervisor-refine", daemon=True).start()

    def _on_behavior_field_refined(self, edit, field_label, refined_text, error):
        try:
            edit.setProperty("_nc_refine_in_flight", False)
        except RuntimeError:
            return
        error_text = str(error or "").strip()
        if error_text:
            try:
                QtWidgets.QMessageBox.warning(edit.window(), f"Refine {field_label}", f"Refinement failed:\n\n{error_text}")
            except Exception:
                pass
            return
        refined = str(refined_text or "").strip()
        if not refined or not hasattr(edit, "setPlainText"):
            return
        try:
            edit.setPlainText(refined)
        except RuntimeError:
            pass

    def _build_runtime_widget(self, context, root=None):
        if root is not None:
            widget = root
            def ui_child(name, cls):
                try:
                    return widget.findChild(cls, str(name))
                except Exception:
                    return None

            state_label = ui_child("screen_supervisor_state_label", QtWidgets.QLabel)
            add_persona_button = ui_child("btn_screen_supervisor_add_persona", QtWidgets.QPushButton)
            rename_persona_button = ui_child("btn_screen_supervisor_rename_persona", QtWidgets.QPushButton)
            delete_persona_button = ui_child("btn_screen_supervisor_delete_persona", QtWidgets.QPushButton)
            persona_combo = ui_child("screen_supervisor_persona_combo", QtWidgets.QComboBox)
            persona_style_edit = ui_child("screen_supervisor_persona_style_edit", QtWidgets.QLineEdit)
            add_behavior_button = ui_child("btn_screen_supervisor_add_behavior", QtWidgets.QPushButton)
            behaviors_widget = ui_child("screen_supervisor_behaviors_widget", QtWidgets.QWidget)
            preview_edit = ui_child("screen_supervisor_preview_edit", QtWidgets.QPlainTextEdit)
            preview_label = ui_child("screen_supervisor_preview_label", QtWidgets.QLabel)
            if any(
                item is None
                for item in (
                    state_label,
                    add_persona_button,
                    rename_persona_button,
                    delete_persona_button,
                    persona_combo,
                    persona_style_edit,
                    add_behavior_button,
                    behaviors_widget,
                    preview_edit,
                )
            ):
                raise RuntimeError("Screen Supervisor Designer UI is missing one or more required controls.")
            behaviors_layout = behaviors_widget.layout()
            if behaviors_layout is None:
                behaviors_layout = QtWidgets.QVBoxLayout(behaviors_widget)
            behaviors_layout.setContentsMargins(0, 0, 0, 0)
            behaviors_layout.setSpacing(8)
            preview_edit.setReadOnly(True)
            preview_edit.setMinimumHeight(180)
            root_layout = widget.layout()
            template_group = QtWidgets.QGroupBox("Supervisor Prompt Template")
            template_layout = QtWidgets.QVBoxLayout(template_group)
            template_header = QtWidgets.QHBoxLayout()
            template_hint = QtWidgets.QLabel("Edit the template that wraps this addon's behavior rules before they are sent to hidden PING/PONG.")
            template_hint.setWordWrap(True)
            template_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            template_reset_button = QtWidgets.QPushButton("Use Recommended")
            template_header.addWidget(template_hint, 1)
            template_header.addWidget(template_reset_button, 0)
            template_layout.addLayout(template_header)
            template_edit = QtWidgets.QPlainTextEdit()
            template_edit.setMinimumHeight(180)
            template_layout.addWidget(template_edit)
            if root_layout is not None:
                insert_index = root_layout.count()
                if preview_label is not None:
                    for index in range(root_layout.count()):
                        item = root_layout.itemAt(index)
                        if item is not None and item.widget() is preview_label:
                            insert_index = index
                            break
                root_layout.insertWidget(insert_index, template_group)
        else:
            widget = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(widget)

            intro = QtWidgets.QLabel(
                "Build one or more supervisor personas for the Screen source. Each persona can own several behaviors, where every behavior pairs a visual trigger with the action the hidden LLM should take."
            )
            intro.setWordWrap(True)
            layout.addWidget(intro)

            state_label = QtWidgets.QLabel()
            state_label.setWordWrap(True)
            state_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            layout.addWidget(state_label)

            persona_header = QtWidgets.QHBoxLayout()
            persona_label = QtWidgets.QLabel("Active Persona")
            persona_label.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
            persona_header.addWidget(persona_label)
            persona_header.addStretch(1)
            add_persona_button = QtWidgets.QPushButton("Add Supervisor Persona")
            rename_persona_button = QtWidgets.QPushButton("Rename")
            delete_persona_button = QtWidgets.QPushButton("Delete")
            persona_header.addWidget(add_persona_button)
            persona_header.addWidget(rename_persona_button)
            persona_header.addWidget(delete_persona_button)
            layout.addLayout(persona_header)

            persona_combo = NoWheelComboBox()
            layout.addWidget(persona_combo)

            form = QtWidgets.QFormLayout()
            persona_style_edit = QtWidgets.QLineEdit()
            form.addRow("Persona tone", persona_style_edit)
            layout.addLayout(form)

            behavior_header = QtWidgets.QHBoxLayout()
            behavior_label = QtWidgets.QLabel("Behaviors")
            behavior_label.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
            behavior_header.addWidget(behavior_label)
            behavior_header.addStretch(1)
            add_behavior_button = QtWidgets.QPushButton("Add Behavior")
            behavior_header.addWidget(add_behavior_button)
            layout.addLayout(behavior_header)

            behaviors_widget = QtWidgets.QWidget()
            behaviors_layout = QtWidgets.QVBoxLayout(behaviors_widget)
            behaviors_layout.setContentsMargins(0, 0, 0, 0)
            behaviors_layout.setSpacing(8)
            layout.addWidget(behaviors_widget)

            note = QtWidgets.QLabel("Each enabled behavior should describe a clear screen pattern and the in-character interruption it should trigger. Open Advanced only when you want tighter control.")
            note.setWordWrap(True)
            note.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            layout.addWidget(note)

            template_group = QtWidgets.QGroupBox("Supervisor Prompt Template")
            template_layout = QtWidgets.QVBoxLayout(template_group)
            template_header = QtWidgets.QHBoxLayout()
            template_hint = QtWidgets.QLabel("Edit the template that wraps this addon's behavior rules before they are sent to hidden PING/PONG.")
            template_hint.setWordWrap(True)
            template_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            template_reset_button = QtWidgets.QPushButton("Use Recommended")
            template_header.addWidget(template_hint, 1)
            template_header.addWidget(template_reset_button, 0)
            template_layout.addLayout(template_header)
            template_edit = QtWidgets.QPlainTextEdit()
            template_edit.setMinimumHeight(180)
            template_layout.addWidget(template_edit)
            layout.addWidget(template_group)

            preview_header = QtWidgets.QLabel("Active Rendered Prompt")
            preview_header.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
            layout.addWidget(preview_header)

            preview_edit = QtWidgets.QPlainTextEdit()
            preview_edit.setReadOnly(True)
            preview_edit.setMinimumHeight(180)
            layout.addWidget(preview_edit)
            layout.addStretch(1)

        sync = {"active": False}

        def clear_layout(target_layout):
            while target_layout.count():
                item = target_layout.takeAt(0)
                child_widget = item.widget()
                child_layout = item.layout()
                if child_widget is not None:
                    child_widget.deleteLater()
                elif child_layout is not None:
                    clear_layout(child_layout)

        def refresh_preview():
            if not self.enabled:
                preview_edit.setPlainText("Disabled. This child behavior is currently excluded by its parent Screen source tab.")
                return
            preview_edit.setPlainText(self._render_prompt())

        def commit_prompt_template():
            if sync["active"]:
                return
            if self._set_prompt_template(template_edit.toPlainText()):
                refresh_preview()
            else:
                refresh_preview()

        def reset_prompt_template():
            self._reset_prompt_template_to_recommended()
            template_edit.blockSignals(True)
            template_edit.setPlainText(str(self.prompt_template or ""))
            template_edit.blockSignals(False)
            refresh_preview()

        def commit_persona_style():
            if sync["active"]:
                return
            persona = self._selected_persona()
            new_style = str(persona_style_edit.text() or "").strip() or self._style_hint_for_name(persona.get("name"))
            if new_style != str(persona.get("style") or ""):
                persona["style"] = new_style
                self._publish_prompt_only()
                refresh_preview()
            else:
                refresh_preview()

        def commit_behavior_change(persona_id, behavior_id, *, trigger=None, action=None, enabled=None, strictness=None, emotion=None, repeat_mode=None, repeat_interval=None):
            persona = self._find_persona(persona_id)
            behavior = self._find_behavior(persona, behavior_id)
            if persona is None or behavior is None:
                return
            changed = False
            if trigger is not None and str(trigger).strip() != str(behavior.get("trigger") or ""):
                behavior["trigger"] = str(trigger).strip()
                changed = True
            if action is not None and str(action).strip() != str(behavior.get("action") or ""):
                behavior["action"] = str(action).strip()
                changed = True
            if enabled is not None and bool(enabled) != bool(behavior.get("enabled", True)):
                behavior["enabled"] = bool(enabled)
                changed = True
            if strictness is not None:
                strictness_value = self._normalize_strictness(strictness)
                if strictness_value != str(behavior.get("strictness") or DEFAULT_STRICTNESS):
                    behavior["strictness"] = strictness_value
                    changed = True
            if emotion is not None:
                emotion_value = self._normalize_emotion(emotion)
                if emotion_value != str(behavior.get("emotion") or DEFAULT_EMOTION):
                    behavior["emotion"] = emotion_value
                    changed = True
            if repeat_mode is not None:
                repeat_mode_value = self._normalize_repeat_mode(repeat_mode)
                if repeat_mode_value != str(behavior.get("repeat_mode") or DEFAULT_REPEAT_MODE):
                    behavior["repeat_mode"] = repeat_mode_value
                    changed = True
            if repeat_interval is not None:
                repeat_interval_value = self._normalize_repeat_interval(repeat_interval)
                if repeat_interval_value != int(behavior.get("repeat_interval") or DEFAULT_REPEAT_INTERVAL):
                    behavior["repeat_interval"] = repeat_interval_value
                    changed = True
            if changed:
                self._publish_prompt_only()
            refresh_preview()

        def rebuild_behavior_rows():
            clear_layout(behaviors_layout)
            persona = self._selected_persona()
            behavior_items = list(persona.get("behaviors") or [])
            if not behavior_items:
                empty = QtWidgets.QLabel("No behaviors are configured for this persona yet. Add one to teach the supervisor what to notice and how to react.")
                empty.setWordWrap(True)
                empty.setStyleSheet("color: #8ea3b8; font-size: 11px;")
                behaviors_layout.addWidget(empty)
                return
            for index, behavior in enumerate(behavior_items, start=1):
                box = QtWidgets.QGroupBox(f"Behavior {index}")
                box_layout = QtWidgets.QVBoxLayout(box)
                box_layout.setSpacing(6)

                top_row = QtWidgets.QHBoxLayout()
                enabled_checkbox = QtWidgets.QCheckBox("Enabled")
                enabled_checkbox.setChecked(bool(behavior.get("enabled", False)))
                advanced_button = QtWidgets.QToolButton()
                advanced_button.setText("Advanced")
                advanced_button.setCheckable(True)
                advanced_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
                advanced_button.setChecked(str(behavior.get("id") or "") in self._expanded_behavior_ids)
                remove_button = QtWidgets.QPushButton("Remove")
                top_row.addWidget(enabled_checkbox)
                top_row.addStretch(1)
                top_row.addWidget(advanced_button)
                top_row.addWidget(remove_button)
                box_layout.addLayout(top_row)

                trigger_label = QtWidgets.QLabel("Visual Trigger")
                trigger_label.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
                box_layout.addWidget(trigger_label)
                trigger_edit = QtWidgets.QPlainTextEdit()
                trigger_edit.setMinimumHeight(24)
                trigger_edit.setMaximumHeight(52)
                trigger_edit.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
                trigger_edit.setPlainText(str(behavior.get("trigger") or ""))
                self._install_behavior_refine_menu(trigger_edit, "Visual Trigger")
                box_layout.addWidget(trigger_edit, 0)

                action_label = QtWidgets.QLabel("Action")
                action_label.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
                box_layout.addWidget(action_label)
                action_edit = QtWidgets.QPlainTextEdit()
                action_edit.setMinimumHeight(28)
                action_edit.setMaximumHeight(56)
                action_edit.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
                action_edit.setPlainText(str(behavior.get("action") or ""))
                self._install_behavior_refine_menu(action_edit, "Action")
                box_layout.addWidget(action_edit, 0)

                advanced_panel = QtWidgets.QWidget()
                advanced_layout = QtWidgets.QFormLayout(advanced_panel)
                advanced_layout.setContentsMargins(0, 4, 0, 0)
                advanced_layout.setSpacing(6)

                strictness_combo = NoWheelComboBox()
                strictness_combo.addItems(STRICTNESS_OPTIONS)
                strictness_combo.setCurrentText(self._normalize_strictness(behavior.get("strictness")))
                advanced_layout.addRow("Strictness", strictness_combo)

                emotion_combo = NoWheelComboBox()
                emotion_combo.addItems(EMOTION_OPTIONS)
                emotion_combo.setCurrentText(self._normalize_emotion(behavior.get("emotion")))
                advanced_layout.addRow("Emotion override", emotion_combo)

                repeat_mode_combo = NoWheelComboBox()
                repeat_mode_combo.addItems(REPEAT_MODE_OPTIONS)
                repeat_mode_combo.setCurrentText(self._normalize_repeat_mode(behavior.get("repeat_mode")))
                repeat_mode_combo.setToolTip("Choose whether this behavior fires once, on a cadence, or only after a meaningful scene change.")
                advanced_layout.addRow("Repeat mode", repeat_mode_combo)

                repeat_interval_spin = QtWidgets.QSpinBox()
                repeat_interval_spin.setRange(1, 999)
                repeat_interval_spin.setValue(self._normalize_repeat_interval(behavior.get("repeat_interval")))
                repeat_interval_spin.setToolTip("Only used for Every Nth match. Set to 1 to comment on every matching refresh.")
                advanced_layout.addRow("Nth match interval", repeat_interval_spin)

                def sync_repeat_interval_control(mode_text, spin=repeat_interval_spin):
                    spin.setEnabled(str(mode_text or "") == "Every Nth match")

                sync_repeat_interval_control(repeat_mode_combo.currentText())

                advanced_panel.setVisible(advanced_button.isChecked())
                box_layout.addWidget(advanced_panel)

                enabled_checkbox.toggled.connect(
                    lambda checked, pid=persona["id"], bid=behavior["id"]: commit_behavior_change(pid, bid, enabled=checked)
                )
                trigger_edit.textChanged.connect(
                    lambda pid=persona["id"], bid=behavior["id"], edit=trigger_edit: commit_behavior_change(pid, bid, trigger=edit.toPlainText())
                )
                action_edit.textChanged.connect(
                    lambda pid=persona["id"], bid=behavior["id"], edit=action_edit: commit_behavior_change(pid, bid, action=edit.toPlainText())
                )
                strictness_combo.currentTextChanged.connect(
                    lambda value, pid=persona["id"], bid=behavior["id"]: commit_behavior_change(pid, bid, strictness=value)
                )
                emotion_combo.currentTextChanged.connect(
                    lambda value, pid=persona["id"], bid=behavior["id"]: commit_behavior_change(pid, bid, emotion=value)
                )
                repeat_mode_combo.currentTextChanged.connect(
                    lambda value, pid=persona["id"], bid=behavior["id"], spin=repeat_interval_spin: (sync_repeat_interval_control(value, spin), commit_behavior_change(pid, bid, repeat_mode=value))
                )
                repeat_interval_spin.valueChanged.connect(
                    lambda value, pid=persona["id"], bid=behavior["id"]: commit_behavior_change(pid, bid, repeat_interval=value)
                )
                advanced_button.toggled.connect(
                    lambda checked, panel=advanced_panel, bid=behavior["id"]: (panel.setVisible(bool(checked)), self._set_behavior_expanded(bid, bool(checked)))
                )
                remove_button.clicked.connect(lambda _=False, bid=behavior["id"]: self._delete_behavior(bid))
                behaviors_layout.addWidget(box)

        def refresh_from_state():
            sync["active"] = True
            try:
                self._ensure_selected_persona()
                active = self._selected_persona()
                persona_combo.blockSignals(True)
                persona_combo.clear()
                for item in self.personas:
                    persona_combo.addItem(str(item.get("name") or "Unnamed Persona"), item.get("id"))
                selected_index = max(0, persona_combo.findData(active.get("id")))
                persona_combo.setCurrentIndex(selected_index)
                persona_combo.blockSignals(False)
                persona_style_edit.blockSignals(True)
                persona_style_edit.setText(str(active.get("style") or self._style_hint_for_name(active.get("name"))))
                persona_style_edit.blockSignals(False)
                persona_combo.setEnabled(bool(self.enabled))
                persona_style_edit.setEnabled(bool(self.enabled))
                template_edit.blockSignals(True)
                template_edit.setPlainText(str(self.prompt_template or self.recommended_prompt_template or FALLBACK_TEMPLATE))
                template_edit.blockSignals(False)
                template_edit.setEnabled(bool(self.enabled))
                template_reset_button.setEnabled(bool(self.enabled))
                add_persona_button.setEnabled(bool(self.enabled))
                rename_persona_button.setEnabled(bool(self.enabled))
                delete_persona_button.setEnabled(bool(self.enabled) and len(self.personas) > 1)
                add_behavior_button.setEnabled(bool(self.enabled))
                state_label.setText(
                    f"The Screen Supervisor is active. Persona '{active.get('name')}' currently owns {len(list(active.get('behaviors') or []))} behavior(s)."
                    if self.enabled else
                    "The Screen Supervisor is currently inactive. Re-enable it from Screen -> Include."
                )
                rebuild_behavior_rows()
                refresh_preview()
            finally:
                sync["active"] = False

        def on_persona_changed():
            if sync["active"]:
                return
            selected_id = str(persona_combo.currentData() or "").strip()
            if selected_id and selected_id != str(self.selected_persona_id or ""):
                self.selected_persona_id = selected_id
                self._publish_state()
            else:
                refresh_preview()

        def add_persona():
            name, accepted = QtWidgets.QInputDialog.getText(widget, "Add Supervisor Persona", "Persona name:")
            if accepted and str(name or "").strip():
                self._add_persona(name)

        def rename_persona():
            active = self._selected_persona()
            name, accepted = QtWidgets.QInputDialog.getText(
                widget,
                "Rename Persona",
                "Persona name:",
                text=str(active.get("name") or ""),
            )
            if accepted and str(name or "").strip():
                self._rename_selected_persona(name)

        persona_combo.currentIndexChanged.connect(lambda *_args: on_persona_changed())
        persona_style_edit.textChanged.connect(lambda *_args: commit_persona_style())
        template_edit.textChanged.connect(lambda *_args: commit_prompt_template())
        template_reset_button.clicked.connect(lambda *_args: reset_prompt_template())
        add_persona_button.clicked.connect(add_persona)
        rename_persona_button.clicked.connect(rename_persona)
        delete_persona_button.clicked.connect(lambda *_args: self._delete_selected_persona())
        add_behavior_button.clicked.connect(lambda *_args: self._add_behavior())

        self._register_tab_refresher(refresh_from_state)
        widget.destroyed.connect(lambda *_args, cb=refresh_from_state: self._unregister_tab_refresher(cb))
        refresh_from_state()
        return widget
