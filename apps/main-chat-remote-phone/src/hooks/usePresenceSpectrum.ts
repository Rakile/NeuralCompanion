import React from 'react';

import type { RemoteClient } from '../api/client';
import type { PresenceActivity } from '../api/types';
import type { PlaybackState } from './useAudioQueue';
import { useSpectrumPlayback } from './useSpectrumPlayback';
import { normalizeMicLevel, SPECTRUM_BARS } from '../utils/liveFullscreenSpectrum';

export type VoiceThreadFrame = {
  enabled?: boolean;
  fps?: number;
  energies: readonly number[];
  inputLevel: number;
  frameTimeMs: number;
  source: 'analyzed' | 'live' | 'procedural';
};

const EMPTY_ENERGIES = Array(SPECTRUM_BARS).fill(0);

export function usePresenceSpectrum(
  client: RemoteClient,
  playback: PlaybackState,
  activity: PresenceActivity,
  meteringDb: number | null | undefined,
  meteringRevision: number,
  enabled: boolean,
  reducedMotion = false,
  fps = 24,
): VoiceThreadFrame {
  const speaking = enabled && activity === 'speaking';
  const clockActive = enabled && !reducedMotion && activity !== 'ready';
  const spectrum = useSpectrumPlayback(client, playback, 64, fps, enabled && !reducedMotion, clockActive);
  const inputLevel = React.useMemo(
    () => activity === 'listening' ? normalizeMicLevel(meteringDb) : 0,
    [activity, meteringDb, meteringRevision],
  );
  if (speaking) {
    return {
      enabled, fps,
      energies: spectrum.energies,
      inputLevel: 0,
      frameTimeMs: spectrum.frameTimeMs,
      source: spectrum.source === 'analyzed' ? 'analyzed' : spectrum.source === 'live' ? 'live' : 'procedural',
    };
  }
  return {
    enabled, fps,
    energies: EMPTY_ENERGIES,
    inputLevel,
    frameTimeMs: spectrum.frameTimeMs,
    source: activity === 'listening' ? 'live' : 'procedural',
  };
}
