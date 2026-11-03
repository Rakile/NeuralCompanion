import React from 'react';
import { Image, PanResponder, Pressable, StyleSheet, Text, View } from 'react-native';
import type { GestureResponderEvent, StyleProp, ViewStyle } from 'react-native';
import { useThemeColors } from '../styles/ThemeContext';
import { controlGlyphTypography } from '../styles/theme';

type Position = { scale: number; x: number; y: number };
const initial: Position = { scale: 1, x: 0, y: 0 };

/** Shared enlarged-image surface; gestures never touch playback or the chat scroll. */
export function ZoomableImage({ uri, style, onReload }: { uri: string; style: StyleProp<ViewStyle>; onReload?: () => void }) {
  const colors = useThemeColors();
  const [position, setPosition] = React.useState(initial);
  const [failedUri, setFailedUri] = React.useState('');
  const current = React.useRef(initial);
  const size = React.useRef({ width: 0, height: 0 });
  const previous = React.useRef<{ count: number; x: number; y: number; distance: number } | null>(null);
  const update = (next: Position) => {
    const scale = Math.max(1, Math.min(5, next.scale));
    const boundX = size.current.width * (scale - 1) / 2;
    const boundY = size.current.height * (scale - 1) / 2;
    current.current = { scale, x: Math.max(-boundX, Math.min(boundX, next.x)), y: Math.max(-boundY, Math.min(boundY, next.y)) };
    setPosition(current.current);
  };
  React.useEffect(() => { previous.current = null; update(initial); }, [uri]);
  const sample = (event: GestureResponderEvent) => {
    const touches = event.nativeEvent.touches;
    if (!touches.length) return null;
    const a = touches[0], b = touches[1];
    if (!a) return null;
    return { count: touches.length, x: b ? (a.pageX + b.pageX) / 2 : a.pageX,
      y: b ? (a.pageY + b.pageY) / 2 : a.pageY,
      distance: b ? Math.hypot(a.pageX - b.pageX, a.pageY - b.pageY) : 0 };
  };
  const responder = React.useMemo(() => PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onMoveShouldSetPanResponder: () => true,
    onPanResponderGrant: event => { previous.current = sample(event); },
    onPanResponderMove: event => {
      const next = sample(event), old = previous.current;
      previous.current = next;
      if (!next || !old || next.count !== old.count) return;
      const p = current.current;
      update({ scale: next.count >= 2 && old.distance > 0 ? p.scale * next.distance / old.distance : p.scale,
        x: p.x + next.x - old.x, y: p.y + next.y - old.y });
    },
    onPanResponderRelease: () => { previous.current = null; },
    onPanResponderTerminate: () => { previous.current = null; },
    onPanResponderTerminationRequest: () => false,
  }), []);
  return (
    <View style={[style, styles.viewport]} onLayout={event => { size.current = event.nativeEvent.layout; update(current.current); }}>
      <View style={StyleSheet.absoluteFill} {...responder.panHandlers}>
        <Image source={{ uri }} accessibilityLabel="Visual Reply. Pinch to zoom and drag to pan." resizeMode="contain"
          onError={() => setFailedUri(uri)}
          style={[StyleSheet.absoluteFill, { transform: [{ translateX: position.x }, { translateY: position.y }, { scale: position.scale }] }]} />
      </View>
      {failedUri === uri ? <View style={[StyleSheet.absoluteFill, styles.failure, { backgroundColor: colors.panel }]}>
        <Text accessibilityRole="alert" style={{ color: colors.text }}>Could not load this image.</Text>
        {onReload ? <Pressable accessibilityRole="button" accessibilityLabel="Reload image" style={styles.button}
          onPress={() => { setFailedUri(''); onReload(); }}><Text style={{ color: colors.accent }}>Reload image</Text></Pressable> : null}
      </View> : null}
      <View style={[styles.toolbar, { backgroundColor: colors.panel, borderColor: colors.border }]}>
        <Pressable accessibilityRole="button" accessibilityLabel="Zoom out" onPress={() => update({ ...current.current, scale: current.current.scale / 1.5 })} style={styles.button}><Text style={[{ color: colors.text },controlGlyphTypography]}>−</Text></Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Fit image" onPress={() => update(initial)} style={styles.button}><Text style={{ color: colors.text }}>Fit</Text></Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Zoom in" onPress={() => update({ ...current.current, scale: current.current.scale * 1.5 })} style={styles.button}><Text style={[{ color: colors.text },controlGlyphTypography]}>+</Text></Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  failure: { alignItems: 'center', justifyContent: 'center', gap: 12 },
  viewport: { overflow: 'hidden' },
  toolbar: { position: 'absolute', right: 8, top: 8, flexDirection: 'row', borderRadius: 22, borderWidth: 1 },
  button: { minWidth: 44, minHeight: 44, alignItems: 'center', justifyContent: 'center' },
});
