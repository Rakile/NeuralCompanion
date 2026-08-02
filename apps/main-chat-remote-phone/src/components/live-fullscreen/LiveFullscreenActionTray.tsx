import React from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import * as FileSystem from 'expo-file-system/legacy';
import * as ImagePicker from 'expo-image-picker';

import { remoteActionError } from '../../api/envelope';
import { colors, spacing } from '../../styles/theme';

type Props = {
  visible: boolean;
  includeExit: boolean;
  disabled: boolean;
  onSendText: (text: string) => Promise<unknown>;
  onSendImage: (imageBase64: string, format: string, prompt: string) => Promise<unknown>;
  onOpenCamera: (onSent: () => void) => void;
  onClose: () => void;
  onExit: () => void;
};

function imageFormat(asset: ImagePicker.ImagePickerAsset): string {
  const mime = String(asset.mimeType || '').toLowerCase();
  if (mime === 'image/png') return 'png';
  if (mime === 'image/webp') return 'webp';
  return 'jpg';
}

export function LiveFullscreenActionTray({
  visible,
  includeExit,
  disabled,
  onSendText,
  onSendImage,
  onOpenCamera,
  onClose,
  onExit,
}: Props) {
  const [text, setText] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');
  if (!visible) return null;

  const sendText = async () => {
    const message = text.trim();
    if (!message || busy || disabled) return;
    setBusy(true);
    setError('');
    try {
      const result = await onSendText(message);
      const messageError = remoteActionError(result, 'Message was not accepted.');
      if (messageError) throw new Error(messageError);
      setText('');
      onClose();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Message could not be sent.');
    } finally {
      setBusy(false);
    }
  };

  const pickPhoto = async () => {
    if (busy || disabled) return;
    setBusy(true);
    setError('');
    try {
      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) throw new Error('Photo library permission is required.');
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images'],
        allowsEditing: false,
        quality: 0.82,
      });
      if (result.canceled || !result.assets?.length) return;
      const asset = result.assets[0]!;
      const imageBase64 = asset.base64 || await FileSystem.readAsStringAsync(asset.uri, {
        encoding: FileSystem.EncodingType.Base64,
      });
      const prompt = text.trim() || 'Please respond to this photo.';
      const response = await onSendImage(imageBase64, imageFormat(asset), prompt);
      const imageError = remoteActionError(response, 'Photo was not accepted.');
      if (imageError) throw new Error(imageError);
      setText('');
      onClose();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Photo could not be sent.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView
      pointerEvents="box-none"
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      style={StyleSheet.absoluteFill}
    >
      <View style={styles.tray}>
        <TextInput
          value={text}
          onChangeText={setText}
          editable={!busy && !disabled}
          placeholder="Message or photo prompt"
          placeholderTextColor="#7890a8"
          style={styles.input}
          multiline
        />
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <View style={styles.actions}>
          <Pressable style={styles.primaryButton} disabled={busy || !text.trim()} onPress={() => void sendText()}>
            <Text style={styles.primaryText}>{busy ? 'Working...' : 'Send'}</Text>
          </Pressable>
          <Pressable style={styles.button} disabled={busy} onPress={() => onOpenCamera(onClose)}>
            <Text style={styles.buttonText}>Camera</Text>
          </Pressable>
          <Pressable style={styles.button} disabled={busy} onPress={() => void pickPhoto()}>
            <Text style={styles.buttonText}>Photo</Text>
          </Pressable>
          <Pressable style={styles.button} disabled={busy} onPress={onClose}>
            <Text style={styles.buttonText}>Close</Text>
          </Pressable>
          {includeExit ? (
            <Pressable style={styles.exitButton} disabled={busy} onPress={onExit}>
              <Text style={styles.exitText}>Exit fullscreen</Text>
            </Pressable>
          ) : null}
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  tray: {
    backgroundColor: 'rgba(4,10,18,0.96)',
    borderColor: '#00d9ff',
    borderRadius: 14,
    borderWidth: 1,
    bottom: spacing.md,
    gap: spacing.sm,
    left: spacing.md,
    padding: spacing.md,
    position: 'absolute',
    right: spacing.md,
  },
  input: {
    backgroundColor: '#0c1725',
    borderColor: '#38536f',
    borderRadius: 9,
    borderWidth: 1,
    color: '#ffffff',
    maxHeight: 110,
    minHeight: 46,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  error: { color: colors.danger, fontSize: 12 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  button: {
    borderColor: '#41617f',
    borderRadius: 7,
    borderWidth: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  buttonText: { color: '#ffffff', fontSize: 12, fontWeight: '800' },
  primaryButton: {
    backgroundColor: '#00d9ff',
    borderRadius: 7,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  primaryText: { color: '#00131a', fontSize: 12, fontWeight: '900' },
  exitButton: {
    borderColor: '#ff385c',
    borderRadius: 7,
    borderWidth: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  exitText: { color: '#ff6b85', fontSize: 12, fontWeight: '900' },
});
