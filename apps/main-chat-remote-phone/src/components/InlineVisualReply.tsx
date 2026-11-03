import { useThemedStyles, useThemeColors } from '../styles/ThemeContext';
import type { ThemeColors } from '../styles/theme';
import React from 'react';
import { ActivityIndicator, Image, Pressable, ScrollView, Share, StyleSheet, Text, View } from 'react-native';
import * as FileSystem from 'expo-file-system/legacy';
import * as MediaLibrary from 'expo-media-library';
import * as Sharing from 'expo-sharing';

import type { RemoteClient } from '../api/client';
import type { InlineVisualReply as InlineVisualReplyItem } from '../api/types';
import { useAuthorizedMediaUrl } from '../hooks/useAuthorizedMediaUrl';
import { colors, spacing } from '../styles/theme';
import { orderedVisualReplies, visualReplyPresentation } from '../utils/inlineVisualReply';
import { withVisualReplyExport, visualReplyMedia } from '../utils/visualReplyMedia';
import type { VisualDisplay } from '../utils/visualDisplay';

type InlineVisualReplyProps = {
  items: readonly InlineVisualReplyItem[];
  client: RemoteClient;
  disabled?: boolean;
  onOpen: (item: InlineVisualReplyItem) => void;
  onRetry: (item: InlineVisualReplyItem) => Promise<void>;
  onOpenVisual: () => void;
  onImageSizeResolved?: () => void;
  display?: VisualDisplay;
};

export function VisualReplyMediaActions({
  item,
  mediaUrl,
  disabled = false,
}: {
  item: InlineVisualReplyItem;
  mediaUrl: string;
  disabled?: boolean;
}) {
  const styles = useThemedStyles(createStyles);

  const [actionBusy, setActionBusy] = React.useState(false);
  const [actionError, setActionError] = React.useState('');
  const [actionStatus, setActionStatus] = React.useState('');
  const actionOwner = React.useRef({ key: `${item.id}:${mediaUrl}`, busy: false });
  if (actionOwner.current.key !== `${item.id}:${mediaUrl}`) actionOwner.current = { key: `${item.id}:${mediaUrl}`, busy: false };
  React.useEffect(() => { setActionBusy(false); setActionError(''); setActionStatus(''); }, [item.id, mediaUrl]);
  if (!mediaUrl || item.content_type === 'image/demo') return null;
  const { extension, mimeType } = visualReplyMedia(item.content_type, item.url_path);

  const run = async (sharing: boolean) => {
    const owner = actionOwner.current;
    if (owner.busy || disabled) return;
    owner.busy = true; setActionBusy(true); setActionError(''); setActionStatus('');
    try {
      if (!sharing) {
        const permission = await MediaLibrary.requestPermissionsAsync(true, ['photo']);
        if (!permission.granted) throw new Error('Photo library permission is required to save. You can still Share this image.');
      }
      await withVisualReplyExport(FileSystem, mediaUrl, extension, async uri => {
        if (!sharing) await MediaLibrary.saveToLibraryAsync(uri);
        else if (await Sharing.isAvailableAsync()) await Sharing.shareAsync(uri, { dialogTitle: 'Share Visual Reply', mimeType });
        else await Share.share({ url: uri, message: 'NeuralCompanion Visual Reply' });
      }, sharing);
      if (!sharing && actionOwner.current === owner) setActionStatus('Saved to Photos.');
    } catch (exc) {
      if (actionOwner.current === owner) setActionError(exc instanceof Error ? exc.message : 'Could not export Visual Reply.');
    } finally { owner.busy = false; if (actionOwner.current === owner) setActionBusy(false); }
  };

  return (
    <>
      <View style={styles.actions}>
        <Pressable accessibilityLabel="Save Visual Reply" accessibilityRole="button" accessibilityState={{ disabled: actionBusy || disabled }} disabled={actionBusy || disabled} onPress={() => void run(false)} style={styles.action}><Text style={styles.actionText}>Save</Text></Pressable>
        <Pressable accessibilityLabel="Share Visual Reply" accessibilityRole="button" accessibilityState={{ disabled: actionBusy || disabled }} disabled={actionBusy || disabled} onPress={() => void run(true)} style={styles.action}><Text style={styles.actionText}>Share</Text></Pressable>
      </View>
      {actionError ? <Text style={styles.error}>{actionError}</Text> : null}
      {actionBusy ? <Text accessibilityLiveRegion="polite" style={styles.status}>Preparing image…</Text> : null}
      {actionStatus ? <Text accessibilityLiveRegion="polite" style={styles.status}>{actionStatus}</Text> : null}
    </>
  );
}

