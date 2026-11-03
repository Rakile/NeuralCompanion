import { usePresentationStyle, useThemedStyles, useThemeColors } from '../styles/ThemeContext';
import type { ThemeColors } from '../styles/theme';
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Image, Modal, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { RemoteClient } from '../api/client';
import type { VisualAction } from '../api/client';
import { remoteActionError } from '../api/envelope';
import type { VisualState } from '../api/types';
import { useInterfaceMode } from '../context/InterfaceModeContext';
import { colors, controlGlyphTypography, spacing } from '../styles/theme';
import { useAuthorizedMediaUrl } from '../hooks/useAuthorizedMediaUrl';
import { ZoomableImage } from './ZoomableImage';
import { VisualReplyMediaActions } from './InlineVisualReply';

type Props = {
  client: RemoteClient;
  visual: VisualState | undefined;
  disabled: boolean;
  controlsAvailable: boolean;
  controlsDisabled?: boolean;
  demoMode?: boolean;
  onGenerate: (prompt: string) => Promise<unknown>;
  onAction: (action: VisualAction) => Promise<unknown>;
  onRefresh: () => Promise<void>;
};

function DemoVisualReplyArtwork({ caption }: { caption: string }) {
  const styles = useThemedStyles(createStyles, 'VisualPanel');

  return (
    <View style={styles.demoArtwork}>
      <View style={styles.demoSky}>
        <View style={styles.demoMoon} />
        <View style={[styles.demoRain, styles.demoRainLeft]} />
        <View style={[styles.demoRain, styles.demoRainCenter]} />
        <View style={[styles.demoRain, styles.demoRainRight]} />
      </View>
      <View style={styles.demoTower}>
        <View style={styles.demoPulse} />
        <View style={styles.demoAntenna} />
        <View style={styles.demoTowerLegs} />
      </View>
      <View style={styles.demoForeground}>
        <View style={styles.demoCharacter} />
        <View style={[styles.demoCharacter, styles.demoCharacterSecond]} />
      </View>
      <Text style={styles.demoCaption} numberOfLines={3}>{caption}</Text>
    </View>
  );
}

