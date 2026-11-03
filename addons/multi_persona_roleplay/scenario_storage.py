"""Atomic scenario snapshots; callers perform I/O on the addon worker lane."""

from __future__ import annotations
import copy
import json
import os
import re
import shutil
import stat
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from uuid import uuid4
from .scenario_models import (
    ScenarioDefinition,
    parse_scenario,
    scenario_to_dict,
    validate_variable,
    ScenarioValidationError,
)


class RevisionConflict(ValueError):
    pass


class ScenarioPersistenceError(OSError):
    pass


@dataclass(frozen=True)
class SessionCheckpoint:
    story_id: str
    session_id: str
    generation: int
    checkpoint_revision: int
    definition: ScenarioDefinition
    scene_id: str
    variables: dict
    completed_events: tuple[str, ...] = ()
    effects: dict = field(default_factory=dict)
    paused: bool = True
    started: bool = False

    @classmethod
    def create(
        cls, story_id: str, definition: ScenarioDefinition
    ) -> "SessionCheckpoint":
        return cls(
            story_id,
            uuid4().hex,
            1,
            0,
            definition,
            definition.initial_scene_id,
            {v["id"]: v["initial"] for v in definition.payload()["variables"]},
        )


def checkpoint_to_dict(cp: SessionCheckpoint) -> dict:
    return {
        key: copy.deepcopy(getattr(cp, key))
        for key in (
            "story_id",
            "session_id",
            "generation",
            "checkpoint_revision",
            "scene_id",
            "variables",
            "completed_events",
            "effects",
            "paused",
            "started",
        )
    } | {"definition": scenario_to_dict(cp.definition)}


def checkpoint_from_dict(raw: dict) -> SessionCheckpoint:
    fields = {
        "story_id",
        "session_id",
        "generation",
        "checkpoint_revision",
        "definition",
        "scene_id",
        "variables",
        "completed_events",
        "effects",
        "paused",
        "started",
    }
    if not isinstance(raw, dict) or set(raw) != fields:
        raise ScenarioValidationError("Invalid checkpoint fields")
    data = dict(raw)
    definition = data.pop("definition")
    if not isinstance(definition, dict):
        raise ScenarioValidationError("Invalid checkpoint definition")
    persona_ids = frozenset(r["persona_id"] for r in definition.get("roles", []))
    data["definition"] = parse_scenario(definition, persona_ids=persona_ids)
    for key in ("story_id", "session_id"):
        ScenarioRepository._identifier(data[key])
    for key in ("generation", "checkpoint_revision"):
        if type(data[key]) is not int or data[key] < 0:
            raise ScenarioValidationError("Invalid checkpoint revision or generation")
    if type(data["paused"]) is not bool or type(data["started"]) is not bool:
        raise ScenarioValidationError("Invalid checkpoint lifecycle flags")
    if not isinstance(data["scene_id"], str) or data["scene_id"] not in {
        s["id"] for s in definition["scenes"]
    }:
        raise ScenarioValidationError("Checkpoint scene does not exist")
    if not isinstance(data["variables"], dict) or set(data["variables"]) != {
        v["id"] for v in definition["variables"]
    }:
        raise ScenarioValidationError(
            "Checkpoint variables do not match its definition"
        )
    for variable in definition["variables"]:
        validate_variable(data["variables"][variable["id"]], variable)
    completed = data["completed_events"]
    if (
        not isinstance(completed, (list, tuple))
        or any(not isinstance(e, str) for e in completed)
        or len(set(completed)) != len(completed)
    ):
        raise ScenarioValidationError("Invalid completed-event ledger")
    if not set(completed).issubset(
        {e["id"] for e in definition["events"] if e["once"]}
    ):
        raise ScenarioValidationError("Completed event is not a declared once-event")
    effects = data["effects"]
    if not isinstance(effects, dict) or len(effects) > 10000:
        raise ScenarioValidationError("Invalid effect journal")
    for key, record in effects.items():
        if (
            not isinstance(key, str)
            or not 1 <= len(key) <= 240
            or not isinstance(record, dict)
        ):
            raise ScenarioValidationError("Invalid effect record")
        if record.get("status") not in (
            "pending",
            "completed",
            "failed",
            "cancelled",
            "indeterminate",
        ):
            raise ScenarioValidationError("Unknown effect status")
        if not isinstance(record.get("output", {}), dict):
            raise ScenarioValidationError("Invalid effect output")
    data["completed_events"] = tuple(data.get("completed_events", ()))
    return SessionCheckpoint(**data)


