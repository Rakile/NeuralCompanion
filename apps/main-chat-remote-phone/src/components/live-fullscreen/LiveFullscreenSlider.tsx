import { useThemedStyles, useThemeColors } from '../../styles/ThemeContext';
import type { ThemeColors } from '../../styles/theme';
import React from 'react';
import { PanResponder, StyleSheet, Text, View } from 'react-native';

import { colors, spacing } from '../../styles/theme';
import { sliderValueFromDrag } from '../../utils/liveFullscreenTransform';

type Props = {
  label: string;
  value: number;
  minimum: number;
  maximum: number;
  step?: number;
  suffix?: string;
  touchHeight?: number;
  onChange: (value: number) => void;
};

export function LiveFullscreenSlider({
  label,
  value,
  minimum,
  maximum,
  step = 1,
  suffix = '%',
  touchHeight,
  onChange,
}: Props) {
  const styles = useThemedStyles(createStyles);

  const [trackWidth, setTrackWidth] = React.useState(1);
  const [displayValue, setDisplayValue] = React.useState(value);
  const draggingRef = React.useRef(false);
  const startValueRef = React.useRef(value);
  const trackWidthRef = React.useRef(trackWidth);
  const minimumRef = React.useRef(minimum);
  const maximumRef = React.useRef(maximum);
  const stepRef = React.useRef(step);
  const onChangeRef = React.useRef(onChange);

  trackWidthRef.current = trackWidth;
  minimumRef.current = minimum;
  maximumRef.current = maximum;
  stepRef.current = step;
  onChangeRef.current = onChange;

  React.useEffect(() => {
    if (!draggingRef.current) {
      setDisplayValue(value);
    }
  }, [value]);

  const applyValueRef = React.useRef<(nextValue: number) => void>(() => undefined);
  applyValueRef.current = (nextValue: number) => {
    setDisplayValue(nextValue);
    onChangeRef.current(nextValue);
  };

  const responderRef = React.useRef<ReturnType<typeof PanResponder.create> | null>(null);
  if (!responderRef.current) {
    responderRef.current = PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderGrant: (event) => {
        draggingRef.current = true;
        const tappedValue = sliderValueFromDrag(
          minimumRef.current,
          event.nativeEvent.locationX,
          trackWidthRef.current,
          minimumRef.current,
          maximumRef.current,
          stepRef.current,
        );
        startValueRef.current = tappedValue;
        applyValueRef.current(tappedValue);
      },
      onPanResponderMove: (_event, gesture) => {
        applyValueRef.current(sliderValueFromDrag(
          startValueRef.current,
          gesture.dx,
          trackWidthRef.current,
          minimumRef.current,
          maximumRef.current,
          stepRef.current,
        ));
      },
      onPanResponderRelease: () => {
        draggingRef.current = false;
      },
      onPanResponderTerminate: () => {
        draggingRef.current = false;
      },
    });
  }
  const responder = responderRef.current;
  const ratio = Math.max(
    0,
    Math.min(1, (displayValue - minimum) / Math.max(step, maximum - minimum)),
  );

  return (
    <View style={styles.group}>
      <View style={styles.labelRow}>
        <Text style={styles.label}>{label}</Text>
        <Text style={styles.value}>
          {Number.isInteger(displayValue) ? displayValue : displayValue.toFixed(Math.max(1, Math.min(3, String(step).split('.')[1]?.length || 0)))}{suffix}
        </Text>
      </View>
      <View
        accessible
        // Keep locationX relative to the track when dragging its decorative thumb.
        pointerEvents="box-only"
        accessibilityLabel={label}
        accessibilityRole="adjustable"
        accessibilityValue={{ min: minimum, max: maximum, now: displayValue }}
        accessibilityActions={[{ name: 'increment' }, { name: 'decrement' }]}
        onAccessibilityAction={(event) => {
          const direction = event.nativeEvent.actionName === 'increment' ? 1 : -1;
          applyValueRef.current(Math.max(
            minimum,
            Math.min(maximum, displayValue + step * direction),
          ));
        }}
        onLayout={(event) => setTrackWidth(Math.max(1, event.nativeEvent.layout.width))}
        style={[styles.track, touchHeight ? { height: touchHeight } : null]}
        {...responder.panHandlers}
      >
        <View style={[styles.fill, { width: `${ratio * 100}%` }]} />
        <View style={[styles.thumb, { left: `${ratio * 100}%` }]} />
      </View>
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  group: { gap: spacing.xs },
  labelRow: { flexDirection: 'row', justifyContent: 'space-between' },
  label: { color: colors.text, fontSize: 13, fontWeight: '700', flex: 1, marginRight: spacing.sm },
  value: { color: colors.accent, fontSize: 12, fontWeight: '800' },
  track: {
    backgroundColor: colors.panelAlt,
    borderColor: colors.border,
    borderRadius: 8,
    borderWidth: 1,
    height: 20,
    justifyContent: 'center',
    overflow: 'visible',
  },
  fill: { backgroundColor: colors.accent, borderRadius: 6, height: 6 },
  thumb: {
    backgroundColor: colors.panel,
    borderColor: colors.accent,
    borderRadius: 9,
    borderWidth: 3,
    height: 18,
    marginLeft: -9,
    position: 'absolute',
    width: 18,
  },
});
