from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import re
from typing import Any

MUSE_RESULTS_DIR = Path("MuseTalk") / "results" / "v15"
MUSE_AVATAR_RESULTS_DIR = MUSE_RESULTS_DIR / "avatars"
NC_AVATAR_PACKS_DIR = Path("avatar_packs")
LEGACY_MUSE_AVATAR_PACKS_DIR = MUSE_RESULTS_DIR / "avatar_packs"
MUSE_AVATAR_PACKS_DIR = NC_AVATAR_PACKS_DIR
MUSE_AVATAR_POSE_FILENAME = "avatar_pose.json"
MUSE_AVATAR_PACK_MANIFEST_FILENAME = "manifest.json"


def sanitize_pack_token(value: Any, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
    text = re.sub(r"_+", "_", text).strip("_")
    return text or fallback


def read_avatar_pose_tags(avatar_id: str, avatars_dir: Path | None = None) -> list[str]:
    root = Path(avatars_dir or MUSE_AVATAR_RESULTS_DIR)
    pose_path = root / str(avatar_id or "").strip() / MUSE_AVATAR_POSE_FILENAME
    if not pose_path.is_file():
        return []
    try:
        payload = json.loads(pose_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    tags: list[str] = []
    for raw_tag in payload.get("emotion_tags", []) or []:
        clean_tag = str(raw_tag or "").strip().strip("[]").strip().lower()
        if clean_tag and clean_tag not in tags:
            tags.append(clean_tag)
    return tags


@dataclass(slots=True)
class MuseTalkAvatarVariant:
    variant_id: str
    avatar_id: str
    avatar_path: str = ""
    tags: list[str] = field(default_factory=list)
    display_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized_tags(self) -> list[str]:
        seen: set[str] = set()
        values: list[str] = []
        for raw in list(self.tags or []):
            clean = str(raw or "").strip().strip("[]").strip().lower()
            if clean and clean not in seen:
                seen.add(clean)
                values.append(clean)
        return values


@dataclass(slots=True)
class MuseTalkAvatarTransition:
    from_variant: str
    to_variant: str
    start_frame: int
    end_frame: int
    mode: str = "play_once_then_hold_default"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload = dict(self.metadata or {})
        payload.update(
            {
                "from_variant": self.from_variant,
                "to_variant": self.to_variant,
                "start_frame": int(self.start_frame),
                "end_frame": int(self.end_frame),
                "mode": str(self.mode or "play_once_then_hold_default"),
            }
        )
        return payload


@dataclass(slots=True)
class MuseTalkAvatarPack:
    pack_id: str
    display_name: str
    default_variant: str
    variants: dict[str, MuseTalkAvatarVariant]
    transitions: list[MuseTalkAvatarTransition] = field(default_factory=list)
    source: str = "manifest"
    manifest_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def default_variant_config(self) -> MuseTalkAvatarVariant | None:
        return self.variants.get(self.default_variant) or (next(iter(self.variants.values())) if self.variants else None)

    @property
    def default_avatar_id(self) -> str:
        variant = self.default_variant_config
        return str(variant.avatar_id if variant is not None else "default_avatar")

    def variant_for_avatar_id(self, avatar_id: str) -> MuseTalkAvatarVariant | None:
        clean = str(avatar_id or "").strip()
        for variant in self.variants.values():
            if str(variant.avatar_id or "").strip() == clean:
                return variant
        return None

    def emotion_avatar_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for variant in self.variants.values():
            for tag in variant.normalized_tags():
                mapping[str(tag)] = variant.avatar_id
        return mapping

    def transition_rule_for_avatar_ids(self, from_avatar_id: str, to_avatar_id: str) -> dict[str, Any] | None:
        from_variant = self.variant_for_avatar_id(from_avatar_id)
        to_variant = self.variant_for_avatar_id(to_avatar_id)
        if from_variant is None or to_variant is None:
            return None
        for transition in self.transitions:
            if transition.from_variant == from_variant.variant_id and transition.to_variant == to_variant.variant_id:
                return transition.to_payload()
        return None

    def referenced_avatar_ids(self) -> set[str]:
        return {str(variant.avatar_id or "").strip() for variant in self.variants.values() if str(variant.avatar_id or "").strip()}

    def to_manifest_payload(self, manifest_dir: Path | None = None) -> dict[str, Any]:
        manifest_root = Path(manifest_dir).resolve() if manifest_dir is not None else None
        variants_payload: dict[str, Any] = {}
        for variant_id, variant in self.variants.items():
            payload = dict(variant.metadata or {})
            payload.update(
                {
                    "avatar_id": str(variant.avatar_id or "").strip(),
                    "tags": list(variant.normalized_tags()),
                }
            )
            if variant.display_name:
                payload["display_name"] = str(variant.display_name)
            if variant.avatar_path:
                avatar_path = Path(str(variant.avatar_path))
                stored_path = ""
                if manifest_root is not None:
                    try:
                        resolved_avatar_path = avatar_path.resolve()
                        stored_path = str(resolved_avatar_path.relative_to(manifest_root))
                    except Exception:
                        # Distributed packs must not save machine-specific paths.
                        stored_path = ""
                elif not avatar_path.is_absolute():
                    stored_path = str(avatar_path)
                if stored_path.replace("\\", "/").strip("/") in {
                    str(variant_id or "").strip(),
                    str(variant.avatar_id or "").strip(),
                }:
                    stored_path = ""
                if stored_path:
                    payload["avatar_path"] = stored_path
            variants_payload[str(variant_id)] = payload
        transitions_payload: dict[str, Any] = {}
        for transition in self.transitions:
            key = f"{transition.from_variant}->{transition.to_variant}"
            transitions_payload[key] = transition.to_payload()
        payload = dict(self.metadata or {})
        payload.update(
            {
                "id": self.pack_id,
                "display_name": self.display_name,
                "default_variant": self.default_variant,
                "variants": variants_payload,
            }
        )
        if transitions_payload:
            payload["transitions"] = transitions_payload
        return payload


def _variant_tags_from_payload(variant_id: str, avatar_id: str, payload: dict[str, Any], avatars_dir: Path) -> list[str]:
    explicit_tags = payload.get("tags") or payload.get("emotion_tags") or []
    tags: list[str] = []
    for raw in explicit_tags:
        clean = str(raw or "").strip().strip("[]").strip().lower()
        if clean and clean not in tags:
            tags.append(clean)
    if tags:
        return tags
    return read_avatar_pose_tags(avatar_id, avatars_dir=avatars_dir)


def _is_prepared_avatar_dir(path: Path) -> bool:
    candidate = Path(path)
    return candidate.is_dir() and ((candidate / "avator_info.json").is_file() or (candidate / "full_imgs").is_dir())


def _read_avatar_pose_tags_from_path(avatar_path: Path) -> list[str]:
    pose_path = Path(avatar_path) / MUSE_AVATAR_POSE_FILENAME
    if not pose_path.is_file():
        return []
    try:
        payload = json.loads(pose_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    tags: list[str] = []
    for raw_tag in payload.get("emotion_tags", []) or []:
        clean_tag = str(raw_tag or "").strip().strip("[]").strip().lower()
        if clean_tag and clean_tag not in tags:
            tags.append(clean_tag)
    return tags


def _infer_tags_for_variant(variant_id: str, avatar_path: Path) -> list[str]:
    return _read_avatar_pose_tags_from_path(avatar_path)


def load_avatar_pack_manifest(manifest_path: Path, avatars_dir: Path | None = None) -> MuseTalkAvatarPack:
    avatars_root = Path(avatars_dir or MUSE_AVATAR_RESULTS_DIR)
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    pack_id = sanitize_pack_token(payload.get("id") or manifest_path.parent.name, manifest_path.parent.name)
    display_name = str(payload.get("display_name") or pack_id).strip() or pack_id
    variants_raw = payload.get("variants") or {}
    variants: dict[str, MuseTalkAvatarVariant] = {}
    if isinstance(variants_raw, dict):
        iterable = variants_raw.items()
    else:
        iterable = []
    for raw_variant_id, raw_variant_payload in iterable:
        variant_id = sanitize_pack_token(raw_variant_id, "default")
        variant_payload = dict(raw_variant_payload or {})
        avatar_id = sanitize_pack_token(variant_payload.get("avatar_id") or variant_id, variant_id)
        raw_avatar_path = str(variant_payload.get("avatar_path") or "").strip()
        avatar_path = ""
        if raw_avatar_path:
            avatar_path_candidate = Path(raw_avatar_path)
            if not avatar_path_candidate.is_absolute():
                avatar_path_candidate = manifest_path.parent / avatar_path_candidate
            avatar_path = str(avatar_path_candidate.resolve())
        else:
            for local_name in (variant_id, avatar_id):
                local_path = manifest_path.parent / local_name
                if local_path.is_dir():
                    avatar_path = str(local_path.resolve())
                    break
        tags = _variant_tags_from_payload(variant_id, avatar_id, variant_payload, avatars_root)
        variants[variant_id] = MuseTalkAvatarVariant(
            variant_id=variant_id,
            avatar_id=avatar_id,
            avatar_path=avatar_path,
            tags=tags,
            display_name=str(variant_payload.get("display_name") or variant_id).strip(),
            metadata={k: v for k, v in variant_payload.items() if k not in {"avatar_id", "avatar_path", "tags", "emotion_tags", "display_name"}},
        )
    local_variants = {
        variant_id: variant
        for variant_id, variant in variants.items()
        if str(variant.avatar_path or "").strip()
    }
    if local_variants:
        variants = local_variants
    if not variants:
        default_avatar_id = sanitize_pack_token(payload.get("default_avatar_id") or pack_id, "default_avatar")
        variants["default"] = MuseTalkAvatarVariant(
            variant_id="default",
            avatar_id=default_avatar_id,
            avatar_path="",
            tags=read_avatar_pose_tags(default_avatar_id, avatars_dir=avatars_root),
            display_name="Default",
        )
    default_variant = sanitize_pack_token(payload.get("default_variant") or next(iter(variants.keys())), next(iter(variants.keys())))
    if default_variant not in variants:
        default_variant = next(iter(variants.keys()))

    transitions: list[MuseTalkAvatarTransition] = []
    transitions_raw = payload.get("transitions") or {}
    if isinstance(transitions_raw, dict):
        iterable_transitions = transitions_raw.items()
    elif isinstance(transitions_raw, list):
        iterable_transitions = [(f"{index}", item) for index, item in enumerate(transitions_raw)]
    else:
        iterable_transitions = []
    for transition_key, raw_transition in iterable_transitions:
        transition_payload = dict(raw_transition or {})
        from_variant = sanitize_pack_token(
            transition_payload.get("from_variant") or str(transition_key).split("->", 1)[0],
            default_variant,
        )
        to_variant = sanitize_pack_token(
            transition_payload.get("to_variant") or (str(transition_key).split("->", 1)[1] if "->" in str(transition_key) else default_variant),
            default_variant,
        )
        if from_variant not in variants or to_variant not in variants:
            continue
        transitions.append(
            MuseTalkAvatarTransition(
                from_variant=from_variant,
                to_variant=to_variant,
                start_frame=int(transition_payload.get("start_frame", 0) or 0),
                end_frame=int(transition_payload.get("end_frame", 0) or 0),
                mode=str(transition_payload.get("mode") or "play_once_then_hold_default"),
                metadata={k: v for k, v in transition_payload.items() if k not in {"from_variant", "to_variant", "start_frame", "end_frame", "mode"}},
            )
        )

    return MuseTalkAvatarPack(
        pack_id=pack_id,
        display_name=display_name,
        default_variant=default_variant,
        variants=variants,
        transitions=transitions,
        source="manifest",
        manifest_path=str(manifest_path),
        metadata={k: v for k, v in payload.items() if k not in {"id", "display_name", "default_variant", "variants", "transitions", "default_avatar_id"}},
    )


def build_legacy_avatar_pack(default_avatar_id: str, legacy_map: dict[str, str] | None = None, legacy_transitions: dict[tuple[str, str], dict[str, Any]] | None = None, avatars_dir: Path | None = None) -> MuseTalkAvatarPack:
    avatars_root = Path(avatars_dir or MUSE_AVATAR_RESULTS_DIR)
    clean_default_avatar_id = sanitize_pack_token(default_avatar_id or "default_avatar", "default_avatar")
    variants: dict[str, MuseTalkAvatarVariant] = {
        "default": MuseTalkAvatarVariant(
            variant_id="default",
            avatar_id=clean_default_avatar_id,
            avatar_path="",
            tags=read_avatar_pose_tags(clean_default_avatar_id, avatars_dir=avatars_root),
            display_name="Default",
        )
    }
    reverse_variant_by_avatar: dict[str, str] = {clean_default_avatar_id: "default"}
    for raw_emotion, raw_avatar_id in dict(legacy_map or {}).items():
        avatar_id = sanitize_pack_token(raw_avatar_id, "default_avatar")
        variant_id = sanitize_pack_token(raw_emotion, avatar_id)
        variants[variant_id] = MuseTalkAvatarVariant(
            variant_id=variant_id,
            avatar_id=avatar_id,
            avatar_path="",
            tags=read_avatar_pose_tags(avatar_id, avatars_dir=avatars_root),
            display_name=str(raw_emotion or variant_id).strip() or variant_id,
        )
        reverse_variant_by_avatar[avatar_id] = variant_id
    transitions: list[MuseTalkAvatarTransition] = []
    for (from_avatar_id, to_avatar_id), raw_rule in dict(legacy_transitions or {}).items():
        from_variant = reverse_variant_by_avatar.get(str(from_avatar_id or "").strip())
        to_variant = reverse_variant_by_avatar.get(str(to_avatar_id or "").strip())
        if not from_variant or not to_variant:
            continue
        transitions.append(
            MuseTalkAvatarTransition(
                from_variant=from_variant,
                to_variant=to_variant,
                start_frame=int((raw_rule or {}).get("start_frame", 0) or 0),
                end_frame=int((raw_rule or {}).get("end_frame", 0) or 0),
                mode=str((raw_rule or {}).get("mode") or "play_once_then_hold_default"),
                metadata={k: v for k, v in dict(raw_rule or {}).items() if k not in {"start_frame", "end_frame", "mode"}},
            )
        )
    return MuseTalkAvatarPack(
        pack_id="legacy",
        display_name=f"Legacy ({clean_default_avatar_id})",
        default_variant="default",
        variants=variants,
        transitions=transitions,
        source="legacy",
    )


def build_standalone_avatar_pack(avatar_id: str, avatars_dir: Path | None = None) -> MuseTalkAvatarPack:
    avatars_root = Path(avatars_dir or MUSE_AVATAR_RESULTS_DIR)
    clean_avatar_id = sanitize_pack_token(avatar_id, "default_avatar")
    display_name = f"{clean_avatar_id} (Single)"
    variant = MuseTalkAvatarVariant(
        variant_id="default",
        avatar_id=clean_avatar_id,
        avatar_path="",
        tags=read_avatar_pose_tags(clean_avatar_id, avatars_dir=avatars_root),
        display_name="Default",
    )
    return MuseTalkAvatarPack(
        pack_id=f"single__{clean_avatar_id}",
        display_name=display_name,
        default_variant="default",
        variants={"default": variant},
        transitions=[],
        source="standalone",
    )


def build_implicit_avatar_pack(pack_dir: Path) -> MuseTalkAvatarPack | None:
    pack_root = Path(pack_dir)
    if not pack_root.is_dir():
        return None
    variants: dict[str, MuseTalkAvatarVariant] = {}
    default_variant = ""
    for child in sorted(pack_root.iterdir()):
        if not _is_prepared_avatar_dir(child):
            continue
        variant_id = sanitize_pack_token(child.name, child.name)
        if not variant_id:
            continue
        tags = _infer_tags_for_variant(variant_id, child)
        variants[variant_id] = MuseTalkAvatarVariant(
            variant_id=variant_id,
            avatar_id=variant_id,
            avatar_path=str(child.resolve()),
            tags=tags,
            display_name=child.name,
        )
        if variant_id in {"default_avatar", "default", "neutral", "idle", "base"} and not default_variant:
            default_variant = variant_id
    if not variants:
        return None
    if not default_variant:
        default_variant = next(iter(variants.keys()))
    pack_id = sanitize_pack_token(pack_root.name, pack_root.name)
    return MuseTalkAvatarPack(
        pack_id=pack_id,
        display_name=pack_root.name,
        default_variant=default_variant,
        variants=variants,
        transitions=[],
        source="implicit_pack",
        manifest_path="",
    )


def avatar_pack_search_dirs(packs_dir: Path | None = None, *, include_legacy: bool = False) -> tuple[Path, ...]:
    """Return avatar-pack roots in preference order.

    NC-owned packs live at repo-root ``avatar_packs/``. The old MuseTalk
    results path is intentionally opt-in only so new packs stay portable.
    """
    roots: list[Path] = [Path(packs_dir or NC_AVATAR_PACKS_DIR)]
    if include_legacy:
        roots.append(LEGACY_MUSE_AVATAR_PACKS_DIR)
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(Path(root))
        if key and key not in seen:
            seen.add(key)
            deduped.append(Path(root))
    return tuple(deduped)


def discover_avatar_packs(
    default_avatar_id: str,
    legacy_map: dict[str, str] | None = None,
    legacy_transitions: dict[tuple[str, str], dict[str, Any]] | None = None,
    avatars_dir: Path | None = None,
    packs_dir: Path | None = None,
    include_legacy: bool = False,
    include_standalone: bool = True,
) -> dict[str, MuseTalkAvatarPack]:
    avatars_root = Path(avatars_dir or MUSE_AVATAR_RESULTS_DIR)
    packs: dict[str, MuseTalkAvatarPack] = {}
    referenced_avatar_ids: set[str] = set()

    if include_legacy:
        legacy_pack = build_legacy_avatar_pack(default_avatar_id, legacy_map=legacy_map, legacy_transitions=legacy_transitions, avatars_dir=avatars_root)
        packs[legacy_pack.pack_id] = legacy_pack
        referenced_avatar_ids.update(legacy_pack.referenced_avatar_ids())

    for packs_root in avatar_pack_search_dirs(packs_dir, include_legacy=include_legacy):
        if not packs_root.exists():
            continue
        for child in sorted(packs_root.iterdir()):
            if not child.is_dir():
                continue
            manifest_path = child / MUSE_AVATAR_PACK_MANIFEST_FILENAME
            pack = None
            if manifest_path.is_file():
                try:
                    pack = load_avatar_pack_manifest(manifest_path, avatars_dir=avatars_root)
                except Exception:
                    pack = None
            else:
                try:
                    pack = build_implicit_avatar_pack(child)
                except Exception:
                    pack = None
            if pack is None:
                continue
            # Earlier roots win. This lets repo-root avatar_packs override legacy
            # MuseTalk results packs with the same id.
            if pack.pack_id in packs:
                continue
            packs[pack.pack_id] = pack
            referenced_avatar_ids.update(pack.referenced_avatar_ids())

    if include_standalone and avatars_root.exists():
        for child in sorted(avatars_root.iterdir()):
            if not child.is_dir():
                continue
            avatar_id = child.name
            if avatar_id in referenced_avatar_ids:
                continue
            if not ((child / "avator_info.json").exists() or (child / "full_imgs").exists()):
                continue
            pack = build_standalone_avatar_pack(avatar_id, avatars_dir=avatars_root)
            packs[pack.pack_id] = pack

    return packs


def get_avatar_pack(
    default_avatar_id: str,
    requested_pack_id: str | None = None,
    legacy_map: dict[str, str] | None = None,
    legacy_transitions: dict[tuple[str, str], dict[str, Any]] | None = None,
    avatars_dir: Path | None = None,
    packs_dir: Path | None = None,
    include_legacy: bool = False,
    include_standalone: bool = True,
) -> MuseTalkAvatarPack:
    packs = discover_avatar_packs(
        default_avatar_id=default_avatar_id,
        legacy_map=legacy_map,
        legacy_transitions=legacy_transitions,
        avatars_dir=avatars_dir,
        packs_dir=packs_dir,
        include_legacy=include_legacy,
        include_standalone=include_standalone,
    )
    requested = str(requested_pack_id or "").strip()
    if requested and requested in packs:
        return packs[requested]
    if "legacy" in packs:
        return packs["legacy"]
    if not packs:
        if not include_legacy and not include_standalone:
            raise LookupError("No MuseTalk avatar packs available.")
        return build_legacy_avatar_pack(default_avatar_id, legacy_map=legacy_map, legacy_transitions=legacy_transitions, avatars_dir=avatars_dir)
    return next(iter(packs.values()))


def save_avatar_pack_manifest(pack: MuseTalkAvatarPack, packs_dir: Path | None = None) -> Path:
    packs_root = Path(packs_dir or MUSE_AVATAR_PACKS_DIR)
    pack_dir = packs_root / sanitize_pack_token(pack.pack_id, "pack")
    pack_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = pack_dir / MUSE_AVATAR_PACK_MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(pack.to_manifest_payload(manifest_dir=pack_dir), indent=2, ensure_ascii=True), encoding="utf-8")
    return manifest_path
