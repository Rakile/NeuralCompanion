import { useThemedStyles, useThemeColors, usePresentationStyle } from '../../styles/ThemeContext';
import type { ThemeColors } from '../../styles/theme';
import { AppIcon } from './AppIcon';
import type { AppIconName } from './AppIcon';
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { PrimaryDestination } from '../../utils/productionShell';
import { PRIMARY_DESTINATIONS } from '../../utils/productionShell';
import { colors, radii, spacing } from '../../styles/theme';
import { primaryNavigationMetrics } from '../../utils/presenceControls';

const glyphs: Record<PrimaryDestination, AppIconName> = {
  chat: 'chat',
  story: 'story',
  visual: 'visual',
  tools: 'settings',
};

type PrimaryNavigationProps = {
  active: PrimaryDestination;
  bottomInset: number;
  onChange: (destination: PrimaryDestination) => void;
};

export function PrimaryNavigation({ active, bottomInset, onChange }: PrimaryNavigationProps) {
  const styles = useThemedStyles(createStyles, 'PrimaryNavigation');
  const colors = useThemeColors();
  const editorial = usePresentationStyle() === 'editorial';

  const metrics = primaryNavigationMetrics(bottomInset);
  return (
    <View
      accessibilityLabel="Main destinations"
      accessibilityRole="tablist"
      style={[
        styles.container,
        {
          paddingBottom: metrics.bottomPadding,
          paddingTop: metrics.topPadding,
        },
      ]}
    >
      {PRIMARY_DESTINATIONS.map((destination) => {
        const selected = destination.id === active;
        return (
          <Pressable
            accessibilityLabel={destination.label}
            accessibilityRole="tab"
            accessibilityState={{ selected }}
            key={destination.id}
            onPress={() => onChange(destination.id)}
            style={[
              styles.item,
              { minHeight: metrics.itemMinHeight },
              selected && styles.itemActive,
            ]}
          >
            <AppIcon name={glyphs[destination.id]} size={25} color={selected ? colors.accent : colors.muted} />
            {editorial ? <Text style={[styles.label, selected && styles.labelActive]}>{destination.label}</Text> : null}
          </Pressable>
        );
      })}
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  container: {
    backgroundColor: colors.backgroundElevated,
    borderTopColor: colors.borderSoft,
    borderTopWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
    paddingHorizontal: spacing.md,
  },
  item: {
    alignItems: 'center',
    borderRadius: radii.lg,
    flex: 1,
    gap: 1,
    justifyContent: 'center',
  },
  itemActive: { backgroundColor: colors.accentSoft },
  glyph: { color: colors.muted, fontSize: 17, fontWeight: '800', lineHeight: 20 },
  glyphActive: { color: colors.accent },
  label: { color: colors.muted, fontSize: 10, fontWeight: '700' },
  labelActive: { color: colors.text },
});
