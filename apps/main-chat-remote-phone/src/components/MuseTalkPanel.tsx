import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Animated, Easing, Image, StyleSheet, Text, View } from 'react-native';

import { RemoteClient } from '../api/client';
import type { MuseTalkState } from '../api/types';
import type { MuseTalkQuality } from '../hooks/usePhoneSettings';
import { colors, spacing } from '../styles/theme';

const STREAM_LOAD_TIMEOUT_MS = 4500;
const STREAM_STALL_TIMEOUT_MS = 8000;

type Props = {
  client: RemoteClient;
  musetalk: MuseTalkState | undefined;
  disabled: boolean;
  available: boolean;
  quality?: MuseTalkQuality;
  demoMode?: boolean;
};

function streamFpsForQuality(fps: number, quality: MuseTalkQuality): number {
  const base = Math.round(fps || 8);
  if (quality === 'low_latency') {
    return Math.max(2, Math.min(6, base || 6));
  }
  if (quality === 'quality') {
    return Math.max(4, Math.min(18, base || 12));
  }
  return Math.max(2, Math.min(12, base || 8));
}

function DemoMuseTalkAvatar({ speakingText }: { speakingText: string }) {
  const pulse = useRef(new Animated.Value(0)).current;
  const mouth = useRef(new Animated.Value(0)).current;
  const blink = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const pulseLoop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 900, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 0, duration: 900, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
      ]),
    );
    const mouthLoop = Animated.loop(
      Animated.sequence([
        Animated.timing(mouth, { toValue: 1, duration: 170, easing: Easing.linear, useNativeDriver: true }),
        Animated.timing(mouth, { toValue: 0, duration: 190, easing: Easing.linear, useNativeDriver: true }),
      ]),
    );
    const blinkLoop = Animated.loop(
      Animated.sequence([
        Animated.delay(1600),
        Animated.timing(blink, { toValue: 1, duration: 90, easing: Easing.linear, useNativeDriver: true }),
        Animated.timing(blink, { toValue: 0, duration: 110, easing: Easing.linear, useNativeDriver: true }),
      ]),
    );
    pulseLoop.start();
    mouthLoop.start();
    blinkLoop.start();
    return () => {
      pulseLoop.stop();
      mouthLoop.stop();
      blinkLoop.stop();
    };
  }, [blink, mouth, pulse]);

  const auraScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.96, 1.04] });
  const mouthScale = mouth.interpolate({ inputRange: [0, 1], outputRange: [0.55, 1.45] });
  const eyeScale = blink.interpolate({ inputRange: [0, 1], outputRange: [1, 0.12] });

  return (
    <View style={styles.demoAvatarStage}>
      <Animated.View style={[styles.demoAvatarAura, { transform: [{ scale: auraScale }] }]} />
      <View style={styles.demoAvatarFace}>
        <View style={styles.demoAvatarHair} />
        <View style={styles.demoAvatarEyes}>
          <Animated.View style={[styles.demoAvatarEye, { transform: [{ scaleY: eyeScale }] }]} />
          <Animated.View style={[styles.demoAvatarEye, { transform: [{ scaleY: eyeScale }] }]} />
        </View>
        <View style={styles.demoAvatarNose} />
        <Animated.View style={[styles.demoAvatarMouth, { transform: [{ scaleY: mouthScale }] }]} />
      </View>
      <Text style={styles.demoAvatarText} numberOfLines={2}>{speakingText}</Text>
    </View>
  );
}

