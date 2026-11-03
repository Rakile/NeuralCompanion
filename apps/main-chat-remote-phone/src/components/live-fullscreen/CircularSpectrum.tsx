import React from 'react';
import { StyleSheet, View } from 'react-native';
import Svg, { Circle, Defs, LinearGradient, Path, Stop } from 'react-native-svg';

import {
  spectrumBarRadii,
  spectrumRadius,
} from '../../utils/liveFullscreenGeometry';
import type { SpectrumBarDirection } from '../../utils/liveFullscreenGeometry';
import type { LiveFullscreenPalette } from '../../utils/liveFullscreenSettings';
import {
  resampleSpectrum,
  spectrumPhaseAtTime,
  spectrumRotationPhase,
} from '../../utils/liveFullscreenSpectrum';

export type SpectrumActivity = 'idle' | 'listening' | 'thinking' | 'speaking';

type Props = {
  activity: SpectrumActivity;
  outerEnergies: readonly number[];
  innerEnergies: readonly number[];
  palette: LiveFullscreenPalette;
  circleSizePct: number;
  waveformDepthPct: number;
  glowStrengthPct: number;
  motionIntensityPct: number;
  rotationSpeedPct: number;
  barCount: number;
  frameTimeMs: number;
  opacity?: number;
};

function stateColor(activity: SpectrumActivity): string {
  if (activity === 'listening') return '#00ff66';
  if (activity === 'thinking') return '#a855ff';
  if (activity === 'speaking') return '#00eaff';
  return '#56f7ff';
}

export function CircularSpectrum({
  activity,
  outerEnergies,
  innerEnergies,
  palette,
  circleSizePct,
  waveformDepthPct,
  glowStrengthPct,
  motionIntensityPct,
  rotationSpeedPct,
  barCount,
  frameTimeMs,
  opacity = 1,
}: Props) {
  const [layout, setLayout] = React.useState({ width: 320, height: 320 });
  const speed = activity === 'thinking' ? 0.045 : 0.012;
  const motionPhase = spectrumPhaseAtTime(frameTimeMs, speed, motionIntensityPct);
  const rotationPhase = spectrumRotationPhase(activity, frameTimeMs, speed, rotationSpeedPct);

  const maxDepth = Math.min(layout.width, layout.height) * 0.18;
  const radius = spectrumRadius(layout.width, layout.height, circleSizePct, maxDepth);
  const centerX = layout.width / 2;
  const centerY = layout.height / 2;
  const depthScale = maxDepth * Math.max(0, Math.min(2, waveformDepthPct / 100));
  const directionalMotionPhase = rotationSpeedPct <= 0 ? 0 : motionPhase;
  const outerDisplay = resampleSpectrum(outerEnergies, barCount);
  const innerDisplay = resampleSpectrum(innerEnergies, barCount);
  function buildBars(
    displayEnergies: readonly number[],
    direction: SpectrumBarDirection,
    includeThinkingMotion: boolean,
  ): string {
    const displayBarCount = displayEnergies.length;
    return Array.from({ length: displayBarCount }, (_, index) => {
      const supplied = Number(displayEnergies[index] || 0);
      if (direction === 'inward' && supplied <= 0.001) return '';
      const idleEnergy = activity === 'idle' ? 0.025 : activity === 'thinking' ? 0.12 : 0.05;
      const traveling = includeThinkingMotion && activity === 'thinking'
        ? (Math.sin((index / displayBarCount) * Math.PI * 4 + directionalMotionPhase) + 1) * 0.16
        : 0;
      const energy = direction === 'outward'
        ? Math.max(idleEnergy, Math.min(1, supplied + traveling))
        : Math.min(1, supplied);
      const depth = direction === 'outward'
        ? Math.max(1.5, depthScale * energy)
        : depthScale * energy;
      const angle = (
        (index / displayBarCount) * Math.PI * 2
      ) - Math.PI / 2 + rotationPhase * 0.002;
      const { innerRadius, outerRadius } = spectrumBarRadii(
        radius,
        depth,
        direction,
        radius * 0.52,
      );
      return [
        'M',
        centerX + Math.cos(angle) * innerRadius,
        centerY + Math.sin(angle) * innerRadius,
        'L',
        centerX + Math.cos(angle) * outerRadius,
        centerY + Math.sin(angle) * outerRadius,
      ].join(' ');
    }).join(' ');
  }
  const outerBars = buildBars(outerDisplay, 'outward', true);
  const innerBars = buildBars(innerDisplay, 'inward', false);
  const stateStroke = stateColor(activity);
  const outerStroke = palette === 'state' ? stateStroke : 'url(#live-spectrum-gradient)';
  const innerStroke = palette === 'state'
    ? stateColor('listening')
    : 'url(#live-spectrum-gradient)';
  const glowOpacity = Math.max(0, Math.min(0.8, glowStrengthPct / 250));

  return (
    <View
      pointerEvents="none"
      style={[StyleSheet.absoluteFill, { opacity: Math.max(0, Math.min(1, opacity)) }]}
      onLayout={(event) => {
        const { width, height } = event.nativeEvent.layout;
        if (width > 0 && height > 0) setLayout({ width, height });
      }}
    >
      <Svg width="100%" height="100%" viewBox={`0 0 ${layout.width} ${layout.height}`}>
        <Defs>
          <LinearGradient id="live-spectrum-gradient" x1="0" y1="0" x2="1" y2="1">
            {palette === 'electric' ? [
              <Stop key="e0" offset="0" stopColor="#00f5ff" />,
              <Stop key="e1" offset="0.5" stopColor="#0066ff" />,
              <Stop key="e2" offset="1" stopColor="#d000ff" />,
            ] : [
              <Stop key="s0" offset="0" stopColor="#ff1744" />,
              <Stop key="s1" offset="0.2" stopColor="#ffea00" />,
              <Stop key="s2" offset="0.4" stopColor="#00ff66" />,
              <Stop key="s3" offset="0.62" stopColor="#00e5ff" />,
              <Stop key="s4" offset="0.82" stopColor="#2962ff" />,
              <Stop key="s5" offset="1" stopColor="#ff00c8" />,
            ]}
          </LinearGradient>
        </Defs>
        <Circle
          cx={centerX}
          cy={centerY}
          r={radius}
          fill="none"
          stroke={palette === 'state' ? stateStroke : '#22eaff'}
          strokeOpacity={activity === 'idle' ? 0.5 : 0.26}
          strokeWidth={activity === 'idle' ? 1.4 : 1}
        />
        {glowOpacity > 0 ? (
          <>
            <Path
              d={outerBars}
              fill="none"
              stroke={outerStroke}
              strokeLinecap="round"
              strokeOpacity={glowOpacity * 0.35}
              strokeWidth={5 + Math.min(8, glowStrengthPct / 25)}
            />
            <Path
              d={innerBars}
              fill="none"
              stroke={innerStroke}
              strokeLinecap="round"
              strokeOpacity={glowOpacity * 0.35}
              strokeWidth={5 + Math.min(8, glowStrengthPct / 25)}
            />
          </>
        ) : null}
        <Path
          d={outerBars}
          fill="none"
          stroke={outerStroke}
          strokeLinecap="round"
          strokeOpacity={activity === 'idle' ? 0.72 : 1}
          strokeWidth={2.2}
        />
        <Path
          d={innerBars}
          fill="none"
          stroke={innerStroke}
          strokeLinecap="round"
          strokeOpacity={activity === 'idle' ? 0.72 : 1}
          strokeWidth={2.2}
        />
      </Svg>
    </View>
  );
}
