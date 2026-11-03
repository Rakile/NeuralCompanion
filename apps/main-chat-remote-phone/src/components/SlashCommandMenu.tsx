import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useThemedStyles } from '../styles/ThemeContext';
import type { ThemeColors } from '../styles/theme';
import type { SlashCommand } from '../utils/slashCommands';

export function SlashCommandMenu({ commands, busy, onChoose }: {
  commands: SlashCommand[]; busy: boolean; onChoose: (command: SlashCommand) => void;
}) {
  const styles = useThemedStyles(createStyles);
  return <View style={styles.panel}>
    <Text style={styles.title}>Commands · // sends a literal slash</Text>
    <ScrollView style={styles.list} keyboardShouldPersistTaps="always" nestedScrollEnabled>
      {commands.length ? commands.map(command => <Pressable key={command.name}
        accessibilityRole="button" accessibilityLabel={`/${command.name}`}
        accessibilityHint={command.disabledReason || command.description}
        accessibilityState={{ disabled: busy || Boolean(command.disabledReason) }}
        disabled={busy || Boolean(command.disabledReason)}
        style={[styles.row, Boolean(command.disabledReason) && styles.unavailable]}
        onPress={() => onChoose(command)}>
        <Text style={styles.name}>{command.usage || `/${command.name}`}</Text>
        <Text style={styles.detail}>{command.disabledReason || command.description}</Text>
      </Pressable>) : <Text style={styles.empty}>No matching command. Try /commands.</Text>}
    </ScrollView>
  </View>;
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  panel: { backgroundColor: colors.panel, borderRadius: 14, overflow: 'hidden', marginBottom: 6, flexShrink: 1 },
  title: { color: colors.muted, fontSize: 12, paddingHorizontal: 12, paddingVertical: 7 },
  list: { maxHeight: 174, flexShrink: 1 },
  row: { minHeight: 52, paddingVertical: 9, paddingHorizontal: 12, justifyContent: 'center' },
  name: { color: colors.accent, fontSize: 15, fontWeight: '700' },
  detail: { color: colors.textSecondary, fontSize: 12, marginTop: 2 },
  unavailable: { opacity: 0.6 },
  empty: { color: colors.textSecondary, padding: 12 },
});
