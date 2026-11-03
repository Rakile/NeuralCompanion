import { useThemedStyles, useThemeColors } from '../../styles/ThemeContext';
import type { ThemeColors } from '../../styles/theme';
import React from 'react';
import { PanResponder, Pressable, StyleSheet, View } from 'react-native';

import { colors } from '../../styles/theme';

type Props = { expanded: boolean; onChange: (expanded: boolean) => void };

export function ChatHeaderHandle({ expanded, onChange }: Props) {
  const styles = useThemedStyles(createStyles);

  const callback = React.useRef(onChange);
  callback.current = onChange;
  const gesture = React.useMemo(() => PanResponder.create({
    onMoveShouldSetPanResponder: (_event, state) => Math.abs(state.dy) > 8 && Math.abs(state.dy) > Math.abs(state.dx),
    onPanResponderRelease: (_event, state) => {
      if (state.dy > 18) callback.current(true);
      if (state.dy < -18) callback.current(false);
    },
  }), []);
  return (
    <View {...gesture.panHandlers} style={styles.touchArea}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={expanded ? 'Hide chat controls' : 'Show chat controls'}
        accessibilityHint="Pull down to show settings and chat views; swipe up to hide"
        accessibilityState={{ expanded }}
        hitSlop={{ top: 10, bottom: 10, left: 16, right: 16 }}
        onPress={() => onChange(!expanded)}
        style={styles.button}
      >
        <View style={[styles.handle, expanded && styles.active]} />
      </Pressable>
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  touchArea: { alignItems: 'center', backgroundColor: colors.backgroundElevated, height: 24, justifyContent: 'center' },
  button: { alignItems: 'center', height: 24, justifyContent: 'center', width: 88 },
  handle: { backgroundColor: colors.muted, borderRadius: 3, height: 3, opacity: 0.65, width: 36 },
  active: { backgroundColor: colors.accent, opacity: 1 },
});
