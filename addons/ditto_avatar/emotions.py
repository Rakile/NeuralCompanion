"""Immutable per-chunk choices; safe to import in host or isolated GPU worker."""
from dataclasses import dataclass

NATIVE_EMOTIONS = ('Angry','Disgust','Fear','Happy','Neutral','Sad','Surprise','Contempt')


def native_emotion(value):
    clean = str(value or '').strip().strip('[]').strip().lower()
    if clean == 'surprised':
        clean = 'surprise'
    return next((name for name in NATIVE_EMOTIONS if name.lower() == clean), None)


@dataclass(frozen=True)
class ChunkChoice:
    variant_id: str
    avatar_path: str
    native_emotion: str
    settings: tuple

    def to_wire(self):
        return dict(variant_id=self.variant_id, avatar_path=self.avatar_path,
                    native_emotion=self.native_emotion, settings=dict(self.settings))

    @classmethod
    def from_wire(cls, value):
        target = native_emotion(value['native_emotion'])
        if target is None:
            raise ValueError('Unsupported native Ditto emotion.')
        settings = value['settings']
        if not isinstance(settings, dict) or any(type(v) not in (str, int, float, bool) for v in settings.values()):
            raise ValueError('Chunk render settings must be scalar values.')
        return cls(str(value['variant_id']), str(value['avatar_path']), target, tuple(sorted(settings.items())))


def bind_chunk_choice(config, pack, emotion_name, *, active_avatar_id, last_queued_avatar_id):
    try:
        from .config import avatar_tuning, package_tuning, render_settings
        from .packages import effective_emotion_avatar_map
    except ImportError:
        from config import avatar_tuning, package_tuning, render_settings
        from packages import effective_emotion_avatar_map
    from addons.musetalk_avatar.avatar_packs import resolve_emotion_avatar
    if pack is None:
        variant_id, path = '__standalone__', str(config.get('ditto_avatar_path') or '')
    else:
        variant = pack.variants.get(str(config.get('ditto_variant_id') or '')) or pack.default_variant_config
        if variant is None:
            raise ValueError('Prepare a default avatar for this package first.')
        if config.get('ditto_avatar_selection') == 'From reply emotion':
            avatar_id = resolve_emotion_avatar(emotion_name, effective_emotion_avatar_map(pack, config), pack.default_avatar_id)
            if avatar_id is None:
                avatar_id = active_avatar_id or last_queued_avatar_id or pack.default_avatar_id
            variant = pack.variant_for_avatar_id(avatar_id) or pack.default_variant_config
        variant_id, path = variant.variant_id, variant.avatar_path
    if pack is not None:
        config = dict(config)
        profile = pack.metadata.get('ditto_render_settings')
        if profile is not None:
            config.update(package_tuning(profile))
        profile = variant.metadata.get('ditto_render_settings')
        if profile is not None:
            config.update(avatar_tuning(profile, config))
    manual = native_emotion(config.get('ditto_emotion', 'Neutral')) or 'Neutral'
    target = manual
    if config.get('ditto_emotion_selection') == 'From reply emotion':
        tag = str(emotion_name or '').strip().strip('[]').strip().lower()
        mapping = pack.metadata.get('ditto_emotion_map', {}) if pack is not None else {}
        target = native_emotion(mapping.get(tag, tag)) or manual
    settings = render_settings(config)
    settings['emotion'] = target
    return ChunkChoice(variant_id, path, target, tuple(sorted(settings.items())))
