"""Native QML quick-persona persistence and validation."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import threading
import time
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from core.text_tags import is_single_word_control_tag, is_sound_tag
from core.persona_prompt_builder import normalize_builder, normalize_type
from core.persona_overrides import normalize_persona_overrides

from core.runtime.visual import (
    normalize_persona_appearance_freedom,
    normalize_persona_visual_reply_policy,
)

QUICK_PERSONA_SCHEMA_VERSION = 7
QUICK_PERSONA_PAGE_SIZE = 5
QUICK_PERSONA_MAX_VISIBLE_ROWS = 4
QUICK_PERSONA_INITIAL_SLOTS = 15
QUICK_PERSONA_AVATAR_MODES = frozenset({"off", "single", "mood", "ring"})
QUICK_PERSONA_AVATAR_SIZE_DEFAULT = 120
QUICK_PERSONA_AVATAR_SIZE_MINIMUM = 80
QUICK_PERSONA_AVATAR_SIZE_MAXIMUM = 400
QUICK_PERSONA_AVATAR_SIZE_STEP = 20
QUICK_PERSONA_SELF_IMAGE_MODES = frozenset({"hybrid", "prompt", "reference"})
QUICK_PERSONA_REFERENCE_STRENGTH_DEFAULT = 0.75
BUILTIN_GUIDE_ID = "nc-default-guide"
BUILTIN_GUIDE_NAME = "Echo - NC Guide"
BUILTIN_GUIDE_PROMPT = """You are Echo, NeuralCompanion's built-in guide and a warm, concise companion. Offer setup guidance only when asked. When the user asks how NeuralCompanion works, give the exact workspace, addon, tab, or control path, explain what the setting changes, and suggest one safe next step. Runtime owns language-model, speech-input, voice-output, Visual Reply, and avatar providers. Addons contains personas and Visual Identity, Web Search, sensory providers, AI Presence, Companion Orb, tutorials, performance tools, and installed optional features. Conversation contains chat input, queued messages, playback, editing, regeneration, images, Web Search, mood portraits, controls, and history. Visual Reply configures generated images; Avatar Preview shows active avatar output; Tutorials contains guided walkthroughs. Never claim that a feature is installed or that you changed, saved, enabled, or initialized anything unless NeuralCompanion reports it. If a location is uncertain, direct the user to Tutorials or the relevant addon."""


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(value: object, *, fallback: str = "persona") -> str:
    text = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    return (text[:64] or fallback).lower()


def _normalize_slot(value: object) -> int:
    try:
        slot = int(value)
    except (TypeError, ValueError):
        slot = 0
    return max(0, slot)


def _normalize_visible_rows(value: object) -> int:
    try:
        rows = int(value)
    except (TypeError, ValueError, OverflowError):
        rows = 1
    return max(1, min(QUICK_PERSONA_MAX_VISIBLE_ROWS, rows))


def _normalize_avatar_mode(value: object) -> str:
    mode = str(value or "off").strip().lower()
    return mode if mode in QUICK_PERSONA_AVATAR_MODES else "off"


def _normalize_avatar_size(value: object) -> int:
    try:
        requested = int(value)
    except (TypeError, ValueError):
        requested = QUICK_PERSONA_AVATAR_SIZE_DEFAULT
    bounded = min(
        QUICK_PERSONA_AVATAR_SIZE_MAXIMUM,
        max(QUICK_PERSONA_AVATAR_SIZE_MINIMUM, requested),
    )
    steps = round(
        (bounded - QUICK_PERSONA_AVATAR_SIZE_MINIMUM)
        / QUICK_PERSONA_AVATAR_SIZE_STEP
    )
    return QUICK_PERSONA_AVATAR_SIZE_MINIMUM + (
        steps * QUICK_PERSONA_AVATAR_SIZE_STEP
    )


def _safe_path(value: object) -> str:
    return str(value or "").strip()


def clean_persona_portrait_prompt(value: object) -> str:
    """Remove obsolete provider/background mechanics from identity prompts.

    Transparency is a generation option owned by the portrait pipeline.  Older
    records embedded alpha and #00FF00 fallbacks directly in the identity text,
    which can make image models colour the subject green instead of the backdrop.
    """

    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    text = re.sub(
        r"\s+(?:on|with)\s+(?:an?\s+)?transparent(?:\s+png)?\s+background\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    blocked_markers = (
        "#00ff00",
        "chroma-key",
        "chroma key",
        "green spill",
        "native alpha",
        "alpha channel",
        "return alpha",
        "cannot return alpha",
        "does not support alpha",
        "transparency is unavailable",
        "transparent png output",
    )
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = [
        sentence.strip()
        for sentence in sentences
        if sentence.strip()
        and not any(marker in sentence.lower() for marker in blocked_markers)
    ]
    return " ".join(kept).strip()


