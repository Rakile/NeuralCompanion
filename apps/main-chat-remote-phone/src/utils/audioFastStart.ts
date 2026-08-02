import type { AudioChunk, AudioState, RemoteState } from '../api/types';

export type AudioHistoryBoundary = 'empty_snapshot' | 'connection_changed' | 'explicit_reset';

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function isAudioChunk(value: unknown): value is AudioChunk {
  if (!isRecord(value)) {
    return false;
  }
  return typeof value.id === 'string'
    && Boolean(value.id.trim())
    && typeof value.url_path === 'string'
    && Boolean(value.url_path.trim());
}

function isAudioState(value: unknown): value is AudioState {
  if (!isRecord(value)) {
    return false;
  }
  if (!('items' in value)) {
    return true;
  }
  return Array.isArray(value.items) && value.items.every(isAudioChunk);
}

function positiveGeneration(audio: AudioState | undefined): number {
  const parsed = Number(audio?.generation || 0);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
}

export function shouldAcceptAudioSnapshot(
  current: AudioState | undefined,
  incoming: AudioState,
): boolean {
  const currentGeneration = positiveGeneration(current);
  const incomingGeneration = positiveGeneration(incoming);
  return currentGeneration === 0
    || incomingGeneration === 0
    || incomingGeneration >= currentGeneration;
}

export function mergeRemoteSnapshot(
  current: RemoteState | null,
  incoming: RemoteState,
): RemoteState {
  if (
    current?.media
    && incoming.media
    && !shouldAcceptAudioSnapshot(current.media, incoming.media)
  ) {
    return { ...incoming, media: current.media };
  }
  return incoming;
}

export function mergeAudioSnapshot(state: RemoteState | null, payload: unknown): RemoteState | null {
  if (!state || !isAudioState(payload)) {
    return state;
  }
  if (!shouldAcceptAudioSnapshot(state.media, payload)) {
    return state;
  }
  return {
    ...state,
    media: payload,
  };
}

export function audioHistoryAfterBoundary(
  seenIds: ReadonlySet<string>,
  boundary: AudioHistoryBoundary,
): Set<string> {
  return boundary === 'empty_snapshot' ? new Set(seenIds) : new Set();
}

export function nextUnseenAudioChunk(
  chunks: AudioChunk[],
  seenIds: ReadonlySet<string>,
  excludedId = '',
): AudioChunk | undefined {
  return chunks.find((chunk) => {
    const id = String(chunk.id || '').trim();
    return Boolean(id) && id !== excludedId && !seenIds.has(id);
  });
}

export function refreshAudioChunkMetadata(
  current: AudioChunk | null,
  chunks: AudioChunk[],
): AudioChunk | null {
  if (!current) {
    return null;
  }
  return chunks.find((chunk) => String(chunk.id || '') === String(current.id || ''))
    ?? current;
}

export function shouldInterruptForPhoneText(
  activity: string,
  playingId: string,
): boolean {
  return Boolean(String(playingId || '').trim())
    || ['speaking', 'thinking'].includes(String(activity || '').trim().toLowerCase());
}

export function createLatestAudioSampleBuffer(): {
  get: () => readonly number[] | null;
  set: (sample: readonly number[] | null) => void;
} {
  let current: readonly number[] | null = null;
  return {
    get: () => current,
    set: (sample) => {
      current = sample;
    },
  };
}
