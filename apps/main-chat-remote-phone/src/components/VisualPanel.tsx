import React, { useEffect, useState } from 'react';
import { Image, Modal, Pressable, Share, StyleSheet, Text, TextInput, View } from 'react-native';
import * as FileSystem from 'expo-file-system/legacy';
import * as MediaLibrary from 'expo-media-library';
import * as Sharing from 'expo-sharing';

import { RemoteClient } from '../api/client';
import type { VisualAction } from '../api/client';
import { remoteActionError } from '../api/envelope';
import type { VisualState } from '../api/types';
import { colors, spacing } from '../styles/theme';

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

function imageFileExtension(path: string): string {
  const pathWithoutQuery = String(path || '').split('?')[0] || '';
  const match = pathWithoutQuery.match(/\.(jpe?g|png|webp)$/i);
  const extension = match?.[1] ? match[1].toLowerCase().replace('jpeg', 'jpg') : '';
  return extension ? `.${extension}` : '.jpg';
}

function imageMimeType(extension: string): string {
  if (extension === '.png') {
    return 'image/png';
  }
  if (extension === '.webp') {
    return 'image/webp';
  }
  return 'image/jpeg';
}

function DemoVisualReplyArtwork({ caption }: { caption: string }) {
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
  const [prompt, setPrompt] = useState('');
  const [busy, setBusy] = useState(false);
  const [shareBusy, setShareBusy] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [error, setError] = useState('');
  const controlsDisabled = disabled || controlsBlocked || !controlsAvailable;
  const imagePath = disabled ? '' : String(visual?.state?.image_url_path || '');
  const imageVersion = visual?.state?.image_cache_key || visual?.state?.updated_at || '';
  const imageUrl = imagePath ? client.authorizedUrl(imagePath, imageVersion ? { v: String(imageVersion) } : {}) : '';
  const latestRequest = visual?.latest_request;
  const requestStatus = latestRequest?.status ? String(latestRequest.status) : '';
  const statusText = disabled
    ? 'offline'
    : controlsAvailable
      ? String(requestStatus || visual?.state?.status || visual?.settings?.mode_value || 'idle')
      : 'unavailable';
  const requestError = requestStatus === 'error' || requestStatus === 'rejected'
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
    if (controlsDisabled) {
      setBusy(false);
      setError('');
    }
  }, [controlsDisabled]);
  const run = async (action: () => Promise<unknown>, restorePrompt = '') => {
    if (busy) {
      return;
    }
    setBusy(true);
    setError('');
    try {
      const result = await action();
      const errorMessage = remoteActionError(result, 'Visual Reply action was not accepted.');
      if (errorMessage) {
        throw new Error(errorMessage);
      }
      await onRefresh();
    } catch (exc) {
      if (restorePrompt) {
        setPrompt(restorePrompt);
      }
      setError(exc instanceof Error ? exc.message : 'Visual Reply action failed.');
    } finally {
      setBusy(false);
    }
  };
  const shareImage = async () => {
    if (!imageUrl || shareBusy) {
      return;
    }
    setShareBusy(true);
    setError('');
    try {
      if (!FileSystem.cacheDirectory) {
        throw new Error('Expo cache directory is unavailable.');
      }
      const extension = imageFileExtension(imagePath);
      const target = `${FileSystem.cacheDirectory}nc_visual_reply_${Date.now()}${extension}`;
      const result = await FileSystem.downloadAsync(imageUrl, target);
      const permission = await MediaLibrary.requestPermissionsAsync(true, ['photo']);
      if (!permission.granted) {
        throw new Error('Photo library permission is required to save the Visual Reply image.');
      }
      await MediaLibrary.saveToLibraryAsync(result.uri);
      if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(result.uri, {
          dialogTitle: 'Share Visual Reply',
          mimeType: imageMimeType(extension),
        });
      } else {
        await Share.share({ url: result.uri, message: 'Neural Companion Visual Reply' });
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Could not share Visual Reply image.');
    } finally {
      setShareBusy(false);
    }
  };
  return (
    <View style={styles.panel}>
      <View style={styles.header}>
        <Text style={styles.title}>Visual Reply</Text>
        <Text style={styles.meta}>{statusText}</Text>
      </View>
      {imageUrl ? (
        <Pressable style={styles.imageFrame} onPress={() => setFullscreen(true)}>
          <Image source={{ uri: imageUrl }} style={styles.image} resizeMode="cover" />
        </Pressable>
      ) : demoMode ? (
        <DemoVisualReplyArtwork caption={String(visual?.state?.caption || visual?.latest_request?.prompt_preview || 'Demo Visual Reply scene')} />
      ) : (
        <View style={styles.emptyImage}>
          <Text style={styles.emptyTitle}>{emptyTitle}</Text>
          <Text style={styles.emptyText}>{emptyText}</Text>
        </View>
      )}
      {visual?.state?.caption ? <Text style={styles.caption}>{String(visual.state.caption)}</Text> : null}
      <View style={styles.row}>
        <TextInput
          value={prompt}
          onChangeText={setPrompt}
          editable={!controlsDisabled}
          placeholder="Visual prompt"
          placeholderTextColor={colors.muted}
          style={styles.input}
        />
        <Pressable disabled={controlsDisabled || busy || !prompt.trim()} style={[styles.button, (controlsDisabled || busy || !prompt.trim()) && styles.disabled]} onPress={() => {
          const next = prompt.trim();
          setPrompt('');
          run(() => onGenerate(next), next).catch(() => undefined);
        }}>
          <Text style={styles.buttonText}>Generate</Text>
        </Pressable>
      </View>
      <View style={styles.actions}>
        <Pressable disabled={!imageUrl || shareBusy} style={[styles.secondaryButton, styles.primaryAction, (!imageUrl || shareBusy) && styles.disabled]} onPress={shareImage}>
          <Text style={styles.buttonText}>{shareBusy ? 'Saving' : 'Save/Share'}</Text>
        </Pressable>
        <Pressable disabled={controlsDisabled || busy} style={[styles.secondaryButton, (controlsDisabled || busy) && styles.disabled]} onPress={() => run(() => onAction('show'))}>
          <Text style={styles.buttonText}>Show on Desktop</Text>
        </Pressable>
        <Pressable disabled={controlsDisabled || busy} style={[styles.secondaryButton, (controlsDisabled || busy) && styles.disabled]} onPress={() => run(() => onAction('hide'))}>
          <Text style={styles.buttonText}>Hide</Text>
        </Pressable>
        <Pressable disabled={controlsDisabled || busy} style={[styles.secondaryButton, (controlsDisabled || busy) && styles.disabled]} onPress={() => run(() => onAction('clear'))}>
          <Text style={styles.buttonText}>Clear</Text>
        </Pressable>
        <Pressable disabled={controlsDisabled || busy} style={[styles.secondaryButton, (controlsDisabled || busy) && styles.disabled]} onPress={() => run(() => onAction('generate_last'))}>
          <Text style={styles.buttonText}>Generate Last</Text>
        </Pressable>
        <Pressable disabled={busy} style={[styles.secondaryButton, busy && styles.disabled]} onPress={() => run(onRefresh)}>
          <Text style={styles.buttonText}>Refresh</Text>
        </Pressable>
      </View>
      {error || requestError ? <Text style={styles.error}>{error || requestError}</Text> : null}
      <Modal visible={fullscreen && Boolean(imageUrl)} animationType="fade" transparent>
        <View style={styles.fullscreen}>
          <Pressable style={styles.fullscreenClose} onPress={() => setFullscreen(false)}>
            <Text style={styles.buttonText}>Close</Text>
          </Pressable>
          {imageUrl ? <Image source={{ uri: imageUrl }} style={styles.fullscreenImage} resizeMode="contain" /> : null}
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    backgroundColor: colors.panel,
    borderTopColor: colors.border,
    borderTopWidth: 1,
    gap: spacing.sm,
    padding: spacing.md,
  },
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
