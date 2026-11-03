import type { PresenceActivity, PresenceAvatar, PresenceState, RemoteState } from '../api/types.ts';

export type PresenceMoodPalette = {
  accent: string;
  glow: string;
  muted: string;
};

const MOOD_PALETTES: Record<string, PresenceMoodPalette> = {
  neutral: { accent: '#64d9ff', glow: '#1f8fbc', muted: '#18384a' },
  happy: { accent: '#65f2c2', glow: '#21aa84', muted: '#19493e' },
  calm: { accent: '#79c8ff', glow: '#4c83d8', muted: '#1d3655' },
  curious: { accent: '#b99cff', glow: '#7658d6', muted: '#352855' },
  excited: { accent: '#ffbf69', glow: '#e67242', muted: '#573221' },
  sad: { accent: '#7ea6e8', glow: '#536eaa', muted: '#24324e' },
  angry: { accent: '#ff7373', glow: '#cd3f55', muted: '#56242e' },
  fear: { accent: '#c69cff', glow: '#815fc4', muted: '#3d2c52' },
  focus: { accent: '#9cf7ff', glow: '#3bb7c4', muted: '#23464b' },
};

export function presenceMoodPalette(mood: unknown): PresenceMoodPalette {
  const key = String(mood || '').trim().toLowerCase();
  return MOOD_PALETTES[key] ?? MOOD_PALETTES.neutral!;
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function textValue(value: unknown, fallback = ''): string {
  const text = typeof value === 'string' ? value.trim() : '';
  return text || fallback;
}

function optionalText(value: unknown): string | undefined {
  const text = textValue(value);
  return text || undefined;
}

function finiteNumber(value: unknown, fallback = 0): number {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

export function normalizePresenceState(value: unknown): PresenceState | null {
  const presence = recordValue(value);
  const streamId = textValue(presence.stream_id);
  const revision = Number(presence.revision);
  if (presence.schema_version !== 1 || !streamId || !Number.isInteger(revision) || revision < 0) {
    return null;
  }

  const mood = textValue(presence.mood, 'neutral').toLowerCase();
  const activity = normalizePresenceActivity(presence.activity);
  const personaValue = recordValue(presence.persona);
  const personaName = textValue(personaValue.name, 'Companion');
  const personaInitials = textValue(
    personaValue.initials,
    personaName.split(/\s+/).map((part) => part[0] || '').join('').slice(0, 2).toUpperCase() || 'NC',
  );
  const avatarValue = recordValue(presence.avatar);
  const avatarKindValue = textValue(avatarValue.kind, 'initials');
  const avatarKind: PresenceAvatar['kind'] = ['musetalk', 'mood', 'neutral', 'initials'].includes(avatarKindValue)
    ? avatarKindValue as PresenceAvatar['kind']
    : 'initials';
  const musetalkValue = recordValue(presence.musetalk);
  const portraitValue = recordValue(presence.portrait_playback);
  const portraitMessageId = textValue(portraitValue.message_id);
  const portraitMood = textValue(portraitValue.mood).toLowerCase();
  const portraitPlayback = /^[A-Za-z0-9_.:-]{1,120}$/.test(portraitMessageId)
    && /^[a-z][a-z0-9_-]{0,31}$/.test(portraitMood)
    ? { message_id: portraitMessageId, portrait_key: textValue(portraitValue.portrait_key), mood: portraitMood }
    : undefined;

  return {
    schema_version: 1,
    stream_id: streamId,
    revision,
    updated_at: finiteNumber(presence.updated_at),
    activity,
    state_label: textValue(
      presence.state_label,
      activity === 'ready' ? 'Ready' : `${activity.charAt(0).toUpperCase()}${activity.slice(1)}`,
    ),
    audio_level: Math.max(0, Math.min(1, finiteNumber(presence.audio_level))),
    mood,
    persona: {
      id: textValue(personaValue.id),
      name: personaName,
      initials: personaInitials.slice(0, 2).toUpperCase(),
    },
    avatar: {
      kind: avatarKind,
      mood: textValue(avatarValue.mood, mood),
      url_path: optionalText(avatarValue.url_path),
      mood_url_path: optionalText(avatarValue.mood_url_path),
      neutral_url_path: optionalText(avatarValue.neutral_url_path),
      content_type: optionalText(avatarValue.content_type),
    },
    musetalk: {
      available: musetalkValue.available === true,
      healthy: musetalkValue.healthy === true,
    },
    ...(portraitPlayback ? { portrait_playback: portraitPlayback } : {}),
  };
}

export function mergePresenceValue(
  current: PresenceState | null | undefined,
  incoming: PresenceState,
): PresenceState {
  if (!current || current.stream_id !== incoming.stream_id) {
    return incoming;
  }
  return incoming.revision > current.revision ? incoming : current;
}

export function mergePresenceSnapshot(
  state: RemoteState | null,
  payload: unknown,
): RemoteState | null {
  const normalized = normalizePresenceState(payload);
  if (!normalized) {
    return state;
  }
  if (!state) {
    return { presence: normalized };
  }
  const presence = mergePresenceValue(normalizePresenceState(state.presence), normalized);
  return presence === state.presence ? state : { ...state, presence };
}

export function mergeRemotePresence(
  current: RemoteState | null,
  incoming: RemoteState,
): RemoteState {
  const incomingPresence = normalizePresenceState(incoming.presence);
  const currentPresence = normalizePresenceState(current?.presence);
  const safeIncoming = incomingPresence
    ? { ...incoming, presence: incomingPresence }
    : { ...incoming, presence: undefined };
  if (!currentPresence) {
    return safeIncoming;
  }
  if (!incomingPresence) {
    return { ...incoming, presence: currentPresence };
  }
  const presence = mergePresenceValue(currentPresence, incomingPresence);
  return presence === incomingPresence ? safeIncoming : { ...incoming, presence };
}

export type AvatarFallback = 'musetalk' | 'mood' | 'neutral' | 'initials';

export function avatarFallbackOrder(presence: PresenceState | null | undefined): AvatarFallback[] {
  if (!presence) {
    return ['initials'];
  }
  const order: AvatarFallback[] = [];
  if (presence.musetalk?.healthy) {
    order.push('musetalk');
  }
  if (presence.avatar?.mood_url_path || (presence.avatar?.kind === 'mood' && presence.avatar.url_path)) {
    order.push('mood');
  }
  if (presence.avatar?.neutral_url_path || (presence.avatar?.kind === 'neutral' && presence.avatar.url_path)) {
    order.push('neutral');
  }
  order.push('initials');
  return order;
}

export function normalizePresenceActivity(value: unknown): PresenceActivity {
  const activity = String(value || '').trim().toLowerCase();
  return ['stopped', 'ready', 'listening', 'thinking', 'speaking', 'failure'].includes(activity)
    ? activity as PresenceActivity
    : 'ready';
}

export type VoiceThreadPolicy = {
  motion: 'breathe' | 'inward' | 'travel' | 'spectrum' | 'still';
  palette: 'mood' | 'listening' | 'thinking' | 'failure';
};

export function threadState(activity: PresenceActivity, _mood: string): VoiceThreadPolicy {
  if (activity === 'listening') {
    return { motion: 'inward', palette: 'listening' };
  }
  if (activity === 'thinking') {
    return { motion: 'travel', palette: 'thinking' };
  }
  if (activity === 'speaking') {
    return { motion: 'spectrum', palette: 'mood' };
  }
  if (activity === 'failure' || activity === 'stopped') {
    return { motion: 'still', palette: 'failure' };
  }
  return { motion: 'breathe', palette: 'mood' };
}
