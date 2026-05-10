from __future__ import annotations

from pathlib import Path

from addons.musetalk_avatar.avatar_packs import discover_avatar_packs, get_avatar_pack


def normalize_enabled_pack_emotions(value):
    mapping = {}
    if not isinstance(value, dict):
        return mapping
    for raw_pack_id, raw_tags in value.items():
        pack_id = str(raw_pack_id or "").strip()
        if not pack_id:
            continue
        if isinstance(raw_tags, (list, tuple, set)):
            iterable = list(raw_tags)
        else:
            iterable = str(raw_tags or "").split(",")
        tags = []
        for raw_tag in iterable:
            clean_tag = str(raw_tag or "").strip().strip("[]").strip().lower()
            if clean_tag and clean_tag not in tags:
                tags.append(clean_tag)
        mapping[pack_id] = tags
    return mapping


def enabled_pack_emotions(runtime_config, pack_id):
    mapping = normalize_enabled_pack_emotions(dict(runtime_config or {}).get("musetalk_enabled_pack_emotions"))
    clean_pack_id = str(pack_id or "").strip()
    if not clean_pack_id or clean_pack_id not in mapping:
        return None
    return set(mapping.get(clean_pack_id) or [])


def discover_packs(**kwargs):
    return discover_avatar_packs(**kwargs)


def get_pack(**kwargs):
    return get_avatar_pack(**kwargs)


def pack_catalog(runtime_config, *, legacy_map=None, legacy_transitions=None):
    runtime_config = dict(runtime_config or {})
    packs = discover_packs(
        default_avatar_id=str(runtime_config.get("musetalk_avatar_id", "default_avatar") or "default_avatar"),
        legacy_map=dict(legacy_map or {}),
        legacy_transitions=dict(legacy_transitions or {}),
        include_legacy=False,
        include_standalone=False,
    )
    catalog = []
    for pack_id, pack in packs.items():
        catalog.append(
            {
                "id": pack_id,
                "display_name": str(pack.display_name or pack_id),
                "default_avatar_id": str(pack.default_avatar_id or "default_avatar"),
                "default_variant": str(pack.default_variant or "default"),
                "source": str(pack.source or "manifest"),
                "variant_count": len(pack.variants or {}),
            }
        )
    return catalog


def available_pack_emotion_names(runtime_config, *, default_names, avatar_profile=None, legacy_map=None, legacy_transitions=None, avatars_dir=None):
    runtime_config = dict(runtime_config or {})
    names = set(default_names or set())
    try:
        names.update(str(key or "").strip().lower() for key in dict(avatar_profile or {}).keys() if str(key or "").strip())
    except Exception:
        pass
    packs = discover_packs(
        default_avatar_id=str(runtime_config.get("musetalk_avatar_id", "default_avatar") or "default_avatar"),
        legacy_map=dict(legacy_map or {}),
        legacy_transitions=dict(legacy_transitions or {}),
        avatars_dir=Path(avatars_dir) if avatars_dir is not None else None,
        include_legacy=False,
        include_standalone=False,
    )
    selected_pack_id = str(runtime_config.get("musetalk_avatar_pack_id", "") or "").strip()
    pack_iterable = [packs[selected_pack_id]] if selected_pack_id in packs else list(packs.values())
    for pack in pack_iterable:
        try:
            full_map = pack.emotion_avatar_map()
            enabled_tags = enabled_pack_emotions(runtime_config, pack.pack_id)
            if enabled_tags is None:
                names.update(
                    str(tag or "").strip().lower()
                    for tag in full_map.keys()
                    if str(tag or "").strip()
                )
            else:
                locked_tags = {
                    str(tag or "").strip().lower()
                    for tag, avatar_id in full_map.items()
                    if str(tag or "").strip()
                    and str(avatar_id or "").strip() == str(pack.default_avatar_id or "").strip()
                }
                names.update(
                    str(tag or "").strip().lower()
                    for tag in full_map.keys()
                    if str(tag or "").strip().lower() in enabled_tags or str(tag or "").strip().lower() in locked_tags
                )
        except Exception:
            continue
    return names


def select_pack(runtime_config, requested_pack_id, *, legacy_map=None, legacy_transitions=None):
    requested_pack_id = str(requested_pack_id or "").strip()
    if not requested_pack_id:
        return str(dict(runtime_config or {}).get("musetalk_avatar_pack_id", "") or "").strip()
    selected = get_pack(
        default_avatar_id=str(dict(runtime_config or {}).get("musetalk_avatar_id", "default_avatar") or "default_avatar"),
        requested_pack_id=requested_pack_id,
        legacy_map=dict(legacy_map or {}),
        legacy_transitions=dict(legacy_transitions or {}),
        include_legacy=False,
        include_standalone=False,
    )
    return selected.pack_id
