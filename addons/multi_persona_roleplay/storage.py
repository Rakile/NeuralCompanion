from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import PersonaConfig, RoleplaySessionState, personas_from_payload


class RoleplayStorage:
    STORY_SCHEMA_VERSION = 2
    MEMORY_SCHEMA_VERSION = 2

    def __init__(self, context):
        self.context = context
        self.logger = context.logger if context is not None else None
        self.defaults_dir = Path(context.manifest.root_dir) / "defaults"

    def _log_warning(self, message: str, *args) -> None:
        logger = self.logger
        if logger is not None:
            logger.warning(message, *args)

    def _default_json(self, name: str, fallback: Any) -> Any:
        path = self.defaults_dir / name
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._log_warning("Failed to read default %s: %s", name, exc)
            return fallback

    def _read_json(self, relative_path: str, fallback: Any) -> Any:
        try:
            path = self.context.storage.resolve(relative_path)
            if not path.exists():
                return fallback
            return self.context.storage.read_json(relative_path)
        except Exception as exc:
            self._log_warning("Failed to read %s: %s", relative_path, exc)
            return fallback

    def _write_json(self, relative_path: str, payload: Any) -> None:
        self.context.storage.write_json(relative_path, payload)

    def ensure_defaults(self) -> None:
        if not self.context.storage.resolve("personas.json").exists():
            self._write_json("personas.json", self._default_json("personas.json", []))
        if not self.context.storage.resolve("visual_styles.json").exists():
            self._write_json("visual_styles.json", self._default_json("visual_styles.json", []))
        if not self.context.storage.resolve("roleplay_templates.json").exists():
            self._write_json("roleplay_templates.json", self._default_json("roleplay_templates.json", {}))
        if not self.context.storage.resolve("scenarios/default_group_scene.json").exists():
            self._write_json("scenarios/default_group_scene.json", self._default_json("default_group_scene.json", {}))
        if not self.context.storage.resolve("settings.json").exists():
            self._write_json("settings.json", {"version": 1, "repetition_threshold": 0.8})
        settings = self._read_json("settings.json", {})
        if not isinstance(settings, dict):
            settings = {"version": 1, "repetition_threshold": 0.8}
        settings_changed = False
        if "show_current_character_visual" not in settings:
            settings["show_current_character_visual"] = False
            settings_changed = True
        if "story_sounds_enabled" not in settings:
            settings["story_sounds_enabled"] = True
            settings_changed = True
        session_path = self.context.storage.resolve("sessions/current_session.json")
        if not session_path.exists():
            self.save_session(self.load_default_session())
            settings["default_scenario_seeded"] = True
            self._write_json("settings.json", settings)
            return
        if not bool(settings.get("default_scenario_seeded", False)):
            current_session = self._read_json("sessions/current_session.json", {})
            if self._session_looks_uninitialized(current_session):
                self.save_session(self.load_default_session())
            settings["default_scenario_seeded"] = True
            self._write_json("settings.json", settings)
            settings_changed = False
        if settings_changed:
            self._write_json("settings.json", settings)

    @staticmethod
    def _session_looks_uninitialized(payload: Any) -> bool:
        if not isinstance(payload, dict):
            return True
        meaningful_keys = (
            "scene_title",
            "location",
            "time_of_day",
            "mood",
            "objective",
            "scene_summary",
        )
        if any(str(payload.get(key) or "").strip() for key in meaningful_keys):
            return False
        if int(payload.get("turn_index", 0) or 0) > 0:
            return False
        if payload.get("recent_events"):
            return False
        return not bool(payload.get("enabled", False))

    def load_personas(self) -> list[PersonaConfig]:
        self.ensure_defaults()
        personas = personas_from_payload(self._read_json("personas.json", []))
        if personas:
            personas = self._seed_ar_persona_profiles_once(personas)
            return personas
        personas = personas_from_payload(self._default_json("personas.json", []))
        self.save_personas(personas)
        return personas

    def save_personas(self, personas: list[PersonaConfig]) -> None:
        self._write_json("personas.json", [persona.to_dict() for persona in list(personas or [])])

    def _seed_ar_persona_profiles_once(self, personas: list[PersonaConfig]) -> list[PersonaConfig]:
        settings = self._read_json("settings.json", {})
        if not isinstance(settings, dict) or bool(settings.get("ar_profile_defaults_seeded", False)):
            return personas
        defaults = personas_from_payload(self._default_json("personas.json", []))
        defaults_by_id = {persona.id: persona for persona in defaults}
        changed = False
        for persona in personas:
            default = defaults_by_id.get(persona.id)
            if default is None:
                continue
            if not str(persona.ar_description or "").strip() and str(default.ar_description or "").strip():
                persona.ar_description = default.ar_description
                changed = True
            if not str(persona.ar_system_prompt or "").strip() and str(default.ar_system_prompt or "").strip():
                persona.ar_system_prompt = default.ar_system_prompt
                changed = True
        settings["ar_profile_defaults_seeded"] = True
        self._write_json("settings.json", settings)
        if changed:
            self.save_personas(personas)
        return personas

    def load_session(self) -> RoleplaySessionState:
        self.ensure_defaults()
        payload = self._read_json("sessions/current_session.json", {})
        payload = self._seed_ar_session_defaults_once(payload if isinstance(payload, dict) else {})
        return RoleplaySessionState.from_dict(payload if isinstance(payload, dict) else {})

    def load_default_session(self) -> RoleplaySessionState:
        payload = self._default_json("default_group_scene.json", {})
        return RoleplaySessionState.from_dict(payload if isinstance(payload, dict) else {})

    def save_session(self, session: RoleplaySessionState) -> None:
        self._write_json("sessions/current_session.json", session.to_dict())

    def load_story_index(self) -> list[dict[str, Any]]:
        raw = self._read_json("stories/index.json", [])
        if not isinstance(raw, list):
            return []
        items = []
        seen = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            story_id = self.story_id(item.get("id") or item.get("title") or "")
            if not story_id or story_id in seen:
                continue
            seen.add(story_id)
            items.append({
                "id": story_id,
                "title": str(item.get("title") or story_id).strip() or story_id,
                "updated_at": str(item.get("updated_at") or "").strip(),
            })
        return items

    def save_story(self, story: dict[str, Any]) -> str:
        payload = dict(story or {})
        payload["schema_version"] = self.STORY_SCHEMA_VERSION
        story_id = self.story_id(payload.get("id") or payload.get("title") or "story")
        payload["id"] = story_id
        self._write_json(f"stories/{story_id}.json", payload)
        index = [item for item in self.load_story_index() if item.get("id") != story_id]
        index.append({
            "id": story_id,
            "title": str(payload.get("title") or story_id).strip() or story_id,
            "updated_at": str(payload.get("updated_at") or "").strip(),
        })
        index.sort(key=lambda item: str(item.get("title") or item.get("id") or "").lower())
        self._write_json("stories/index.json", index)
        return story_id

    def load_story(self, story_id: str) -> dict[str, Any]:
        normalized = self.story_id(story_id)
        if not normalized:
            return {}
        raw = self._read_json(f"stories/{normalized}.json", {})
        return self._migrate_story_payload(dict(raw or {}) if isinstance(raw, dict) else {}, normalized)

    def save_story_memory(self, story_id: str, payload: dict[str, Any]) -> None:
        normalized = self.story_id(story_id)
        if not normalized:
            return
        data = dict(payload or {})
        data["schema_version"] = self.MEMORY_SCHEMA_VERSION
        self._write_json(f"stories/{normalized}.memory.json", data)

    def load_story_memory(self, story_id: str) -> dict[str, Any]:
        normalized = self.story_id(story_id)
        if not normalized:
            return {}
        raw = self._read_json(f"stories/{normalized}.memory.json", {})
        return self._migrate_story_memory(dict(raw or {}) if isinstance(raw, dict) else {}, normalized)

    def _migrate_story_payload(self, payload: dict[str, Any], story_id: str = "") -> dict[str, Any]:
        if not payload:
            return {}
        notes: list[str] = []
        try:
            schema_version = int(payload.get("schema_version", 1) or 1)
        except Exception:
            schema_version = 1
            notes.append("invalid schema_version was treated as 1")
        schema_version = max(1, schema_version)
        if schema_version > self.STORY_SCHEMA_VERSION:
            notes.append(f"unsupported future schema_version {schema_version}; loaded with fallback defaults")
            self._log_warning("Story %s uses unsupported schema_version %s; using fallback defaults.", story_id or payload.get("id") or "", schema_version)
        if "schema_version" not in payload:
            notes.append("missing schema_version; treated as legacy story")
        payload["schema_version"] = min(schema_version, self.STORY_SCHEMA_VERSION)
        payload.setdefault("id", self.story_id(payload.get("title") or story_id or "story"))
        payload.setdefault("title", str(payload.get("id") or "Story").replace("_", " ").title())
        payload.setdefault("summary", "")
        if not isinstance(payload.get("session"), dict):
            payload["session"] = {}
            notes.append("missing session object; created empty session")
        if not isinstance(payload.get("personas"), list):
            payload["personas"] = []
            notes.append("missing personas list; created empty list")
        if not isinstance(payload.get("persona_overrides"), dict):
            payload["persona_overrides"] = {}
        if notes:
            payload["_migration_log"] = notes
            self._log_warning("Story %s migration/fallback: %s", payload.get("id") or story_id, "; ".join(notes))
        return payload

    def _migrate_story_memory(self, payload: dict[str, Any], story_id: str = "") -> dict[str, Any]:
        if not payload:
            return {}
        notes: list[str] = []
        try:
            schema_version = int(payload.get("schema_version", 1) or 1)
        except Exception:
            schema_version = 1
            notes.append("invalid schema_version was treated as 1")
        schema_version = max(1, schema_version)
        if schema_version > self.MEMORY_SCHEMA_VERSION:
            notes.append(f"unsupported future schema_version {schema_version}; loaded with fallback defaults")
            self._log_warning("Story memory %s uses unsupported schema_version %s; using fallback defaults.", story_id, schema_version)
        if "schema_version" not in payload:
            notes.append("missing schema_version; treated as legacy story memory")
        payload["schema_version"] = min(schema_version, self.MEMORY_SCHEMA_VERSION)
        payload.setdefault("story_id", story_id)
        if not isinstance(payload.get("long_memory"), dict):
            payload["long_memory"] = {}
            notes.append("missing long_memory object; created empty memory")
        if not isinstance(payload.get("session"), dict):
            payload["session"] = {}
            notes.append("missing session object; created empty session")
        if not isinstance(payload.get("settings"), dict):
            payload["settings"] = {}
            notes.append("missing settings object; created empty settings")
        if notes:
            payload["_migration_log"] = notes
            self._log_warning("Story memory %s migration/fallback: %s", payload.get("story_id") or story_id, "; ".join(notes))
        return payload

    def delete_story(self, story_id: str) -> None:
        normalized = self.story_id(story_id)
        if not normalized:
            return
        path = self.context.storage.resolve(f"stories/{normalized}.json")
        try:
            if path.exists():
                path.unlink()
        except Exception as exc:
            self._log_warning("Failed to delete story %s: %s", normalized, exc)
        memory_path = self.context.storage.resolve(f"stories/{normalized}.memory.json")
        try:
            if memory_path.exists():
                memory_path.unlink()
        except Exception as exc:
            self._log_warning("Failed to delete story memory %s: %s", normalized, exc)
        index = [item for item in self.load_story_index() if item.get("id") != normalized]
        self._write_json("stories/index.json", index)

    @staticmethod
    def story_id(value: Any) -> str:
        raw = str(value or "").strip().lower()
        result = []
        previous = False
        for char in raw:
            if char.isalnum():
                result.append(char)
                previous = False
            elif not previous:
                result.append("_")
                previous = True
        text = "".join(result).strip("_")
        return text[:80] or "story"

    def _seed_ar_session_defaults_once(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self._read_json("settings.json", {})
        if not isinstance(settings, dict) or bool(settings.get("ar_scene_defaults_seeded", False)):
            return payload
        default_payload = self._default_json("default_group_scene.json", {})
        if not isinstance(default_payload, dict) or not self._ar_state_looks_uninitialized(payload.get("ar_state")):
            settings["ar_scene_defaults_seeded"] = True
            self._write_json("settings.json", settings)
            return payload
        merged = dict(payload)
        for key in ("ar_use_persona_profiles", "ar_pacing", "ar_interaction_frequency", "ar_state"):
            if key in default_payload:
                merged[key] = default_payload[key]
        settings["ar_scene_defaults_seeded"] = True
        self._write_json("settings.json", settings)
        self._write_json("sessions/current_session.json", merged)
        return merged

    @staticmethod
    def _ar_state_looks_uninitialized(payload: Any) -> bool:
        if not isinstance(payload, dict):
            return True
        meaningful_keys = (
            "current_scene",
            "location",
            "story_goal",
            "mood",
            "time_of_day",
            "player_intent",
        )
        if any(str(payload.get(key) or "").strip() for key in meaningful_keys):
            return False
        if payload.get("recent_events") or payload.get("pending_choices") or payload.get("active_characters"):
            return False
        return True

    def load_visual_styles(self) -> list[dict[str, str]]:
        self.ensure_defaults()
        raw = self._read_json("visual_styles.json", [])
        if not isinstance(raw, list):
            raw = []
        styles = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            style_id = str(item.get("id") or "").strip()
            label = str(item.get("label") or style_id).strip()
            prompt = str(item.get("prompt") or "").strip()
            if style_id and label:
                styles.append({"id": style_id, "label": label, "prompt": prompt})
        return styles

    def load_settings(self) -> dict[str, Any]:
        self.ensure_defaults()
        raw = self._read_json("settings.json", {})
        return dict(raw or {}) if isinstance(raw, dict) else {}

    def save_settings(self, settings: dict[str, Any]) -> None:
        payload = dict(settings or {})
        payload["version"] = int(payload.get("version", 1) or 1)
        self._write_json("settings.json", payload)

    def import_personas_from_path(self, path: str | Path) -> list[PersonaConfig]:
        source = Path(path)
        payload = json.loads(source.read_text(encoding="utf-8"))
        personas = personas_from_payload(payload)
        if not personas:
            raise ValueError("Persona JSON did not contain any valid personas.")
        return personas

    def export_personas_to_path(self, path: str | Path, personas: list[PersonaConfig]) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps([persona.to_dict() for persona in list(personas or [])], indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
