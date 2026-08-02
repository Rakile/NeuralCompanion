import React from 'react';

import type { RemoteClient } from '../api/client';
import type { AudioChunk } from '../api/types';
import type { PlaybackState } from './useAudioQueue';
import {
  playbackSpectrumFrame,
  smoothSpectrum,
  SPECTRUM_BARS,
  shouldPublishSpectrumFrame,
  spectrumFrameIntervalMs,
} from '../utils/liveFullscreenSpectrum';
import type { SpectrumSource, SpectrumTimeline } from '../utils/liveFullscreenSpectrum';
import { decodeSpectrumTimeline } from '../utils/liveFullscreenSpectrum';

export type SpectrumFrameState = {
  energies: number[];
  source: SpectrumSource;
  frameTimeMs: number;
};

const EMPTY_FRAME = Array(SPECTRUM_BARS).fill(0);
const MAX_TIMELINES = 8;

function readySpectrumPath(chunk: AudioChunk | null): string {
  return chunk?.spectrum_status === 'ready' ? String(chunk.spectrum_url_path || '') : '';
}

export function useSpectrumPlayback(
  client: RemoteClient,
  playback: PlaybackState,
  smoothingPct: number,
  fps: number,
  visible: boolean,
  clockActive: boolean,
): SpectrumFrameState {
  const timelinesRef = React.useRef<Map<string, SpectrumTimeline>>(new Map());
  const loadingRef = React.useRef<Set<string>>(new Set());
  const smoothedRef = React.useRef<number[]>(EMPTY_FRAME);
  const positionRef = React.useRef({ seconds: 0, updatedAt: Date.now() });
  const activeChunkIdRef = React.useRef('');
  const playbackRef = React.useRef(playback);
  const smoothingPctRef = React.useRef(smoothingPct);
  const fpsRef = React.useRef(fps);
  const clockActiveRef = React.useRef(clockActive);
  const lastPublishedAtRef = React.useRef(0);
  const animationStartedAtRef = React.useRef(Date.now());
  const stateRef = React.useRef<SpectrumFrameState>({
    energies: EMPTY_FRAME,
    source: 'idle',
    frameTimeMs: 0,
  });
  const [state, setState] = React.useState<SpectrumFrameState>(stateRef.current);

  playbackRef.current = playback;
  smoothingPctRef.current = smoothingPct;
  fpsRef.current = fps;
  clockActiveRef.current = clockActive;

  React.useEffect(() => {
    positionRef.current = {
      seconds: Math.max(0, playback.positionSeconds),
      updatedAt: Date.now(),
    };
  }, [playback.positionSeconds]);

  React.useEffect(() => {
    const candidates = [playback.currentChunk, playback.preparedChunk];
    for (const chunk of candidates) {
      const id = String(chunk?.id || '');
      const path = readySpectrumPath(chunk);
      if (!id || !path || timelinesRef.current.has(id) || loadingRef.current.has(id)) {
        continue;
      }
      loadingRef.current.add(id);
      client.audioSpectrum(path)
        .then((payload) => {
          timelinesRef.current.set(id, decodeSpectrumTimeline(payload));
          while (timelinesRef.current.size > MAX_TIMELINES) {
            const oldest = timelinesRef.current.keys().next().value;
            if (!oldest) {
              break;
            }
            timelinesRef.current.delete(oldest);
          }
        })
        .catch(() => undefined)
        .finally(() => {
          loadingRef.current.delete(id);
        });
    }
  }, [
    client,
    playback.currentChunk?.id,
    playback.currentChunk?.spectrum_status,
    playback.currentChunk?.spectrum_url_path,
    playback.preparedChunk?.id,
    playback.preparedChunk?.spectrum_status,
    playback.preparedChunk?.spectrum_url_path,
  ]);

  React.useEffect(() => {
    if (!visible) {
      return undefined;
    }
    animationStartedAtRef.current = Date.now();
    lastPublishedAtRef.current = 0;
    let frameHandle = 0;
    const draw = () => {
      const current = playbackRef.current;
      const chunkId = String(current.currentChunk?.id || '');
      if (activeChunkIdRef.current !== chunkId) {
        activeChunkIdRef.current = chunkId;
        smoothedRef.current = EMPTY_FRAME;
        positionRef.current = {
          seconds: Math.max(0, current.positionSeconds),
          updatedAt: Date.now(),
        };
      }
      const playbackActive = Boolean(current.isPlaying && current.currentChunk);
      if (!playbackActive && !clockActiveRef.current) {
        const idle = {
          energies: EMPTY_FRAME,
          source: 'idle' as const,
          frameTimeMs: 0,
        };
        if (stateRef.current.source !== 'idle' || stateRef.current.frameTimeMs !== 0) {
          stateRef.current = idle;
          setState(idle);
        }
        frameHandle = requestAnimationFrame(draw);
        return;
      }
      const now = Date.now();
      if (!shouldPublishSpectrumFrame(now, lastPublishedAtRef.current, fpsRef.current)) {
        frameHandle = requestAnimationFrame(draw);
        return;
      }
      const intervalMs = spectrumFrameIntervalMs(fpsRef.current);
      const frameElapsed = Math.max(0, now - lastPublishedAtRef.current);
      lastPublishedAtRef.current = now - (frameElapsed % intervalMs);
      const frameTimeMs = Math.max(0, now - animationStartedAtRef.current);
      if (!playbackActive || !current.currentChunk) {
        const idle = {
          energies: EMPTY_FRAME,
          source: 'idle' as const,
          frameTimeMs,
        };
        stateRef.current = idle;
        setState(idle);
        frameHandle = requestAnimationFrame(draw);
        return;
      }
      const timeline = timelinesRef.current.get(current.currentChunk.id);
      const elapsed = Math.max(0, now - positionRef.current.updatedAt) / 1000;
      const seconds = positionRef.current.seconds + elapsed;
      const frame = playbackSpectrumFrame(
        timeline,
        seconds,
        current.getLiveSample(),
        smoothedRef.current,
      );
      const energies = smoothSpectrum(
        smoothedRef.current,
        frame.energies,
        smoothingPctRef.current,
      );
      smoothedRef.current = energies;
      const next = { energies, source: frame.source, frameTimeMs };
      stateRef.current = next;
      setState(next);
      frameHandle = requestAnimationFrame(draw);
    };
    frameHandle = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frameHandle);
  }, [visible]);

  return state;
}
