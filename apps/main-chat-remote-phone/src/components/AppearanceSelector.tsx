import { useThemedStyles, useThemeColors } from '../styles/ThemeContext';
import type { ThemeColors } from '../styles/theme';
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { InterfaceStyle } from '../utils/interfaceMode';
import { colors, spacing } from '../styles/theme';

type ModeOption = {
  value: InterfaceStyle;
  label: string;
  detail: string;
  recommended?: boolean;
};

const options: ModeOption[] = [
  { value: 'adaptive', label: 'Adaptive Focus', detail: 'Main content first. Secondary tools open when needed.', recommended: true },
  { value: 'flat', label: 'Flat Utility', detail: 'All controls stay visible as compact rows and dividers.' },
  { value: 'immersive', label: 'Immersive Minimal', detail: 'Deep-black surfaces keep attention on chat and avatar content.' },
  { value: 'classic', label: 'Classic', detail: 'Original card density with the new production navigation.' },
];

export function AppearanceSelector({ value, onChange }: { value: InterfaceStyle; onChange: (value: InterfaceStyle) => void }) {
  const styles = useThemedStyles(createStyles);

  return (
    <View style={styles.options}>
      {options.map((option) => {
        const selected = value === option.value;
        return (
          <Pressable
            accessibilityLabel={`${option.label}. ${option.detail}`}
            accessibilityRole="radio"
            accessibilityState={{ checked: selected }}
            key={option.value}
            style={styles.option}
            onPress={() => onChange(option.value)}
          >
            <View style={[styles.radio, selected && styles.radioSelected]}>
              {selected ? <View style={styles.radioDot} /> : null}
            </View>
            <View style={styles.copy}>
              <View style={styles.labelRow}>
                <Text style={styles.label}>{option.label}</Text>
                {option.recommended ? <Text style={styles.recommended}>Recommended</Text> : null}
              </View>
              <Text style={styles.detail}>{option.detail}</Text>
            </View>
          </Pressable>
        );
      })}
      <Text style={styles.savedNote}>Applies to every tab immediately.</Text>
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  options: { gap: 0 },
  option: { alignItems: 'center', borderBottomColor: colors.border, borderBottomWidth: 1, flexDirection: 'row', gap: spacing.md, minHeight: 62, paddingVertical: spacing.sm },
  radio: { alignItems: 'center', borderColor: colors.muted, borderRadius: 9, borderWidth: 1, height: 18, justifyContent: 'center', width: 18 },
  radioSelected: { borderColor: colors.accent },
  radioDot: { backgroundColor: colors.accent, borderRadius: 4, height: 8, width: 8 },
  copy: { flex: 1, minWidth: 0 },
  labelRow: { alignItems: 'center', flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  label: { color: colors.text, fontSize: 13, fontWeight: '800' },
  detail: { color: colors.muted, fontSize: 11, lineHeight: 16, marginTop: 3 },
  recommended: { backgroundColor: colors.accentSoft, borderRadius: 4, color: colors.ok, fontSize: 8, fontWeight: '900', paddingHorizontal: 6, paddingVertical: 3, textTransform: 'uppercase' },
  savedNote: { color: colors.ok, fontSize: 11, marginTop: spacing.sm, textAlign: 'center' },
});
