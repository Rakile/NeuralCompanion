import { useThemedStyles, useThemeColors } from '../styles/ThemeContext';
import type { ThemeColors } from '../styles/theme';
import React from 'react';
import { Image, Modal, Pressable, StyleSheet, Text, View } from 'react-native';

import type { RemoteClient } from '../api/client';
import type { InlineVisualReply, MuseTalkState, PresenceState } from '../api/types';
import type { PlaybackState } from '../hooks/useAudioQueue';
import { usePresenceSpectrum } from '../hooks/usePresenceSpectrum';
import { useReducedMotion } from '../hooks/useReducedMotion';
import type { CompanionDisplayMode } from '../utils/companionDisplayMode';
import type { VoiceThreadPalette } from '../utils/presenceControls';
import { useAuthorizedMediaUrl } from '../hooks/useAuthorizedMediaUrl';
import type { AvatarPresentationRegistry } from '../hooks/useAvatarPresentationTarget';
import { colors, spacing } from '../styles/theme';
import { LivingVoiceThread } from './presence/LivingVoiceThread';
import { MoodAvatar } from './presence/MoodAvatar';
import { PortraitPresence } from './presence/PortraitPresence';
import { PresenceHeader } from './presence/PresenceHeader';
import { AvatarPresentationTarget } from './presence/AvatarPresentationTarget';
import { VisualReplyMediaActions } from './InlineVisualReply';
import { ZoomableImage } from './ZoomableImage';

type CompanionSurfaceProps = {
  mode: CompanionDisplayMode;
  presence: PresenceState | null;
  musetalk?: MuseTalkState;
  client: RemoteClient;
  playback: PlaybackState;
  meteringDb: number | null | undefined;
  meteringRevision: number;
  animationEnabled: boolean;
  spectrumFps: number;
  showPresenceControls: boolean;
  showTopVoiceThread?: boolean;
  showHeader?: boolean;
  voiceThreadPalette: VoiceThreadPalette;
  onAvatarLongPress: () => void;
  liveControls?: React.ReactNode;
  chatFeed: React.ReactNode;
  composer: React.ReactNode;
  useControlsDock?: boolean;
  latestVisualReply?: InlineVisualReply;
  visualSessionStartedAt: number;
  dismissedVisualIds: ReadonlySet<string>;
  focusedVisualReply?: InlineVisualReply;
  onDismissVisual: (id: string) => void;
  onCloseFocusedVisual: () => void;
  onModeChange: (mode: CompanionDisplayMode) => void;
  onTalk: () => void;
  onOpenMore: () => void;
  commandsAvailable: boolean;
  presentationTarget?: AvatarPresentationRegistry;
};

type PresenceExperienceProps = Omit<
  CompanionSurfaceProps,
  'chatFeed' | 'composer' | 'focusedVisualReply' | 'onCloseFocusedVisual' | 'commandsAvailable'
>;

