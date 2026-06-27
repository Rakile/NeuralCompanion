import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { RemoteState } from '../api/types';
import { colors, spacing } from '../styles/theme';

type Props = {
  state: RemoteState | null;
  disabled: boolean;
  onStart: () => Promise<void>;
  onStop: () => Promise<void>;
};

export function RuntimeBar({ state, disabled, onStart, onStop }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const runtime = state?.runtime_status;
  const engine = state?.engine;
  const running = Boolean(engine?.running ?? runtime?.running);
  const buddy = state?.buddy_chat;
  const buddyAvailable = buddy?.available !== false && state?.features?.buddy_chat !== false;
  const buddyLabel = buddyAvailable
    ? buddy?.enabled
      ? `Buddies ${Number(buddy.active_persona_count ?? 0) || 'On'}`
      : 'Buddies Off'
    : '';
  useEffect(() => {
    if (disabled) {
      setBusy(false);
      setError('');
    }
  }, [disabled]);
  const trigger = async (action: () => Promise<void>) => {
    if (busy) {
      return;
    }
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Runtime command failed.');
    } finally {
      setBusy(false);
    }
  };
  return (
    <View style={styles.row}>
      <Text style={[styles.item, running ? styles.running : styles.stopped]}>{running ? 'Running' : 'Stopped'}</Text>
      <Text style={styles.item}>{runtime?.chat_provider || 'chat'}</Text>
      <Text style={styles.item}>{runtime?.model_name || 'model'}</Text>
      <Text style={styles.item}>{runtime?.tts_backend || 'tts'}</Text>
      <Text style={styles.item}>{runtime?.microphone_state || 'mic'}</Text>
      {buddyLabel ? <Text style={[styles.item, buddy?.enabled ? styles.running : undefined]}>{buddyLabel}</Text> : null}
      <Pressable disabled={disabled || running || busy} style={[styles.button, (disabled || running || busy) && styles.disabled]} onPress={() => trigger(onStart)}>
        <Text style={styles.buttonText}>Start</Text>
      </Pressable>
      <Pressable disabled={disabled || !running || busy} style={[styles.button, (disabled || !running || busy) && styles.disabled]} onPress={() => trigger(onStop)}>
        <Text style={styles.buttonText}>Stop</Text>
      </Pressable>
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    backgroundColor: colors.panelAlt,
    borderBottomColor: colors.border,
    borderBottomWidth: 1,
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  item: {
    backgroundColor: colors.panel,
    borderColor: colors.border,
    borderRadius: 4,
    borderWidth: 1,
    color: colors.muted,
    fontSize: 12,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  running: {
    color: colors.ok,
  },
  stopped: {
    color: colors.warning,
  },
  button: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.border,
    borderRadius: 4,
    borderWidth: 1,
    justifyContent: 'center',
    minHeight: 28,
    paddingHorizontal: spacing.md,
  },
  disabled: {
    opacity: 0.35,
  },
  buttonText: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '700',
  },
  error: {
    color: colors.danger,
    fontSize: 12,
    width: '100%',
  },
});
