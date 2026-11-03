import { usePresentationStyle, useThemedStyles, useThemeColors } from '../../styles/ThemeContext';
import type { ThemeColors } from '../../styles/theme';
import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { colors, controlGlyphTypography, radii, spacing } from '../../styles/theme';

type ToolLinkProps = {
  title: string;
  detail: string;
  status?: string;
  disabled?: boolean;
  onPress: () => void;
};

function ToolLink({ title, detail, status, disabled = false, onPress }: ToolLinkProps) {
  const styles = useThemedStyles(createStyles, 'ToolsScreen');
  const editorial = usePresentationStyle() === 'editorial';

  return (
    <Pressable
      accessibilityHint={detail}
      accessibilityLabel={status ? `${title}, ${status}` : title}
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [styles.link, editorial && styles.editorialLink, disabled && styles.disabled, pressed && !disabled && styles.pressed]}
    >
      <View style={styles.linkCopy}>
        <Text style={styles.linkTitle}>{title}</Text>
        <Text style={styles.linkDetail}>{detail}</Text>
      </View>
      {status ? <Text style={styles.status}>{status}</Text> : null}
      <Text accessibilityElementsHidden style={styles.chevron}>›</Text>
    </Pressable>
  );
}

type ToolsScreenProps = {
  embedded?: boolean;
  audioCount: number;
  demoMode: boolean;
  musetalkAvailable: boolean;
  runtimeRunning: boolean;
  onOpenAudio: () => void;
  onOpenConnection: () => void;
  onOpenFullscreen: () => void;
  onOpenCharacters?: () => void;
  children: React.ReactNode;
};

export function ToolsScreen({
  audioCount,
  demoMode,
  musetalkAvailable,
  runtimeRunning,
  onOpenAudio,
  onOpenConnection,
  onOpenFullscreen,
  onOpenCharacters,
  children, embedded = false,
}: ToolsScreenProps) {
  const styles = useThemedStyles(createStyles, 'ToolsScreen');
  const editorial = usePresentationStyle() === 'editorial';

  const [desktopOpen, setDesktopOpen] = React.useState(false);
  const desktopContent = <>
      <View style={styles.sectionHeading}>
        <Text style={styles.sectionTitle}>Avatar & desktop</Text>
        <Text style={styles.sectionMeta}>{musetalkAvailable ? 'Avatar available' : 'Avatar unavailable'} · {runtimeRunning ? 'Runtime running' : 'Runtime idle'}</Text>
      </View>
      {children}
  </>;
  const Container = embedded ? View : ScrollView;
  return (
    <Container style={embedded ? styles.embedded : styles.screen} {...(embedded ? {} : { contentContainerStyle: styles.content, keyboardShouldPersistTaps: 'handled' as const })}>
      {!embedded ? <View style={styles.heading}>
        <Text style={styles.eyebrow}>NC REMOTE</Text>
        <Text style={styles.title}>Tools</Text>
        {!editorial ? <Text style={styles.subtitle}>Session controls stay close without crowding your conversation.</Text> : null}
      </View> : null}
      <View style={styles.links}>
        {onOpenCharacters ? <ToolLink title="Chat characters" detail="Story cast, dialogue voices and portraits"
          status="Library" onPress={onOpenCharacters} /> : null}
        <ToolLink
          detail="Playback, autoplay, volume and queued speech"
          onPress={onOpenAudio}
          status={audioCount ? `${audioCount} queued` : 'Ready'}
          title="Phone audio"
        />
        <ToolLink
          detail="Pairing, LAN and secure Internet routes"
          onPress={onOpenConnection}
          status={demoMode ? 'Demo' : 'Manage'}
          title="Connection"
        />
        <ToolLink
          detail="Open the low-latency silk voice experience"
          onPress={onOpenFullscreen}
          status="Silk"
          title="Live full screen"
        />
      </View>
      {editorial ? <Pressable accessibilityRole="button" accessibilityState={{ expanded: desktopOpen }} onPress={() => setDesktopOpen(value => !value)} style={styles.editorialDisclosure}><Text style={styles.sectionTitle}>Avatar & desktop <Text style={controlGlyphTypography}>{desktopOpen ? "−" : "+"}</Text></Text><Text style={styles.sectionMeta}>{musetalkAvailable ? "Avatar available" : "Avatar unavailable"} · {runtimeRunning ? "Runtime running" : "Runtime idle"}</Text></Pressable> : null}
      {editorial ? <View style={!desktopOpen && styles.editorialHidden}>{desktopContent}</View> : desktopContent}
    </Container>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  editorialHidden: { display: "none" },
  editorialLink: { minHeight: 80, paddingHorizontal: 0, paddingVertical: 16 },
  editorialDisclosure: { minHeight: 64, justifyContent: "center", gap: 6, borderTopColor: colors.borderSoft, borderTopWidth: 1 },
  screen: { flex: 1 },
  embedded: { gap: spacing.lg },
  content: { gap: spacing.lg, padding: spacing.lg, paddingBottom: spacing.xl },
  heading: { gap: 4 },
  eyebrow: { color: colors.accent, fontSize: 10, fontWeight: '900', letterSpacing: 1.6 },
  title: { color: colors.text, fontSize: 30, fontWeight: '900', letterSpacing: -0.8 },
  subtitle: { color: colors.textSecondary, fontSize: 13, lineHeight: 19, maxWidth: 340 },
  links: { gap: spacing.sm },
  link: {
    alignItems: 'center',
    backgroundColor: colors.panel,
    borderColor: colors.borderSoft,
    borderRadius: radii.xl,
    borderWidth: 1,
    flexDirection: 'row',
    gap: spacing.sm,
    minHeight: 72,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  pressed: { backgroundColor: colors.panelAlt },
  disabled: { opacity: 0.45 },
  linkCopy: { flex: 1, minWidth: 0 },
  linkTitle: { color: colors.text, fontSize: 15, fontWeight: '800' },
  linkDetail: { color: colors.muted, fontSize: 11, lineHeight: 16, marginTop: 3 },
  status: { color: colors.accent, fontSize: 10, fontWeight: '800' },
  chevron: { color: colors.textSecondary, fontSize: 26, fontWeight: '300' },
  sectionHeading: { gap: 3, marginTop: spacing.sm },
  sectionTitle: { color: colors.text, fontSize: 18, fontWeight: '900' },
  sectionMeta: { color: colors.muted, fontSize: 11 },
});
