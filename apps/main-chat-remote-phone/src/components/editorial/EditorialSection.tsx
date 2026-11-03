import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useThemeColors } from '../../styles/ThemeContext';
import { controlGlyphTypography } from '../../styles/theme';

type Props = React.PropsWithChildren<{
  title: string;
  summary?: string;
  initiallyOpen?: boolean;
  forceOpen?: boolean;
}>;

/** Keeps editors mounted while details are tucked away. Never owns feature state. */
export function EditorialSection({ title, summary, initiallyOpen = false, forceOpen = false, children }: Props) {
  const colors = useThemeColors();
  const [open, setOpen] = React.useState(initiallyOpen);
  const expanded = open || forceOpen;
  return <View style={[styles.section, { borderColor: colors.borderSoft }]}>
    <Pressable accessibilityRole="button" accessibilityLabel={title} accessibilityState={{ expanded, disabled:forceOpen }}
      disabled={forceOpen}
      onPress={() => setOpen(value => !value)} style={styles.heading}>
      <View style={styles.copy}>
        <Text style={[styles.title, { color: colors.text }]}>{title}</Text>
        {!expanded && summary ? <Text style={[styles.summary, { color: colors.muted }]}>{summary}</Text> : null}
      </View>
      {!forceOpen ? <Text accessibilityElementsHidden style={[styles.arrow, { color: colors.accent }]}>{expanded ? '−' : '+'}</Text> : null}
    </Pressable>
    <View style={[styles.body, !expanded && styles.hidden]} accessibilityElementsHidden={!expanded}
      importantForAccessibility={expanded ? 'auto' : 'no-hide-descendants'}>{children}</View>
  </View>;
}

const styles = StyleSheet.create({
  section: { borderBottomWidth: StyleSheet.hairlineWidth, paddingVertical: 8 },
  heading: { minHeight: 56, flexDirection: 'row', alignItems: 'center', gap: 12 },
  copy: { flex: 1, gap: 4 },
  title: { fontSize: 16, fontWeight: '500' },
  summary: { fontSize: 13, lineHeight: 19 },
  arrow: { ...controlGlyphTypography, minWidth: 32, textAlign: 'center' },
  body: { gap: 14, paddingTop: 8, paddingBottom: 16 },
  hidden: { display: 'none' },
});
