import { CameraView, useCameraPermissions } from 'expo-camera';
import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Image, Linking, Modal, Pressable, SafeAreaView, StatusBar, StyleSheet, Text, TextInput, View } from 'react-native';

import { colors, spacing } from '../styles/theme';

type CapturedPhoto = {
  uri: string;
  base64: string;
};

type Props = {
  visible: boolean;
  onCancel: () => void;
  onSend: (imageBase64: string, format: 'jpg', prompt: string) => Promise<void>;
};

export function ChatPhotoCapture({ visible, onCancel, onSend }: Props) {
  const cameraRef = useRef<CameraView | null>(null);
  const [permission, requestPermission] = useCameraPermissions();
  const [photo, setPhoto] = useState<CapturedPhoto | null>(null);
  const [prompt, setPrompt] = useState('Please respond to this photo.');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (visible) {
      setPhoto(null);
      setPrompt('Please respond to this photo.');
      setBusy(false);
      setError('');
    }
  }, [visible]);

  const takePhoto = async () => {
    if (!cameraRef.current || busy) {
      return;
    }
    setBusy(true);
    setError('');
    try {
      const picture = await cameraRef.current.takePictureAsync({ base64: true, quality: 0.72 });
      if (!picture?.uri || !picture.base64) {
        throw new Error('The camera did not return photo data.');
      }
      setPhoto({ uri: picture.uri, base64: picture.base64 });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Could not take photo.');
    } finally {
      setBusy(false);
    }
  };

  const sendPhoto = async () => {
    if (!photo || busy) {
      return;
    }
    setBusy(true);
    setError('');
    try {
      await onSend(photo.base64, 'jpg', prompt.trim() || 'Please respond to this photo.');
      onCancel();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Could not send photo.');
    } finally {
      setBusy(false);
    }
  };

  const requestCamera = () => {
    setError('');
    requestPermission().catch(() => setError('Camera permission could not be requested.'));
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onCancel} statusBarTranslucent>
      <SafeAreaView style={styles.screen}>
        <StatusBar barStyle="light-content" backgroundColor={colors.background} />
        <View style={styles.header}>
          <Text style={styles.title}>Add photo to chat</Text>
          <Pressable style={styles.headerButton} onPress={onCancel} disabled={busy}>
            <Text style={styles.headerButtonText}>Close</Text>
          </Pressable>
        </View>

        {!permission ? (
          <View style={styles.centered}>
            <ActivityIndicator color={colors.accent} size="large" />
          </View>
        ) : !permission.granted ? (
          <View style={styles.centered}>
            <Text style={styles.permissionTitle}>Camera access required</Text>
            <Pressable
              style={styles.primaryButton}
              onPress={permission.canAskAgain ? requestCamera : () => Linking.openSettings().catch(() => undefined)}
            >
              <Text style={styles.primaryButtonText}>{permission.canAskAgain ? 'Allow camera' : 'Open settings'}</Text>
            </Pressable>
          </View>
        ) : photo ? (
          <View style={styles.previewArea}>
            <Image source={{ uri: photo.uri }} style={styles.preview} resizeMode="contain" />
          </View>
        ) : (
          <View style={styles.cameraArea}>
            <CameraView
              ref={cameraRef}
              style={styles.camera}
              facing="back"
              onMountError={(event) => setError(event.message || 'Camera could not be started.')}
            />
          </View>
        )}

        <View style={styles.controls}>
          {photo ? (
            <TextInput
              value={prompt}
              onChangeText={setPrompt}
              editable={!busy}
              placeholder="Ask about this photo"
              placeholderTextColor={colors.muted}
              style={styles.promptInput}
              multiline
            />
          ) : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}
          {permission?.granted ? (
            <View style={styles.buttonRow}>
              {photo ? (
                <Pressable style={styles.secondaryButton} onPress={() => setPhoto(null)} disabled={busy}>
                  <Text style={styles.secondaryButtonText}>Retake</Text>
                </Pressable>
              ) : null}
              <Pressable
                style={[styles.primaryButton, busy && styles.disabled]}
                onPress={photo ? sendPhoto : takePhoto}
                disabled={busy}
              >
                <Text style={styles.primaryButtonText}>{busy ? 'Working' : photo ? 'Send photo' : 'Take photo'}</Text>
              </Pressable>
            </View>
          ) : null}
        </View>
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  screen: { backgroundColor: colors.background, flex: 1 },
  header: {
    alignItems: 'center',
    borderBottomColor: colors.border,
    borderBottomWidth: 1,
    flexDirection: 'row',
    justifyContent: 'space-between',
    minHeight: 58,
    paddingHorizontal: spacing.lg,
  },
  title: { color: colors.text, fontSize: 17, fontWeight: '800' },
  headerButton: {
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    minHeight: 36,
    justifyContent: 'center',
    paddingHorizontal: spacing.md,
  },
  headerButtonText: { color: colors.text, fontSize: 13, fontWeight: '800' },
  cameraArea: { flex: 1 },
  camera: { flex: 1 },
  previewArea: { backgroundColor: '#000000', flex: 1 },
  preview: { height: '100%', width: '100%' },
  centered: { alignItems: 'center', flex: 1, gap: spacing.md, justifyContent: 'center', padding: spacing.lg },
  permissionTitle: { color: colors.text, fontSize: 17, fontWeight: '800' },
  controls: {
    backgroundColor: colors.panel,
    borderTopColor: colors.border,
    borderTopWidth: 1,
    gap: spacing.sm,
    padding: spacing.md,
  },
  promptInput: {
    backgroundColor: colors.panelAlt,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    color: colors.text,
    maxHeight: 90,
    minHeight: 44,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  buttonRow: { flexDirection: 'row', gap: spacing.sm, justifyContent: 'flex-end' },
  primaryButton: {
    alignItems: 'center',
    backgroundColor: colors.accent,
    borderRadius: 6,
    minHeight: 42,
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
  },
  primaryButtonText: { color: '#061019', fontSize: 14, fontWeight: '800' },
  secondaryButton: {
    alignItems: 'center',
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    minHeight: 42,
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
  },
  secondaryButtonText: { color: colors.text, fontSize: 14, fontWeight: '800' },
  error: { color: colors.danger, fontSize: 12, textAlign: 'center' },
  disabled: { opacity: 0.4 },
});
