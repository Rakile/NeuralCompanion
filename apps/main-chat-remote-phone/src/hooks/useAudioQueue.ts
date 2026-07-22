import { useCallback, useEffect, useRef, useState } from 'react';
import { createAudioPlayer, setAudioModeAsync } from 'expo-audio';

import { RemoteClient } from '../api/client';
import type { AudioChunk } from '../api/types';
import { nextUnseenAudioChunk } from '../utils/audioFastStart';
import { recordPhoneDebug } from '../utils/phoneDebugBridge';

const PLAYBACK_STATUS_INTERVAL_MS = 100;
const PLAYBACK_FALLBACK_GRACE_MS = 1500;
const UNKNOWN_DURATION_PLAYBACK_TIMEOUT_MS = 2 * 60 * 1000;
const MAX_PLAYBACK_FALLBACK_MS = 10 * 60 * 1000;

export type PlaybackState = {
  enabled: boolean;
  volume: number;
  playingId: string;
  playedCount: number;
  error: string;
  setEnabled: (enabled: boolean) => void;
  playNow: (chunk: AudioChunk) => Promise<void>;
  stop: () => void;
  reset: () => void;
};

type AudioQueueOptions = {
  autoplayEnabled?: boolean;
  volume?: number;
  onAutoplayEnabledChange?: (enabled: boolean) => void;
};

type AudioStatus = {
  didJustFinish?: boolean;
  error?: string;
  isLoaded?: boolean;
  playing?: boolean;
};

type AudioPlayerHandle = {
  play: () => void;
  pause?: () => void;
  release?: () => void;
  remove?: () => void;
  volume?: number;
  addListener?: (
    event: string,
    listener: (status: AudioStatus) => void,
  ) => { remove?: () => void } | undefined;
};

type PlayerSlot = {
  id: string;
  chunk: AudioChunk;
  player: AudioPlayerHandle;
  createdAtMs: number;
  subscription?: { remove?: () => void };
  fallbackTimer?: ReturnType<typeof setTimeout>;
  playbackStartedLogged?: boolean;
  preparedLogged?: boolean;
};

function normalizeVolume(value: number | undefined): number {
  const parsed = Number(value ?? 1);
  if (!Number.isFinite(parsed)) {
    return 1;
  }
  return Math.max(0, Math.min(1, parsed));
}

function releasePlayer(player: AudioPlayerHandle | undefined): void {
  if (!player) {
    return;
  }
  player.pause?.();
  if (player.release) {
    player.release();
  } else {
    player.remove?.();
  }
}

function timingDetails(chunk: AudioChunk, eventAtMs: number): Record<string, number | string> {
  const backendCreatedAtMs = Math.max(0, Number(chunk.created_at || 0) * 1000);
  return {
    chunk_id: String(chunk.id || ''),
    sequence_index: Number(chunk.sequence_index ?? chunk.index ?? 0),
    backend_created_at_ms: Math.round(backendCreatedAtMs),
    backend_to_event_ms: backendCreatedAtMs > 0 ? Math.max(0, Math.round(eventAtMs - backendCreatedAtMs)) : 0,
  };
}

