import React from 'react';
import { StyleSheet, View } from 'react-native';
import Svg, { Defs, LinearGradient, Path, Stop } from 'react-native-svg';

import type { PresenceActivity } from '../../api/types';
import type { VoiceThreadFrame } from '../../hooks/usePresenceSpectrum';
import { presenceMoodPalette, threadState } from '../../utils/presenceState';
import {
  buildFineSilkPath,
  responsiveSilkLevel,
  silkFlowVelocity,
  silkVoiceLevel,
  smoothSilkLevel,
} from '../../utils/voiceThreadGeometry';
import type { VoiceThreadPalette } from '../../utils/presenceControls';
import { silkAudioColors } from '../../utils/voiceThreadColors';
import { SilkSettingsContext, VoiceVisualizerContext } from './SilkSettingsContext';
import type { VoiceVisualizerStyle } from '../../utils/voiceVisualizer';
import { VoiceMeter } from './VoiceMeter';

type LivingVoiceThreadProps = {
  activity: PresenceActivity;
  mood: string;
  frame: VoiceThreadFrame;
  compact?: boolean;
  fullscreen?: boolean;
  heightOverride?: number;
  reduceMotion?: boolean;
  lowPower?: boolean;
  waveformDepthPct?: number;
  glowStrengthPct?: number;
  motionIntensityPct?: number;
  paletteMode?: VoiceThreadPalette;
  visualizerStyle?: VoiceVisualizerStyle;
};