def _normalize_self_image_mode(value: object) -> str:
    mode = str(value or "hybrid").strip().lower()
    return mode if mode in QUICK_PERSONA_SELF_IMAGE_MODES else "hybrid"


def _normalize_reference_strength(value: object) -> float:
    try:
        strength = float(value)
    except (TypeError, ValueError):
        strength = QUICK_PERSONA_REFERENCE_STRENGTH_DEFAULT
    return round(max(0.0, min(1.0, strength)), 2)


def _coerce_persona(value: object, *, slot: int) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    name = str(value.get("name") or "").strip()
    system_prompt = str(value.get("system_prompt") or "").strip()
    if not name and not system_prompt:
        return None
    persona_id = str(value.get("id") or "").strip() or f"persona-{slot + 1}-{_slug(name)}"
    raw_moods = value.get("mood_images")
    mood_images = {
        str(key or "").strip().lower(): _safe_path(path)
        for key, path in dict(raw_moods or {}).items()
        if str(key or "").strip() and _safe_path(path)
    }
    raw_visual_auto_show = value.get("visual_reply_auto_show")
    visual_auto_show = (
        bool(raw_visual_auto_show)
        if isinstance(raw_visual_auto_show, bool)
        else None
    )
    return {
        "id": persona_id,
        "slot": slot,
        "name": name or f"Persona {slot + 1}",
        "short_bio": re.sub(r"\s+", " ", str(value.get("short_bio") or "")).strip()[:180],
        "system_prompt": system_prompt,
        "persona_prompt_type": normalize_type(value.get("persona_prompt_type")),
        "prompt_builder": normalize_builder(value.get("prompt_builder")),
        "overrides": normalize_persona_overrides(value.get("overrides")),
        "emotional_instructions": str(value.get("emotional_instructions") or ""),
        "prompt_defaults": {key: str(value["prompt_defaults"].get(key) or "") for key in ("system_prompt", "technical_prompt")} if isinstance(value.get("prompt_defaults"), Mapping) else {
            "system_prompt": system_prompt,
            "technical_prompt": str(value.get("emotional_instructions") or ""),
        },
        "voice_path": _safe_path(value.get("voice_path")),
        "use_cloned_voice": bool(value.get("use_cloned_voice", True)),
        "avatar_path": _safe_path(value.get("avatar_path")),
        "mood_images": mood_images,
        "mood_descriptions": {
            str(key).strip().lower(): str(hint or "").strip()
            for key, hint in dict(value.get("mood_descriptions") or {}).items()
            if str(key).strip().lower() in mood_images
        },
        "visual_identity_prompt": clean_persona_portrait_prompt(
            value.get("visual_identity_prompt")
        ),
        "portrait_prompt": clean_persona_portrait_prompt(value.get("portrait_prompt")),
        "portrait_transparency_enabled": bool(
            value.get("portrait_transparency_enabled", True)
        ),
        "self_image_mode": _normalize_self_image_mode(value.get("self_image_mode")),
        "appearance_freedom": normalize_persona_appearance_freedom(
            value.get("appearance_freedom")
        ),
        "visual_reference_strength": _normalize_reference_strength(
            value.get("visual_reference_strength")
        ),
        "mood_reference_enabled": bool(value.get("mood_reference_enabled", True)),
        "visual_reply_policy": normalize_persona_visual_reply_policy(
            value.get("visual_reply_policy", "inherit")
        ),
        "visual_reply_auto_show": visual_auto_show,
        "identity_relay_ref": _safe_path(value.get("identity_relay_ref")),
        "created_at": str(value.get("created_at") or _utc_stamp()),
        "updated_at": str(value.get("updated_at") or _utc_stamp()),
    }


