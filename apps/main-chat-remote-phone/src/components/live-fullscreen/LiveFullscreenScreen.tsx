import React from 'react';
import {
  Animated,
  Modal,
  SafeAreaView,
  StatusBar,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import type { RemoteClient } from '../../api/client';
import type { RemoteState } from '../../api/types';
import type { PlaybackState } from '../../hooks/useAudioQueue';
import { useAuthorizedMediaUrl } from '../../hooks/useAuthorizedMediaUrl';
import { useSpectrumPlayback } from '../../hooks/useSpectrumPlayback';
import {
  captureVisualReplyBaseline,
  isFreshVisualReply,
} from '../../utils/liveFullscreenVisual';
import { shouldExitLiveFullscreen } from '../../utils/liveFullscreenSession';
import type { LiveFullscreenSettings } from '../../utils/liveFullscreenSettings';
import {
  advanceMicSpectrumHistoryState,
  composeLiveFullscreenEnergies,
  createMicSpectrumHistoryState,
  directionalSpectrumSeconds,
  proceduralSpectrum,
  SPECTRUM_BARS,
} from '../../utils/liveFullscreenSpectrum';
import {
  backgroundTransformFromGesture,
  chooseTransformTarget,
  circleTransformFromGesture,
} from '../../utils/liveFullscreenTransform';
import type {
  FullscreenTransformTarget,
  TwoTouchMetrics,
} from '../../utils/liveFullscreenTransform';
import { AudioSampleTap } from './AudioSampleTap';
import { CircularSpectrum } from './CircularSpectrum';
import type { SpectrumActivity } from './CircularSpectrum';
import { LiveFullscreenActionTray } from './LiveFullscreenActionTray';
import { LiveFullscreenBackground } from './LiveFullscreenBackground';
import { LiveFullscreenGestureLayer } from './LiveFullscreenGestureLayer';
import { VisualReplyPortal } from './VisualReplyPortal';

type Props = {
  visible: boolean;
  connected: boolean;
  sessionActive: boolean;
  demoMode: boolean;
  state: RemoteState | null;
  client: RemoteClient;
  playback: PlaybackState;
  activity: SpectrumActivity;
  meteringDb: number | null | undefined;
  meteringRevision: number;
  microphoneActive: boolean;
  microphoneSpeechDetected: boolean;
  settings: LiveFullscreenSettings;
  onSettingsChange: (updates: Partial<LiveFullscreenSettings>) => void;
  onSendText: (text: string) => Promise<unknown>;
  onSendImage: (imageBase64: string, format: string, prompt: string) => Promise<unknown>;
  onOpenCamera: (onSent: () => void) => void;
  onExit: () => void;
};

type TrayMode = 'double' | 'long' | null;

export function LiveFullscreenScreen({
  visible,
  connected,
  sessionActive,
  demoMode,
  state,
  client,
  playback,
  activity,
  meteringDb,
  meteringRevision,
  microphoneActive,
  microphoneSpeechDetected,
  settings,
  onSettingsChange,
  onSendText,
  onSendImage,
  onOpenCamera,
  onExit,
}: Props) {
  const [layout, setLayout] = React.useState({ width: 360, height: 720 });
  const [trayMode, setTrayMode] = React.useState<TrayMode>(null);
  const [visualOpen, setVisualOpen] = React.useState(false);
  const [portalVisible, setPortalVisible] = React.useState(false);
  const [portalSettled, setPortalSettled] = React.useState(false);
  const [mediaError, setMediaError] = React.useState('');
  const [transientSettings, setTransientSettings] = React.useState<
    Partial<LiveFullscreenSettings> | null
  >(null);
  const effectiveSettings = React.useMemo<LiveFullscreenSettings>(
    () => ({ ...settings, ...(transientSettings || {}) }),
    [settings, transientSettings],
  );
  const effectiveSettingsRef = React.useRef(effectiveSettings);
  effectiveSettingsRef.current = effectiveSettings;
  const transformSessionRef = React.useRef<{
    target: Exclude<FullscreenTransformTarget, null>;
    initial: TwoTouchMetrics;
    startSettings: LiveFullscreenSettings;
    lastUpdates: Partial<LiveFullscreenSettings> | null;
  } | null>(null);
  const baselineRef = React.useRef(captureVisualReplyBaseline(undefined));
  const baselineReadyRef = React.useRef(false);
  const spectrumOpacity = React.useRef(new Animated.Value(1)).current;
  const [micSpectrum, setMicSpectrum] = React.useState(createMicSpectrumHistoryState);
  const micInputRef = React.useRef({
    microphoneActive,
    meteringDb,
    meteringRevision,
  });
  micInputRef.current = {
    microphoneActive,
    meteringDb,
    meteringRevision,
  };
  const ttsPlaybackActive = Boolean(
    playback.playingId
    || (playback.isPlaying && playback.currentChunk)
    || playback.preparedChunk
  );
  const spectrumClockActive = activity !== 'idle'
    || ttsPlaybackActive
    || microphoneActive
    || micSpectrum.envelope.level > 0.001;
  const spectrum = useSpectrumPlayback(
    client,
    playback,
    settings.audioSmoothingPct,
    settings.spectrumFps,
    visible,
    spectrumClockActive,
  );
  React.useEffect(() => {
    if (!visible) {
      setMicSpectrum(createMicSpectrumHistoryState());
      return;
    }
    setMicSpectrum((previous) => advanceMicSpectrumHistoryState(previous, {
      frameTimeMs: spectrum.frameTimeMs,
      ...micInputRef.current,
    }));
  }, [spectrum.frameTimeMs, visible]);
  const visualState = state?.visual?.state;
  const visualVersion = visualState?.image_cache_key || visualState?.updated_at || '';
  const imagePath = String(visualState?.image_url_path || '');
  const authorizedVisual = useAuthorizedMediaUrl(client, imagePath, visualVersion ? { v: String(visualVersion) } : {});
  const imageUrl = authorizedVisual.url;

  React.useEffect(() => {
    if (!visible) {
      setTrayMode(null);
      setVisualOpen(false);
      setPortalVisible(false);
      setPortalSettled(false);
      setTransientSettings(null);
      transformSessionRef.current = null;
      return;
    }
    baselineRef.current = captureVisualReplyBaseline(state?.visual);
    baselineReadyRef.current = Boolean(state?.visual);
    spectrumOpacity.setValue(1);
  }, [spectrumOpacity, visible]);

  React.useEffect(() => {
    if (!visible || baselineReadyRef.current || !state?.visual) return;
    baselineRef.current = captureVisualReplyBaseline(state.visual);
    baselineReadyRef.current = true;
  }, [state?.visual, visible]);

  React.useEffect(() => {
    if (!visible || !baselineReadyRef.current || !settings.autoRevealVisualReply || visualOpen) return;
    if (isFreshVisualReply(baselineRef.current, visualState)) {
      baselineRef.current = captureVisualReplyBaseline(state?.visual);
      setVisualOpen(true);
      setPortalSettled(false);
      setPortalVisible(true);
    }
  }, [
    settings.autoRevealVisualReply,
    spectrumOpacity,
    visible,
    visualOpen,
    state?.visual,
    visualState?.image_cache_key,
    visualState?.image_url_path,
    visualState?.updated_at,
  ]);

  React.useEffect(() => {
    if (shouldExitLiveFullscreen({ visible, demoMode, sessionActive })) onExit();
  }, [demoMode, onExit, sessionActive, visible]);

  const dismissVisual = React.useCallback(() => {
    setPortalVisible(false);
    setVisualOpen(false);
    setPortalSettled(false);
    Animated.timing(spectrumOpacity, {
      duration: 220,
      toValue: 1,
      useNativeDriver: true,
    }).start();
  }, [spectrumOpacity]);
  const handlePortalReady = React.useCallback(() => {
    Animated.timing(spectrumOpacity, {
      duration: 160,
      toValue: Math.max(0, Math.min(1, settings.imageSpectrumOpacityPct / 200)),
      useNativeDriver: true,
    }).start();
  }, [settings.imageSpectrumOpacityPct, spectrumOpacity]);
  const handlePortalRevealComplete = React.useCallback(() => {
    Animated.timing(spectrumOpacity, {
      duration: 140,
      toValue: 0,
      useNativeDriver: true,
    }).start(({ finished }) => {
      if (finished) setPortalSettled(true);
    });
  }, [spectrumOpacity]);
  const handlePortalLoadError = React.useCallback((message: string) => {
    setMediaError(message);
    dismissVisual();
  }, [dismissVisual]);
  const handleSingleTap = React.useCallback(() => {
    if (portalVisible) dismissVisual();
  }, [dismissVisual, portalVisible]);
  const handleDoubleTap = React.useCallback(() => setTrayMode('double'), []);
  const handleLongPress = React.useCallback(() => setTrayMode('long'), []);
  const closeTray = React.useCallback(() => setTrayMode(null), []);
  const handleTransformStart = React.useCallback((metrics: TwoTouchMetrics) => {
    if (trayMode !== null || portalVisible) return;
    const current = effectiveSettingsRef.current;
    const baseCircleSize = Math.max(
      160,
      Math.min(layout.width * 0.9, layout.height * 0.54),
    );
    const currentCircleSize = baseCircleSize * current.circleSizePct / 100;
    const circleFrame = {
      height: currentCircleSize,
      left: (
        layout.width * current.circleHorizontalPositionPct / 100
      ) - currentCircleSize / 2,
      top: (
        layout.height * current.verticalPositionPct / 100
      ) - currentCircleSize / 2,
      width: currentCircleSize,
    };
    const target = chooseTransformTarget(
      metrics,
      circleFrame,
      current.backgroundKind !== 'none',
    );
    transformSessionRef.current = target ? {
      target,
      initial: metrics,
      startSettings: { ...current },
      lastUpdates: null,
    } : null;
    setTransientSettings(null);
  }, [layout.height, layout.width, portalVisible, trayMode]);
  const handleTransformPreview = React.useCallback((metrics: TwoTouchMetrics) => {
    const session = transformSessionRef.current;
    if (!session) return;
    const updates = session.target === 'circle'
      ? circleTransformFromGesture(
        session.startSettings,
        session.initial,
        metrics,
        layout,
      )
      : backgroundTransformFromGesture(
        session.startSettings,
        session.initial,
        metrics,
        layout,
      );
    session.lastUpdates = updates;
    setTransientSettings(updates);
  }, [layout]);
  const handleTransformCommit = React.useCallback(() => {
    const session = transformSessionRef.current;
    transformSessionRef.current = null;
    if (session?.lastUpdates) {
      onSettingsChange(session.lastUpdates);
    }
    setTransientSettings(null);
  }, [onSettingsChange]);

  const directionalSeconds = directionalSpectrumSeconds(
    Date.now() / 1000,
    effectiveSettings.rotationSpeedPct,
  );
  const outputEnergies = activity === 'thinking'
    ? proceduralSpectrum(directionalSeconds, 0.28)
    : spectrum.energies;
  const { outerEnergies, innerEnergies } = composeLiveFullscreenEnergies({
    ttsEnergies: outputEnergies,
    ttsPlaybackActive: ttsPlaybackActive || activity === 'thinking',
    microphoneEnergies: micSpectrum.energies,
    barCount: SPECTRUM_BARS,
  });
  const baseCircleSize = Math.max(160, Math.min(layout.width * 0.9, layout.height * 0.54));
  const circleSize = baseCircleSize * effectiveSettings.circleSizePct / 100;
  const circleLeft = (
    layout.width * effectiveSettings.circleHorizontalPositionPct / 100
  ) - circleSize / 2;
  const circleTop = (
    layout.height * effectiveSettings.verticalPositionPct / 100
  ) - circleSize / 2;

  return (
    <Modal visible={visible} animationType="fade" presentationStyle="fullScreen" statusBarTranslucent onRequestClose={onExit}>
      <SafeAreaView
        style={styles.screen}
        onLayout={(event) => {
          const { width, height } = event.nativeEvent.layout;
          if (width && height) setLayout({ width, height });
        }}
      >
        <StatusBar hidden />
        <LiveFullscreenBackground
          settings={effectiveSettings}
          visible={visible}
          visualReplyOpen={portalVisible}
          onError={setMediaError}
        />
        <Animated.View
          pointerEvents="none"
          style={[
            styles.circleFrame,
            {
              height: circleSize,
              left: circleLeft,
              opacity: spectrumOpacity,
              top: circleTop,
              width: circleSize,
            },
          ]}
        >
          {!portalSettled ? (
            <CircularSpectrum
              activity={activity}
              outerEnergies={outerEnergies}
              innerEnergies={innerEnergies}
              palette={effectiveSettings.palette}
              circleSizePct={100}
              waveformDepthPct={effectiveSettings.waveformDepthPct}
              glowStrengthPct={effectiveSettings.glowStrengthPct}
              motionIntensityPct={effectiveSettings.motionIntensityPct}
              rotationSpeedPct={effectiveSettings.rotationSpeedPct}
              barCount={effectiveSettings.spectrumBarCount}
              frameTimeMs={spectrum.frameTimeMs}
            />
          ) : null}
        </Animated.View>
        <View style={styles.liveIndicator}>
          <View style={[styles.liveDot, !connected && !demoMode && styles.disconnectedDot]} />
          <Text style={styles.liveText}>{demoMode ? 'DEMO' : connected ? 'LIVE' : 'OFFLINE'}</Text>
        </View>
        {mediaError ? <Text style={styles.errorBanner}>{mediaError}</Text> : null}
        <VisualReplyPortal
          imageUrl={imageUrl}
          visible={portalVisible}
          portalSpeedPct={settings.portalSpeedPct}
          edgeSoftnessPct={settings.edgeSoftnessPct}
          onDismiss={dismissVisual}
          onReady={handlePortalReady}
          onRevealComplete={handlePortalRevealComplete}
          onLoadError={handlePortalLoadError}
        />
        {playback.activePlayer ? (
          <AudioSampleTap player={playback.activePlayer} onSample={playback.setLiveSample} />
        ) : null}
        <LiveFullscreenGestureLayer
          longPressSeconds={settings.longPressSeconds}
          vibrationEnabled={settings.vibrationEnabled}
          plongEnabled={settings.plongEnabled}
          transformEnabled={trayMode === null && !portalVisible}
          onSingleTap={handleSingleTap}
          onDoubleTap={handleDoubleTap}
          onLongPress={handleLongPress}
          onTransformStart={handleTransformStart}
          onTransformPreview={handleTransformPreview}
          onTransformCommit={handleTransformCommit}
        />
        <LiveFullscreenActionTray
          visible={trayMode !== null}
          includeExit={trayMode === 'long'}
          disabled={!connected && !demoMode}
          onSendText={onSendText}
          onSendImage={onSendImage}
          onOpenCamera={onOpenCamera}
          onClose={closeTray}
          onExit={onExit}
        />
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  screen: { backgroundColor: '#000000', flex: 1, overflow: 'hidden' },
  circleFrame: { position: 'absolute' },
  liveIndicator: {
    alignItems: 'center',
    backgroundColor: 'rgba(0,0,0,0.55)',
    borderRadius: 10,
    flexDirection: 'row',
    gap: 6,
    left: 12,
    paddingHorizontal: 9,
    paddingVertical: 5,
    position: 'absolute',
    top: 10,
  },
  liveDot: { backgroundColor: '#00ff66', borderRadius: 4, height: 8, width: 8 },
  disconnectedDot: { backgroundColor: '#ff1744' },
  liveText: { color: '#ffffff', fontSize: 10, fontWeight: '900', letterSpacing: 1.1 },
  errorBanner: {
    backgroundColor: 'rgba(120,0,24,0.78)',
    bottom: 14,
    color: '#ffffff',
    fontSize: 12,
    left: 14,
    padding: 8,
    position: 'absolute',
    right: 14,
    textAlign: 'center',
  },
});