const PresenceExperience = React.memo(function PresenceExperience({
  mode,
  presence,
  musetalk,
  client,
  playback,
  meteringDb,
  meteringRevision,
  animationEnabled,
  spectrumFps,
  showPresenceControls,
  showTopVoiceThread = true,
  showHeader = true,
  useControlsDock = false,
  voiceThreadPalette,
  latestVisualReply,
  visualSessionStartedAt,
  dismissedVisualIds,
  onDismissVisual,
  onModeChange,
  onTalk,
  onOpenMore,
  onAvatarLongPress,
  liveControls,
  presentationTarget,
}: PresenceExperienceProps) {
  const styles = useThemedStyles(createStyles);

  const activity = presence?.activity || 'ready';
  const mood = presence?.mood || 'neutral';
  const reducedMotion = useReducedMotion();
  const threadFrame = usePresenceSpectrum(
    client,
    playback,
    activity,
    meteringDb,
    meteringRevision,
    animationEnabled,
    reducedMotion,
    spectrumFps,
  );

  return (
    <>
      {showHeader ? <PresenceHeader
        presence={presence}
        musetalk={musetalk}
        client={client}
        frame={threadFrame}
        mode={mode}
        onModeChange={onModeChange}
        onAvatarLongPress={onAvatarLongPress}
        paletteMode={voiceThreadPalette}
        reduceMotion={reducedMotion}
        showControls={showPresenceControls}
        showThread={showTopVoiceThread}
        compact={useControlsDock || !showPresenceControls}
      /> : null}
      {mode === 'companion' ? (
        <View style={[styles.hero, useControlsDock && styles.heroExpanded]}>
          {presentationTarget ? <AvatarPresentationTarget presentationTarget={presentationTarget} targetId="companion"
            identity={presence?.persona?.name || 'Companion'} borderRadius={0} onLongPress={onAvatarLongPress}
            metadataRevision={`${presence?.persona?.name || 'Companion'}:${activity}:${mood}`} style={[styles.heroAvatar, useControlsDock && styles.heroAvatarExpanded]}>
            <MoodAvatar presence={presence} musetalk={musetalk} client={client} variant="portrait" onLongPress={onAvatarLongPress} />
          </AvatarPresentationTarget> : <View style={[styles.heroAvatar, useControlsDock && styles.heroAvatarExpanded]}><MoodAvatar presence={presence} musetalk={musetalk} client={client} variant="portrait" onLongPress={onAvatarLongPress} /></View>}
          {!useControlsDock ? <View style={styles.heroThread}><LivingVoiceThread activity={activity} mood={mood} frame={threadFrame} reduceMotion={reducedMotion} paletteMode={voiceThreadPalette} /></View> : null}
        </View>
      ) : null}
      {mode === 'portrait' ? (
        <PortraitPresence
          presence={presence}
          musetalk={musetalk}
          client={client}
          threadFrame={threadFrame}
          reduceMotion={reducedMotion}
          latestVisualReply={latestVisualReply}
          visualSessionStartedAt={visualSessionStartedAt}
          dismissedVisualIds={dismissedVisualIds}
          onDismissVisual={onDismissVisual}
          onOpenChat={() => onModeChange('conversation')}
          onTalk={onTalk}
          onOpenMore={onOpenMore}
          onAvatarLongPress={onAvatarLongPress}
          paletteMode={voiceThreadPalette}
          liveControls={liveControls}
          presentationTarget={presentationTarget}
          showActions={!useControlsDock}
        />
      ) : null}
    </>
  );
});

function FocusedVisualReply({ item, client, onClose, disabled }: { item: InlineVisualReply; client: RemoteClient; onClose: () => void; disabled: boolean }) {
  const styles = useThemedStyles(createStyles);

  const media = useAuthorizedMediaUrl(client, String(item.url_path || ''), { v: String(item.updated_at || '') });
  const demoArtwork = item.content_type === 'image/demo';
  return (
    <Modal animationType="fade" transparent visible onRequestClose={onClose}>
      <View style={styles.modalBackdrop}>
        <View style={styles.modalCard}>
          {media.url ? <ZoomableImage uri={media.url} style={styles.focusedImage} onReload={media.reload} /> : demoArtwork ? (
            <View style={[styles.focusedImage, styles.focusedDemo]}><Text style={styles.focusedDemoText}>DEMO VISUAL REPLY</Text></View>
          ) : <Text style={styles.modalText}>{media.error || 'Loading Visual Reply...'}</Text>}
          {media.error ? <Pressable accessibilityRole="button" accessibilityLabel="Reload image" disabled={disabled}
            style={styles.closeButton} onPress={media.reload}><Text style={styles.closeButtonText}>Reload image</Text></Pressable> : null}
          {item.caption ? <Text style={styles.modalText}>{item.caption}</Text> : null}
          <VisualReplyMediaActions item={item} mediaUrl={media.url} disabled={disabled} />
          <Pressable accessibilityLabel="Close Visual Reply" accessibilityRole="button" onPress={onClose} style={styles.closeButton}><Text style={styles.closeButtonText}>Close</Text></Pressable>
        </View>
      </View>
    </Modal>
  );
}