function VisualReplyCard({
  item,
  client,
  disabled,
  onOpen,
  onRetry,
  onOpenVisual,
  onImageSizeResolved,
  display = { layout: 'fit', frame: true },
}: Omit<InlineVisualReplyProps, 'items'> & { item: InlineVisualReplyItem }) {
  const styles = useThemedStyles(createStyles);

  const media = useAuthorizedMediaUrl(client, disabled ? '' : String(item.url_path || ''), {
    v: String(item.updated_at || ''),
  });
  const presentation = visualReplyPresentation(item);
  const demoArtwork = item.content_type === 'image/demo';
  const [failedUrl, setFailedUrl] = React.useState('');
  // Signed URLs rotate independently of the image; keep its measured frame.
  const mediaIdentity = `${item.id}:${item.url_path || ''}:${item.updated_at || ''}`;
  const [naturalSize, setNaturalSize] = React.useState({ identity: mediaIdentity, ratio: 4 / 3, known: false });
  const naturalRatio = naturalSize.identity === mediaIdentity ? naturalSize.ratio : 4 / 3;
  React.useEffect(() => {
    if (display.layout !== 'fill' || !media.url || presentation.kind !== 'image'
      || (naturalSize.identity === mediaIdentity && naturalSize.known)) return;
    let current = true;
    Image.getSize(media.url, (width, height) => {
      if (!current) return;
      const ratio = width > 0 && height > 0 ? width / height : 4 / 3;
      if (Math.abs(ratio - naturalRatio) > .01) onImageSizeResolved?.();
      setNaturalSize({ identity: mediaIdentity, ratio, known: true });
    }, () => undefined);
    return () => { current = false; };
  }, [media.url, mediaIdentity, display.layout, presentation.kind, naturalSize.identity,
    naturalSize.known, naturalRatio, onImageSizeResolved]);
  const cardStyle = [styles.card, display.layout === 'fill' && styles.cardFill,
    !display.frame && styles.cardNoFrame];
  const imageStyle = [styles.image, display.layout === 'fill' && { aspectRatio: naturalRatio },
    !display.frame && styles.imageNoFrame];
  const loadingError = media.error || (failedUrl && failedUrl === media.url ? 'Could not load this image.' : '');
  const [retryBusy, setRetryBusy] = React.useState(false);
  const [retryError, setRetryError] = React.useState('');
  const retry = async () => {
    if (disabled || retryBusy) return;
    setRetryBusy(true);
    setRetryError('');
    try {
      await onRetry(item);
    } catch (exc) {
      setRetryError(exc instanceof Error ? exc.message : 'Could not retry Visual Reply.');
    } finally {
      setRetryBusy(false);
    }
  };

  if (presentation.kind === 'progress') {
    return <View style={cardStyle}>
      <View style={imageStyle}><ActivityIndicator color="#64d9ff" /></View>
      <Text style={styles.status}>{presentation.label}</Text>
    </View>;
  }
  if (loadingError && !demoArtwork && presentation.kind !== 'error') {
    return <View style={cardStyle}>
      <Text accessibilityRole="alert" style={styles.error}>{loadingError}</Text>
      <Pressable accessibilityRole="button" accessibilityLabel="Reload image" disabled={disabled}
        onPress={() => { setFailedUrl(''); media.reload(); }} style={styles.action}><Text style={styles.actionText}>Reload image</Text></Pressable>
    </View>;
  }
  if (presentation.kind === 'error') {
    return (
      <View style={cardStyle}>
        <Text style={styles.error}>{presentation.label}</Text>
        <View style={styles.actions}>
          <Pressable accessibilityLabel="Retry Visual Reply" accessibilityRole="button" accessibilityState={{ busy: retryBusy, disabled: disabled || retryBusy }} disabled={disabled || retryBusy} onPress={() => void retry()} style={styles.action}><Text style={styles.actionText}>{retryBusy ? 'Retrying…' : 'Retry'}</Text></Pressable>
          <Pressable accessibilityLabel="Open Visual screen" accessibilityRole="button" onPress={onOpenVisual} style={styles.action}><Text style={styles.actionText}>Visual</Text></Pressable>
        </View>
        {retryError ? <Text accessibilityRole="alert" style={styles.error}>{retryError}</Text> : null}
      </View>
    );
  }
  return (
    <View style={cardStyle}>
      {media.url ? <Pressable accessibilityLabel="Open Visual Reply" accessibilityRole="button" onPress={() => onOpen(item)}><Image source={{ uri: media.url }} onError={() => setFailedUrl(media.url)} style={imageStyle} resizeMode="contain" /></Pressable> : demoArtwork ? (
        <Pressable accessibilityLabel="Open demo Visual Reply" accessibilityRole="button" onPress={() => onOpen(item)} style={styles.demoArtwork}>
          <View style={styles.demoMoon} />
          <View style={styles.demoTower} />
          <Text style={styles.demoLabel}>DEMO VISUAL</Text>
        </Pressable>
      ) : <View style={imageStyle}><ActivityIndicator color="#64d9ff" /></View>}
      {item.caption ? <Text style={styles.caption}>{item.caption}</Text> : null}
      <View style={styles.actions}>
        <Pressable accessibilityLabel="Open Visual Reply" accessibilityRole="button" accessibilityState={{ disabled }} disabled={disabled} onPress={() => onOpen(item)} style={styles.action}><Text style={styles.actionText}>Open</Text></Pressable>
      </View>
      <VisualReplyMediaActions item={item} mediaUrl={media.url} disabled={disabled} />
    </View>
  );
}

