from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AddonManifest:
    id: str
    name: str
    version: str
    entry_point: str
    description: str = ""
    category: str = ""
    permissions: list[str] = field(default_factory=list)
    ui: list[dict[str, Any]] = field(default_factory=list)
    enabled: bool = True
    manifest_path: Path | None = None

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
            ui=[
                dict(item)
                for item in list(payload.get("ui", []) or [])
                if isinstance(item, dict)
            ],
            enabled=bool(payload.get("enabled", True)),
            manifest_path=path,
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
