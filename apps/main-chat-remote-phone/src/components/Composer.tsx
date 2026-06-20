import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { colors, spacing } from '../styles/theme';

type Props = {
  disabled: boolean;
  voiceAvailable: boolean;
  recording: boolean;
  busy: boolean;
  recordingError: string;
  transcript?: string;
  onTranscriptConsumed?: () => void;
  onSend: (text: string) => Promise<void>;
  onRecordPress: () => Promise<void>;
};

export function Composer({ disabled, voiceAvailable, recording, busy, recordingError, transcript = '', onTranscriptConsumed, onSend, onRecordPress }: Props) {
  const [text, setText] = useState('');
  const [sendError, setSendError] = useState('');
  const recordDisabled = busy || ((disabled || !voiceAvailable) && !recording);
  useEffect(() => {
    if (disabled) {
      setSendError('');
    }
  }, [disabled]);
  useEffect(() => {
    const next = transcript.trim();
    if (!next) {
      return;
    }
    setText((current) => (current.trim() ? `${current.trim()} ${next}` : next));
    onTranscriptConsumed?.();
  }, [onTranscriptConsumed, transcript]);
  const send = async () => {
    const message = text.trim();
    if (!message) {
      return;
    }
    setText('');
    setSendError('');
    try {
      await onSend(message);
    } catch (exc) {
      setText(message);
      setSendError(exc instanceof Error ? exc.message : 'Message send failed.');
    }
  };
  return (
    <View style={styles.wrap}>
      {sendError || recordingError ? <Text style={styles.error}>{sendError || recordingError}</Text> : null}
      {!voiceAvailable ? <Text style={styles.hint}>Phone voice needs a desktop STT backend with file transcription.</Text> : null}
      <View style={styles.composer}>
        <TextInput
          value={text}
          onChangeText={setText}
          editable={!disabled}
          placeholder="Message"
          placeholderTextColor={colors.muted}
          style={styles.input}
          multiline
        />
        <Pressable disabled={recordDisabled} style={[styles.micButton, recording && styles.recording, recordDisabled && styles.disabled]} onPress={onRecordPress}>
          <Text style={styles.buttonText}>{recording ? 'Stop' : voiceAvailable ? 'Mic' : 'No STT'}</Text>
        </Pressable>
        <Pressable disabled={disabled || !text.trim()} style={[styles.sendButton, disabled && styles.disabled]} onPress={send}>
          <Text style={styles.sendText}>Send</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    backgroundColor: colors.panel,
    borderTopColor: colors.border,
    borderTopWidth: 1,
    padding: spacing.md,
    gap: spacing.sm,
  },
  composer: {
    alignItems: 'flex-end',
    flexDirection: 'row',
    gap: spacing.sm,
  },
  error: {
    color: colors.danger,
    fontSize: 12,
    lineHeight: 16,
  },
  hint: {
    color: colors.muted,
    fontSize: 12,
    lineHeight: 16,
  },
  input: {
    backgroundColor: colors.panelAlt,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    color: colors.text,
    flex: 1,
    fontSize: 15,
    maxHeight: 96,
    minHeight: 42,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  micButton: {
    alignItems: 'center',
    backgroundColor: colors.panelAlt,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    height: 42,
    justifyContent: 'center',
    width: 58,
  },
  recording: {
    backgroundColor: '#58212c',
    borderColor: colors.danger,
  },
  buttonText: {
    color: colors.text,
    fontSize: 13,
    fontWeight: '700',
  },
  sendButton: {
    alignItems: 'center',
    backgroundColor: colors.accent,
    borderRadius: 6,
    height: 42,
    justifyContent: 'center',
    width: 64,
  },
  disabled: {
    opacity: 0.4,
  },
  sendText: {
    color: '#061019',
    fontSize: 13,
    fontWeight: '800',
  },
});
