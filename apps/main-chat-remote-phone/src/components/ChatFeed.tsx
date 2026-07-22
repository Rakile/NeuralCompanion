import React, { useEffect, useRef } from 'react';
import { Image, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { RemoteClient } from '../api/client';
import type { ChatMessage } from '../api/types';
import type { ChatIndicatorStyle, ChatTextColor } from '../hooks/usePhoneSettings';
import { useInterfaceMode } from '../context/InterfaceModeContext';
import { colors, spacing } from '../styles/theme';

type Props = {
  messages: ChatMessage[];
  client: RemoteClient;
  textColor?: ChatTextColor;
  indicatorStyle?: ChatIndicatorStyle;
  activity?: 'idle' | 'thinking' | 'speaking' | 'listening';
};

const cleanTextColors: Record<ChatTextColor, string> = {
  white: '#f4f7fa',
  green: '#8ff0b0',
  amber: '#ffd27a',
  cyan: '#83e6f5',
};

function ActivityIndicator({ activity, styleName }: { activity: NonNullable<Props['activity']>; styleName: ChatIndicatorStyle }) {
  return (
    <View style={styles.activityRow}>
      {styleName === 'dot' ? <View style={styles.activityDot} /> : null}
      {styleName === 'pulse' ? <View style={styles.activityPulse}><View style={styles.activityDot} /></View> : null}
      {styleName === 'line' ? <View style={styles.activityLine} /> : null}
      {styleName === 'text' ? <Text style={styles.activityText}>{activity}</Text> : null}
    </View>
  );
}

export function ChatFeed({ messages, client, textColor = 'white', indicatorStyle = 'dot', activity = 'idle' }: Props) {
  const { mode } = useInterfaceMode();
  const classicMode = mode === 'classic';
  const adaptiveMode = mode === 'adaptive';
  const flatMode = mode === 'flat';
  const immersiveMode = mode === 'immersive';
  const scrollRef = useRef<ScrollView | null>(null);
  useEffect(() => {
    scrollRef.current?.scrollToEnd({ animated: true });
  }, [messages.length]);

  return (
    <ScrollView
      ref={scrollRef}
      style={[styles.feed, adaptiveMode && styles.adaptiveFeed, flatMode && styles.flatFeed, immersiveMode && styles.immersiveFeed]}
      contentContainerStyle={[styles.content, !classicMode && styles.cleanContent, flatMode && styles.flatContent]}
    >
      {!classicMode ? <ActivityIndicator activity={activity} styleName={indicatorStyle} /> : null}
      {!messages.length ? (
        <View style={[styles.emptyCard, !classicMode && styles.cleanEmpty]}>
          <Text style={styles.emptyTitle}>No chat loaded</Text>
          <Text style={styles.emptyText}>Connect to desktop or tap Demo.</Text>
        </View>
      ) : null}
      {messages.map((message) => (
        <View
          key={`${message.index}:${message.id}`}
          style={classicMode
            ? [styles.bubble, message.role === 'user' ? styles.user : styles.assistant]
            : [styles.cleanMessageBlock, adaptiveMode && styles.adaptiveMessage, flatMode && styles.flatMessage, immersiveMode && styles.immersiveMessage]}
        >
          <Text style={[styles.role, !classicMode && styles.cleanRole]}>{message.role || 'message'}</Text>
          {message.image_url_path ? (
            <Image
              source={{ uri: client.authorizedUrl(message.image_url_path) }}
              style={styles.attachment}
              resizeMode="cover"
            />
          ) : null}
          <Text selectable={!classicMode} style={[styles.message, !classicMode && { color: cleanTextColors[textColor] }]}>{message.content}</Text>
        </View>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  feed: {
    flex: 1,
  },
  content: {
    gap: spacing.sm,
    padding: spacing.md,
  },
  emptyCard: {
    backgroundColor: colors.panel,
    borderColor: colors.border,
    borderRadius: 8,
    borderWidth: 1,
    gap: spacing.xs,
    padding: spacing.md,
  },
  emptyTitle: {
    color: colors.text,
    fontSize: 14,
    fontWeight: '900',
  },
  emptyText: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
  },
  bubble: {
    borderRadius: 8,
    borderWidth: 1,
    maxWidth: '94%',
    padding: spacing.md,
  },
  user: {
    alignSelf: 'flex-end',
    backgroundColor: colors.accentSoft,
    borderColor: '#2d5e7e',
  },
  assistant: {
    alignSelf: 'flex-start',
    backgroundColor: colors.panel,
    borderColor: colors.border,
  },
  role: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: '700',
    marginBottom: spacing.xs,
    textTransform: 'uppercase',
  },
  message: {
    color: colors.text,
    fontSize: 15,
    lineHeight: 21,
  },
  adaptiveFeed: { backgroundColor: '#0b0e11' },
  flatFeed: { backgroundColor: colors.background },
  immersiveFeed: { backgroundColor: '#000000' },
  cleanContent: { gap: spacing.lg, paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  flatContent: { gap: 0 },
  cleanMessageBlock: { alignSelf: 'stretch' },
  adaptiveMessage: { maxWidth: '94%' },
  flatMessage: { borderBottomColor: colors.border, borderBottomWidth: 1, paddingVertical: spacing.md },
  immersiveMessage: { paddingVertical: spacing.sm },
  cleanRole: { color: '#707780', marginBottom: spacing.sm },
  cleanEmpty: { backgroundColor: 'transparent', borderWidth: 0, paddingHorizontal: 0 },
  activityRow: { alignItems: 'center', height: 18, justifyContent: 'center' },
  activityDot: { backgroundColor: '#56d89b', borderRadius: 4, height: 7, width: 7 },
  activityPulse: { alignItems: 'center', borderColor: '#56d89b', borderRadius: 8, borderWidth: 1, height: 16, justifyContent: 'center', width: 16 },
  activityLine: { backgroundColor: '#56d89b', borderRadius: 1, height: 2, width: 52 },
  activityText: { color: '#8c959f', fontSize: 11, fontWeight: '700', textTransform: 'uppercase' },
  attachment: {
    aspectRatio: 4 / 3,
    borderRadius: 6,
    marginBottom: spacing.sm,
    maxWidth: 360,
    width: '100%',
  },
});
