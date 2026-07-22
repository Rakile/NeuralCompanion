import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import type { StyleProp, ViewStyle } from 'react-native';

import { useInterfaceMode } from '../context/InterfaceModeContext';
import { colors, spacing } from '../styles/theme';

type SurfaceProps = React.PropsWithChildren<{ style?: StyleProp<ViewStyle> }>;
type SectionProps = SurfaceProps & { title?: string };

export function ModeSurface({ children, style }: SurfaceProps) {
  const { mode, policy } = useInterfaceMode();
  return <View style={[styles.surface, policy.cards && styles.card, mode === 'immersive' && styles.immersive, style]}>{children}</View>;
}

export function ModeSection({ title, children, style }: SectionProps) {
  const { mode, policy } = useInterfaceMode();
  return (
    <View style={[styles.section, policy.cards ? styles.card : styles.cleanSection, mode === 'immersive' && styles.immersive, style]}>
      {title ? <Text style={[styles.title, !policy.cards && styles.cleanTitle]}>{title}</Text> : null}
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  surface: { backgroundColor: 'transparent' },
  section: { gap: spacing.sm },
  card: { backgroundColor: colors.panel, borderColor: colors.border, borderRadius: 6, borderWidth: 1, padding: spacing.md },
  cleanSection: { borderBottomColor: colors.border, borderBottomWidth: 1, paddingHorizontal: spacing.md, paddingVertical: spacing.md },
  immersive: { backgroundColor: '#000000', borderBottomColor: '#20252a' },
  title: { color: colors.text, fontSize: 14, fontWeight: '800' },
  cleanTitle: { color: colors.muted, fontSize: 11, textTransform: 'uppercase' },
});
