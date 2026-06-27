import React from 'react';
import { KeyboardAvoidingView, Platform, Pressable, SafeAreaView, ScrollView, StatusBar, StyleSheet, Text, View } from 'react-native';
import { activateKeepAwakeAsync, deactivateKeepAwake } from 'expo-keep-awake';

import { ChatFeed } from './src/components/ChatFeed';
import { Composer } from './src/components/Composer';
import { ConnectionPanel } from './src/components/ConnectionPanel';
import { ControlsBar } from './src/components/ControlsBar';
import { MediaPanel } from './src/components/MediaPanel';
import { MprcPanel } from './src/components/MprcPanel';
import { MuseTalkPanel } from './src/components/MuseTalkPanel';
import { RuntimeBar } from './src/components/RuntimeBar';
import { SettingsPanel } from './src/components/SettingsPanel';
import { VisualPanel } from './src/components/VisualPanel';
import { useDemoRemote } from './src/demo/useDemoRemote';
import type { RemoteState } from './src/api/types';
import { useAudioQueue } from './src/hooks/useAudioQueue';
import { usePhoneSettings } from './src/hooks/usePhoneSettings';
import { useRecorder } from './src/hooks/useRecorder';
import { useRemoteConnection } from './src/hooks/useRemoteConnection';
import { colors, spacing } from './src/styles/theme';

type MainTab = 'chat' | 'story' | 'visual' | 'audio' | 'musetalk' | 'settings';

