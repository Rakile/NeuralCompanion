import React, { useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { colors, spacing } from '../styles/theme';

const labels: Record<string, string> = {
  pause_speech: 'Pause',
  skip_speech: 'Skip',
  skip_user_reply: 'Skip User',
  regenerate_response: 'Regenerate',
  retry_user_input: 'Retry',
  replay_last_assistant: 'Replay Last',
  replay_chat_session: 'Replay Chat',
};

type Props = {
  actions: string[];
  disabled: boolean;
  onControl: (action: string) => Promise<void>;
};

export function ControlsBar({ actions, disabled, onControl }: Props) {
  const [busyAction, setBusyAction] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    if (disabled) {
      setBusyAction('');
      setError('');
    }
  }, [disabled]);
  const trigger = async (action: string) => {
    if (disabled || busyAction) {
      return;
    }
    setBusyAction(action);
    setError('');
    try {
      await onControl(action);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Control action failed.');
    } finally {
      setBusyAction('');
    }
  };

  return (
    <View style={styles.panel}>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.scroller} contentContainerStyle={styles.row}>
        {actions.map((action) => {
          const busy = busyAction === action;
          const blocked = disabled || Boolean(busyAction);
          return (
            <Pressable key={action} disabled={blocked} style={[styles.button, blocked && styles.disabled]} onPress={() => trigger(action)}>
              <Text style={styles.text}>{busy ? 'Working' : labels[action] ?? action}</Text>
            </Pressable>
          );
        })}
      </ScrollView>
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    backgroundColor: colors.background,
    borderBottomColor: colors.border,
    borderBottomWidth: 1,
  },
  scroller: {
    maxHeight: 54,
  },
  row: {
    gap: spacing.sm,
    padding: spacing.sm,
  },
  button: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    height: 36,
    justifyContent: 'center',
    paddingHorizontal: spacing.md,
  },
  disabled: {
    opacity: 0.35,
  },
  text: {
    color: colors.text,
    fontSize: 13,
    fontWeight: '700',
  },
  error: {
    color: colors.danger,
    fontSize: 12,
    lineHeight: 16,
    paddingBottom: spacing.sm,
    paddingHorizontal: spacing.sm,
  },
});
