import React from 'react';
import { Animated, Image, Pressable, StyleSheet, View } from 'react-native';
import Svg, {
  Defs,
  Image as SvgImage,
  Mask,
  RadialGradient,
  Rect,
  Stop,
} from 'react-native-svg';

type Props = {
  imageUrl: string;
  visible: boolean;
  portalSpeedPct: number;
  edgeSoftnessPct: number;
  onDismiss: () => void;
  onReady: () => void;
  onRevealComplete: () => void;
  onLoadError: (message: string) => void;
};

export function VisualReplyPortal({
  imageUrl,
  visible,
  portalSpeedPct,
  edgeSoftnessPct,
  onDismiss,
  onReady,
  onRevealComplete,
  onLoadError,
}: Props) {
  const progress = React.useRef(new Animated.Value(0)).current;
  const [ready, setReady] = React.useState(false);

  React.useEffect(() => {
    let alive = true;
    if (!visible || !imageUrl) {
      progress.setValue(0);
      setReady(false);
      return () => {
        alive = false;
      };
    }
    Image.prefetch(imageUrl)
      .then((loaded) => {
        if (!alive || !loaded) {
          if (alive) onLoadError('The new Visual Reply image could not be loaded.');
          return;
        }
        setReady(true);
        onReady();
        const speed = Math.max(0.25, Math.min(2, portalSpeedPct / 100));
        Animated.timing(progress, {
          duration: Math.round(620 / speed),
          toValue: 1,
          useNativeDriver: true,
        }).start(({ finished }) => {
          if (finished) onRevealComplete();
        });
      })
      .catch(() => {
        if (alive) onLoadError('The new Visual Reply image could not be loaded.');
      });
    return () => {
      alive = false;
    };
  }, [
    imageUrl,
    onLoadError,
    onReady,
    onRevealComplete,
    portalSpeedPct,
    progress,
    visible,
  ]);

  if (!visible || !ready || !imageUrl) return null;
  const softness = Math.max(0, Math.min(1, edgeSoftnessPct / 200));
  const scale = progress.interpolate({ inputRange: [0, 1], outputRange: [0.06, 1] });
  const opacity = progress.interpolate({ inputRange: [0, 0.18, 1], outputRange: [0, 0.45, 1] });

  return (
    <View style={StyleSheet.absoluteFill}>
      <Pressable style={StyleSheet.absoluteFill} onPress={onDismiss}>
        <Animated.View style={[styles.portal, { opacity, transform: [{ scale }] }]}>
          <Svg width="100%" height="100%" viewBox="0 0 100 100">
            <Defs>
              <RadialGradient id="reply-soft-edge" cx="50%" cy="50%" rx="50%" ry="50%">
                <Stop offset={`${Math.round(68 - softness * 24)}%`} stopColor="#ffffff" stopOpacity="1" />
                <Stop offset="100%" stopColor="#000000" stopOpacity="0" />
              </RadialGradient>
              <Mask id="reply-mask">
                <Rect width="100" height="100" fill="url(#reply-soft-edge)" />
              </Mask>
            </Defs>
            <SvgImage
              href={{ uri: imageUrl }}
              width="100"
              height="100"
              preserveAspectRatio="xMidYMid slice"
              mask="url(#reply-mask)"
            />
          </Svg>
        </Animated.View>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  portal: {
    bottom: '8%',
    left: '5%',
    position: 'absolute',
    right: '5%',
    top: '8%',
  },
});
