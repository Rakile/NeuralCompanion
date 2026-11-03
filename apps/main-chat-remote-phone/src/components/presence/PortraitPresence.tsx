import { useThemedStyles, useThemeColors } from '../../styles/ThemeContext';
import type { ThemeColors } from '../../styles/theme';
import React from 'react';
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';
import { rememberCaptureControl } from '../../diagnostics/captureControlTrail';

import type { RemoteClient } from '../../api/client';
import type { InlineVisualReply, MuseTalkState, PresenceState } from '../../api/types';
import type { VoiceThreadFrame } from '../../hooks/usePresenceSpectrum';
import type { AvatarPresentationRegistry } from '../../hooks/useAvatarPresentationTarget';
import { useAuthorizedMediaUrl } from '../../hooks/useAuthorizedMediaUrl';
import { colors, spacing } from '../../styles/theme';
import { shouldEmergeVisualReply } from '../../utils/inlineVisualReply';
import type { VoiceThreadPalette } from '../../utils/presenceControls';
import { LivingVoiceThread } from './LivingVoiceThread';
import { MoodAvatar } from './MoodAvatar';
import { AvatarPresentationTarget } from './AvatarPresentationTarget';

type PortraitPresenceProps = {
  presence: PresenceState | null;
  musetalk?: MuseTalkState;
  client: RemoteClient;
  threadFrame: VoiceThreadFrame;
  reduceMotion?: boolean;
  latestVisualReply?: InlineVisualReply;
  visualSessionStartedAt: number;
  dismissedVisualIds: ReadonlySet<string>;
  onDismissVisual: (id: string) => void;
  onOpenChat: () => void;
  onTalk: () => void;
  onOpenMore: () => void;
  onAvatarLongPress: () => void;
  paletteMode: VoiceThreadPalette;
  liveControls?: React.ReactNode;
  presentationTarget?: AvatarPresentationRegistry;
  showActions?: boolean;
};

function EmergingVisual({ item, client, onDismiss }: { item: InlineVisualReply; client: RemoteClient; onDismiss: () => void }) {
  const styles = useThemedStyles(createStyles);

  const media = useAuthorizedMediaUrl(client, String(item.url_path || ''), { v: String(item.updated_at || '') });
  return (
    <View style={styles.emergence}>
      {media.url ? <Image source={{ uri: media.url }} resizeMode="cover" style={styles.emergenceImage} /> : null}
      <View style={styles.emergenceCopy}>
        <Text style={styles.emergenceTitle}>Visual Reply</Text>
        <Text numberOfLines={2} style={styles.emergenceCaption}>{item.caption || item.prompt_preview || 'A new visual is ready.'}</Text>
      </View>
      <Pressable accessibilityLabel="Dismiss Visual Reply" accessibilityRole="button" onPress={onDismiss} style={styles.close}><Text style={styles.closeText}>×</Text></Pressable>
    </View>
  );
}

