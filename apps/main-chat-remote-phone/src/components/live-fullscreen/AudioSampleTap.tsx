import React from 'react';
import { useAudioSampleListener } from 'expo-audio';
import type { AudioPlayer } from 'expo-audio';

import { sampleToSpectrum } from '../../utils/liveFullscreenSpectrum';

type Props = {
  player: AudioPlayer;
  onSample: (sample: readonly number[] | null) => void;
};

export function AudioSampleTap({ player, onSample }: Props) {
  useAudioSampleListener(player, (sample) => {
    if (player.isAudioSamplingSupported === false) {
      onSample(null);
      return;
    }
    onSample(sampleToSpectrum(sample.channels));
  });

  React.useEffect(() => () => onSample(null), [onSample, player]);
  return null;
}
