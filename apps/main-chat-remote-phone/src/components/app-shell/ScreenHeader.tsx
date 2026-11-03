import { useThemedStyles, useThemeColors } from '../../styles/ThemeContext';
import type { ThemeColors } from '../../styles/theme';
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, radii, spacing } from '../../styles/theme';

type ScreenHeaderProps = {
  title: string;
  subtitle?: string;
  onBack: () => void;
};

export function ScreenHeader({ title, subtitle, onBack }: ScreenHeaderProps) {
  const styles = useThemedStyles(createStyles, 'ScreenHeader');

  return (
    <View style={styles.header}>
      <Pressable
        accessibilityHint="Returns to the previous app screen"
        accessibilityLabel="Back"
        accessibilityRole="button"
        hitSlop={8}
        onPress={onBack}
        style={styles.back}
      >
        <Text style={styles.backGlyph}>‹</Text>
      </Pressable>
      <View style={styles.copy}>
        <Text style={styles.title}>{title}</Text>
        {subtitle ? <Text numberOfLines={1} style={styles.subtitle}>{subtitle}</Text> : null}
      </View>
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  header: {
    alignItems: 'center',
    borderBottomColor: colors.borderSoft,
    borderBottomWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
    gap: spacing.sm,
    minHeight: 62,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  back: {
    alignItems: 'center',
    borderColor: colors.borderSoft,
    borderRadius: radii.md,
    borderWidth: 1,
    height: 44,
    justifyContent: 'center',
    width: 44,
  },
  backGlyph: { color: colors.text, fontSize: 30, fontWeight: '300', lineHeight: 32, marginTop: -3 },
  copy: { flex: 1, minWidth: 0 },
  title: { color: colors.text, fontSize: 20, fontWeight: '900' },
  subtitle: { color: colors.muted, fontSize: 11, marginTop: 2 },
});

