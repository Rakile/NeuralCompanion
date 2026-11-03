import React from 'react';
import {
  Animated,
  Modal,
  Platform,
  Pressable,
  StatusBar,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { usePresentationStyle, useThemeColors } from '../../styles/ThemeContext';

import type { RemoteClient } from '../../api/client';
import type { PresenceActivity, RemoteState } from '../../api/types';
import type { PlaybackState } from '../../hooks/useAudioQueue';
import type { VoiceThreadFrame } from '../../hooks/usePresenceSpectrum';
import { useAuthorizedMediaUrl } from '../../hooks/useAuthorizedMediaUrl';
import { useSpectrumPlayback } from '../../hooks/useSpectrumPlayback';
import { useReducedMotion } from '../../hooks/useReducedMotion';
import {
  captureVisualReplyBaseline,
  isFreshVisualReply,
} from '../../utils/liveFullscreenVisual';
import { shouldExitLiveFullscreen } from '../../utils/liveFullscreenSession';
import type { LiveFullscreenSettings } from '../../utils/liveFullscreenSettings';
import {
  advanceMicSpectrumHistoryState,
  createMicSpectrumHistoryState,
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
import { LivingVoiceThread } from '../presence/LivingVoiceThread';
import { LiveFullscreenActionTray } from './LiveFullscreenActionTray';
import type {ChatPhotoDraft} from '../../hooks/useChatPhotoDraft';
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
  photoDraft?: ChatPhotoDraft;
  onExit: () => void;
  liveControls?: React.ReactNode;
  canStopSpeech?: boolean;
  onStopSpeech?: () => void;
};

type TrayMode = 'double' | null;
type SpectrumActivity = 'idle' | 'listening' | 'thinking' | 'speaking';
const SILENT_THREAD_ENERGIES = Array(SPECTRUM_BARS).fill(0);

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
  photoDraft,
  onExit,
  liveControls,
  canStopSpeech,
  onStopSpeech,
}: Props) {
  const safeAreaInsets = useSafeAreaInsets();
  const colors = useThemeColors();
  const editorial = usePresentationStyle() === 'editorial';
  const reducedMotion = useReducedMotion();
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
  const voiceSilkOpacity = React.useRef(new Animated.Value(1)).current;
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
    visible && !reducedMotion,
    spectrumClockActive && !reducedMotion,
  );
  React.useEffect(() => {
    if (!visible || reducedMotion) {
      setMicSpectrum(createMicSpectrumHistoryState());
      return;
    }
    setMicSpectrum((previous) => advanceMicSpectrumHistoryState(previous, {
      frameTimeMs: spectrum.frameTimeMs,
      ...micInputRef.current,
    }));
  }, [reducedMotion, spectrum.frameTimeMs, visible]);
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
    voiceSilkOpacity.setValue(1);
  }, [voiceSilkOpacity, visible]);

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
    voiceSilkOpacity,
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
    Animated.timing(voiceSilkOpacity, {
      duration: 220,
      toValue: 1,
      useNativeDriver: true,
    }).start();
  }, [voiceSilkOpacity]);
  const handlePortalReady = React.useCallback(() => {
    Animated.timing(voiceSilkOpacity, {
      duration: 160,
      toValue: Math.max(0, Math.min(1, settings.imageSpectrumOpacityPct / 200)),
      useNativeDriver: true,
    }).start();
  }, [settings.imageSpectrumOpacityPct, voiceSilkOpacity]);
  const handlePortalRevealComplete = React.useCallback(() => {
    Animated.timing(voiceSilkOpacity, {
      duration: 140,
      toValue: 0,
      useNativeDriver: true,
    }).start(({ finished }) => {
      if (finished) setPortalSettled(true);
    });
  }, [voiceSilkOpacity]);
  const handlePortalLoadError = React.useCallback((message: string) => {
    setMediaError(message);
    dismissVisual();
  }, [dismissVisual]);
  const handleSingleTap = React.useCallback(() => {
    if (portalVisible) dismissVisual();
  }, [dismissVisual, portalVisible]);
  const handleDoubleTap = React.useCallback(() => setTrayMode('double'), []);
  const closeTray = React.useCallback(() => setTrayMode(null), []);
  const handleTransformStart = React.useCallback((metrics: TwoTouchMetrics) => {
    if (trayMode !== null || portalVisible) return;
    const current = effectiveSettingsRef.current;
    const currentScale = current.circleSizePct / 100;
    const currentSilkWidth = Math.max(180, layout.width * 0.9) * currentScale;
    const currentSilkHeight = Math.max(72, Math.min(layout.height * 0.3, 260) * currentScale);
    const silkFrame = {
      height: currentSilkHeight,
      left: (
        layout.width * current.circleHorizontalPositionPct / 100
      ) - currentSilkWidth / 2,
      top: (
        layout.height * current.verticalPositionPct / 100
      ) - currentSilkHeight / 2,
      width: currentSilkWidth,
    };
    const target = chooseTransformTarget(
      metrics,
      silkFrame,
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

  const voiceThreadActivity: PresenceActivity = activity === 'idle'
    ? state?.presence?.activity || 'ready'
    : activity;
  const presenceMood = state?.presence?.mood || 'neutral';
  const thinkingEnergies = activity === 'thinking'
    ? proceduralSpectrum(spectrum.frameTimeMs / 1000, 0.28)
    : SILENT_THREAD_ENERGIES;
  const voiceThreadFrame = React.useMemo<VoiceThreadFrame>(() => {
    if (voiceThreadActivity === 'listening') {
      return {
        energies: micSpectrum.energies,
        inputLevel: micSpectrum.envelope.level,
        frameTimeMs: spectrum.frameTimeMs,
        source: 'live',
      };
    }
    if (voiceThreadActivity === 'thinking') {
      return { energies: thinkingEnergies, inputLevel: 0, frameTimeMs: spectrum.frameTimeMs, source: 'procedural' };
    }
    if (voiceThreadActivity === 'speaking' || ttsPlaybackActive) {
      return {
        energies: spectrum.energies,
        inputLevel: 0,
        frameTimeMs: spectrum.frameTimeMs,
        source: spectrum.source === 'idle' ? 'procedural' : spectrum.source,
      };
    }
    return { energies: SILENT_THREAD_ENERGIES, inputLevel: 0, frameTimeMs: spectrum.frameTimeMs, source: 'procedural' };
  }, [micSpectrum, spectrum.energies, spectrum.frameTimeMs, spectrum.source, thinkingEnergies, ttsPlaybackActive, voiceThreadActivity]);
  const silkScale = effectiveSettings.circleSizePct / 100;
  const silkWidth = Math.max(180, layout.width * 0.9) * silkScale;
  const silkHeight = Math.max(72, Math.min(layout.height * 0.3, 260) * silkScale);
  const silkLeft = (
    layout.width * effectiveSettings.circleHorizontalPositionPct / 100
  ) - silkWidth / 2;
  const silkTop = (
    layout.height * effectiveSettings.verticalPositionPct / 100
  ) - silkHeight / 2;

  return (
    <Modal visible={visible} animationType="fade" presentationStyle="fullScreen" statusBarTranslucent onRequestClose={onExit}>
      <View
        style={[styles.screen, editorial && { backgroundColor: colors.background }]}
        onLayout={(event) => {
          const { width, height } = event.nativeEvent.layout;
          if (width && height) setLayout({ width, height });
        }}
      >
        <StatusBar hidden />
        <LiveFullscreenBackground
          settings={effectiveSettings}
          visible={visible && !reducedMotion}
          visualReplyOpen={portalVisible}
          onError={setMediaError}
        />
        <Animated.View
          pointerEvents="none"
          style={[
            styles.voiceSilkFrame,
            {
              height: silkHeight,
              left: silkLeft,
              opacity: voiceSilkOpacity,
              top: silkTop,
              width: silkWidth,
            },
          ]}
        >
          {!portalSettled ? (
            <LivingVoiceThread
              activity={voiceThreadActivity}
              mood={presenceMood}
              frame={voiceThreadFrame}
              fullscreen
              heightOverride={silkHeight}
              paletteMode={effectiveSettings.palette}
              waveformDepthPct={effectiveSettings.waveformDepthPct}
              glowStrengthPct={effectiveSettings.glowStrengthPct}
              motionIntensityPct={effectiveSettings.motionIntensityPct}
              reduceMotion={reducedMotion}
              lowPower={effectiveSettings.spectrumFps <= 18}
            />
          ) : null}
        </Animated.View>
        <View style={[styles.liveIndicator, editorial && styles.editorialIndicator, { top: safeAreaInsets.top + 10 }]}>
          <View style={[styles.liveDot, editorial && { backgroundColor: colors.ok },
            !connected && !demoMode && styles.disconnectedDot]} />
          <Text style={[styles.liveText, editorial && { color: colors.textSecondary }]}>{demoMode ? 'DEMO' : connected ? 'LIVE' : 'OFFLINE'}</Text>
        </View>
        {mediaError ? <Text style={[styles.errorBanner, editorial && { color: colors.danger,
          backgroundColor: colors.panel }, { bottom: safeAreaInsets.bottom + 14 }]}>{mediaError}</Text> : null}
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
        <LiveFullscreenGestureLayer
          longPressSeconds={settings.longPressSeconds}
          longPressEnabled={false}
          vibrationEnabled={settings.vibrationEnabled}
          plongEnabled={settings.plongEnabled}
          transformEnabled={trayMode === null && !portalVisible}
          onSingleTap={handleSingleTap}
          onDoubleTap={handleDoubleTap}
          onLongPress={() => undefined}
          onTransformStart={handleTransformStart}
          onTransformPreview={handleTransformPreview}
          onTransformCommit={handleTransformCommit}
        />
        <LiveFullscreenActionTray
          liveControls={liveControls}
          canStopSpeech={canStopSpeech}
          onStopSpeech={onStopSpeech}
          visible={trayMode !== null}
          includeExit
          dismissOnBackdrop
          disabled={!connected && !demoMode}
          onSendText={onSendText}
            photoDraft={photoDraft}
          onClose={closeTray}
          onExit={onExit}
        />
        {Platform.OS === 'ios' ? (
          <Pressable
            accessibilityLabel="Exit fullscreen"
            accessibilityRole="button"
            onPress={onExit}
            style={[styles.exitButton, { top: safeAreaInsets.top + 6, right: safeAreaInsets.right + 8 }]}
          >
            <Text style={styles.exitText}>×</Text>
          </Pressable>
        ) : null}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  screen: { backgroundColor: '#000000', flex: 1, overflow: 'hidden' },
  voiceSilkFrame: { justifyContent: 'center', position: 'absolute' },
  exitButton: {
    alignItems: 'center',
    backgroundColor: 'rgba(0,0,0,0.55)',
    borderRadius: 22,
    justifyContent: 'center',
    minHeight: 44,
    minWidth: 44,
    position: 'absolute',
    zIndex: 10,
  },
  exitText: { color: '#ffffff', fontSize: 26, lineHeight: 30 },
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
  editorialIndicator: { backgroundColor:'transparent', borderRadius:0 },
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
