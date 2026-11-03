import React from 'react';
import { Animated, Pressable, StyleSheet, View } from 'react-native';
import { requireNativeView } from 'expo';
import type { ViewProps } from 'react-native';
import type { AVRemoteOutput } from '../relay/av';
import type { MuseTalkLiveSessionViewProps } from '../dev/MuseTalkLiveSessionView';
import { useMuseTalkFullscreenZoom } from '../hooks/useMuseTalkFullscreenZoom';
import { useAVPresentation } from './useAVPresentation';
import { useIdleLoopCache } from './useIdleLoopCache';

// Loaded only after BOTH factory/module and encrypted peer AV negotiation pass.
const NativeView = requireNativeView<ViewProps & { handle: string }>('ExpoAudio');

export function AVMuseTalkSessionView(props: MuseTalkLiveSessionViewProps & { output: AVRemoteOutput }) {
  const zoom = useMuseTalkFullscreenZoom(props.fullscreen);
  const enabled = props.eligible && props.foreground !== false;
  const handle = useAVPresentation(props.output, enabled, props.onPresentationReadyChange);
  useIdleLoopCache(props.client,props.output,enabled);
  React.useEffect(() => { props.onStartHandler(null); }, [props.onStartHandler]);
  React.useEffect(() => {
    props.onRenderingChange(enabled);
    return () => { props.onRenderingChange(false); };
  }, [enabled, props.onRenderingChange]);
  const inlineVisible = enabled && Boolean(props.presentation?.visible && props.presentation.displayReady && props.presentation.target);
  const bounds = props.presentation?.bounds ?? { x: 0, y: 0, width: 1, height: 1 };
  const target = props.presentation?.target;
  const inlineStyle = { left: bounds.x, top: bounds.y, width: bounds.width, height: bounds.height,
    borderRadius: target?.borderRadius ?? 0, opacity: inlineVisible ? 1 : 0 };
  return <View onLayout={zoom.onLayout}
    accessibilityElementsHidden={!props.fullscreen && !inlineVisible}
    importantForAccessibility={!props.fullscreen && !inlineVisible ? 'no-hide-descendants' : 'auto'}
    pointerEvents={props.fullscreen || inlineVisible ? 'auto' : 'none'}
    style={[styles.host, props.fullscreen ? styles.fullscreen : inlineStyle, !props.fullscreen && styles.inline]}>
    <Animated.View style={[styles.viewport, props.fullscreen && zoom.style]}>
      {props.presenceFallback}
      {enabled && handle ? <NativeView handle={handle} style={StyleSheet.absoluteFill} /> : null}
    </Animated.View>
    {props.fullscreen ? props.fullscreenControls(zoom.gestures) : inlineVisible && target ? <View pointerEvents="box-none" style={StyleSheet.absoluteFill}>
      {target.onLongPress ? <Pressable accessible accessibilityRole="button"
        accessibilityLabel={`${target.identity} avatar. Persona and model controls`}
        accessibilityHint="Long press to change persona or reply model" onAccessibilityTap={target.onLongPress}
        delayLongPress={450} onLongPress={target.onLongPress} style={StyleSheet.absoluteFill} /> : null}
      {target.overlay}
    </View> : null}
  </View>;
}

const styles = StyleSheet.create({
  host: { backgroundColor: '#000', position: 'absolute', overflow: 'hidden' },
  inline: { zIndex: 100 }, viewport: { flex: 1 },
  fullscreen: { ...StyleSheet.absoluteFillObject, zIndex: 2000, elevation: 30 },
});