export function InlineVisualReply({ items, client, disabled = false, onOpen, onRetry, onOpenVisual,
  onImageSizeResolved,
  display = { layout: 'fit', frame: true } }: InlineVisualReplyProps) {
  const styles = useThemedStyles(createStyles);

  const ordered = orderedVisualReplies(items);
  if (!ordered.length) return null;
  const cards = ordered.map((item) => (
    <VisualReplyCard key={item.id} item={item} client={client} disabled={disabled} onOpen={onOpen}
      onRetry={onRetry} onOpenVisual={onOpenVisual} onImageSizeResolved={onImageSizeResolved} display={display} />
  ));
  if (display.layout === 'fill') return <View style={[styles.gallery, styles.galleryFill]}>{cards}</View>;
  if (cards.length === 1) return <View style={styles.gallery}>{cards}</View>;
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.gallery}>
      {cards}
    </ScrollView>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  gallery: { gap: spacing.sm, paddingVertical: spacing.xs },
  galleryFill: { flexDirection: 'column', width: '100%' },
  card: { backgroundColor: colors.panel, borderColor: colors.border, borderRadius: 14, borderWidth: 1, gap: spacing.xs, justifyContent: 'center', minHeight: 96, padding: spacing.sm, width: 250 },
  cardFill: { width: '100%' },
  cardNoFrame: { backgroundColor: 'transparent', borderWidth: 0, borderRadius: 0, paddingHorizontal: 0 },
  image: { alignItems: 'center', aspectRatio: 4 / 3, borderRadius: 10, justifyContent: 'center', width: '100%' },
  imageNoFrame: { borderRadius: 0 },
  caption: { color: colors.text, fontSize: 12, lineHeight: 17 },
  status: { color: colors.muted, fontSize: 12, textAlign: 'center' },
  error: { color: colors.danger, fontSize: 11, lineHeight: 15 },
  actions: { flexDirection: 'row', gap: spacing.xs },
  action: { alignItems: 'center', borderColor: colors.border, borderRadius: 999, borderWidth: 1, justifyContent: 'center', minHeight: 44, minWidth: 44, paddingHorizontal: spacing.sm },
  actionText: { color: colors.text, fontSize: 11, fontWeight: '800' },
  demoArtwork: { alignItems: 'center', aspectRatio: 4 / 3, backgroundColor: '#10243c', borderRadius: 10, justifyContent: 'center', overflow: 'hidden', position: 'relative', width: '100%' },
  demoMoon: { backgroundColor: '#9adfff', borderRadius: 25, height: 50, opacity: 0.86, position: 'absolute', right: 22, top: 18, width: 50 },
  demoTower: { backgroundColor: '#263746', bottom: 0, height: '66%', position: 'absolute', transform: [{ rotate: '5deg' }], width: 34 },
  demoLabel: { bottom: 10, color: '#dff8ff', fontSize: 10, fontWeight: '900', letterSpacing: 1.4, position: 'absolute' },
});
