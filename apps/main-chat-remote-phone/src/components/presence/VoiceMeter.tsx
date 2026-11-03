import React from 'react';
import { StyleSheet, View } from 'react-native';
import Svg, { Circle, Rect } from 'react-native-svg';
import type { PresenceActivity } from '../../api/types';
import type { VoiceThreadFrame } from '../../hooks/usePresenceSpectrum';
import { useThemeColors } from '../../styles/ThemeContext';
import { smoothSilkLevel } from '../../utils/voiceThreadGeometry';
import { voiceMeterCount, voiceMeterMarks, voiceMeterTargets, VOICE_VISUALIZER_STYLES } from '../../utils/voiceVisualizer';
import type { VoiceMeterStyle } from '../../utils/voiceVisualizer';
import { SilkSettingsContext } from './SilkSettingsContext';

type Props = {
  design: VoiceMeterStyle; activity: PresenceActivity; frame: VoiceThreadFrame;
  fullscreen?: boolean; heightOverride?: number; reduceMotion?: boolean; lowPower?: boolean;
  waveformDepthPct?: number; glowStrengthPct?: number; motionIntensityPct?: number;
};

/** Rendering only. The existing app-level sampler remains the sole owner of playback analysis. */
export function VoiceMeter({ design, activity, frame, fullscreen = false, heightOverride, reduceMotion = false,
  lowPower = false, waveformDepthPct = 100, glowStrengthPct = 100, motionIntensityPct = 100 }: Props) {
  const colors = useThemeColors();
  const tuning = React.useContext(SilkSettingsContext);
  const count = voiceMeterCount(design);
  const [width, setWidth] = React.useState(320);
  const height = Math.max(40, heightOverride || (fullscreen ? 220 : design === 'halo_meter' ? 112 : 88));
  const enabled = frame.enabled && !reduceMotion && motionIntensityPct > 0;
  const targets = React.useRef<number[]>([]);
  targets.current = enabled ? voiceMeterTargets(frame, activity, count, tuning) : Array(count).fill(0);
  const timing = React.useRef(tuning); timing.current = tuning;
  const envelope = React.useRef<number[]>(Array(count).fill(0));
  const [levels, setLevels] = React.useState<number[]>(Array(count).fill(0));
  const fps = Math.max(12, Math.min(lowPower ? 20 : 30, frame.fps || 24));
  React.useEffect(() => {
    envelope.current = Array(count).fill(0);
    setLevels(envelope.current);
    if (!enabled || (activity !== 'speaking' && activity !== 'listening')) return;
    let request = 0, last = 0, drawn = 0;
    const tick = (now: number) => {
      const elapsed = last ? Math.min(50, now - last) : 16;
      last = now;
      envelope.current = envelope.current.map((value, index) =>
        smoothSilkLevel(value, targets.current[index] || 0, elapsed, timing.current.attack, timing.current.release));
      if (now - drawn >= 1000 / fps - 1) {
        drawn = now;
        setLevels(envelope.current);
      }
      request = requestAnimationFrame(tick);
    };
    request = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(request);
  }, [activity, count, enabled, fps]);
  const depth = Math.max(0, Math.min(2, waveformDepthPct / 100 * motionIntensityPct / 100));
  const visibleLevels = enabled ? levels.map(level => Math.min(1, level * depth)) : Array(count).fill(0);
  const marks = voiceMeterMarks(design, width, height, visibleLevels);
  const color = activity === 'failure' ? colors.danger : activity === 'thinking' ? colors.muted : colors.accent;
  const glow = Math.max(0, Math.min(1, glowStrengthPct / 100));
  const name = VOICE_VISUALIZER_STYLES.find(option => option.value === design)!.label;
  return <View onLayout={event => setWidth(Math.max(1, event.nativeEvent.layout.width))}
    accessibilityRole="image" accessibilityLabel={`${name}, ${activity}`} style={[styles.container, { height }]}>
    <Svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`}>
      {design === 'halo_meter' ? <Circle cx={width / 2} cy={height / 2}
        r={Math.min(width, height) * .19} fill={colors.accentSoft} opacity={.45} /> : null}
      {marks.map((mark, index) => <React.Fragment key={index}>
        {design === 'centered_pulse' && !reduceMotion && visibleLevels[index] > .015 && glow > 0 ? <Rect
          x={mark.x - 3} y={mark.y - 3} width={mark.width + 6} height={mark.height + 6} rx={mark.radius + 3}
          fill={color} opacity={visibleLevels[index] * .055 * glow} /> : null}
        <Rect x={mark.x} y={mark.y} width={mark.width} height={mark.height} rx={mark.radius}
          fill={color} opacity={mark.opacity} rotation={mark.rotation} originX={width / 2} originY={height / 2} />
      </React.Fragment>)}
    </Svg>
  </View>;
}

const styles = StyleSheet.create({ container: { width: '100%', justifyContent: 'center', overflow: 'hidden' } });
