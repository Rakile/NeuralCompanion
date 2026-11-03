import React from 'react';
import { Image, Pressable, StyleSheet, Text } from 'react-native';
import type { RemoteClient } from '../../api/client';
import type { PresenceState } from '../../api/types';
import { useAuthorizedMediaUrl } from '../../hooks/useAuthorizedMediaUrl';

// Header identity is a still neutral portrait, independent of mood/video playback.
export function NeutralHeaderAvatar({ presence, client, onPress, speakerName, portraitPath }: {
  presence: PresenceState | null; client: RemoteClient; onPress: () => void;
  speakerName?: string; portraitPath?: string;
}) {
  const path = speakerName ? portraitPath || '' : presence?.avatar?.neutral_url_path
    || (presence?.avatar?.kind === 'neutral' ? presence.avatar.url_path : '') || '';
  const media = useAuthorizedMediaUrl(client, path);
  const [failedUrl, setFailedUrl] = React.useState('');
  const portrait = Boolean(media.url && !media.error && failedUrl !== media.url);
  return <Pressable accessibilityRole="button" accessibilityLabel={`${speakerName || presence?.persona?.name || 'Companion'}: choose persona`}
    onPress={onPress} style={styles.avatar}>
    {speakerName && !portrait ? <Text style={styles.initial}>{speakerName.slice(0, 1).toUpperCase()}</Text>
      : <Image source={portrait ? { uri: media.url } : require('../../../assets/desktop-app-icon.png')}
        resizeMode={portrait ? 'cover' : 'contain'} style={styles.avatar}
        onError={() => setFailedUrl(media.url)} />}
  </Pressable>;
}
const styles = StyleSheet.create({
  avatar: { width: 48, height: 48, borderWidth: 0, borderRadius: 0, alignItems: 'center', justifyContent: 'center' },
  initial: { color: '#63D8FF', fontSize: 28, fontWeight: '700' },
});
