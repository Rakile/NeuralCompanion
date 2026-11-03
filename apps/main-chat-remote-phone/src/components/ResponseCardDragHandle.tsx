import React from 'react';
import { PanResponder, StyleSheet, Text, View } from 'react-native';
import { useThemedStyles } from '../styles/ThemeContext';
import type { ThemeColors } from '../styles/theme';
import type { ResponseCardId } from '../utils/responseCardOrder';

type Props = {
  id: ResponseCardId;
  title: string;
  active: boolean;
  onBegin: (id: ResponseCardId) => void;
  onMove: (id: ResponseCardId, dy: number, pageY: number) => void;
  onEnd: (id: ResponseCardId) => void;
  onCancel: (id: ResponseCardId) => void;
  onStep: (id: ResponseCardId, direction: -1 | 1) => void;
};

export function ResponseCardDragHandle({ id, title, active, onBegin, onMove, onEnd, onCancel, onStep }: Props) {
  const styles = useThemedStyles(createStyles);
  const latest = React.useRef({ onBegin, onMove, onEnd, onCancel, onStep });
  latest.current = { onBegin, onMove, onEnd, onCancel, onStep };
  const hold = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const dragging = React.useRef(false);
  const clearHold = () => { if (hold.current) clearTimeout(hold.current); hold.current = null; };
  React.useEffect(() => () => clearHold(), []);
  const responder = React.useMemo(() => PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onMoveShouldSetPanResponder: () => true,
    onPanResponderGrant: () => {
      clearHold();
      dragging.current = false;
      hold.current = setTimeout(() => { dragging.current = true; latest.current.onBegin(id); }, 320);
    },
    onPanResponderMove: (_event, gesture) => {
      if (!dragging.current && Math.abs(gesture.dy) > 10) clearHold();
      if (dragging.current) latest.current.onMove(id, gesture.dy, gesture.moveY);
    },
    onPanResponderRelease: () => {
      clearHold();
      if (dragging.current) latest.current.onEnd(id);
      dragging.current = false;
    },
    onPanResponderTerminate: () => {
      clearHold();
      if (dragging.current) latest.current.onCancel(id);
      dragging.current = false;
    },
  }), [id]);
  return <View {...responder.panHandlers} accessible accessibilityRole="adjustable"
    accessibilityLabel={`Reorder ${title} card`}
    accessibilityHint="Hold and drag, or swipe up or down with accessibility actions"
    accessibilityActions={[{ name: 'increment', label: 'Move up' }, { name: 'decrement', label: 'Move down' }]}
    onAccessibilityAction={event => {
      if (event.nativeEvent.actionName === 'increment') latest.current.onStep(id, -1);
      if (event.nativeEvent.actionName === 'decrement') latest.current.onStep(id, 1);
    }}
    style={[styles.handle, active && styles.active]}>
    <Text style={styles.grip}>⋮⋮</Text><Text style={styles.hold}>HOLD</Text>
  </View>;
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  handle: { minWidth: 48, minHeight: 46, alignItems: 'center', justifyContent: 'center',
    borderRadius: 9, borderWidth: 1, borderColor: colors.warning, backgroundColor: colors.panelAlt },
  active: { backgroundColor: colors.accentSoft, borderWidth: 2 },
  grip: { color: colors.warning, fontSize: 20, lineHeight: 21, fontWeight: '700' },
  hold: { color: colors.warning, fontSize: 9, lineHeight: 11, fontWeight: '700', letterSpacing: 1 },
});