export function MuseTalkPanel({ client, musetalk, disabled, available, quality = 'balanced', demoMode = false }: Props) {
  const [streamFailed, setStreamFailed] = useState(false);
  const [streamLoaded, setStreamLoaded] = useState(false);
  const [lastStreamAdvanceAt, setLastStreamAdvanceAt] = useState(() => Date.now());
  const lastStreamVersionRef = useRef('');
  const mediaDisabled = disabled || !available;
  const feed = musetalk?.feed;
  const latestFeed = feed && feed.length ? feed[feed.length - 1] : undefined;
  const latestFrame = musetalk?.frames?.length ? musetalk.frames[musetalk.frames.length - 1] : undefined;
  const pipeline = musetalk?.pipeline ?? {};
  const pipelineActive = Boolean(pipeline.active || pipeline.stream_open || pipeline.stream_mode);
  const streamPath = musetalk?.stream_url_path || musetalk?.state?.stream_url_path;
  const framePath = musetalk?.state?.frame_url_path || latestFeed?.frame_url_path || latestFrame?.url_path;
  const frameVersion = latestFeed?._seq ?? musetalk?.state?.preview_frame_index ?? musetalk?.state?.updated_at ?? 0;
  const streamVersion = String(latestFeed?._seq ?? musetalk?.state?.preview_frame_index ?? musetalk?.state?.updated_at ?? '');
  const fps = mediaDisabled ? 0 : (musetalk?.state?.fps ?? 0);
  const streamFps = streamFpsForQuality(fps, quality);
  const usingStream = Boolean(!mediaDisabled && streamPath && !streamFailed);
  const activePath = mediaDisabled ? '' : usingStream ? streamPath : framePath;
  const frameUrl = useMemo(() => {
    if (!activePath) {
      return '';
    }
    const params: Record<string, string> = {};
    if (usingStream) {
      params.fps = String(streamFps);
      params.wait = '2';
    } else if (activePath === framePath && frameVersion) {
      params.v = String(frameVersion);
    }
    return client.authorizedUrl(activePath, params);
  }, [activePath, client, framePath, frameVersion, streamFps, usingStream]);
  const mode = disabled ? 'offline' : !available ? 'unavailable' : usingStream ? 'stream' : framePath ? 'frame' : 'idle';
  const statusText = disabled ? 'offline' : available ? musetalk?.state?.status || 'idle' : 'unavailable';
  const caption = mediaDisabled ? 'No frame' : musetalk?.state?.text || musetalk?.state?.chunk_id || 'No frame';

  useEffect(() => {
    setStreamFailed(false);
    setStreamLoaded(false);
    setLastStreamAdvanceAt(Date.now());
    lastStreamVersionRef.current = '';
  }, [available, client.baseUrl, client.pairingCode, disabled, streamPath]);

  useEffect(() => {
    if (!usingStream || !frameUrl || streamLoaded) {
      return undefined;
    }
    const timer = setTimeout(() => {
      setStreamFailed(true);
    }, STREAM_LOAD_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [frameUrl, streamLoaded, usingStream]);

  useEffect(() => {
    if (!usingStream) {
      lastStreamVersionRef.current = '';
      return;
    }
    if (streamVersion && streamVersion !== lastStreamVersionRef.current) {
      lastStreamVersionRef.current = streamVersion;
      setLastStreamAdvanceAt(Date.now());
    }
  }, [streamVersion, usingStream]);

  useEffect(() => {
    if (!usingStream || !streamLoaded || !pipelineActive) {
      return undefined;
    }
    const timer = setTimeout(() => {
      if (Date.now() - lastStreamAdvanceAt >= STREAM_STALL_TIMEOUT_MS) {
        setStreamFailed(true);
      }
    }, STREAM_STALL_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [lastStreamAdvanceAt, pipelineActive, streamLoaded, usingStream]);

  return (
    <View style={styles.panel}>
      <View style={styles.header}>
        <Text style={styles.title}>MuseTalk</Text>
        <Text style={styles.meta}>{statusText} - {streamFps} fps - {mode} - {quality.replace('_', ' ')}</Text>
      </View>
      {frameUrl ? (
        <Image
          source={{ uri: frameUrl }}
          resizeMode="contain"
          style={styles.frame}
          onLoad={() => {
            if (usingStream) {
              setStreamLoaded(true);
            }
          }}
          onError={() => {
            if (usingStream) {
              setStreamFailed(true);
            }
          }}
        />
      ) : demoMode ? (
        <DemoMuseTalkAvatar speakingText={caption} />
      ) : null}
      <Text style={styles.caption} numberOfLines={1}>{caption}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    backgroundColor: colors.panel,
    borderTopColor: colors.border,
    borderTopWidth: 1,
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  header: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  title: {
    color: colors.text,
    fontSize: 13,
    fontWeight: '800',
  },
  meta: {
    color: colors.muted,
    fontSize: 12,
  },
  frame: {
    alignSelf: 'center',
    aspectRatio: 16 / 9,
    backgroundColor: colors.background,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    maxHeight: 160,
    width: '100%',
  },
  demoAvatarStage: {
    alignItems: 'center',
    alignSelf: 'center',
    aspectRatio: 16 / 9,
    backgroundColor: colors.background,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    justifyContent: 'center',
    maxHeight: 180,
    overflow: 'hidden',
    width: '100%',
  },
  demoAvatarAura: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.accent,
    borderRadius: 999,
    borderWidth: 1,
    height: 170,
    opacity: 0.54,
    position: 'absolute',
    width: 170,
  },
  demoAvatarFace: {
    alignItems: 'center',
    backgroundColor: '#172534',
    borderColor: '#80d4ff',
    borderRadius: 999,
    borderWidth: 2,
    height: 118,
    justifyContent: 'center',
    overflow: 'hidden',
    width: 118,
  },
  demoAvatarHair: {
    backgroundColor: '#10151d',
    borderBottomLeftRadius: 60,
    borderBottomRightRadius: 60,
    height: 38,
    left: 0,
    position: 'absolute',
    right: 0,
    top: 0,
  },
  demoAvatarEyes: {
    flexDirection: 'row',
    gap: 22,
    marginTop: 8,
  },
  demoAvatarEye: {
    backgroundColor: '#dff7ff',
    borderRadius: 999,
    height: 11,
    width: 11,
  },
  demoAvatarNose: {
    backgroundColor: '#5b7590',
    borderRadius: 999,
    height: 18,
    marginTop: 8,
    width: 4,
  },
  demoAvatarMouth: {
    backgroundColor: colors.accent,
    borderRadius: 999,
    height: 9,
    marginTop: 10,
    width: 34,
  },
  demoAvatarText: {
    bottom: spacing.sm,
    color: colors.text,
    fontSize: 12,
    left: spacing.md,
    position: 'absolute',
    right: spacing.md,
    textAlign: 'center',
  },
  caption: {
    color: colors.muted,
    fontSize: 12,
  },
});