export function PortraitPresence({
  presence,
  musetalk,
  client,
  threadFrame,
  reduceMotion = false,
  latestVisualReply,
  visualSessionStartedAt,
  dismissedVisualIds,
  onDismissVisual,
  onOpenChat,
  onTalk,
  onOpenMore,
  onAvatarLongPress,
  paletteMode,
  liveControls,
  presentationTarget,
  showActions = true,
}: PortraitPresenceProps) {
  const styles = useThemedStyles(createStyles);

  const activity = presence?.activity || 'ready';
  const mood = presence?.mood || 'neutral';
  const emerge = shouldEmergeVisualReply(latestVisualReply, dismissedVisualIds, visualSessionStartedAt);
  const identityOverlay = <>
    <View style={styles.identityOverlay}>
      <Text style={styles.name}>{presence?.persona?.name || 'Companion'}</Text>
      <Text style={styles.state}>{presence?.state_label || 'Ready'} · {mood}</Text>
    </View>
    {emerge && latestVisualReply ? (
      <EmergingVisual item={latestVisualReply} client={client} onDismiss={() => onDismissVisual(latestVisualReply.id)} />
    ) : null}
  </>;
  const avatar = <MoodAvatar presence={presence} musetalk={musetalk} client={client} variant="portrait" onLongPress={onAvatarLongPress} />;
  return (
    <View style={styles.container}>
      {presentationTarget ? <AvatarPresentationTarget presentationTarget={presentationTarget} targetId="portrait"
        identity={presence?.persona?.name || 'Companion'} borderRadius={0} onLongPress={onAvatarLongPress}
        overlay={identityOverlay} metadataRevision={`${presence?.persona?.name || 'Companion'}:${presence?.state_label || 'Ready'}:${mood}:${emerge ? latestVisualReply?.id || '' : ''}:${latestVisualReply?.updated_at || ''}`}
        style={styles.portraitStage}>{avatar}</AvatarPresentationTarget>
        : <View style={styles.portraitStage}>{avatar}{identityOverlay}</View>}
      {showActions ? <><View style={styles.thread}><LivingVoiceThread activity={activity} mood={mood} frame={threadFrame} reduceMotion={reduceMotion} paletteMode={paletteMode} /></View>
      {liveControls}
      <View style={styles.actions}>
        <Pressable accessibilityLabel="Open conversation chat" accessibilityRole="button" onPress={onOpenChat} style={styles.action}><Text style={styles.actionText}>Open chat</Text></Pressable>
        <Pressable accessibilityLabel="Record voice message" accessibilityRole="button" onPress={() => { rememberCaptureControl('portrait_talk'); onTalk(); }} style={[styles.action, styles.talk]}><Text style={styles.actionText}>Talk</Text></Pressable>
        <Pressable accessibilityLabel="Open tools" accessibilityRole="button" onPress={onOpenMore} style={styles.action}><Text style={styles.actionText}>More</Text></Pressable>
      </View></> : null}
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  container: { backgroundColor: colors.background, flex: 1, gap: spacing.sm, padding: spacing.md },
  portraitStage: { borderRadius: 0, borderWidth: 0, flex: 1, minHeight: 100, overflow: 'hidden', position: 'relative' },
  identityOverlay: { backgroundColor: 'rgba(2,6,10,0.72)', bottom: 0, left: 0, padding: spacing.md, position: 'absolute', right: 0 },
  name: { color: colors.text, fontSize: 24, fontWeight: '900' },
  state: { color: colors.textSecondary, fontSize: 13, marginTop: 2, textTransform: 'capitalize' },
  thread: { backgroundColor: colors.background, borderRadius: 18, overflow: 'hidden', paddingHorizontal: spacing.sm },
  actions: { flexDirection: 'row', gap: spacing.sm },
  action: { alignItems: 'center', borderColor: colors.border, borderRadius: 999, borderWidth: 1, flex: 1, justifyContent: 'center', minHeight: 44, paddingHorizontal: spacing.md },
  talk: { backgroundColor: colors.accentSoft, borderColor: colors.accent },
  actionText: { color: colors.text, fontSize: 12, fontWeight: '900' },
  emergence: { backgroundColor: colors.panel, borderColor: colors.accent, borderRadius: 16, borderWidth: 1, left: spacing.md, overflow: 'hidden', position: 'absolute', right: spacing.md, top: spacing.md },
  emergenceImage: { aspectRatio: 16 / 9, width: '100%' },
  emergenceCopy: { padding: spacing.sm },
  emergenceTitle: { color: colors.accent, fontSize: 11, fontWeight: '900', textTransform: 'uppercase' },
  emergenceCaption: { color: colors.text, fontSize: 12, lineHeight: 17, marginTop: 3 },
  close: { alignItems: 'center', backgroundColor: 'rgba(0,0,0,0.6)', borderRadius: 22, height: 44, justifyContent: 'center', position: 'absolute', right: 8, top: 8, width: 44 },
  closeText: { color: '#fff', fontSize: 23, lineHeight: 25 },
});