export function CompanionSurface(props: CompanionSurfaceProps) {
  const styles = useThemedStyles(createStyles);

  const {
    mode, presence, musetalk, client, playback, meteringDb, meteringRevision, animationEnabled, spectrumFps, showPresenceControls, showTopVoiceThread, voiceThreadPalette, onAvatarLongPress, liveControls, chatFeed, composer,
    latestVisualReply, visualSessionStartedAt, dismissedVisualIds, focusedVisualReply,
    onDismissVisual, onCloseFocusedVisual, onModeChange, onTalk, onOpenMore, commandsAvailable,
    presentationTarget, useControlsDock = false, showHeader = true,
  } = props;
  return (
    <View style={styles.surface}>
      <PresenceExperience
        mode={mode}
        presence={presence}
        musetalk={musetalk}
        client={client}
        playback={playback}
        meteringDb={meteringDb}
        meteringRevision={meteringRevision}
        animationEnabled={animationEnabled}
        spectrumFps={spectrumFps}
        showPresenceControls={showPresenceControls}
        showTopVoiceThread={showTopVoiceThread}
        showHeader={showHeader}
        voiceThreadPalette={voiceThreadPalette}
        latestVisualReply={latestVisualReply}
        visualSessionStartedAt={visualSessionStartedAt}
        dismissedVisualIds={dismissedVisualIds}
        onDismissVisual={onDismissVisual}
        onModeChange={onModeChange}
        onTalk={onTalk}
        onOpenMore={onOpenMore}
        onAvatarLongPress={onAvatarLongPress}
        liveControls={liveControls}
        presentationTarget={presentationTarget}
        useControlsDock={useControlsDock}
      />
      {mode === 'companion' && useControlsDock ? <View style={styles.chatPreview}>
        <View style={styles.previewHeading}><Text style={styles.previewLabel}>Conversation</Text>
          <Pressable accessibilityRole="button" accessibilityLabel="Open conversation chat" onPress={() => onModeChange('conversation')} style={styles.openChat}>
            <Text style={styles.previewLink}>Open chat ›</Text>
          </Pressable></View>
        {chatFeed}
      </View> : mode !== 'portrait' ? <>{chatFeed}{composer}</> : null}
      {focusedVisualReply ? <FocusedVisualReply item={focusedVisualReply} client={client} onClose={onCloseFocusedVisual} disabled={!commandsAvailable} /> : null}
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  surface: { backgroundColor: colors.background, flex: 1 },
  hero: { alignItems: 'center', backgroundColor: colors.background, borderBottomColor: colors.border, borderBottomWidth: 1, flexDirection: 'row', gap: spacing.md, padding: spacing.md },
  heroAvatar: { height: 112, width: 112 },
  heroExpanded: { flex: 1, minHeight: 100, padding: 0, gap: 0, flexDirection: 'column' },
  heroAvatarExpanded: { flex: 1, height: undefined, width: '100%' },
  chatPreview: { flex: 0.5, maxHeight: 210, minHeight: 90 },
  previewHeading: { flexDirection:'row', alignItems:'center', justifyContent:'space-between', paddingHorizontal:spacing.md },
  previewLabel: { color:colors.muted, fontSize:12 },
  previewLink: { color:colors.accent, fontSize:12 },
  openChat: { minHeight:44, justifyContent:'center', paddingHorizontal:spacing.sm },
  heroThread: { flex: 1 },
  modalBackdrop: { alignItems: 'center', backgroundColor: 'rgba(0,0,0,0.9)', flex: 1, justifyContent: 'center', padding: spacing.lg },
  modalCard: { backgroundColor: colors.panel, borderColor: colors.border, borderRadius: 18, borderWidth: 1, gap: spacing.md, maxHeight: '88%', padding: spacing.md, width: '100%' },
  focusedImage: { aspectRatio: 1, borderRadius: 12, width: '100%' },
  focusedDemo: { alignItems: 'center', backgroundColor: '#102b45', justifyContent: 'center' },
  focusedDemoText: { color: '#dff8ff', fontSize: 15, fontWeight: '900', letterSpacing: 1.5 },
  modalText: { color: colors.text, fontSize: 13, lineHeight: 18 },
  closeButton: { alignItems: 'center', borderColor: colors.accent, borderRadius: 999, borderWidth: 1, padding: spacing.md },
  closeButtonText: { color: colors.text, fontWeight: '900' },
});
