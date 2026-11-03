from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


PRESET_SCHEMA_VERSION = 1
MAX_PRESET_NAME_LENGTH = 80
MAX_PRESET_COMMENT_LENGTH = 500
_PRESET_ID_PATTERN = re.compile(r"[A-Za-z0-9_. -]+")


class PresetValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OrbPresetRecord:
    preset_id: str
    name: str
    comment: str
    saved_at: str
    settings: dict[str, Any]


@dataclass(frozen=True, slots=True)
class OrbPresetCatalog:
    records: tuple[OrbPresetRecord, ...]
    errors: tuple[str, ...]


def _plain_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _plain_json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_plain_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [
            _plain_json_value(item)
            for item in sorted(value, key=repr)
        ]
    raise PresetValidationError(
        f"Preset setting value is not JSON-compatible: {type(value).__name__}"
    )


class CompanionOrbPresetStore:
    def __init__(self, root: Path, supported_keys: Collection[str]) -> None:
        self._root = Path(root)
        self._supported_keys = frozenset(str(key) for key in supported_keys)

    @staticmethod
    def _normalize_name(value: Any) -> str:
        if not isinstance(value, str):
            raise PresetValidationError("Preset name must be text.")
        name = value.strip()
        if not name:
            raise PresetValidationError("Preset name cannot be empty.")
        if len(name) > MAX_PRESET_NAME_LENGTH:
            raise PresetValidationError(
                f"Preset name cannot exceed {MAX_PRESET_NAME_LENGTH} characters."
            )
        return name

    @staticmethod
    def _normalize_comment(value: Any) -> str:
        if not isinstance(value, str):
            raise PresetValidationError("Preset comment must be text.")
        comment = value.strip()
        if len(comment) > MAX_PRESET_COMMENT_LENGTH:
            raise PresetValidationError(
                f"Preset comment cannot exceed {MAX_PRESET_COMMENT_LENGTH} characters."
            )
        return comment

    @classmethod
    def _preset_id_for_name(cls, name: str) -> str:
        normalized = cls._normalize_name(name)
        preset_id = re.sub(r"[^A-Za-z0-9_. -]+", "_", normalized).strip(" ._")
        if not preset_id:
            raise PresetValidationError(
                "Preset name must contain at least one filename-safe character."
            )
        return preset_id

    @staticmethod
    def _validate_preset_id(value: Any) -> str:
        if not isinstance(value, str):
            raise PresetValidationError("Preset identifier must be text.")
        preset_id = value.strip()
        if (
            not preset_id
            or preset_id in {".", ".."}
            or "/" in preset_id
            or "\\" in preset_id
            or _PRESET_ID_PATTERN.fullmatch(preset_id) is None
        ):
            raise PresetValidationError("Preset identifier is invalid.")
        return preset_id

    def _safe_path(self, preset_id: str) -> Path:
        validated = self._validate_preset_id(preset_id)
        root = self._root.resolve()
        target = (root / f"{validated}.json").resolve()
        if target.parent != root:
            raise PresetValidationError("Preset path escaped its storage directory.")
        return target

    def _matching_path(self, preset_id: str) -> Path | None:
        validated = self._validate_preset_id(preset_id)
        if not self._root.exists():
            return None
        wanted = validated.casefold()
        for path in self._root.glob("*.json"):
            if path.stem.casefold() == wanted:
                return path
        return None

    def _filtered_settings(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise PresetValidationError("Preset settings must be an object.")
        return {
            str(key): _plain_json_value(item)
            for key, item in value.items()
            if str(key) in self._supported_keys
        }

    def _record_from_payload(self, preset_id: str, payload: Any) -> OrbPresetRecord:
        if not isinstance(payload, Mapping):
            raise PresetValidationError("Preset file must contain an object.")
        version = payload.get("version")
        if type(version) is not int or version != PRESET_SCHEMA_VERSION:
            raise PresetValidationError(
                f"Unsupported Companion Orb preset version: {version!r}."
            )
        name = self._normalize_name(payload.get("name"))
        comment = self._normalize_comment(payload.get("comment", ""))
        saved_at = payload.get("saved_at")
        if not isinstance(saved_at, str):
            raise PresetValidationError("Preset save timestamp must be text.")
        settings = self._filtered_settings(payload.get("settings"))
        return OrbPresetRecord(
            preset_id=self._validate_preset_id(preset_id),
            name=name,
            comment=comment,
            saved_at=saved_at,
            settings=settings,
        )

    def catalog(self) -> OrbPresetCatalog:
        if not self._root.exists():
            return OrbPresetCatalog(records=(), errors=())
        records: list[OrbPresetRecord] = []
        errors: list[str] = []
        for path in sorted(self._root.glob("*.json"), key=lambda item: item.name.casefold()):
            try:
                records.append(self.load(path.stem))
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")
        records.sort(key=lambda record: record.name.casefold())
        return OrbPresetCatalog(records=tuple(records), errors=tuple(errors))

    def load(self, preset_id: str) -> OrbPresetRecord:
        validated = self._validate_preset_id(preset_id)
        path = self._matching_path(validated)
        if path is None:
            raise FileNotFoundError(f"Companion Orb preset not found: {validated}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PresetValidationError(
                f"Preset JSON is invalid: {exc.msg}."
            ) from exc
        return self._record_from_payload(path.stem, payload)

    def save(
        self,
        name: str,
        comment: str,
        settings: Mapping[str, Any],
        *,
        overwrite: bool,
    ) -> OrbPresetRecord:
        normalized_name = self._normalize_name(name)
        normalized_comment = self._normalize_comment(comment)
        requested_id = self._preset_id_for_name(normalized_name)
        filtered_settings = self._filtered_settings(settings)

        self._root.mkdir(parents=True, exist_ok=True)
        existing = self._matching_path(requested_id)
        if existing is not None and not overwrite:
            raise FileExistsError(
                f"Companion Orb preset already exists: {existing.stem}"
            )
        target = existing if existing is not None else self._safe_path(requested_id)
        saved_at = datetime.now().astimezone().isoformat(timespec="seconds")
        payload = {
            "version": PRESET_SCHEMA_VERSION,
            "name": normalized_name,
            "comment": normalized_comment,
            "saved_at": saved_at,
            "settings": filtered_settings,
        }

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.stem}-",
            suffix=".tmp",
            dir=str(self._root),
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            temporary_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temporary_path, target)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

        return OrbPresetRecord(
            preset_id=target.stem,
            name=normalized_name,
            comment=normalized_comment,
            saved_at=saved_at,
            settings=filtered_settings,
        )

    def delete(self, preset_id: str) -> None:
        validated = self._validate_preset_id(preset_id)
        path = self._matching_path(validated)
        if path is None:
            raise FileNotFoundError(f"Companion Orb preset not found: {validated}")
        path.unlink()