function LivingVoiceThreadComponent({
  activity,
  mood,
  frame,
  fullscreen = false,
  heightOverride,
  reduceMotion = false,
  lowPower = false,
  waveformDepthPct = 100,
  glowStrengthPct = 100,
  motionIntensityPct = 100,
  paletteMode = 'state',
}: LivingVoiceThreadProps) {
  const silk = React.useContext(SilkSettingsContext);
  const motion = threadState(activity, mood);
  const moodPalette = !mood || mood.toLowerCase() === 'neutral'
    ? { accent: '#ef83db', glow: '#b749a5' }
    : presenceMoodPalette(mood);
  const statePalette = motion.palette === 'listening'
    ? { accent: '#64f5a7', glow: '#1ba96a' }
    : motion.palette === 'thinking'
      ? { accent: '#b99cff', glow: '#6f4de0' }
      : motion.palette === 'failure'
        ? { accent: '#ff7373', glow: '#b72f46' }
        : moodPalette;
  const palette = paletteMode === 'spectrum'
    ? { accent: '#ff68dd', glow: '#36e7ff' }
    : paletteMode === 'electric'
      ? { accent: '#efffff', glow: '#00c8ff' }
      : statePalette;
  const height = Math.max(40, Number(heightOverride || (fullscreen ? 220 : silk.bandHeight)));
  const reduced = reduceMotion;
  const motionScale = Math.max(0, Math.min(2, motionIntensityPct / 100));
  const depthScale = silk.depth * Math.max(0, Math.min(2, waveformDepthPct / 100));
  const glowScale = Math.max(0, Math.min(2, glowStrengthPct / 100));

  const [width, setWidth] = React.useState(320);
  const [animation, setAnimation] = React.useState({ phase: 0, seconds: 0, level: 0, transient: 0 });
  const rawLevel = silkVoiceLevel(frame.energies, frame.inputLevel, activity, frame.source);
  const target = React.useRef(0);
  target.current = responsiveSilkLevel(rawLevel, silk);
  const tuning = React.useRef(silk);
  tuning.current = silk;
  const phase = React.useRef(0);
  const seconds = React.useRef(0);
  const velocity = React.useRef(0);
  const envelope = React.useRef(0);
  const transient = React.useRef(0);
  const enabled = frame.enabled !== false;
  const renderFps = Math.max(12, Math.min(lowPower ? 20 : 60, frame.fps || 60));
  React.useEffect(() => {
    if (!enabled || reduced) {
      envelope.current = 0;
      transient.current = 0;
      setAnimation({ phase: phase.current, seconds: seconds.current, level: 0, transient: 0 });
      return;
    }
    let request = 0;
    let last = 0;
    let drawn = 0;
    const interval = 1000 / renderFps;
    const tick = (now: number) => {
      const elapsed = last ? Math.min(50, now - last) : 16;
      last = now;
      const design = tuning.current;
      const previous = envelope.current;
      envelope.current = smoothSilkLevel(previous, target.current, elapsed, design.attack, design.release);
      transient.current = Math.max(transient.current * Math.exp(-elapsed / 90), (envelope.current - previous) * 2.3);
      // Integrating signed velocity keeps state/seed changes from jumping the flow phase.
      if (activity !== 'ready') {
        seconds.current += elapsed / 1000 * design.speed * motionScale;
        const flow = silkFlowVelocity(seconds.current, design.seed, design.variation / 100);
        const direction = activity === 'listening' ? -1 : 1;
        velocity.current += (flow * direction - velocity.current) * (1 - Math.exp(-elapsed / 350));
        phase.current += elapsed / 1000 * velocity.current * design.speed * motionScale;
      }
      if (now - drawn >= interval - 1) {
        drawn = now;
        setAnimation({ phase: phase.current, seconds: seconds.current, level: envelope.current, transient: transient.current });
      }
      if (activity !== 'ready' || envelope.current > .002) request = requestAnimationFrame(tick);
    };
    request = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(request);
  }, [activity, enabled, renderFps, motionScale, reduced]);
  const strandCount = reduced ? 1 : lowPower ? Math.min(3, silk.strands) : silk.strands;
  const paths = React.useMemo(() => Array.from({ length: strandCount }, (_, index) => {
    const offset = index - (strandCount - 1) / 2;
    const third = Math.max(1, Math.ceil(frame.energies.length / 3));
    const band = frame.energies.slice((index % 3) * third, ((index % 3) + 1) * third);
    const bandLevel = responsiveSilkLevel(silkVoiceLevel(band, frame.inputLevel, activity, frame.source), silk);
    return { offset, path: buildFineSilkPath({ width, height, phase: animation.phase,
      timeSeconds: animation.seconds, level: animation.level, offset, depthScale,
      seed: silk.seed, variation: silk.variation / 100, spread: silk.spread,
      bandLevel: reduced || !enabled ? 0 : bandLevel, transient: animation.transient }) };
  }), [strandCount, width, height, animation, depthScale, silk, frame.energies, frame.inputLevel, frame.source, activity, reduced, enabled]);
  const voiceGlow = (.04 + animation.level ** .72 * .64 + animation.transient * .12) * glowScale * silk.density / 100;
  const audioColors = silkAudioColors(palette, reduced || !enabled ? 0 : animation.level,
    reduced || !enabled ? 0 : animation.transient, silk.colorResponse);
  return (
    <View
      onLayout={event => setWidth(Math.max(1, event.nativeEvent.layout.width))}
      accessibilityRole="image"
      accessibilityLabel={`${activity} voice thread, ${mood || 'neutral'} mood`}
      style={[styles.container, { height }]}
    >
      <Svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`}>
        <Defs>
          <LinearGradient id="threadGradient" x1="0" y1="0" x2="1" y2="0">
            <Stop offset="0" stopColor={audioColors.glow} stopOpacity={0} />
            <Stop offset="0.24" stopColor={audioColors.glow} stopOpacity={.5 + animation.level * .25} />
            <Stop offset="0.5" stopColor={audioColors.accent} stopOpacity={1} />
            <Stop offset="0.76" stopColor={audioColors.glow} stopOpacity={.5 + animation.level * .25} />
            <Stop offset="1" stopColor={audioColors.glow} stopOpacity={0} />
          </LinearGradient>
          <LinearGradient id="threadHighlight" x1="0" y1="0" x2="1" y2="0">
            <Stop offset="0" stopColor="#ffffff" stopOpacity={0} />
            <Stop offset="0.5" stopColor={audioColors.highlight} stopOpacity={1} />
            <Stop offset="1" stopColor="#ffffff" stopOpacity={0} />
          </LinearGradient>
        </Defs>
        {voiceGlow > .002 && paths.map(({ offset, path }) => (
          <React.Fragment key={`glow-${offset}`}>
            <Path d={path} fill="none" stroke="url(#threadGradient)" strokeWidth={silk.thickness + silk.radius * 1.05}
              opacity={Math.min(1, voiceGlow * .2)} strokeLinecap="round" />
            <Path d={path} fill="none" stroke="url(#threadGradient)" strokeWidth={silk.thickness + silk.radius * .42}
              opacity={Math.min(1, voiceGlow * .49)} strokeLinecap="round" />
          </React.Fragment>
        ))}
        {paths.map(({ offset, path }) => {
          const centre = 1 - Math.abs(offset) / Math.max(1, strandCount / 2);
          return <React.Fragment key={offset}>
            <Path d={path} fill="none" stroke="url(#threadGradient)"
              opacity={Math.min(1, .4 + centre * .2 + animation.level * .28)}
              strokeLinecap="round" strokeWidth={silk.thickness * (.67 + centre * .33)} />
            <Path d={path} fill="none" stroke="url(#threadHighlight)"
              opacity={(.08 + animation.level * .38) * silk.highlight / 100 * centre}
              strokeLinecap="round" strokeWidth={silk.thickness * .35} />
          </React.Fragment>;
        })}
      </Svg>
    </View>
  );
}

export const LivingVoiceThread = React.memo(function VoiceVisualizer(props: LivingVoiceThreadProps) {
  const savedStyle = React.useContext(VoiceVisualizerContext);
  const design = props.visualizerStyle || savedStyle;
  return design === 'silk' ? <LivingVoiceThreadComponent {...props} /> : <VoiceMeter {...props} design={design} />;
});

const styles = StyleSheet.create({
  container: { justifyContent: 'center', overflow: 'hidden', width: '100%' },
});
