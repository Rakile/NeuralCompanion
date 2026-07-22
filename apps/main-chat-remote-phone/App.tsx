import React from 'react';
import { KeyboardAvoidingView, LayoutAnimation, PanResponder, Platform, Pressable, SafeAreaView, ScrollView, StatusBar, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { activateKeepAwakeAsync, deactivateKeepAwake } from 'expo-keep-awake';

import { ChatFeed } from './src/components/ChatFeed';
import { InterfaceModeProvider, useInterfaceMode } from './src/context/InterfaceModeContext';
import { ChatPhotoCapture } from './src/components/ChatPhotoCapture';
import { Composer } from './src/components/Composer';
import { ConnectionPanel } from './src/components/ConnectionPanel';
import { ControlsBar } from './src/components/ControlsBar';
import { MediaPanel } from './src/components/MediaPanel';
import { MprcPanel } from './src/components/MprcPanel';
import { MuseTalkPanel } from './src/components/MuseTalkPanel';
import { PairingQrScanner } from './src/components/PairingQrScanner';
import { RuntimeBar } from './src/components/RuntimeBar';
import { SettingsPanel } from './src/components/SettingsPanel';
import { VisualPanel } from './src/components/VisualPanel';
import { useDemoRemote } from './src/demo/useDemoRemote';
import type { RemoteConnectionStatus, RemoteState, RemoteTransport } from './src/api/types';
import { useAudioQueue } from './src/hooks/useAudioQueue';
import { usePhoneSettings } from './src/hooks/usePhoneSettings';
import { useImmersiveChrome } from './src/hooks/useImmersiveChrome';
import { useRecorder } from './src/hooks/useRecorder';
import { useRemoteConnection } from './src/hooks/useRemoteConnection';
import { colors, spacing } from './src/styles/theme';
import { topControlsSwipeAction } from './src/utils/swipeControls';
import { shouldForceChromeVisible } from './src/utils/interfaceMode';

type MainTab = 'chat' | 'story' | 'visual' | 'audio' | 'more';
type IconName = 'chat' | 'story' | 'visual' | 'audio' | 'more' | 'runtime' | 'pause' | 'mic';
type MoreMode = 'avatar' | 'settings';

const mainTabs: Array<{ id: MainTab; label: string; icon: IconName }> = [
  { id: 'chat', label: 'Chat', icon: 'chat' },
  { id: 'story', label: 'Story', icon: 'story' },
  { id: 'visual', label: 'Visual', icon: 'visual' },
  { id: 'audio', label: 'Audio', icon: 'audio' },
  { id: 'more', label: 'More', icon: 'more' },
];

function textOr(value: unknown, fallback: string): string {
  const text = String(value ?? '').trim();
  return text || fallback;
}

function tabBadge(tab: MainTab, state: RemoteState | null, sessionActive: boolean, demoMode: boolean): string {
  if (demoMode) {
    return 'Demo';
  }
  if (!sessionActive) {
    return 'Offline';
  }
  if (tab === 'visual') {
    return state?.visual?.service_available === false ? 'Off' : state?.visual?.latest_request?.status ? String(state.visual.latest_request.status) : 'Ready';
  }
  if (tab === 'audio') {
    if (state?.media?.backend_playback_suppressed) {
      return 'Muted';
    }
    return state?.media?.items?.length ? `${state.media.items.length}` : 'Ready';
  }
  if (tab === 'story') {
    return state?.mprc?.available ? `Turn ${Number(state.mprc.session?.turn_index ?? 0)}` : 'Off';
  }
  if (tab === 'more') {
    if (state?.musetalk?.available !== false && state?.musetalk?.state?.status) {
      return 'Avatar';
    }
    return state?.buddy_chat?.enabled ? 'Buddy' : 'Ready';
  }
  return state?.runtime_status?.running || state?.engine?.running ? 'Ready' : 'Idle';
}

function IconGlyph({ name, active = false }: { name: IconName; active?: boolean }) {
  return (
    <View style={[styles.iconBox, active && styles.iconBoxActive]}>
      {name === 'chat' ? (
        <>
          <View style={[styles.iconChatLine, styles.iconChatLineLong]} />
          <View style={styles.iconChatLine} />
          <View style={styles.iconChatTail} />
        </>
      ) : null}
      {name === 'story' ? (
        <>
          <View style={styles.iconBookLeft} />
          <View style={styles.iconBookRight} />
          <View style={styles.iconBookSpine} />
        </>
      ) : null}
      {name === 'visual' ? (
        <>
          <View style={styles.iconImageSun} />
          <View style={styles.iconImageMountain} />
        </>
      ) : null}
      {name === 'audio' ? (
        <View style={styles.iconBars}>
          <View style={[styles.iconBar, styles.iconBarShort]} />
          <View style={[styles.iconBar, styles.iconBarTall]} />
          <View style={styles.iconBar} />
        </View>
      ) : null}
      {name === 'more' ? (
        <View style={styles.iconGrid}>
          <View style={styles.iconDot} />
          <View style={styles.iconDot} />
          <View style={styles.iconDot} />
          <View style={styles.iconDot} />
        </View>
      ) : null}
      {name === 'runtime' ? <View style={styles.iconPlay} /> : null}
      {name === 'pause' ? (
        <View style={styles.iconPause}>
          <View style={styles.iconPauseBar} />
          <View style={styles.iconPauseBar} />
        </View>
      ) : null}
      {name === 'mic' ? (
        <>
          <View style={styles.iconMicHead} />
          <View style={styles.iconMicStem} />
          <View style={styles.iconMicBase} />
        </>
      ) : null}
    </View>
  );
}

function SignalTile({ label, value, tone = 'neutral' }: { label: string; value: string; tone?: 'neutral' | 'ok' | 'warn' }) {
  return (
    <View style={styles.signalTile}>
      <Text style={styles.signalLabel}>{label}</Text>
      <Text
        style={[
          styles.signalValue,
          tone === 'ok' && styles.signalValueOk,
          tone === 'warn' && styles.signalValueWarn,
        ]}
        numberOfLines={1}
      >
        {value}
      </Text>
    </View>
  );
}

function RemoteCockpit({
  state,
  baseUrl,
  demoMode,
  sessionActive,
  status,
  transport,
}: {
  state: RemoteState | null;
  baseUrl: string;
  demoMode: boolean;
  sessionActive: boolean;
  status: RemoteConnectionStatus;
  transport: RemoteTransport;
}) {
  const runtime = state?.runtime_status;
  const running = Boolean(state?.engine?.running ?? runtime?.running);
  const ttsBackend = textOr(state?.runtime_settings?.tts_backend || runtime?.tts_backend, 'TTS');
  const storyTurn = state?.mprc?.available ? `Turn ${Number(state.mprc.session?.turn_index ?? 0)}` : 'Off';
  const subtitle = demoMode ? 'Offline phone app tour' : sessionActive ? `${textOr(baseUrl, 'LAN backend')} - ${transport === 'none' ? status : transport}` : 'Not connected';
  const pill = demoMode ? 'DEMO' : sessionActive ? 'LIVE' : 'OFFLINE';
  return (
    <View style={styles.cockpit}>
      <View style={styles.cockpitHeader}>
        <View style={styles.brandBlock}>
          <View style={styles.brandMark}>
            <View style={styles.brandCrossVertical} />
            <View style={styles.brandCrossHorizontal} />
          </View>
          <View style={styles.brandTextBlock}>
            <Text style={styles.brandTitle}>NC Remote</Text>
            <Text style={styles.brandSubtitle} numberOfLines={1}>{subtitle}</Text>
          </View>
        </View>
        <Text style={[styles.statePill, sessionActive && styles.statePillLive]}>{pill}</Text>
      </View>
      <View style={styles.signalRow}>
        <SignalTile label="Engine" value={running ? 'Running' : 'Stopped'} tone={running ? 'ok' : 'warn'} />
        <SignalTile label="TTS" value={state?.media?.backend_playback_suppressed ? 'Phone' : ttsBackend} tone={state?.media?.items?.length ? 'ok' : 'neutral'} />
        <SignalTile label="Story" value={storyTurn} tone={state?.mprc?.available ? 'ok' : 'neutral'} />
      </View>
    </View>
  );
}

function QuickActions({
  running,
  disabled,
  visualDisabled,
  voiceAvailable,
  recording,
  onStart,
  onStop,
  onPause,
  onTalk,
  onVisual,
}: {
  running: boolean;
  disabled: boolean;
  visualDisabled: boolean;
  voiceAvailable: boolean;
  recording: boolean;
  onStart: () => Promise<void>;
  onStop: () => Promise<void>;
  onPause: () => Promise<void>;
  onTalk: () => void;
  onVisual: () => void;
}) {
  const runtimeDisabled = disabled;
  const pauseDisabled = disabled;
  const talkDisabled = !voiceAvailable;
  return (
    <View style={styles.quickActions}>
      <Pressable
        disabled={runtimeDisabled}
        style={[styles.actionButton, runtimeDisabled && styles.disabled]}
        onPress={() => (running ? onStop() : onStart()).catch(() => undefined)}
      >
        <IconGlyph name="runtime" />
        <Text style={styles.actionText}>{running ? 'Stop' : 'Start'}</Text>
      </Pressable>
      <Pressable
        disabled={pauseDisabled}
        style={[styles.actionButton, pauseDisabled && styles.disabled]}
        onPress={() => onPause().catch(() => undefined)}
      >
        <IconGlyph name="pause" />
        <Text style={styles.actionText}>Pause</Text>
      </Pressable>
      <Pressable
        disabled={talkDisabled}
        style={[styles.actionButton, recording && styles.actionButtonActive, talkDisabled && styles.disabled]}
        onPress={onTalk}
      >
        <IconGlyph name="mic" />
        <Text style={styles.actionText}>{recording ? 'Stop Mic' : 'Talk'}</Text>
      </Pressable>
      <Pressable
        disabled={visualDisabled}
        style={[styles.actionButton, visualDisabled && styles.disabled]}
        onPress={onVisual}
      >
        <IconGlyph name="visual" />
        <Text style={styles.actionText}>Visual</Text>
      </Pressable>
    </View>
  );
}

function DesktopControlsDrawer({
  state,
  disabled,
  demoMode,
  onStart,
  onStop,
  onControl,
}: {
  state: RemoteState | null;
  disabled: boolean;
  demoMode: boolean;
  onStart: () => Promise<void>;
  onStop: () => Promise<void>;
  onControl: (action: string) => Promise<void>;
}) {
  const { mode, policy } = useInterfaceMode();
  const modeAwareControls = mode !== 'classic';
  const [open, setOpen] = React.useState(mode === 'flat');
  const runtime = state?.runtime_status;
  const running = Boolean(state?.engine?.running ?? runtime?.running);
  const actionCount = state?.controls?.actions?.length ?? 0;
  React.useEffect(() => {
    setOpen(mode === 'flat');
  }, [mode]);
  return (
    <View style={[styles.controlsDrawer, modeAwareControls && styles.controlsDrawerClean, mode === 'immersive' && styles.controlsDrawerImmersive]}>
      <Pressable style={styles.controlsDrawerHeader} onPress={() => setOpen((value) => !value)}>
        <View style={styles.controlsDrawerText}>
          <Text style={styles.controlsDrawerTitle}>Desktop Controls</Text>
          <Text style={styles.controlsDrawerMeta} numberOfLines={1}>
            {demoMode ? 'Demo desktop state' : running ? 'Runtime running' : 'Runtime stopped'} - {runtime?.chat_provider || 'LLM'} - {actionCount} actions
          </Text>
        </View>
        <Text style={styles.controlsDrawerToggle}>{open ? 'Hide' : 'Show'}</Text>
      </Pressable>
      {open || (modeAwareControls && !policy.primaryFirst) ? (
        <View style={styles.controlsDrawerBody}>
          <RuntimeBar state={state} disabled={disabled} onStart={onStart} onStop={onStop} />
          <ControlsBar actions={state?.controls?.actions ?? []} disabled={disabled} onControl={onControl} />
        </View>
      ) : null}
    </View>
  );
}

function BottomNavigation({
  activeTab,
  state,
  sessionActive,
  demoMode,
  onChange,
}: {
  activeTab: MainTab;
  state: RemoteState | null;
  sessionActive: boolean;
  demoMode: boolean;
  onChange: (tab: MainTab) => void;
}) {
  const { mode, policy } = useInterfaceMode();
  return (
    <View style={[styles.bottomNav, !policy.cards && styles.bottomNavClean, mode === 'immersive' && styles.bottomNavImmersive]}>
      {mainTabs.map((tab) => {
        const selected = activeTab === tab.id;
        return (
          <Pressable
            key={tab.id}
            style={[styles.navButton, selected && styles.navButtonActive]}
            onPress={() => onChange(tab.id)}
          >
            <IconGlyph name={tab.icon} active={selected} />
            <Text style={[styles.navLabel, selected && styles.navLabelActive]} numberOfLines={1}>{tab.label}</Text>
            <Text style={[styles.navBadge, selected && styles.navBadgeActive]} numberOfLines={1}>{tabBadge(tab.id, state, sessionActive, demoMode)}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function MorePanel({
  mode,
  onModeChange,
  state,
  remote,
  demo,
  demoMode,
  commandsAvailable,
  sessionActive,
  musetalkAvailable,
  settings,
  setSettings,
}: {
  mode: MoreMode;
  onModeChange: (mode: MoreMode) => void;
  state: RemoteState | null;
  remote: ReturnType<typeof useRemoteConnection>;
  demo: ReturnType<typeof useDemoRemote>;
  demoMode: boolean;
  commandsAvailable: boolean;
  sessionActive: boolean;
  musetalkAvailable: boolean;
  settings: ReturnType<typeof usePhoneSettings>['settings'];
  setSettings: ReturnType<typeof usePhoneSettings>['setSettings'];
}) {
  const { mode: interfaceMode, policy } = useInterfaceMode();
  const sendOptions = React.useMemo(() => ({
    playOnBackend: settings.playOnBackend,
    capturePhoneAudio: settings.sendMode !== 'text_only',
    visualAfterSend: settings.sendMode === 'visual_reply',
  }), [settings.playOnBackend, settings.sendMode]);
  return (
    <View style={styles.morePanel}>
      <View style={[styles.moreTabs, !policy.cards && styles.moreTabsClean, interfaceMode === 'immersive' && styles.moreTabsImmersive]}>
        <Pressable
          style={[styles.moreTabButton, mode === 'avatar' && styles.moreTabButtonActive]}
          onPress={() => onModeChange('avatar')}
        >
          <Text style={[styles.moreTabText, mode === 'avatar' && styles.moreTabTextActive]}>Avatar</Text>
        </Pressable>
        <Pressable
          style={[styles.moreTabButton, mode === 'settings' && styles.moreTabButtonActive]}
          onPress={() => onModeChange('settings')}
        >
          <Text style={[styles.moreTabText, mode === 'settings' && styles.moreTabTextActive]}>Appearance & Settings</Text>
        </Pressable>
      </View>
      {mode === 'avatar' ? (
        <ScrollView style={styles.tabPanel} contentContainerStyle={styles.stackedContent}>
          <MuseTalkPanel
            client={remote.client}
            musetalk={state?.musetalk}
            disabled={!sessionActive}
            available={musetalkAvailable}
            quality={settings.museTalkQuality}
            demoMode={demoMode}
          />
          <DesktopControlsDrawer
            state={state}
            disabled={!commandsAvailable}
            demoMode={demoMode}
            onStart={demoMode ? demo.startEngine : remote.startEngine}
            onStop={demoMode ? demo.stopEngine : remote.stopEngine}
            onControl={(action) => demoMode ? demo.sendControl(action, sendOptions) : remote.sendControl(action, sendOptions)}
          />
        </ScrollView>
      ) : (
        <SettingsPanel
          settings={settings}
          onChange={setSettings}
          state={state}
          health={remote.health}
          status={remote.status}
          transport={remote.transport}
          error={remote.error}
          onSendDebug={() => remote.client.uploadDebug('manual')}
        />
      )}
    </View>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = React.useState<MainTab>('chat');
  const [moreMode, setMoreMode] = React.useState<MoreMode>('settings');
  const [demoMode, setDemoMode] = React.useState(false);
  const [pairingScannerVisible, setPairingScannerVisible] = React.useState(false);
  const [chatPhotoVisible, setChatPhotoVisible] = React.useState(false);
  const [topControlsCollapsed, setTopControlsCollapsed] = React.useState(false);
  const { height: screenHeight } = useWindowDimensions();
  const { settings, setSettings } = usePhoneSettings();
  const remote = useRemoteConnection({
    autoReconnect: settings.autoReconnect,
    pollingIntervalMs: settings.pollingIntervalMs,
  });
  const demo = useDemoRemote(demoMode);
  const sessionActive = demoMode || remote.connected || remote.transport !== 'none';
  const activeState = demoMode ? demo.state : sessionActive ? remote.state : null;
  const commandsAvailable = demoMode || remote.connected;
  const runtime = activeState?.runtime_status;
  const runtimeRunning = Boolean(activeState?.engine?.running ?? runtime?.running);
  const phoneSttAvailable = activeState?.features?.phone_stt !== false;
  const visualControlsAvailable = activeState?.features?.visual_reply_controls !== false && activeState?.visual?.service_available !== false;
  const musetalkAvailable = activeState?.musetalk?.available !== false
    && (activeState?.features?.musetalk_frame_feed !== false || activeState?.features?.musetalk_frame_stream !== false);
  const sendOptions = React.useMemo(() => ({
    playOnBackend: settings.playOnBackend,
    capturePhoneAudio: settings.sendMode !== 'text_only',
    visualAfterSend: settings.sendMode === 'visual_reply',
  }), [settings.playOnBackend, settings.sendMode]);
  const recorder = useRecorder(remote.client, remote.connected && !demoMode, phoneSttAvailable && !demoMode, {
    sendToChat: settings.micBehavior === 'send_auto',
    sendOptions,
  });
  const audioQueue = useAudioQueue(remote.client, !demoMode && remote.connected ? activeState?.media?.items ?? [] : [], {
    autoplayEnabled: settings.phoneTtsAutoplay,
    volume: settings.phoneTtsVolume,
    onAutoplayEnabledChange: (phoneTtsAutoplay) => setSettings({ phoneTtsAutoplay }),
  });
  const runtimeActivity = React.useMemo(() => {
    const microphone = String(runtime?.microphone_state || '').toLowerCase();
    const status = String(activeState?.status_line || '').toLowerCase();
    if (microphone.includes('listen') || microphone.includes('record')) return 'listening' as const;
    if (audioQueue.playingId || status.includes('speak') || status.includes('tts')) return 'speaking' as const;
    if (status.includes('think') || status.includes('generat') || status.includes('infer')) return 'thinking' as const;
    return 'idle' as const;
  }, [activeState?.status_line, audioQueue.playingId, runtime?.microphone_state]);
  const immersiveChrome = useImmersiveChrome({
    mode: settings.interfaceStyle,
    forceVisible: shouldForceChromeVisible({
      disconnected: !sessionActive || Boolean(remote.error),
      authorizationError: /unauthor|pairing|forbidden/i.test(remote.error),
      recording: recorder.recording,
      sttBusy: recorder.busy,
      playing: Boolean(audioQueue.playingId),
      playbackError: Boolean(audioQueue.error),
      visualError: ['error', 'rejected'].includes(String(activeState?.visual?.latest_request?.status || '').toLowerCase()),
      buddyProviderError: Boolean(activeState?.buddy_chat?.last_provider_error),
      castError: Boolean(activeState?.mprc?.cast?.dependency_error),
    }),
  });
  const topChromeCollapsed = topControlsCollapsed || !immersiveChrome.chromeVisible;

  const setTopControlsVisible = React.useCallback((visible: boolean) => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setTopControlsCollapsed(!visible);
  }, []);
  const topControlsPanResponder = React.useMemo(() => PanResponder.create({
    onMoveShouldSetPanResponderCapture: (_event, gesture) => topControlsSwipeAction({
      dx: gesture.dx,
      dy: gesture.dy,
      y0: gesture.y0,
      screenHeight,
      collapsed: topChromeCollapsed,
    }) !== 'none',
    onPanResponderRelease: (_event, gesture) => {
      const action = topControlsSwipeAction({
        dx: gesture.dx,
        dy: gesture.dy,
        y0: gesture.y0,
        screenHeight,
        collapsed: topChromeCollapsed,
      });
      if (action === 'collapse') {
        setTopControlsVisible(false);
      } else if (action === 'expand') {
        immersiveChrome.revealChrome();
        setTopControlsVisible(true);
      }
    },
  }), [immersiveChrome, screenHeight, setTopControlsVisible, topChromeCollapsed]);

  React.useEffect(() => {
    const tag = 'nc-main-chat-remote';
    if (remote.connected && settings.keepAwake) {
      activateKeepAwakeAsync(tag).catch(() => undefined);
      return () => {
        deactivateKeepAwake(tag).catch(() => undefined);
      };
    }
    deactivateKeepAwake(tag).catch(() => undefined);
    return undefined;
  }, [remote.connected, settings.keepAwake]);

  return (
    <InterfaceModeProvider mode={settings.interfaceStyle}>
    <SafeAreaView style={[styles.screen, settings.interfaceStyle === 'immersive' && styles.screenImmersive]}>
      <StatusBar barStyle="light-content" />
      <KeyboardAvoidingView style={styles.keyboard} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={[styles.appShell, settings.interfaceStyle === 'immersive' && styles.appShellImmersive]} {...topControlsPanResponder.panHandlers} onTouchStart={immersiveChrome.revealChrome}>
          {immersiveChrome.chromeVisible ? (
          <Pressable
            style={styles.topControlsHandle}
            onPress={() => setTopControlsVisible(topControlsCollapsed)}
            accessibilityRole="button"
            accessibilityLabel={topControlsCollapsed ? 'Show connection controls' : 'Hide connection controls'}
          >
            <View style={[styles.topControlsHandleBar, topControlsCollapsed && styles.topControlsHandleBarActive]} />
          </Pressable>
          ) : null}
          {immersiveChrome.chromeVisible && !topControlsCollapsed ? <>
            <ConnectionPanel
              baseUrl={remote.baseUrl}
              pairingCode={remote.pairingCode}
              connected={remote.connected}
              status={remote.status}
              transport={remote.transport}
              error={remote.error}
              demoMode={demoMode}
              onBaseUrlChange={remote.setBaseUrl}
              onPairingCodeChange={remote.setPairingCode}
              onScanQrCode={() => setPairingScannerVisible(true)}
              onConnect={remote.connect}
              onDisconnect={remote.disconnect}
              onRefresh={remote.refresh}
              onDemoModeChange={(enabled) => {
                setDemoMode(enabled);
                if (enabled) {
                  demo.reset();
                }
              }}
            />
            {demoMode ? (
              <View style={styles.demoBanner}>
                <Text style={styles.demoBannerTitle}>Demo Mode</Text>
                <Text style={styles.demoBannerText}>Offline story tour with sample chat, Visual Reply, and animated MuseTalk avatar.</Text>
              </View>
            ) : null}
            <RemoteCockpit
              state={activeState}
              baseUrl={remote.baseUrl}
              demoMode={demoMode}
              sessionActive={sessionActive}
              status={remote.status}
              transport={remote.transport}
            />
            <QuickActions
              running={runtimeRunning}
              disabled={!commandsAvailable}
              visualDisabled={!sessionActive}
              voiceAvailable={phoneSttAvailable && !demoMode && commandsAvailable}
              recording={recorder.recording}
              onStart={demoMode ? demo.startEngine : remote.startEngine}
              onStop={demoMode ? demo.stopEngine : remote.stopEngine}
              onPause={() => demoMode ? demo.sendControl('pause_speech', sendOptions) : remote.sendControl('pause_speech', sendOptions)}
              onTalk={recorder.toggleRecording}
              onVisual={() => setActiveTab('visual')}
            />
          </> : null}
          <PairingQrScanner
            visible={pairingScannerVisible}
            onCancel={() => setPairingScannerVisible(false)}
            onPairingScanned={(setup) => {
              if (remote.pairAndConnect(setup.baseUrl, setup.pairingCode)) {
                setDemoMode(false);
                setPairingScannerVisible(false);
              }
            }}
          />
          <ChatPhotoCapture
            visible={chatPhotoVisible}
            onCancel={() => setChatPhotoVisible(false)}
            onSend={(imageBase64, format, prompt) => remote.sendImage(imageBase64, format, prompt, sendOptions)}
          />
          <View style={styles.mainArea}>
            {activeTab === 'chat' ? (
              <View style={styles.chatPanel}>
                <ChatFeed
                  messages={activeState?.chat?.messages ?? []}
                  client={remote.client}
                  textColor={settings.chatTextColor}
                  indicatorStyle={settings.chatIndicatorStyle}
                  activity={runtimeActivity}
                />
                <Composer
                  disabled={!commandsAvailable}
                  photoAvailable={!demoMode && commandsAvailable}
                  voiceAvailable={phoneSttAvailable && !demoMode}
                  recording={recorder.recording}
                  busy={recorder.busy}
                  recordingError={recorder.error}
                  transcript={recorder.transcript}
                  onTranscriptConsumed={recorder.clearTranscript}
                  onSend={(text) => demoMode ? demo.sendText(text, sendOptions) : remote.sendText(text, sendOptions)}
                  onRecordPress={recorder.toggleRecording}
                  onPhotoPress={() => setChatPhotoVisible(true)}
                />
              </View>
            ) : null}
            {activeTab === 'visual' ? (
              <ScrollView
                keyboardShouldPersistTaps="handled"
                style={styles.tabPanel}
                contentContainerStyle={styles.stackedContent}
              >
                <VisualPanel
                  client={remote.client}
                  visual={activeState?.visual}
                  disabled={!sessionActive}
                  controlsAvailable={visualControlsAvailable}
                  controlsDisabled={!commandsAvailable}
                  demoMode={demoMode}
                  onGenerate={demoMode ? demo.visualGenerate : remote.visualGenerate}
                  onAction={demoMode ? demo.visualAction : remote.visualAction}
                  onRefresh={demoMode ? async () => undefined : remote.refresh}
                />
              </ScrollView>
            ) : null}
            {activeTab === 'story' ? (
              <ScrollView
                keyboardShouldPersistTaps="handled"
                style={styles.tabPanel}
                contentContainerStyle={styles.stackedContent}
              >
                <MprcPanel
                  mprc={activeState?.mprc}
                  disabled={!sessionActive}
                  onSend={demoMode ? demo.sendStoryText : remote.sendStoryText}
                  onChoice={demoMode ? demo.selectStoryChoice : remote.selectStoryChoice}
                  onAction={demoMode ? demo.storyAction : remote.storyAction}
                  onCastAction={demoMode ? demo.storyCastAction : remote.storyCastAction}
                  onRefresh={demoMode ? async () => undefined : remote.refresh}
                />
              </ScrollView>
            ) : null}
            {activeTab === 'audio' ? (
              <ScrollView style={styles.tabPanel} contentContainerStyle={styles.stackedContent}>
                <MediaPanel
                  audio={activeState?.media}
                  playback={audioQueue}
                  disabled={!commandsAvailable}
                  demoMode={demoMode}
                  onClearQueue={async () => {
                    if (demoMode) {
                      await demo.clearAudio();
                    } else {
                      await remote.clearAudio();
                    }
                    audioQueue.reset();
                  }}
                />
              </ScrollView>
            ) : null}
            {activeTab === 'more' ? (
              <MorePanel
                mode={moreMode}
                onModeChange={setMoreMode}
                state={activeState}
                remote={remote}
                demo={demo}
                demoMode={demoMode}
                commandsAvailable={commandsAvailable}
                sessionActive={sessionActive}
                musetalkAvailable={musetalkAvailable}
                settings={settings}
                setSettings={setSettings}
              />
            ) : null}
          </View>
          {immersiveChrome.chromeVisible ? <BottomNavigation
            activeTab={activeTab}
            state={activeState}
            sessionActive={sessionActive}
            demoMode={demoMode}
            onChange={setActiveTab}
          /> : null}
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
    </InterfaceModeProvider>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.background,
  },
  screenImmersive: {
    backgroundColor: '#000000',
  },
  keyboard: {
    flex: 1,
  },
  appShell: {
    flex: 1,
    gap: spacing.sm,
    paddingBottom: spacing.sm,
    paddingHorizontal: spacing.sm,
    paddingTop: Platform.OS === 'android' ? (StatusBar.currentHeight ?? 0) + spacing.xs : spacing.xs,
  },
  appShellImmersive: {
    gap: 0,
    paddingBottom: 0,
    paddingHorizontal: 0,
  },
  topControlsHandle: {
    alignItems: 'center',
    height: 22,
    justifyContent: 'center',
  },
  topControlsHandleBar: {
    backgroundColor: colors.border,
    borderRadius: 2,
    height: 4,
    width: 48,
  },
  topControlsHandleBarActive: {
    backgroundColor: colors.accent,
  },
  demoBanner: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.accent,
    borderRadius: 8,
    borderWidth: 1,
    gap: 2,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  demoBannerTitle: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '900',
    textTransform: 'uppercase',
  },
  demoBannerText: {
    color: colors.text,
    fontSize: 12,
    lineHeight: 16,
  },
  cockpit: {
    backgroundColor: colors.panel,
    borderColor: colors.border,
    borderRadius: 8,
    borderWidth: 1,
    gap: spacing.sm,
    padding: spacing.md,
  },
  cockpitHeader: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: spacing.sm,
    justifyContent: 'space-between',
  },
  brandBlock: {
    alignItems: 'center',
    flex: 1,
    flexDirection: 'row',
    gap: spacing.sm,
    minWidth: 0,
  },
  brandMark: {
    alignItems: 'center',
    backgroundColor: colors.panelAlt,
    borderColor: colors.accent,
    borderRadius: 8,
    borderWidth: 1,
    height: 34,
    justifyContent: 'center',
    overflow: 'hidden',
    width: 34,
  },
  brandCrossVertical: {
    backgroundColor: colors.accent,
    height: 24,
    opacity: 0.7,
    position: 'absolute',
    width: 2,
  },
  brandCrossHorizontal: {
    backgroundColor: colors.accent,
    height: 2,
    opacity: 0.7,
    position: 'absolute',
    width: 24,
  },
  brandTextBlock: {
    flex: 1,
    minWidth: 0,
  },
  brandTitle: {
    color: colors.text,
    fontSize: 16,
    fontWeight: '900',
  },
  brandSubtitle: {
    color: colors.muted,
    fontSize: 11,
    marginTop: 2,
  },
  statePill: {
    borderColor: colors.border,
    borderRadius: 7,
    borderWidth: 1,
    color: colors.muted,
    flexShrink: 0,
    fontSize: 11,
    fontWeight: '900',
    paddingHorizontal: spacing.sm,
    paddingVertical: 5,
  },
  statePillLive: {
    backgroundColor: 'rgba(94, 224, 160, 0.12)',
    borderColor: colors.ok,
    color: colors.ok,
  },
  signalRow: {
    flexDirection: 'row',
    gap: spacing.xs,
  },
  signalTile: {
    backgroundColor: colors.panelAlt,
    borderColor: colors.border,
    borderRadius: 7,
    borderWidth: 1,
    flex: 1,
    minHeight: 46,
    minWidth: 0,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  signalLabel: {
    color: colors.muted,
    fontSize: 10,
    fontWeight: '800',
    textTransform: 'uppercase',
  },
  signalValue: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '900',
    marginTop: 3,
  },
  signalValueOk: {
    color: colors.ok,
  },
  signalValueWarn: {
    color: colors.warning,
  },
  quickActions: {
    flexDirection: 'row',
    gap: spacing.xs,
  },
  actionButton: {
    alignItems: 'center',
    backgroundColor: colors.panel,
    borderColor: colors.border,
    borderRadius: 8,
    borderWidth: 1,
    flex: 1,
    gap: 4,
    justifyContent: 'center',
    minHeight: 58,
    minWidth: 0,
    paddingHorizontal: spacing.xs,
    paddingVertical: spacing.xs,
  },
  actionButtonActive: {
    borderColor: colors.ok,
  },
  actionText: {
    color: colors.text,
    fontSize: 10,
    fontWeight: '900',
    textAlign: 'center',
  },
  iconBox: {
    alignItems: 'center',
    borderColor: colors.muted,
    borderRadius: 6,
    borderWidth: 2,
    height: 22,
    justifyContent: 'center',
    position: 'relative',
    width: 22,
  },
  iconBoxActive: {
    borderColor: colors.accent,
  },
  iconChatLine: {
    backgroundColor: colors.muted,
    borderRadius: 1,
    height: 2,
    marginBottom: 2,
    width: 10,
  },
  iconChatLineLong: {
    width: 13,
  },
  iconChatTail: {
    borderLeftColor: 'transparent',
    borderLeftWidth: 4,
    borderTopColor: colors.muted,
    borderTopWidth: 4,
    bottom: -5,
    height: 0,
    position: 'absolute',
    right: 3,
    width: 0,
  },
  iconBookLeft: {
    borderColor: colors.muted,
    borderRadius: 3,
    borderWidth: 1,
    height: 14,
    left: 3,
    position: 'absolute',
    width: 7,
  },
  iconBookRight: {
    borderColor: colors.muted,
    borderRadius: 3,
    borderWidth: 1,
    height: 14,
    position: 'absolute',
    right: 3,
    width: 7,
  },
  iconBookSpine: {
    backgroundColor: colors.muted,
    height: 14,
    position: 'absolute',
    width: 1,
  },
  iconImageSun: {
    backgroundColor: colors.warning,
    borderRadius: 999,
    height: 4,
    position: 'absolute',
    right: 4,
    top: 4,
    width: 4,
  },
  iconImageMountain: {
    borderBottomColor: colors.muted,
    borderBottomWidth: 8,
    borderLeftColor: 'transparent',
    borderLeftWidth: 6,
    borderRightColor: 'transparent',
    borderRightWidth: 6,
    bottom: 4,
    height: 0,
    position: 'absolute',
    width: 0,
  },
  iconBars: {
    alignItems: 'flex-end',
    flexDirection: 'row',
    gap: 2,
  },
  iconBar: {
    backgroundColor: colors.muted,
    borderRadius: 2,
    height: 12,
    width: 3,
  },
  iconBarShort: {
    height: 7,
  },
  iconBarTall: {
    height: 15,
  },
  iconGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 3,
    height: 13,
    width: 13,
  },
  iconDot: {
    backgroundColor: colors.muted,
    borderRadius: 2,
    height: 5,
    width: 5,
  },
  iconPlay: {
    borderBottomColor: 'transparent',
    borderBottomWidth: 6,
    borderLeftColor: colors.muted,
    borderLeftWidth: 9,
    borderTopColor: 'transparent',
    borderTopWidth: 6,
    height: 0,
    marginLeft: 2,
    width: 0,
  },
  iconPause: {
    flexDirection: 'row',
    gap: 4,
  },
  iconPauseBar: {
    backgroundColor: colors.muted,
    borderRadius: 2,
    height: 12,
    width: 3,
  },
  iconMicHead: {
    borderColor: colors.muted,
    borderRadius: 7,
    borderWidth: 2,
    height: 12,
    position: 'absolute',
    top: 3,
    width: 9,
  },
  iconMicStem: {
    backgroundColor: colors.muted,
    bottom: 4,
    height: 6,
    position: 'absolute',
    width: 2,
  },
  iconMicBase: {
    backgroundColor: colors.muted,
    borderRadius: 2,
    bottom: 3,
    height: 2,
    position: 'absolute',
    width: 10,
  },
  mainArea: {
    flex: 1,
    minHeight: 0,
  },
  chatPanel: {
    flex: 1,
    minHeight: 0,
  },
  tabPanel: {
    flex: 1,
  },
  stackedContent: {
    gap: spacing.sm,
    paddingBottom: spacing.lg,
  },
  controlsDrawer: {
    backgroundColor: colors.panel,
    borderColor: colors.border,
    borderRadius: 8,
    borderWidth: 1,
    overflow: 'hidden',
  },
  controlsDrawerClean: { backgroundColor: 'transparent', borderLeftWidth: 0, borderRadius: 0, borderRightWidth: 0 },
  controlsDrawerImmersive: { borderColor: '#20252a' },
  controlsDrawerHeader: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: spacing.sm,
    minHeight: 48,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  controlsDrawerText: {
    flex: 1,
    minWidth: 0,
  },
  controlsDrawerTitle: {
    color: colors.text,
    fontSize: 13,
    fontWeight: '900',
  },
  controlsDrawerMeta: {
    color: colors.muted,
    fontSize: 12,
    marginTop: 2,
  },
  controlsDrawerToggle: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '800',
  },
  controlsDrawerBody: {
    borderTopColor: colors.border,
    borderTopWidth: 1,
  },
  morePanel: {
    flex: 1,
    gap: spacing.sm,
    minHeight: 0,
  },
  moreTabs: {
    backgroundColor: colors.panel,
    borderColor: colors.border,
    borderRadius: 8,
    borderWidth: 1,
    flexDirection: 'row',
    gap: spacing.xs,
    padding: spacing.xs,
  },
  moreTabsClean: {
    backgroundColor: 'transparent',
    borderLeftWidth: 0,
    borderRadius: 0,
    borderRightWidth: 0,
  },
  moreTabsImmersive: {
    borderColor: '#20252a',
  },
  moreTabButton: {
    alignItems: 'center',
    borderColor: 'transparent',
    borderRadius: 7,
    borderWidth: 1,
    flex: 1,
    minHeight: 36,
    justifyContent: 'center',
  },
  moreTabButtonActive: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.accent,
  },
  moreTabText: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: '900',
  },
  moreTabTextActive: {
    color: colors.text,
  },
  bottomNav: {
    backgroundColor: colors.panel,
    borderColor: colors.border,
    borderRadius: 8,
    borderWidth: 1,
    flexDirection: 'row',
    gap: spacing.xs,
    minHeight: 66,
    padding: spacing.xs,
  },
  bottomNavClean: {
    backgroundColor: 'transparent',
    borderBottomWidth: 0,
    borderLeftWidth: 0,
    borderRadius: 0,
    borderRightWidth: 0,
  },
  bottomNavImmersive: {
    backgroundColor: 'rgba(0,0,0,0.92)',
    borderTopColor: '#20252a',
  },
  navButton: {
    alignItems: 'center',
    borderColor: 'transparent',
    borderRadius: 7,
    borderWidth: 1,
    flex: 1,
    gap: 2,
    justifyContent: 'center',
    minWidth: 0,
    paddingHorizontal: 2,
    paddingVertical: spacing.xs,
  },
  navButtonActive: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.accent,
  },
  navLabel: {
    color: colors.muted,
    fontSize: 10,
    fontWeight: '900',
    textAlign: 'center',
  },
  navLabelActive: {
    color: colors.text,
  },
  navBadge: {
    color: colors.muted,
    fontSize: 8,
    fontWeight: '800',
    textAlign: 'center',
    textTransform: 'uppercase',
  },
  navBadgeActive: {
    color: colors.ok,
  },
  disabled: {
    opacity: 0.35,
  },
});
