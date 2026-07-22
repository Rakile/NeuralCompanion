import type { AudioChunk, AudioState, RemoteState } from '../api/types';

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

export function mergeAudioSnapshot(state: RemoteState | null, payload: unknown): RemoteState | null {
  if (!state || !isAudioState(payload)) {
    return state;
  }
  return {
    ...state,
    media: payload,
  };
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
