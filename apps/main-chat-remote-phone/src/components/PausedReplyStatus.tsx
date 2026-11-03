import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useThemedStyles } from '../styles/ThemeContext';
import type { ThemeColors } from '../styles/theme';

export function PausedReplyStatus({disabled, onPlay}: {disabled: boolean; onPlay: () => Promise<void>}) {
  const styles = useThemedStyles(createStyles);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');
  return <View style={styles.panel}>
    <View style={styles.row}>
      <Text accessibilityLiveRegion="polite" style={styles.label}>Response paused</Text>
      <Pressable accessibilityRole="button" accessibilityLabel="Resume paused response" disabled={disabled || busy}
        style={[styles.button, (disabled || busy) && styles.disabled]} onPress={async () => {
          if (busy) return;
          setBusy(true); setError('');
          try { await onPlay(); }
          catch (failure) { setError(failure instanceof Error ? failure.message : 'Could not resume response.'); }
          finally { setBusy(false); }
        }}><Text style={styles.label}>{busy ? 'Resuming…' : 'Play'}</Text></Pressable>
    </View>
    {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
  </View>;
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  panel: {marginHorizontal: 12, marginVertical: 6, padding: 10, borderRadius: 12,
    borderWidth: 1, borderColor: colors.accent, backgroundColor: colors.panel},
  row: {flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12},
  label: {color: colors.text, fontSize: 14, fontWeight: '700'},
  button: {minHeight: 44, paddingHorizontal: 20, borderRadius: 8, justifyContent: 'center', backgroundColor: colors.accentSoft},
  disabled: {opacity: 0.45}, error: {color: colors.danger, fontSize: 13, marginTop: 6},
});
