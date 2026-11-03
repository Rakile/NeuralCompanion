import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { PHONE_THEMES } from '../styles/theme';
import type { PhoneThemeId, ThemeColors } from '../styles/theme';
import { useThemedStyles } from '../styles/ThemeContext';

export function ThemeChooser({ value, onChange }: { value: PhoneThemeId; onChange: (id: PhoneThemeId) => void }) {
  const styles = useThemedStyles(createStyles);
  return <View accessibilityRole="radiogroup" accessibilityLabel="Color theme" style={styles.grid}>
    {PHONE_THEMES.map(theme => <Pressable key={theme.id} accessibilityRole="radio" accessibilityLabel={`${theme.name}, ${theme.appearance} theme`}
      accessibilityState={{ checked: value === theme.id }} onPress={() => onChange(theme.id)} style={[styles.choice, value === theme.id && styles.selected]}>
      <View accessibilityElementsHidden style={[styles.sample, { backgroundColor: theme.colors.background }]}>
        <View style={[styles.sampleHeader, { backgroundColor: theme.colors.panelAlt }]} />
        <View style={[styles.sampleLine, { backgroundColor: theme.colors.accent }]} />
        <View style={[styles.sampleLine, { backgroundColor: theme.colors.textSecondary, width: '48%' }]} />
      </View>
      <Text style={styles.name}>{theme.name}{value === theme.id ? ' ✓' : ''}</Text>
      <Text style={styles.detail}>{theme.appearance === 'light' ? 'Bright' : 'Dark'}</Text>
    </Pressable>)}
  </View>;
}
const createStyles = (colors: ThemeColors) => StyleSheet.create({
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  choice: { flexBasis: '46%', flexGrow: 1, borderRadius: 16, backgroundColor: colors.panelAlt, padding: 10, borderWidth: 1, borderColor: 'transparent', minHeight: 130 },
  selected: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
  sample: { height: 62, borderRadius: 9, padding: 9, gap: 6 },
  sampleHeader: { height: 10, width: '42%', borderRadius: 3 },
  sampleLine: { height: 3, width: '74%', borderRadius: 2 },
  name: { color: colors.text, fontSize: 14, fontWeight: '600', marginTop: 9 },
  detail: { color: colors.muted, fontSize: 11, marginTop: 2 },
});