class QuickPersonaStore:
    """Small atomic store for redesigned-UI quick persona snapshots.

    Persona presets and the established system-prompt library remain untouched.
    This store only owns the quick selector and its portrait assets.
    """

    def __init__(self, app_root: Path, *, path: Path | None = None) -> None:
        self.app_root = Path(app_root).resolve()
        self.path = Path(path or (self.app_root / "runtime" / "quick_personas.json"))
        self.asset_root = self.app_root / "runtime" / "quick_personas"
        self._lock = threading.RLock()

    def load(self, *, strict: bool = False) -> dict[str, Any]:
        with self._lock:
            raw: object = {}
            if self.path.is_file():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    if strict:
                        raise
                    raw = {}
            payload = dict(raw or {}) if isinstance(raw, Mapping) else {}
            raw_personas = payload.get("personas")
            if not isinstance(raw_personas, Mapping):
                raw_personas = {}
            personas: dict[str, dict[str, Any]] = {}
            for raw_slot, value in raw_personas.items():
                slot = _normalize_slot(raw_slot)
                persona = _coerce_persona(value, slot=slot)
                if persona is not None:
                    personas[str(slot)] = persona
            slot_count = max(
                QUICK_PERSONA_INITIAL_SLOTS,
                int(payload.get("slot_count") or 0),
                max((int(key) + 1 for key in personas), default=0),
            )
            slot_count = ((slot_count + QUICK_PERSONA_PAGE_SIZE - 1) // QUICK_PERSONA_PAGE_SIZE) * QUICK_PERSONA_PAGE_SIZE
            active_slot = payload.get("active_slot")
            try:
                active_slot = int(active_slot) if active_slot is not None else -1
            except (TypeError, ValueError):
                active_slot = -1
            if str(active_slot) not in personas:
                active_slot = -1
            return {
                "schema_version": QUICK_PERSONA_SCHEMA_VERSION,
                "slot_count": slot_count,
                "visible_rows": _normalize_visible_rows(payload.get("visible_rows")),
                "active_slot": active_slot,
                "avatar_mode": _normalize_avatar_mode(payload.get("avatar_mode")),
                "avatar_size": _normalize_avatar_size(payload.get("avatar_size")),
                "personas": personas,
                "updated_at": str(payload.get("updated_at") or ""),
                "builtin_personas_seeded": bool(payload.get("builtin_personas_seeded", False)),
                "character_copy_receipts": dict(payload.get("character_copy_receipts") or {}),
            }

    def ensure_builtin_guide(self) -> dict[str, Any] | None:
        """Seed the shipped guide once without replacing a user persona."""
        with self._lock:
            payload = self.load()
            if bool(payload.get("builtin_personas_seeded", False)):
                return None
            existing = next(
                (item for item in payload["personas"].values() if item.get("id") == BUILTIN_GUIDE_ID),
                None,
            )
            if existing is not None:
                self._seed_bundled_personas(payload)
                payload["builtin_personas_seeded"] = True
                self._write(payload)
                return dict(existing)
            slot = next(
                index for index in range(int(payload["slot_count"]) + QUICK_PERSONA_PAGE_SIZE)
                if str(index) not in payload["personas"]
            )
            record = _coerce_persona(
                {
                    "id": BUILTIN_GUIDE_ID,
                    "name": BUILTIN_GUIDE_NAME,
                    "system_prompt": BUILTIN_GUIDE_PROMPT,
                    "use_cloned_voice": False,
                    "mood_reference_enabled": False,
                    "visual_reply_policy": "inherit",
                },
                slot=slot,
            )
            if record is None:
                raise RuntimeError("The built-in NC Guide persona is invalid.")
            payload["personas"][str(slot)] = record
            payload["slot_count"] = max(int(payload["slot_count"]), slot + 1)
            payload["builtin_personas_seeded"] = True
            if int(payload["active_slot"]) < 0:
                payload["active_slot"] = slot
            self._seed_bundled_personas(payload)
            self._write(payload)
            return dict(record)

    def _seed_bundled_personas(self, payload: dict[str, Any]) -> None:
        """Add shipped starter cards only during the existing first-run seed."""
        bundle_path = self.app_root / "ui" / "assets" / "personas" / "quick_personas.json"
        try:
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        rows = bundle.get("personas", []) if isinstance(bundle, Mapping) else []
        if not isinstance(rows, list):
            return
        existing_ids = {record["id"] for record in payload["personas"].values()}
        for value in rows:
            if not isinstance(value, Mapping):
                continue
            persona_id = str(value.get("id") or "").strip()
            if not persona_id or persona_id in existing_ids:
                continue
            slot = next(index for index in range(int(payload["slot_count"]) + QUICK_PERSONA_PAGE_SIZE)
                        if str(index) not in payload["personas"])
            record = _coerce_persona(value, slot=slot)
            if record is None:
                continue
            payload["personas"][str(slot)] = record
            existing_ids.add(persona_id)
            payload["slot_count"] = max(int(payload["slot_count"]), slot + 1)

    def _write(self, payload: Mapping[str, Any]) -> None:
        normalized = dict(payload)
        normalized["schema_version"] = QUICK_PERSONA_SCHEMA_VERSION
        normalized["updated_at"] = _utc_stamp()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        temp_path.write_text(
            json.dumps(normalized, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temp_path, self.path)

    def visible_rows(self) -> int:
        return int(self.load()["visible_rows"])

    def set_visible_rows(self, rows: int) -> int:
        normalized = _normalize_visible_rows(rows)
        with self._lock:
            payload = self.load(strict=True)
            payload["visible_rows"] = normalized
            self._write(payload)
        return normalized

    def page_count(self) -> int:
        payload = self.load()
        page_size = QUICK_PERSONA_PAGE_SIZE * int(payload["visible_rows"])
        return max(1, (int(payload["slot_count"]) + page_size - 1) // page_size)

    def page(self, page_index: int) -> list[dict[str, Any]]:
        payload = self.load()
        page_size = QUICK_PERSONA_PAGE_SIZE * int(payload["visible_rows"])
        page_count = max(1, (int(payload["slot_count"]) + page_size - 1) // page_size)
        page = min(max(0, int(page_index)), page_count - 1)
        start = page * page_size
        personas = dict(payload["personas"])
        active_slot = int(payload["active_slot"])
        records = []
        for slot in range(start, start + page_size):
            persona = personas.get(str(slot))
            if persona is None:
                records.append(
                    {
                        "slot": slot,
                        "position": slot - start + 1,
                        "empty": True,
                        "active": False,
                        "name": "Empty slot",
                        "avatar_path": "",
                        "mood_images": {},
                    }
                )
                continue
            records.append(
                {
                    **dict(persona),
                    "position": slot - start + 1,
                    "empty": False,
                    "active": slot == active_slot,
                }
            )
        return records

    def persona(self, slot: int) -> dict[str, Any] | None:
        return self.load()["personas"].get(str(_normalize_slot(slot)))

    @staticmethod
    def _prompt_editor_record(record: Mapping[str, Any], active_slot: int) -> dict[str, Any]:
        from core.provider_prompt_rules import normalize_rules
        fields = {"system_prompt": record["system_prompt"],
                  "technical_prompt": record["emotional_instructions"],
                  "technical_rules": normalize_rules((record.get('overrides') or {}).get('technical_rules'))}
        revision = hashlib.sha256(json.dumps([record["id"], fields, record["prompt_defaults"]],
            ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return dict(id=record["id"], name=record["name"], revision=revision,
                    active=record["slot"] == active_slot, defaults=dict(record["prompt_defaults"]), **fields)

    def prompt_editor(self, persona_id: str) -> dict[str, Any]:
        with self._lock:
            payload = self.load(strict=True)
            record = next((r for r in payload['personas'].values() if r['id'] == persona_id), None)
            if record is None:
                raise ValueError('This persona is no longer available. Reload the list.')
            return self._prompt_editor_record(record, payload['active_slot'])

    def edit_prompts(self, persona_id: str, revision: str, system_prompt: str,
                     technical_prompt: str, *, restore: bool = False,
                     technical_rules: Mapping[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            payload = self.load(strict=True)
            record = next((r for r in payload['personas'].values() if r['id'] == persona_id), None)
            if record is None:
                raise ValueError('This persona is no longer available. Reload the list.')
            current = self._prompt_editor_record(record, payload['active_slot'])
            if current['revision'] != revision:
                raise ValueError('These prompts changed on the desktop. Reopen the editor before saving.')
            if restore:
                system_prompt = current['defaults']['system_prompt']
                technical_prompt = current['defaults']['technical_prompt']
            if any(not isinstance(v, str) or len(v) > 100000 for v in (system_prompt, technical_prompt)):
                raise ValueError('Each prompt must be text of at most 100,000 characters.')
            if technical_rules is not None:
                from core.provider_prompt_rules import normalize_rules
                if not isinstance(technical_rules, Mapping):
                    raise ValueError('Provider rules must be an object.')
                if 'legacy_enabled' in technical_rules and not isinstance(technical_rules['legacy_enabled'], bool):
                    raise ValueError('Legacy rules enabled must be a boolean.')
                for kind in ('avatar', 'tts'):
                    entries = technical_rules.get(kind, {})
                    if not isinstance(entries, Mapping) or len(entries) > 256:
                        raise ValueError('Provider rules must contain a provider map.')
                    if any(not isinstance(entry, Mapping) or not isinstance(entry.get('enabled'), bool)
                           or not isinstance(entry.get('text'), str) for entry in entries.values()):
                        raise ValueError('Each provider rule needs an enabled boolean and text.')
                rules = normalize_rules(technical_rules)
                record['overrides'] = {**dict(record.get('overrides') or {}), 'technical_rules': rules}
            record.update(system_prompt=system_prompt.strip(), emotional_instructions=technical_prompt,
                          updated_at=_utc_stamp())
            self._write(payload)
            return self._prompt_editor_record(record, payload['active_slot'])

    def active_persona(self, *, strict: bool = False) -> dict[str, Any] | None:
        payload = self.load(strict=strict)
        return payload["personas"].get(str(payload["active_slot"]))

    def avatar_mode(self) -> str:
        return str(self.load()["avatar_mode"])

    def set_avatar_mode(self, mode: str) -> str:
        normalized = _normalize_avatar_mode(mode)
        with self._lock:
            payload = self.load()
            payload["avatar_mode"] = normalized
            self._write(payload)
        return normalized

    def avatar_size(self) -> int:
        return int(self.load()["avatar_size"])

    def set_avatar_size(self, size: int) -> int:
        normalized = _normalize_avatar_size(size)
        with self._lock:
            payload = self.load()
            payload["avatar_size"] = normalized
            self._write(payload)
        return normalized

    def save_persona(
        self,
        slot: int,
        snapshot: Mapping[str, Any],
        *,
        strict: bool = False,
    ) -> dict[str, Any]:
        normalized_slot = _normalize_slot(slot)
        with self._lock:
            payload = self.load(strict=strict)
            previous = payload["personas"].get(str(normalized_slot), {})
            record = _coerce_persona(
                {
                    **dict(previous),
                    **dict(snapshot),
                    # Existing identities remain stable; new/imported records
                    # must never inherit local permissions from a deleted ID.
                    "id": previous.get("id") or "persona-" + uuid4().hex,
                    "slot": normalized_slot,
                    "created_at": previous.get("created_at") or _utc_stamp(),
                    "updated_at": _utc_stamp(),
                },
                slot=normalized_slot,
            )
            if record is None:
                raise ValueError("A quick persona needs a name or system prompt.")
            if not previous:
                # A moved persona may still own the ID derived from this position.
                owned_ids = {_slug(item["id"]) for item in payload["personas"].values()}
                base_id = _slug(record["id"])[:58]
                suffix = 2
                while _slug(record["id"]) in owned_ids:
                    record["id"] = f"{base_id}-{suffix}"
                    suffix += 1
            payload["personas"][str(normalized_slot)] = record
            payload["slot_count"] = max(
                int(payload["slot_count"]),
                ((normalized_slot // QUICK_PERSONA_PAGE_SIZE) + 1) * QUICK_PERSONA_PAGE_SIZE,
            )
            self._write(payload)
            return dict(record)

    def create_blank(self, name: str, *, slot: int | None = None) -> dict[str, Any]:
        """Add a named persona without capturing the current session settings."""
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("A persona name is required.")
        with self._lock:
            payload = self.load(strict=True)
            target = (_normalize_slot(slot) if slot is not None else
                      next(index for index in range(int(payload["slot_count"]) + 1)
                           if str(index) not in payload["personas"]))
            if str(target) in payload["personas"]:
                raise ValueError("That slot already contains a persona.")
            return self.save_persona(target, {"name": clean_name, "system_prompt": ""}, strict=True)

    def rename_persona(self, persona_id: str, name: str) -> dict[str, Any]:
        """Rename by stable identity so reordering cannot retarget an edit."""
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("A persona name is required.")
        with self._lock:
            payload = self.load(strict=True)
            record = next((item for item in payload["personas"].values()
                           if item["id"] == persona_id), None)
            if record is None:
                raise ValueError("This persona is no longer available. Reload the list.")
            if record["name"] != clean_name:
                record["name"] = clean_name
                record["updated_at"] = _utc_stamp()
                self._write(payload)
            return dict(record)

    def set_bio(self, persona_id: str, bio: str) -> dict[str, Any]:
        """Update only the short card description for a stable persona identity."""
        with self._lock:
            payload = self.load(strict=True)
            record = next((item for item in payload["personas"].values()
                           if item["id"] == persona_id), None)
            if record is None:
                raise ValueError("This persona is no longer available. Reload the list.")
            clean_bio = re.sub(r"\s+", " ", str(bio or "")).strip()[:180]
            if record["short_bio"] != clean_bio:
                record["short_bio"] = clean_bio
                record["updated_at"] = _utc_stamp()
                self._write(payload)
            return dict(record)

    def create_persona_copy(self, operation_id: str, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        """Create + receipt in one write, without selecting or replacing a persona."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", operation_id):
            raise ValueError("Invalid copy operation identity.")
        fingerprint = hashlib.sha256(json.dumps(dict(snapshot), sort_keys=True,
                                                ensure_ascii=False).encode()).hexdigest()
        with self._lock:
            payload = self.load(strict=True)
            previous = payload["character_copy_receipts"].get(operation_id)
            if previous:
                if previous.get("fingerprint") != fingerprint:
                    raise ValueError("This copy operation belongs to different character settings.")
                record = next((row for row in payload["personas"].values()
                               if row["id"] == previous["persona_id"]), None)
                if record is None:
                    raise ValueError("The copied persona has since been deleted.")
                return dict(record)
            slot = next(index for index in range(len(payload["personas"]) + 1)
                        if str(index) not in payload["personas"])
            identity = "chat-character-" + hashlib.sha256(operation_id.encode()).hexdigest()[:24]
            record = _coerce_persona({**dict(snapshot), "id": identity}, slot=slot)
            if record is None:
                raise ValueError("A copied character needs a name or description.")
            # Older pending copy intents may predate standalone character prompts.
            # Keep their original receipt fingerprint so retries still find this copy.
            if not record['system_prompt'].strip():
                record['system_prompt'] = (
                    f"You are {record['name']}. Interact with the user as this character. "
                    "Keep your identity and manner of speaking consistent, respond to the current "
                    "conversation, and leave the user's dialogue and decisions to the user.")
                if not record['prompt_defaults']['system_prompt'].strip():
                    record['prompt_defaults']['system_prompt'] = record['system_prompt']
            if not record['prompt_builder']['candidate'].strip():
                record['prompt_builder'].update(candidate=record['system_prompt'],
                                                prompt_type=record['persona_prompt_type'] or 'custom')
            if record['avatar_path']:
                source = Path(record['avatar_path'])
                source = source if source.is_absolute() else self.app_root / source
                if not source.is_file() or source.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
                    raise ValueError('The character portrait is unavailable.')
                content = source.read_bytes()
                destination = self.asset_root / identity / ('avatar-' + hashlib.sha256(content).hexdigest()[:16] + source.suffix.lower())
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    with destination.open('xb') as output:
                        output.write(content)
                        output.flush()
                        os.fsync(output.fileno())
                elif destination.read_bytes() != content:
                    raise ValueError('A different portrait owns the copy destination.')
                record['avatar_path'] = destination.relative_to(self.app_root).as_posix()
            payload["personas"][str(slot)] = record
            payload["character_copy_receipts"][operation_id] = {"fingerprint": fingerprint, "persona_id": identity}
            payload["slot_count"] = max(int(payload["slot_count"]),
                ((slot // QUICK_PERSONA_PAGE_SIZE) + 1) * QUICK_PERSONA_PAGE_SIZE)
            self._write(payload)
            return dict(record)

    def save_overrides(self, persona_id: str, overrides: Mapping[str, Any]) -> dict[str, Any]:
        """Save against stable identity under the lock, including after a reorder."""
        normalized = normalize_persona_overrides(overrides)
        with self._lock:
            payload = self.load(strict=True)
            record = next((row for row in payload["personas"].values()
                           if row["id"] == persona_id), None)
            if record is None:
                raise ValueError("The persona was removed before its overrides could be saved.")
            return self.save_persona(int(record["slot"]), {"overrides": normalized}, strict=True)

    def save_technical_rules(self, persona_id: str, rules: Mapping[str, Any]) -> dict[str, Any]:
        from core.provider_prompt_rules import normalize_rules
        normalized = normalize_rules(rules)
        with self._lock:
            record = next((row for row in self.load(strict=True)['personas'].values()
                           if row['id'] == persona_id), None)
            if record is None:
                raise ValueError('The persona is no longer available.')
            overrides = dict(record['overrides'])
            overrides['technical_rules'] = normalized
            return self.save_persona(int(record['slot']), {'overrides': overrides}, strict=True)

    def save_prompt_builder(
        self, persona_id: str, draft: Mapping[str, Any], *, apply: bool = False,
    ) -> dict[str, Any]:
        """Resolve identity under the write lock so reorders cannot retarget a draft."""
        with self._lock:
            payload = self.load(strict=True)
            record = next((row for row in payload["personas"].values()
                           if row["id"] == persona_id), None)
            if record is None:
                raise ValueError("The persona was removed before its prompt could be saved.")
            normalized = normalize_builder(draft)
            updates: dict[str, Any] = {"prompt_builder": normalized}
            if apply:
                applied_text = str(draft.get("_apply_text") or normalized["candidate"])
                if not applied_text.strip():
                    raise ValueError("The persona prompt is empty.")
                updates.update(system_prompt=applied_text,
                               persona_prompt_type=normalize_type(
                                   draft.get("_apply_type", normalized["prompt_type"])))
            return self.save_persona(int(record["slot"]), updates, strict=True)

    def move_persona(self, source: int, target: int, persona_id: str) -> None:
        """Insert a saved identity at another position without changing its assets."""
        with self._lock:
            payload = self.load(strict=True)
            count = int(payload["slot_count"])
            page_size = QUICK_PERSONA_PAGE_SIZE * int(payload["visible_rows"])
            visible_capacity = ((count + page_size - 1) // page_size) * page_size
            if not (0 <= source < count and 0 <= target < visible_capacity):
                raise ValueError("That quick persona position is no longer available.")
            records = payload["personas"]
            record = records.get(str(source))
            if record is None or record["id"] != persona_id:
                raise ValueError("That quick persona changed. Please drag it again.")
            if source == target:
                return

            def moved_slot(slot: int) -> int:
                if slot == source:
                    return target
                if source < slot <= target:
                    return slot - 1
                if target <= slot < source:
                    return slot + 1
                return slot

            payload["personas"] = {
                str(moved_slot(int(key))): {**item, "slot": moved_slot(int(key))}
                for key, item in records.items()
            }
            payload["active_slot"] = moved_slot(int(payload["active_slot"]))
            payload["slot_count"] = max(count, ((target // QUICK_PERSONA_PAGE_SIZE) + 1)
                                        * QUICK_PERSONA_PAGE_SIZE)
            self._write(payload)

    def set_active(self, slot: int) -> dict[str, Any]:
        normalized_slot = _normalize_slot(slot)
        with self._lock:
            payload = self.load()
            record = payload["personas"].get(str(normalized_slot))
            if record is None:
                raise ValueError("That quick persona slot is empty.")
            payload["active_slot"] = normalized_slot
            self._write(payload)
            return dict(record)

    def clear(self, slot: int) -> None:
        normalized_slot = _normalize_slot(slot)
        with self._lock:
            payload = self.load()
            record = payload["personas"].pop(str(normalized_slot), None)
            if payload["active_slot"] == normalized_slot:
                payload["active_slot"] = -1
            self._write(payload)
        if record:
            persona_id = _slug(record.get("id"), fallback=f"persona-{normalized_slot + 1}")
            owned_root = (self.asset_root / persona_id).resolve()
            try:
                owned_root.relative_to(self.asset_root.resolve())
            except ValueError:
                return
            if owned_root.is_dir():
                shutil.rmtree(owned_root, ignore_errors=True)

    @staticmethod
    def _write_transparent_avatar(source: Path, destination: Path) -> None:
        """Preserve alpha or remove a generated solid background with Pillow.

        Provider-supplied alpha is preserved exactly.  The local solid-backdrop
        fallback can leave green RGB values in antialiased edge pixels, so only
        that fallback suppresses green-dominant pixels along the alpha edge.
        Fully opaque interior colours are deliberately left unchanged.
        """

        try:
            from PIL import Image, ImageChops, ImageFilter, ImageStat
        except ImportError as error:  # pragma: no cover - Pillow ships with NC
            raise RuntimeError("Pillow is required to prepare transparent persona portraits.") from error

        with Image.open(source) as opened:
            image = opened.convert("RGBA")
        alpha = image.getchannel("A")
        alpha_histogram = alpha.histogram()
        transparent_pixels = sum(alpha_histogram[:245])
        if transparent_pixels >= max(1, int(image.width * image.height * 0.005)):
            # A provider-supplied alpha channel is already authoritative.  Do
            # not run legacy chroma-spill correction over genuine cutout RGB;
            # it can recolour green eyes, clothing, or fine edge details.
            image.save(destination, format="PNG")
            return
        else:
            width, height = image.size
            sample_size = max(2, min(24, width // 12, height // 12))
            corners = (
                (0, 0, sample_size, sample_size),
                (width - sample_size, 0, width, sample_size),
                (0, height - sample_size, sample_size, height),
                (width - sample_size, height - sample_size, width, height),
            )
            corner_colors = [
                ImageStat.Stat(image.crop(box).convert("RGB")).mean[:3]
                for box in corners
            ]
            background_color = tuple(
                int(
                    round(
                        sum(color[channel] for color in corner_colors)
                        / len(corner_colors)
                    )
                )
                for channel in range(3)
            )
            rgb = image.convert("RGB")
            background = Image.new("RGB", image.size, background_color)
            difference = ImageChops.difference(rgb, background).convert("L")
            transparency = difference.point(
                lambda value: (
                    0
                    if value <= 12
                    else 255
                    if value >= 44
                    else int((value - 12) * 255 / 32)
                )
            ).filter(ImageFilter.GaussianBlur(radius=0.7))

        image.putalpha(transparency)

        expanded = transparency.filter(ImageFilter.MaxFilter(size=5))
        contracted = transparency.filter(ImageFilter.MinFilter(size=5))
        edge_mask = ImageChops.subtract(expanded, contracted).filter(
            ImageFilter.GaussianBlur(radius=0.45)
        )
        cleaned_pixels = []
        for (red, green, blue, alpha_value), edge_value in zip(
            image.getdata(), edge_mask.getdata()
        ):
            neutral_green = max(red, blue)
            spill = green - neutral_green
            if spill <= 7:
                cleaned_pixels.append((red, green, blue, alpha_value))
                continue
            transparency_strength = max(0.0, (245 - alpha_value) / 180.0)
            edge_strength = (edge_value / 255.0) * 0.82
            strength = min(1.0, max(transparency_strength, edge_strength))
            cleaned_green = int(round(green - (spill * strength)))
            cleaned_pixels.append((red, cleaned_green, blue, alpha_value))
        image.putdata(cleaned_pixels)
        image.save(destination, format="PNG")

    def save_portrait_set(
        self, slot: int, persona_id: str, rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Validate a complete draft, copy new images, then atomically save it.

        Called on the portrait worker. Existing assets are retained so failed or
        cancelled edits cannot destroy a saved portrait or a history reference.
        """
        from PIL import Image

        record = self.persona(slot)
        if record is None or record["id"] != persona_id:
            raise ValueError("The selected persona has changed. Reopen the portrait editor.")
        validated: list[tuple[str, Path | None, str]] = []
        seen: set[str] = set()
        for row in rows:
            tag = str(row.get("tag") or "").strip().lower()
            if not is_single_word_control_tag(tag) or is_sound_tag(tag) or len(tag) > 32:
                raise ValueError("Use a mood tag of up to 32 letters, numbers, underscores or hyphens. Voice sounds are reserved.")
            if tag in seen:
                raise ValueError(f"The mood tag [{tag}] is already used.")
            seen.add(tag)
            raw_path = str(row.get("path") or "").strip()
            source = Path(raw_path) if raw_path else None
            if source is not None:
                source = (source if source.is_absolute() else self.app_root / source).resolve()
                if source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                    raise ValueError(f"Choose a PNG, JPEG or WebP image for [{tag}].")
                try:
                    with Image.open(source) as image:
                        image.verify()
                except (OSError, ValueError, Image.DecompressionBombError) as error:
                    raise ValueError(f"The image for [{tag}] could not be read.") from error
            elif tag != "neutral":
                raise ValueError(f"Choose an image for [{tag}] before saving.")
            validated.append((tag, source, str(row.get("hint") or "").strip()))
        if "neutral" not in seen:
            raise ValueError("Keep the neutral reference in the portrait set.")
        destination_dir = self.asset_root / _slug(persona_id)
        owned_paths = {str(record.get("avatar_path") or ""), *dict(record.get("mood_images") or {}).values()}
        owned = {(self.app_root / path).resolve() for path in owned_paths if path}
        created: list[Path] = []
        images: dict[str, str] = {}
        hints: dict[str, str] = {}
        avatar_path = ""
        try:
            for tag, source, hint in validated:
                relative = ""
                if source is not None:
                    if source in owned and source.is_relative_to(self.app_root):
                        destination = source
                    else:
                        destination = destination_dir / "moods" / f"{tag}-{time.time_ns()}{source.suffix.lower()}"
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        created.append(destination)
                        shutil.copy2(source, destination)
                    relative = destination.relative_to(self.app_root).as_posix()
                if tag == "neutral":
                    avatar_path = relative
                else:
                    images[tag] = relative
                    if hint:
                        hints[tag] = hint
            with self._lock:
                current = self.persona(slot)
                if current is None or current["id"] != persona_id or any(
                    current.get(key) != record.get(key)
                    for key in ("avatar_path", "mood_images", "mood_descriptions")
                ):
                    raise ValueError("The portrait set changed while saving. Reopen the editor and try again.")
                return self.save_persona(slot, {"avatar_path": avatar_path,
                    "mood_images": images, "mood_descriptions": hints}, strict=True)
        except Exception:
            for path in created:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    def import_avatar(
        self,
        slot: int,
        source_path: str | Path,
        *,
        mood: str = "",
        prepare_transparency: bool = False,
    ) -> str:
        record = self.persona(slot)
        if record is None:
            raise ValueError("Save the quick persona before adding an avatar.")
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise ValueError("The selected avatar image was not found.")
        suffix = ".png" if prepare_transparency else (
            source.suffix.lower()
            if source.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
            else ".png"
        )
        persona_id = _slug(record.get("id"), fallback=f"persona-{int(slot) + 1}")
        destination_dir = self.asset_root / persona_id
        normalized_mood = _slug(mood, fallback="") if str(mood or "").strip() else ""
        unique_stamp = time.time_ns()
        if normalized_mood:
            destination = destination_dir / "moods" / f"{normalized_mood}-{unique_stamp}{suffix}"
            previous_path = str(dict(record.get("mood_images") or {}).get(normalized_mood) or "")
        else:
            destination = destination_dir / f"avatar-{unique_stamp}{suffix}"
            previous_path = str(record.get("avatar_path") or "")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if prepare_transparency:
            self._write_transparent_avatar(source, destination)
        else:
            shutil.copy2(source, destination)
        relative = destination.resolve().relative_to(self.app_root).as_posix()
        updated = dict(record)
        if normalized_mood:
            mood_images = dict(updated.get("mood_images") or {})
            mood_images[normalized_mood] = relative
            updated["mood_images"] = mood_images
        else:
            updated["avatar_path"] = relative
        self.save_persona(slot, updated)
        if previous_path:
            previous = Path(previous_path)
            if not previous.is_absolute():
                previous = self.app_root / previous
            try:
                previous = previous.resolve()
                previous.relative_to(destination_dir.resolve())
            except (OSError, ValueError):
                previous = None
            if previous is not None and previous != destination.resolve() and previous.is_file():
                try:
                    previous.unlink()
                except OSError:
                    pass
        return relative
