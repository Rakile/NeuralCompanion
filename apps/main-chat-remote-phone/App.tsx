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
import { useAudioQueue } from './src/hooks/useAudioQueue';
import { usePhoneSettings } from './src/hooks/usePhoneSettings';
import { useRecorder } from './src/hooks/useRecorder';
import { useRemoteConnection } from './src/hooks/useRemoteConnection';
import { colors, spacing } from './src/styles/theme';

type MainTab = 'chat' | 'story' | 'visual' | 'audio' | 'musetalk' | 'settings';

const mainTabs: Array<{ id: MainTab; label: string }> = [
  { id: 'chat', label: 'Chat' },
  { id: 'story', label: 'Story' },
  { id: 'visual', label: 'Visual' },
  { id: 'audio', label: 'Audio' },
  { id: 'musetalk', label: 'Avatar' },
  { id: 'settings', label: 'Settings' },
];

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
          <RuntimeBar
            state={activeState}
            disabled={!commandsAvailable}
            onStart={demoMode ? demo.startEngine : remote.startEngine}
            onStop={demoMode ? demo.stopEngine : remote.stopEngine}
          />
          <ControlsBar
            actions={activeState?.controls?.actions ?? []}
            disabled={!commandsAvailable}
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
              return (
                <Pressable
                  key={tab.id}
                  style={[styles.tabButton, selected && styles.tabButtonActive]}
                  onPress={() => setActiveTab(tab.id)}
                >
                  <Text style={[styles.tabText, selected && styles.tabTextActive]}>{tab.label}</Text>
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
  tabButton: {
    alignItems: 'center',
    borderColor: 'transparent',
    borderRadius: 5,
    borderWidth: 1,
    minWidth: 82,
    minHeight: 36,
    justifyContent: 'center',
    paddingHorizontal: spacing.xs,
  },
  tabButtonActive: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.accent,
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
