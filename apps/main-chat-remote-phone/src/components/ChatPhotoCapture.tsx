import { useThemedStyles, useThemeColors } from '../styles/ThemeContext';
import type { ThemeColors } from '../styles/theme';
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as ImagePicker from 'expo-image-picker';
import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Image, Keyboard, KeyboardAvoidingView, Linking, Modal, Platform, Pressable, ScrollView, StatusBar, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { colors, spacing } from '../styles/theme';
import { addAvatarToPhotoPrompt, normalizePickedPhotoAsset, type ChatPhoto, type ChatPhotoFormat } from '../utils/chatPhoto';

type Props = {
  visible: boolean;
  onCancel: () => void;
  onSend: (imageBase64: string, format: ChatPhotoFormat, prompt: string, source: ChatPhoto['source']) => Promise<void>;
  onSent?: () => void;
};

export function ChatPhotoCapture({ visible, onCancel, onSend, onSent }: Props) {
  const styles = useThemedStyles(createStyles);
  const colors = useThemeColors();

  const cameraRef = useRef<CameraView | null>(null);
  const [permission, requestPermission] = useCameraPermissions();
  const [photo, setPhoto] = useState<ChatPhoto | null>(null);
  const [prompt, setPrompt] = useState('Please respond to this photo.');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [keyboardVisible, setKeyboardVisible] = useState(false);

  useEffect(() => {
    if (Platform.OS !== 'android' || !visible) { setKeyboardVisible(false); return; }
    setKeyboardVisible(Keyboard.isVisible());
    const show = Keyboard.addListener('keyboardDidShow', () => setKeyboardVisible(true));
    const hide = Keyboard.addListener('keyboardDidHide', () => setKeyboardVisible(false));
    return () => { show.remove(); hide.remove(); };
  }, [visible]);

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
      setPhoto({ uri: picture.uri, base64: picture.base64, format: 'jpg', source: 'camera' });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Could not take photo.');
    } finally {
      setBusy(false);
    }
  };

  const choosePhoto = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images'],
        allowsEditing: false,
        base64: true,
        quality: 0.82,
        ...(Platform.OS === 'ios' ? { preferredAssetRepresentationMode: ImagePicker.UIImagePickerPreferredAssetRepresentationMode.Compatible } : {}),
      });
      if (result.canceled) return;
      const selected = normalizePickedPhotoAsset(result.assets[0] || {});
      if (!selected) throw new Error('The selected image could not be read.');
      setPhoto(selected);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Could not choose a photo.');
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
      await onSend(photo.base64, photo.format, prompt.trim() || 'Please respond to this photo.', photo.source);
      onSent?.();
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
      <KeyboardAvoidingView style={styles.screen} behavior="padding"
        enabled={visible && Boolean(photo) && (Platform.OS === 'ios' || keyboardVisible)}>
      <SafeAreaView edges={['top', 'bottom', 'left', 'right']} style={styles.screen}>
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
        ) : photo ? (
          <View style={styles.previewArea}>
            <Image source={{ uri: photo.uri }} style={styles.preview} resizeMode="contain" />
          </View>
        ) : !permission.granted ? (
          <View style={styles.centered}>
            <Text style={styles.permissionTitle}>Camera access is optional</Text>
            <Text style={styles.permissionDetail}>Allow the camera, or choose an existing photo below.</Text>
            <Pressable
              style={styles.primaryButton}
              onPress={permission.canAskAgain ? requestCamera : () => Linking.openSettings().catch(() => undefined)}
            >
              <Text style={styles.primaryButtonText}>{permission.canAskAgain ? 'Allow camera' : 'Open settings'}</Text>
            </Pressable>
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

        <ScrollView style={styles.controlsScroll} contentContainerStyle={styles.controls}
          keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag">
          {photo ? (
            <TextInput
              value={prompt}
              onChangeText={setPrompt}
              editable={!busy}
              placeholder="Ask about this photo or describe an edit"
              placeholderTextColor={colors.muted}
              style={styles.promptInput}
              multiline
            />
          ) : null}
          {photo ? (
            <Pressable style={styles.secondaryButton} disabled={busy}
              accessibilityRole="button" onPress={() => setPrompt(addAvatarToPhotoPrompt(prompt))}>
              <Text style={styles.secondaryButtonText}>Add avatar to photo</Text>
            </Pressable>
          ) : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <View style={styles.buttonRow}>
              <Pressable style={styles.secondaryButton} onPress={choosePhoto} disabled={busy}>
                <Text style={styles.secondaryButtonText}>{photo ? 'Choose another' : 'Choose photo'}</Text>
              </Pressable>
              {photo ? (
                <Pressable style={styles.secondaryButton} onPress={() => setPhoto(null)} disabled={busy || !permission?.granted}>
                  <Text style={styles.secondaryButtonText}>Camera</Text>
                </Pressable>
              ) : null}
              {permission?.granted || photo ? (
              <Pressable
                style={[styles.primaryButton, busy && styles.disabled]}
                onPress={photo ? sendPhoto : takePhoto}
                disabled={busy}
              >
                <Text style={styles.primaryButtonText}>{busy ? 'Working' : photo ? 'Send photo' : 'Take photo'}</Text>
              </Pressable>
              ) : null}
            </View>
        </ScrollView>
      </SafeAreaView>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
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
    minHeight: 44,
    justifyContent: 'center',
    paddingHorizontal: spacing.md,
  },
  headerButtonText: { color: colors.text, fontSize: 13, fontWeight: '800' },
  cameraArea: { flex: 1 },
  camera: { flex: 1 },
  previewArea: { backgroundColor: '#000000', flex: 1, minHeight: 0 },
  preview: { height: '100%', width: '100%' },
  centered: { alignItems: 'center', flex: 1, gap: spacing.md, justifyContent: 'center', padding: spacing.lg },
  permissionTitle: { color: colors.text, fontSize: 17, fontWeight: '800' },
  permissionDetail: { color: colors.muted, fontSize: 13, lineHeight: 19, maxWidth: 300, textAlign: 'center' },
  controlsScroll: { flexGrow: 0, flexShrink: 1 },
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
  buttonRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, justifyContent: 'flex-end' },
  primaryButton: {
    alignItems: 'center',
    backgroundColor: colors.accent,
    borderRadius: 6,
    minHeight: 42,
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
  },
  primaryButtonText: { color: colors.background, fontSize: 14, fontWeight: '800' },
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
