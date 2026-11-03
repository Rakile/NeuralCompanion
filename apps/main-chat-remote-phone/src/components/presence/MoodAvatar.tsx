import React from 'react';
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';

import type { RemoteClient } from '../../api/client';
import type { MuseTalkState, PresenceState } from '../../api/types';
import { useAuthorizedMediaUrl } from '../../hooks/useAuthorizedMediaUrl';
import { presenceMoodPalette } from '../../utils/presenceState';
import { useAVPreview } from '../../native/useAVPreview';

type MoodAvatarProps = {
  presence: PresenceState | null | undefined;
  musetalk?: MuseTalkState;
  client: RemoteClient;
  variant: 'message' | 'header' | 'portrait';
  overridePath?: string;
  initials?: string;
  mood?: string;
  contentFit?: 'cover' | 'contain';
  onLongPress?: () => void;
  size?: number;
};

type Candidate = { kind: 'musetalk' | 'mood' | 'neutral'; path: string; version: string };

export function MoodAvatar({ presence, musetalk, client, variant, overridePath = '', initials, mood, contentFit = 'cover', onLongPress, size }: MoodAvatarProps) {
  const liveMood = mood || presence?.mood || 'neutral';
  const palette = presenceMoodPalette(liveMood);
  const latestFeed = musetalk?.feed?.length ? musetalk.feed[musetalk.feed.length - 1] : undefined;
  const latestFrame = musetalk?.frames?.length ? musetalk.frames[musetalk.frames.length - 1] : undefined;
  const museTalkPath = musetalk?.state?.frame_url_path || latestFeed?.frame_url_path || latestFrame?.url_path || '';
  const moodPath = overridePath || presence?.avatar?.mood_url_path || (presence?.avatar?.kind === 'mood' ? presence.avatar.url_path : '') || '';
  const neutralPath = presence?.avatar?.neutral_url_path || (presence?.avatar?.kind === 'neutral' ? presence.avatar.url_path : '') || '';
  const museTalkVersion = String(latestFeed?._seq ?? musetalk?.state?.updated_at ?? '');
  // Refreshing a still frame must not temporarily replace the avatar with initials.
  // Retention is limited to the same persona/stream and the hook's credential owner.
  const frameOwner = presence?.persona?.id
    ? JSON.stringify([presence.stream_id, presence.persona.id]) : '';
  const preview = useAVPreview(client, museTalkPath, museTalkVersion, frameOwner);
  const museTalkMedia = useAuthorizedMediaUrl(client, preview.path, { v: preview.version }, frameOwner);
  const moodMedia = useAuthorizedMediaUrl(client, moodPath);
  const neutralMedia = useAuthorizedMediaUrl(client, neutralPath);
  const [failedKinds, setFailedKinds] = React.useState<Set<Candidate['kind']>>(new Set());

  React.useEffect(() => {
    setFailedKinds(new Set());
  }, [client.identityKey, moodPath, museTalkPath, museTalkVersion, neutralPath]);

  const candidates: Candidate[] = [];
  if (presence?.musetalk?.healthy && museTalkPath && !museTalkMedia.error) candidates.push({ kind: 'musetalk', path: museTalkMedia.url, version: museTalkPath });
  if (moodPath && !moodMedia.error) candidates.push({ kind: 'mood', path: moodMedia.url, version: moodPath });
  if (neutralPath && neutralPath !== moodPath && !neutralMedia.error) candidates.push({ kind: 'neutral', path: neutralMedia.url, version: neutralPath });
  const selected = candidates.find((candidate) => candidate.path && !failedKinds.has(candidate.kind));
  const sizeStyle = variant === 'portrait' ? styles.portrait : variant === 'header' ? styles.header : styles.message;
  const conversationSize = variant === 'message' && size ? { width: Math.max(48, Math.min(128, size)), height: Math.max(48, Math.min(128, size)) } : undefined;
  const fallbackInitials = String(initials || presence?.persona?.initials || 'NC').slice(0, 2).toUpperCase();

  const content = selected ? (
      <Image
        accessible={!onLongPress}
        accessibilityLabel={`${presence?.persona?.name || 'Companion'}, ${liveMood} mood`}
        source={{ uri: selected.path }}
        resizeMode={contentFit}
        style={[styles.image, sizeStyle, conversationSize]}
        onError={() => setFailedKinds((current) => new Set(current).add(selected.kind))}
      />
    ) : (
    <View
      accessible={!onLongPress}
      accessibilityLabel={`${presence?.persona?.name || 'Companion'} initials, ${liveMood} mood`}
      style={[styles.initials, sizeStyle, conversationSize, { backgroundColor: palette.muted }]}
    >
      <Text style={[styles.initialsText, variant === 'portrait' && styles.portraitInitials]}>{fallbackInitials}</Text>
    </View>
  );
  if (!onLongPress) {
    return content;
  }
  return (
    <Pressable
      accessibilityHint="Long press to open Companion controls and conversation avatar size"
      accessibilityLabel={`${presence?.persona?.name || 'Companion'} avatar. Companion controls`}
      accessibilityRole="button"
      hitSlop={variant === 'message' ? 4 : 0}
      onAccessibilityTap={onLongPress}
      delayLongPress={450}
      onLongPress={onLongPress}
      style={variant === 'portrait' ? styles.portraitPressable : undefined}
    >
      {content}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  image: { borderWidth: 0, overflow: 'hidden' },
  initials: { alignItems: 'center', borderWidth: 0, justifyContent: 'center', overflow: 'hidden' },
  initialsText: { color: '#f7fbff', fontSize: 13, fontWeight: '900' },
  portraitInitials: { fontSize: 52 },
  message: { borderRadius: 0, height: 36, width: 36 },
  header: { borderRadius: 0, height: 48, width: 48 },
  portrait: { borderRadius: 0, height: '100%', width: '100%' },
  portraitPressable: { height: '100%', width: '100%' },
});
