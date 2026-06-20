import React, { useEffect, useRef } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import type { ChatMessage } from '../api/types';
import { colors, spacing } from '../styles/theme';

export function ChatFeed({ messages }: { messages: ChatMessage[] }) {
  const scrollRef = useRef<ScrollView | null>(null);
  useEffect(() => {
    scrollRef.current?.scrollToEnd({ animated: true });
  }, [messages.length]);

  return (
    <ScrollView ref={scrollRef} style={styles.feed} contentContainerStyle={styles.content}>
      {messages.map((message) => (
        <View key={`${message.index}:${message.id}`} style={[styles.bubble, message.role === 'user' ? styles.user : styles.assistant]}>
          <Text style={styles.role}>{message.role || 'message'}</Text>
          <Text style={styles.message}>{message.content}</Text>
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
});