class ScenarioRepository:
    def __init__(self, root: Path):
        self._source_root = Path(root).absolute()
        self.root = Path(root).resolve()
        self._lock = threading.RLock()

    @staticmethod
    def _identifier(value: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,120}", value
        ):
            raise ValueError("Invalid scenario storage ID")
        return value

    def _story(self, story_id: str) -> Path:
        path = (self.root / self._identifier(story_id)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Scenario storage path escapes root")
        return path

    @staticmethod
    def _deletion_path(path: Path, root: Path):
        """Reject redirects before traversing or deleting an owned directory."""
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(metadata.st_mode) or (
            getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise ScenarioPersistenceError(f"Refusing to delete redirected scenario path: {path}")
        if not path.resolve().is_relative_to(root):
            raise ScenarioPersistenceError(f"Scenario deletion path escapes storage root: {path}")
        return metadata

    def delete_story(self, story_id: str) -> None:
        """Delete one idle story's artifacts under the existing writer lock.

        The caller must first exclude an active/queued scenario session. The
        storage lock excludes concurrent disk writes, not future worker work.
        """
        identifier = self._identifier(story_id)
        if self._deletion_path(self._source_root, self.root) is None:
            return
        with self._writer():
            directory = self.root / identifier
            if self._deletion_path(directory, self.root) is None:
                return
            # Validate the complete tree before deleting anything. In particular,
            # Windows junctions must never be followed by recursive traversal.
            pending = [directory]
            while pending:
                path = pending.pop()
                metadata = self._deletion_path(path, directory)
                if metadata is not None and stat.S_ISDIR(metadata.st_mode):
                    pending.extend(path.iterdir())
            shutil.rmtree(directory)

    @contextmanager
    def _writer(self):
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            with (self.root / "writer.lock").open("a+b") as handle:
                if os.name == "nt":
                    import msvcrt

                    if handle.tell() == 0:
                        handle.write(b"0")
                        handle.flush()
                    handle.seek(0)
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    except OSError as exc:
                        raise ScenarioPersistenceError(
                            "Scenario storage is busy"
                        ) from exc
                    try:
                        yield
                    finally:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except OSError as exc:
                        raise ScenarioPersistenceError(
                            "Scenario storage is busy"
                        ) from exc
                    try:
                        yield
                    finally:
                        fcntl.flock(handle, fcntl.LOCK_UN)

    def _write(self, path: Path, payload: dict) -> None:
        if not path.resolve().is_relative_to(self.root):
            raise ScenarioPersistenceError("Scenario path escapes storage root")
        temporary = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=".scenario-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(
                    payload, stream, ensure_ascii=False, allow_nan=False, indent=2
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except (OSError, ValueError) as exc:
            raise ScenarioPersistenceError(str(exc)) from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _read(self, path: Path) -> dict:
        # Checkpoints can contain a bounded journal larger than a single definition.
        if not path.resolve().is_relative_to(self.root):
            raise ScenarioPersistenceError("Scenario path escapes storage root")
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ScenarioPersistenceError("Scenario progress file is too large")
        return json.loads(path.read_text(encoding="utf-8"))

    def persist_story_definition(
        self, story_id: str, definition: ScenarioDefinition
    ) -> ScenarioDefinition:
        """Optimistic authored save; unchanged content reuses its immutable revision."""
        with self._writer():
            directory = self._story(story_id) / "definitions"
            revisions = sorted(
                int(p.stem) for p in directory.glob("*.json") if p.stem.isdigit()
            )
            current = revisions[-1] if revisions else None
            payload = definition.payload()
            if current is not None:
                saved = self._read(directory / f"{current}.json")
                if {k: v for k, v in saved.items() if k != "revision"} == {
                    k: v for k, v in payload.items() if k != "revision"
                }:
                    return parse_scenario(
                        saved,
                        persona_ids=frozenset(r["persona_id"] for r in saved["roles"]),
                    )
                if definition.revision != current:
                    raise RevisionConflict(
                        "Scenario definition changed; reload the saved story before overwriting it"
                    )
            payload["revision"] = (current or 0) + 1
            result = parse_scenario(
                payload,
                persona_ids=frozenset(r["persona_id"] for r in payload["roles"]),
            )
            self._write(directory / f"{result.revision}.json", payload)
            return result

    def check_definition_revision(
        self, story_id: str, definition: ScenarioDefinition
    ) -> None:
        directory = self._story(story_id) / "definitions"
        revisions = sorted(
            int(p.stem) for p in directory.glob("*.json") if p.stem.isdigit()
        )
        if not revisions:
            return
        current = revisions[-1]
        saved = self._read(directory / f"{current}.json")
        if {k: v for k, v in saved.items() if k != "revision"} == {
            k: v for k, v in definition.payload().items() if k != "revision"
        }:
            return
        if definition.revision != current:
            raise RevisionConflict(
                "Scenario definition changed; reload the saved story before applying it"
            )

    def save_definition(
        self,
        story_id: str,
        definition: ScenarioDefinition,
        *,
        expected_revision: int | None,
    ) -> ScenarioDefinition:
        with self._writer():
            directory = self._story(story_id) / "definitions"
            revisions = sorted(
                int(p.stem) for p in directory.glob("*.json") if p.stem.isdigit()
            )
            current = revisions[-1] if revisions else None
            if current != expected_revision:
                raise RevisionConflict("Story definition changed; reload before saving")
            payload = scenario_to_dict(definition)
            payload["revision"] = (current or 0) + 1
            result = parse_scenario(
                payload,
                persona_ids=frozenset(r["persona_id"] for r in payload["roles"]),
            )
            self._write(directory / f"{result.revision}.json", payload)
            return result

    def load_definition(self, story_id: str, revision: int) -> ScenarioDefinition:
        if type(revision) is not int or revision < 1:
            raise ValueError("Invalid revision")
        payload = self._read(self._story(story_id) / "definitions" / f"{revision}.json")
        return parse_scenario(
            payload, persona_ids=frozenset(r["persona_id"] for r in payload["roles"])
        )

    def save_checkpoint(
        self, checkpoint: SessionCheckpoint, *, expected_revision: int | None
    ) -> SessionCheckpoint:
        path = (
            self._story(checkpoint.story_id)
            / "sessions"
            / f"{self._identifier(checkpoint.session_id)}.json"
        )
        with self._writer():
            current = self._read(path)["checkpoint_revision"] if path.exists() else None
            if current != expected_revision:
                raise RevisionConflict(
                    "Scenario progress changed; reload before writing"
                )
            result = replace(checkpoint, checkpoint_revision=(current or 0) + 1)
            self._write(path, checkpoint_to_dict(result))
            return result

    def load_checkpoint(self, story_id: str, session_id: str) -> SessionCheckpoint:
        result = checkpoint_from_dict(
            self._read(
                self._story(story_id)
                / "sessions"
                / f"{self._identifier(session_id)}.json"
            )
        )
        if result.story_id != story_id or result.session_id != session_id:
            raise ScenarioValidationError(
                "Checkpoint ownership does not match its path"
            )
        return result

    def latest_checkpoint(self, story_id: str) -> SessionCheckpoint | None:
        paths = list((self._story(story_id) / "sessions").glob("*.json"))
        if not paths:
            return None
        path = max(paths, key=lambda p: p.stat().st_mtime_ns)
        return self.load_checkpoint(story_id, path.stem)

    def recover(self, checkpoint: SessionCheckpoint) -> SessionCheckpoint:
        effects = copy.deepcopy(checkpoint.effects)
        for record in effects.values():
            if record["status"] == "pending":
                record["status"] = (
                    "indeterminate" if record.get("dispatch_started") else "cancelled"
                )
        return replace(
            checkpoint,
            effects=effects,
            paused=True,
            generation=checkpoint.generation + 1,
        )
