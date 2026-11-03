import { usePresentationStyle, useThemedStyles, useThemeColors } from '../styles/ThemeContext';
import type { ThemeColors } from '../styles/theme';
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, radii } from '../styles/theme';
import {AppIcon} from './app-shell/AppIcon';
import {FullscreenFrameGlow} from './live-fullscreen/FullscreenFrameGlow';

type Props = {
  compact?: boolean;
  enabled: boolean;
  disabled: boolean;
  available: boolean;
  status: string;
  error?: string;
  onToggle: () => Promise<void>;
  onFullscreen?: () => void;
  canStopSpeech?: boolean;
  onStopSpeech?: () => void;
};

export function LiveModeControl({ compact = false, enabled, disabled, available, status, error, onToggle, onFullscreen, canStopSpeech, onStopSpeech }: Props) {
  const styles = useThemedStyles(createStyles);
  const palette = useThemeColors();
  const editorial = usePresentationStyle() === 'editorial';

  const unavailable = !enabled && (disabled || !available);
  return (
    <View>
      <View style={styles.row}>
        <Pressable
          accessibilityRole="switch"
          accessibilityLabel="Live Mode"
          accessibilityHint="Listen hands-free. Pause to send, speak during a reply to interrupt."
          accessibilityState={{ checked: enabled, disabled: unavailable }}
          disabled={unavailable}
          onPress={onToggle}
          style={[styles.control, compact && styles.compact, compact && editorial && styles.editorialCompact,
            enabled && styles.active, unavailable && styles.disabled]}
        >
          {compact && !editorial ? <FullscreenFrameGlow radius={30} shimmer={!unavailable} /> : null}
          {compact ? <AppIcon name="live" size={22} color={editorial ? palette.accent : '#e7f7ff'} /> : <View style={[styles.dot, enabled && styles.liveDot]} />}
          {compact ? <Text style={[styles.compactLabel, editorial && styles.editorialCompactLabel]}>{enabled ? 'Stop Live' : 'Start Live'}</Text> : <>
            <Text style={styles.label}>Live Mode</Text>
            <Text numberOfLines={1} style={styles.status}>{enabled ? status || 'Listening' : 'Tap to talk hands-free'}</Text>
            <Text style={[styles.toggle, enabled && styles.toggleActive]}>{enabled ? 'Stop' : 'Start'}</Text>
          </>}
        </Pressable>
        {onFullscreen ? (
          <Pressable accessibilityRole="button" accessibilityLabel="Open live full screen" onPress={onFullscreen} style={styles.fullscreen}>
            <Text style={styles.fullscreenGlyph}>⛶</Text>
          </Pressable>
        ) : null}
        {canStopSpeech ? (
          <Pressable accessibilityRole="button" accessibilityLabel="Stop speech" onPress={onStopSpeech} style={styles.stopSpeech}>
            <Text style={styles.label}>Stop speech</Text>
          </Pressable>
        ) : null}
      </View>
      {compact && enabled && status ? <Text style={styles.compactStatus}>{status}</Text> : null}
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  row: { alignItems: 'center', flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  control: { alignItems: 'center', borderRadius: radii.md, flexGrow: 1, flexShrink: 1, flexBasis: 210, flexDirection: 'row', gap: 7, minHeight: 44, paddingHorizontal: 8 },
  compact: {flexBasis:0,minHeight:56,borderRadius:30,borderWidth:1,borderColor:'#608da5',
    backgroundColor:'rgba(6,25,37,0.88)',justifyContent:'center',paddingHorizontal:10,gap:9},
  editorialCompact: { minHeight:52, borderRadius:10, borderColor:colors.borderSoft,
    backgroundColor:colors.backgroundElevated },
  compactLabel: {color:'#e7f7ff',fontSize:13,fontWeight:'600',flexShrink:1},
  editorialCompactLabel: { color:colors.accent, fontSize:15 },
  compactStatus: {color:colors.muted,fontSize:10,paddingTop:4},
  stopSpeech: { minWidth: 44, minHeight: 44, justifyContent: 'center', paddingHorizontal: 10, borderColor: colors.borderSoft, borderWidth: 1, borderRadius: radii.md },
  active: { backgroundColor: colors.accentSoft },
  disabled: { opacity: 0.45 },
  dot: { backgroundColor: colors.muted, borderRadius: 4, height: 6, width: 6 },
  liveDot: { backgroundColor: colors.ok },
  label: { color: colors.textSecondary, fontSize: 11, fontWeight: '800' },
  status: { color: colors.muted, flex: 1, fontSize: 10 },
  toggle: { color: colors.text, fontSize: 11, fontWeight: '800' },
  toggleActive: { color: colors.accent },
  fullscreen: { alignItems: 'center', borderColor: colors.borderSoft, borderRadius: radii.md, borderWidth: 1, height: 44, justifyContent: 'center', width: 44 },
  fullscreenGlyph: { color: colors.textSecondary, fontSize: 23 },
  error: { color: colors.danger, fontSize: 12, lineHeight: 16, paddingVertical: 4 },
});
