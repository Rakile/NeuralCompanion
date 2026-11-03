import { useThemedStyles, useThemeColors } from '../styles/ThemeContext';
import type { ThemeColors } from '../styles/theme';
import React, { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { RemoteState } from '../api/types';
import { colors, spacing } from '../styles/theme';

type Props = {
  showDetails?: boolean;
  state: RemoteState | null;
  disabled: boolean;
  onStart: () => Promise<void>;
  onStop: () => Promise<void>;
};

export function RuntimeBar({ state, disabled, onStart, onStop, showDetails = true }: Props) {
  const styles = useThemedStyles(createStyles);

  const [busy, setBusy] = useState(false);
  const [pendingKind, setPendingKind] = useState<'start' | 'stop' | null>(null);
  const pending = useRef<'start' | 'stop' | null>(null);
  const generation = useRef(0);
  const pendingGeneration = useRef(0);
  const mounted = useRef(true);
  const [error, setError] = useState('');
  const runtime = state?.runtime_status;
  const engine = state?.engine;
  const running = Boolean(engine?.running ?? runtime?.running);
  const initializing = Boolean(engine?.starting || engine?.initializing);
  const stopping = Boolean(engine?.stopping || engine?.cancelling);
  const cleanup = Boolean(engine?.cleanup_pending);
  const canStart = !disabled && !running && !initializing && !stopping && !cleanup && !busy;
  const canStop = !disabled && !stopping && pendingKind !== 'stop'
    && (initializing || cleanup || (running && !busy));
  const stopLabel = engine?.cancelling || (initializing && pendingKind === 'stop') ? 'Cancelling…' : stopping || pendingKind === 'stop' ? 'Stopping…'
    : initializing ? 'Cancel initialization' : cleanup ? 'Retry cleanup' : 'Stop';
  const buddy = state?.buddy_chat;
  const buddyAvailable = buddy?.available !== false && state?.features?.buddy_chat !== false;
  const buddyLabel = buddyAvailable
    ? buddy?.enabled
      ? `Buddies ${Number(buddy.active_persona_count ?? 0) || 'On'}`
      : 'Buddies Off'
    : '';
  useEffect(() => {
    if (disabled) {
      generation.current++;
      setError('');
    }
  }, [disabled]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; generation.current++; }; }, []);
  const trigger = async (kind: 'start' | 'stop', action: () => Promise<void>) => {
    if (disabled || pending.current === 'stop' || (kind === 'start' && pending.current)
      || (kind === 'start' ? !canStart : !canStop)) {
      return;
    }
    const mine = ++generation.current;
    pendingGeneration.current = mine;
    pending.current = kind;
    setPendingKind(kind);
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (exc) {
      if (mine === generation.current) setError(exc instanceof Error ? exc.message : 'Runtime command failed.');
    } finally {
      if (mine === pendingGeneration.current) {
        pending.current = null;
        if (mounted.current) { setBusy(false); setPendingKind(null); }
      }
    }
  };
  return (
    <View style={[styles.row, !showDetails && styles.actionsOnly]}>
      {showDetails ? <>
      <Text style={[styles.item, running ? styles.running : styles.stopped]}>{stopping ? stopLabel : initializing ? 'Initializing…' : running ? 'Running' : 'Stopped'}</Text>
      <Text style={styles.item}>{runtime?.chat_provider || 'chat'}</Text>
      <Text style={styles.item}>{runtime?.model_name || 'model'}</Text>
      <Text style={styles.item}>{runtime?.tts_backend || 'tts'}</Text>
      <Text style={styles.item}>{runtime?.microphone_state || 'mic'}</Text>
      {buddyLabel ? <Text style={[styles.item, buddy?.enabled ? styles.running : undefined]}>{buddyLabel}</Text> : null}
      </> : null}
      <Pressable accessibilityLabel="Start desktop runtime" accessibilityRole="button" accessibilityState={{ busy, disabled: !canStart }} disabled={!canStart} style={[styles.button, !canStart && styles.disabled]} onPress={() => trigger('start', onStart)}>
        <Text style={styles.buttonText}>Start</Text>
      </Pressable>
      <Pressable accessibilityLabel={initializing ? 'Cancel initialization' : cleanup ? 'Retry cleanup' : 'Stop desktop runtime'} accessibilityRole="button" accessibilityState={{ busy: pendingKind === 'stop', disabled: !canStop }} disabled={!canStop} style={[styles.button, initializing && styles.cancel, !canStop && styles.disabled]} onPress={() => trigger('stop', onStop)}>
        <Text style={styles.buttonText}>{initializing && !stopping ? '× ' : ''}{stopLabel}</Text>
      </Pressable>
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  actionsOnly: { backgroundColor: 'transparent', borderBottomWidth: 0, paddingHorizontal: 0, paddingVertical: 0, gap: 8 },
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
    minHeight: 44,
    paddingHorizontal: spacing.md,
  },
  disabled: {
    opacity: 0.35,
  },
  cancel: { borderColor: colors.warning, borderWidth: 1 },
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
