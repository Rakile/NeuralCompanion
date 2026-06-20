import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { AudioChunk, AudioState } from '../api/types';
import type { PlaybackState } from '../hooks/useAudioQueue';
import { colors, spacing } from '../styles/theme';

type Props = {
  audio: AudioState | undefined;
  playback: PlaybackState;
  disabled?: boolean;
  demoMode?: boolean;
  onClearQueue?: () => Promise<void>;
};

function latestAudioChunk(items: AudioChunk[] | undefined): AudioChunk | undefined {
  return items && items.length ? items[items.length - 1] : undefined;
}

export function MediaPanel({ audio, playback, disabled = false, demoMode = false, onClearQueue }: Props) {
  const [clearing, setClearing] = useState(false);
  const [clearError, setClearError] = useState('');
  const latest = latestAudioChunk(audio?.items);
  const backendPlaybackText = audio?.backend_playback_suppressed ? ' - desktop muted' : '';
  const playbackDisabled = disabled || demoMode;
  const clearQueue = async () => {
    if (clearing) {
      return;
    }
    setClearing(true);
    setClearError('');
    try {
      if (onClearQueue) {
        await onClearQueue();
      }
      playback.reset();
    } catch (exc) {
      setClearError(exc instanceof Error ? exc.message : 'Could not clear phone audio queue.');
    } finally {
      setClearing(false);
    }
  };
  return (
    <View style={styles.panel}>
      <View style={styles.row}>
        <Text style={styles.title}>TTS</Text>
        <Text style={styles.meta} numberOfLines={2}>{audio?.status || 'idle'} - {audio?.items?.length ?? 0} chunks - {playback.playedCount} played{backendPlaybackText}</Text>
      </View>
      <View style={styles.controls}>
        <Pressable style={[styles.secondaryButton, playback.enabled && styles.activeButton]} onPress={() => playback.setEnabled(!playback.enabled)}>
          <Text style={styles.buttonText}>{playback.enabled ? 'Autoplay on' : 'Autoplay off'}</Text>
        </Pressable>
        <Text style={styles.meta}>Volume {Math.round(playback.volume * 100)}%</Text>
      </View>
      {latest ? (
        <View style={styles.row}>
          <Text style={styles.latest} numberOfLines={1}>{latest.speaker || 'Assistant'} - {latest.text || latest.id}</Text>
          <Pressable disabled={playbackDisabled} style={[styles.button, playbackDisabled && styles.disabled]} onPress={() => playback.playNow(latest)}>
            <Text style={styles.buttonText}>{demoMode ? 'Demo chunk' : playback.playingId === latest.id ? 'Playing' : 'Replay latest'}</Text>
          </Pressable>
        </View>
      ) : null}
      {audio?.items?.length ? (
        <View style={styles.controls}>
          <Pressable disabled={!playback.playingId} style={[styles.secondaryButton, !playback.playingId && styles.disabled]} onPress={playback.stop}>
            <Text style={styles.buttonText}>Stop</Text>
          </Pressable>
          <Pressable style={[styles.secondaryButton, clearing && styles.disabled]} disabled={clearing} onPress={clearQueue}>
            <Text style={styles.buttonText}>{clearing ? 'Clearing' : 'Clear queue'}</Text>
          </Pressable>
        </View>
      ) : null}
      {!latest ? (
        <View style={styles.emptyCard}>
          <Text style={styles.emptyTitle}>No phone audio yet</Text>
          <Text style={styles.metaLeft}>Connect to desktop or tap Demo. Phone TTS chunks appear here when NC generates speech for the remote app.</Text>
        </View>
      ) : null}
      {demoMode ? <Text style={styles.metaLeft}>Demo mode shows the phone audio queue without playing generated files.</Text> : null}
      {playback.error || clearError ? <Text style={styles.error}>{playback.error || clearError}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    backgroundColor: colors.panel,
    borderTopColor: colors.border,
    borderTopWidth: 1,
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  row: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: spacing.sm,
    justifyContent: 'space-between',
  },
  title: {
    color: colors.text,
    fontSize: 13,
    fontWeight: '800',
  },
  meta: {
    color: colors.muted,
    flex: 1,
    fontSize: 12,
    textAlign: 'right',
  },
  metaLeft: {
    color: colors.muted,
    fontSize: 12,
    textAlign: 'left',
  },
  latest: {
    color: colors.text,
    flex: 1,
    fontSize: 12,
  },
  button: {
    backgroundColor: colors.accentSoft,
    borderRadius: 6,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  buttonText: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '700',
  },
  controls: {
    flexDirection: 'row',
    gap: spacing.sm,
    justifyContent: 'flex-end',
  },
  secondaryButton: {
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  activeButton: {
    borderColor: colors.accent,
  },
  emptyCard: {
    backgroundColor: colors.panelAlt,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    gap: spacing.xs,
    padding: spacing.sm,
  },
  emptyTitle: {
    color: colors.text,
    fontSize: 13,
    fontWeight: '900',
  },
  disabled: {
    opacity: 0.35,
  },
  error: {
    color: colors.danger,
    fontSize: 12,
  },
});