export function VisualPanel({ client, visual, disabled, controlsAvailable, controlsDisabled: controlsBlocked = false, demoMode = false, onGenerate, onAction, onRefresh }: Props) {
  const styles = useThemedStyles(createStyles, 'VisualPanel');
  const colors = useThemeColors();

  const { mode, policy } = useInterfaceMode();
  const editorial = usePresentationStyle() === 'editorial';
  const visualPrimary = editorial || policy.primaryFirst;
  const [prompt, setPrompt] = useState('');
  const [moreActions, setMoreActions] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failedPrompt, setFailedPrompt] = useState('');
  const promptRevision = React.useRef(0);
  const requestOwner = React.useMemo(() => ({ busy: false, active: true }), [client.identityKey, client.pairingCode, disabled]);
  const currentOwner = React.useRef(requestOwner); currentOwner.current = requestOwner;
  const [fullscreen, setFullscreen] = useState(false);
  const [error, setError] = useState('');
  const controlsDisabled = disabled || controlsBlocked || !controlsAvailable;
  const actionDisabled = (action: VisualAction | 'generate') => controlsDisabled || busy
    || (Array.isArray(visual?.supported_actions) && !visual.supported_actions.includes(action));
  const imagePath = disabled ? '' : String(visual?.state?.image_url_path || '');
  const imageVersion = visual?.state?.image_cache_key || visual?.state?.updated_at || '';
  const authorizedImage = useAuthorizedMediaUrl(client, imagePath, imageVersion ? { v: String(imageVersion) } : {});
  const imageUrl = authorizedImage.url;
  const [failedImageUrl, setFailedImageUrl] = useState('');
  const imageError = authorizedImage.error || (imageUrl && imageUrl === failedImageUrl ? 'Could not load this image.' : '');
  const reloadImage = () => { setFailedImageUrl(''); authorizedImage.reload(); };
  const latestRequest = visual?.latest_request;
  const requestStatus = latestRequest?.status ? String(latestRequest.status) : '';
  const statusText = disabled
    ? 'offline'
    : controlsAvailable
      ? String(requestStatus || visual?.state?.status || visual?.settings?.mode_value || 'idle')
      : 'unavailable';
  const requestError = ['error', 'failed', 'rejected'].includes(requestStatus)
    ? String(latestRequest?.message || 'Last Visual Reply request was not accepted.')
    : '';
  const emptyTitle = disabled
    ? 'Visual Reply offline'
    : controlsAvailable
      ? 'No Visual Reply image yet'
      : 'Visual Reply unavailable';
  const emptyText = disabled
    ? 'Connect to desktop or tap Demo.'
    : controlsAvailable
      ? 'Generate an image from the phone or ask NC for a Visual Reply in chat.'
      : 'Visual Reply is unavailable because desktop provider is off.';
  useEffect(() => {
    requestOwner.active = true; setBusy(false); setError(''); setFailedPrompt('');
    return () => { requestOwner.active = false; };
  }, [requestOwner]);
  useEffect(() => {
    if (controlsDisabled) {
      setBusy(false);
      setError('');
    }
  }, [controlsDisabled]);
  const run = async (action: () => Promise<unknown>, restorePrompt = '') => {
    if (requestOwner.busy || !requestOwner.active || requestOwner !== currentOwner.current) {
      return;
    }
    requestOwner.busy = true; setBusy(true);
    setError('');
    setFailedPrompt('');
    const revision = promptRevision.current;
    const current = () => requestOwner.active && requestOwner === currentOwner.current;
    try {
      const result = await action();
      if (!current()) return;
      const errorMessage = remoteActionError(result, 'Visual Reply action was not accepted.');
      if (errorMessage) {
        throw new Error(errorMessage);
      }
      await onRefresh();
    } catch (exc) {
      if (!current()) return;
      if (restorePrompt && revision === promptRevision.current) {
        setPrompt(currentPrompt => currentPrompt ? currentPrompt : restorePrompt);
      }
      if (restorePrompt) setFailedPrompt(restorePrompt);
      setError(exc instanceof Error ? exc.message : 'Visual Reply action failed.');
    } finally {
      requestOwner.busy = false;
      if (current()) setBusy(false);
    }
  };
  const header = (
    <View style={styles.header}>
      <Text style={[styles.title, editorial && styles.editorialTitle]}>{editorial ? "Visual" : "Visual Reply"}</Text>
      <Text style={styles.meta}>{statusText}</Text>
    </View>
  );
  const loadingState = imageError ? <View style={styles.emptyImage}>
    <Text accessibilityRole="alert" style={styles.error}>{imageError}</Text>
    <Pressable accessibilityRole="button" accessibilityLabel="Reload image" disabled={disabled} style={styles.secondaryButton} onPress={reloadImage}>
      <Text style={styles.buttonText}>Reload image</Text>
    </Pressable>
  </View> : <View style={styles.emptyImage}><ActivityIndicator color={colors.accent} /><Text style={styles.emptyText}>Loading image…</Text></View>;
  const visualCanvas = imageError ? loadingState : imageUrl ? (
    <Pressable
      style={[styles.imageFrame, !policy.cards && styles.cleanImageFrame, mode === 'immersive' && styles.immersiveImageFrame, editorial && styles.cleanImageFrame]}
      onPress={() => setFullscreen(true)}
    >
      <Image source={{ uri: imageUrl }} onError={() => setFailedImageUrl(imageUrl)} style={styles.image} resizeMode="contain" />
    </Pressable>
  ) : authorizedImage.loading || imagePath ? loadingState : demoMode ? (
    <DemoVisualReplyArtwork caption={String(visual?.state?.caption || visual?.latest_request?.prompt_preview || 'Demo Visual Reply scene')} />
  ) : (
    <View style={[styles.emptyImage, !policy.cards && styles.cleanEmptyImage]}>
      <Text style={styles.emptyTitle}>{emptyTitle}</Text>
      <Text style={styles.emptyText}>{emptyText}</Text>
    </View>
  );
  return (
    <View style={[styles.panel, !policy.cards && styles.cleanPanel, mode === 'immersive' && styles.immersivePanel, editorial && styles.editorialPanel]}>
      {!visualPrimary || editorial ? header : null}
      {visualCanvas}
      {visualPrimary && !editorial ? header : null}
      {visual?.state?.caption ? <Text style={[styles.caption, editorial && styles.editorialCaption]}>{String(visual.state.caption)}</Text> : null}
      <View style={styles.row}>
        <TextInput
          value={prompt}
          onChangeText={text => { promptRevision.current++; setPrompt(text); }}
          editable={!controlsDisabled}
          placeholder="Visual prompt"
          placeholderTextColor={colors.muted}
          style={styles.input}
        />
        <Pressable disabled={actionDisabled('generate') || !prompt.trim()} style={[styles.button, (actionDisabled('generate') || !prompt.trim()) && styles.disabled]} onPress={() => {
          if (actionDisabled('generate') || requestOwner.busy || !prompt.trim()) return;
          const next = prompt.trim();
          promptRevision.current++;
          setPrompt('');
          run(() => onGenerate(next), next).catch(() => undefined);
        }}>
          <Text style={styles.buttonText}>Generate</Text>
        </Pressable>
      </View>
      <VisualReplyMediaActions item={{ id: String(imageVersion || imagePath), status: 'ready', url_path: imagePath,
        content_type: String(visual?.state?.image_content_type || '') }} mediaUrl={imageError ? '' : imageUrl} disabled={disabled} />
      {editorial ? <Pressable accessibilityRole="button" accessibilityState={{ expanded: moreActions }} onPress={() => setMoreActions(value => !value)} style={styles.editorialDisclosure}><Text style={styles.buttonText}>Desktop & more actions <Text style={controlGlyphTypography}>{moreActions ? "−" : "+"}</Text></Text></Pressable> : null}
      {!editorial || moreActions ? <View style={styles.actions}>
        <Pressable disabled={actionDisabled('show')} style={[styles.secondaryButton, actionDisabled('show') && styles.disabled]} onPress={() => run(() => onAction('show'))}>
          <Text style={styles.buttonText}>Show on Desktop</Text>
        </Pressable>
        <Pressable disabled={actionDisabled('hide')} style={[styles.secondaryButton, actionDisabled('hide') && styles.disabled]} onPress={() => run(() => onAction('hide'))}>
          <Text style={styles.buttonText}>Hide</Text>
        </Pressable>
        <Pressable disabled={actionDisabled('clear')} style={[styles.secondaryButton, actionDisabled('clear') && styles.disabled]} onPress={() => run(() => onAction('clear'))}>
          <Text style={styles.buttonText}>Clear</Text>
        </Pressable>
        <Pressable disabled={actionDisabled('generate_last')} style={[styles.secondaryButton, actionDisabled('generate_last') && styles.disabled]} onPress={() => run(() => onAction('generate_last'))}>
          <Text style={styles.buttonText}>Generate Last</Text>
        </Pressable>
        <Pressable disabled={busy} style={[styles.secondaryButton, busy && styles.disabled]} onPress={() => run(onRefresh)}>
          <Text style={styles.buttonText}>Refresh</Text>
        </Pressable>
      </View> : null}
      {error || requestError ? <Text style={styles.error}>{error || requestError}</Text> : null}
      {failedPrompt ? <Pressable accessibilityRole="button" accessibilityLabel="Retry previous prompt" disabled={actionDisabled('generate')}
        style={styles.secondaryButton} onPress={() => run(() => onGenerate(failedPrompt), failedPrompt)}><Text style={styles.buttonText}>Retry previous prompt</Text></Pressable> : null}
      <Modal visible={fullscreen && Boolean(imagePath)} animationType="fade" transparent onRequestClose={() => setFullscreen(false)}>
        <SafeAreaView style={styles.fullscreen}>
          <Pressable accessibilityRole="button" accessibilityLabel="Close full-screen image" style={styles.fullscreenClose} onPress={() => setFullscreen(false)}>
            <Text style={styles.buttonText}>Close</Text>
          </Pressable>
          {imageUrl ? <ZoomableImage uri={imageUrl} style={styles.fullscreenImage} onReload={reloadImage} /> : loadingState}
        </SafeAreaView>
      </Modal>
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  editorialTitle: { fontFamily: "serif", fontSize: 28, fontWeight: "400" },
  editorialPanel: { padding: 20, gap: 20 },
  editorialCaption: { fontFamily: "serif", fontSize: 18, lineHeight: 27, color: colors.text },
  editorialDisclosure: { minHeight: 48, borderTopColor: colors.borderSoft, borderTopWidth: 1, justifyContent: "center" },
  panel: {
    backgroundColor: colors.panel,
    borderTopColor: colors.border,
    borderTopWidth: 1,
    gap: spacing.sm,
    padding: spacing.md,
  },
  cleanPanel: { backgroundColor: 'transparent', borderTopWidth: 0, paddingHorizontal: 0 },
  immersivePanel: { backgroundColor: colors.background },
  header: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  title: {
    color: colors.text,
    fontSize: 13,
    fontWeight: '800',
  },
  meta: {
    color: colors.muted,
    fontSize: 12,
  },
  imageFrame: {
    alignSelf: 'center',
    aspectRatio: 1,
    backgroundColor: colors.background,
    borderColor: colors.border,
    borderRadius: 8,
    borderWidth: 1,
    maxHeight: 320,
    overflow: 'hidden',
    width: '100%',
  },
  image: {
    height: '100%',
    width: '100%',
  },
  cleanImageFrame: { borderRadius: 0, borderWidth: 0, maxHeight: 440 },
  immersiveImageFrame: { backgroundColor: '#000000', maxHeight: 560 },
  emptyImage: {
    alignItems: 'center',
    alignSelf: 'center',
    aspectRatio: 1,
    backgroundColor: colors.background,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    justifyContent: 'center',
    maxHeight: 320,
    padding: spacing.md,
    width: '100%',
  },
  emptyTitle: {
    color: colors.text,
    fontSize: 14,
    fontWeight: '900',
    marginBottom: spacing.xs,
    textAlign: 'center',
  },
  cleanEmptyImage: { backgroundColor: 'transparent', borderRadius: 0, borderWidth: 0 },
  emptyText: {
    color: colors.muted,
    fontSize: 12,
    lineHeight: 17,
    textAlign: 'center',
  },
  caption: {
    color: colors.muted,
    fontSize: 12,
    lineHeight: 17,
  },
  demoArtwork: {
    alignSelf: 'center',
    aspectRatio: 1.18,
    backgroundColor: '#101722',
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    maxHeight: 230,
    overflow: 'hidden',
    width: '100%',
  },
  demoSky: {
    backgroundColor: '#182437',
    height: '58%',
    position: 'relative',
  },
  demoMoon: {
    backgroundColor: '#b7d8ff',
    borderRadius: 999,
    height: 38,
    opacity: 0.8,
    position: 'absolute',
    right: 28,
    top: 22,
    width: 38,
  },
  demoRain: {
    backgroundColor: '#8ecbff',
    height: 120,
    opacity: 0.28,
    position: 'absolute',
    top: 0,
    transform: [{ rotate: '18deg' }],
    width: 2,
  },
  demoRainLeft: {
    left: '24%',
  },
  demoRainCenter: {
    left: '52%',
  },
  demoRainRight: {
    left: '76%',
  },
  demoTower: {
    alignItems: 'center',
    bottom: 36,
    height: 155,
    justifyContent: 'flex-start',
    left: 0,
    position: 'absolute',
    right: 0,
  },
  demoPulse: {
    backgroundColor: colors.accent,
    borderColor: '#b8e9ff',
    borderRadius: 999,
    borderWidth: 2,
    height: 28,
    marginBottom: 6,
    shadowColor: colors.accent,
    shadowOpacity: 0.8,
    shadowRadius: 12,
    width: 28,
  },
  demoAntenna: {
    backgroundColor: '#d8e6f3',
    height: 84,
    width: 5,
  },
  demoTowerLegs: {
    borderBottomColor: '#6c8194',
    borderBottomWidth: 74,
    borderLeftColor: 'transparent',
    borderLeftWidth: 38,
    borderRightColor: 'transparent',
    borderRightWidth: 38,
    height: 0,
    opacity: 0.88,
    width: 72,
  },
  demoForeground: {
    backgroundColor: '#141b24',
    bottom: 0,
    height: '34%',
    left: 0,
    position: 'absolute',
    right: 0,
  },
  demoCharacter: {
    backgroundColor: '#e6edf7',
    borderRadius: 999,
    bottom: 38,
    height: 34,
    left: '28%',
    position: 'absolute',
    width: 18,
  },
  demoCharacterSecond: {
    backgroundColor: '#9ad7ff',
    left: '63%',
  },
  demoCaption: {
    bottom: spacing.sm,
    color: colors.text,
    fontSize: 12,
    left: spacing.sm,
    lineHeight: 16,
    position: 'absolute',
    right: spacing.sm,
  },
  row: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  input: {
    backgroundColor: colors.panelAlt,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    color: colors.text,
    flex: 1,
    height: 38,
    paddingHorizontal: spacing.md,
  },
  button: {
    alignItems: 'center',
    backgroundColor: colors.accentSoft,
    borderRadius: 6,
    height: 38,
    justifyContent: 'center',
    paddingHorizontal: spacing.md,
  },
  buttonText: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '700',
  },
  actions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  secondaryButton: {
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  primaryAction: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.accent,
  },
  disabled: {
    opacity: 0.35,
  },
  error: {
    color: colors.danger,
    fontSize: 12,
  },
  fullscreen: {
    backgroundColor: 'rgba(0, 0, 0, 0.94)',
    flex: 1,
    padding: spacing.md,
  },
  fullscreenClose: {
    minHeight: 48,
    minWidth: 80,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.panel,
    alignSelf: 'flex-end',
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    marginBottom: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  fullscreenImage: {
    flex: 1,
    width: '100%',
  },
});