const mainTabs: Array<{ id: MainTab; label: string; icon: string }> = [
  { id: 'chat', label: 'Chat', icon: 'CH' },
  { id: 'story', label: 'Story', icon: 'ST' },
  { id: 'visual', label: 'Image', icon: 'IMG' },
  { id: 'audio', label: 'Audio', icon: 'AUD' },
  { id: 'musetalk', label: 'Avatar', icon: 'AV' },
  { id: 'settings', label: 'Settings', icon: 'SET' },
];

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
  if (tab === 'musetalk') {
    return state?.musetalk?.available === false ? 'Off' : state?.musetalk?.state?.status ? 'Live' : 'Ready';
  }
  if (tab === 'story') {
    return state?.mprc?.available ? `Turn ${Number(state.mprc.session?.turn_index ?? 0)}` : 'Off';
  }
  if (tab === 'settings') {
    return state?.buddy_chat?.enabled ? 'Buddy' : 'Ready';
  }
  return state?.runtime_status?.running || state?.engine?.running ? 'Ready' : 'Idle';
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
  const [open, setOpen] = React.useState(false);
  const runtime = state?.runtime_status;
  const running = Boolean(state?.engine?.running ?? runtime?.running);
  const actionCount = state?.controls?.actions?.length ?? 0;
  return (
    <View style={styles.controlsDrawer}>
      <Pressable style={styles.controlsDrawerHeader} onPress={() => setOpen((value) => !value)}>
        <View style={styles.controlsDrawerText}>
          <Text style={styles.controlsDrawerTitle}>Desktop Controls</Text>
          <Text style={styles.controlsDrawerMeta} numberOfLines={1}>
            {demoMode ? 'Demo desktop state' : running ? 'Runtime running' : 'Runtime stopped'} - {runtime?.chat_provider || 'LLM'} - {actionCount} actions
          </Text>
        </View>
        <Text style={styles.controlsDrawerToggle}>{open ? 'Hide' : 'Show'}</Text>
      </Pressable>
      {open ? (
        <View style={styles.controlsDrawerBody}>
          <RuntimeBar state={state} disabled={disabled} onStart={onStart} onStop={onStop} />
          <ControlsBar actions={state?.controls?.actions ?? []} disabled={disabled} onControl={onControl} />
        </View>
      ) : null}
    </View>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = React.useState<MainTab>('chat');
  const [demoMode, setDemoMode] = React.useState(false);
  const { settings, setSettings } = usePhoneSettings();
  const remote = useRemoteConnection({
    autoReconnect: settings.autoReconnect,
    pollingIntervalMs: settings.pollingIntervalMs,
  });
  const demo = useDemoRemote(demoMode);
  const sessionActive = demoMode || remote.connected || remote.transport !== 'none';
  const activeState = demoMode ? demo.state : sessionActive ? remote.state : null;
  const commandsAvailable = demoMode || remote.connected;
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
    <SafeAreaView style={styles.screen}>
      <StatusBar barStyle="light-content" />
      <KeyboardAvoidingView style={styles.keyboard} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.appShell}>
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
          <DesktopControlsDrawer
            state={activeState}
            disabled={!commandsAvailable}
            demoMode={demoMode}
            onStart={demoMode ? demo.startEngine : remote.startEngine}
            onStop={demoMode ? demo.stopEngine : remote.stopEngine}
            onControl={(action) => demoMode ? demo.sendControl(action, sendOptions) : remote.sendControl(action, sendOptions)}
          />
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            style={styles.tabBar}
            contentContainerStyle={styles.tabBarContent}
          >
            {mainTabs.map((tab) => {
              const selected = activeTab === tab.id;
              const badge = tabBadge(tab.id, activeState, sessionActive, demoMode);
              return (
                <Pressable
                  key={tab.id}
                  style={[styles.tabButton, selected && styles.tabButtonActive]}
                  onPress={() => setActiveTab(tab.id)}
                >
                  <View style={styles.tabInner}>
                    <Text style={[styles.tabIcon, selected && styles.tabIconActive]}>{tab.icon}</Text>
                    <Text style={[styles.tabText, selected && styles.tabTextActive]}>{tab.label}</Text>
                  </View>
                  <Text style={[styles.tabBadge, selected && styles.tabBadgeActive]}>{badge}</Text>
                </Pressable>
              );
            })}
          </ScrollView>
          <View style={styles.mainArea}>
            {activeTab === 'chat' ? (
              <>
                <ChatFeed messages={activeState?.chat?.messages ?? []} />
                <Composer
                  disabled={!commandsAvailable}
                  voiceAvailable={phoneSttAvailable && !demoMode}
                  recording={recorder.recording}
                  busy={recorder.busy}
                  recordingError={recorder.error}
                  transcript={recorder.transcript}
                  onTranscriptConsumed={recorder.clearTranscript}
                  onSend={(text) => demoMode ? demo.sendText(text, sendOptions) : remote.sendText(text, sendOptions)}
                  onRecordPress={recorder.toggleRecording}
                />
              </>
            ) : null}
            {activeTab === 'visual' ? (
              <ScrollView
                keyboardShouldPersistTaps="handled"
                style={styles.tabPanel}
                contentContainerStyle={styles.tabContent}
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
                contentContainerStyle={styles.tabContent}
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
              <ScrollView style={styles.tabPanel} contentContainerStyle={styles.tabContent}>
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
            {activeTab === 'musetalk' ? (
              <ScrollView style={styles.tabPanel} contentContainerStyle={styles.tabContent}>
                <MuseTalkPanel
                  client={remote.client}
                  musetalk={activeState?.musetalk}
                  disabled={!sessionActive}
                  available={musetalkAvailable}
                  quality={settings.museTalkQuality}
                  demoMode={demoMode}
                />
              </ScrollView>
            ) : null}
            {activeTab === 'settings' ? (
              <SettingsPanel
                settings={settings}
                onChange={setSettings}
                state={activeState}
                health={remote.health}
                status={remote.status}
                transport={remote.transport}
                error={remote.error}
              />
            ) : null}
          </View>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.background,
  },
  keyboard: {
    flex: 1,
  },
  appShell: {
    flex: 1,
    gap: spacing.sm,
    paddingBottom: spacing.md,
    paddingHorizontal: spacing.sm,
    paddingTop: Platform.OS === 'android' ? (StatusBar.currentHeight ?? 0) + spacing.xs : spacing.xs,
  },
  tabBar: {
    backgroundColor: colors.panel,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    flexGrow: 0,
    maxHeight: 48,
  },
  tabBarContent: {
    flexDirection: 'row',
    gap: spacing.xs,
    padding: spacing.xs,
  },
  demoBanner: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.accent,
    borderRadius: 6,
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
  controlsDrawer: {
    backgroundColor: colors.panel,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    overflow: 'hidden',
  },
  controlsDrawerHeader: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: spacing.sm,
    minHeight: 46,
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
  tabButton: {
    alignItems: 'center',
    borderColor: 'transparent',
    borderRadius: 5,
    borderWidth: 1,
    gap: 2,
    justifyContent: 'center',
    minHeight: 42,
    minWidth: 84,
    paddingHorizontal: spacing.xs,
    paddingVertical: spacing.xs,
  },
  tabButtonActive: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.accent,
  },
  tabInner: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: spacing.xs,
  },
  tabIcon: {
    color: colors.muted,
    fontSize: 10,
    fontWeight: '900',
  },
  tabIconActive: {
    color: colors.text,
  },
  tabText: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: '800',
    textAlign: 'center',
  },
  tabTextActive: {
    color: colors.text,
  },
  tabBadge: {
    color: colors.muted,
    fontSize: 9,
    fontWeight: '800',
    textAlign: 'center',
    textTransform: 'uppercase',
  },
  tabBadgeActive: {
    color: colors.ok,
  },
  mainArea: {
    flex: 1,
    minHeight: 0,
  },
  tabPanel: {
    flex: 1,
  },
  tabContent: {
    backgroundColor: colors.panel,
    paddingBottom: spacing.lg,
  },
});
