from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[2]
SCENIC_PACKS_ROOT = APP_ROOT / "ScenicPacks"
PACK_FILENAME = "scenic_pack.json"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


@dataclass(frozen=True)
class ScenicImage:
    tag: str
    image_path: str

    def absolute_path(self, pack_root: Path) -> Path:
        return (pack_root / self.image_path).resolve()


@dataclass(frozen=True)
class ScenicPack:
    pack_id: str
    pack_name: str
    root: Path
    json_path: Path
    images: tuple[ScenicImage, ...]

    def tags(self) -> set[str]:
        return {image.tag for image in self.images if image.tag}

    def image_for_tag(self, tag: str) -> ScenicImage | None:
        wanted = normalize_tag(tag)
        if not wanted:
            return None
        for image in self.images:
            if image.tag == wanted:
                return image
        if wanted != "neutral":
            for image in self.images:
                if image.tag == "neutral":
                    return image
        if self.images:
            return self.images[0]
        return None


def normalize_tag(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^\[|\]$", "", text)
    text = re.sub(r"[^a-z0-9_-]+", "_", text).strip("_")
    return text


def sanitize_pack_id(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_. -]+", "_", text).strip(" ._")
    text = re.sub(r"\s+", "_", text)
    return text or "ScenicPack"


def packs_root() -> Path:
    SCENIC_PACKS_ROOT.mkdir(parents=True, exist_ok=True)
    return SCENIC_PACKS_ROOT


def pack_json_path(pack_id: str) -> Path:
    return packs_root() / sanitize_pack_id(pack_id) / PACK_FILENAME


def discover_packs() -> dict[str, ScenicPack]:
    root = packs_root()
    packs: dict[str, ScenicPack] = {}
    for json_path in sorted(root.glob(f"*/{PACK_FILENAME}")):
        pack = load_pack(json_path)
        if pack is not None:
            packs[pack.pack_id] = pack
    return packs


def load_pack(path_or_id: str | Path) -> ScenicPack | None:
    raw_path = Path(path_or_id)
    json_path = raw_path if raw_path.suffix.lower() == ".json" else pack_json_path(str(path_or_id))
    if not json_path.exists():
        return None
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    pack_root = json_path.parent
    pack_id = sanitize_pack_id(pack_root.name)
    images = []
    for item in list(payload.get("images") or []):
        if not isinstance(item, dict):
            continue
        tag = normalize_tag(item.get("tag"))
        rel_path = _safe_relative_path(item.get("image_path"))
        if tag and rel_path:
            images.append(ScenicImage(tag=tag, image_path=rel_path))
    return ScenicPack(
        pack_id=pack_id,
        pack_name=str(payload.get("pack_name") or pack_root.name).strip() or pack_root.name,
        root=pack_root,
        json_path=json_path,
        images=tuple(images),
    )


def create_pack(pack_name: str) -> ScenicPack:
    pack_id = sanitize_pack_id(pack_name)
    root = packs_root() / pack_id
    root.mkdir(parents=True, exist_ok=True)
    (root / "images").mkdir(parents=True, exist_ok=True)
    pack = ScenicPack(
        pack_id=pack_id,
        pack_name=str(pack_name or pack_id).strip() or pack_id,
        root=root,
        json_path=root / PACK_FILENAME,
        images=(),
    )
    save_pack(pack)
    return pack


def save_pack(pack: ScenicPack) -> None:
    pack.root.mkdir(parents=True, exist_ok=True)
    payload = {
        "engine": "Scenic",
        "pack_name": pack.pack_name,
        "images": [
            {
                "tag": image.tag,
                "image_path": image.image_path.replace("\\", "/"),
            }
            for image in pack.images
        ],
    }
    pack.json_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def add_image(pack: ScenicPack, source_path: str | Path, tag: str) -> ScenicPack:
    source = Path(source_path)
    clean_tag = normalize_tag(tag)
    if not clean_tag:
        raise ValueError("Tag is required.")
    if not source.exists() or source.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError("Choose a supported image file.")
    images_dir = pack.root / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    target = images_dir / f"{clean_tag}{source.suffix.lower()}"
    previous_paths = [
        image.absolute_path(pack.root)
        for image in pack.images
        if image.tag == clean_tag
    ]
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    rel_path = target.relative_to(pack.root).as_posix()
    for previous_path in previous_paths:
        if previous_path != target.resolve():
            _delete_pack_image(pack, previous_path)
    images = [image for image in pack.images if image.tag != clean_tag]
    images.append(ScenicImage(tag=clean_tag, image_path=rel_path))
    next_pack = ScenicPack(pack.pack_id, pack.pack_name, pack.root, pack.json_path, tuple(images))
    save_pack(next_pack)
    return next_pack


def remove_tag(pack: ScenicPack, tag: str) -> ScenicPack:
    clean_tag = normalize_tag(tag)
    removed_paths = [
        image.absolute_path(pack.root)
        for image in pack.images
        if image.tag == clean_tag
    ]
    images = [image for image in pack.images if image.tag != clean_tag]
    next_pack = ScenicPack(pack.pack_id, pack.pack_name, pack.root, pack.json_path, tuple(images))
    save_pack(next_pack)
    for image_path in removed_paths:
        _delete_pack_image(pack, image_path)
    return next_pack


def update_tag(pack: ScenicPack, old_tag: str, new_tag: str, *, replace_existing: bool = False) -> ScenicPack:
    old_clean = normalize_tag(old_tag)
    new_clean = normalize_tag(new_tag)
    if not old_clean or not new_clean:
        raise ValueError("Tag is required.")
    if old_clean == new_clean:
        save_pack(pack)
        return pack
    if any(image.tag == new_clean for image in pack.images) and not replace_existing:
        raise ValueError(f"Tag '{new_clean}' already exists in this pack.")
    found = False
    source_path = None
    target_rel_path = ""
    replaced_paths = []
    images = []
    for image in pack.images:
        if image.tag == old_clean:
            source_path = image.absolute_path(pack.root)
            suffix = source_path.suffix.lower() or ".png"
            target_path = pack.root / "images" / f"{new_clean}{suffix}"
            target_rel_path = target_path.relative_to(pack.root).as_posix()
            found = True
        elif image.tag == new_clean:
            replaced_paths.append(image.absolute_path(pack.root))
        else:
            images.append(image)
    if not found:
        raise ValueError(f"Tag '{old_clean}' was not found in this pack.")
    if source_path is not None:
        _move_pack_image(pack, source_path, pack.root / target_rel_path)
    images.append(ScenicImage(tag=new_clean, image_path=target_rel_path))
    next_pack = ScenicPack(pack.pack_id, pack.pack_name, pack.root, pack.json_path, tuple(images))
    save_pack(next_pack)
    target_path = (pack.root / target_rel_path).resolve()
    for image_path in replaced_paths:
        if image_path.resolve() != target_path:
            _delete_pack_image(pack, image_path)
    return next_pack


def available_pack_emotion_names(runtime_config: dict[str, Any], *, default_names=None, **_kwargs) -> set[str]:
    names = set(default_names or [])
    pack = selected_pack(runtime_config)
    if pack is not None:
        names.update(pack.tags())
    return {normalize_tag(name) for name in names if normalize_tag(name)}


def selected_pack(runtime_config: dict[str, Any] | None) -> ScenicPack | None:
    pack_id = str((runtime_config or {}).get("scenic_pack_id") or "").strip()
    packs = discover_packs()
    pack = packs.get(pack_id) if pack_id else None
    if pack is None and packs:
        pack = next(iter(packs.values()))
    return pack


def _safe_relative_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text or Path(text).is_absolute() or ".." in Path(text).parts:
        return ""
    return text


def _delete_pack_image(pack: ScenicPack, image_path: Path) -> None:
    try:
        resolved = image_path.resolve()
        resolved.relative_to(pack.root.resolve())
    except Exception:
        return
    if resolved.is_file():
        try:
            resolved.unlink()
        except OSError:
            return


def _move_pack_image(pack: ScenicPack, source_path: Path, target_path: Path) -> None:
    try:
        source = source_path.resolve()
        target = target_path.resolve()
        source.relative_to(pack.root.resolve())
        target.relative_to(pack.root.resolve())
    except Exception:
        return
    if source == target:
        return
    if not source.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        source.replace(target)
    except OSError:
        return
