import { useThemedStyles, useThemeColors } from './src/styles/ThemeContext';
import type { ThemeColors } from './src/styles/theme';
import React from 'react';
import * as Crypto from 'expo-crypto';
import { recordPhoneDebug } from './src/utils/phoneDebugBridge';
import { useNativeDiagnostics } from './src/diagnostics/useNativeDiagnostics';
import {connectionTrace} from './src/utils/connectionTrace';
import {useConnectionDiagnostics} from './src/hooks/useConnectionDiagnostics';
import { Alert, AppState, BackHandler, Keyboard, KeyboardAvoidingView, Platform, Pressable, ScrollView, StatusBar, StyleSheet, Text, View } from 'react-native';
import { activateKeepAwakeAsync, deactivateKeepAwake } from 'expo-keep-awake';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import { ReadingConversation } from './src/components/ReadingConversation';
import { ConversationControls } from './src/components/ConversationControls';
import { usePhoneMediaControls } from './src/hooks/usePhoneMediaControls';
import { useAuthorizedMediaUrl } from './src/hooks/useAuthorizedMediaUrl';
import { DesktopControlsSheet } from './src/components/DesktopControlsSheet';
import {SoundscapePanel} from './src/components/soundscape/SoundscapePanel';
import {ChatSoundsMenu} from './src/components/soundscape/ChatSoundsMenu';
import {useSoundscape} from './src/hooks/useSoundscape';
import type { ConversationActionBody, ConversationActionKind, ConversationActionTarget } from './src/api/types';
import { InterfaceModeProvider, useInterfaceMode } from './src/context/InterfaceModeContext';
import { useChatPhotoDraft } from './src/hooks/useChatPhotoDraft';
import { useManualTurnQueue } from './src/hooks/useManualTurnQueue';
import type {ManualDeparturePermit} from './src/native/androidManualDeparture';
import {PendingVoiceRecording} from './src/components/PendingVoiceRecording';
import { remoteActionError } from './src/api/envelope';
import { Composer } from './src/components/Composer';
import { DismissibleFault } from './src/components/DismissibleFault';
import { useComposerDraft } from './src/hooks/useComposerDraft';
import type { SlashCommand } from './src/utils/slashCommands';
import { noCommandArguments } from './src/utils/slashCommands';
import { requestCommandDraft } from './src/utils/commandDraft';
import { LiveModeControl } from './src/components/LiveModeControl';
import { ConnectionPanel } from './src/components/ConnectionPanel';
import { ControlsBar } from './src/components/ControlsBar';
import {extraQuickMenuActions} from './src/utils/quickMenuActions';
import {QuickMenuActionButton} from './src/components/QuickMenuActionButton';
import { MediaPanel } from './src/components/MediaPanel';
import { MprcPanel } from './src/components/MprcPanel';
import { MuseTalkPanel } from './src/components/MuseTalkPanel';
import { PairingQrScanner } from './src/components/PairingQrScanner';
import { LiveFullscreenScreen } from './src/components/live-fullscreen/LiveFullscreenScreen';
import { MuseTalkFullscreenControls } from './src/components/live-fullscreen/MuseTalkFullscreenControls';
import {IdleLoopDownloadStatus} from './src/components/IdleLoopDownloadStatus';
import { AudioSampleTap } from './src/components/live-fullscreen/AudioSampleTap';
import { RuntimeBar } from './src/components/RuntimeBar';
import type { SettingsSection } from './src/components/SettingsPanel';
import { PhoneThemeProvider, usePhoneTheme } from './src/styles/ThemeContext';
import { SettingsPanel } from './src/components/SettingsPanel';
import { VisualPanel } from './src/components/VisualPanel';
import { VisualReplySettingsSheet } from './src/components/VisualReplySettingsSheet';
import { CompanionSurface } from './src/components/CompanionSurface';
import { PresenceControlsDock } from './src/components/PresenceControlsDock';
import { ContinuousPanel } from './src/components/continuous/ContinuousPanel';
import { StoryPlanPanel } from './src/components/story-plan/StoryPlanPanel';
import { StoryCompletionSheet } from './src/components/story-plan/StoryCompletionSheet';
import { StoryRefinePanel } from './src/components/story-plan/StoryRefinePanel';
import type { StoryRefineSettings } from './src/components/story-plan/StoryRefinePanel';
import { StoryLibraryPanel } from './src/components/story-library/StoryLibraryPanel';
import { storyPlanToChatPrompt } from './src/utils/storyPlan';
import type { StoryPlan, StoryPlanDraft, StoryPlanAction, StoryPace, StoryLibraryEntry, StoryLibraryAction, StoryLibraryResult } from './src/api/types';
import { readContinuousUserMessage, ContinuousUserPlayback } from './src/utils/continuousUserSpeech';
import { useContinuousConversation } from './src/hooks/useContinuousConversation';
import { continuousActivityAllowed, retainContinuousOutput } from './src/utils/continuousBackground';
import { setBackgroundInterval as setInterval, setBackgroundTimeout, clearBackgroundTimer as clearInterval } from './src/utils/backgroundClock';
import { AppHeader } from './src/components/app-shell/AppHeader';
import { NeutralHeaderAvatar } from './src/components/presence/NeutralHeaderAvatar';
import { MoodAvatar } from './src/components/presence/MoodAvatar';
import { QuickPersonaSheet } from './src/components/presence/QuickPersonaSheet';
import { PrimaryNavigation } from './src/components/app-shell/PrimaryNavigation';
import { ScreenHeader } from './src/components/app-shell/ScreenHeader';
import { ToolsScreen } from './src/components/app-shell/ToolsScreen';
import { ChatCharacterLibrary } from './src/components/chat-characters/ChatCharacterLibrary';
import { CharacterNotice, CharacterCandidateNotice } from './src/components/chat-characters/CharacterNotice';
import { AssignExistingCharacterSheet } from './src/components/chat-characters/AssignExistingCharacterSheet';
import { useChatCharacters } from './src/hooks/useChatCharacters';
import { activeCharacterSpeaker, canPreviewCharacterVoice } from './src/utils/chatCharacterDrafts';
import { useDemoRemote } from './src/demo/useDemoRemote';
import type { ChatMessage, InlineVisualReply, PresenceActivity, RemoteConnectionStatus, RemoteState, RemoteTransport } from './src/api/types';
import type { VisualAutoMode, VisualAutoStatus } from './src/api/types';
import { useAudioQueue } from './src/hooks/useAudioQueue';
import {progressivePcmAvailable} from './src/native/progressivePcm';
import { useMuseTalkLivePresentation } from './src/hooks/useMuseTalkLivePresentation';
import { useAvatarPresentationTarget } from './src/hooks/useAvatarPresentationTarget';
import { usePhonePresentation } from './src/hooks/usePhonePresentation';
import type { OptionalVisualStart } from './src/utils/optionalVisualStart';
import { usePhoneSettings } from './src/hooks/usePhoneSettings';
import { engineIndicatorStatus } from './src/utils/engineIndicator';
import { SilkSettingsContext, VoiceVisualizerContext } from './src/components/presence/SilkSettingsContext';
import { useBackendRecorder } from './src/hooks/useBackendRecorder';
import { usePhoneNativeSpeech } from './src/hooks/usePhoneNativeSpeech';
import { PhonePlaybackBoundary } from './src/utils/phoneNativeSpeech';
import { useRemoteConnection } from './src/hooks/useRemoteConnection';
import { isRecord } from './src/api/envelope';
import type { AudioChunk, PhoneReplyAuth, PhoneReplyReceipt, PhoneReplyStatus } from './src/api/types';
import { isUncertainPhoneReplyError, phoneReplyErrorCode, phoneReplyRequestId, retryPhoneReply, RemoteRequestError } from './src/api/client';
import { phoneReplyReceiptAvailable } from './src/native/iosPlaybackGuard';
import { BackgroundReplyFence } from './src/utils/backgroundReplyFence';
import { withStreamingReplyPreview } from './src/utils/streamingReplyPreview';
import { createReplyContinuation, continuationIsCurrent } from './src/utils/replyContinuation';
import type { ReplyContinuation } from './src/utils/replyContinuation';
import { getIosLiveCapture } from './src/native/iosLiveCapture';
import { playbackGuardAvailable } from './src/native/iosPlaybackGuard';
import { androidContinuousCaptureRuntimeEnabled, continuousCaptureRuntimeEnabled } from './src/native/iosContinuousCapturePolicy';
import { colors, spacing } from './src/styles/theme';
import { keyboardAvoidingBehavior } from './src/utils/keyboardLayout';
import { InitialAudioSnapshot, shouldInterruptForPhoneText } from './src/utils/audioFastStart';
import { liveMicPauseReason } from './src/utils/liveMicPolicy';
import {
  PHONE_STORY_MODE_ENABLED,
  isPhoneDestinationEnabled,
  closeSecondarySurface,
  productionBackAction,
  resolveProductionSurface,
  shouldShowConnectionBack,
  shouldShowPrimaryNavigation,
} from './src/utils/productionShell';
import type { PrimaryDestination, SecondarySurface } from './src/utils/productionShell';

type MainTab = PrimaryDestination;
type IconName = 'chat' | 'story' | 'visual' | 'audio' | 'more' | 'runtime' | 'pause' | 'mic';
type MoreMode = 'avatar' | 'settings';
import { useBufferedPlayback } from './src/native/useBufferedPlayback';
import { MuseTalkLiveSessionView } from './src/dev/MuseTalkLiveSessionView';
import { muxedTrialBlockedAudio } from './src/dev/useMuxedPlayback';
import { useDesktopOrderedAudioQueue } from './src/dev/useDesktopOrderedAudioQueue';
import {desktopOrderedContinuationAvailable} from './src/dev/useDesktopOrderedPlayback';
import {useOrderedIdleStorage} from './src/native/orderedIdleCacheRuntime';
import { orderedFailureDetails,orderedPlaybackErrorMessage } from './src/dev/desktopOrderedProtocol';
import {invokeCleanup,noteCleanupFailure} from './src/utils/cleanupFailureProvenance';
import {rememberCaptureControl} from './src/diagnostics/captureControlTrail';
import {selectMuxedPlayback,useMuxedCachePolicy} from './src/native/muxedPlaybackPolicy';
import {AndroidAudioRouteRecovery} from './src/native/androidAudioRouteRecovery';
import type {AudioRouteRecoveryContext} from './src/native/androidAudioRouteRecovery';

const PHONE_REPLY_STATUS_WARNING = 'Phone reply status unavailable. Playback ownership has not been released.';
const PHONE_REPLY_ACK_RECOVERY_EXPIRED = 'Reply acknowledgement recovery expired. Start again when ready.';

const allMainTabs: Array<{ id: MainTab; label: string; icon: IconName }> = [
  { id: 'chat', label: 'Chat', icon: 'chat' },
  { id: 'story', label: 'Story', icon: 'story' },
  { id: 'visual', label: 'Visual', icon: 'visual' },
  { id: 'tools', label: 'Tools', icon: 'more' },
];
const mainTabs = allMainTabs.filter(({ id }) => isPhoneDestinationEnabled(id));

function textOr(value: unknown, fallback: string): string {
  const text = String(value ?? '').trim();
  return text || fallback;
}

function explicitRequestId(payload: unknown): string | null {
  if (!isRecord(payload) || !isRecord(payload.result)) return null;
  const result = payload.result;
  return result.accepted === true && typeof result.phone_request_id === 'string'
    && result.phone_request_id.length > 0 && result.phone_request_id.length <= 256
    ? result.phone_request_id : null;
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
  if (tab === 'story') {
    return state?.mprc?.available ? `Turn ${Number(state.mprc.session?.turn_index ?? 0)}` : 'Off';
  }
  if (tab === 'tools') {
    if (state?.musetalk?.available !== false && state?.musetalk?.state?.status) {
      return 'Avatar';
    }
    return state?.buddy_chat?.enabled ? 'Buddy' : 'Ready';
  }
  return state?.runtime_status?.running || state?.engine?.running ? 'Ready' : 'Idle';
}

function IconGlyph({ name, active = false }: { name: IconName; active?: boolean }) {
  const styles = useThemedStyles(createStyles);

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
  const styles = useThemedStyles(createStyles);

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
  const styles = useThemedStyles(createStyles);

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
        {PHONE_STORY_MODE_ENABLED ? <SignalTile label="Story" value={storyTurn} tone={state?.mprc?.available ? 'ok' : 'neutral'} /> : null}
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
  const styles = useThemedStyles(createStyles);

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
  const styles = useThemedStyles(createStyles);

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
      <Pressable
        accessibilityLabel="Desktop controls"
        accessibilityHint={open ? 'Collapses desktop controls' : 'Expands desktop controls'}
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        style={styles.controlsDrawerHeader}
        onPress={() => setOpen((value) => !value)}
      >
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
  const styles = useThemedStyles(createStyles);

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
  setLiveFullscreenSettings,
  nativeSpeech,
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
  setLiveFullscreenSettings: ReturnType<typeof usePhoneSettings>['setLiveFullscreenSettings'];
  nativeSpeech: ReturnType<typeof usePhoneNativeSpeech>;
}) {
  const styles = useThemedStyles(createStyles);

  const { mode: interfaceMode, policy } = useInterfaceMode();
  const sendOptions = React.useMemo(() => ({
    playOnBackend: false,
    capturePhoneAudio: true,
    visualAfterSend: settings.sendMode === 'visual_reply',
  }), [settings.sendMode]);
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
          nativeSpeech={nativeSpeech}
          settings={settings}
          onChange={setSettings}
          onLiveFullscreenChange={setLiveFullscreenSettings}
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
  useNativeDiagnostics();
  const preferences = usePhoneSettings();
  return <PhoneThemeProvider theme={preferences.settings.colorTheme} presentationStyle={preferences.settings.presentationStyle}>
    <SilkSettingsContext.Provider value={preferences.settings.silk}>
      <VoiceVisualizerContext.Provider value={preferences.settings.voiceVisualizerStyle}>
        <PhoneApp preferences={preferences} />
      </VoiceVisualizerContext.Provider>
    </SilkSettingsContext.Provider>
  </PhoneThemeProvider>;
}

