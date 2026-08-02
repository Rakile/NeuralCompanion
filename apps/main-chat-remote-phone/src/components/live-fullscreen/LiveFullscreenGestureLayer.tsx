import React from 'react';
import { PanResponder, StyleSheet, Vibration, View } from 'react-native';
import { useAudioPlayer } from 'expo-audio';

import {
  FULLSCREEN_DOUBLE_TAP_MS,
  FULLSCREEN_GESTURE_MOVE_LIMIT_PX,
} from '../../utils/liveFullscreenGestures';
import {
  createFullscreenTransformResponderCallbacks,
  twoTouchMetrics,
} from '../../utils/liveFullscreenTransform';
import type { TwoTouchMetrics } from '../../utils/liveFullscreenTransform';

const PLONG = require('../../../assets/live_fullscreen_plong.wav');

type Props = {
  longPressSeconds: number;
  vibrationEnabled: boolean;
  plongEnabled: boolean;
  transformEnabled: boolean;
  onSingleTap: () => void;
  onDoubleTap: () => void;
  onLongPress: () => void;
  onTransformStart: (metrics: TwoTouchMetrics) => void;
  onTransformPreview: (metrics: TwoTouchMetrics) => void;
  onTransformCommit: () => void;
};

export function LiveFullscreenGestureLayer({
  longPressSeconds,
  vibrationEnabled,
  plongEnabled,
  transformEnabled,
  onSingleTap,
  onDoubleTap,
  onLongPress,
  onTransformStart,
  onTransformPreview,
  onTransformCommit,
}: Props) {
  const chime = useAudioPlayer(PLONG);
  const movedRef = React.useRef(false);
  const longCompletedRef = React.useRef(false);
  const transformingRef = React.useRef(false);
  const transformSequenceRef = React.useRef(false);
  const lastTapRef = React.useRef(0);
  const singleTapTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const longTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const vibrationTimerRef = React.useRef<ReturnType<typeof setInterval> | null>(null);
  const callbacksRef = React.useRef({
    onDoubleTap,
    onLongPress,
    onSingleTap,
    onTransformCommit,
    onTransformPreview,
    onTransformStart,
  });
  const optionsRef = React.useRef({
    longPressSeconds,
    plongEnabled,
    transformEnabled,
    vibrationEnabled,
  });
  callbacksRef.current = {
    onDoubleTap,
    onLongPress,
    onSingleTap,
    onTransformCommit,
    onTransformPreview,
    onTransformStart,
  };
  optionsRef.current = {
    longPressSeconds,
    plongEnabled,
    transformEnabled,
    vibrationEnabled,
  };

  const clearHoldTimers = React.useCallback(() => {
    if (longTimerRef.current) clearTimeout(longTimerRef.current);
    if (vibrationTimerRef.current) clearInterval(vibrationTimerRef.current);
    longTimerRef.current = null;
    vibrationTimerRef.current = null;
  }, []);

  const completeLongPressRef = React.useRef(() => undefined);
  completeLongPressRef.current = () => {
    if (movedRef.current || longCompletedRef.current) return;
    longCompletedRef.current = true;
    if (optionsRef.current.vibrationEnabled) Vibration.vibrate(120);
    if (optionsRef.current.plongEnabled) {
      chime.seekTo(0).then(() => chime.play()).catch(() => undefined);
    }
    callbacksRef.current.onLongPress();
  };

  const finishTransformRef = React.useRef(() => undefined);
  finishTransformRef.current = () => {
    if (!transformingRef.current) return;
    transformingRef.current = false;
    callbacksRef.current.onTransformCommit();
  };

  const beginTransformRef = React.useRef<(metrics: TwoTouchMetrics) => void>(() => undefined);
  beginTransformRef.current = (metrics: TwoTouchMetrics) => {
    clearHoldTimers();
    if (singleTapTimerRef.current) {
      clearTimeout(singleTapTimerRef.current);
      singleTapTimerRef.current = null;
      lastTapRef.current = 0;
    }
    movedRef.current = true;
    if (!transformSequenceRef.current) {
      transformSequenceRef.current = true;
      if (optionsRef.current.transformEnabled) {
        transformingRef.current = true;
        callbacksRef.current.onTransformStart(metrics);
      }
    }
    if (transformingRef.current) {
      callbacksRef.current.onTransformPreview(metrics);
    }
  };

  const responderRef = React.useRef<ReturnType<typeof PanResponder.create> | null>(null);
  if (!responderRef.current) {
    const transformCallbacks = createFullscreenTransformResponderCallbacks({
      isTransforming: () => transformingRef.current,
      onSingleTouchMove: (distancePx) => {
        if (distancePx > FULLSCREEN_GESTURE_MOVE_LIMIT_PX) {
          movedRef.current = true;
          clearHoldTimers();
        }
      },
      onTransformContact: (metrics) => beginTransformRef.current(metrics),
      onTransformEnd: () => finishTransformRef.current(),
    });
    responderRef.current = PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderGrant: (event) => {
        clearHoldTimers();
        movedRef.current = false;
        longCompletedRef.current = false;
        transformingRef.current = false;
        transformSequenceRef.current = false;
        const metrics = twoTouchMetrics(event.nativeEvent.touches);
        if (metrics) {
          beginTransformRef.current(metrics);
          return;
        }
        longTimerRef.current = setTimeout(
          () => completeLongPressRef.current(),
          Math.max(1000, Math.min(6000, optionsRef.current.longPressSeconds * 1000)),
        );
        if (optionsRef.current.vibrationEnabled) {
          vibrationTimerRef.current = setInterval(() => Vibration.vibrate(70), 700);
        }
      },
      ...transformCallbacks,
      onPanResponderRelease: () => {
        clearHoldTimers();
        if (transformingRef.current) {
          finishTransformRef.current();
        }
        if (transformSequenceRef.current) {
          transformSequenceRef.current = false;
          return;
        }
        if (movedRef.current || longCompletedRef.current) return;
        const now = Date.now();
        if (now - lastTapRef.current <= FULLSCREEN_DOUBLE_TAP_MS) {
          if (singleTapTimerRef.current) clearTimeout(singleTapTimerRef.current);
          singleTapTimerRef.current = null;
          lastTapRef.current = 0;
          callbacksRef.current.onDoubleTap();
          return;
        }
        lastTapRef.current = now;
        singleTapTimerRef.current = setTimeout(() => {
          singleTapTimerRef.current = null;
          lastTapRef.current = 0;
          callbacksRef.current.onSingleTap();
        }, FULLSCREEN_DOUBLE_TAP_MS);
      },
      onPanResponderTerminate: () => {
        clearHoldTimers();
        finishTransformRef.current();
        transformSequenceRef.current = false;
      },
    });
  }
  const responder = responderRef.current;

  React.useEffect(() => () => {
    clearHoldTimers();
    if (singleTapTimerRef.current) clearTimeout(singleTapTimerRef.current);
    finishTransformRef.current();
  }, [clearHoldTimers]);

  return <View style={StyleSheet.absoluteFill} {...responder.panHandlers} />;
}
