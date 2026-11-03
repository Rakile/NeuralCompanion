import React from 'react';
import { AppState, Image, StyleSheet, View } from 'react-native';
import { useEvent } from 'expo';
import { useVideoPlayer, VideoView } from 'expo-video';
import type { VideoSource } from 'expo-video';

import type { LiveFullscreenSettings } from '../../utils/liveFullscreenSettings';

const BUNDLED_STILL = require('../../../assets/live_fullscreen_matrix_face.png');
const BUNDLED_VIDEO = require('../../../assets/live_fullscreen_matrix_face.mp4');

type Props = {
  settings: LiveFullscreenSettings;
  visible: boolean;
  visualReplyOpen: boolean;
  onError?: (message: string) => void;
};

export function LiveFullscreenBackground({
  settings,
  visible,
  visualReplyOpen,
  onError,
}: Props) {
  const [failed, setFailed] = React.useState(false);
  const [appActive, setAppActive] = React.useState(AppState.currentState === 'active');
  const [layout, setLayout] = React.useState({ width: 1, height: 1 });
  const isVideo = !failed && (
    settings.backgroundKind === 'bundled_video'
    || settings.backgroundKind === 'custom_video'
  );
  const custom = settings.backgroundKind === 'custom_image' || settings.backgroundKind === 'custom_video';
  const videoSource: VideoSource | null = isVideo
    ? settings.backgroundKind === 'custom_video' && settings.backgroundUri
      ? { uri: settings.backgroundUri }
      : BUNDLED_VIDEO
    : null;
  const player = useVideoPlayer(videoSource, (instance) => {
    instance.loop = true;
    instance.muted = true;
    instance.volume = 0;
    instance.audioMixingMode = 'mixWithOthers';
  });
  const videoStatus = useEvent(player, 'statusChange', {
    status: player.status,
    error: undefined,
  });

  React.useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => setAppActive(state === 'active'));
    return () => subscription.remove();
  }, []);

  React.useEffect(() => {
    setFailed(false);
  }, [settings.backgroundKind, settings.backgroundUri]);

  React.useEffect(() => {
    player.loop = true;
    player.muted = true;
    player.volume = 0;
    player.audioMixingMode = 'mixWithOthers';
    const pauseForVisual = visualReplyOpen && settings.pauseVideoForVisual;
    if (visible && appActive && isVideo && !pauseForVisual) {
      player.play();
    } else {
      player.pause();
    }
  }, [appActive, isVideo, player, settings.pauseVideoForVisual, visible, visualReplyOpen]);

  React.useEffect(() => {
    if (videoStatus.status !== 'error' || failed) return;
    setFailed(true);
    onError?.('The selected MP4 could not be played. Using the bundled still image.');
  }, [failed, onError, videoStatus.status]);

  const opacity = Math.max(0, Math.min(1, settings.backgroundOpacityPct / 100));
  const intensity = Math.max(0, Math.min(1, (settings.backgroundOpacityPct - 100) / 100));
  const transform = [
    { translateX: layout.width * settings.backgroundOffsetXPct / 100 },
    { translateY: layout.height * settings.backgroundOffsetYPct / 100 },
    { scale: Math.max(0.25, Math.min(2, settings.backgroundScalePct / 100)) },
  ];
  const resizeMode = settings.backgroundResizeMode === 'fill' ? 'cover' : 'contain';
  const showBlack = settings.backgroundKind === 'none';
  const imageSource = failed
    ? BUNDLED_STILL
    : settings.backgroundKind === 'custom_image' && settings.backgroundUri
      ? { uri: settings.backgroundUri }
      : BUNDLED_STILL;

  return (
    <View
      pointerEvents="none"
      style={styles.root}
      onLayout={(event) => {
        const { width, height } = event.nativeEvent.layout;
        if (width > 0 && height > 0) {
          setLayout({ width, height });
        }
      }}
    >
      {!showBlack && isVideo && !failed ? (
        <VideoView
          player={player}
          style={[StyleSheet.absoluteFill, { opacity, transform }]}
          nativeControls={false}
          contentFit={resizeMode}
          surfaceType="textureView"
        />
      ) : !showBlack ? (
        <Image
          source={imageSource}
          style={[StyleSheet.absoluteFill, { opacity, transform }]}
          resizeMode={resizeMode}
          blurRadius={Math.round(Math.max(0, settings.backgroundSoftnessPct) / 18)}
          onError={() => {
            if (custom) {
              setFailed(true);
              onError?.('The custom background is unavailable. Using the bundled still image.');
            }
          }}
        />
      ) : null}
      {intensity > 0 ? (
        <View style={[StyleSheet.absoluteFill, { backgroundColor: `rgba(0,255,90,${intensity * 0.12})` }]} />
      ) : null}
      {settings.backgroundSoftnessPct > 0 && isVideo ? (
        <View
          style={[
            StyleSheet.absoluteFill,
            { backgroundColor: `rgba(0,0,0,${Math.min(0.36, settings.backgroundSoftnessPct / 550)})` },
          ]}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: '#000000',
    overflow: 'hidden',
  },
});
