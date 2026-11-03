import React from 'react';
import {PanResponder, Pressable, StyleSheet, Text, View} from 'react-native';
import {useThemedStyles} from '../styles/ThemeContext';
import type {ThemeColors} from '../styles/theme';

type Props = {
  message: string;
  actionLabel?: string;
  onAction?: () => void;
};

/** A local dismissal never acknowledges or clears the underlying fault. */
export function DismissibleFault({message, actionLabel, onAction}: Props) {
  const styles = useThemedStyles(createStyles, 'DismissibleFault');
  const [dismissed, setDismissed] = React.useState('');
  React.useEffect(() => { if (!message) setDismissed(''); }, [message]);
  const gesture = React.useMemo(() => PanResponder.create({
    onMoveShouldSetPanResponder: (_event, state) =>
      state.dx > 12 && state.dx > Math.abs(state.dy) * 1.3,
    onPanResponderRelease: (_event, state) => {
      if (state.dx >= 72 && state.dx > Math.abs(state.dy) * 1.3) setDismissed(message);
    },
  }), [message]);
  if (!message || dismissed === message) return null;
  return <View {...gesture.panHandlers} style={styles.container}>
    <View style={styles.row}>
      <Text accessibilityRole="alert" style={styles.text}>{message}</Text>
      <Pressable accessibilityRole="button" accessibilityLabel="Dismiss fault message"
        accessibilityHint="Hides this message. A new fault will appear again."
        hitSlop={10} onPress={() => setDismissed(message)} style={styles.dismiss}>
        <Text style={styles.dismissText}>×</Text>
      </Pressable>
    </View>
    {actionLabel && onAction ? <Pressable accessibilityRole="button" accessibilityLabel={actionLabel}
      onPress={onAction} style={styles.action}>
      <Text style={styles.actionText}>{actionLabel} ›</Text>
    </Pressable> : null}
  </View>;
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  container: {borderLeftWidth:2, borderLeftColor:colors.danger, paddingLeft:12,
    paddingRight:16, paddingVertical:6, gap:2},
  row: {flexDirection:'row', alignItems:'flex-start', gap:8},
  text: {color:colors.danger, fontSize:12, lineHeight:17, flex:1},
  dismiss: {minWidth:32, minHeight:32, alignItems:'center', justifyContent:'center'},
  dismissText: {color:colors.danger, fontSize:22, lineHeight:25},
  action: {minHeight:32, justifyContent:'center', alignSelf:'flex-start'},
  actionText: {color:colors.accent, fontSize:12, fontWeight:'700'},
});