export function useAudioQueue(client: RemoteClient, chunks: AudioChunk[], options: AudioQueueOptions = {}): PlaybackState {
  const [enabled, setEnabledState] = useState(options.autoplayEnabled ?? true);
  const [playingId, setPlayingId] = useState('');
  const [playedCount, setPlayedCount] = useState(0);
  const [error, setError] = useState('');
  const volume = normalizeVolume(options.volume);
  const played = useRef<Set<string>>(new Set());
  const autoplaySeen = useRef<Set<string>>(new Set());
  const active = useRef<PlayerSlot | null>(null);
  const prepared = useRef<PlayerSlot | null>(null);
  const chunksRef = useRef<AudioChunk[]>(chunks);
  const enabledRef = useRef(enabled);
  const volumeRef = useRef(volume);
  const playNextRef = useRef<() => void>(() => undefined);
  const prepareNextRef = useRef<() => void>(() => undefined);

  chunksRef.current = chunks;
  enabledRef.current = enabled;
  volumeRef.current = volume;

  useEffect(() => {
    setAudioModeAsync({ playsInSilentMode: true }).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (typeof options.autoplayEnabled === 'boolean') {
      setEnabledState(options.autoplayEnabled);
    }
  }, [options.autoplayEnabled]);

  useEffect(() => {
    if (active.current?.player) {
      active.current.player.volume = volume;
    }
    if (prepared.current?.player) {
      prepared.current.player.volume = volume;
    }
  }, [volume]);

  const setEnabled = useCallback((nextEnabled: boolean) => {
    setEnabledState(Boolean(nextEnabled));
    options.onAutoplayEnabledChange?.(Boolean(nextEnabled));
  }, [options.onAutoplayEnabledChange]);

  const releaseActive = useCallback((clearPlaying = true) => {
    const current = active.current;
    active.current = null;
    if (current?.fallbackTimer) {
      clearTimeout(current.fallbackTimer);
    }
    current?.subscription?.remove?.();
    releasePlayer(current?.player);
    if (clearPlaying) {
      setPlayingId('');
    }
  }, []);

  const releasePrepared = useCallback(() => {
    const current = prepared.current;
    prepared.current = null;
    current?.subscription?.remove?.();
    releasePlayer(current?.player);
  }, []);

  const activateChunk = useCallback(async (chunk: AudioChunk, preparedSlot?: PlayerSlot | null) => {
    const chunkId = String(chunk.id || '').trim();
    if (!chunkId) {
      return;
    }
    releaseActive(false);
    let player: AudioPlayerHandle;
    let createdAtMs = Date.now();
    let usedPreparedPlayer = false;
    if (preparedSlot && prepared.current === preparedSlot && preparedSlot.id === chunkId) {
      prepared.current = null;
      preparedSlot.subscription?.remove?.();
      preparedSlot.subscription = undefined;
      player = preparedSlot.player;
      createdAtMs = preparedSlot.createdAtMs;
      usedPreparedPlayer = true;
    } else {
      releasePrepared();
      const url = client.authorizedUrl(chunk.url_path);
      player = createAudioPlayer(url, { updateInterval: PLAYBACK_STATUS_INTERVAL_MS }) as AudioPlayerHandle;
      createdAtMs = Date.now();
      void recordPhoneDebug('info', 'audio_player_created', {
        ...timingDetails(chunk, createdAtMs),
        prepared: false,
      });
    }

    setPlayingId(chunkId);
    setError('');
    try {
      player.volume = volumeRef.current;
      const slot: PlayerSlot = {
        id: chunkId,
        chunk,
        player,
        createdAtMs,
      };
      active.current = slot;
      slot.subscription = player.addListener?.('playbackStatusUpdate', (status: AudioStatus) => {
        const current = active.current;
        if (!current || current.id !== chunkId || current.player !== player) {
          return;
        }
        if (status.playing && !current.playbackStartedLogged) {
          current.playbackStartedLogged = true;
          const startedAtMs = Date.now();
          void recordPhoneDebug('info', 'audio_playback_started', {
            ...timingDetails(chunk, startedAtMs),
            player_create_to_start_ms: Math.max(0, startedAtMs - createdAtMs),
            prepared: usedPreparedPlayer,
          });
        }
        if (!status.didJustFinish && !status.error) {
          return;
        }
        const finishedAtMs = Date.now();
        if (status.error) {
          setError(status.error);
          void recordPhoneDebug('error', 'audio_playback_failed', {
            ...timingDetails(chunk, finishedAtMs),
            error: status.error,
            prepared: usedPreparedPlayer,
          });
        } else {
          void recordPhoneDebug('info', 'audio_playback_finished', {
            ...timingDetails(chunk, finishedAtMs),
            prepared: usedPreparedPlayer,
          });
        }
        releaseActive(true);
        setTimeout(() => playNextRef.current(), 0);
      });
      const durationMs = Math.max(0, Number(chunk.duration_seconds || 0) * 1000);
      const fallbackMs = durationMs > 0
        ? Math.min(MAX_PLAYBACK_FALLBACK_MS, durationMs + PLAYBACK_FALLBACK_GRACE_MS)
        : UNKNOWN_DURATION_PLAYBACK_TIMEOUT_MS;
      slot.fallbackTimer = setTimeout(() => {
        if (active.current?.id !== chunkId) {
          return;
        }
        const timedOutAtMs = Date.now();
        void recordPhoneDebug('error', 'audio_playback_failed', {
          ...timingDetails(chunk, timedOutAtMs),
          error: 'playback completion timeout',
          prepared: usedPreparedPlayer,
        });
        releaseActive(true);
        setTimeout(() => playNextRef.current(), 0);
      }, fallbackMs);
      player.play();
      autoplaySeen.current.add(chunkId);
      played.current.add(chunkId);
      setPlayedCount(played.current.size);
      prepareNextRef.current();
    } catch (exc) {
      releaseActive(true);
      const message = exc instanceof Error ? exc.message : 'Audio playback failed.';
      setError(message);
      void recordPhoneDebug('error', 'audio_playback_failed', {
        ...timingDetails(chunk, Date.now()),
        error: message,
        prepared: usedPreparedPlayer,
      });
      setTimeout(() => playNextRef.current(), 0);
    }
  }, [client, releaseActive, releasePrepared]);

  const prepareNext = useCallback(() => {
    const current = active.current;
    if (!enabledRef.current || !current) {
      releasePrepared();
      return;
    }
    const next = nextUnseenAudioChunk(chunksRef.current, autoplaySeen.current, current.id);
    if (!next) {
      releasePrepared();
      return;
    }
    if (prepared.current?.id === next.id) {
      return;
    }
    releasePrepared();
    try {
      const createdAtMs = Date.now();
      const player = createAudioPlayer(client.authorizedUrl(next.url_path), {
        updateInterval: PLAYBACK_STATUS_INTERVAL_MS,
        downloadFirst: true,
      }) as AudioPlayerHandle;
      player.volume = volumeRef.current;
      const slot: PlayerSlot = {
        id: next.id,
        chunk: next,
        player,
        createdAtMs,
      };
      prepared.current = slot;
      void recordPhoneDebug('info', 'audio_player_created', {
        ...timingDetails(next, createdAtMs),
        prepared: true,
      });
      slot.subscription = player.addListener?.('playbackStatusUpdate', (status: AudioStatus) => {
        const currentPrepared = prepared.current;
        if (!currentPrepared || currentPrepared.id !== next.id || currentPrepared.player !== player) {
          return;
        }
        if (status.isLoaded && !currentPrepared.preparedLogged) {
          currentPrepared.preparedLogged = true;
          const preparedAtMs = Date.now();
          void recordPhoneDebug('info', 'audio_player_prepared', {
            ...timingDetails(next, preparedAtMs),
            prepare_ms: Math.max(0, preparedAtMs - createdAtMs),
          });
        }
        if (status.error) {
          void recordPhoneDebug('error', 'audio_playback_failed', {
            ...timingDetails(next, Date.now()),
            error: status.error,
            phase: 'prepare',
          });
          releasePrepared();
        }
      });
    } catch (exc) {
      releasePrepared();
      void recordPhoneDebug('error', 'audio_playback_failed', {
        ...timingDetails(next, Date.now()),
        error: exc instanceof Error ? exc.message : 'Audio preparation failed.',
        phase: 'prepare',
      });
    }
  }, [client, releasePrepared]);

  const playNext = useCallback(() => {
    if (!enabledRef.current || active.current) {
      return;
    }
    const preparedSlot = prepared.current;
    if (
      preparedSlot
      && !autoplaySeen.current.has(preparedSlot.id)
      && chunksRef.current.some((chunk) => chunk.id === preparedSlot.id)
    ) {
      void activateChunk(preparedSlot.chunk, preparedSlot);
      return;
    }
    if (preparedSlot) {
      releasePrepared();
    }
    const next = nextUnseenAudioChunk(chunksRef.current, autoplaySeen.current);
    if (next) {
      void activateChunk(next);
    }
  }, [activateChunk, releasePrepared]);

  playNextRef.current = playNext;
  prepareNextRef.current = prepareNext;

  const playNow = useCallback(async (chunk: AudioChunk) => {
    const preparedSlot = prepared.current?.id === chunk.id ? prepared.current : null;
    await activateChunk(chunk, preparedSlot);
  }, [activateChunk]);

  useEffect(() => () => {
    releaseActive(false);
    releasePrepared();
  }, [releaseActive, releasePrepared]);

  useEffect(() => {
    releaseActive(true);
    releasePrepared();
    played.current.clear();
    autoplaySeen.current.clear();
    setPlayedCount(0);
    setError('');
  }, [client.baseUrl, client.pairingCode, releaseActive, releasePrepared]);

  useEffect(() => {
    if (!chunks.length) {
      releaseActive(true);
      releasePrepared();
      played.current.clear();
      autoplaySeen.current.clear();
      setPlayedCount(0);
      setError('');
      return;
    }
    const validIds = new Set(chunks.map((chunk) => chunk.id).filter(Boolean));
    if (active.current && !validIds.has(active.current.id)) {
      releaseActive(true);
    }
    if (prepared.current && !validIds.has(prepared.current.id)) {
      releasePrepared();
    }
    if (!enabled) {
      releasePrepared();
      for (const item of chunks) {
        if (item.id) {
          autoplaySeen.current.add(item.id);
        }
      }
      return;
    }
    if (active.current) {
      prepareNextRef.current();
    } else {
      playNextRef.current();
    }
  }, [chunks, enabled, releaseActive, releasePrepared]);

  return {
    enabled,
    volume,
    playingId,
    playedCount,
    error,
    setEnabled,
    playNow,
    stop: () => {
      releaseActive(true);
      releasePrepared();
      setError('');
    },
    reset: () => {
      releaseActive(true);
      releasePrepared();
      played.current.clear();
      autoplaySeen.current.clear();
      setPlayedCount(0);
      setError('');
    },
  };
}
