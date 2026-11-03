import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import type { ConversationActionKind, ConversationActionTarget, ConversationActionsSnapshot } from '../api/types';
import { spacing } from '../styles/theme';
import type { ThemeColors } from '../styles/theme';
import { useThemedStyles } from '../styles/ThemeContext';
import {QuickMenuActionButton} from './QuickMenuActionButton';
import {normalizeQuickMenuActions} from '../utils/quickMenuActions';
import type {QuickMenuPreferences} from '../utils/quickMenuActions';

export function ConversationControls({snapshot, disabled, busyAction, onAction, onRecover, onReset, resetDisabled = false,
  showConversationControls = true, showResetChat = true, quickMenuActions, onQuickMenuActionsChange}: QuickMenuPreferences & {
  snapshot?: ConversationActionsSnapshot; disabled: boolean; busyAction: string;
  onAction: (kind: ConversationActionKind, target: ConversationActionTarget) => Promise<void>;
  onRecover?: () => void;
  onReset?: () => void; resetDisabled?: boolean;
  showConversationControls?: boolean; showResetChat?: boolean;
}) {
  const styles = useThemedStyles(createStyles);
  return <View style={styles.row}>
    {showConversationControls ? (['regenerate','retry'] as const).filter(kind => normalizeQuickMenuActions(quickMenuActions)
      .includes(kind==='regenerate'?'regenerate_response':'retry_user_input')).map(kind => <QuickMenuActionButton key={kind} accessibilityRole="button"
      action={kind==='regenerate'?'regenerate_response':'retry_user_input'} quickMenuActions={quickMenuActions}
      onQuickMenuActionsChange={onQuickMenuActionsChange}
      accessibilityLabel={kind === 'regenerate' ? 'Regenerate' : 'Retry'}
      disabled={disabled || Boolean(busyAction) || !snapshot?.[kind]}
      style={[styles.button, (disabled || busyAction || !snapshot?.[kind]) && styles.disabled]}
      onPress={() => { if (snapshot?.[kind]) void onAction(kind, snapshot[kind]!); }}>
      <Text style={styles.text}>{kind === 'regenerate' ? 'Regenerate' : 'Retry'}</Text>
    </QuickMenuActionButton>) : null}
    {showResetChat ? <Pressable accessibilityRole="button" accessibilityLabel="Reset Chat"
      accessibilityState={{disabled:disabled || Boolean(busyAction) || resetDisabled || !onReset}}
      disabled={disabled || Boolean(busyAction) || resetDisabled || !onReset}
      style={[styles.button, (disabled || busyAction || resetDisabled || !onReset) && styles.disabled]}
      onPress={onReset}>
      <Text style={[styles.text, styles.danger]}>Reset Chat</Text>
    </Pressable> : null}
    {busyAction && (showConversationControls || showResetChat) ? <Text style={styles.status}>Waiting for {busyAction.replace('_',' ')}…</Text> : null}
    {showConversationControls && onRecover ? <Pressable accessibilityRole="button" onPress={onRecover}><Text style={styles.text}>Check action</Text></Pressable> : null}
  </View>;
}
const createStyles=(colors: ThemeColors)=>StyleSheet.create({row:{flexDirection:'row',flexWrap:'wrap',alignItems:'center',gap:spacing.sm,paddingHorizontal:spacing.md,paddingVertical:spacing.xs},
  button:{borderColor:colors.border,borderWidth:1,borderRadius:8,padding:spacing.sm},disabled:{opacity:0.4},text:{color:colors.text,fontWeight:'700'},danger:{color:colors.danger},status:{color:colors.muted,fontSize:12}});