function PhoneApp({ preferences }: { preferences: ReturnType<typeof usePhoneSettings> }) {
  const styles = useThemedStyles(createStyles);
  const colors = useThemeColors();

  const avatarPresentation = useAvatarPresentationTarget();
  const [activeTab, setActiveTab] = React.useState<MainTab>('chat');
  const [secondarySurface, setSecondarySurface] = React.useState<SecondarySurface>(null);
  const [demoMode, setDemoMode] = React.useState(false);
  const [pairingScannerVisible, setPairingScannerVisible] = React.useState(false);
  const [liveFullscreenVisible, setLiveFullscreenVisible] = React.useState(false);
  const [presenceDockHeight, setPresenceDockHeight] = React.useState(130);
  const [avatarControlsVisible, setAvatarControlsVisible] = React.useState(false);
  const [personaSheetTab, setPersonaSheetTab] = React.useState<'persona' | 'model' | 'voice'>('persona');
  const [settingsSection, setSettingsSection] = React.useState<SettingsSection>('companion');
  const [charactersVisible, setCharactersVisible] = React.useState(false);
  const [assignmentCandidate, setAssignmentCandidate] = React.useState<{
    id:string; name:string; conversationId:string;
  } | null>(null);
  const [soundscapeVisible,setSoundscapeVisible]=React.useState(false);
  const [soundscapeEditId,setSoundscapeEditId]=React.useState('');
  const [visualSettingsVisible, setVisualSettingsVisible] = React.useState(false);
  const [visualAutoStatus, setVisualAutoStatus] = React.useState<VisualAutoStatus | null>(null);
  const [visualAutoBusy, setVisualAutoBusy] = React.useState(false);
  const [visualAutoError, setVisualAutoError] = React.useState('');
  const [visualButtonError, setVisualButtonError] = React.useState('');
  const [visualButtonBusy, setVisualButtonBusy] = React.useState(false);
  const visualLongPressAt = React.useRef(0);
const [storyPlanVisible, setStoryPlanVisible] = React.useState(false);
  const [storyCompletionDismissed, setStoryCompletionDismissed] = React.useState(false);
  const [storyExtension, setStoryExtension] = React.useState<{source:StoryPlan; operationId:string; mode:string} | null>(null);
  const [storyExtensionDraft, setStoryExtensionDraft] = React.useState<StoryPlanDraft | null>(null);
  const storyAppendAttempt = React.useRef<{signature:string;operationId:string;revision:number} | null>(null);
const [storyPlanDraft, setStoryPlanDraft] = React.useState<StoryPlanDraft | null>(null);
const [storyRefineSetup, setStoryRefineSetup] = React.useState<{
  text:string; owner:string; initialSettings?:StoryRefineSettings; referencePlan?:StoryPlanDraft} | null>(null);
const [storyRefineSettings, setStoryRefineSettings] = React.useState<StoryRefineSettings | null>(null);
const [storyRefineCandidate, setStoryRefineCandidate] = React.useState<StoryPlanDraft | null>(null);
const [storyRefineCandidateSettings, setStoryRefineCandidateSettings] = React.useState<StoryRefineSettings | null>(null);
const [savedStoryPlan, setSavedStoryPlan] = React.useState<StoryPlan | null>(null);
const [storyPlanBusy, setStoryPlanBusy] = React.useState(false);
const [storyPlanError, setStoryPlanError] = React.useState('');
const [storyOpeningPending, setStoryOpeningPending] = React.useState(false);
const storyPlanOwner = React.useRef('');
const storyPlanOperation = React.useRef(false);
const [storyLibraryVisible, setStoryLibraryVisible] = React.useState(false);
const [storyLibraryEntries, setStoryLibraryEntries] = React.useState<StoryLibraryEntry[]>([]);
const [activeStoryEntryId, setActiveStoryEntryId] = React.useState<string | null>(null);
const [storyLibraryBusy, setStoryLibraryBusy] = React.useState(false);
const [storyLibraryActivity, setStoryLibraryActivity] = React.useState('');
const [storyLibraryError, setStoryLibraryError] = React.useState('');
const [storyRecoveryId, setStoryRecoveryId] = React.useState<string | null>(null);
const [storyTransport, setStoryTransport] = React.useState<'play' | 'pause' | 'resume'>('play');
const storyLibraryOperation = React.useRef(false);
const storySaveRetry = React.useRef<{signature:string; operationId:string} | null>(null);
const storyLibraryReadSeq = React.useRef(0);
const [responseStoryPlan, setResponseStoryPlan] = React.useState<StoryPlan | null>(null);
const [responseStoryPlanLoading, setResponseStoryPlanLoading] = React.useState(false);
const [responseStoryPlanError, setResponseStoryPlanError] = React.useState('');
const responseStoryPlanRequest = React.useRef(0);
  const [initialCharacterId, setInitialCharacterId] = React.useState('');
  const openAvatarControls = React.useCallback(() => { setSettingsSection('companion'); setSecondarySurface('settings'); }, []);
  const photoVoiceSubmissionRef = React.useRef<(permit?:ManualDeparturePermit) => ((text: string) => Promise<unknown>) | undefined>(() => undefined);
  const clearPhotoDraftRef = React.useRef<() => void>(() => undefined);
  const safeAreaInsets = useSafeAreaInsets();
  const [androidKeyboardVisible, setAndroidKeyboardVisible] = React.useState(
    () => Platform.OS === 'android' && Keyboard.isVisible(),
  );
  React.useEffect(() => {
    const show = Keyboard.addListener('keyboardDidShow', () => {
      if (Platform.OS === 'android') setAndroidKeyboardVisible(true);
      avatarPresentation.remeasure();
    });
    // Android's hide event can retain an inset screenY. Do not let the
    // avoider's overlap calculation turn that into a permanent bottom gap.
    const hide = Keyboard.addListener('keyboardDidHide', () => {
      if (Platform.OS === 'android') setAndroidKeyboardVisible(false);
      avatarPresentation.remeasure();
    });
    return () => { show.remove(); hide.remove(); };
  }, [avatarPresentation.remeasure]);
  const { settings, setLiveFullscreenSettings, setSettings } = preferences;
  const theme = usePhoneTheme();
  const [focusedVisualReply, setFocusedVisualReply] = React.useState<InlineVisualReply | undefined>();
  const [dismissedVisualIds, setDismissedVisualIds] = React.useState<Set<string>>(new Set());
  const [portraitSessionStartedAt, setPortraitSessionStartedAt] = React.useState(() => Date.now() / 1000);
  const remote = useRemoteConnection({
    mediaRequired: !demoMode && settings.audioMode === 'backend_hq',
    autoReconnect: settings.autoReconnect,
    pollingIntervalMs: settings.pollingIntervalMs,
  });
  const demo = useDemoRemote(demoMode);
  const orderedContinuationSupported=Platform.OS==='android'&&desktopOrderedContinuationAvailable();
  const orderedConnectionScope=React.useRef({key:'',scope:''});
  if(!orderedContinuationSupported||!remote.liveRecoveryKey
    ||orderedConnectionScope.current.key!==remote.liveRecoveryKey)
    orderedConnectionScope.current={key:remote.liveRecoveryKey,scope:''};
  if(remote.client.bufferedPeer?.cacheScope&&remote.liveRecoveryKey)
    orderedConnectionScope.current={key:remote.liveRecoveryKey,scope:remote.client.bufferedPeer.cacheScope};
  const retainedOrderedConnection=orderedContinuationSupported&&!!orderedConnectionScope.current.scope;
  const orderedConnectionAvailable=remote.connected||remote.playbackConnected===true||retainedOrderedConnection;
  const sessionActive = demoMode || orderedConnectionAvailable || remote.transport !== 'none';
  const returnToChatAfterRecovery = React.useRef(false);
  const openConnection = () => {
    returnToChatAfterRecovery.current = !demoMode && !remote.connected;
    setSecondarySurface('connection');
  };
  React.useEffect(() => {
    if (!remote.connected || !returnToChatAfterRecovery.current) return;
    returnToChatAfterRecovery.current = false;
    if (secondarySurface === 'connection') {
      setSecondarySurface(null);
      setActiveTab('chat');
    }
  }, [remote.connected, secondarySurface]);
  const visibleSurface = resolveProductionSurface({
    demoMode,
    primary: activeTab,
    secondary: secondarySurface,
    sessionActive,
    reconnecting: Boolean(remote.relay?.session?.wantsConnection && remote.relay.session.recoveryKey),
  });
  React.useEffect(() => {
    if (Platform.OS !== 'android') return undefined;
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      const action = productionBackAction({ primary: activeTab, secondary: secondarySurface });
      if (action === 'close_secondary') {
        setSecondarySurface(null);
        return true;
      }
      if (action === 'open_chat') {
        setActiveTab('chat');
        return true;
      }
      return false;
    });
    return () => subscription.remove();
  }, [activeTab, secondarySurface]);
  const activeState = demoMode ? demo.state : sessionActive ? remote.state : null;
  const displayMessages = React.useMemo(
    () => withStreamingReplyPreview(activeState?.chat?.messages ?? [], activeState?.chat?.streaming_preview),
    [activeState?.chat?.messages, activeState?.chat?.streaming_preview],
  );
  const characters = useChatCharacters(remote.client, remote.chatCharacterScope,
    !demoMode && remote.connected && remote.chatCharactersAvailable);
  const draftIdentity = remote.activeRoute === 'internet_relay'
    ? remote.relay?.session?.recoveryKey || remote.client.identityKey
    : `${remote.client.identityKey}:${remote.client.pairingCode}`;
  const composerDraft = useComposerDraft(`${draftIdentity}:${demoMode}`, activeState?.conversation_actions?.session_generation);
  const submissionEpoch = React.useRef(0);
  const [conversationActionBusy, setConversationActionBusy] = React.useState('');
  const connectionModeSwitch = React.useRef(false);
  const connectionSwitchMounted = React.useRef(true);
  const [connectionModeChanging, setConnectionModeChanging] = React.useState(false);
  const [connectionModeError, setConnectionModeError] = React.useState('');
  React.useEffect(() => {
    connectionSwitchMounted.current = true;
    return () => { connectionSwitchMounted.current = false; };
  }, []);
  const commandsAvailable = demoMode || remote.connected;
  const runtime = activeState?.runtime_status;
  const runtimeRunning = Boolean(activeState?.engine?.running ?? runtime?.running);
  const [engineStartPending, setEngineStartPending] = React.useState(false);
  const reportedEngineStatus = engineIndicatorStatus({
    connected: commandsAvailable, running: runtimeRunning,
    lifecycleState: activeState?.engine?.lifecycle_state ?? runtime?.lifecycle_state,
    startPending: false,
  });
  const engineStatus = engineIndicatorStatus({
    connected: commandsAvailable, running: runtimeRunning,
    lifecycleState: activeState?.engine?.lifecycle_state ?? runtime?.lifecycle_state,
    startPending: engineStartPending,
  });
  React.useEffect(() => {
    if (!commandsAvailable || reportedEngineStatus === 'running') setEngineStartPending(false);
  }, [commandsAvailable, reportedEngineStatus]);
  React.useEffect(() => {
    if (!engineStartPending) return undefined;
    const timeout = setTimeout(() => setEngineStartPending(false), 90000);
    return () => clearTimeout(timeout);
  }, [engineStartPending]);
  const startEngineFromHeader = async () => {
    if (engineStatus !== 'stopped' || !commandsAvailable) return;
    setEngineStartPending(true);
    try { await (demoMode ? demo.startEngine() : remote.startEngine()); }
    catch (error) {
      setEngineStartPending(false);
      Alert.alert('Engine could not start', error instanceof Error ? error.message : 'Try again from Desktop controls.');
    }
  };
  const nativeRequested = settings.audioMode === 'phone_native' && !demoMode;
  const storyActive = Boolean(activeState?.mprc?.session?.enabled || activeState?.mprc?.session?.active);
  const nativePlayback = nativeRequested && !storyActive;
  const [foreground, setForeground] = React.useState(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  useConnectionDiagnostics();
  const backgroundVisualsPaused = Platform.OS === 'ios' && !foreground;
  const foregroundRef = React.useRef(foreground);
  React.useEffect(() => {
    const subscription = AppState.addEventListener('change', (value) => {
      connectionTrace.event('phone_lifecycle', {state:value});
      foregroundRef.current = value === 'active'; setForeground(value === 'active');
    });
    return () => subscription.remove();
  }, []);
  const releasePlaybackRef = React.useRef<() => void>(() => undefined);
  const beforeNativeListeningRef = React.useRef<() => Promise<void>>(async () => undefined);
  const sendNativeTranscriptRef = React.useRef<(text: string) => Promise<unknown>>(async () => undefined);
  const nativeSpeech = usePhoneNativeSpeech({
    mode: settings.audioMode, identityKey: remote.client.identityKey, connected: remote.connected && !demoMode,
    storyActive, backendSupported: activeState?.features?.phone_native_audio === true,
    backendReason: String(activeState?.features?.phone_native_audio_reason || ''),
    language: settings.nativeLanguage, speakerId: settings.nativeSpeakerId, sendToChat: settings.micBehavior === 'send_auto',
    sensitivity: settings.nativeMicSensitivity,
    conversationGeneration: activeState?.conversation_actions?.session_generation,
    messages: activeState?.chat?.messages ?? [],
    onSendText: (text) => sendNativeTranscriptRef.current(text),
    releasePlayback: () => releasePlaybackRef.current(),
    onLiveSpeechStart: () => remote.sendControl('interrupt_response'),
    onBeforeListening: () => beforeNativeListeningRef.current(),
  });
  const nativeChatReady = !storyActive && activeState?.features?.phone_native_audio === true
    && nativeSpeech.capabilities?.tts.available === true && !nativeSpeech.probing;
  const chatCommandsAvailable = commandsAvailable && conversationActionBusy !== 'reset_chat' && (!nativeRequested || nativeChatReady);
  const phoneSttAvailable = nativePlayback
    ? nativeChatReady && nativeSpeech.capabilities?.stt.available === true
    : activeState?.features?.phone_stt !== false;
  const visualControlsAvailable = activeState?.features?.visual_reply_controls !== false && activeState?.visual?.service_available !== false;
  const musetalkAvailable = activeState?.musetalk?.available !== false
    && (activeState?.features?.musetalk_frame_feed !== false || activeState?.features?.musetalk_frame_stream !== false);
  const sendOptions = React.useMemo(() => ({
    audioMode: settings.audioMode,
    playOnBackend: false,
    capturePhoneAudio: settings.audioMode !== 'phone_native',
    visualAfterSend: settings.sendMode === 'visual_reply',
  }), [settings.sendMode, settings.audioMode]);
  const pauseLiveForPlaybackRef = React.useRef<() => Promise<void>>(async () => undefined);
  const playbackBoundary = React.useRef(new PhonePlaybackBoundary()).current;
  const initialAudioSnapshot = React.useRef(new InitialAudioSnapshot()).current;
  const backendHistory = initialAudioSnapshot.observe(
    remote.client.identityKey, demoMode ? null : activeState?.media?.items ?? null,
  );
  const playbackSource = !sessionActive || demoMode || (nativePlayback && (!(remote.connected || remote.mediaContinuity) || !foreground)) ? 'off' : storyActive ? 'story' : nativePlayback ? 'native' : 'hq';
  const backendChunks = playbackBoundary.select(remote.client.identityKey, playbackSource, activeState?.media?.items ?? []);
  const audioChunks = nativePlayback && playbackSource === 'native' ? nativeSpeech.chunks : backendChunks;
  const capture = React.useRef(getIosLiveCapture()).current;
  const discoveredGuardedOutput = React.useRef(playbackGuardAvailable()).current;
  const guardedOutput = Platform.OS === 'android'
    ? androidContinuousCaptureRuntimeEnabled() && discoveredGuardedOutput
    : discoveredGuardedOutput;
  const [stopListeningSupported, setStopListeningSupported] = React.useState(false);
  const [nativeContinuationSupported, setNativeContinuationSupported] = React.useState(false);
  React.useEffect(() => { let alive = true;
    void capture.capabilities().then(caps => { if (alive) {
      setStopListeningSupported(caps.stopListeningVersion === 1 && caps.foregroundReplyControlsVersion === 1);
      setNativeContinuationSupported(caps.replyContinuationVersion === 1);
    } }).catch(() => undefined);
    return () => { alive = false; };
  }, [capture]);
  const phoneReplyControls = !demoMode && !storyActive && settings.audioMode === 'backend_hq'
    && activeState?.features?.phone_reply_controls_version === 1
    && ((Platform.OS !== 'ios' && !androidContinuousCaptureRuntimeEnabled())
      || (phoneReplyReceiptAvailable() && stopListeningSupported));
  const sharedManualQueueAdvertised = phoneReplyControls && activeState?.features?.shared_manual_queue_version === 1;
  const continuationAdvertised = sharedManualQueueAdvertised && nativeContinuationSupported && activeState?.features?.reply_continuation_version === 1;
  const recoveryConversation = React.useRef({ target: '', generation: -1 });
  if (recoveryConversation.current.target !== remote.liveRecoveryKey) recoveryConversation.current = { target: remote.liveRecoveryKey, generation: -1 };
  const conversationGeneration = activeState?.conversation_actions?.session_generation;
  if (remote.connectionRecoveryReady && Number.isSafeInteger(conversationGeneration)) recoveryConversation.current.generation = conversationGeneration!;
  const connectionRecoveryKey = remote.liveRecoveryKey && recoveryConversation.current.generation >= 0
    ? JSON.stringify([remote.liveRecoveryKey, recoveryConversation.current.generation]) : '';
  const replyContinuation = React.useRef<ReplyContinuation | null>(null);
  const continuationManifest = React.useRef<AudioChunk[]>([]);
  const continuationTimer = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  React.useEffect(() => () => clearTimeout(continuationTimer.current), []);
  const progressiveSupported = phoneReplyControls && guardedOutput && progressivePcmAvailable()
    && activeState?.features?.progressive_audio_version === 1;
  const progressiveMode = React.useRef({supported:false,enabled:false});
  progressiveMode.current = {supported:progressiveSupported,
    enabled:progressiveSupported && settings.progressiveLiquidAudio === true && !remote.client.avHandle};
  const getPhoneReplyAuth = React.useCallback(async (renew = false) => {
    const auth = await remote.getPhoneReplyAuth(renew, sharedManualQueueAdvertised ? 1 : undefined, continuationAdvertised ? 1 : undefined);
    // Owner mode is frozen by the backend when each new reply registers. The
    // client's cache coalesces callers; existing players never change routes.
    if (progressiveMode.current.supported) {
      let enabled = progressiveMode.current.enabled;
      // Await an in-flight live-track handshake only for an explicit opt-in.
      // Buffered peers resolve null; existing Opus tracks keep their own route.
      if (enabled && remote.client.bufferedPeer) {
        try { enabled = await remote.client.getAVOutput() === null && progressiveMode.current.enabled; }
        catch { enabled = false; }
      }
      await remote.client.setProgressiveAudioMode(auth,enabled);
    }
    return auth;
  }, [remote.getPhoneReplyAuth, remote.client, sharedManualQueueAdvertised, continuationAdvertised]);
  React.useEffect(() => {
    if (!remote.connected || !progressiveSupported) return;
    let active = true;
    void getPhoneReplyAuth().catch(() => {
      if (active) setPhoneReplyError('Progressive audio mode could not be updated. Reconnect before sending.');
    });
    return () => { active = false; };
  }, [remote.connected,progressiveSupported,settings.progressiveLiquidAudio,remote.client.avHandle,getPhoneReplyAuth]);
  type OwnedReply = {
    auth: PhoneReplyAuth; ticket: string | null; sessionId?: string; done: boolean; closed: boolean;
    manualSkipRequested?: boolean; manualSkipAccepted?: boolean; skipOperationId?: string; skipPromise?: Promise<void>;
    manualOrder?: number; phase?: PhoneReplyStatus['phase']; queuedBehindId?: string;
    outputRetired?: boolean; deadline: number; completedObservationDeadline?: number; completionOperationId?: string;
  };
  type PendingReplySubmission = { ticket: string | null; generation: number; deadline: number };
  type RetiredReply = { reply: OwnedReply; operationId: string; confirmed: boolean; waitForBinding?: boolean };
  const backgroundFence = React.useRef({ identity: remote.client.identityKey, credentialOwner: remote.phoneReplyOwner,
    recoveryScope: connectionRecoveryKey,
    continuationLive: false,
    relayRecoveryKey: remote.relayRecoveryKey,
    fence: new BackgroundReplyFence(), replies: new Map<string, OwnedReply>(), pending: new Map<string, PendingReplySubmission>(),
    retirements: new Map<string, RetiredReply>() });
  const outputGeneration = React.useRef(0);
  const retirementSequence = React.useRef(0);
  const keepContinuationOwner = Boolean(connectionRecoveryKey && backgroundFence.current.recoveryScope === connectionRecoveryKey
    && (retainedOrderedConnection || backgroundFence.current.continuationLive || [...backgroundFence.current.replies.values()].some(r => !r.done && r.auth.reply_continuation_version === 1)));
  if (!keepContinuationOwner && (backgroundFence.current.identity !== remote.client.identityKey || backgroundFence.current.credentialOwner !== remote.phoneReplyOwner
    || backgroundFence.current.relayRecoveryKey !== remote.relayRecoveryKey
    || (backgroundFence.current.recoveryScope && backgroundFence.current.recoveryScope !== connectionRecoveryKey))) {
    const previous = backgroundFence.current;
    const retirements = new Map<string, RetiredReply>();
    if (remote.relayRecoveryKey && previous.relayRecoveryKey === remote.relayRecoveryKey) {
      for (const [id, retirement] of previous.retirements) retirements.set(id, retirement);
      for (const [id, reply] of previous.replies) {
        if (!reply.done && reply.auth.shared_queue_version === 1 && !retirements.has(id)) {
          // Keep only the immutable retirement receipt; playback never resumes
          // across a peer replacement. The poll confirms native closure first.
          retirements.set(id, { reply, operationId: `reconnect-${Date.now()}-${++retirementSequence.current}`, confirmed: false, waitForBinding: true });
        }
      }
    }
    backgroundFence.current = { identity: remote.client.identityKey, credentialOwner: remote.phoneReplyOwner,
      recoveryScope: connectionRecoveryKey,
      continuationLive: false,
      relayRecoveryKey: remote.relayRecoveryKey,
      fence: new BackgroundReplyFence(), replies: new Map(), pending: new Map(), retirements };
    outputGeneration.current++;
    replyContinuation.current = null; continuationManifest.current = [];
  }
  if (!backgroundFence.current.recoveryScope) backgroundFence.current.recoveryScope = connectionRecoveryKey;
  const connectionFence = backgroundFence.current;
  const backgroundSession = React.useRef<{ id: string; owner: typeof connectionFence; inputStopped?: boolean; ordered?:boolean } | null>(null);
  const independentCaptureSessions=React.useRef(new Map<string,{id:string;owner:typeof connectionFence;inputStopped?:boolean;ordered?:boolean}>());
  for(const [id,scope] of independentCaptureSessions.current)if(scope.owner!==connectionFence)independentCaptureSessions.current.delete(id);
  const [phoneReplyError, setPhoneReplyError] = React.useState('');
  const routeContext=React.useRef<AudioRouteRecoveryContext|null>(null);
  const routeRecovery=React.useRef<AndroidAudioRouteRecovery|null>(null);
  if(!routeRecovery.current)routeRecovery.current=new AndroidAudioRouteRecovery(()=>routeContext.current!);
  React.useEffect(()=>()=>routeRecovery.current?.cancel(),[foreground,connectionFence,remote.client,remote.connected]);
  const recoverAndroidRoute=(ticket:string|null)=>Platform.OS==='android'&&routeContext.current
    ?routeRecovery.current!.recover(ticket):Promise.resolve(false);
  const backgroundDrainPending = React.useRef(false);
  const [automaticPolicyRevision, setAutomaticPolicyRevision] = React.useState(0);
  const [playbackTicket, setPlaybackTicket] = React.useState<string | null>(null);
  const [orderedRecovery, setOrderedRecovery] = React.useState<{ticket:string|null;epoch:number;paused:boolean}>({ticket:null,epoch:0,paused:false});
  const ticketRef = React.useRef<string | null>(null);
  const ticketPublication = React.useRef<{ ticket: string; resolve: (published: boolean) => void } | null>(null);
  const ticketCommit = React.useRef<Promise<void> | null>(null);
  const foregroundOpening = React.useRef<Promise<void> | null>(null);
  const [liveOutputCompletion, setLiveOutputCompletion] = React.useState(0);
  const liveControl = React.useRef<Promise<void> | null>(null);
  const explicitSequence = React.useRef(0);
  const publishOutput = React.useCallback((ticket: string): Promise<void> => {
    ticketPublication.current?.resolve(false);
    ticketRef.current = ticket;
    const committed = new Promise<boolean>((resolve) => { ticketPublication.current = { ticket, resolve }; });
    setPlaybackTicket(ticket);
    const completion = committed.then((published) => { if (!published) throw new Error('Playback ownership changed. Try again.'); });
    ticketCommit.current = completion;
    const clear = () => { if (ticketCommit.current === completion) ticketCommit.current = null; };
    void completion.then(clear, clear);
    return completion;
  }, []);
  const closePublishedOutput = React.useCallback(() => {
    ticketPublication.current?.resolve(false); ticketPublication.current = null;
    ticketRef.current = null; setPlaybackTicket(null);
  }, []);
  const reviseBackgroundPolicy = () => setAutomaticPolicyRevision(value => value + 1);
  const trackReply = (id: string, auth: PhoneReplyAuth, sessionId?: string) => {
    if (connectionFence !== backgroundFence.current) return;
    if (!connectionFence.replies.has(id)) {
      if (connectionFence.replies.size >= 256) {
        setPhoneReplyError('Reply capacity reached. Stop Live and restart the phone app when ready.');
        void endPhoneReplyOutput().catch(() => undefined); return;
      }
      connectionFence.replies.set(id, { auth, ticket: ticketRef.current, sessionId, done: false, closed: false, deadline: Date.now() + 900_000 });
      // An accepted new reply supersedes an earlier request that never returned its acknowledgement.
      setPhoneReplyError(current => current === PHONE_REPLY_ACK_RECOVERY_EXPIRED ? '' : current);
    }
    reviseBackgroundPolicy();
  };
  const closedReplyExplanation = 'Background Live stopped: automatic replies are closed for this connection because request correlation is missing or a safety limit was reached. Use an updated gateway and restart the phone app before retrying background Live. Explicit Replay and ordinary foreground Live remain available.';
  const consumeBackgroundPolicy = (owner: typeof connectionFence) => {
    reviseBackgroundPolicy();
    if (owner !== backgroundFence.current || owner.fence.automaticBlockReason() !== 'latched-closed') return;
    audioQueue.interrupt();
    if (backgroundSession.current?.owner === owner) void backendRecorder.cancelCapture().catch(() => undefined);
  };
  const sessionVisualStartRef = React.useRef<OptionalVisualStart | null>(null);
  const visualOwnerRef = React.useRef<'session' | 'none'>('none');
  const liveVisualStartRef = React.useRef<OptionalVisualStart | null>(null);
  if (!liveVisualStartRef.current) {
    liveVisualStartRef.current = (chunk, signal, deadline) => {
      const handler = visualOwnerRef.current === 'session' ? sessionVisualStartRef.current : null;
      return handler?.(chunk, signal, deadline);
    };
  }
  const bufferedReplyAuthority = (chunk:AudioChunk) => {
      const reply=chunk.phone_request_id?backgroundFence.current.replies.get(chunk.phone_request_id):null;
      const peer=remote.client.bufferedPeer;
      if(backgroundFence.current!==connectionFence || !reply || reply.closed || reply.done || !reply.ticket
        || reply.ticket!==ticketRef.current || reply.deadline<=Date.now() || !peer?.cacheScope)return null;
      return {scope:{owner:peer.cacheScope,replyId:chunk.phone_request_id!,expiresAt:reply.deadline},auth:reply.auth,ticket:reply.ticket};
    };
  const muxedCandidate = selectMuxedPlayback({platform:Platform.OS,connected:orderedConnectionAvailable,
    museTalk:String(runtime?.avatar_engine||'').trim().toLowerCase().includes('musetalk'),
    backendHq:settings.audioMode==='backend_hq',demo:demoMode,story:storyActive,nativeSpeech:nativePlayback,cacheMode:'off'});
  const muxedCachePolicy=useMuxedCachePolicy(remote.client,connectionFence,orderedConnectionAvailable&&Platform.OS==='android');
  const orderedIdleStorage=useOrderedIdleStorage(remote.client.bufferedPeer?.cacheScope||orderedConnectionScope.current.scope,connectionFence,
    orderedConnectionAvailable&&Platform.OS==='android',muxedCachePolicy);
  const muxedTrialSelected=muxedCandidate&&muxedCachePolicy.mode!=='unknown';
  const orderedBackground=React.useRef<{ticket:string|null;owner:object;ready:boolean}|null>(null);
  const retainsOrderedBackground=()=>orderedBackground.current?.ready===true
    &&orderedBackground.current.ticket===ticketRef.current&&orderedBackground.current.owner===connectionFence;
  const muxedRouteBlocked=muxedCandidate;
  const muxedTrialEligible=muxedTrialSelected&&guardedOutput&&phoneReplyControls&&musetalkAvailable
    &&(foreground||Boolean(backgroundSession.current)||retainsOrderedBackground())
    &&!(orderedRecovery.ticket===playbackTicket&&orderedRecovery.paused);
  const bufferedPlayback = useBufferedPlayback({client:remote.client,owner:connectionFence,ticket:playbackTicket,
    enabled:!muxedRouteBlocked && !demoMode && !storyActive && settings.audioMode==='backend_hq' && guardedOutput && phoneReplyControls,
    chunks:backendChunks,reply:bufferedReplyAuthority});
  const soundscapeOnsetRef = React.useRef<(id:string)=>void>(()=>undefined);
  const soundscapeStopEffectRef = React.useRef<()=>void>(()=>undefined);
  const ordinaryAudioQueue = useAudioQueue(remote.client, audioChunks, {
    bufferedAudio:muxedTrialSelected ? undefined : muxedRouteBlocked ? muxedTrialBlockedAudio : bufferedPlayback.runtime?.audio,
    initialSnapshot: nativePlayback || demoMode ? undefined : backendHistory,
    sourceKey: playbackSource,
    continuationScopeKey: nativeContinuationSupported ? connectionRecoveryKey : undefined,
    resolveOwnedAudio: nativePlayback ? nativeSpeech.resolveOwnedAudio : undefined,
    getReplyAuth: nativePlayback || demoMode ? undefined : chunk => {
      const reply = chunk.phone_request_id ? backgroundFence.current.replies.get(chunk.phone_request_id) : null;
      return reply && !reply.closed && !reply.done && reply.ticket === ticketRef.current ? reply.auth : null;
    },
    onChunkFinished: nativePlayback ? nativeSpeech.playbackFinished : bufferedPlayback.runtime?.finished,
    onAssistantPlaybackStarted: id=>soundscapeOnsetRef.current(id),
    autoplayEnabled: !muxedRouteBlocked&&settings.phoneTtsAutoplay,
    volume: settings.phoneTtsVolume,
    narrationPace: settings.phoneNarrationPace,
    onAutoplayEnabledChange: (phoneTtsAutoplay) => setSettings({ phoneTtsAutoplay }),
    onBeforePlayback: () => pauseLiveForPlaybackRef.current(),
    onBeforeAutomaticVisualStart: muxedRouteBlocked ? undefined : (chunk, signal, deadline) => liveVisualStartRef.current?.(chunk, signal, deadline),
    automaticVisualStartBudgetMs: () => visualOwnerRef.current === 'none' ? 1000 : Infinity,
    playbackTicket,
    requirePlaybackTicket: guardedOutput,
    phoneReplyControls,
    manualContinuationEnabled: continuationAdvertised && !backgroundSession.current && !demoMode && !storyActive,
    transportConnected: remote.connected,
    ownedReplyIds: [...connectionFence.replies].filter(([, reply]) => !reply.done && !reply.closed).map(([id]) => id),
    nativeAdmittedReplyIds: [...connectionFence.replies].filter(([, reply]) => Boolean(reply.sessionId)).map(([id]) => id),
    canRecoverTransportLoss: () => Boolean(backgroundSession.current
      && !backgroundSession.current.inputStopped && remote.liveRecoveryKey
      && backgroundSession.current.owner === backgroundFence.current),
    onReplyFailure: reason => {
      void recordPhoneDebug('error', 'live_stop_requested', { initiator: 'audio_queue', reason,
        pending_count: connectionFence.pending.size, reply_count: connectionFence.replies.size }).catch(() => undefined);
      setPhoneReplyError(reason.includes('capacity')
        ? 'The reply queue reached its limit. Stop Live, then start it again.'
        : reason === 'player_binding_rejected'
          ? 'Audio permission for this reply ended. Reconnect, then retry the reply.'
          : 'Reply audio was interrupted. Reconnect, then use Retry in the conversation.');
      void endPhoneReplyOutput().catch(() => undefined);
    },
    onCharacterPreviewError: message => Alert.alert('Voice preview unavailable', message),
    automaticPolicyRevision,
    allowAutomaticChunk: chunk => !muxedRouteBlocked&&(!phoneReplyControls || (Boolean(chunk.phone_request_id)
      && backgroundFence.current.replies.has(chunk.phone_request_id!)))
      && backgroundFence.current.fence.allowsAutomatic(chunk.phone_request_id),
  });
  const muxedPlayback=useDesktopOrderedAudioQueue({client:remote.client,owner:connectionFence,ticket:playbackTicket,
    onAssistantPlaybackStarted:id=>soundscapeOnsetRef.current(id),
    continuationKey:orderedContinuationSupported?connectionRecoveryKey:undefined,
    transportReady:remote.connected&&!!remote.client.bufferedPeer&&!remote.client.bufferedPeer.closed,
    freshState:remote.connectionRecoveryReady,transportRevision:remote.transportFailureRevision,
    recoveryProfile:remote.orderedRecoveryProfile,
    onBackgroundReady:ready=>{orderedBackground.current={ticket:playbackTicket,owner:connectionFence,ready};},
    selected:muxedTrialSelected,enabled:muxedTrialEligible,getAuth:getPhoneReplyAuth,reply:bufferedReplyAuthority,
    idleCache:orderedIdleStorage,
    ordinary:ordinaryAudioQueue,autoplay:settings.phoneTtsAutoplay,volume:settings.phoneTtsVolume,
    recoveryEpoch:orderedRecovery.ticket===playbackTicket?orderedRecovery.epoch:0,
    nativeAdmitted:id=>Boolean(connectionFence.replies.get(id)?.sessionId),
    beforeSpeech:()=>pauseLiveForPlaybackRef.current(),
    onInterruption:receipt=>{soundscapeStopEffectRef.current();void onsetPhoneReply(receipt).catch(()=>{
      setPhoneReplyError('Phone interruption could not be accepted. Context was preserved.');
    });},
    onAutoplayChanged:phoneTtsAutoplay=>setSettings({phoneTtsAutoplay}),requestStop:requestPhoneReplyStop,
    onRecovering:error=>{
      void recordPhoneDebug('warning','ordered_output_failed',{
        ...orderedFailureDetails(error),recovery:(error as Error)?.message==='phone_reply_authentication'
          ?'private_credential_renewal':'exact_cold_retirement',attempt:1}).catch(()=>undefined);
      setPhoneReplyError('Reconnecting playback…');
    },
    onFailure:error=>{
      const details=orderedFailureDetails(error),{reason}=details;
      void recordPhoneDebug('error','ordered_output_failed',details).catch(()=>undefined);
      if(!remote.connected||remote.client.bufferedPeer?.closed){
        // The ordered runtime already fences and joins its old generation.
        // Keep the existing supervisor ticket for authenticated reconnect;
        // revoking it here would also kill the protected microphone lifetime.
        setPhoneReplyError('Reconnecting playback…');return;
      }
      void recoverAndroidRoute(playbackTicket).catch(()=>false).then(handled=>{
        if(handled||connectionFence!==backgroundFence.current||playbackTicket!==ticketRef.current)return;
        setPhoneReplyError(orderedPlaybackErrorMessage(reason));void endPhoneReplyOutput().catch(()=>undefined);
      });
    }});
  const audioQueue=muxedPlayback.playback;
  // Queue options have now been rendered. Explicit Replay must await this commit
  // boundary before playNow captures its ticket (setState alone is not a flush).
  React.useEffect(() => {
    const publication = ticketPublication.current;
    if (publication && publication.ticket === playbackTicket && ticketRef.current === playbackTicket) {
      ticketPublication.current = null; publication.resolve(true);
    }
  }, [playbackTicket]);
  React.useEffect(() => {
    if (!foreground) {
      // Native retires foreground-only authority on app backgrounding. Never
      // offer its old ticket to a fresh player when the app returns.
      if (guardedOutput && !backgroundSession.current && !retainsOrderedBackground()
        && !(Platform.OS === 'android' && (replyPlaybackNeeded || continuousServiceNeeded || notificationActionPending))) closePublishedOutput();
      return;
    }
    let alive = true;
    let openedTicket: string | null = null;
    const generation = outputGeneration.current;
    if (guardedOutput && foregroundRef.current) {
      const opening = (async () => {
        const state = await capture.outputState();
        if (!alive || !foregroundRef.current || generation !== outputGeneration.current || state.open || state.sessionId !== null) return;
        // Retirement keeps the predecessor identity for native compare-and-open.
        // Never replace an open or protected owner during automatic recovery.
        const ticket = await capture.beginForegroundOutput(state.ticket);
        if (!alive || !foregroundRef.current || generation !== outputGeneration.current) { await capture.retireOutput(ticket); return; }
        openedTicket = ticket;
        await publishOutput(ticket);
      })();
      foregroundOpening.current = opening;
      void opening.catch(() => undefined).finally(() => { if (foregroundOpening.current === opening) foregroundOpening.current = null; });
    }
    return () => {
      alive = false;
      if (openedTicket && ticketPublication.current?.ticket === openedTicket) {
        ticketPublication.current.resolve(false); ticketPublication.current = null;
      }
    };
    // Reset Chat advances the conversation fence while the app stays in front.
    // Its old output has been retired; the new session needs its own opening.
  }, [foreground, capture, guardedOutput, publishOutput, closePublishedOutput, connectionFence, liveOutputCompletion]);
  React.useEffect(()=>{
    if(!muxedTrialSelected)return;
    void recordPhoneDebug('info','muxed_selection_gate',{
      enabled:muxedTrialEligible,guard_available:guardedOutput,reply_controls_available:phoneReplyControls,
      avatar_available:musetalkAvailable,foreground,background_session_present:Boolean(backgroundSession.current),
      output_available:Boolean(playbackTicket),
    }).catch(()=>undefined);
  },[muxedTrialSelected,muxedTrialEligible,guardedOutput,phoneReplyControls,musetalkAvailable,foreground,playbackTicket]);
  React.useEffect(()=>{
    if(!muxedCachePolicy.error&&muxedCachePolicy.mode!=='unknown')
      setPhoneReplyError(current=>current==='Idle-cache policy unavailable.'?'':current);
    if(muxedCandidate&&muxedCachePolicy.error)setPhoneReplyError(muxedCachePolicy.error);
    else if(muxedTrialSelected&&(!guardedOutput||!phoneReplyControls||!musetalkAvailable
      ||muxedTrialEligible&&playbackTicket&&!muxedPlayback.available))
      setPhoneReplyError('ordered.native_capability_unavailable');
    else if(muxedTrialEligible&&playbackTicket&&muxedPlayback.session)
      setPhoneReplyError(current=>current==='ordered.native_capability_unavailable'
        ||(current==='ordered.transport_disconnected'||current==='Reconnecting playback…')&&muxedPlayback.phase==='idle'?'':current);
  },[muxedCandidate,muxedCachePolicy.error,muxedCachePolicy.mode,muxedTrialSelected,muxedTrialEligible,guardedOutput,phoneReplyControls,musetalkAvailable,
    playbackTicket,muxedPlayback.session,muxedPlayback.phase,muxedPlayback.available]);
  releasePlaybackRef.current = audioQueue.interrupt;
  const interruptLiveResponse = () => {
    if (connectionFence !== backgroundFence.current) return Promise.resolve();
    if(muxedTrialSelected){const id=audioQueue.activeReplyId;if(id)audioQueue.skipReply(id);}
    else audioQueue.interrupt();
    if (!guardedOutput) return remote.sendControl('interrupt_response', sendOptions);
    // Coalesce controls instead of building a backlog. The next Start drains
    // this request, including WebSocket-to-HTTP fallback, outside the audio lock.
    if (liveControl.current) return liveControl.current;
    const operation = remote.sendControl('interrupt_response', sendOptions).catch(() => undefined);
    liveControl.current = operation;
    void operation.finally(() => { if (liveControl.current === operation) liveControl.current = null; });
    return operation;
  };
  const livePauseReason = liveMicPauseReason({
    connected: remote.connected && !demoMode,
    voiceAvailable: phoneSttAvailable && !demoMode,
    phonePlaying: Boolean(audioQueue.playingId),
    backendStatus: String(activeState?.status_line || ''),
  });
  const phonePlaybackActive = Boolean(
    audioQueue.playingId
    || audioQueue.isPlaying
    || audioQueue.currentChunk
    || audioQueue.preparedChunk
  );
  const characterPreviewId = audioQueue.currentChunk?.id.startsWith('character-preview-')
    ? audioQueue.currentChunk.id.slice('character-preview-'.length) : '';
  // Short library previews are ordinary foreground audio, not protected replies.
  // Counting them here starts LiveAudioService and can race its immediate teardown.
  const phoneReplyAudioActive = Boolean(
    audioQueue.currentChunk?.phone_request_id || audioQueue.preparedChunk?.phone_request_id
  );
  const speakingChunk = audioQueue.currentChunk
    && (audioQueue.isPlaying || audioQueue.playingId === audioQueue.currentChunk.id)
    ? audioQueue.currentChunk : null;
  const headerCharacter = activeCharacterSpeaker(Boolean(characters.snapshot?.character_voices_enabled),
    speakingChunk?.speaker, (characters.snapshot?.characters ?? []).filter(
      card => card.conversation_id === characters.snapshot?.conversation_id));
  const onsetPhoneReply = async (receipt?: PhoneReplyReceipt) => {
    if (!receipt || connectionFence !== backgroundFence.current) return;
    const owned = connectionFence.replies.get(receipt.phone_request_id);
    if (!owned) { setPhoneReplyError('Phone reply receipt ownership unavailable.'); return; }
    owned.closed = true; connectionFence.fence.closeReply(receipt.phone_request_id);
    audioQueue.skipReply(receipt.phone_request_id); reviseBackgroundPolicy();
    const result = await retryPhoneReply(() => remote.client.sendPhoneReplyAction(owned.auth, { kind: 'onset', receipt }),
      () => backgroundFence.current === connectionFence && connectionFence.replies.get(receipt.phone_request_id) === owned);
    if (backgroundFence.current !== connectionFence) return;
    if (!['accepted', 'duplicate'].includes(result.status)) setPhoneReplyError('Phone interruption could not be accepted. Context was preserved.');
  };
  const skipOwnedReply = (id: string): Promise<void> => {
    const owned = connectionFence.replies.get(id);
    const current = () => phoneReplyControls && connectionFence === backgroundFence.current
      && connectionFence.replies.get(id) === owned && owned?.ticket === ticketRef.current && !owned?.outputRetired;
    if (!owned || !current()) return Promise.reject(new Error('The conversation changed. Try again.'));
    if (owned.skipPromise) return owned.skipPromise;
    if (owned.manualSkipAccepted || owned.done) return Promise.resolve();
    owned.manualSkipRequested = true;
    audioQueue.skipReply(id); owned.closed = true; connectionFence.fence.closeReply(id); reviseBackgroundPolicy();
    const action = { kind: 'skip' as const, phone_request_id: id,
      operation_id: owned.skipOperationId ??= `skip-${Date.now()}-${++explicitSequence.current}` };
    // Retrying an uncertain acknowledgement must reuse the original operation.
    owned.skipPromise = Promise.resolve().then(async () => {
      if (!current()) throw new Error('The conversation changed. Try again.');
      const result = await retryPhoneReply(() => remote.client.sendPhoneReplyAction(owned.auth, action), current);
      if (!current()) throw new Error('The conversation changed. Try again.');
      if (!['accepted', 'duplicate'].includes(result.status)) throw new Error('Stop speech was not acknowledged. Tap again to retry. Audio remains stopped locally.');
      owned.manualSkipAccepted = true; reviseBackgroundPolicy();
    }).finally(() => { owned.skipPromise = undefined; });
    return owned.skipPromise;
  };
  const stoppableReplyId = (() => {
    const id = audioQueue.activeReplyId, owned = id ? connectionFence.replies.get(id) : undefined;
    if (!id || !owned || owned.done || owned.manualSkipAccepted) return null;
    const hasMedia = audioQueue.currentChunk?.phone_request_id === id || audioQueue.preparedChunk?.phone_request_id === id;
    // activeReplyId also falls back to owned receipts. A pending receipt has no
    // output yet: suppressing it here would silently kill the user's NEXT reply.
    if (owned.auth.shared_queue_version === 1 && !hasMedia
      && owned.phase !== 'generating' && owned.phase !== 'complete') return null;
    return id;
  })();
  const stopSpeech = () => {
    if(routeRecovery.current?.pending)void backendRecorder.cancelCapture().catch(()=>undefined);
    routeRecovery.current?.cancel();
    if (!phoneReplyControls || connectionFence !== backgroundFence.current) return;
    void soundscape.playback?.pause().catch(()=>undefined);
    if (audioQueue.stopExplicitPlayback) { audioQueue.stopExplicitPlayback(); return; }
    const id = stoppableReplyId;
    if (!id) return;
    const owned = connectionFence.replies.get(id);
    if (!owned) return;
    void requestPhoneReplyStop(id).catch(()=>{if(connectionFence===backgroundFence.current)
      setPhoneReplyError('Stop speech acknowledgement unavailable. Audio remains stopped locally.');});
  };
  async function requestPhoneReplyStop(id:string) {
    if(!phoneReplyControls||connectionFence!==backgroundFence.current)return;
    const owned=connectionFence.replies.get(id);if(!owned||owned.done)return;
    owned.manualSkipRequested = true;
    audioQueue.skipReply(id); owned.closed = true; connectionFence.fence.closeReply(id); reviseBackgroundPolicy();
    const action = { kind: 'skip' as const, phone_request_id: id, operation_id: `skip-${Date.now()}-${++explicitSequence.current}` };
    await retryPhoneReply(() => remote.client.sendPhoneReplyAction(owned.auth, action),
      () => backgroundFence.current === connectionFence && connectionFence.replies.get(id) === owned).then(result => {
        if (connectionFence === backgroundFence.current && !['accepted', 'duplicate'].includes(result.status)) setPhoneReplyError('Stop speech could not be acknowledged. Audio remains stopped locally.');
        if (connectionFence === backgroundFence.current && connectionFence.replies.get(id) === owned && ['accepted', 'duplicate'].includes(result.status)) {
          owned.manualSkipAccepted = true; reviseBackgroundPolicy();
        }
      });
  }
  const canStopSpeech = phoneReplyControls && (Boolean(audioQueue.stopExplicitPlayback) || Boolean(stoppableReplyId));
  const backendRecorder = useBackendRecorder(remote.client, remote.connected && !demoMode && !nativePlayback && conversationActionBusy !== 'reset_chat', phoneSttAvailable && !demoMode && !nativePlayback, {
    manualScope:connectionFence,
    prepareTranscriptSubmission: permit => photoVoiceSubmissionRef.current(permit),
    connectionRecoveryKey: !demoMode && !nativePlayback && !storyActive ? connectionRecoveryKey : '',
    connectionRecoveryReady: remote.connectionRecoveryReady === true,
    onReplyContinuationPaused: muxedRouteBlocked||backgroundSession.current?.ordered?undefined:(checkpoint, pendingAdmissions) => {
      const session = backgroundSession.current;
      if (!session || session.owner !== backgroundFence.current || !ticketRef.current) throw new Error('Reply recovery ownership changed.');
      const owner = session.owner;
      const replies = checkpoint.replies.map(r => {
        // Native admission may commit before its JS promise resolves. Only
        // checkpoint-proven IDs may recover that pending receipt's authority.
        const pending = pendingAdmissions?.get(r.requestId);
        if (!owner.replies.has(r.requestId) && pending?.auth.reply_continuation_version === 1) {
          owner.fence.settleUpload(session.id, pending.uploadId, r.requestId);
          trackReply(r.requestId, pending.auth, session.id);
        }
        const owned = owner.replies.get(r.requestId);
        if (!owned || owned.auth.reply_continuation_version !== 1) throw new Error('Reply continuation unavailable.');
        return { requestId:r.requestId, auth:owned.auth };
      });
      replyContinuation.current = createReplyContinuation(connectionRecoveryKey, session.id, ticketRef.current, checkpoint,
        replies, performance.now(), replyContinuation.current);
      const record = replyContinuation.current;
      clearTimeout(continuationTimer.current);
      continuationTimer.current = setTimeout(() => {
        if (replyContinuation.current !== record) return;
        setPhoneReplyError('Interrupted reply recovery expired. Start Live again when ready.');
        void replyPoll.current.endPhoneReplyOutput().catch(() => undefined);
      }, Math.max(0, record.deadlineMs - performance.now()));
      outputGeneration.current++;
      owner.fence.suspend(session.id); owner.pending.clear();
      audioQueue.suspendReplyPlayback(checkpoint); reviseBackgroundPolicy();
    },
    onReplyContinuationValidate: muxedRouteBlocked||backgroundSession.current?.ordered?undefined:async checkpoint => {
      const record = replyContinuation.current;
      const current = () => record && replyContinuation.current === record
        && continuationIsCurrent(record, connectionRecoveryKey, checkpoint.recoveryEpoch, performance.now())
        && backgroundSession.current?.id === record.sessionId && ticketRef.current === record.ticket
        && connectionFence === backgroundFence.current;
      if (!current() || !record) throw new Error('Reply recovery expired or changed.');
      const manifest: AudioChunk[] = [], retained: string[] = [];
      for (const reply of record.replies) {
        const owned = connectionFence.replies.get(reply.requestId);
        if (!owned || owned.closed || owned.done) continue;
        let cursor: number | null = 0;
        do {
          const status = await remote.client.getPhoneReplyContinuation(reply.auth, reply.requestId, cursor, -1);
          if (!current()) throw new Error('Reply recovery changed.');
          if (owned.closed || owned.done) break;
          if (status.phase === 'cancelled' || status.phase === 'superseded' || status.playback_stop_requested || !status.continuation.available)
            throw new Error('The interrupted reply is no longer available.');
          manifest.push(...status.continuation.items);
          cursor = status.continuation.next_cursor;
        } while (cursor !== null);
        if (!owned.closed && !owned.done) retained.push(reply.requestId);
      }
      continuationManifest.current = manifest;
      return retained;
    },
    onReplyContinuationRestored: muxedRouteBlocked||backgroundSession.current?.ordered?undefined:async checkpoint => {
      const record = replyContinuation.current;
      if (!record || !continuationIsCurrent(record, connectionRecoveryKey, checkpoint.recoveryEpoch, performance.now())
        || connectionFence !== backgroundFence.current || ticketRef.current !== record.ticket) throw new Error('Reply recovery changed.');
      const ids = record.replies.filter(r => { const owned = connectionFence.replies.get(r.requestId); return owned && !owned.closed && !owned.done; }).map(r => r.requestId);
      if (!connectionFence.fence.resume(record.sessionId, ids)) throw new Error('Reply recovery cancelled.');
      // Preserve the exact checkpoint object used to seal the queue; skipped
      // members cancel this attempt instead of regaining admission.
      if (!await audioQueue.restoreReplyPlayback(checkpoint, continuationManifest.current, checkpoint.recoveryEpoch)) throw new Error('Reply playback could not resume.');
      if (ids.length === 0 && replyContinuation.current === record) {
        clearTimeout(continuationTimer.current);
        replyContinuation.current = null;
      }
      setPhoneReplyError(''); reviseBackgroundPolicy();
    },
    onConnectionReplyRetired: (id, ticket, requestId, auth) => {
      if (connectionFence !== backgroundFence.current || backgroundSession.current?.id !== id || ticketRef.current !== ticket
        || auth.shared_queue_version !== 1 || connectionFence.retirements.has(requestId)) return;
      // Only an immutable receipt for suppressed output; never playback admission.
      connectionFence.retirements.set(requestId, {
        reply: { auth, ticket, sessionId: id, done: false, closed: true, outputRetired: true, deadline: Date.now() + 900_000 },
        operationId: `reconnect-${Date.now()}-${++retirementSequence.current}`, confirmed: true, waitForBinding: true,
      });
      reviseBackgroundPolicy();
    },
    onConnectionPaused: (id, ticket) => {
      const ordered=backgroundSession.current?.id===id&&backgroundSession.current.ordered;
      if(ordered)setOrderedRecovery(previous=>({ticket,epoch:previous.ticket===ticket?previous.epoch:0,paused:true}));
      // Native has already blocked and invalidated old players/admissions. Keep
      // the capture ticket alive while reconciling old backend reply receipts.
      const owner = backgroundSession.current?.id === id ? backgroundSession.current.owner : connectionFence;
      outputGeneration.current++;
      for (const [requestId, reply] of owner.replies) {
        if(!ordered)audioQueue.skipReply(requestId); owner.fence.closeReply(requestId);
        if (!reply.done && reply.auth.shared_queue_version === 1) backgroundFence.current.retirements.set(requestId, {
          reply, operationId: `reconnect-${Date.now()}-${++retirementSequence.current}`, confirmed: true, waitForBinding: true,
        });
      }
      for (const uploadId of owner.fence.tailPermit(id).pendingUploadIds) owner.fence.abandonUpload(id, uploadId);
      owner.replies.clear(); owner.pending.clear();
      for (const retired of backgroundFence.current.retirements.values()) {
        if (retired.reply.ticket === ticket) retired.confirmed = true;
      }
      audioQueue.interrupt(); reviseBackgroundPolicy();
    },
    onConnectionRestored: (id, ticket, recoveryEpoch) => {
      if (connectionFence !== backgroundFence.current || backgroundSession.current?.id !== id || ticketRef.current !== ticket) {
        throw new Error('Live recovery ownership changed.');
      }
      // Retired receipts never become playback-authorized again, even though
      // the native microphone lifetime and its Stop controls are retained.
      for (const retired of connectionFence.retirements.values()) if (retired.reply.ticket === ticket) retired.confirmed = true;
      connectionFence.replies.clear(); connectionFence.pending.clear(); connectionFence.fence.begin(id);
      const ordered=backgroundSession.current.ordered;
      backgroundSession.current = { id, owner: connectionFence, ordered }; backgroundDrainPending.current = false;
      if(ordered){
        if(!Number.isSafeInteger(recoveryEpoch)||recoveryEpoch!<1)throw Error('ordered.recovery_epoch_missing');
        setOrderedRecovery({ticket,epoch:recoveryEpoch!,paused:false});
      }
      outputGeneration.current++; setPhoneReplyError(''); reviseBackgroundPolicy();
    },
    phoneReplyControls,
    getPhoneReplyAuth,
    onPhoneReplyOnset: onsetPhoneReply,
    getPhoneReplyReceiptAuth: (id, ticket, receipt) => {
      const session = backgroundSession.current;
      const owned = connectionFence.replies.get(receipt.phone_request_id);
      if (connectionFence !== backgroundFence.current || session?.owner !== connectionFence || session.id !== id
        || session.inputStopped || !ticket || ticketRef.current !== ticket || !owned
        || (owned.sessionId !== id && !(Platform.OS==='android'&&independentCaptureSessions.current.get(id)?.owner===connectionFence))
        || owned.ticket !== ticket || owned.outputRetired) return undefined;
      // Onset closes playback before the utterance upload completes. A closed
      // reply still owns that interruption; the gateway validates its receipt.
      return owned.auth;
    },
    onPhoneReplyAbandon: async receipt => {
      const owned = connectionFence.replies.get(receipt.phone_request_id);
      if (!owned || connectionFence !== backgroundFence.current) return;
      const action = { kind: 'abandon' as const, phone_request_id: receipt.phone_request_id, interruption_id: receipt.interruption_id };
      await retryPhoneReply(() => remote.client.sendPhoneReplyAction(owned.auth, action), () => backgroundFence.current === connectionFence && connectionFence.replies.get(receipt.phone_request_id) === owned);
    },
    freezePhoneReply: () => audioQueue.freezeReply(`onset-${Date.now()}-${++explicitSequence.current}`),
    onPhoneReplySubmitted: (id, auth) => trackReply(id, auth),
    beginPhoneReplySubmission: () => beginForegroundSubmission(explicitActionContext),
    getReplyTailPermit: id => connectionFence.fence.tailPermit(id),
    onBeforeReplyOutputFinish: async (id, ticket) => {
      if(Platform.OS==='android'&&independentCaptureSessions.current.get(id)?.owner===connectionFence)return;
      const matches = () => backgroundSession.current?.id === id
        && backgroundSession.current.owner === connectionFence
        && backgroundFence.current === connectionFence && ticketRef.current === ticket;
      if (!matches()) throw new Error('ordered.live_tail_owner_changed');
      if (backgroundSession.current?.ordered) await replyPoll.current.muxedPlayback.close();
      if (!matches()) throw new Error('ordered.live_tail_owner_changed');
    },
    onBackgroundListeningStopped: id => {
      if (backgroundSession.current?.id !== id || backgroundSession.current.owner !== connectionFence) return;
      connectionFence.fence.stopListening(id); backgroundSession.current.inputStopped = true; reviseBackgroundPolicy();
      if(Platform.OS==='android')backgroundSession.current=null;
    },
    onBackgroundOutputFinished: id => {
      if(Platform.OS==='android'){
        const scope=independentCaptureSessions.current.get(id);
        if(scope?.owner!==connectionFence)return;
        connectionFence.fence.finishListening(id);independentCaptureSessions.current.delete(id);
        if(backgroundSession.current===scope)backgroundSession.current=null;
        reviseBackgroundPolicy();return;
      }
      if (backgroundSession.current?.id !== id || backgroundSession.current.owner !== connectionFence) return;
      retainStoppedReplies(id);
      // A frozen receipt may still be retrying after its native audio lifetime
      // ends. Retain it without letting its later status release a new ticket.
      for (const reply of connectionFence.replies.values()) if (reply.sessionId === id) reply.outputRetired = true;
      connectionFence.fence.finishListening(id); backgroundSession.current = null;
      outputGeneration.current++; closePublishedOutput(); reviseBackgroundPolicy();
      // Successful Live tail closure is not a playback error. Reuse the guarded
      // foreground opening to restore idle without starting the microphone.
      setLiveOutputCompletion(value => value + 1);
    },
    onBackgroundUploadAbandoned: (id, uploadId) => { connectionFence.fence.abandonUpload(id, uploadId); reviseBackgroundPolicy(); },
    allowBackgroundLive: settings.allowBackgroundLive && !storyActive && activeTab !== 'story' && activeTab !== 'visual',
    transportFailureRevision: remote.transportFailureRevision,
    orderedPlaybackPeer:muxedTrialSelected&&orderedConnectionAvailable?remote.client.bufferedPeer:null,
    orderedContinuationKey:muxedTrialSelected&&orderedContinuationSupported?connectionRecoveryKey:undefined,
    onBeforeLiveStart: async kind => {
      // Android Live only enables listening; actual speech onset owns interruption.
      // Manual recording and the existing iOS policy still stop the current reply.
      if (Platform.OS !== 'android' || kind !== 'live') await muxedPlayback.beforeCapture();
      await liveControl.current;
      await foregroundOpening.current;
      // Both Live and manual callers have already drained the preceding capture.
      await ensureForegroundOutput(false);
    },
    getPlaybackTicketForCapture:async()=>{
      await ensureForegroundOutput(false);
      const state=await capture.outputState();
      if(connectionFence!==backgroundFence.current||!state.open||state.sessionId!==null||!state.ticket||state.ticket!==ticketRef.current)
        throw new Error('Live capture playback owner unavailable.');
      return state.ticket;
    },
    onAudioRouteFailure:ticket=>recoverAndroidRoute(ticket),
    confirmBluetoothHeadphones: () => new Promise<boolean>((resolve) => {
      if (!foregroundRef.current) { resolve(false); return; }
      Alert.alert('Bluetooth headphones?', 'Confirm this Bluetooth device is headphones you are wearing, rather than a speaker or car audio.', [
        { text: 'Cancel', style: 'cancel', onPress: () => resolve(false) },
        { text: 'I’m wearing headphones', onPress: () => resolve(foregroundRef.current) },
      ], { cancelable: true, onDismiss: () => resolve(false) });
    }),
    onBackgroundSessionStart: id => {
      if (connectionFence !== backgroundFence.current) throw new Error('The conversation changed. Try again.');
      if (connectionFence.fence.automaticBlockReason() === 'latched-closed') throw new Error(closedReplyExplanation);
      backgroundDrainPending.current = false;
      connectionFence.continuationLive = continuationAdvertised;
      if(Platform.OS==='android'){
        if(independentCaptureSessions.current.size>=256)throw new Error('Capture session capacity reached.');
        const scope={id,owner:connectionFence,ordered:muxedTrialSelected};
        independentCaptureSessions.current.set(id,scope);backgroundSession.current=scope;
        connectionFence.fence.begin(id,true);consumeBackgroundPolicy(connectionFence);return;
      }
      for (const requestId of connectionFence.replies.keys()) {
        audioQueue.skipReply(requestId); connectionFence.fence.closeReply(requestId);
      }
      connectionFence.replies.clear(); connectionFence.pending.clear();
      outputGeneration.current++;
      backgroundSession.current = { id, owner: connectionFence, ordered:muxedTrialSelected };
      connectionFence.fence.begin(id); audioQueue.interrupt(); consumeBackgroundPolicy(connectionFence);
      if (connectionFence.fence.automaticBlockReason() === 'latched-closed') throw new Error(closedReplyExplanation);
    },
    onBackgroundOutputTicket: (id, ticket) => {
      if (backgroundSession.current?.id !== id || backgroundFence.current !== connectionFence) return;
      if(Platform.OS==='android'){
        if(ticketRef.current!==ticket)throw new Error('Live capture playback owner changed.');
        return;
      }
      void publishOutput(ticket).catch(() => undefined);
    },
    onBackgroundUpload: (id, uploadId) => { connectionFence.fence.beginUpload(id, uploadId); consumeBackgroundPolicy(connectionFence); },
    onBackgroundUploadSettled: (id, uploadId, requestId, auth) => {
      connectionFence.fence.settleUpload(id, uploadId, requestId); consumeBackgroundPolicy(connectionFence);
      if (requestId && auth && ((backgroundSession.current?.id === id && backgroundSession.current.owner === connectionFence)
        ||(Platform.OS==='android'&&independentCaptureSessions.current.get(id)?.owner===connectionFence))) trackReply(requestId, auth, id);
    },
    onBackgroundSessionStop: id => {
      if(Platform.OS==='android'){
        const scope=independentCaptureSessions.current.get(id);
        if(scope?.owner!==connectionFence)return;
        // Input failure/cleanup is not a playback cancellation. Accepted work
        // keeps its admission record until native reply settlement.
        connectionFence.fence.stopListening(id);scope.inputStopped=true;
        if(backgroundSession.current===scope)backgroundSession.current=null;
        reviseBackgroundPolicy();return;
      }
      connectionFence.continuationLive = false;
      clearTimeout(continuationTimer.current); replyContinuation.current = null;
      const retainedSharedReply = retainStoppedReplies(id)
        || [...connectionFence.retirements.values()].some(retired => retired.reply.sessionId === id);
      connectionFence.fence.cancel(id); reviseBackgroundPolicy();
      if (phoneReplyControls) for (const uploadId of connectionFence.fence.tailPermit(id).pendingUploadIds) connectionFence.fence.abandonUpload(id, uploadId);
      for (const [requestId, reply] of connectionFence.replies) if (reply.sessionId === id) {
        audioQueue.skipReply(requestId); connectionFence.replies.delete(requestId);
      }
      if (backgroundSession.current?.id !== id) return;
      backgroundDrainPending.current = true;
      backgroundSession.current = null; outputGeneration.current++;
      closePublishedOutput(); audioQueue.interrupt();
      if (backgroundFence.current === connectionFence && !retainedSharedReply) void interruptLiveResponse();
    },
    liveDuckingLevel: Platform.OS === 'android' || settings.liveDuckingUseSystemDefault ? 'default' : settings.liveDuckingLevel,
    liveMicSensitivity: settings.liveMicSensitivity,
    sendToChat: settings.micBehavior === 'send_auto',
    sendOptions: storyActive ? { ...sendOptions, audioMode: 'backend_hq' } : sendOptions,
    livePauseReason,
    playbackActive: phonePlaybackActive,
    onLiveSpeechStart: interruptLiveResponse,
  });
  function retainStoppedReplies(sessionId?: string) {
    // Terminal playback/capture cleanup can close output without a Live-off
    // tail. Retain exact cancellation receipts before clearing playback state;
    // the poll confirms native retirement before acknowledging them to the PC.
    let retained = false;
    for (const [id, reply] of connectionFence.replies) {
      if ((sessionId !== undefined && reply.sessionId !== sessionId) || reply.done || reply.auth.shared_queue_version !== 1) continue;
      retained = true;
      audioQueue.skipReply(id); reply.closed = true; reply.outputRetired = true;
      connectionFence.fence.closeReply(id);
      if (!connectionFence.retirements.has(id)) connectionFence.retirements.set(id, {
        reply, operationId: `retired-${Date.now()}-${++explicitSequence.current}`, confirmed: false,
        waitForBinding: reply.phase === 'pending',
      });
    }
    return retained;
  }
  usePhonePresentation(remote.client, getPhoneReplyAuth,
    !muxedRouteBlocked&&remote.connected && phoneReplyControls && activeState?.features?.phone_presentation_version === 1
      && (!guardedOutput || Boolean(playbackTicket))
      && (backendRecorder.liveEnabled || phonePlaybackActive || connectionFence.pending.size > 0
        || [...connectionFence.replies.values()].some(reply => !reply.done && !reply.closed && !reply.outputRetired
          && reply.ticket === ticketRef.current)));
  const replyPlaybackNeeded = (remote.connected || remote.mediaContinuity) && guardedOutput && Boolean(playbackTicket)
    && (phoneReplyAudioActive || connectionFence.pending.size > 0
      || [...connectionFence.replies.values()].some(reply => !reply.done && !reply.closed && !reply.outputRetired
        && reply.ticket === ticketRef.current));
  React.useEffect(() => {
    const ticket = playbackTicket;
    return () => {
      if (Platform.OS === 'android' && ticket) void capture.setReplyPlaybackActive?.(ticket, false).catch(() => undefined);
    };
  }, [capture, playbackTicket]);
  async function endPhoneReplyOutput(routeChange=false) {
    soundscapeStopEffectRef.current();
    if(!routeChange)routeRecovery.current?.cancel();
    if (connectionFence !== backgroundFence.current) return;
    if (nativeRequested) nativeSpeech.cancel();
    const ticket = ticketRef.current;
    retainStoppedReplies();
    for (const id of connectionFence.replies.keys()) audioQueue.skipReply(id);
    connectionFence.replies.clear(); connectionFence.pending.clear(); reviseBackgroundPolicy();
    const cleanup = await Promise.allSettled([
      invokeCleanup('capture.cancel',()=>backendRecorder.cancelCapture()),
      invokeCleanup('playback.close',()=>muxedPlayback.close()),
    ]);
    const failures: unknown[] = cleanup.flatMap((result,index) => result.status === 'rejected'
      ? [noteCleanupFailure(result.reason,index===0?'capture.cancel':'playback.close')] : []);
    // Protected cancellation closes its publication itself. Ordinary foreground
    // output has no capture lease, but still needs exact native retirement.
    if (guardedOutput && ticket && ticketRef.current === ticket && backgroundFence.current === connectionFence) {
      let cleanupOperation='output.retire';
      try {
        await capture.retireOutput(ticket);
        if (ticketRef.current === ticket && backgroundFence.current === connectionFence) {
          cleanupOperation='output.state';
          const state = await capture.outputState();
          if (ticketRef.current === ticket && backgroundFence.current === connectionFence) {
            cleanupOperation='output.confirmation';
            if (state.open || state.ticket !== ticket) throw new Error('Phone reply output closure could not be confirmed.');
            outputGeneration.current++; closePublishedOutput();
          }
        }
      } catch (error) { failures.push(noteCleanupFailure(error,cleanupOperation)); }
    }
    if (failures.length === 1) throw failures[0];
    if (failures.length > 1) throw Object.assign(new Error('Phone reply output cleanup failed.'), {errors: failures});
  }
  async function settleConnectionChange(change: () => void) {
    if (connectionModeSwitch.current) return;
    connectionModeSwitch.current = true;
    setConnectionModeChanging(true); setConnectionModeError('');
    try {
      // Exact reader ACKs and Desktop retirement still need the old peer.
      // Dropping it first strands that owner and blocks the next video stream.
      await endPhoneReplyOutput();
      if (!connectionSwitchMounted.current || backgroundFence.current !== connectionFence) return;
      change();
    } catch (error) {
      if (connectionSwitchMounted.current) setConnectionModeError(error instanceof Error
        ? error.message : 'Playback could not finish closing. Retry the connection switch.');
    } finally {
      connectionModeSwitch.current = false;
      if (connectionSwitchMounted.current) setConnectionModeChanging(false);
    }
  }
  function changeConnectionMode(mode: typeof remote.connectionMode) {
    if (mode === remote.connectionMode) return;
    return settleConnectionChange(() => remote.setConnectionMode(mode));
  }
  const replyPoll = React.useRef({ audioQueue, backendRecorder, remote, endPhoneReplyOutput, getPhoneReplyAuth, muxedPlayback });
  replyPoll.current = { audioQueue, backendRecorder, remote, endPhoneReplyOutput, getPhoneReplyAuth, muxedPlayback };
  routeContext.current={scope:connectionFence,connection:remote.client,ticket:ticketRef.current,
    foreground:foregroundRef.current,enabled:remote.connected&&muxedTrialSelected&&!nativePlayback&&!storyActive,
    live:Boolean(backgroundSession.current&&!backgroundSession.current.inputStopped),output:()=>capture.outputState(),
    close:()=>replyPoll.current.endPhoneReplyOutput(true),
    restorePlayback:()=>ensureForegroundOutput(),
    restoreLive:async()=>{
      const next=replyPoll.current.backendRecorder;
      if(!('resumeLiveAfterRouteChange' in next))throw Error('Audio route capture unavailable');
      await next.resumeLiveAfterRouteChange();
    },
    report:(stage,error)=>{
      // Preserve bounded, sanitized settlement causes; never retain raw native
      // messages/paths or let a hostile exception property affect recovery.
      let causes:Omit<ReturnType<typeof orderedFailureDetails>,'capture_actions'>[]=[];
      try {
        const children=error&&typeof error==='object'?Object.getOwnPropertyDescriptor(error,'errors')?.value:undefined;
        if(Array.isArray(children))causes=children.slice(0,4).map(child=>{
          const {capture_actions,...cause}=orderedFailureDetails(child);return cause;
        });
      }catch{}
      void recordPhoneDebug('warning','android_audio_route_recovery',{
        stage,...(error===undefined?{}:orderedFailureDetails(error)),...(causes.length?{causes}:{}),
      }).catch(()=>undefined);
      if(backgroundFence.current!==connectionFence)return;
      if(stage.endsWith('_failed'))setPhoneReplyError(`Audio device recovery could not complete (${stage}). Try Talk or Start Live again.`);
      else if(stage==='restored')setPhoneReplyError('');
    }};
  React.useEffect(() => {
    // A replacement credential owner must not inherit a transport warning from
    // the previous connection. Unrelated ownership/capture errors remain visible.
    setPhoneReplyError(current => current === PHONE_REPLY_STATUS_WARNING ? '' : current);
    let alive = true, polling = false;
    const completedObserver = () => {
      const session = backgroundSession.current;
      if (session?.owner === connectionFence && connectionFence.fence.tailPermit(session.id).pendingUploadIds.length) return undefined;
      if (!session && [...connectionFence.pending.values()].some(pending => pending.ticket === ticketRef.current
        && pending.generation === outputGeneration.current)) return undefined;
      let observer: OwnedReply | undefined;
      for (const reply of connectionFence.replies.values()) {
        if (reply.outputRetired || reply.ticket !== ticketRef.current
          || (reply.sessionId ? session?.owner !== connectionFence || session.id !== reply.sessionId : Boolean(session))) continue;
        // Current unfinished work supplies cancellation observation itself.
        if (!reply.done) return undefined;
        observer = reply;
      }
      return observer;
    };
    const poll = async () => {
      if ('reconnecting' in replyPoll.current.backendRecorder && replyPoll.current.backendRecorder.reconnecting) return;
      if (!alive || polling || connectionFence !== backgroundFence.current
        || (!connectionFence.replies.size && !connectionFence.pending.size && !connectionFence.retirements.size
          && !backgroundSession.current?.inputStopped)) return;
      polling = true;
      const generation = outputGeneration.current;
      const currentPoll = () => alive && connectionFence === backgroundFence.current
        && generation === outputGeneration.current
        && !('reconnecting' in replyPoll.current.backendRecorder && replyPoll.current.backendRecorder.reconnecting);
      const terminal = async () => {
        if (currentPoll()) await replyPoll.current.endPhoneReplyOutput();
      };
      let observingCompleted = false;
      let observedCurrentStatus = false;
      try {
        for (const [id, retired] of connectionFence.retirements) {
          const current = () => currentPoll() && connectionFence.retirements.get(id) === retired;
          if (!current()) return;
          try {
            if (!retired.confirmed) {
              const ticket = retired.reply.ticket;
              // Idempotent retirement targets only the old ticket. Native Begin
              // cannot issue a successor without retiring its predecessor first.
              if (ticket) {
                await capture.retireOutput(ticket);
                const state = await capture.outputState();
                if (!current()) return;
                if (state.ticket === ticket && state.open) throw new Error('Reply output is still open.');
              } else if (guardedOutput) continue;
              // Unguarded output is released by the audio queue's identity-change
              // effect before this poll. It has no native output ticket.
              retired.confirmed = true;
            }
            if (!replyPoll.current.remote.connected) continue;
            if (retired.waitForBinding) {
              const status = await replyPoll.current.remote.client.getPhoneReplyStatus(retired.reply.auth, id);
              if (!current()) return;
              if (status.phase === 'pending') continue;
              if (status.phase === 'cancelled' || status.phase === 'superseded') {
                connectionFence.retirements.delete(id); observedCurrentStatus = true; continue;
              }
            }
            // Retry this immutable operation on the next poll, without holding up
            // status observation for a new reply for the full retry horizon.
            const result = await replyPoll.current.remote.client.sendPhoneReplyAction(retired.reply.auth,
              { kind: 'skip', phone_request_id: id, operation_id: retired.operationId });
            if (!current()) return;
            if (['accepted', 'duplicate', 'stale'].includes(result.status)) {
              connectionFence.retirements.delete(id); observedCurrentStatus = true;
            }
          } catch (failure) {
            if (!current()) return;
            const code = phoneReplyErrorCode(failure);
            if (code === 'phone_reply_stale_scope') {
              // Native output is already retired. The backend has definitively
              // rejected this old receipt, so retrying cannot release anything.
              // Do not tear down a successor or wait for a new reply to recover.
              connectionFence.retirements.delete(id); observedCurrentStatus = true;
              continue;
            }
            setPhoneReplyError(PHONE_REPLY_STATUS_WARNING);
            // An obsolete receipt cannot authorize teardown of newer output.
            if (code === 'phone_reply_authentication' || code === 'phone_reply_ownership') connectionFence.retirements.delete(id);
          }
        }
        if (!replyPoll.current.remote.connected) {
          if ([...connectionFence.replies.values()].some(reply => reply.auth.shared_queue_version === 1)) {
            setPhoneReplyError(PHONE_REPLY_STATUS_WARNING); return;
          }
          await terminal(); return;
        }
        for (const [id, pending] of connectionFence.pending) {
          if (backgroundSession.current || pending.ticket !== ticketRef.current || pending.generation !== outputGeneration.current) {
            connectionFence.pending.delete(id); continue;
          }
          if (Date.now() > pending.deadline) {
            setPhoneReplyError(PHONE_REPLY_ACK_RECOVERY_EXPIRED); await terminal(); return;
          }
        }
        for (const [id, reply] of connectionFence.replies) {
          if (reply.outputRetired) { if (Date.now() > reply.deadline) connectionFence.replies.delete(id); continue; }
          if (reply.done && reply !== completedObserver()) continue;
          // Completion recovery and idle cancellation monitoring have distinct,
          // fixed clocks. Neither is refreshed by polling or newer submissions.
          const sharedQueue = reply.auth.shared_queue_version === 1;
          const deadline = reply.done ? reply.completedObservationDeadline ?? 0 : reply.deadline;
          if (Date.now() > deadline && !(sharedQueue && !reply.done)) {
            setPhoneReplyError(reply.done ? 'Reply cancellation monitoring expired. Start Live again when ready.'
              : 'Reply completion timed out. Stop Live and restart when ready.'); await terminal(); return;
          }
          observingCompleted = reply.done;
          let pagesReconciled = false;
          const readStatus = async () => {
            if (reply.auth.reply_continuation_version !== 1 || reply.done || reply.closed) {
              const status = await replyPoll.current.remote.client.getPhoneReplyStatus(reply.auth, id);
              pagesReconciled = reply.auth.reply_continuation_version !== 1;
              return status;
            }
            const items: AudioChunk[] = [];
            let cursor: number | null = 0;
            let status;
            do {
              status = await replyPoll.current.remote.client.getPhoneReplyContinuation(reply.auth, id, cursor,
                replyPoll.current.audioQueue.completedReplySequence(id));
              if (!currentPoll() || reply.closed) return status;
              // Cancellation can release this old reply's retained media.
              // Let the exact reply-status handler retire it; missing old bytes
              // must never terminate the replacement idle/output owner.
              if (status.phase === 'cancelled' || status.phase === 'superseded' || status.playback_stop_requested)
                return status;
              if (!status.continuation.available) {
                // Retention is optional for uninterrupted playback. Capacity
                // exhaustion only becomes terminal when restoring that reply.
                if (status.continuation.reason === 'capacity'
                  && !replyContinuation.current?.replies.some(r => r.requestId === id)) return status;
                connectionTrace.event('reply_recovery_unavailable', {reply_id:id, phase:status.phase,
                  reason:status.continuation.reason, done:Number(reply.done), retired:Number(reply.outputRetired)}, true);
                setPhoneReplyError('Interrupted reply audio is no longer available.');
                await terminal(); return status;
              }
              items.push(...status.continuation.items); cursor = status.continuation.next_cursor;
            } while (cursor !== null);
            replyPoll.current.audioQueue.appendReplyMedia(id, items);
            pagesReconciled = true;
            return status;
          };
          const status = await readStatus().catch(failure => {
            if (reply.done && (reply.outputRetired || reply !== completedObserver())) return null;
            throw failure;
          });
          if (!currentPoll() || connectionFence.replies.get(id) !== reply) return;
          if (!status || reply.outputRetired || (reply.done && reply !== completedObserver())) continue;
          // Publish knowledge only after page reconciliation and the current
          // connection/reply recheck. This creates no output permission.
          replyPoll.current.muxedPlayback.observeReplyStatus(id, status, pagesReconciled);
          observedCurrentStatus = true;
          if (reply.phase !== status.phase) { reply.phase = status.phase; reviseBackgroundPolicy(); }
          if (status.phase === 'superseded') {
            connectionFence.replies.delete(id); connectionFence.fence.closeReply(id); reviseBackgroundPolicy(); continue;
          }
          if (status.phase === 'cancelled') {
            if(!replyPoll.current.muxedPlayback.selected){await terminal();return;}
            reply.closed=true;connectionFence.fence.closeReply(id);reviseBackgroundPolicy();
          }
          if (reply.done) continue;
          const playback = replyPoll.current.audioQueue;
          if (sharedQueue && status.playback_stop_requested && !reply.closed) {
            playback.skipReply(id); reply.closed = true; connectionFence.fence.closeReply(id); reviseBackgroundPolicy();
          }
          // With autoplay off there is no future vocalization to drain. Finish
          // through the same owned-reply path so re-enabling it cannot revive
          // an old silent reply or leave that reply waiting until timeout.
          const silentComplete = !playback.enabled && !playback.playingId && !playback.isPlaying
            && !playback.currentChunk && !playback.preparedChunk;
          const completionReady = (status.phase === 'complete' && ((!replyPoll.current.muxedPlayback.selected&&silentComplete) || playback.replyDrained(id, status.last_sequence_index)))
            || (status.phase==='cancelled'&&replyPoll.current.muxedPlayback.selected&&playback.replyDrained(id,status.last_sequence_index))
            || (sharedQueue && status.playback_stop_requested === true && playback.replyDrained(id, status.last_sequence_index));
          if (completionReady) {
            if (reply.ticket && reply.ticket !== ticketRef.current) { await terminal(); return; }
            if (!replyPoll.current.audioQueue.finishReply(id)) continue;
            if (sharedQueue) {
              const operationId = reply.completionOperationId ??= `playback-${Date.now()}-${++explicitSequence.current}`;
              const action = { kind: 'playback_finished' as const, phone_request_id: id, operation_id: operationId };
              const result = await retryPhoneReply(() => replyPoll.current.remote.client.sendPhoneReplyAction(reply.auth, action),
                () => currentPoll() && connectionFence.replies.get(id) === reply
                  && reply.ticket === ticketRef.current
                  && (reply.sessionId ? (Platform.OS==='android'
                    ?independentCaptureSessions.current.get(reply.sessionId)?.owner===connectionFence
                    :backgroundSession.current?.owner === connectionFence&&backgroundSession.current.id === reply.sessionId)
                    : Platform.OS==='android'||!backgroundSession.current));
              if (!currentPoll() || connectionFence.replies.get(id) !== reply) return;
              if (!['accepted', 'duplicate'].includes(result.status)) continue;
            }
            reply.done = true; reply.completedObservationDeadline = Date.now() + 900_000;
            if (replyContinuation.current?.replies.every(r => connectionFence.replies.get(r.requestId)?.done)) {
              clearTimeout(continuationTimer.current); replyContinuation.current = null;
            }
            connectionFence.fence.closeReply(id); reviseBackgroundPolicy();
          }
        }
        const finishingSessions=Platform.OS==='android'?[...independentCaptureSessions.current.values()]:[backgroundSession.current];
        for(const session of finishingSessions)if (session?.owner === connectionFence && session.inputStopped && ticketRef.current
          && 'finishReplyOutput' in replyPoll.current.backendRecorder) {
          const ids = connectionFence.fence.retainedRequestIds(session.id);
          if (!connectionFence.fence.tailPermit(session.id).pendingUploadIds.length && ids.every(id => connectionFence.replies.get(id)?.done)) {
            await replyPoll.current.backendRecorder.finishReplyOutput(session.id, ticketRef.current, ids);
          }
        }
        if (observedCurrentStatus && !connectionFence.retirements.size && currentPoll()) {
          setPhoneReplyError(current => current === PHONE_REPLY_STATUS_WARNING ? '' : current);
        }
      } catch (failure) {
        if (currentPoll()) {
          setPhoneReplyError(PHONE_REPLY_STATUS_WARNING);
          const code = phoneReplyErrorCode(failure);
          if (code === 'phone_reply_authentication' || code === 'phone_reply_ownership' || (observingCompleted && Boolean(code))) {
            await terminal().catch(() => undefined);
            // Only the expired private capability is renewed; outer credentials stay owned by the connection hook.
            if (alive && (code === 'phone_reply_authentication' || code === 'phone_reply_ownership')) await replyPoll.current.getPhoneReplyAuth(true).catch(() => undefined);
          }
        }
      } finally { polling = false; }
    };
    const timer = setInterval(() => { void poll(); }, 1000);
    return () => { alive = false; clearInterval(timer); connectionFence.pending.clear(); };
  }, [connectionFence]);
  const ensureForegroundOutput = async (drainPreviousCapture = true, retained?:ManualDeparturePermit, preserveReply = false) => {
    const identity = connectionFence;
    if (identity !== backgroundFence.current) throw new Error('The conversation changed. Try again.');
    if (!guardedOutput) return;
    if(!foregroundRef.current&&retained){
      retained.assertSend();
      const state=await capture.outputState();
      retained.assertSend();
      if(identity!==backgroundFence.current||!retainsOrderedBackground()||!state.open||state.sessionId!==null
        ||state.ticket!==ticketRef.current)throw Error('Retained recording output owner ended.');
      return; // Never open or replace output from a background recording.
    }
    if (!foregroundRef.current) throw new Error('Return to the app before starting playback.');
    if (backgroundSession.current?.owner === identity) { await ticketCommit.current; return; }
    const generation = outputGeneration.current;
    if (foregroundOpening.current) await foregroundOpening.current;
    const opening = (async () => {
      let state = await capture.outputState();
      if (!foregroundRef.current || backgroundFence.current !== identity || generation !== outputGeneration.current) {
        throw new Error('The conversation changed. Try again.');
      }
      if (state.open && state.sessionId === null && state.ticket === ticketRef.current) { await ticketCommit.current; return; }
      const expectedTicket = state.ticket;
      // Only a retiring protected producer needs this drain. Foreground Live and
      // manual capture can coexist with a foreground output ticket as before.
      if (backgroundDrainPending.current) {
        if (drainPreviousCapture) await backendRecorder.cancelCapture();
        if (generation === outputGeneration.current) backgroundDrainPending.current = false;
      }
      await liveControl.current;
      state = await capture.outputState();
      if (!foregroundRef.current || backgroundFence.current !== identity || generation !== outputGeneration.current || state.ticket !== expectedTicket) {
        throw new Error('The conversation changed. Try again.');
      }
      if (!preserveReply) audioQueue.interrupt();
      // Failed preparation can leave the drained foreground predecessor open.
      // Retire only this captured identity; a concurrent new owner fails Begin.
      if (state.open && expectedTicket) await capture.retireOutput(expectedTicket);
      if (!foregroundRef.current || backgroundFence.current !== identity || generation !== outputGeneration.current) {
        throw new Error('The conversation changed. Try again.');
      }
      const ticket = await capture.beginForegroundOutput(expectedTicket);
      if (!foregroundRef.current || backgroundFence.current !== identity || generation !== outputGeneration.current) {
        await capture.retireOutput(ticket); throw new Error('The conversation changed. Try again.');
      }
      await publishOutput(ticket);
    })();
    foregroundOpening.current = opening;
    try { await opening; }
    finally { if (foregroundOpening.current === opening) foregroundOpening.current = null; }
  };
  // Bind handlers to the rendered attempt too: a picker or
  // stale view may call its handler only after Stop/new Live has already run.
  const explicitActionContext = {
    owner: connectionFence, session: backgroundSession.current, generation: outputGeneration.current,
    submissionEpoch: submissionEpoch.current,
  };
  const assertExplicitAction = (action: typeof explicitActionContext, retainedReplay = false) => {
    if (chatResetRef.current?.confirmed) throw new Error('Wait for Reset Chat to finish.');
    if (action.owner !== backgroundFence.current || action.session !== backgroundSession.current
      || action.generation !== outputGeneration.current || action.submissionEpoch !== submissionEpoch.current) {
      throw new Error('The conversation changed. Try again.');
    }
    if (action.session && !(retainedReplay && action.session.inputStopped) && (!('isBackgroundSessionReady' in backendRecorder)
      || !backendRecorder.isBackgroundSessionReady(action.session.id))) {
      throw new Error('Background Live is still starting. Wait until it is ready, then try again. Stop is available.');
    }
  };
  function beginForegroundSubmission(action = explicitActionContext) {
    assertExplicitAction(action);
    if (action.session || (guardedOutput && !ticketRef.current)) throw new Error('Phone reply output ownership unavailable.');
    for (const [id, pending] of connectionFence.pending) {
      if (pending.ticket !== ticketRef.current || pending.generation !== outputGeneration.current) connectionFence.pending.delete(id);
    }
    if (connectionFence.pending.size >= 2) throw new Error('Previous reply acknowledgements are still pending. Wait before sending again.');
    const id = `foreground-${++explicitSequence.current}`;
    const pending = { ticket: ticketRef.current, generation: outputGeneration.current, deadline: Date.now() + 900_000 };
    connectionFence.pending.set(id, pending); reviseBackgroundPolicy();
    const sameScope = () => action.owner === backgroundFence.current && !backgroundSession.current
      && connectionFence.pending.get(id) === pending && pending.ticket === ticketRef.current
      && pending.generation === outputGeneration.current;
    const isCurrent = () => sameScope() && Date.now() <= pending.deadline;
    return {
      isCurrent,
      settle: (requestId: string | null, auth: PhoneReplyAuth) => {
        // Adopt and remove pending ownership synchronously, under the original
        // owner/ticket/generation fence. An expired ACK never revives output.
        if (isCurrent()) {
          if(requestId&&Platform.OS==='android'&&guardedOutput&&
            !capture.admitForegroundReply?.(pending.ticket!,requestId))throw Error('ordered.foreground_reply_admission_rejected');
          if (requestId) trackReply(requestId, auth);
          connectionFence.pending.delete(id);
        } else if (!sameScope()) connectionFence.pending.delete(id);
        reviseBackgroundPolicy();
      },
      fail: (failure: unknown) => {
        // An uncertain dispatch may have committed. Keep its original absolute
        // deadline, including across private-capability renewal, without resend.
        if (!sameScope() || !isUncertainPhoneReplyError(failure)) connectionFence.pending.delete(id);
        reviseBackgroundPolicy();
      },
    };
  }
  const correlatedSubmission = async (
    operation: (auth?: PhoneReplyAuth) => Promise<unknown>, action = explicitActionContext, kind: 'text' | 'image' = 'text',
    retained?:ManualDeparturePermit,
    continuousBackground = false,
  ) => {
    assertExplicitAction(action);
    if (continuousBackground) await prepareContinuousOutput(action);
    else await ensureForegroundOutput(true,retained);
    assertExplicitAction(action);
    if (!foregroundRef.current && !continuousBackground && !retained?.isCurrent()) throw new Error('Return to the app before sending.');
    const { session } = action;
    const uploadId = `explicit-${++explicitSequence.current}`;
    if (phoneReplyControls) {
      const submit = async (auth: PhoneReplyAuth) => {
        retained?.assertSend();retained?.markDispatched();
        const result = await operation(auth);
        // An accepted turn without a usable ID may be generating already. Keep
        // the existing uncertain-ACK fence; never release the next manual turn.
        if (!remoteActionError(result) && !phoneReplyRequestId(result)) {
          throw new Error('Phone reply acknowledgement unavailable. The message may have been accepted.');
        }
        return result;
      };
      const auth = await getPhoneReplyAuth();
      assertExplicitAction(action);
      if (session && 'submitReplyTurn' in backendRecorder) return backendRecorder.submitReplyTurn(session.id, uploadId, kind, () => submit(auth),auth);
      const pending = beginForegroundSubmission(action);
      try {
        // Acquire Android's media service while the sending Activity is visible,
        // before network dispatch can outlive a switch to another app.
        if (Platform.OS === 'android' && ticketRef.current) await capture.setReplyPlaybackActive?.(ticketRef.current, true);
        assertExplicitAction(action);
        if (!pending.isCurrent()) throw new Error('Phone reply ownership ended.');
        let result: unknown, submittedAuth = auth;
        try { result = await submit(auth); }
        catch (failure) {
          if (phoneReplyErrorCode(failure) !== 'phone_reply_authentication') throw failure;
          // The server rejected this private capability before dispatch.
          try { submittedAuth = await getPhoneReplyAuth(true); }
          catch (renewalFailure) { pending.fail(failure); throw renewalFailure; }
          assertExplicitAction(action);
          if (!pending.isCurrent()) throw new Error('Phone reply ownership ended.');
          result = await submit(submittedAuth);
        }
        pending.settle(phoneReplyRequestId(result), submittedAuth);
        return result;
      } catch (failure) { pending.fail(failure); throw failure; }
    }
    if (session) {
      session.owner.fence.beginUpload(session.id, uploadId); consumeBackgroundPolicy(session.owner);
      if (session.owner.fence.automaticBlockReason() === 'latched-closed') throw new Error(closedReplyExplanation);
    }
    let requestId: string | null = null;
    try { const result = await operation(); requestId = explicitRequestId(result); return result; }
    finally {
      if (session) {
        session.owner.fence.settleUpload(session.id, uploadId, requestId); consumeBackgroundPolicy(session.owner);
      }
    }
  };
  const continuousAvailable = remote.continuousAvailable;
  const continuousBackgroundSupported = Platform.OS === 'android' && guardedOutput;
  const continuousActivity = continuousActivityAllowed(foreground, continuousBackgroundSupported, playbackTicket);
  const prepareContinuousOutput = async (context = explicitActionContext, signal?: AbortSignal) => {
    if (!continuousBackgroundSupported) { await ensureForegroundOutput(); return undefined; }
    return retainContinuousOutput({capture, foreground:()=>foregroundRef.current,
      ticket:()=>ticketRef.current, ensureForeground:()=>ensureForegroundOutput(),
      current:()=>{
        try { assertExplicitAction(context); return !signal?.aborted && remote.connected && !backgroundSession.current; }
        catch { return false; }
      }});
  };
  const continuousCanClaim = continuousActivity && !backendRecorder.recording && !backendRecorder.busy && !backendRecorder.liveEnabled;
  const continuousOwner = React.useMemo(()=>({connection:connectionFence,ticket:playbackTicket}),[connectionFence,playbackTicket]);
  const [notificationPauseOwner,setNotificationPauseOwner] = React.useState<typeof continuousOwner|null>(null);
  const [,updateUserPlayback] = React.useState(0);
  const [notificationActionPending,setNotificationActionPending] = React.useState(false);
  const userPlayback = React.useMemo(()=>new ContinuousUserPlayback(()=>updateUserPlayback(n=>n+1)),[continuousOwner]);
  React.useEffect(()=>{userPlayback.setVolume(settings.automatedUserTtsVolume);},[userPlayback,settings.automatedUserTtsVolume]);
  const continuous = useContinuousConversation({client:remote.client,owner:continuousOwner,
    enabled:remote.connected && continuousAvailable && phoneReplyControls && !storyActive && !demoMode && continuousActivity,
    canClaim:continuousCanClaim,auth:getPhoneReplyAuth,
    // A visible app may reacquire a lost ticket in readUser; enabled already
    // excludes background activity when no protected ticket exists.
    canReadUser:!phonePlaybackActive,
    readUser:async(speech,signal)=>{
      const ticket = await prepareContinuousOutput(explicitActionContext,signal);
      if (signal.aborted) throw new Error('User speech cancelled.');
      return readContinuousUserMessage(remote.client, getPhoneReplyAuth, speech.operation_id, signal, ticket, userPlayback);
    },
    claim:async id=>{
      const context=explicitActionContext;
      const result=await correlatedSubmission(async auth=>{
        const retainedAuth=auth ?? await getPhoneReplyAuth();
        return retryPhoneReply(()=>remote.client.claimContinuous(retainedAuth,id),()=>{
          try{assertExplicitAction(context);return true;}catch{return false;}
        });
      },context,'text',undefined,continuousBackgroundSupported);
      const error=remoteActionError(result);if(error)throw new Error(error);
    }});
  const soundscape=useSoundscape(remote.client,!demoMode&&!storyActive&&remote.connected
    && activeState?.features?.soundscape_version===1 && Boolean(activeState?.engine?.running ?? activeState?.runtime_status?.running),conversationGeneration,
    activeState?.features?.soundscape_context_version===1);
  soundscapeOnsetRef.current=soundscape.onAssistantOnset;
  soundscapeStopEffectRef.current=()=>{soundscape.playback?.cancelOnset();soundscape.playback?.clearCue();void soundscape.playback?.stopEffects().catch(()=>undefined);};
  const soundscapeAssistantId=[...(activeState?.chat?.messages??[])].reverse()
    .find(message=>message.role==='assistant')?.id;
  React.useEffect(()=>{
    const state=soundscape.controls.state;
    if(!state?.enabled||state.paused||!soundscapeAssistantId
      ||(!state.ambience.follow_story&&!state.music.follow_story&&!state.effects?.enabled))return;
    const early=setTimeout(()=>void soundscape.controls.refresh(false).catch(()=>undefined),100);
    const retry=setTimeout(()=>void soundscape.controls.refresh(false).catch(()=>undefined),1200);
    return()=>{clearTimeout(early);clearTimeout(retry);};
  },[soundscapeAssistantId,soundscape.controls.refresh,soundscape.controls.state?.enabled,
    soundscape.controls.state?.paused,soundscape.controls.state?.ambience.follow_story,
    soundscape.controls.state?.music.follow_story,soundscape.controls.state?.effects?.enabled]);
  React.useEffect(()=>{
    const id=audioQueue.currentChunk?.phone_request_id ?? audioQueue.currentChunk?.id ?? 'assistant';
    void soundscape.playback?.speech(id,audioQueue.isPlaying&&!audioQueue.paused,false).catch(()=>undefined);
    return ()=>{void soundscape.playback?.speech(id,false,false).catch(()=>undefined);};
  },[soundscape.playback,audioQueue.currentChunk?.phone_request_id,audioQueue.currentChunk?.id,audioQueue.isPlaying,audioQueue.paused]);
  React.useEffect(()=>{
    const id='user-'+(continuous.state?.prepared_id ?? 'current');
    void soundscape.playback?.speech(id,userPlayback.audible&&!userPlayback.paused,false).catch(()=>undefined);
    return ()=>{void soundscape.playback?.speech(id,false,false).catch(()=>undefined);};
  },[soundscape.playback,continuous.state?.prepared_id,userPlayback.audible,userPlayback.paused]);
  const soundscapeStoryWasActive=React.useRef(false);
  React.useEffect(()=>{
    const phase=continuous.state?.state;
    if(phase && !['paused','stopped','idle'].includes(phase)) {
      soundscapeStoryWasActive.current=true;
      void soundscape.playback?.resumeAfterStory().catch(()=>undefined);
    }
    if(audioQueue.paused||(continuous.readingUser&&userPlayback.paused))void soundscape.playback?.pause('user').catch(()=>undefined);
    else if(soundscapeStoryWasActive.current && ['paused','stopped'].includes(phase ?? '') && !audioQueue.activeReplyId && !continuous.readingUser) {
      soundscapeStoryWasActive.current=false;
      void soundscape.playback?.pause('story').catch(()=>undefined);
    }
  },[soundscape.playback,audioQueue.paused,userPlayback.paused,continuous.readingUser,continuous.state?.state,audioQueue.activeReplyId]);
  // Keep the same native service through user speech, assistant speech and their
  // handoff. Starting is still subject to Android's foreground-only native check.
  const continuousServiceNeeded = continuousBackgroundSupported && (remote.connected || remote.mediaContinuity)
    && continuousAvailable && phoneReplyControls && !storyActive && !demoMode
    && continuousCanClaim && Boolean(continuous.state?.owned)
    && (!['stopped','paused','suspended'].includes(continuous.state?.state ?? 'stopped')
      || (continuous.state?.state === 'paused' && notificationPauseOwner === continuousOwner));
  React.useEffect(() => {
    if (Platform.OS !== 'android' || !playbackTicket || !capture.setReplyPlaybackActive) return;
    const ticket = playbackTicket;
    const needed = replyPlaybackNeeded || continuousServiceNeeded || (notificationActionPending && remote.connected && guardedOutput);
    void capture.setReplyPlaybackActive(ticket, needed).catch(() => {
      if (ticketRef.current === ticket && needed) setPhoneReplyError('Background reply playback could not start. Reconnect and retry.');
    });
  }, [capture, playbackTicket, replyPlaybackNeeded, continuousServiceNeeded, notificationActionPending, remote.connected, guardedOutput]);
  const enterMediaSurface = async (destination: MainTab) => {
    if (!isPhoneDestinationEnabled(destination)) destination = 'chat';
    const leavingContinuousLive = continuousCaptureRuntimeEnabled() && !backendRecorder.recording
      && (backendRecorder.liveEnabled || backgroundSession.current !== null || backgroundDrainPending.current);
    if (leavingContinuousLive && (destination === 'story' || destination === 'visual')) {
      await backendRecorder.cancelCapture();
      await ensureForegroundOutput();
    }
    setSecondarySurface(null); setActiveTab(destination);
  };
  beforeNativeListeningRef.current = backendRecorder.cancelCapture;
  React.useEffect(() => {
    if (nativePlayback) void backendRecorder.cancelCapture().catch(() => nativeSpeech.reportCaptureReleaseError());
  }, [nativePlayback, backendRecorder.cancelCapture]);
  const replyBlock = connectionFence.fence.automaticBlockReason();
  const replyExplanation = replyBlock === 'latched-closed' ? closedReplyExplanation
    : replyBlock === 'waiting-for-ack' ? 'Automatic replies are waiting for the previous cancelled request acknowledgement. Explicit Replay remains available.' : '';
  const updateExplanation = !demoMode && commandsAvailable && !phoneReplyControls && !nativePlayback && !storyActive
    ? 'Separate Live off and Stop speech require an updated gateway and phone app. Existing Live behavior is active.' : '';
  const recorderError = phoneReplyError || replyExplanation || backendRecorder.error || updateExplanation;
  const routeSafeRecorder={...backendRecorder,
    toggleLive:()=>{const recovering=routeRecovery.current?.pending;routeRecovery.current?.cancel();
      return recovering?backendRecorder.cancelCapture():backendRecorder.toggleLive();},
    toggleRecording:()=>{routeRecovery.current?.cancel();return backendRecorder.toggleRecording();}};
  const activeRecorder = nativePlayback ? nativeSpeech : recorderError
    ? { ...routeSafeRecorder, error: recorderError } : routeSafeRecorder;
  const recorder = { ...activeRecorder,
    toggleRecording: async () => { if (!chatResetRef.current?.confirmed) await activeRecorder.toggleRecording(); },
    toggleLive: async () => { if (!chatResetRef.current?.confirmed) await activeRecorder.toggleLive(); },
  };
  pauseLiveForPlaybackRef.current = recorder.pauseLiveForPlayback;
  const runtimeActivity = React.useMemo(() => {
    const microphone = String(runtime?.microphone_state || '').toLowerCase();
    const status = String(activeState?.status_line || '').toLowerCase();
    if (recorder.recording || recorder.livePhase === 'speech') return 'listening' as const;
    if (phonePlaybackActive || status.includes('speak') || status.includes('tts')) return 'speaking' as const;
    if (recorder.busy || status.includes('think') || status.includes('generat') || status.includes('infer')) return 'thinking' as const;
    if (
      recorder.liveEnabled
      || microphone.includes('listen')
      || microphone.includes('record')
    ) return 'listening' as const;
    return 'idle' as const;
  }, [
    activeState?.status_line,
    phonePlaybackActive,
    recorder.busy,
    recorder.liveEnabled,
    recorder.livePhase,
    recorder.recording,
    runtime?.microphone_state,
  ]);
  const presenceActivity: PresenceActivity = recorder.recording || recorder.livePhase === 'speech'
    ? 'listening'
    : phonePlaybackActive
      ? 'speaking'
      : recorder.busy
        ? 'thinking'
        : recorder.liveEnabled
          ? 'listening'
          : activeState?.presence?.activity || (runtimeActivity === 'idle' ? 'ready' : runtimeActivity);
  const livePresence = React.useMemo(() => {
    if (!activeState?.presence) return null;
    if (activeState.presence.activity === presenceActivity) return activeState.presence;
    return {
      ...activeState.presence,
      activity: presenceActivity,
      state_label: presenceActivity === 'ready'
        ? 'Ready'
        : `${presenceActivity.charAt(0).toUpperCase()}${presenceActivity.slice(1)}`,
    };
  }, [activeState?.presence, presenceActivity]);
  const latestVisualReply = React.useMemo(() => {
    const messages = activeState?.chat?.messages ?? [];
    for (let messageIndex = messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
      const replies = messages[messageIndex]?.visual_replies ?? [];
      for (let replyIndex = replies.length - 1; replyIndex >= 0; replyIndex -= 1) {
        const reply = replies[replyIndex];
        if (reply?.status === 'ready') return reply;
      }
    }
    return undefined;
  }, [activeState?.chat?.messages]);
  const handleCompanionModeChange = React.useCallback((companionDisplayMode: typeof settings.companionDisplayMode) => {
    if (companionDisplayMode === 'portrait' && settings.companionDisplayMode !== 'portrait') {
      setPortraitSessionStartedAt(Date.now() / 1000);
    }
    setSettings({ companionDisplayMode, showPresenceControls: false });
  }, [setSettings, settings.companionDisplayMode]);
  const manualScope = React.useRef({ connectionFence, transportRevision: remote.transportFailureRevision, nativeRequested, storyActive, phoneReplyControls, sharedManualQueueAdvertised, demoMode, connected: remote.connected });
  manualScope.current = { connectionFence, transportRevision: remote.transportFailureRevision, nativeRequested, storyActive, phoneReplyControls, sharedManualQueueAdvertised, demoMode, connected: remote.connected };
  const enqueueManualTurn = useManualTurnQueue((retainedRecording=false) => {
    if ((!foregroundRef.current&&!retainedRecording) || phonePlaybackActive) return true;
    const owner = backgroundFence.current, session = backgroundSession.current;
    return owner.pending.size > 0 || Boolean(session && owner.fence.tailPermit(session.id).pendingUploadIds.length)
      || [...owner.replies.values()].some(reply => !reply.outputRetired
        && (reply.manualSkipRequested ? !reply.manualSkipAccepted : !reply.done));
  });
  const queueManualTurn = async (operation: () => Promise<unknown>,retained?:ManualDeparturePermit) => {
    // Only the correlated HQ route has the authoritative whole-reply drain
    // signal. Preserve native/legacy admission until those routes supply one.
    if (!phoneReplyControls) return operation();
    const scope = manualScope.current, action = explicitActionContext;
    const validate = () => {
      assertExplicitAction(action);
      if(retained&&!retained.isCurrent())throw Error('The recording conversation changed.');
      const current = manualScope.current;
      if (scope.connectionFence !== current.connectionFence || scope.transportRevision !== current.transportRevision
        || scope.nativeRequested !== current.nativeRequested || scope.storyActive !== current.storyActive
        || scope.phoneReplyControls !== current.phoneReplyControls || scope.sharedManualQueueAdvertised !== current.sharedManualQueueAdvertised
        || scope.demoMode !== current.demoMode || !current.connected) {
        throw new Error('The conversation changed. Queued message was not sent.');
      }
    };
    validate();
    if (sharedManualQueueAdvertised) {
      const auth = await getPhoneReplyAuth();
      validate();
      if (auth.shared_queue_version === 1) return operation();
    }
    return enqueueManualTurn(operation, validate,retained?.isCurrent);
  };
  const chatResetRef = React.useRef<{owner:typeof connectionFence; confirmed:boolean} | null>(null);
  React.useEffect(() => {
    if (chatResetRef.current?.owner !== connectionFence) chatResetRef.current = null;
  }, [connectionFence]);
  const [conversationActionRecoverable, setConversationActionRecoverable] = React.useState(false);
  const conversationActionRef = React.useRef<{owner: typeof connectionFence; run: () => Promise<void>; promise?: Promise<void>} | null>(null);
  React.useEffect(() => {
    if (conversationActionRef.current?.owner !== connectionFence) {
      conversationActionRef.current = null;
      setConversationActionBusy(''); setConversationActionRecoverable(false);
    }
  }, [connectionFence]);
  const conversationActionsAvailable = sharedManualQueueAdvertised && activeState?.features?.conversation_actions_version === 1;
  const confirmChatReset = () => {
    if (chatResetRef.current || conversationActionBusy || !chatCommandsAvailable
      || recorder.recording || recorder.busy || activeState?.features?.chat_reset !== true) return;
    const job = {owner:connectionFence, confirmed:false};
    chatResetRef.current = job;
    const current = () => chatResetRef.current === job && backgroundFence.current === job.owner
      && foregroundRef.current && manualScope.current.connected && !manualScope.current.storyActive;
    const finish = () => {
      if (chatResetRef.current !== job) return;
      chatResetRef.current = null; setConversationActionBusy('');
    };
    const reset = async () => {
      if (!current() || job.confirmed) { if (!job.confirmed) finish(); return; }
      job.confirmed = true; setConversationActionBusy('reset_chat');
      rememberCaptureControl('chat_reset_begin');
      submissionEpoch.current++;
      try {
        // Stop only this phone's current output/capture before resetting the
        // shared session. Cancelling the confirmation never reaches this path.
        await endPhoneReplyOutput();
        rememberCaptureControl('chat_reset_output_closed');
        if (!current()) return;
        // Deliberately use one HTTP dispatch: a lost response must not cause a
        // second destructive reset through WebSocket fallback or automatic retry.
        rememberCaptureControl('chat_reset_dispatched');
        const result = await remote.client.control('reset_chat');
        if (!current()) return;
        const error = remoteActionError(result, 'Chat reset was not accepted.');
        if (error) throw new Error(error);
        rememberCaptureControl('chat_reset_accepted');
        clearPhotoDraftRef.current();
        composerDraft.clear();
        await remote.refresh();
        rememberCaptureControl('chat_reset_refreshed');
        // Reset retired the carrier's output ticket along with old speech.
        // Restore only foreground ordered playback, not microphone capture.
        if (current() && muxedTrialSelected) await ensureForegroundOutput();
      } catch (failure) {
        rememberCaptureControl('chat_reset_failed');
        if (current()) Alert.alert('Reset Chat unavailable',
          `${failure instanceof Error ? failure.message : 'Reset could not be confirmed.'} Check the conversation before trying again.`);
      } finally { finish(); }
    };
    Alert.alert('Reset Chat?', 'Reset the current conversation on both the phone and PC? Ongoing speech and queued messages will be cleared. Live Mode will stop.', [
      {text:'Cancel', style:'cancel', onPress:finish},
      {text:'Reset Chat', style:'destructive', onPress:reset},
    ], {cancelable:true, onDismiss:() => { if (!job.confirmed) finish(); }});
  };
  const runConversationAction = async (kind: ConversationActionKind, target: ConversationActionTarget, fromNotification = false) => {
    routeRecovery.current?.cancel();
    if (chatResetRef.current) return;
    const previous = conversationActionRef.current;
    if (previous?.owner === connectionFence) { await previous.promise; return; }
    if (!conversationActionsAvailable || !remote.connected || backendRecorder.recording || backendRecorder.busy) return;
    const context = explicitActionContext;
    const body: ConversationActionBody = Object.freeze({kind, target:Object.freeze({...target}),
      operation_id:`conversation-${Date.now()}-${++explicitSequence.current}`});
    let retainedAuth: PhoneReplyAuth | undefined;
    const job = {owner:connectionFence, run:async () => {}, promise:undefined as Promise<void> | undefined};
    job.run = async () => {
      let definitiveRejection = false;
      setConversationActionBusy(kind); setConversationActionRecoverable(false); setPhoneReplyError('');
      const isCurrent = () => {
        try { assertExplicitAction(context); return foregroundRef.current || (fromNotification && continuousBackgroundSupported && Boolean(ticketRef.current)); } catch { return false; }
      };
      const send = async (auth?: PhoneReplyAuth) => {
        retainedAuth ??= auth ?? await getPhoneReplyAuth();
        const result = await retryPhoneReply(() => remote.client.sendConversationAction(retainedAuth!, body), isCurrent);
        if (result.status !== 'accepted') {
          definitiveRejection = true;
          // Definitive rejection: no history is optimistically changed here.
          return {ok:false, error:`Conversation action ${result.status}: ${result.reason || 'refresh and try again'}.`,
            result:{accepted:false, phone_request_id:null}};
        }
        return {ok:true, result:{accepted:true, phone_request_id:result.phone_request_id}};
      };
      try {
        assertExplicitAction(context);
        if((kind==='regenerate'||kind==='retry')&&muxedTrialSelected)await muxedPlayback.beforeConversationAction();
        assertExplicitAction(context);
        const response = kind === 'retry' ? await send() : await correlatedSubmission(send, context, 'text', undefined, fromNotification && continuousBackgroundSupported);
        const error = remoteActionError(response);
        if (error) throw new Error(error);
        if (conversationActionRef.current === job) conversationActionRef.current = null;
      } catch (failure) {
        if (job.owner === backgroundFence.current) {
          setPhoneReplyError(failure instanceof Error ? failure.message : 'Conversation action unavailable.');
          if (!definitiveRejection && isUncertainPhoneReplyError(failure) && isCurrent()) setConversationActionRecoverable(true);
          else if (conversationActionRef.current === job) conversationActionRef.current = null;
        }
      } finally {
        job.promise = undefined;
        if (job.owner === backgroundFence.current && conversationActionRef.current !== job) setConversationActionBusy('');
      }
    };
    conversationActionRef.current = job;
    job.promise = job.run(); await job.promise;
  };
  const dispatchPhoneText = React.useCallback(async (text: string) => {
    if (demoMode) {
      return demo.sendText(text, sendOptions);
    }
    const action = explicitActionContext;
    assertExplicitAction(action);
    if (!phoneReplyControls && shouldInterruptForPhoneText(runtimeActivity, audioQueue.playingId)) {
      if (nativeRequested) nativeSpeech.interrupt();
      else audioQueue.interrupt();
      if (nativeRequested) await remote.sendControl('interrupt_response', sendOptions).catch(() => undefined);
      else await interruptLiveResponse().catch(() => undefined);
    }
    assertExplicitAction(action);
    if (nativeRequested) await nativeSpeech.submit(() => remote.sendText(text, sendOptions));
    else {
      const order = ++explicitSequence.current;
      const result = await correlatedSubmission(auth => remote.sendText(text, { ...sendOptions, phoneReplyAuth: auth }), action);
      markManualSubmission(result, order, action);
    }
  }, [
    audioQueue.interrupt,
    phonePlaybackActive,
    demo,
    demoMode,
    remote,
    runtimeActivity,
    sendOptions,
    nativeRequested,
    nativeSpeech,
    correlatedSubmission,
    interruptLiveResponse,
  ]);
  function markManualSubmission(result: unknown, order: number, action: typeof explicitActionContext) {
    if (action.owner !== backgroundFence.current || action.session !== backgroundSession.current
      || action.generation !== outputGeneration.current) return;
    const id = phoneReplyRequestId(result), owned = id ? connectionFence.replies.get(id) : undefined;
    if (owned?.auth.shared_queue_version === 1) { owned.manualOrder = order; reviseBackgroundPolicy(); }
  }
  const sendPhoneText = async (text: string) => {
    assertExplicitAction(explicitActionContext);
    await continuous.withManualInput(() => demoMode ? dispatchPhoneText(text) : queueManualTurn(() => dispatchPhoneText(text)),
      {afterAutomatedUser:true});
  };
  sendNativeTranscriptRef.current = text => continuous.withManualInput(() => dispatchPhoneText(text));
  const sendPhoneImage = async (imageBase64: string, format: string, prompt: string, imageSource: 'phone_camera' | 'phone_gallery', retained?:ManualDeparturePermit) => { await continuous.withManualInput(() => queueManualTurn(async () => {
    const action = explicitActionContext;
    assertExplicitAction(action);
    const operation = (auth?: PhoneReplyAuth) => remote.sendImage(imageBase64, format, prompt, { ...sendOptions, imageSource, phoneReplyAuth: auth });
    if (nativeRequested) await nativeSpeech.submit(operation);
    else {
      const order = ++explicitSequence.current;
      markManualSubmission(await correlatedSubmission(operation, action, 'image', retained), order, action);
    }
  }, retained), {afterAutomatedUser:true}); };
  const photoDraft = useChatPhotoDraft(`${remote.client.identityKey}:${demoMode}`, {
    sendText: sendPhoneText,
    sendImage: (photo, prompt) => {
      if (demoMode) throw new Error('Photo input requires a desktop connection.');
      return sendPhoneImage(photo.base64, photo.format, prompt, photo.source === 'camera' ? 'phone_camera' : 'phone_gallery');
    },
  });
  photoVoiceSubmissionRef.current = permit => photoDraft.prepareVoiceSubmission(permit
    ?(photo,text)=>sendPhoneImage(photo.base64,photo.format,text,photo.source==='camera'?'phone_camera':'phone_gallery',permit)
    :undefined);
  clearPhotoDraftRef.current = photoDraft.clear;
  sendNativeTranscriptRef.current = text => continuous.withManualInput(() => photoDraft.photo ? photoDraft.send(text) : dispatchPhoneText(text));

  // The desktop owns one replacement slot. Only its latest acknowledged manual
  // input can light Send; polling confirms that it is actually still pending.
  const pendingManualReply = (): [string, OwnedReply] | undefined => {
    let latest: [string, OwnedReply] | undefined;
    for (const entry of connectionFence.replies) {
      const reply = entry[1];
      if (!reply.manualOrder || reply.outputRetired || reply.ticket !== ticketRef.current) continue;
      if (!latest || reply.manualOrder > latest[1].manualOrder!) latest = entry;
    }
    return latest && !latest[1].done && !latest[1].closed && latest[1].phase === 'pending' ? latest : undefined;
  };
  const queuePredecessor = (id: string, queued: OwnedReply): [string, OwnedReply] | undefined => {
    const canBlockQueue = (replyId: string | null | undefined) => {
      const reply = replyId ? connectionFence.replies.get(replyId) : undefined;
      return replyId !== id && reply && !reply.done && !reply.outputRetired
        && !reply.manualSkipAccepted && reply.ticket === ticketRef.current
        && (reply.phase === 'generating' || reply.phase === 'complete');
    };
    const boundPredecessors = [...connectionFence.replies.keys()].filter(canBlockQueue);
    const previousId = (canBlockQueue(queued.queuedBehindId) ? queued.queuedBehindId : undefined)
      ?? (canBlockQueue(audioQueue.activeReplyId) ? audioQueue.activeReplyId
        : boundPredecessors.length === 1 ? boundPredecessors[0] : undefined);
    const previous = previousId ? connectionFence.replies.get(previousId) : undefined;
    return previousId && previous ? [previousId, previous] : undefined;
  };
  const queuedAction = React.useRef<{ owner: typeof connectionFence; promise: Promise<void> } | null>(null);
  const pendingForAdvance = pendingManualReply();
  const queuedMessage = sharedManualQueueAdvertised && Boolean(pendingForAdvance && queuePredecessor(...pendingForAdvance));
  const processQueuedMessage = (): Promise<void> => {
    if (queuedAction.current?.owner === connectionFence) return queuedAction.current.promise;
    const pending = pendingManualReply();
    if (!pending || !sharedManualQueueAdvertised) return Promise.resolve();
    const [id, queued] = pending, context = explicitActionContext;
    const predecessor = queuePredecessor(id, queued);
    if (!predecessor) return Promise.resolve();
    const job = { owner: connectionFence, promise: Promise.resolve() };
    job.promise = Promise.resolve().then(async () => {
      assertExplicitAction(context);
      if (!foregroundRef.current || !replyPoll.current.remote.connected) throw new Error('Reconnect before advancing your queued message.');
      // Capture the predecessor before awaiting. A late response cannot stop a
      // different reply that started while the request was in flight.
      // The bound predecessor still owns the playback gate after local drain.
      const [previousId, previous] = predecessor;
      connectionTrace.event('queued_send_attempt', {reply_id:id, previous_id:previousId,
        replies:connectionFence.replies.size, foreground:Number(foregroundRef.current), connected:Number(replyPoll.current.remote.connected),
        phase:previous?.phase, done:Number(Boolean(previous?.done)), retired:Number(Boolean(previous?.outputRetired))});
      const status = await remote.client.getPhoneReplyStatus(queued.auth, id);
      assertExplicitAction(context);
      if (!foregroundRef.current || !replyPoll.current.remote.connected || pendingManualReply()?.[1] !== queued) return;
      if (status.phone_request_id !== id) throw new Error('Queued message status could not be verified. Try again.');
      queued.phase = status.phase; reviseBackgroundPolicy();
      if (status.phase !== 'pending') return;
      if (previous.outputRetired || previous.ticket !== ticketRef.current) {
        connectionTrace.event('queued_send_blocked', {reply_id:id, previous_id:previousId, phase:status.phase,
          reason:'predecessor_unavailable', replies:connectionFence.replies.size}, true);
        return;
      }
      queued.queuedBehindId = previousId;
      await skipOwnedReply(previousId);
    }).finally(() => { if (queuedAction.current === job) queuedAction.current = null; });
    queuedAction.current = job;
    return job.promise;
  };
  const phoneAudio = nativePlayback
    ? { available: true, status: 'Phone Native', error: nativeSpeech.error, items: nativeSpeech.chunks }
    : activeState?.media;
  const resumeResponse = async () => {
        const checkpoint = audioQueue.manualRecovery;
        const owner = connectionFence;
        const generation = outputGeneration.current;
        const current = () => owner === backgroundFence.current && generation === outputGeneration.current
          && remote.connected && !backgroundSession.current;
        if (!checkpoint || !current()) throw new Error('Reconnect before resuming.');
        // A headset may resume the existing background output owner. It must
        // never open a replacement lifetime while the app is in the background.
        if (!foregroundRef.current) {
          const state = await capture.outputState();
          if (!current() || !state.open || state.sessionId !== null || state.ticket !== ticketRef.current)
            throw new Error('Return to the app to reconnect audio before resuming.');
        }
        const manifest: AudioChunk[] = [];
        for (const saved of checkpoint.replies) {
          const reply = owner.replies.get(saved.requestId);
          if (!reply || reply.closed || reply.done || reply.auth.reply_continuation_version !== 1)
            throw new Error('This reply is no longer available.');
          let cursor: number | null = 0;
          do {
            const status = await remote.client.getPhoneReplyContinuation(reply.auth, saved.requestId, cursor, -1);
            if (!current() || owner.replies.get(saved.requestId) !== reply || reply.closed || reply.done)
              throw new Error('The conversation changed while resuming.');
            if (!status.continuation.available || status.playback_stop_requested || ['cancelled', 'superseded'].includes(status.phase))
              throw new Error('The saved reply audio has expired or was stopped.');
            manifest.push(...status.continuation.items); cursor = status.continuation.next_cursor;
          } while (cursor !== null);
        }
        if (foregroundRef.current) await ensureForegroundOutput(true, undefined, true);
        if (!current()) throw new Error('The conversation changed while resuming.');
        for (const saved of checkpoint.replies) owner.replies.get(saved.requestId)!.ticket = ticketRef.current;
        reviseBackgroundPolicy();
        // Native ownership is published before the existing queue restores and seeks.
        await ticketCommit.current;
        if (!current() || !await audioQueue.restoreReplyPlayback(checkpoint, manifest, checkpoint.recoveryEpoch))
          throw new Error('Could not restore the saved playback position.');
        setPhoneReplyError('');

  };
  const interruptedReply = React.useRef<{ checkpoint: NonNullable<typeof audioQueue.manualRecovery>;
    owner: typeof connectionFence } | null>(null);
  const resumingInterruptedReply = React.useRef(false);
  React.useEffect(() => {
    if (remote.connected || !audioQueue.currentChunk || audioQueue.paused || audioQueue.manualRecovery
      || !continuationAdvertised || backgroundSession.current || demoMode || storyActive) return;
    // A short peer blip should not stop an otherwise healthy local player.
    // If the peer stays unavailable, save its exact reply position before the
    // following chunk can fail repeatedly while the photo picker is open.
    const timer = setBackgroundTimeout(() => {
      if (remote.connected || connectionFence !== backgroundFence.current) return;
      const checkpoint = audioQueue.suspendForPeerInterruption();
      if (checkpoint) interruptedReply.current = { checkpoint, owner: connectionFence };
    }, 1500);
    return () => timer.cancel();
  }, [remote.connected, audioQueue.currentChunk?.id, audioQueue.paused, audioQueue.manualRecovery,
    continuationAdvertised, demoMode, storyActive, connectionFence]);
  React.useEffect(() => {
    const interrupted = interruptedReply.current;
    if (!interrupted || resumingInterruptedReply.current) return;
    if (interrupted.owner !== connectionFence || (audioQueue.manualRecovery
      && interrupted.checkpoint !== audioQueue.manualRecovery)) {
      interruptedReply.current = null;
      return;
    }
    if (!remote.connected || !remote.connectionRecoveryReady || !foreground
      || audioQueue.manualRecovery !== interrupted.checkpoint) return;
    resumingInterruptedReply.current = true;
    void resumeResponse().catch(error => {
      if (interruptedReply.current === interrupted) {
        setPhoneReplyError(error instanceof Error ? error.message : 'Resume response in Audio to continue.');
      }
    }).finally(() => {
      if (interruptedReply.current === interrupted) interruptedReply.current = null;
      resumingInterruptedReply.current = false;
    });
  }, [remote.connected, remote.connectionRecoveryReady, foreground, audioQueue.manualRecovery,
    connectionFence]);
  const mediaPlayback = { ...audioQueue,
    stop: nativePlayback ? nativeSpeech.stop : audioQueue.stop,
    playNow: async (chunk: AudioChunk) => {
      try {
        let action = explicitActionContext;
        assertExplicitAction(action, true);
        if (guardedOutput && action.session) {
          if (!foregroundRef.current) throw new Error('Return to the app before replaying.');
          const oldTicket = ticketRef.current;
          await backendRecorder.cancelCapture();
          if (backgroundFence.current !== action.owner || backgroundSession.current
            || outputGeneration.current !== action.generation + 1) throw new Error('Playback ownership changed. Try again.');
          const state = await capture.outputState();
          if (state.open || state.ticket !== oldTicket || !foregroundRef.current) throw new Error('Protected playback could not be released.');
          action = { owner: action.owner, session: null, generation: outputGeneration.current, submissionEpoch: submissionEpoch.current };
          Alert.alert('Replay', 'Live is now off. Replaying the selected audio once.');
        }
        await ensureForegroundOutput();
        assertExplicitAction(action);
        await audioQueue.playNow(chunk);
      } catch (failure) {
        Alert.alert('Replay unavailable', failure instanceof Error ? failure.message : 'Replay could not start. Try again.');
      }
    },
  };
  const museTalkSelected = String(runtime?.avatar_engine || '').trim().toLowerCase().includes('musetalk');
  const playbackControlBusy = React.useRef(false);
  const dispatchChatControl = async (action: string, keepOutputForContinuation = false) => {
    if (playbackControlBusy.current) return;
    playbackControlBusy.current = true;
    const context = explicitActionContext;
    try {
      if (demoMode) { await demo.sendControl(action, sendOptions); return; }
      if (!remote.connected || connectionFence !== backgroundFence.current) throw new Error('Reconnect before using chat controls.');
      if (action === 'pause_speech' || action === 'play_speech') {
        if (action === 'play_speech' || audioQueue.paused) {
          if (audioQueue.manualRecovery) await resumeResponse();
          else await audioQueue.resume();
          void soundscape.playback?.resume().catch(()=>undefined);
        } else { await audioQueue.pause();void soundscape.playback?.pause().catch(()=>undefined); }
        return;
      }
      if (action === 'regenerate_response' || action === 'retry_user_input' || action === 'skip_user_reply') {
        const kind = action === 'regenerate_response' ? 'regenerate' : action === 'retry_user_input' ? 'retry' : 'end_waiting';
        const target = activeState?.conversation_actions?.[kind];
        if (!conversationActionsAvailable || !target) throw new Error('No eligible message for this action. Refresh the conversation and try again.');
        await runConversationAction(kind, target); return;
      }
      if (action === 'skip_speech' || action === 'interrupt_response') {
        soundscapeStopEffectRef.current();
        if(action==='interrupt_response')void soundscape.playback?.pause().catch(()=>undefined);
        if (action === 'interrupt_response' && !nativePlayback) {
          // An explicit replay can occupy the player while a different reply
          // still owns the desktop completion gate. Acknowledge that exact
          // reply before interrupt_response clears the desktop media bridge.
          const candidates = [...connectionFence.replies].filter(([, reply]) =>
            !reply.done && !reply.outputRetired && !reply.manualSkipAccepted
            && reply.ticket === ticketRef.current);
          for (const [id, reply] of candidates) {
            const status = await remote.client.getPhoneReplyStatus(reply.auth, id);
            assertExplicitAction(context);
            if (status.phone_request_id !== id) throw new Error('Reply ownership changed. Try again.');
            if (status.phase === 'generating' || status.phase === 'complete') await skipOwnedReply(id);
          }
        }
        if (nativePlayback) { nativeSpeech.stop(); }
        else if (audioQueue.stopExplicitPlayback) { audioQueue.stopExplicitPlayback(); audioQueue.stop(); }
        else if (stoppableReplyId) await skipOwnedReply(stoppableReplyId);
        else audioQueue.stop();
        if (action === 'interrupt_response') {
          assertExplicitAction(context);
          // The generic interrupt cancels retained Desktop receipts too. Their
          // already-confirmed drain/Skip must not let the status observer close
          // this still-current output ticket before Force can submit its successor.
          if (keepOutputForContinuation) {
            for (const reply of connectionFence.replies.values()) {
              if (reply.ticket === ticketRef.current && (reply.done
                || (reply.manualSkipAccepted && reply.auth.shared_queue_version === 1))) {
                // Shared-queue Skip already acknowledges playback completion.
                // Preserve that proof for an independently stopped Live tail.
                reply.done = true; reply.outputRetired = true;
              }
            }
            reviseBackgroundPolicy();
          }
          await remote.sendControl(action, sendOptions);
        }
        return;
      }
      if (action === 'replay_last_assistant' || action === 'replay_chat_session') {
        let items = [...(phoneAudio?.items ?? [])];
        if (action === 'replay_last_assistant') {
          const latest = items.at(-1);
          items = latest?.phone_request_id ? items.filter(item => item.phone_request_id === latest.phone_request_id) : latest ? [latest] : [];
        }
        if (!items.length) throw new Error('No retained phone audio to replay.');
        if (stoppableReplyId) await skipOwnedReply(stoppableReplyId);
        assertExplicitAction(context);
        await ensureForegroundOutput();
        assertExplicitAction(context);
        await audioQueue.playSequence(items); return;
      }
      await remote.sendControl(action, sendOptions);
    } finally { playbackControlBusy.current = false; }
  };
  // Background Live owns its own system commands. These controls only describe
  // the text-chat/replay lifetime, and stale native events cannot revive it.
  const mediaReplyId = continuous.readingUser ? continuous.state?.prepared_id
    : audioQueue.activeReplyId ?? audioQueue.currentChunk?.id ?? audioQueue.manualRecovery?.replies[0]?.requestId;
  const mediaControlToken = React.useMemo(() => `reply-media-${Date.now()}-${++explicitSequence.current}`,
    [connectionFence, playbackTicket, mediaReplyId]);
  const mediaControlScope = !demoMode && !storyActive && !backgroundSession.current && remote.connected
    && (audioQueue.hasReplyAudio || audioQueue.currentChunk || audioQueue.manualRecovery || audioQueue.paused || continuousServiceNeeded)
    ? mediaControlToken : null;
  const notificationAutoOn = Boolean(continuous.state?.owned && !['stopped','paused','suspended'].includes(continuous.state.state));
  const notificationCanAuto = continuousCanClaim && continuousAvailable && Boolean(continuous.state?.settings && continuous.state.settings.mode !== 'off')
    && !continuous.busy && Boolean(continuous.state?.owned) && !continuous.state?.story_complete;
  const notificationCanForce = notificationCanAuto && Boolean(continuous.state?.force_continuation_supported);
  const forceContinuousFromControls = async () => {
    if (!notificationCanForce) throw new Error('Force continuation is unavailable.');
    const context = explicitActionContext;
    assertExplicitAction(context);
    await prepareContinuousOutput(context);
    await continuous.command('pause'); assertExplicitAction(context);
    await dispatchChatControl('interrupt_response', true); assertExplicitAction(context);
    await continuous.command('force_continue');
    setNotificationPauseOwner(owner=>owner===continuousOwner?null:owner);
  };
  const notificationIdlePaused = notificationPauseOwner === continuousOwner && continuous.state?.state === 'paused'
    && !continuous.readingUser && !audioQueue.hasReplyAudio && !audioQueue.currentChunk && !audioQueue.manualRecovery && !audioQueue.paused;
  const notificationCharacter = activeCharacterSpeaker(Boolean(characters.snapshot?.character_voices_enabled),
    audioQueue.currentChunk?.speaker, (characters.snapshot?.characters ?? []).filter(
      card=>card.conversation_id===characters.snapshot?.conversation_id));
  const notificationPortrait = continuous.readingUser ? '' : notificationCharacter ? notificationCharacter.portrait_url_path || ''
    : activeState?.presence?.avatar?.neutral_url_path || (activeState?.presence?.avatar?.kind === 'neutral' ? activeState.presence.avatar.url_path : '') || '';
  const notificationArtwork = useAuthorizedMediaUrl(remote.client, mediaControlScope ? notificationPortrait : '');
  usePhoneMediaControls(mediaControlScope, continuous.readingUser ? !userPlayback.paused
    : audioQueue.isPlaying || (Boolean(audioQueue.isBetweenSegments) && !audioQueue.paused), settings.headphoneNextTogglesPlayback,
    async command => {
      if (backgroundSession.current || recorder.liveEnabled || storyActive || backgroundFence.current !== connectionFence) return;
      const context=explicitActionContext;
      assertExplicitAction(context);
      setNotificationActionPending(true);
      try {
      if (command === 'force_continue') {
        if(!notificationCanForce)throw new Error('Force continuation is unavailable.');
        await forceContinuousFromControls();
      } else if(command==='auto_toggle') {
        if(!notificationCanAuto)throw new Error('Continuous Mode is unavailable.');
        if(!notificationAutoOn)await prepareContinuousOutput(context);
        assertExplicitAction(context);
        if(notificationAutoOn)setNotificationPauseOwner(continuousOwner);
        try {
          await continuous.command(notificationAutoOn?'pause':continuous.state?.state==='stopped'?'start':'resume');
          if(!notificationAutoOn)setNotificationPauseOwner(owner=>owner===continuousOwner?null:owner);
        } catch(error) {
          if(notificationAutoOn)setNotificationPauseOwner(owner=>owner===continuousOwner?null:owner);
          throw error;
        }
      } else if(command==='regenerate') {
        const target=activeState?.conversation_actions?.regenerate;
        if(!target || !conversationActionsAvailable || conversationActionBusy)throw new Error('No reply available to regenerate.');
        await continuous.withManualInput(()=>runConversationAction('regenerate',target,true));
      } else if(command==='stop') {
        if(continuous.state?.owned)await continuous.command('stop');
        assertExplicitAction(context);await dispatchChatControl('interrupt_response');
        setNotificationPauseOwner(owner=>owner===continuousOwner?null:owner);
      } else if(notificationIdlePaused && (command==='play' || command==='toggle' || (command==='next' && settings.headphoneNextTogglesPlayback))) {
        if(!notificationCanAuto)throw new Error('Continuous Mode is unavailable.');
        await prepareContinuousOutput(context);assertExplicitAction(context);
        await continuous.command('resume');
        setNotificationPauseOwner(owner=>owner===continuousOwner?null:owner);
      } else if(continuous.readingUser) {
        if(command==='pause'){userPlayback.pause();void soundscape.playback?.pause().catch(()=>undefined);}
        else if(command==='play'){userPlayback.resume();void soundscape.playback?.resume().catch(()=>undefined);}
        else if(command==='toggle' || (command==='next' && settings.headphoneNextTogglesPlayback)) {
          if(userPlayback.paused){userPlayback.resume();void soundscape.playback?.resume().catch(()=>undefined);}
          else {userPlayback.pause();void soundscape.playback?.pause().catch(()=>undefined);}
        }
      } else if (command === 'pause') { if (!audioQueue.paused) await dispatchChatControl('pause_speech'); }
      else if (command === 'play') { if (audioQueue.paused) await dispatchChatControl('play_speech'); }
      else if (command === 'toggle' || (command === 'next' && settings.headphoneNextTogglesPlayback)) await dispatchChatControl('pause_speech');
      } finally { setNotificationActionPending(false); }
    }, setPhoneReplyError, {
      title:continuous.readingUser?'You':notificationCharacter?.name || activeState?.presence?.persona?.name || 'Companion',
      subtitle:continuous.readingUser?(userPlayback.paused?'Your reply paused':'Reading your reply aloud')
        :audioQueue.paused?'Reply paused':audioQueue.isPlaying?'Assistant speaking':continuous.state?.story_complete?'Story finished · add beats in NC':notificationAutoOn?'Preparing next turn':notificationIdlePaused?'Continuous Mode paused':'Conversation audio',
      artwork:notificationArtwork.url,
      buffering:!notificationIdlePaused && !continuous.readingUser && !audioQueue.paused && !audioQueue.currentChunk && !audioQueue.manualRecovery,
      canRegenerate:conversationActionsAvailable && Boolean(activeState?.conversation_actions?.regenerate) && !conversationActionBusy && !continuous.busy,
      canForce:notificationCanForce,canAuto:notificationCanAuto,autoOn:notificationAutoOn,
    });
  const museTalkLiveEligible = Boolean((muxedTrialSelected ? muxedPlayback.runtime?.player : bufferedPlayback.runtime && bufferedPlayback.presentation) && museTalkSelected
    && !demoMode && foreground
    && !storyActive && !nativePlayback && playbackSource === 'hq' && musetalkAvailable);
  const museTalkPresentation = useMuseTalkLivePresentation({
    liveEnabled: recorder.liveEnabled,
    museTalkSelected,
    available: museTalkLiveEligible,
    owner: connectionFence,
    retainSelectionWhileUnavailable: orderedConnectionAvailable && !demoMode && !storyActive && !nativePlayback
      && settings.audioMode === 'backend_hq' && musetalkAvailable,
    diagnosticAvailability: {playerPresent:Boolean(muxedPlayback.runtime?.player),
      bufferedRuntimePresent:Boolean(bufferedPlayback.runtime),bufferedPresentationPresent:Boolean(bufferedPlayback.presentation),
      muxedSelected:muxedTrialSelected,demoMode,foreground,storyActive,nativePlayback,
      hqSelected:playbackSource==='hq',musetalkAvailable},
  });
  React.useEffect(() => {
    avatarPresentation.remeasure();
  }, [avatarPresentation.remeasure, visibleSurface, settings.companionDisplayMode,
    settings.showPresenceControls, androidKeyboardVisible, museTalkPresentation.fullscreen]);
  const [liveSessionRendering, setLiveSessionRendering] = React.useState(false);
  const [desktopControlsVisible, setDesktopControlsVisible] = React.useState(false);
  const [selectedControlMessage, setSelectedControlMessage] = React.useState<{owner: typeof connectionFence; message: ChatMessage} | null>(null);
  React.useEffect(() => {
    responseStoryPlanRequest.current++;
    setResponseStoryPlan(null);
    setResponseStoryPlanLoading(false);
    setResponseStoryPlanError('');
  }, [connectionFence, conversationGeneration]);
  const loadResponseStoryPlan = async () => {
    const request = ++responseStoryPlanRequest.current;
    const owner = connectionFence;
    const generation = conversationGeneration;
    setResponseStoryPlan(null);
    setResponseStoryPlanError('');
    if (!remote.connected || activeState?.features?.story_plan_version !== 1
      || !Number.isSafeInteger(generation)) {
      setResponseStoryPlanLoading(false);
      return;
    }
    setResponseStoryPlanLoading(true);
    try {
      const plan = await remote.client.storyPlan({action:'status',session_generation:generation!});
      if (request === responseStoryPlanRequest.current && owner === backgroundFence.current)
        setResponseStoryPlan(plan);
    } catch (error) {
      if (request === responseStoryPlanRequest.current && owner === backgroundFence.current)
        setResponseStoryPlanError(error instanceof Error ? error.message : 'Could not check Story Plan progress.');
    } finally {
      if (request === responseStoryPlanRequest.current && owner === backgroundFence.current)
        setResponseStoryPlanLoading(false);
    }
  };
  const nextResponseStoryBeat = async () => {
    const plan = responseStoryPlan;
    const selection = selectedControlMessage;
    if (!plan || plan.status !== 'active' || plan.current_beat + 1 >= plan.beats.length)
      throw new Error('There is no next Story Plan beat.');
    if (!selection || selection.owner !== backgroundFence.current || !remote.connected
      || !Number.isSafeInteger(conversationGeneration))
      throw new Error('Reconnect and reopen the response menu.');
    try {
      const updated = await remote.client.storyPlan({action:'beat',revision:plan.revision,
        index:plan.current_beat + 1,session_generation:conversationGeneration!});
      if (selection.owner !== backgroundFence.current) throw new Error('The conversation changed.');
      if (updated) {
        setResponseStoryPlan(updated);
        if (!storyPlanDraft) setSavedStoryPlan(updated);
      }
    } catch (error) {
      if (error instanceof Error && /changed|refresh/i.test(error.message)) {
        await loadResponseStoryPlan();
        throw new Error('The story beat changed. Review the current beat before pressing Next again.');
      }
      throw error;
    }
  };
  const changeResponseStoryPace = async (pace: StoryPace) => {
    const plan = responseStoryPlan;
    const selection = selectedControlMessage;
    if (!plan || plan.status !== 'active') throw new Error('There is no active Story Plan.');
    if (!selection || selection.owner !== backgroundFence.current || !remote.connected
      || !Number.isSafeInteger(conversationGeneration))
      throw new Error('Reconnect and reopen the response menu.');
    try {
      const updated = await remote.client.storyPlan({action:'pace',revision:plan.revision,
        pace,session_generation:conversationGeneration!});
      if (selection.owner !== backgroundFence.current) throw new Error('The conversation changed.');
      if (!updated) throw new Error('The Story Plan is no longer available.');
      setResponseStoryPlan(updated);
      if (!storyPlanDraft) setSavedStoryPlan(updated);
    } catch (error) {
      if (error instanceof Error && /changed|refresh/i.test(error.message)) {
        await loadResponseStoryPlan();
        throw new Error('The Story Plan changed. Review its pace and try again.');
      }
      throw error;
    }
  };
  const imageRequestBusy = React.useRef(false);
  const generateMessageImage = async (message: ChatMessage) => {
    if (imageRequestBusy.current) throw new Error('An image request is already being sent.');
    if (!message.content.trim()) throw new Error('This response is no longer available.');
    if (!demoMode && !remote.connected) throw new Error('Reconnect before generating an image.');
    imageRequestBusy.current = true;
    try {
      const existing = message.visual_replies?.find(item => item.turn_id || item.normal_chat_transaction_id);
      const result = await (demoMode ? demo.visualGenerate(message.content) : remote.visualGenerate(message.content, {
        turnId: message.turn_id || existing?.turn_id || message.id,
        normalChatTransactionId: existing?.normal_chat_transaction_id,
        refinePrompt: true,
      }));
      const error = remoteActionError(result, 'Visual Reply did not accept the image request.');
      if (error) throw new Error(error);
    } finally { imageRequestBusy.current = false; }
  };
  const generateSelectedMessageImage = async () => {
    const selection = selectedControlMessage;
    if (!selection || selection.owner !== backgroundFence.current) throw new Error('Open the response controls again.');
    const message = activeState?.chat?.messages?.find(item => item.id === selection.message.id && item.role === 'assistant');
    if (!message) throw new Error('This response is no longer available.');
    await generateMessageImage(message);
  };
  const latestVisualSource = [...(activeState?.chat?.messages ?? [])].reverse()
    .find(item => item.role === 'assistant' && item.content.trim());
  const generateLatestVisual = async () => {
    if (!latestVisualSource || visualButtonBusy) return;
    setVisualButtonBusy(true); setVisualButtonError('');
    try { await generateMessageImage(latestVisualSource); }
    catch (error) { setVisualButtonError(error instanceof Error ? error.message : 'Image request failed.'); }
    finally { setVisualButtonBusy(false); }
  };
  const refreshVisualAuto = async () => {
    if (!Number.isSafeInteger(conversationGeneration)) throw new Error('Reconnect to view Visual Reply settings.');
    const status = await remote.client.visualAuto({ action: 'status', session_generation: conversationGeneration! });
    setVisualAutoStatus(status);
  };
  const openVisualSettings = () => {
    visualLongPressAt.current = Date.now();
    setVisualSettingsVisible(true); setVisualAutoStatus(null); setVisualAutoError('');
    void refreshVisualAuto().catch(error => setVisualAutoError(
      error instanceof Error ? error.message : 'Could not load Visual Reply settings.'));
  };
  const changeVisualAuto = async (mode: VisualAutoMode, imagesPerBeat: number) => {
    if (!visualAutoStatus || !Number.isSafeInteger(conversationGeneration) || visualAutoBusy) return;
    setVisualAutoBusy(true); setVisualAutoError('');
    try {
      setVisualAutoStatus(await remote.client.visualAuto({ action: 'update',
        session_generation: conversationGeneration!, revision: visualAutoStatus.revision,
        mode, images_per_beat: imagesPerBeat }));
    } catch (error) {
      setVisualAutoError(error instanceof Error ? error.message : 'Could not save Visual Reply settings.');
    } finally { setVisualAutoBusy(false); }
  };
  const museTalkOwner = React.useRef({ value: connectionFence, revision: 0 });
  if (museTalkOwner.current.value !== connectionFence) {
    museTalkOwner.current = { value: connectionFence, revision: museTalkOwner.current.revision + 1 };
  }
  const museTalkEnvironmentKey = `${museTalkOwner.current.revision}:${museTalkSelected}:${storyActive}:${nativePlayback}:${playbackSource}:${musetalkAvailable}:${demoMode}:${muxedTrialSelected}`;
  const previousMuseTalkEnvironment = React.useRef(museTalkEnvironmentKey);
  const [museTalkInvalidationRevision, setMuseTalkInvalidationRevision] = React.useState(0);
  React.useEffect(() => {
    if (previousMuseTalkEnvironment.current !== museTalkEnvironmentKey) {
      previousMuseTalkEnvironment.current = museTalkEnvironmentKey;
      setMuseTalkInvalidationRevision(value => value + 1);
    }
  }, [museTalkEnvironmentKey]);
  visualOwnerRef.current = museTalkLiveEligible || liveSessionRendering ? 'session' : 'none';
  const openPresentation = React.useCallback(() => {
    if (museTalkSelected && museTalkLiveEligible) museTalkPresentation.open();
    else setLiveFullscreenVisible(true);
  }, [museTalkSelected, museTalkLiveEligible, museTalkPresentation.open]);
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

  const chatFeed = (composer: React.ReactElement<React.ComponentProps<typeof Composer>>) => (
    <View style={{flex: 1}}>
    <CharacterCandidateNotice key={characters.snapshot?.conversation_id||'no-conversation'}
      busy={characters.busy} error={characters.error}
      onDiscard={()=>{const snapshot=characters.snapshot;const candidate=snapshot?.candidates?.[0];
        if(candidate&&snapshot)void characters.mutate(`/${candidate.id}/discard`,{
          expected_revision:snapshot.revision,conversation_id:snapshot.conversation_id}).catch(()=>undefined);}}
      candidate={characters.snapshot?.character_voices_enabled&&characters.snapshot?.allow_new_characters
        ?characters.snapshot?.candidates?.[0]:undefined}
      onAssignExisting={()=>{const snapshot=characters.snapshot;const candidate=snapshot?.candidates?.[0];
        if(candidate&&snapshot)setAssignmentCandidate({id:candidate.id,name:candidate.name,
          conversationId:snapshot.conversation_id});}}
      onReview={()=>{setInitialCharacterId('');setCharactersVisible(true);}}/>
    <CharacterNotice card={characters.snapshot?.characters.find(c=>c.conversation_id===characters.snapshot?.conversation_id&&!c.notice_dismissed&&!c.voice_id)}
      busy={characters.busy} error={characters.error}
      onDiscard={()=>{const snapshot=characters.snapshot;
        const card=snapshot?.characters.find(c=>c.conversation_id===snapshot.conversation_id&&!c.notice_dismissed&&!c.voice_id);
        if(card&&snapshot)void characters.mutate(`/${card.id}/discard`,{
          expected_revision:card.revision,conversation_id:snapshot.conversation_id}).catch(()=>undefined);}}
      onOpen={()=>{const card=characters.snapshot?.characters.find(c=>c.conversation_id===characters.snapshot?.conversation_id&&!c.notice_dismissed&&!c.voice_id);
        setInitialCharacterId(card?.id||'');setCharactersVisible(true);}}
      onDismiss={()=>{const card=characters.snapshot?.characters.find(c=>c.conversation_id===characters.snapshot?.conversation_id&&!c.notice_dismissed&&!c.voice_id);
        if(card)void characters.mutate(`/${card.id}/dismiss-notice`,{expected_revision:card.revision}).catch(()=>undefined);}}/>
    <ReadingConversation
      soundMenu={settings.showSoundsMenu===true&&!demoMode&&!storyActive?<ChatSoundsMenu sound={soundscape.controls}
        onLibrary={()=>{setSoundscapeEditId('');setSoundscapeVisible(true);}}
        onEditAsset={asset=>{setSoundscapeEditId(asset.id);setSoundscapeVisible(true);}}/>:undefined}
      composer={composer}
      onOpenResponseControls={() => {
        Keyboard.dismiss();
        const latest = [...(activeState?.chat?.messages ?? [])].reverse().find(message => message.role === 'assistant');
        setSelectedControlMessage(latest ? {owner:connectionFence,message:latest} : null);
        setDesktopControlsVisible(true);
        void loadResponseStoryPlan();
      }}
      onGenerateVisual={settings.showVisualButton !== false && activeState?.features?.visual_reply_controls ? () => {
        if (Date.now() - visualLongPressAt.current < 700) return;
        void generateLatestVisual();
      } : undefined}
      onVisualOptions={openVisualSettings}
      visualDisabled={!remote.connected || !latestVisualSource || visualButtonBusy}
      playback={mediaPlayback}
      scope={`${remote.client.identityKey}:${conversationGeneration}:${demoMode}`}
      visible={foreground && visibleSurface === 'chat'}
      settings={settings}
      onSettingsChange={setSettings}
      onControl={dispatchChatControl}
      canReplay={Boolean(phoneAudio?.items?.length)}
      endWaitingTarget={settings.showConversationControls !== false && conversationActionsAvailable && !conversationActionBusy
        ? activeState?.conversation_actions?.end_waiting : null}
      onEndWaiting={target => runConversationAction('end_waiting', target)}
      messages={displayMessages}
      automatedUserText={continuous.userSpeechText}
      automatedUserPlayback={continuous.readingUser ? userPlayback.reading : undefined}
      presence={livePresence}
      client={remote.client}
      conversationAvatarSize={settings.conversationAvatarSize}
      visualDisplay={settings.visualDisplay}
      textColor={settings.chatTextColor}
      indicatorStyle={settings.chatIndicatorStyle}
      activity={presenceActivity}
      disabled={!commandsAvailable}
      presenceMode={settings.companionDisplayMode === 'companion' ? 'companion' : 'conversation'}
      onOpenVisualReply={setFocusedVisualReply}
      onRetryVisualReply={async (item) => {
        const prompt = String(item.prompt_preview || item.caption || '').trim();
        if (!prompt) {
          await enterMediaSurface('visual');
          return;
        }
        await enterMediaSurface('visual');
        await (demoMode
          ? demo.visualGenerate(prompt)
          : remote.visualGenerate(prompt, {
            turnId: item.turn_id,
            normalChatTransactionId: item.normal_chat_transaction_id,
          }));
      }}
      onOpenVisualPanel={() => { void enterMediaSurface('visual').catch(() => undefined); }}
      onAvatarLongPress={openAvatarControls}
      onOpenDesktopControls={message => { Keyboard.dismiss(); setSelectedControlMessage({owner: connectionFence, message}); setDesktopControlsVisible(true); void loadResponseStoryPlan(); }}
      connected={commandsAvailable}
    />
    </View>
  );
  const commandOwner = connectionFence;
  const commandSession = conversationGeneration;
  const commandScopeKey = `${remote.client.identityKey}:${conversationGeneration}:${demoMode}`;
  React.useEffect(() => {
    setStoryRefineSetup(current => current && current.owner !== commandScopeKey ? null : current);
    if (storyPlanOwner.current && storyPlanOwner.current !== commandScopeKey) {
      storyPlanOwner.current = '';
      setStoryPlanVisible(false); setStoryPlanDraft(null); setSavedStoryPlan(null);
      setStoryRefineSettings(null); setStoryRefineCandidate(null); setStoryRefineCandidateSettings(null);
      setStoryExtension(null); setStoryExtensionDraft(null);
      storyAppendAttempt.current = null;
      setStoryOpeningPending(false);
    }
  }, [commandScopeKey]);
  const commandCurrent = () => commandOwner === backgroundFence.current && foregroundRef.current
    && manualScope.current.connected && commandSession === replyPoll.current.remote.state?.conversation_actions?.session_generation;
  const draftCurrent = () => commandOwner === backgroundFence.current
    && typeof commandSession === 'number'
    && commandSession === replyPoll.current.remote.state?.conversation_actions?.session_generation;
  const commandBlocked = !chatCommandsAvailable || demoMode ? 'Connect to the desktop first.'
    : recorder.recording || recorder.busy ? 'Finish the microphone recording first.'
    : conversationActionBusy ? 'Wait for the current conversation action.' : '';
  React.useEffect(() => {
    if (!continuous.state?.story_complete) setStoryCompletionDismissed(false);
  }, [continuous.state?.story_complete]);
  const storyPlanAction = async (action: Omit<StoryPlanAction, 'session_generation'>) => {
    if (storyPlanOperation.current) throw new Error('A Story Plan action is already in progress.');
    if (!commandCurrent() || storyPlanOwner.current !== commandScopeKey
      || typeof conversationGeneration !== 'number')
      throw new Error('The conversation changed. Reopen Story Plan.');
    storyPlanOperation.current = true;
    setStoryPlanBusy(true); setStoryPlanError('');
    try {
      const result = await remote.client.storyPlan({ ...action, session_generation: conversationGeneration });
      if (!commandCurrent() || storyPlanOwner.current !== commandScopeKey)
        throw new Error('The conversation changed. Reopen Story Plan.');
      setSavedStoryPlan(result);
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Story Plan request failed.';
      setStoryPlanError(message);
      throw error;
    } finally { storyPlanOperation.current = false; setStoryPlanBusy(false); }
  };
  const openStoryPlan = async () => {
    storyPlanOwner.current = commandScopeKey;
    setStoryPlanVisible(true); setStoryPlanError('');
    if (storyPlanDraft) return;
    try { await storyPlanAction({ action: 'status' }); } catch { /* Error shown in the panel. */ }
  };
  const saveStoryPlan = async (plan: StoryPlanDraft) => {
    try {
      await storyPlanAction({ action: 'save', plan });
      setStoryPlanDraft(null); setStoryOpeningPending(false);
    } catch { /* Error shown in the panel. */ }
  };
  const sendRefinedStory = async (plan: StoryPlanDraft) => {
    if (storyPlanOperation.current) return;
    if (!commandCurrent() || storyPlanOwner.current !== commandScopeKey) {
      setStoryPlanError('The conversation changed. Reopen Story Plan.'); return;
    }
    storyPlanOperation.current = true; setStoryPlanBusy(true); setStoryPlanError('');
    try { await sendPhoneText(storyPlanToChatPrompt(plan)); setStoryPlanDraft(null); setStoryPlanVisible(false); }
    catch (error) { setStoryPlanError(error instanceof Error ? error.message : 'Story prompt could not be sent.'); }
    finally { storyPlanOperation.current = false; setStoryPlanBusy(false); }
  };
  const sendStoryOpening = async (plan: StoryPlan) => {
    if (storyPlanOperation.current) return;
    if (!commandCurrent() || storyPlanOwner.current !== commandScopeKey) {
      setStoryPlanError('The conversation changed. Reopen Story Plan.'); return;
    }
    storyPlanOperation.current = true; setStoryPlanBusy(true); setStoryPlanError('');
    try {
      await sendPhoneText(plan.opening_cue);
      setStoryOpeningPending(false); setStoryPlanVisible(false);
    } catch (error) {
      setStoryOpeningPending(true);
      setStoryPlanError(error instanceof Error ? error.message : 'Opening cue could not be sent.');
    } finally { storyPlanOperation.current = false; setStoryPlanBusy(false); }
  };
  const startStoryPlan = async () => {
    if (!savedStoryPlan) return;
    try {
      const started = await storyPlanAction({ action: 'start', revision: savedStoryPlan.revision });
      if (started) await sendStoryOpening(started);
    } catch { /* Error shown in the panel. */ }
  };
  const extendStoryPlan = async () => {
    try {
      storyPlanOwner.current = commandScopeKey;
      // Stop automatic successors while reviewing; let existing speech finish.
      const mode = continuous.state?.settings?.mode ?? 'off';
      if (mode !== 'off') await continuous.command('pause', {preserve_user_speech:true});
      const source = await storyPlanAction({action:'status'});
      if (!source?.plan_id || source.status === 'saved') throw new Error('Start the story before adding beats.');
      setStoryExtension({source, operationId:Crypto.randomUUID().replace(/-/g,''), mode});
      storyAppendAttempt.current = null;
      setStoryExtensionDraft(null); setStoryPlanVisible(false);
    } catch (error) {
      setStoryPlanError(error instanceof Error ? error.message : 'Could not extend story.');
      setStoryPlanVisible(true);
    }
  };
  const appendStoryBeats = async (draft:StoryPlanDraft, resume:boolean) => {
    const extension = storyExtension;
    if (!extension) return;
    const pace = draft.pace ?? extension.source.pace;
    const signature = JSON.stringify([extension.source.plan_id, draft.beats, pace]);
    try {
      const currentMode = continuous.state?.settings?.mode;
      if (currentMode && currentMode !== 'off') await continuous.command('pause', {preserve_user_speech:true});
      let attempt = storyAppendAttempt.current?.signature === signature ? storyAppendAttempt.current : null;
      if (!attempt) {
        const latest = await storyPlanAction({action:'status'});
        if (!latest || latest.plan_id !== extension.source.plan_id
          || JSON.stringify(latest.beats) !== JSON.stringify(extension.source.beats))
          throw new Error('The story changed while refining. Reopen Add beats to review the latest story.');
        attempt = {signature, revision:latest.revision,
          operationId:storyAppendAttempt.current ? Crypto.randomUUID().replace(/-/g,'') : extension.operationId};
        storyAppendAttempt.current = attempt;
      }
      const appended = await storyPlanAction({action:'append', plan_id:extension.source.plan_id,
        revision:attempt.revision, operation_id:attempt.operationId,
        beats:draft.beats, pace});
      if (!appended) return;
      setStoryExtension(null); setStoryExtensionDraft(null); setStoryPlanDraft(null);
      storyAppendAttempt.current = null;
      setStoryPlanVisible(true);
      if (resume) {
        const mode = continuous.state?.settings?.mode;
        if (!mode || mode === 'off' || mode !== extension.mode) {
          setStoryPlanError('Beats added and saved paused. Choose your Continuous Mode, then Resume.'); return;
        }
        try {
          await prepareContinuousOutput(explicitActionContext);
          await continuous.command('resume');
          setStoryPlanVisible(false);
        } catch {setStoryPlanError('Beats added and saved paused. Tap Resume when connected and ready.');}
      }
    } catch (error) {
      // The original operation id is retained for a safe retry after a lost response.
      setStoryPlanError(error instanceof Error ? error.message : 'Could not add beats. Reconnect and retry.');
    }
  };
  const controlStoryPlan = async () => {
    try {
      if (savedStoryPlan?.status === 'complete') throw new Error('Story finished. Add beats to continue.');
      if (!continuous.state?.settings || continuous.state.settings.mode === 'off')
        throw new Error('Choose Simple or AI Guided in Continuous Mode first.');
      if (['waiting','generating','ready','delay'].includes(continuous.state.state)) {
        await continuous.command('pause', {preserve_user_speech:true});
        if (continuous.readingUser) userPlayback.pause(); else await audioQueue.pause();
      } else {
        await prepareContinuousOutput(explicitActionContext);
        if (continuous.readingUser && userPlayback.paused) userPlayback.resume();
        else if (audioQueue.paused) await audioQueue.resume();
        await continuous.command('resume', {preserve_user_speech:true});
      }
    } catch (error) {setStoryPlanError(error instanceof Error ? error.message : 'Could not change story playback.');}
  };
  const libraryAvailable = !demoMode && remote.connected && activeState?.features?.story_library_version === 1
    && Number.isSafeInteger(conversationGeneration);
  React.useEffect(() => {
    if (!libraryAvailable) return;
    const sequence = ++storyLibraryReadSeq.current;
    let current = true;
    void remote.client.storyLibrary({action:'list',session_generation:conversationGeneration!})
      .then(result => {
        if (current && sequence === storyLibraryReadSeq.current) {
          setStoryLibraryEntries(result.entries ?? []);
          setActiveStoryEntryId(result.active_entry_id ?? null);
          setStoryTransport('play');
        }
      }).catch(() => undefined);
    return () => {current = false;};
  }, [libraryAvailable, remote.client, conversationGeneration]);
  const refreshStoryLibrary = async () => {
    if (!libraryAvailable || !draftCurrent()) throw new Error('Reconnect before opening Story Library.');
    const owner = backgroundFence.current;
    const sequence = ++storyLibraryReadSeq.current;
    const result = await remote.client.storyLibrary({action:'list', session_generation:conversationGeneration!});
    if (owner !== backgroundFence.current) throw new Error('The connection changed. Reopen Story Library.');
    if (sequence === storyLibraryReadSeq.current) {
      setStoryLibraryEntries(result.entries ?? []);
      setActiveStoryEntryId(result.active_entry_id ?? null);
    }
  };
  const openStoryLibrary = () => {
    setStoryLibraryVisible(true); setStoryLibraryError('');
    void refreshStoryLibrary().catch(error => setStoryLibraryError(error instanceof Error ? error.message : 'Could not load Story Library.'));
  };
  const libraryMutation = async (action: StoryLibraryAction['action'], fields: Pick<StoryLibraryAction, 'name' | 'entry_id'> = {}) => {
    if (storyLibraryOperation.current) throw new Error('Wait for the current Story Library action.');
    if (!libraryAvailable || !draftCurrent()) throw new Error('The conversation changed. Reopen Story Library.');
    const owner = backgroundFence.current;
    const saveRequest = action === 'save' || action === 'save_as';
    const signature = JSON.stringify([action, conversationGeneration, fields]);
    const operationId = saveRequest && storySaveRetry.current?.signature === signature
      ? storySaveRetry.current.operationId : Crypto.randomUUID();
    if (saveRequest) storySaveRetry.current = {signature, operationId};
    storyLibraryReadSeq.current++;
    storyLibraryOperation.current = true; setStoryLibraryBusy(true);
    setStoryLibraryActivity(action === 'open' ? 'Opening saved story…'
      : action === 'save' || action === 'save_as' ? 'Saving story…' : 'Updating library…');
    setStoryLibraryError('');
    try {
      const result = await remote.client.storyLibrary({action, session_generation:conversationGeneration!,
        operation_id:operationId, ...fields});
      if (saveRequest) storySaveRetry.current = null;
      if (owner !== backgroundFence.current) throw new Error('The connection changed. Refresh Story Library.');
      if (action === 'open') {
        audioQueue.reset(); userPlayback.reset();
        setActiveStoryEntryId(result.entry_id ?? null);
        setStoryTransport('play'); setSavedStoryPlan(null); setStoryPlanDraft(null);
        setStoryPlanVisible(false); setStoryLibraryVisible(false);
        try { await remote.refresh(); await characters.refresh(); }
        catch { setPhoneReplyError('Story opened. Refresh chat if its new state is not visible yet.'); }
      } else {
        if (action === 'save' || action === 'save_as') {
          setActiveStoryEntryId(result.entry_id ?? null);
          Alert.alert('Story saved', `“${result.name}” · version ${result.version}`);
        }
        try {
          const sequence = ++storyLibraryReadSeq.current;
          const refreshed = await remote.client.storyLibrary({action:'list', session_generation:conversationGeneration!});
          if (owner === backgroundFence.current && sequence === storyLibraryReadSeq.current) {
            setStoryLibraryEntries(refreshed.entries ?? []);
            setActiveStoryEntryId(refreshed.active_entry_id ?? null);
          }
        } catch { setStoryLibraryError('Story change completed. Refresh the library list to see it.'); }
      }
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Story Library action failed.';
      if (saveRequest && error instanceof RemoteRequestError && error.status < 500)
        storySaveRetry.current = null;
      const recovery = /^Story Open failed and automatic recovery failed\. Recovery snapshot: ([a-f0-9]{32})$/.exec(message);
      if (recovery) {
        setStoryRecoveryId(recovery[1] ?? null);
        setStoryLibraryError('Open failed, and the previous chat needs recovery.');
      } else setStoryLibraryError(message);
      throw error;
    } finally { storyLibraryOperation.current = false; setStoryLibraryBusy(false); setStoryLibraryActivity(''); }
  };
  const saveCurrentStory = async (name = '') => {
    if (!activeStoryEntryId) {
      if (!name.trim()) throw new Error('Enter a name before saving this story.');
      await libraryMutation('save_as', {name:name.trim()});
    } else await libraryMutation('save');
  };
  const openSavedStory = async (entry: StoryLibraryEntry, saveCurrent: boolean, currentName: string) => {
    try {
      if (recorder.liveEnabled) throw new Error('Stop Live Mode before opening a saved story.');
      if (saveCurrent) {
        if (activeStoryEntryId) await saveCurrentStory();
        else if (currentName.trim()) await libraryMutation('save_as', {name:currentName.trim()});
        else throw new Error('Enter a name to save the current story first.');
      }
      if (continuous.readingUser || !['stopped', 'paused'].includes(continuous.state?.state ?? 'stopped'))
        await continuous.command('pause');
      await endPhoneReplyOutput();
      audioQueue.stop();
      await libraryMutation('open', {entry_id:entry.entry_id});
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Could not open saved story.';
      if (!/^Story Open failed and automatic recovery failed\./.test(message))
        setStoryLibraryError(message);
    }
  };
  const controlSavedStory = async () => {
    if (storyLibraryOperation.current) throw new Error('Wait for the current Story Library action.');
    storyLibraryOperation.current = true; setStoryLibraryBusy(true);
    setStoryLibraryActivity('Updating story playback…'); setStoryLibraryError('');
    try {
      if (!activeStoryEntryId || !libraryAvailable || !draftCurrent()) throw new Error('Open a saved story first.');
      if (storyTransport === 'play') {
        if (!activeState?.chat?.messages?.some(message => message.role === 'assistant'))
          throw new Error('Start the Story Plan first to create its opening reply.');
        if (!continuous.state?.settings || continuous.state.settings.mode === 'off')
          throw new Error('Choose Simple or AI Guided in Continuous Mode controls first.');
        await prepareContinuousOutput(explicitActionContext);
        await continuous.command('force_continue');
        if(soundscape.controls.state?.enabled)void soundscape.controls.resume().catch(()=>undefined);
        setStoryTransport('pause');
      } else if (storyTransport === 'pause') {
        await continuous.command('pause', {preserve_user_speech:true});
        setStoryTransport('resume');
        if (continuous.readingUser) userPlayback.pause();
        else await audioQueue.pause();
      } else {
        await continuous.command('resume', {preserve_user_speech:true});
        try {
          if (continuous.readingUser && userPlayback.paused) userPlayback.resume();
          else if (audioQueue.paused) await audioQueue.resume();
        } catch (error) {
          await continuous.command('pause', {preserve_user_speech:true}).catch(() => undefined);
          throw error;
        }
        if(soundscape.controls.state?.enabled)void soundscape.controls.resume().catch(()=>undefined);
        setStoryTransport('pause');
      }
    } catch (error) {
      setStoryLibraryError(error instanceof Error ? error.message : 'Story playback control failed.');
      throw error;
    } finally { storyLibraryOperation.current = false; setStoryLibraryBusy(false); setStoryLibraryActivity(''); }
  };
  const recoverPreviousStory = async () => {
    if (!storyRecoveryId || storyLibraryOperation.current) return;
    storyLibraryOperation.current = true; setStoryLibraryBusy(true); setStoryLibraryActivity('Recovering previous chat…');
    try {
      const result = await remote.client.storyLibrary({action:'recover',
        session_generation:conversationGeneration ?? -1, recovery_id:storyRecoveryId});
      if (!result.recovered) throw new Error('NC could not confirm recovery.');
      setStoryRecoveryId(null); setStoryLibraryError('Previous chat restored.');
      setStoryTransport('play');
      await remote.refresh();
    } catch (error) {
      setStoryLibraryError(error instanceof Error ? error.message : 'Recovery failed. Keep this window open and retry.');
      throw error;
    } finally { storyLibraryOperation.current = false; setStoryLibraryBusy(false); setStoryLibraryActivity(''); }
  };
  const actionCommand = (name: string, description: string, run: () => void | Promise<unknown>, reason = '', local = false): SlashCommand => ({
    name, description, disabledReason: reason,
    run: async argument => {
      noCommandArguments(argument, `/${name}`);
      if (!local && !commandCurrent()) throw new Error('The connection changed. Try again.');
      await run();
    },
  });
  const phoneCommands: SlashCommand[] = [
    {name:'commands', description:'Show available commands'},
    actionCommand('persona', 'Choose a saved desktop persona', () => {
      setPersonaSheetTab('persona'); setAvatarControlsVisible(true);
    }, commandBlocked),
    actionCommand('model', 'Choose the desktop provider and model', () => {
      setPersonaSheetTab('model'); setAvatarControlsVisible(true);
    }, commandBlocked),
    actionCommand('web', `Turn Web Search ${activeState?.controls?.web_search?.enabled ? 'off' : 'on'}`, async () => {
      await remote.sendControl(activeState?.controls?.web_search?.enabled ? 'web_search_off' : 'web_search_on');
    }, commandBlocked || (!activeState?.controls?.web_search?.available ? 'Web Search unavailable. Update/restart NC and enable its Web Search addon.' : '')),
    actionCommand('audio', 'Open speech playback and volume controls', () => setSecondarySurface('audio'), '', true),
    actionCommand('skip', queuedMessage ? 'Stop this reply and advance your queued message' : 'Skip the current reply audio', async () => {
      if (queuedMessage) await processQueuedMessage();
      else if (nativePlayback) nativeSpeech.stop();
      else if (audioQueue.stopExplicitPlayback) audioQueue.stopExplicitPlayback();
      else if (stoppableReplyId) await skipOwnedReply(stoppableReplyId);
    }, commandBlocked || (!(queuedMessage || canStopSpeech || (nativePlayback && phonePlaybackActive)) ? 'No active reply to skip.' : '')),
    actionCommand('replay', 'Replay the latest retained audio, as in Audio controls', async () => {
      const latest = phoneAudio?.items?.at(-1);
      if (latest) await mediaPlayback.playNow(latest);
    }, commandBlocked || (!phoneAudio?.items?.length ? 'No retained audio to replay.' : '')),
    ...(['regenerate', 'retry'] as const).map(kind => actionCommand(kind,
      kind === 'regenerate' ? 'Generate another answer' : 'Retry the previous user message', async () => {
        const target = activeState?.conversation_actions?.[kind];
        if (target) await runConversationAction(kind, target);
      }, commandBlocked || (!conversationActionsAvailable || !activeState?.conversation_actions?.[kind] ? 'No eligible message for this action.' : ''))),
    {name:'live', usage:'/live <on|off>', description:`Hands-free listening is ${recorder.liveEnabled ? 'On' : 'Off'}; Off lets the reply finish`,
      disabledReason: (!recorder.liveEnabled && (!phoneSttAvailable || Boolean(commandBlocked))) ? commandBlocked || 'Speech recognition is unavailable.' : '',
      run: async argument => {
        if (!['on', 'off'].includes(argument.toLowerCase())) throw new Error('Use /live on or /live off.');
        if (!commandCurrent()) throw new Error('The connection changed. Try again.');
        const wanted = argument.toLowerCase() === 'on';
        if (wanted !== recorder.liveEnabled) await recorder.toggleLive();
      }},
    actionCommand('visual', 'Open Visual Reply controls', () => enterMediaSurface('visual'), '', true),
    actionCommand('settings', 'Open phone settings', () => setSecondarySurface('settings'), '', true),
    actionCommand('reset', 'Reset the shared conversation — asks for confirmation', confirmChatReset,
      commandBlocked || (activeState?.features?.chat_reset !== true ? 'Desktop reset is unavailable.' : '')),
    ...['refine', 'rewrite', 'shorten', 'translate', 'ideas'].map(name => {
      const definition = activeState?.command_drafts?.find(item => item.name === name);
      return { name, usage:`/${name} <text>`, description:definition?.description || 'Create an editable draft before sending',
        disabledReason: commandBlocked || (!definition ? 'Update and restart NC desktop to enable writing drafts.'
          : activeState?.runtime_status?.running !== true ? 'Start the desktop runtime before drafting.' : ''),
        run: async (argument: string, signal: AbortSignal) => {
          const result = await requestCommandDraft(remote.client, name, argument, signal, commandCurrent);
          return 'draft' in result ? result : undefined;
        },
      };
    }),
    {name:'story_refine', usage:'/story_refine <story idea>', description:'Refine a long story into an editable plan',
      disabledReason:commandBlocked || (!activeState?.command_drafts?.some(item => item.name === 'story_refine')
        ? 'Update and restart NC desktop to enable Story Plans.'
        : activeState?.features?.story_refine_options_version !== 1 ? 'Restart the updated NC desktop to enable Story Refine options.'
        : activeState?.runtime_status?.running !== true ? 'Start the desktop runtime first.' : ''),
      run:async (argument: string) => {
        if (!draftCurrent()) throw new Error('The conversation changed. Try again.');
        setStoryPlanVisible(false);
        setStoryRefineCandidate(null); setStoryRefineCandidateSettings(null);
        setStoryRefineSetup({text:argument, owner:commandScopeKey});
      }},
    actionCommand('story_plan', 'Open the Story Plan for this conversation', openStoryPlan,
      commandBlocked || (activeState?.features?.story_plan_version !== 1 ? 'Update and restart NC desktop to enable Story Plans.' : '')),
    actionCommand('voice', 'Choose the conversation voice', () => {
      setPersonaSheetTab('voice'); setAvatarControlsVisible(true);
    }),
    {name:'roleplay', description:'Reserved for a future addon', disabledReason:'Coming later'},
    {name:'audiostory', description:'Reserved for a future addon', disabledReason:'Coming later'},
  ];
  const conversationControls = (<>
      {conversationActionsAvailable && (settings.showConversationControls !== false || settings.showResetChat !== false)
      ? <ConversationControls snapshot={activeState?.conversation_actions}
      disabled={!chatCommandsAvailable || recorder.recording || recorder.busy} busyAction={conversationActionBusy}
      showConversationControls={settings.showConversationControls !== false}
      showResetChat={settings.showResetChat !== false}
      quickMenuActions={settings.quickMenuActions}
      onQuickMenuActionsChange={quickMenuActions=>setSettings({quickMenuActions})}
      onReset={confirmChatReset} resetDisabled={activeState?.features?.chat_reset !== true}
      onAction={runConversationAction} onRecover={conversationActionRecoverable ? () => {
        const job = conversationActionRef.current;
        if (job?.owner === connectionFence && !job.promise) job.promise = job.run();
      } : undefined} /> : null}
      {settings.showConversationControls !== false && extraQuickMenuActions(settings.quickMenuActions, activeState?.controls?.actions ?? []).length ?
        <ControlsBar actions={extraQuickMenuActions(settings.quickMenuActions, activeState?.controls?.actions ?? [])}
          disabled={!commandsAvailable || Boolean(conversationActionBusy) || recorder.recording || recorder.busy}
          paused={audioQueue.paused} onControl={dispatchChatControl} wrap
          quickMenuActions={settings.quickMenuActions}
          onQuickMenuActionsChange={quickMenuActions=>setSettings({quickMenuActions})}/> : null}
      {settings.showConversationControls!==false && settings.quickMenuActions?.includes('soundscape') && soundscape.controls.available ?
        <QuickMenuActionButton action="soundscape" accessibilityRole="button" accessibilityLabel="Soundscape"
          quickMenuActions={settings.quickMenuActions} onQuickMenuActionsChange={quickMenuActions=>setSettings({quickMenuActions})}
          style={{minHeight:44,padding:12,alignSelf:'flex-start'}} onPress={()=>setSoundscapeVisible(true)}>
          <Text style={{color:colors.accent,fontWeight:'700'}}>Soundscape</Text>
        </QuickMenuActionButton>:null}</>

  );
  const pendingVoice=backendRecorder.pendingRecording?<PendingVoiceRecording recording={backendRecorder.pendingRecording}
    busy={backendRecorder.busy||!foreground||!remote.connected} onSend={backendRecorder.sendPendingRecording}
    onDiscard={backendRecorder.discardPendingRecording}/>:null;
  const composer = <Composer
      draftState={composerDraft.value} onDraftChange={composerDraft.setValue}
      conversationControls={conversationControls}
      commands={phoneCommands} commandScopeKey={commandScopeKey}
      pendingVoice={pendingVoice}
      presenceMode={settings.companionDisplayMode !== 'conversation'}
      disabled={!chatCommandsAvailable || conversationActionBusy === 'reset_chat'}
      photoAvailable={!demoMode && chatCommandsAvailable}
      voiceAvailable={phoneSttAvailable && !demoMode}
      recording={recorder.recording}
      busy={recorder.busy}
      recordingError={recorder.error}
      liveEnabled={recorder.liveEnabled}
      liveStatus={recorder.liveStatus}
      canStopSpeech={canStopSpeech}
      onStopSpeech={stopSpeech}
      fullscreenAvailable={sessionActive}
      transcript={recorder.transcript}
      onTranscriptConsumed={recorder.clearTranscript}
      photoDraft={photoDraft}
      onSend={photoDraft.send}
      queuedMessage={queuedMessage}
      onProcessQueued={processQueuedMessage}
      onRecordPress={recorder.toggleRecording}
      onLivePress={recorder.toggleLive}
      onFullscreenPress={openPresentation}
      onPhotoPress={() => photoDraft.pick('camera')}
    />;
  const chatComposer = composer;
  const presenceDockVisible = visibleSurface === 'chat' && settings.companionDisplayMode !== 'conversation';
  const primaryNavigation = <PrimaryNavigation
    active={visibleSurface === 'settings' ? 'tools' : activeTab}
    bottomInset={presenceDockVisible || androidKeyboardVisible ? 0 : safeAreaInsets.bottom}
    onChange={(destination) => { void enterMediaSurface(destination).catch(() => undefined); }} />;
  const endWaitingTarget = conversationActionsAvailable && settings.showConversationControls !== false && !conversationActionBusy
    ? activeState?.conversation_actions?.end_waiting : undefined;

  const connectionPanel = (
    <ConnectionPanel
      relay={remote.relay}
      baseUrl={remote.baseUrl}
      pairingCode={remote.pairingCode}
      connected={remote.connected}
      status={remote.status}
      transport={remote.transport}
      error={connectionModeError || remote.error}
      demoMode={demoMode}
      connectionMode={remote.connectionMode}
      activeRoute={remote.activeRoute}
      internetProfile={remote.internetProfile}
      enrollmentStatus={remote.enrollmentStatus}
      onBaseUrlChange={remote.setBaseUrl}
      onPairingCodeChange={remote.setPairingCode}
      onScanQrCode={() => setPairingScannerVisible(true)}
      onConnect={remote.connect}
      onDisconnect={() => settleConnectionChange(remote.disconnect)}
      onRefresh={remote.refresh}
      onConnectionModeChange={changeConnectionMode}
      modeChangePending={connectionModeChanging}
      onForgetInternet={remote.forgetInternet}
      onDemoModeChange={(enabled) => {
        setDemoMode(enabled);
        if (enabled) demo.reset();
      }}
    />
  );

  const mediaPanel = (
    <MediaPanel
      audio={phoneAudio}
      playback={mediaPlayback}
      disabled={!commandsAvailable}
      demoMode={demoMode}
      onResumeResponse={audioQueue.manualRecovery || audioQueue.paused
        ? () => dispatchChatControl('play_speech') : undefined}
      onClearQueue={async () => {
        if (nativePlayback) nativeSpeech.clear();
        else if (demoMode) await demo.clearAudio();
        else {
          // Clear must release owned desktop playback too, otherwise queued text waits forever.
          await endPhoneReplyOutput();
          // Clearing backend media invalidates reply receipts. Confirm the same
          // immutable Skip first; the poll may also retry it idempotently.
          for (const [id, retired] of [...connectionFence.retirements]) {
            const current = () => connectionFence === backgroundFence.current && remote.connected;
            if (!current()) throw new Error('Reconnect before clearing the reply.');
            const result = await retryPhoneReply(() => remote.client.sendPhoneReplyAction(retired.reply.auth,
              {kind:'skip',phone_request_id:id,operation_id:retired.operationId}), current);
            if (!current() || !['accepted','duplicate'].includes(result.status))
              throw new Error('The desktop has not released this reply yet. Try Clear queue again after reconnecting.');
            connectionFence.retirements.delete(id);
          }
          await remote.clearAudio();
        }
        audioQueue.reset();
      }}
    />
  );

  const toolsContent = (
<ToolsScreen embedded
                onOpenCharacters={()=>{setInitialCharacterId('');setCharactersVisible(true);}}
                audioCount={phoneAudio?.items?.length ?? 0}
                demoMode={demoMode}
                musetalkAvailable={musetalkAvailable}
                runtimeRunning={runtimeRunning}
                onOpenAudio={() => setSecondarySurface('audio')}
                onOpenConnection={openConnection}
                onOpenFullscreen={openPresentation}
              >
                <MuseTalkPanel
                  client={remote.client}
                  musetalk={activeState?.musetalk}
                  disabled={!sessionActive || backgroundVisualsPaused}
                  available={musetalkAvailable}
                  quality={settings.museTalkQuality}
                  demoMode={demoMode}
                />
                <DesktopControlsDrawer
                  state={activeState}
                  disabled={!commandsAvailable}
                  demoMode={demoMode}
                  onStart={demoMode ? demo.startEngine : remote.startEngine}
                  onStop={async () => { if (demoMode) await demo.stopEngine(); else { await endPhoneReplyOutput(); await remote.stopEngine(); } }}
                  onControl={dispatchChatControl}
                />
              </ToolsScreen>
  );

  const closeSecondary = () => setSecondarySurface(closeSecondarySurface());

  return (
    <InterfaceModeProvider mode={settings.interfaceStyle}>
    <SafeAreaView
      edges={museTalkPresentation.fullscreen ? [] : ['top', 'left', 'right']}
      style={[styles.screen, settings.interfaceStyle === 'immersive' && styles.screenImmersive]}
    >
      <StatusBar hidden={museTalkPresentation.fullscreen} barStyle={theme.appearance === 'light' ? 'dark-content' : 'light-content'} backgroundColor={colors.backgroundElevated} />
      <KeyboardAvoidingView
        style={styles.keyboard}
        behavior={keyboardAvoidingBehavior(Platform.OS)}
        keyboardVerticalOffset={0}
        enabled={Platform.OS !== 'android' || androidKeyboardVisible}
      >
        <View ref={avatarPresentation.rootRef} onLayout={avatarPresentation.remeasure}
          style={[styles.appShell, settings.interfaceStyle === 'immersive' && styles.appShellImmersive]}>
          {audioQueue.activePlayer ? (
            <AudioSampleTap player={audioQueue.activePlayer} fps={settings.liveFullscreen.spectrumFps}
              frequencyBands={settings.voiceVisualizerStyle !== 'silk'} onSample={audioQueue.setLiveSample} />
          ) : null}
          {MuseTalkLiveSessionView ? <MuseTalkLiveSessionView client={remote.client} playback={audioQueue}
            muxed={muxedTrialSelected ? muxedPlayback.runtime : undefined}
            buffered={bufferedPlayback.runtime} bufferedPresentation={bufferedPlayback.presentation}
            eligible={museTalkLiveEligible} foreground={foreground} liveEnabled={recorder.liveEnabled} fullscreen={museTalkPresentation.fullscreen}
            presentation={avatarPresentation.presentation}
            onPresentationReadyChange={avatarPresentation.setDisplayReady}
            onStartHandler={handler => { sessionVisualStartRef.current = handler; }}
            onRenderingChange={setLiveSessionRendering} invalidationRevision={museTalkInvalidationRevision}
            presenceFallback={<MoodAvatar presence={livePresence} client={remote.client} variant="portrait" contentFit="contain" />}
            fullscreenControls={zoomGestures => <MuseTalkFullscreenControls settings={settings.liveFullscreen} zoomGestures={zoomGestures}
              idleStatus={muxedPlayback.idleStatus}
              disabled={!remote.connected} onExit={museTalkPresentation.dismiss}
              onSendText={photoDraft.send} photoDraft={photoDraft}
              canStopSpeech={canStopSpeech} onStopSpeech={stopSpeech}
              liveControls={<LiveModeControl compact enabled={recorder.liveEnabled}
              disabled={Boolean(!commandsAvailable || recorder.recording || (!recorder.liveEnabled && recorder.busy))}
              available={phoneSttAvailable && !demoMode} status={recorder.liveStatus} error={recorder.error}
              onToggle={recorder.toggleLive} />} />} /> : null}
          {visibleSurface === 'settings' || visibleSurface === 'tools' ? (
            settings.presentationStyle === 'editorial' ? null : <ScreenHeader title="Settings" subtitle="Make NC feel like yours" onBack={() => { closeSecondary(); setActiveTab('chat'); }} />
          ) : visibleSurface === 'audio' ? (
            <ScreenHeader title="Phone audio" subtitle="Playback and queued speech" onBack={closeSecondary} />
          ) : visibleSurface === 'connection' && shouldShowConnectionBack(sessionActive) ? (
            <ScreenHeader title="Desktop link" subtitle="Pairing, LAN and secure Internet routes" onBack={closeSecondary} />
          ) : (
            <AppHeader
              companionName={headerCharacter?.name || activeState?.presence?.persona?.name || 'Companion'}
              avatar={<NeutralHeaderAvatar presence={livePresence} client={remote.client}
                speakerName={headerCharacter?.name} portraitPath={headerCharacter?.portrait_url_path}
                onPress={() => { setPersonaSheetTab('persona'); setAvatarControlsVisible(true); }} />}
              demoMode={demoMode}
              connected={remote.connected}
              runtimeRunning={runtimeRunning}
              engineStatus={engineStatus}
              onStartEngine={() => { void startEngineFromHeader(); }}
              stateLabel={livePresence?.state_label || String(activeState?.status_line || '')}
              audioCount={phoneAudio?.items?.length ?? 0}
              playing={audioQueue.isPlaying && !audioQueue.paused}
              paused={audioQueue.paused}
              onOpenAudio={() => setSecondarySurface('audio')}
              onOpenConnection={openConnection}
              onOpenSettings={() => {closeSecondary();setActiveTab('tools');}}
            />
          )}
          <QuickPersonaSheet
            key={remote.client.identityKey}
            client={remote.client}
            initialTab={personaSheetTab}
            storyActive={Boolean(savedStoryPlan || activeState?.mprc?.session?.enabled)}
            enabled={!demoMode && remote.connected}
            onClose={() => setAvatarControlsVisible(false)}
            onSelected={remote.refresh}
            visible={avatarControlsVisible}
          />
          <ChatCharacterLibrary visible={charactersVisible} initialCharacterId={initialCharacterId} api={characters}
            onClose={()=>setCharactersVisible(false)}
            previewId={characterPreviewId}
            onStopPreview={()=>audioQueue.stopCharacterPreview(`character-preview-${characterPreviewId}`)}
            previewAllowed={canPreviewCharacterVoice({connected:remote.connected,speaking:phonePlaybackActive&&!characterPreviewId,
              live:recorder.liveEnabled,busy:recorder.busy||!!queuedMessage})}
            onPreview={candidate=>{
              const allowed=canPreviewCharacterVoice({connected:remote.connected,speaking:phonePlaybackActive&&!characterPreviewId,
                live:recorder.liveEnabled,busy:recorder.busy||!!queuedMessage});
              if(!allowed)return;
              void mediaPlayback.playNow({id:`character-preview-${candidate.id}`,url_path:candidate.url_path,index:0,content_type:'audio/ogg'});
            }}/>
          <AssignExistingCharacterSheet candidate={assignmentCandidate} api={characters}
            onClose={()=>setAssignmentCandidate(null)}/>
          {storyRefineSetup?.owner === commandScopeKey ? <StoryRefinePanel key={commandScopeKey}
            client={remote.client} initialText={storyRefineSetup.text} isCurrent={draftCurrent}
            initialSettings={storyRefineSetup.initialSettings} referencePlan={storyRefineSetup.referencePlan}
            onClose={text => {
              const returningToPlan = Boolean(storyRefineSetup.referencePlan);
              setStoryRefineSetup(null);
              if (returningToPlan) {setStoryPlanVisible(true); return;}
              if (draftCurrent()) composerDraft.setValue(current => current.text ? current
                : {text:`/story_refine ${text}`, command:null});
            }}
            onReady={(plan, settings) => {
              if (!draftCurrent()) return;
              storyPlanOwner.current = commandScopeKey;
              if (storyRefineSetup.referencePlan) {
                setStoryRefineCandidate(plan); setStoryRefineCandidateSettings(settings ?? null);
              } else {
                setSavedStoryPlan(null); setStoryPlanDraft(plan); setStoryRefineCandidate(null);
                setStoryRefineSettings(settings ?? null); setStoryRefineCandidateSettings(null);
              }
              setStoryRefineSetup(null);
              setStoryOpeningPending(false); setStoryPlanError(''); setStoryPlanVisible(true);
            }}/> : null}
          {storyExtension && !storyExtensionDraft ? <StoryRefinePanel key={`extend-${storyExtension.operationId}`}
            client={remote.client} initialText="" isCurrent={draftCurrent} extension={storyExtension.source}
            onClose={() => {setStoryExtension(null); storyAppendAttempt.current=null; setStoryPlanVisible(true);}}
            onReady={plan => {if(draftCurrent()) {setStoryExtensionDraft(plan); setStoryPlanVisible(true);}}}/> : null}
          <StoryPlanPanel visible={storyPlanVisible} plan={storyExtensionDraft ?? storyRefineCandidate ?? savedStoryPlan ?? storyPlanDraft}
            busy={storyPlanBusy} error={storyPlanError} openingPending={storyOpeningPending}
            onCreate={!phoneCommands.find(command => command.name === 'story_refine')?.disabledReason ? () => {
              const command = phoneCommands.find(item => item.name === 'story_refine');
              if (!command?.run) return;
              void Promise.resolve(command.run('', new AbortController().signal)).catch(error => {
                setStoryPlanError(error instanceof Error ? error.message : 'Could not open Story Refine.');
              });
            } : undefined}
            onBackToRefine={!storyExtension && !savedStoryPlan && storyPlanDraft && !storyRefineCandidate ? edited => {
              if (!draftCurrent()) return;
              setStoryPlanDraft(edited);
              const prior = storyRefineSettings;
              setStoryRefineSetup({text:prior?.text || edited.premise, owner:commandScopeKey,
                initialSettings:prior ?? undefined, referencePlan:edited});
              setStoryPlanVisible(false);
            } : undefined}
            comparison={storyRefineCandidate ? {
              onKeep:() => {setStoryRefineCandidate(null); setStoryRefineCandidateSettings(null);},
              onUse:edited => {setStoryPlanDraft(edited); setStoryRefineCandidate(null);
                setStoryRefineSettings(storyRefineCandidateSettings); setStoryRefineCandidateSettings(null);},
            } : undefined}
            extension={storyExtension && storyExtensionDraft ? {source:storyExtension.source,onAppend:appendStoryBeats} : undefined}
            onExtend={activeState?.features?.story_extension_version === 1 ? extendStoryPlan : undefined}
            onTransport={controlStoryPlan}
            transportLabel={continuous.state && ['waiting','generating','ready','delay'].includes(continuous.state.state) ? 'Pause' : 'Resume'}
            onClose={() => {setStoryPlanVisible(false); setStoryExtension(null); setStoryExtensionDraft(null); storyAppendAttempt.current=null;}} onSave={saveStoryPlan}
            onOpenLibrary={!storyExtension && libraryAvailable ? () => { setStoryPlanVisible(false); openStoryLibrary(); } : undefined}
            onSendToChat={sendRefinedStory} onStart={startStoryPlan}
            onSendOpening={async () => { if (savedStoryPlan) Alert.alert('Send opening cue again?',
              'The previous send may have reached chat. Check the conversation to avoid a duplicate scene.', [
                { text: 'Cancel', style: 'cancel' },
                { text: 'Send again', onPress: () => { void sendStoryOpening(savedStoryPlan); } },
              ]); }}
            onProgression={async mode => { if (savedStoryPlan) try {
              await storyPlanAction({ action: 'progression', revision: savedStoryPlan.revision, mode });
            } catch { /* Error shown in the panel. */ } }}
            onBeat={async index => { if (savedStoryPlan) try {
              await storyPlanAction({ action: 'beat', revision: savedStoryPlan.revision, index });
            } catch { /* Error shown in the panel. */ } }}
            onRemove={async () => { if (savedStoryPlan) try {
              await storyPlanAction({ action: 'remove', revision: savedStoryPlan.revision });
              setStoryPlanDraft(null); setStoryOpeningPending(false);
            } catch { /* Error shown in the panel. */ } }}
            onRefresh={async () => { try { await storyPlanAction({ action: 'status' }); }
              catch { /* Error shown in the panel. */ } }} />
          <StoryLibraryPanel visible={storyLibraryVisible} entries={storyLibraryEntries}
            activeEntryId={activeStoryEntryId} busy={storyLibraryBusy} activity={storyLibraryActivity} error={storyLibraryError}
            recoveryId={storyRecoveryId} onRecover={recoverPreviousStory}
            playback={storyTransport} onClose={() => setStoryLibraryVisible(false)}
            onOpenCharacters={() => {setStoryLibraryVisible(false);setInitialCharacterId('');setCharactersVisible(true);}}
            onRefresh={refreshStoryLibrary} onSave={saveCurrentStory}
            onSaveAs={async name => { await libraryMutation('save_as', {name}); }}
            onOpen={openSavedStory}
            onRename={async (entry, name) => { await libraryMutation('rename', {entry_id:entry.entry_id, name}); }}
            onDelete={async entry => { await libraryMutation('delete', {entry_id:entry.entry_id}); }}
            onTransport={controlSavedStory}/>
          <StoryCompletionSheet
            visible={visibleSurface === 'chat' && !demoMode && Boolean(continuous.state?.story_complete)
              && activeState?.features?.story_extension_version === 1 && !storyCompletionDismissed
              && !storyPlanVisible && !storyLibraryVisible && !storyExtension}
            onAdd={() => {setStoryCompletionDismissed(true);void extendStoryPlan();}}
            onLibrary={() => {setStoryCompletionDismissed(true);openStoryLibrary();}}
            onDiscard={() => setStoryCompletionDismissed(true)}/>
          <PairingQrScanner
            visible={pairingScannerVisible}
            onCancel={() => setPairingScannerVisible(false)}
            onPairingScanned={(setup) => {
              if (setup.mode === 'internet') {
                setDemoMode(false);
                setPairingScannerVisible(false);
                void remote.enrollInternetAndConnect(setup);
              } else if (remote.pairAndConnect(setup.baseUrl, setup.pairingCode)) {
                setDemoMode(false);
                setPairingScannerVisible(false);
              }
            }}
          />
          <LiveFullscreenScreen
            canStopSpeech={canStopSpeech}
            onStopSpeech={stopSpeech}
            liveControls={(
              <LiveModeControl
                compact
                enabled={recorder.liveEnabled}
                disabled={!commandsAvailable || recorder.recording || (!recorder.liveEnabled && recorder.busy)}
                available={phoneSttAvailable && !demoMode}
                status={recorder.liveStatus}
                error={recorder.error}
                onToggle={recorder.toggleLive}
              />
            )}
            visible={liveFullscreenVisible && !backgroundVisualsPaused && !museTalkLiveEligible}
            connected={remote.connected}
            sessionActive={sessionActive}
            demoMode={demoMode}
            state={activeState}
            client={remote.client}
            playback={mediaPlayback}
            activity={runtimeActivity}
            meteringDb={recorder.meteringDb}
            meteringRevision={recorder.meteringRevision}
            microphoneActive={recorder.liveEnabled || recorder.recording}
            microphoneSpeechDetected={recorder.recording || recorder.livePhase === 'speech'}
            settings={settings.liveFullscreen}
            onSettingsChange={setLiveFullscreenSettings}
            onSendText={photoDraft.send}
            photoDraft={photoDraft}
            onExit={() => setLiveFullscreenVisible(false)}
          />
          <View style={[styles.mainArea, presenceDockVisible && {paddingBottom: presenceDockHeight}]}>
            {visibleSurface === 'chat' && !demoMode && (
              (settings.showVisualButton !== false && activeState?.features?.visual_reply_controls)
              || (settings.showStoryShortcuts !== false && (activeState?.features?.story_plan_version === 1 || libraryAvailable))
            ) ?
              <View testID="chat-shortcuts" style={{ flexDirection: 'row', alignItems: 'center', minHeight: 48 }}>
                {settings.presentationStyle !== 'editorial' && settings.showVisualButton !== false && activeState?.features?.visual_reply_controls ? <Pressable accessibilityRole="button"
                  accessibilityLabel="Generate Visual Reply" accessibilityHint="Long press for Visual Reply settings"
                  accessibilityState={{ disabled: !remote.connected || !latestVisualSource || visualButtonBusy }}
                  onLongPress={openVisualSettings} delayLongPress={450}
                  onPress={() => { if (Date.now() - visualLongPressAt.current < 700) return;
                    void generateLatestVisual(); }}
                  style={{ minHeight: 44, justifyContent: 'center', paddingHorizontal: 16 }}>
                  <Text style={{ color: colors.accent, fontWeight: '700' }}>▣ Visual</Text>
                  <Text style={{ color: colors.muted, fontSize: 10 }}>{visualButtonBusy ? 'Sending…' : 'Hold for options'}</Text>
                </Pressable> : null}
                {settings.presentationStyle === 'editorial' ? <Text numberOfLines={1} style={{flex:1,color:colors.muted,fontSize:12,paddingLeft:20}}>
                  {savedStoryPlan ? savedStoryPlan.title : 'CONVERSATION'}
                </Text> : <View style={{ flex: 1 }} />}
                {settings.showStoryShortcuts !== false && activeState?.features?.story_plan_version === 1 ? <Pressable accessibilityRole="button" accessibilityLabel="Open Story Plan"
                  onPress={() => { void openStoryPlan(); }} style={{ paddingHorizontal: 16, paddingVertical: 8 }}>
                  <Text style={{ color: colors.accent, fontWeight: '700' }}>Story Plan</Text>
                </Pressable> : null}
                {settings.showStoryShortcuts !== false && libraryAvailable ? <Pressable accessibilityRole="button" accessibilityLabel="Open Story Library"
                  onPress={openStoryLibrary} style={{ paddingHorizontal: 16, paddingVertical: 8 }}>
                  <Text style={{ color: colors.accent, fontWeight: '700' }}>Library</Text>
                </Pressable> : null}
              </View> : null}
            {visibleSurface === 'chat' ? <DismissibleFault message={visualButtonError}/> : null}
            {visibleSurface === 'chat' && continuousAvailable && !demoMode ? <ContinuousPanel controller={continuous} client={remote.client} owner={connectionFence}
              showBar={settings.showContinuousBar !== false}
              onAddStoryBeats={activeState?.features?.story_extension_version === 1 ? extendStoryPlan : undefined}
              playbackError={audioQueue.manualRecovery?audioQueue.error:phoneReplyError}
              onResumeResponse={audioQueue.manualRecovery?()=>dispatchChatControl('play_speech'):undefined}
              onForceContinuation={async()=>{
                const context=explicitActionContext;
                assertExplicitAction(context);
                if(playbackControlBusy.current) throw new Error('A playback action is still in progress. Try again shortly.');
                await dispatchChatControl('interrupt_response', true);
                assertExplicitAction(context);
              }}
              unavailable={!remote.connected?'Connect to NC to use Continuous Mode.':!phoneReplyControls?'Select Backend HQ audio to use Continuous Mode.':''}
              startUnavailable={!continuousCanClaim?'Finish recording or stop Live Mode before starting Continuous Mode.':''}
              onResolveStart={()=>backendRecorder.cancelCapture()}/> : null}
            {visibleSurface === 'chat' ? <DismissibleFault message={audioQueue.error || phoneAudio?.error || ''}
              actionLabel="Audio controls" onAction={() => setSecondarySurface('audio')}/> : null}
            {visibleSurface === 'connection' ? (
              <ScrollView keyboardShouldPersistTaps="handled" style={styles.tabPanel} contentContainerStyle={[styles.setupContent, { paddingBottom: safeAreaInsets.bottom + spacing.xl }]}>
                {settings.presentationStyle !== 'editorial' ? <View style={styles.setupHero}>
                  <Text style={styles.setupEyebrow}>{sessionActive ? 'CONNECTION' : 'WELCOME TO NC'}</Text>
                  <Text style={styles.setupTitle}>{sessionActive ? 'Desktop link' : 'Bring your companion with you.'}</Text>
                  <Text style={styles.setupSubtitle}>
                    {sessionActive
                      ? 'Review the active route, refresh the phone state, or pair with another desktop.'
                      : 'Scan the QR code shown by Main Chat Remote, or enter the local address and pairing code.'}
                  </Text>
                </View> : null}
                {connectionPanel}
              </ScrollView>
            ) : null}
            {visibleSurface === 'settings' || visibleSurface === 'tools' ? (
              <View style={styles.secondaryPanel}>
                <SettingsPanel
                  section={settingsSection}
                  onSectionChange={setSettingsSection}
                  onOpenPersona={() => setAvatarControlsVisible(true)}
                  toolsContent={toolsContent}
                  nativeSpeech={nativeSpeech}
                  settings={settings}
                  onChange={setSettings}
                  onLiveFullscreenChange={setLiveFullscreenSettings}
                  state={activeState}
                  health={remote.health}
                  status={remote.status}
                  transport={remote.transport}
                  error={remote.error}
                  onSendDebug={() => remote.client.uploadDebug('manual')}
                />
              </View>
            ) : null}
            {visibleSurface === 'audio' ? (
              <ScrollView style={styles.tabPanel} contentContainerStyle={[styles.stackedContent, styles.secondaryScroll, { paddingBottom: safeAreaInsets.bottom + spacing.xl }]}>
                {mediaPanel}
              </ScrollView>
            ) : null}
            {visibleSurface === 'chat' ? (
              <CompanionSurface
                mode={settings.companionDisplayMode}
                presence={livePresence}
                musetalk={backgroundVisualsPaused ? undefined : activeState?.musetalk}
                client={remote.client}
                playback={mediaPlayback}
                meteringDb={recorder.meteringDb}
                meteringRevision={recorder.meteringRevision}
                animationEnabled={!backgroundVisualsPaused && !liveFullscreenVisible && !museTalkPresentation.fullscreen}
                spectrumFps={settings.liveFullscreen.spectrumFps}
                showPresenceControls={settings.showPresenceControls}
                showTopVoiceThread={settings.showTopVoiceThread}
                showHeader={settings.showCompanionHeader !== false}
                voiceThreadPalette={settings.voiceThreadPalette}
                presentationTarget={liveSessionRendering && settings.companionDisplayMode !== 'conversation'
                  ? avatarPresentation.targetBinding : undefined}
                onAvatarLongPress={openAvatarControls}
                liveControls={(
                  <LiveModeControl
                    canStopSpeech={canStopSpeech}
                    onStopSpeech={stopSpeech}
                    enabled={recorder.liveEnabled}
                    disabled={!commandsAvailable || recorder.recording || (!recorder.liveEnabled && recorder.busy)}
                    available={phoneSttAvailable && !demoMode}
                    status={recorder.liveStatus}
                    error={recorder.error}
                    onToggle={recorder.toggleLive}
                    onFullscreen={openPresentation}
                  />
                )}
                chatFeed={chatFeed(chatComposer)}
                composer={null}
                useControlsDock={presenceDockVisible}
                latestVisualReply={latestVisualReply}
                visualSessionStartedAt={demoMode ? 0 : portraitSessionStartedAt}
                dismissedVisualIds={dismissedVisualIds}
                focusedVisualReply={focusedVisualReply}
                commandsAvailable={commandsAvailable}
                onDismissVisual={(id) => setDismissedVisualIds((current) => new Set(current).add(id))}
                onCloseFocusedVisual={() => setFocusedVisualReply(undefined)}
                onModeChange={handleCompanionModeChange}
                onTalk={recorder.toggleRecording}
                onOpenMore={() => {
                  setSecondarySurface(null);
                  setActiveTab('tools');
                }}
              />
            ) : null}
            {visibleSurface === 'visual' ? (
              <ScrollView
                keyboardShouldPersistTaps="handled"
                style={styles.tabPanel}
                contentContainerStyle={[styles.stackedContent, styles.primaryScroll]}
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
            {PHONE_STORY_MODE_ENABLED && visibleSurface === 'story' ? (
              <ScrollView
                keyboardShouldPersistTaps="handled"
                style={styles.tabPanel}
                contentContainerStyle={[styles.stackedContent, styles.primaryScroll]}
              >
                <Text style={styles.setupSubtitle}>Story uses Backend HQ Audio. Phone Native applies to normal chat when the Story session is stopped.</Text>
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

          </View>
          {presenceDockVisible ? <PresenceControlsDock
            mode={settings.companionDisplayMode === 'portrait' ? 'portrait' : 'companion'}
            composer={composer} actions={conversationControls} navigation={primaryNavigation}
            endWaitingTarget={endWaitingTarget} onEndWaiting={target => runConversationAction('end_waiting', target)}
            onOpenChat={() => handleCompanionModeChange('conversation')}
            onOpenMore={() => { setSecondarySurface(null); setActiveTab('tools'); }}
            bottomInset={androidKeyboardVisible ? 0 : safeAreaInsets.bottom}
            onCollapsedHeight={setPresenceDockHeight}
          /> : shouldShowPrimaryNavigation(visibleSurface) ? primaryNavigation : null}
        </View>
      </KeyboardAvoidingView>
      {!museTalkPresentation.fullscreen&&!presenceDockVisible?<IdleLoopDownloadStatus status={muxedPlayback.idleStatus} bottomInset={safeAreaInsets.bottom} />:null}
      <SoundscapePanel visible={soundscapeVisible} editAssetId={soundscapeEditId} onClose={()=>{setSoundscapeVisible(false);setSoundscapeEditId('');}} sound={soundscape.controls}/>
      <VisualReplySettingsSheet visible={visualSettingsVisible} display={settings.visualDisplay}
        status={visualAutoStatus} busy={visualAutoBusy} error={visualAutoError}
        onDisplayChange={visualDisplay => setSettings({ visualDisplay })}
        onAutoChange={changeVisualAuto}
        onRefresh={async () => { setVisualAutoError(''); try { await refreshVisualAuto(); }
          catch (error) { setVisualAutoError(error instanceof Error ? error.message : 'Could not refresh Visual Reply settings.'); } }}
        onClose={() => setVisualSettingsVisible(false)} />
      <DesktopControlsSheet onForceContinuation={notificationCanForce ? forceContinuousFromControls : undefined} onSoundscape={Platform.OS==='android'&&activeState?.features?.soundscape_version===1?()=>setSoundscapeVisible(true):undefined}
        liveControls={<LiveModeControl enabled={recorder.liveEnabled}
        disabled={!chatCommandsAvailable || recorder.busy || recorder.recording} available={phoneSttAvailable && !demoMode}
        status={recorder.liveStatus} error={recorder.error} onToggle={async () => { await recorder.toggleLive(); if (settings.autoCloseResponseMenu) setDesktopControlsVisible(false); }}
        canStopSpeech={canStopSpeech} onStopSpeech={() => { stopSpeech(); if (settings.autoCloseResponseMenu) setDesktopControlsVisible(false); }}
        onFullscreen={() => { setDesktopControlsVisible(false); openPresentation(); }} />}
        visible={desktopControlsVisible} autoClose={settings.autoCloseResponseMenu}
        onAutoCloseChange={autoCloseResponseMenu => setSettings({ autoCloseResponseMenu })}
        sectionVisibility={settings}
        onSectionVisibilityChange={setSettings}
        cardOrder={settings.responseCardOrder}
        quickMenuActions={settings.quickMenuActions}
        onQuickMenuActionsChange={quickMenuActions=>setSettings({quickMenuActions})}
        onCardOrderChange={responseCardOrder => setSettings({ responseCardOrder })}
        state={activeState} disabled={!commandsAvailable || conversationActionBusy === 'reset_chat'}
        resetDisabled={!chatCommandsAvailable || activeState?.features?.chat_reset !== true || Boolean(conversationActionBusy)}
        onClose={() => setDesktopControlsVisible(false)}
        onStart={demoMode ? demo.startEngine : remote.startEngine}
        onStop={async () => { if (demoMode) await demo.stopEngine(); else { await endPhoneReplyOutput(); await remote.stopEngine(); } }}
        onControl={dispatchChatControl}
        onQuickSave={!demoMode ? () => remote.sendControl('quick_save_chat_context', sendOptions) : undefined}
        onQuickLoad={!demoMode ? async () => {
          if (recorder.liveEnabled) throw new Error('Stop Live Mode before loading a saved chat.');
          await endPhoneReplyOutput();
          await remote.sendControl('quick_load_chat_context', sendOptions);
        } : undefined}
        continuousState={continuous.state}
        onContinuousSettingsChange={continuousAvailable && !demoMode && !storyActive ? async patch => {
          if (!remote.connected || !phoneReplyControls) throw new Error('Connect with Backend HQ audio to change Continuous Mode.');
          await continuous.command('settings', { settings: patch });
        } : undefined}
        paused={audioQueue.paused}
        selectedMessageId={selectedControlMessage?.message.id}
        selectedMessageText={selectedControlMessage?.message.content}
        onGenerateImage={selectedControlMessage?.owner === connectionFence ? generateSelectedMessageImage : undefined}
        storyPlan={selectedControlMessage?.owner === connectionFence ? responseStoryPlan : null}
        storyPlanLoading={responseStoryPlanLoading} storyPlanError={responseStoryPlanError}
        onNextStoryBeat={nextResponseStoryBeat}
        onStoryPaceChange={changeResponseStoryPace}
        onStoryLibrary={libraryAvailable ? openStoryLibrary : undefined}
        onStoryTransport={libraryAvailable && activeStoryEntryId ? controlSavedStory : undefined}
        storyTransport={storyTransport}
        onReset={confirmChatReset} />
    </SafeAreaView>
    </InterfaceModeProvider>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.background,
  },
  screenImmersive: {
    backgroundColor: colors.background,
  },
  keyboard: {
    flex: 1,
  },
  appShell: {
    flex: 1,
    minHeight: 0,
  },
  appShellImmersive: {
    backgroundColor: colors.background,
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
  setupContent: {
    gap: spacing.lg,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.xl,
  },
  setupHero: {
    gap: spacing.xs,
    paddingHorizontal: spacing.xs,
  },
  setupEyebrow: {
    color: colors.accent,
    fontSize: 10,
    fontWeight: '900',
    letterSpacing: 1.6,
  },
  setupTitle: {
    color: colors.text,
    fontSize: 30,
    fontWeight: '900',
    letterSpacing: -0.8,
    lineHeight: 34,
  },
  setupSubtitle: {
    color: colors.textSecondary,
    fontSize: 13,
    lineHeight: 19,
    maxWidth: 360,
  },
  secondaryPanel: {
    flex: 1,
    minHeight: 0,
  },
  secondaryScroll: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
  },
  primaryScroll: {
    padding: spacing.lg,
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
  controlsDrawerImmersive: { borderColor: colors.border },
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
    borderColor: colors.border,
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
    borderTopColor: colors.border,
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
