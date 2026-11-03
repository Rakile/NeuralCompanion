import { useThemedStyles, useThemeColors, usePresentationStyle } from '../styles/ThemeContext';
import { EditorialSection } from './editorial/EditorialSection';
import type { ThemeColors } from '../styles/theme';
import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import type { StyleProp, ViewStyle } from 'react-native';

import { useInterfaceMode } from '../context/InterfaceModeContext';
import { colors, spacing } from '../styles/theme';

type SurfaceProps = React.PropsWithChildren<{ style?: StyleProp<ViewStyle> }>;
type SectionProps = SurfaceProps & { title?: string; editorialDisclosure?: boolean; summary?: string; initiallyOpen?: boolean; forceOpen?: boolean };

export function ModeSurface({ children, style }: SurfaceProps) {
  const styles = useThemedStyles(createStyles, 'ModeSurface');

  const { mode, policy } = useInterfaceMode();
  return <View style={[styles.surface, policy.cards && styles.card, mode === 'immersive' && styles.immersive, style]}>{children}</View>;
}

export function ModeSection({ title, children, style, editorialDisclosure, summary, initiallyOpen, forceOpen }: SectionProps) {
  const styles = useThemedStyles(createStyles, 'ModeSurface');
  const editorial = usePresentationStyle() === 'editorial';
  const { mode, policy } = useInterfaceMode();
  if (editorial && editorialDisclosure && title) return (
    <EditorialSection title={title} summary={summary} initiallyOpen={initiallyOpen} forceOpen={forceOpen}>{children}</EditorialSection>
  );
  return (
    <View style={[styles.section, policy.cards ? styles.card : styles.cleanSection, mode === 'immersive' && styles.immersive, style]}>
      {title ? <Text style={[styles.title, !policy.cards && styles.cleanTitle]}>{title}</Text> : null}
      {children}
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  surface: { backgroundColor: 'transparent' },
  section: { gap: spacing.sm },
  card: { backgroundColor: colors.panel, borderColor: colors.border, borderRadius: 18, borderWidth: 1, padding: spacing.md },
  cleanSection: { borderBottomColor: colors.border, borderBottomWidth: 1, paddingHorizontal: spacing.md, paddingVertical: spacing.md },
  immersive: { backgroundColor: colors.background, borderBottomColor: colors.border },
  title: { color: colors.text, fontSize: 14, fontWeight: '800' },
  cleanTitle: { color: colors.muted, fontSize: 11, textTransform: 'uppercase' },
});
