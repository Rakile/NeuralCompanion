import React from 'react';
import { Platform } from 'react-native';
import type { AudioPlayer } from 'expo-audio';

import {
  sampleToSpectrum,
  sampleToFrequencySpectrum,
  shouldPublishSpectrumFrame,
  SPECTRUM_FPS,
} from '../../utils/liveFullscreenSpectrum';

type Props = {
  player: AudioPlayer;
  fps?: number;
  frequencyBands?: boolean;
  onSample: (sample: readonly number[] | null) => void;
};

export function AudioSampleTap({ player, fps = SPECTRUM_FPS, frequencyBands = false, onSample }: Props) {
  // A design change must not detach/re-enable native sampling during playback.
  const frequencyBandsRef = React.useRef(frequencyBands);
  frequencyBandsRef.current = frequencyBands;
  React.useEffect(() => {
    let active = true;
    let samplingRequested = false;
    let lastPublishedAtMs = 0;
    let subscription: { remove: () => void } | undefined;
    const clearSample = () => {
      try { onSample(null); } catch { /* The visualization may already be detached. */ }
    };
    const dispose = () => {
      active = false;
      try { subscription?.remove(); } catch { /* The queue may have released the player. */ }
      subscription = undefined;
      if (samplingRequested) {
        samplingRequested = false;
        try { player.setAudioSamplingEnabled(false); } catch { /* Native sampler already released. */ }
      }
      clearSample();
    };

    clearSample();
    // On iOS, attaching PCM sampling changes AVPlayerItem.audioMix after speech
    // starts and caused per-chunk stalls in device tests. Use the existing
    // analyzed/procedural spectrum in every layout and build instead. Mounting
    // or unmounting the waveform must not reconfigure the speech audio player.
    // The track adapter reads a bounded native confirmed-output snapshot and
    // never installs AVPlayerItem.audioMix or changes the audio session.
    if (Platform.OS === 'ios' && (player as AudioPlayer & { ncAVPlayer?: boolean }).ncAVPlayer !== true) {
      return dispose;
    }
    try {
      if (!player.isAudioSamplingSupported) return dispose;
      samplingRequested = true;
      player.setAudioSamplingEnabled(true);
      subscription = player.addListener('audioSampleUpdate', (sample) => {
        if (!active) return;
        try {
          const nowMs = globalThis.performance?.now?.() ?? Date.now();
          if (!shouldPublishSpectrumFrame(nowMs, lastPublishedAtMs, fps)) return;
          lastPublishedAtMs = nowMs;
          if (frequencyBandsRef.current) {
            // The custom AV adapter reports sparse, decimated amplitude samples,
            // not contiguous PCM. Use backend FFT data rather than aliased bands.
            onSample((player as AudioPlayer & { ncAVPlayer?: boolean }).ncAVPlayer === true
              ? null : sampleToFrequencySpectrum(sample.channels));
          } else {
            onSample(sampleToSpectrum(sample.channels));
          }
        } catch {
          // PCM is optional; keep analyzed/procedural spectrum fallback available.
          dispose();
        }
      });
    } catch {
      dispose();
    }
    return dispose;
  }, [fps, onSample, player]);
  return null;
}
