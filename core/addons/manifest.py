from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.runtime.addons import AddonExecutionLanes


@dataclass
class AddonManifest:
    id: str
    name: str
    version: str
    entry_point: str
    description: str = ""
    category: str = ""
    permissions: list[str] = field(default_factory=list)
    services: list[dict[str, Any]] = field(default_factory=list)
    ui: list[dict[str, Any]] = field(default_factory=list)
    native_qml: bool = False
    enabled: bool = True
    manifest_path: Path | None = None
    execution_lanes: AddonExecutionLanes | dict[str, Any] | list[str] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.execution_lanes, AddonExecutionLanes):
            return
        self.execution_lanes = AddonExecutionLanes.from_metadata(
            self.execution_lanes,
            inferred_ui=bool(self.ui),
        )

    @property
    def root_dir(self) -> Path:
        if self.manifest_path is None:
            raise ValueError("Manifest path is not set.")
        return self.manifest_path.parent

    @classmethod
    def from_file(cls, manifest_path: str | Path) -> "AddonManifest":
        path = Path(manifest_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifest = cls(
            id=str(payload.get("id", "") or "").strip(),
            name=str(payload.get("name", "") or "").strip(),
            version=str(payload.get("version", "") or "").strip(),
            entry_point=str(payload.get("entry_point", "") or "").strip(),
            description=str(payload.get("description", "") or "").strip(),
            category=str(payload.get("category", "") or "").strip().lower(),
            permissions=[str(item).strip() for item in list(payload.get("permissions", []) or []) if str(item).strip()],
            services=[
                dict(item)
                for item in list(payload.get("services", []) or [])
                if isinstance(item, dict)
            ],
            ui=[
                dict(item)
                for item in list(payload.get("ui", []) or [])
                if isinstance(item, dict)
            ],
            native_qml=bool(payload.get("native_qml", False)),
            enabled=bool(payload.get("enabled", True)),
            manifest_path=path,
            execution_lanes=payload.get("execution_lanes"),
        )
        manifest.validate()
        return manifest

    def validate(self):
        missing = []
        if not self.id:
            missing.append("id")
        if not self.name:
            missing.append("name")
        if not self.version:
            missing.append("version")
        if not self.entry_point:
            missing.append("entry_point")
        if missing:
            raise ValueError(f"Invalid addon manifest, missing field(s): {', '.join(missing)}")
