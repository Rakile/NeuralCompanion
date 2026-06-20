import { useCallback, useEffect, useRef, useState } from 'react';
import { createAudioPlayer, setAudioModeAsync } from 'expo-audio';

import { RemoteClient } from '../api/client';
import type { AudioChunk } from '../api/types';

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

type AudioPlayerHandle = {
  play: () => void;
  pause?: () => void;
  release?: () => void;
  volume?: number;
  addListener?: (
    event: string,
    listener: (status: { didJustFinish?: boolean; error?: string }) => void,
  ) => { remove?: () => void } | undefined;
};

function normalizeVolume(value: number | undefined): number {
  const parsed = Number(value ?? 1);
  if (!Number.isFinite(parsed)) {
    return 1;
  }
  return Math.max(0, Math.min(1, parsed));
}

export function useAudioQueue(client: RemoteClient, chunks: AudioChunk[], options: AudioQueueOptions = {}): PlaybackState {
  const [enabled, setEnabledState] = useState(options.autoplayEnabled ?? true);
  const [playingId, setPlayingId] = useState('');
  const [playedCount, setPlayedCount] = useState(0);
  const [error, setError] = useState('');
  const volume = normalizeVolume(options.volume);
  const played = useRef<Set<string>>(new Set());
  const autoplaySeen = useRef<Set<string>>(new Set());
  const active = useRef<{
    id: string;
    player: AudioPlayerHandle;
    subscription?: { remove?: () => void };
    fallbackTimer?: ReturnType<typeof setTimeout>;
  } | null>(null);

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
  }, [volume]);

  const setEnabled = useCallback((nextEnabled: boolean) => {
    setEnabledState(Boolean(nextEnabled));
    options.onAutoplayEnabledChange?.(Boolean(nextEnabled));
  }, [options]);

  const releaseActive = useCallback((clearPlaying = true) => {
    const current = active.current;
    active.current = null;
    if (current?.fallbackTimer) {
      clearTimeout(current.fallbackTimer);
    }
    current?.subscription?.remove?.();
    current?.player.pause?.();
    current?.player.release?.();
    if (clearPlaying) {
      setPlayingId('');
    }
  }, []);

  useEffect(() => () => releaseActive(false), [releaseActive]);

  useEffect(() => {
    releaseActive(true);
    played.current.clear();
    autoplaySeen.current.clear();
    setPlayedCount(0);
    setError('');
  }, [client.baseUrl, client.pairingCode, releaseActive]);

  useEffect(() => {
    if (chunks.length) {
      return;
    }
    releaseActive(true);
    played.current.clear();
    autoplaySeen.current.clear();
    setPlayedCount(0);
    setError('');
  }, [chunks.length, releaseActive]);

  const playNow = useCallback(async (chunk: AudioChunk) => {
    if (!chunk.id) {
      return;
    }
    const url = client.authorizedUrl(chunk.url_path);
    releaseActive(false);
    setPlayingId(chunk.id);
    setError('');
    try {
      const player = createAudioPlayer(url, { updateInterval: 250 }) as AudioPlayerHandle;
      player.volume = volume;
      let subscription: { remove?: () => void } | undefined;
      subscription = player.addListener?.('playbackStatusUpdate', (status: { didJustFinish?: boolean; error?: string }) => {
        if (active.current?.id !== chunk.id) {
          return;
        }
        if (status.didJustFinish || status.error) {
          if (status.error) {
            setError(status.error);
          }
          releaseActive(true);
        }
      });
      let fallbackTimer: ReturnType<typeof setTimeout> | undefined;
      const durationMs = Math.max(0, Number(chunk.duration_seconds || 0) * 1000);
      const fallbackMs = durationMs > 0
        ? Math.min(MAX_PLAYBACK_FALLBACK_MS, durationMs + PLAYBACK_FALLBACK_GRACE_MS)
        : UNKNOWN_DURATION_PLAYBACK_TIMEOUT_MS;
      fallbackTimer = setTimeout(() => {
        if (active.current?.id === chunk.id) {
          releaseActive(true);
        }
      }, fallbackMs);
      active.current = { id: chunk.id, player };
      if (subscription) {
        active.current.subscription = subscription;
      }
      if (fallbackTimer) {
        active.current.fallbackTimer = fallbackTimer;
      }
      player.play();
      autoplaySeen.current.add(chunk.id);
      played.current.add(chunk.id);
      setPlayedCount(played.current.size);
    } catch (exc) {
      releaseActive(true);
      setError(exc instanceof Error ? exc.message : 'Audio playback failed.');
    }
  }, [client, releaseActive, volume]);

  useEffect(() => {
    if (!chunks.length) {
      return;
    }
    if (!enabled) {
      for (const item of chunks) {
        if (item.id) {
          autoplaySeen.current.add(item.id);
        }
      }
      return;
    }
    if (playingId) {
      return;
    }
    const next = chunks.find((item) => item.id && !autoplaySeen.current.has(item.id));
    if (next) {
      autoplaySeen.current.add(next.id);
      playNow(next).catch(() => undefined);
    }
  }, [chunks, enabled, playNow, playingId]);

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
      setError('');
    },
    reset: () => {
      releaseActive(true);
      played.current.clear();
      autoplaySeen.current.clear();
      setPlayedCount(0);
      setError('');
    },
  };
}
