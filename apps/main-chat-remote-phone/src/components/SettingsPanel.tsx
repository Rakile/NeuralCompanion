import { useThemedStyles, useThemeColors, usePresentationStyle } from '../styles/ThemeContext';
import type { ThemeColors } from '../styles/theme';
import React from 'react';
import { Platform, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';

import type { RemoteConnectionStatus, RemoteEnvelope, RemoteHealth, RemoteState, RemoteTransport } from '../api/types';
import type { ChatIndicatorStyle, ChatTextColor, CompanionDisplayMode, MicBehavior, MuseTalkQuality, PhoneSettings, SendMode, VoiceThreadPalette } from '../hooks/usePhoneSettings';
import { ThemeChooser } from './ThemeChooser';
import { EditorialSettingsHub } from './editorial/EditorialSettingsHub';
import { PresentationChooser } from './PresentationChooser';
import { VoiceSilkSettings } from './presence/VoiceSilkSettings';
import { MediaCacheSettings } from './MediaCacheSettings';
import { AppIcon } from './app-shell/AppIcon';
import { AppearanceSelector } from './AppearanceSelector';
import { IosLiveAudioSettings } from './IosLiveAudioSettings';
import { LiveFullscreenSettings } from './live-fullscreen/LiveFullscreenSettings';
import { LiveFullscreenSlider } from './live-fullscreen/LiveFullscreenSlider';
import { ModeSection } from './ModeSurface';
import { colors, controlGlyphTypography, spacing } from '../styles/theme';
import { phoneDebugFileName } from '../utils/phoneDebug';
import { PHONE_STORY_MODE_ENABLED } from '../utils/productionShell';
import type { LiveFullscreenSettings as LiveFullscreenSettingsValue } from '../utils/liveFullscreenSettings';
import type { usePhoneNativeSpeech } from '../hooks/usePhoneNativeSpeech';
import { nativeReason, normalizeNativeMicSensitivity } from '../utils/phoneNativeSpeech';
import {progressivePcmAvailable} from '../native/progressivePcm';

export type SettingsSection = 'companion' | 'voice' | 'look' | 'tools';

type Props = {
  section?: SettingsSection;
  onSectionChange?: (section: SettingsSection) => void;
  toolsContent?: React.ReactNode;
  onOpenPersona?: () => void;
  nativeSpeech: ReturnType<typeof usePhoneNativeSpeech>;
  settings: PhoneSettings;
  onChange: (updates: Partial<PhoneSettings>) => void;
  onLiveFullscreenChange: (updates: Partial<LiveFullscreenSettingsValue>) => void;
  state: RemoteState | null;
  health: RemoteEnvelope<RemoteHealth> | null;
  status: RemoteConnectionStatus;
  transport: RemoteTransport;
  error: string;
  onSendDebug: () => Promise<number>;
};

type Option<T extends string> = {
  value: T;
  label: string;
};

const sendModeOptions: Array<Option<SendMode>> = [
  { value: 'phone_tts', label: 'Phone speech' },
  { value: 'visual_reply', label: 'Visual reply' },
];

const micOptions: Array<Option<MicBehavior>> = [
  { value: 'send_auto', label: 'Send automatically' },
  { value: 'transcribe_only', label: 'Transcribe only' },
];

const qualityOptions: Array<Option<MuseTalkQuality>> = [
  { value: 'low_latency', label: 'Low latency' },
  { value: 'balanced', label: 'Balanced' },
  { value: 'quality', label: 'Quality' },
];

const textColorOptions: Array<Option<ChatTextColor>> = [
  { value: 'white', label: 'Default' },
  { value: 'green', label: 'Green' },
  { value: 'amber', label: 'Amber' },
  { value: 'cyan', label: 'Cyan' },
];

const indicatorOptions: Array<Option<ChatIndicatorStyle>> = [
  { value: 'dot', label: 'Dot' },
  { value: 'pulse', label: 'Pulse' },
  { value: 'line', label: 'Line' },
  { value: 'text', label: 'Text' },
];

const companionDisplayOptions: Array<Option<CompanionDisplayMode>> = [
  { value: 'conversation', label: 'Conversation' },
  { value: 'companion', label: 'Companion' },
  { value: 'portrait', label: 'Portrait Presence' },
];

const voiceThreadPaletteOptions: Array<Option<VoiceThreadPalette>> = [
  { value: 'state', label: 'Mood' },
  { value: 'spectrum', label: 'Spectrum' },
  { value: 'electric', label: 'Electric' },
];

function SettingHelp({children}: React.PropsWithChildren) {
  const editorial = usePresentationStyle() === 'editorial';
  const styles = useThemedStyles(createStyles, 'SettingsPanel');
  const [open,setOpen] = React.useState(false);
  if (!editorial) return <Text style={styles.detail}>{children}</Text>;
  return <View>
    <Pressable accessibilityRole="button" accessibilityLabel="Explain this setting" accessibilityState={{expanded:open}}
      style={styles.helpToggle} onPress={()=>setOpen(value=>!value)}>
      <Text style={styles.detail}>{open?'Hide explanation':'About this setting ⌄'}</Text>
    </Pressable>
    {open ? <Text style={styles.detail}>{children}</Text> : null}
  </View>;
}

function ToggleRow({ label, value, onChange, detail, disabled = false }: { label: string; value: boolean; detail?: string; disabled?: boolean; onChange: (value: boolean) => void }) {
  const styles = useThemedStyles(createStyles, 'SettingsPanel');
  const colors = useThemeColors();

  const [detailOpen, setDetailOpen] = React.useState(false);
  const editorial = usePresentationStyle() === 'editorial';
  return (
    <View style={styles.row}>
      <View style={styles.rowText}>
        {editorial && detail ? <Pressable accessibilityRole="button" accessibilityLabel={`About ${label}`}
          accessibilityState={{expanded:detailOpen}} onPress={()=>setDetailOpen(value=>!value)} style={{minHeight:44,justifyContent:'center'}}>
          <Text style={styles.label}>{label} ⓘ</Text></Pressable> : <Text style={styles.label}>{label}</Text>}
        {detail && (!editorial || detailOpen) ? <Text style={styles.detail}>{detail}</Text> : null}
      </View>
      {editorial ? <Switch accessibilityLabel={label} value={value} onValueChange={onChange} disabled={disabled}
        trackColor={{false:colors.border,true:colors.accentMuted}} thumbColor={value?colors.accent:colors.muted}/>
      : <Pressable
        accessibilityLabel={label}
        accessibilityRole="switch"
        accessibilityState={{ checked: value, disabled }}
        disabled={disabled}
        style={[styles.toggle, value && styles.toggleActive]}
        onPress={() => onChange(!value)}
      >
        <Text style={styles.toggleText}>{value ? 'On' : 'Off'}</Text>
      </Pressable>}
    </View>
  );
}

function Segmented<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: Array<Option<T>>; onChange: (value: T) => void }) {
  const styles = useThemedStyles(createStyles, 'SettingsPanel');
  const editorial = usePresentationStyle() === 'editorial';
  const colors = useThemeColors();

  return (
    <View style={styles.group}>
      <Text style={styles.label}>{label}</Text>
      <View accessibilityLabel={label} accessibilityRole="radiogroup" style={styles.segmented}>
        {options.map((option) => {
          const selected = option.value === value;
          return (
            <Pressable
              accessibilityLabel={option.label}
              accessibilityRole="radio"
              accessibilityState={{ checked: selected }}
              key={option.value}
              style={[styles.segment, selected && styles.segmentActive, editorial && {
                borderRadius:0,backgroundColor:'transparent',borderWidth:0,borderBottomWidth:2,
                borderBottomColor:selected?colors.accent:'transparent',minHeight:44,
              }]}
              onPress={() => onChange(option.value)}
            >
              <Text style={[styles.segmentText, selected && styles.segmentTextActive]}>{option.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

function Stepper({ label, value, suffix, minimum, maximum, step, onChange }: { label: string; value: number; suffix: string; minimum: number; maximum: number; step: number; onChange: (value: number) => void }) {
  const styles = useThemedStyles(createStyles, 'SettingsPanel');

  const nextValue = (direction: -1 | 1) => Math.max(minimum, Math.min(maximum, value + step * direction));
  return (
    <View style={styles.row}>
      <Text style={styles.label}>{label}</Text>
      <View style={styles.stepper}>
        <Pressable accessibilityLabel={`Decrease ${label}`} accessibilityRole="button" style={styles.stepButton} onPress={() => onChange(nextValue(-1))}>
          <Text style={[styles.stepText,controlGlyphTypography]}>-</Text>
        </Pressable>
        <Text accessibilityLabel={`${label}: ${value}${suffix}`} style={styles.valueText}>{value}{suffix}</Text>
        <Pressable accessibilityLabel={`Increase ${label}`} accessibilityRole="button" style={styles.stepButton} onPress={() => onChange(nextValue(1))}>
          <Text style={[styles.stepText,controlGlyphTypography]}>+</Text>
        </Pressable>
      </View>
    </View>
  );
}

function Diagnostics({ health, status, transport, error }: { health: RemoteEnvelope<RemoteHealth> | null; status: RemoteConnectionStatus; transport: RemoteTransport; error: string }) {
  const styles = useThemedStyles(createStyles, 'SettingsPanel');

  const lanBackend = health ? (health.status === 'ready' || Boolean(health.remote?.running) ? 'reachable' : String(health.status || 'unavailable')) : 'not checked';
  const bridge = health ? (health.bridge?.error ? String(health.bridge.error) : String(health.bridge?.status || health.status || 'ready')) : 'not checked';
  return (
    <View style={styles.diagnosticsBody}>
      <Text style={styles.diag}>LAN backend: {lanBackend}</Text>
      <Text style={styles.diag}>Local bridge: {bridge}</Text>
      <Text style={styles.diag}>Transport: {transport === 'none' ? status : `${status} / ${transport}`}</Text>
      <Text style={[styles.diag, error ? styles.error : undefined]}>Last error: {error || 'none'}</Text>
    </View>
  );
}

function RuntimeSummary({ state }: { state: RemoteState | null }) {
  const styles = useThemedStyles(createStyles, 'SettingsPanel');

  const runtime = state?.runtime_status;
  const settings = state?.runtime_settings;
  const visualProvider = String(state?.visual?.settings?.provider_label || state?.visual?.settings?.provider_value || 'visual');
  const buddy = state?.buddy_chat;
  const buddyProvider = String(buddy?.shared_provider?.provider_id || 'main');
  const buddyModel = String(buddy?.shared_provider?.model || '').trim();
  const buddyPersonas = Number(buddy?.active_persona_count ?? 0);
  const buddyMode = String(buddy?.llm_mode || 'main');
  return (
    <>
      <ModeSection title="Runtime Settings" editorialDisclosure summary="Model, speech & image providers">
        <Text style={styles.diag}>LLM: {settings?.chat_provider || runtime?.chat_provider || 'unknown'} {settings?.model_name || runtime?.model_name ? `/ ${settings?.model_name || runtime?.model_name}` : ''}</Text>
        <Text style={styles.diag}>STT: {settings?.stt_backend || 'unknown'} {settings?.stt_model_size ? `/ ${settings.stt_model_size}` : ''}</Text>
        <Text style={styles.diag}>TTS: {settings?.tts_backend || runtime?.tts_backend || 'unknown'}</Text>
        <Text style={styles.diag}>Visual Reply: {settings?.visual_reply_provider || visualProvider}</Text>
      </ModeSection>
      <ModeSection title="Buddy Chat" editorialDisclosure summary="Provider & persona details" forceOpen={Boolean(state?.buddy_chat?.last_provider_error)}>
        {buddy?.available === false ? (
          <Text style={styles.detail}>{buddy.message || 'Buddy Chat is not available on the desktop.'}</Text>
        ) : (
          <>
            <Text style={styles.diag}>Status: {buddy?.enabled ? 'Enabled' : 'Disabled'}</Text>
            <Text style={styles.diag}>Mode: {buddyMode === 'per_persona' ? 'Per-persona providers' : buddyMode === 'buddy' ? 'Shared buddy provider' : 'Main LLM Runtime'}</Text>
            <Text style={styles.diag}>Personas: {buddyPersonas} active / {Number(buddy?.persona_count ?? 0)} total</Text>
            <Text style={styles.diag}>Shared provider: {buddyProvider}{buddyModel ? ` / ${buddyModel}` : ''}</Text>
            {Number(buddy?.per_persona_provider_count ?? 0) > 0 ? (
              <Text style={styles.diag}>Persona overrides: {Number(buddy?.per_persona_provider_count ?? 0)}</Text>
            ) : null}
            {buddy?.last_provider_error ? (
              <Text selectable style={styles.error}>Latest provider error: {buddy.last_provider_error}</Text>
            ) : null}
          </>
        )}
      </ModeSection>
    </>
  );
}

export function SettingsPanel({
  nativeSpeech,
  settings,
  onChange,
  onLiveFullscreenChange,
  state,
  health,
  status,
  transport,
  error,
  onSendDebug, section, onSectionChange, toolsContent, onOpenPersona,
}: Props) {
  const styles = useThemedStyles(createStyles, 'SettingsPanel');
  const colors = useThemeColors();

  const [nativeLanguage, setNativeLanguage] = React.useState(settings.nativeLanguage);
  React.useEffect(() => { setNativeLanguage(settings.nativeLanguage); }, [settings.nativeLanguage]);
  React.useEffect(() => () => nativeSpeech.closeSetup(), []);
  const nativeReady = nativeSpeech.capabilities?.available === true && !nativeSpeech.probing;
  const nativeSupported = state?.features?.phone_native_audio === true;
  const nativeDisabledReason = !nativeSupported
    ? String(state?.features?.phone_native_audio_reason || 'Connect to an updated desktop with Phone Native support. Model setup is available here before connecting.')
    : !nativeReady ? nativeReason(nativeSpeech.capabilities?.reason || 'offline_audio_not_ready') : '';
  const [diagnosticsOpen, setDiagnosticsOpen] = React.useState(false);
  const [debugStatus, setDebugStatus] = React.useState('');
  const [localSection, setLocalSection] = React.useState<SettingsSection>('companion');
  const editorial = settings.presentationStyle === 'editorial';
  const [hubVisible, setHubVisible] = React.useState(true);
  const activeSection = section ?? localSection;
  const selectSection = (value: SettingsSection) => { setLocalSection(value); onSectionChange?.(value); setSettingsTab('general'); };
  const [settingsTab, setSettingsTab] = React.useState<'general' | 'live_fullscreen'>('general');
  const volumePercent = Math.round(settings.phoneTtsVolume * 100);
  const pollSeconds = Math.round(settings.pollingIntervalMs / 100) / 10;
  const showDiagnostics = Boolean(error || state?.buddy_chat?.last_provider_error) || diagnosticsOpen;
  return (
    <View style={styles.panel}>
      {editorial && hubVisible && settingsTab === 'general' ? <ScrollView>
        <EditorialSettingsHub connected={status === 'connected'} onSelect={value => {selectSection(value); setHubVisible(false);}} />
      </ScrollView> : null}
      {editorial && !hubVisible && settingsTab === 'general' ? <Pressable accessibilityRole="button"
        accessibilityLabel="Back to settings" style={styles.backToLook} onPress={() => setHubVisible(true)}>
        <Text style={styles.toggleText}>‹ Settings</Text></Pressable> : null}
      {settingsTab === 'live_fullscreen' ? (
        <>
        <Pressable accessibilityRole="button" accessibilityLabel="Back to Look settings" style={styles.backToLook} onPress={() => setSettingsTab('general')}><Text style={styles.toggleText}>‹ Look</Text></Pressable>
        <LiveFullscreenSettings
          settings={settings.liveFullscreen}
          onChange={onLiveFullscreenChange}
        />
        </>
      ) : (
      <ScrollView key={activeSection} keyboardShouldPersistTaps="handled" style={[styles.generalPanel, editorial && hubVisible && {display:'none'}]} contentContainerStyle={styles.content}>
      <Text style={styles.sectionTitle}>{({ companion: 'Companion controls', voice: 'Voice & audio', look: 'Look', tools: 'Tools' })[activeSection]}</Text>
      {activeSection === 'companion' ? <>
      {editorial && onOpenPersona ? <Pressable accessibilityRole="button" accessibilityLabel="Change persona or reply model"
        onPress={onOpenPersona} style={{minHeight:80,paddingVertical:14,borderBottomWidth:StyleSheet.hairlineWidth,borderColor:colors.borderSoft,flexDirection:'row',alignItems:'center',gap:16}}>
        <View style={{flex:1,gap:6}}><Text style={{fontFamily:'serif',fontSize:24,color:colors.text}}>{state?.presence?.persona?.name || 'Your companion'}</Text>
          <Text style={styles.detail}>Persona & reply model</Text></View><Text style={{color:colors.accent,fontSize:15}}>Change ›</Text>
      </Pressable> : null}
      <ModeSection title="Display">
        <Segmented
          label="Main chat view"
          value={settings.companionDisplayMode}
          options={companionDisplayOptions}
          onChange={(companionDisplayMode) => onChange({ companionDisplayMode })}
        />

        <ToggleRow
          label="Show presence controls"
          detail="Shows companion identity and quick display-mode controls. The top visualizer can be hidden separately under Look."
          value={settings.showPresenceControls}
          onChange={(showPresenceControls) => onChange({ showPresenceControls })}
        />
        <ToggleRow
          label="Show conversation controls"
          detail="Shows Regenerate and Retry below the chat."
          value={settings.showConversationControls}
          onChange={(showConversationControls) => onChange({ showConversationControls })}
        />
        <ToggleRow
          label="Show Reset Chat button"
          detail="Shows the button that clears the current conversation after confirmation."
          value={settings.showResetChat}
          onChange={(showResetChat) => onChange({ showResetChat })}
        />
      </ModeSection>
      <ModeSection title="Conversation avatar" editorialDisclosure summary="Portrait size & persona">
        <LiveFullscreenSlider label="Avatar size in conversation" value={settings.conversationAvatarSize} minimum={48} maximum={128} step={4} suffix=" px" onChange={(conversationAvatarSize) => onChange({ conversationAvatarSize })} />
        <Text style={styles.detail}>Only changes avatars above conversation replies. Companion and Portrait keep their own sizes.</Text>
        {onOpenPersona && !editorial ? <Pressable accessibilityRole="button" accessibilityLabel="Change persona or reply model" style={styles.sendDebugButton} onPress={onOpenPersona}><Text style={styles.toggleText}>Persona & reply model</Text></Pressable> : null}
      </ModeSection>
      <ModeSection title="Avatar Stream" editorialDisclosure summary="Stream quality">
        <Segmented label="Quality mode" value={settings.museTalkQuality} options={qualityOptions} onChange={(museTalkQuality) => onChange({ museTalkQuality })} />
      </ModeSection>
      </> : null}
      {activeSection === 'look' ? <>
        <ModeSection title="Interface design">
          <PresentationChooser value={settings.presentationStyle} onChange={presentationStyle => onChange({presentationStyle})} />
        </ModeSection>
        {settings.presentationStyle === 'editorial' ? <Text style={styles.detail}>Editorial uses ivory and copper. Your color theme below is kept for Classic.</Text> : null}
        <ModeSection title="Color theme" editorialDisclosure summary="Saved theme for Classic"><ThemeChooser value={settings.colorTheme} onChange={(colorTheme) => onChange({ colorTheme })} /></ModeSection>
        <ModeSection title="Voice visualizer" editorialDisclosure summary="Style, colors & activity">
          <ToggleRow label="Show visualizer at the top" detail="Reacts to the current voice below the conversation header." value={settings.showTopVoiceThread} onChange={(showTopVoiceThread) => onChange({ showTopVoiceThread })} />
        <VoiceSilkSettings value={settings.silk} palette={settings.voiceThreadPalette} onChange={silk => onChange({ silk })}
          visualizerStyle={settings.voiceVisualizerStyle} onStyleChange={voiceVisualizerStyle => onChange({ voiceVisualizerStyle })} />
        {settings.voiceVisualizerStyle === 'silk' ? <Segmented
          label="Voice silk colors"
          value={settings.voiceThreadPalette}
          options={voiceThreadPaletteOptions}
          onChange={(voiceThreadPalette) => onChange({ voiceThreadPalette })}
        /> : null}
        <Segmented label="Activity indicator" value={settings.chatIndicatorStyle} options={indicatorOptions} onChange={(chatIndicatorStyle) => onChange({ chatIndicatorStyle })} />
        </ModeSection>
        <ModeSection title="Conversation text">
          <Segmented label="Chat text color" value={settings.chatTextColor} options={textColorOptions} onChange={(chatTextColor) => onChange({ chatTextColor })} />
          <Text style={styles.detail}>Applies to assistant replies and your messages. Default restores this design's text color.</Text>
        </ModeSection>
        <ModeSection title="Background & live view">
          <Text style={styles.detail}>Choose a still image or video, adjust dimming, and fine-tune the visualizer and Visual Reply transitions.</Text>
          <Pressable accessibilityRole="button" accessibilityLabel="Background and live view settings" style={styles.sendDebugButton} onPress={() => setSettingsTab('live_fullscreen')}><Text style={styles.toggleText}>Background & live view ›</Text></Pressable>
        </ModeSection>
        <ModeSection title="Interface style" editorialDisclosure summary="Cards, flat or immersive">
        <AppearanceSelector value={settings.interfaceStyle} onChange={(interfaceStyle) => onChange({ interfaceStyle })} />
        </ModeSection>
      </> : null}
      {activeSection === 'voice' ? <>
      <ModeSection title="Phone Audio">
        <Text style={styles.label}>Speech mode</Text>
        <View accessibilityRole="radiogroup" accessibilityLabel="Speech mode" style={styles.segmented}>
          <Pressable accessibilityRole="radio" accessibilityLabel="Backend HQ Audio" accessibilityState={{ checked: settings.audioMode === 'backend_hq' }}
            style={[styles.segment, settings.audioMode === 'backend_hq' && styles.segmentActive]} onPress={() => onChange({ audioMode: 'backend_hq' })}>
            <Text style={styles.segmentText}>Backend HQ Audio</Text>
          </Pressable>
          <Pressable accessibilityRole="radio" accessibilityLabel="Phone Native" accessibilityState={{ checked: settings.audioMode === 'phone_native', disabled: Boolean(nativeDisabledReason) }}
            disabled={Boolean(nativeDisabledReason)} style={[styles.segment, settings.audioMode === 'phone_native' && styles.segmentActive, Boolean(nativeDisabledReason) && { opacity: 0.5 }]}
            onPress={() => onChange({ audioMode: 'phone_native' })}>
            <Text style={styles.segmentText}>Phone Native</Text>
          </Pressable>
        </View>
        <SettingHelp>Backend HQ uses desktop recognition and voices. Phone Native keeps recognition and speech on Android; the desktop still generates chat replies.{PHONE_STORY_MODE_ENABLED ? ' Story always uses Backend HQ Audio.' : ''}</SettingHelp>
        {Platform.OS === 'android' ? <ToggleRow
          label="Experimental progressive LiquidAI audio"
          detail="For future replies with Backend HQ Audio: enable LiquidAI progressive audio on desktop and select No Avatar. Turning this off restores completed-file audio for the next replies. Requires an updated Android app and desktop."
          value={settings.progressiveLiquidAudio}
          disabled={!progressivePcmAvailable() || state?.features?.progressive_audio_version !== 1}
          onChange={progressiveLiquidAudio=>onChange({progressiveLiquidAudio})}
        /> : null}
        {nativeDisabledReason ? <Text style={styles.detail}>{nativeDisabledReason}</Text> : null}
        <Pressable accessibilityRole="button" accessibilityLabel="Set up Phone Native audio" accessibilityState={{ expanded: nativeSpeech.setupOpen }}
          style={styles.sendDebugButton} onPress={nativeSpeech.setupOpen ? nativeSpeech.closeSetup : nativeSpeech.openSetup}>
          <Text style={styles.toggleText}>{nativeSpeech.setupOpen ? 'Hide Phone Native setup' : 'Set up Phone Native audio'}</Text>
        </Pressable>
        {nativeSpeech.setupOpen ? (
          <View style={styles.group}>
            <SettingHelp>The local voice belongs to this phone. It does not clone or use the desktop persona’s TTS voice. Persona, model and Visual Reply controls still work normally.</SettingHelp>
            <SettingHelp>Android microphone permission also enables the voice silk’s live audio sampling during typed replies. Allowing permission here does not start recording.</SettingHelp>
            <Pressable accessibilityRole="button" accessibilityLabel="Allow microphone and voice visualization" style={styles.sendDebugButton}
              onPress={() => void nativeSpeech.requestMicrophonePermission()}>
              <Text style={styles.toggleText}>Allow microphone and voice visualization</Text>
            </Pressable>
            <Text style={styles.label}>Local language (empty uses device language)</Text>
            <TextInput accessibilityLabel="Phone Native language" value={nativeLanguage} autoCapitalize="none" autoCorrect={false}
              placeholder="Device language, or en-US / sv-SE" placeholderTextColor={colors.muted}
              style={[styles.segment, { color: colors.text }]} onChangeText={setNativeLanguage}
              onEndEditing={() => onChange({ nativeLanguage })} />
            <Text style={styles.diag}>Device language: {nativeSpeech.capabilities?.deviceLanguage || 'Not checked'}</Text>
            <Text style={styles.diag}>Recognition: {nativeSpeech.capabilities?.stt.available ? `${nativeSpeech.capabilities.stt.provider === 'sherpa_onnx' ? 'Sherpa Moonshine' : 'Android offline'} / ${nativeSpeech.capabilities.stt.language}` : 'Not ready'}</Text>
            {nativeSpeech.capabilities?.stt.reason ? <Text style={styles.detail}>{nativeReason(nativeSpeech.capabilities.stt.reason)}</Text> : null}
            <Text style={styles.diag}>Speech: {nativeSpeech.capabilities?.tts.available ? `${nativeSpeech.capabilities.tts.provider === 'sherpa_onnx' ? 'Sherpa Kitten' : 'Android offline voice'} / ${nativeSpeech.capabilities.tts.language}` : 'Not ready'}</Text>
            {nativeSpeech.capabilities?.tts.reason ? <Text style={styles.detail}>{nativeReason(nativeSpeech.capabilities.tts.reason)}</Text> : null}
            <Text style={styles.diag}>English models: recognition {nativeSpeech.capabilities?.models.sttInstalled ? 'installed' : 'not installed'}; speech {nativeSpeech.capabilities?.models.ttsInstalled ? 'installed' : 'not installed'}</Text>
            {nativeSpeech.capabilities?.tts.provider === 'sherpa_onnx' ? (
              <Segmented label="Local Kitten voice" value={String(settings.nativeSpeakerId)}
                options={Array.from({ length: 8 }, (_, id) => ({ value: String(id), label: `Kitten voice ${id}` }))}
                onChange={(id) => onChange({ nativeSpeakerId: Number(id) })} />
            ) : null}
            <SettingHelp>Optional English packs: about 61 MB download. Download starts only when you tap below. Other languages need matching installed Android offline recognition and voice data; availability depends on the device.</SettingHelp>
            <Pressable accessibilityRole="button" accessibilityLabel="Download English speech models" disabled={nativeSpeech.installing || nativeSpeech.capabilities?.reason === 'native_build_required'}
              style={styles.sendDebugButton} onPress={() => void nativeSpeech.installModels()}>
              <Text style={styles.toggleText}>{nativeSpeech.installing ? 'Installing English speech models...' : 'Download English speech models (about 61 MB)'}</Text>
            </Pressable>
            {nativeSpeech.installing && nativeSpeech.progress ? <Text accessibilityLiveRegion="polite" style={styles.detail}>
              {nativeSpeech.progress.phase === 'extracting' || nativeSpeech.progress.totalBytes <= 0
                ? 'Extracting models...'
                : `${nativeSpeech.progress.phase}: ${Math.min(100, Math.round(nativeSpeech.progress.bytes / nativeSpeech.progress.totalBytes * 100))}%`}
            </Text> : null}
            <Pressable accessibilityRole="button" accessibilityLabel="Refresh offline speech availability" disabled={nativeSpeech.probing || nativeSpeech.installing}
              style={styles.sendDebugButton} onPress={() => {
                // Android can dismiss the keyboard without ending editing. The
                // committed language effect probes after the new setting reaches the hook.
                if (nativeLanguage !== settings.nativeLanguage) onChange({ nativeLanguage });
                else void nativeSpeech.refreshCapabilities();
              }}>
              <Text style={styles.toggleText}>{nativeSpeech.probing ? 'Checking offline speech...' : nativeLanguage !== settings.nativeLanguage ? 'Apply language and refresh availability' : 'Refresh offline speech availability'}</Text>
            </Pressable>
            {nativeSpeech.error ? <Text accessibilityRole="alert" style={styles.error}>{nativeSpeech.error}</Text> : null}
          </View>
        ) : null}
        <ToggleRow label="Autoplay TTS on phone" value={settings.phoneTtsAutoplay} onChange={(phoneTtsAutoplay) => onChange({ phoneTtsAutoplay })} />
        <ToggleRow label="Headphone Next toggles pause / play" value={settings.headphoneNextTogglesPlayback} onChange={(headphoneNextTogglesPlayback) => onChange({ headphoneNextTogglesPlayback })} />
        <SettingHelp>For text-chat audio. Enable this if your headphones send Next on a double-tap. Play and Pause gestures work directly. Live Mode keeps its existing controls.</SettingHelp>
        <LiveFullscreenSlider
          label="Phone TTS volume"
          value={volumePercent}
          suffix="%"
          minimum={0}
          maximum={100}
          step={1}
          touchHeight={36}
          onChange={(value) => onChange({ phoneTtsVolume: value / 100 })}
        />
        <LiveFullscreenSlider
          label="Automated user voice volume"
          value={Math.round(settings.automatedUserTtsVolume * 100)}
          minimum={0}
          maximum={100}
          step={1}
          touchHeight={36}
          onChange={(value) => onChange({ automatedUserTtsVolume: value / 100 })}
        />
        <SettingHelp>For spoken automated user responses in Continuous Mode, including assigned character voices. Separate from assistant speech and Soundscape.</SettingHelp>
        <Text style={styles.detail}>Phone-started replies play here. Desktop-started replies stay on the computer.</Text>
        <Segmented label="Narration pace" value={settings.phoneNarrationPace}
          options={[{value:'original',label:'Original'},{value:'storyteller',label:'Storyteller'}]}
          onChange={(phoneNarrationPace) => onChange({phoneNarrationPace})} />
        <SettingHelp>Storyteller keeps the natural voice speed, with a light breath at commas and a longer pause at sentence endings. Applies from the next ordinary audio segment, including Replay. Replies synchronized with the avatar keep their original timing. Updated desktop speech adds phrase breaks to new replies; older audio keeps its existing breaks. Original adds no extra pauses.</SettingHelp>
        <IosLiveAudioSettings settings={settings} onChange={onChange} />
      </ModeSection>

      <ModeSection title="Voice Input" editorialDisclosure summary="Microphone & Live Mode">
        <Segmented label="Send mode" value={settings.sendMode} options={sendModeOptions} onChange={(sendMode) => onChange({ sendMode })} />
        <Segmented label="Microphone" value={settings.micBehavior} options={micOptions} onChange={(micBehavior) => onChange({ micBehavior })} />
        {Platform.OS === 'android' && settings.audioMode === 'backend_hq' ? (
          <>
            <LiveFullscreenSlider label="Live Mic sensitivity" value={settings.liveMicSensitivity}
              minimum={1} maximum={5} step={1} suffix="/5"
              onChange={(liveMicSensitivity) => onChange({ liveMicSensitivity })} />
            <SettingHelp>Higher detects quieter speech from farther away, but may react to room noise. Default: 4. Stop and restart Live Mode to apply a change.</SettingHelp>
          </>
        ) : null}
        {settings.audioMode === 'phone_native' ? (
          nativeSpeech.capabilities?.micSensitivitySupported && nativeSpeech.capabilities.stt.provider === 'sherpa_onnx' ? (
            <>
              <Stepper label="Mic sensitivity" value={normalizeNativeMicSensitivity(settings.nativeMicSensitivity)}
                suffix="/5" minimum={1} maximum={5} step={1}
                onChange={(nativeMicSensitivity) => onChange({ nativeMicSensitivity })} />
              <SettingHelp>Phone Native · Sherpa Mic and Live Mode. Higher picks up quieter speech; lower rejects more quiet sounds. Background-noise protection stays active.</SettingHelp>
              <Text style={styles.detail}>Default: 3. Changes apply on the next recording. Stop and restart Live Mode to apply them.</Text>
              <Pressable accessibilityLabel="Reset mic sensitivity" accessibilityRole="button"
                style={[styles.sendDebugButton, { minHeight: 44, justifyContent: 'center' }]}
                onPress={() => onChange({ nativeMicSensitivity: 3 })}>
                <Text style={styles.toggleText}>Reset to 3</Text>
              </Pressable>
            </>
          ) : (
            <Text style={styles.detail}>{nativeSpeech.capabilities?.stt.provider === 'android_offline'
              ? 'Android offline recognition manages its own microphone sensitivity. Your Sherpa setting is kept for when you switch back.'
              : !nativeSpeech.capabilities?.micSensitivitySupported
                ? 'Mic sensitivity requires an updated custom Android app and the local Sherpa recognizer.'
                : 'Set up the local Sherpa recognizer to adjust Mic and Live Mode sensitivity.'}</Text>
          )
        ) : null}
      </ModeSection>

      </> : null}
      {activeSection === 'tools' ? <>
      {toolsContent}
      <ModeSection title="Chat history" editorialDisclosure summary="Messages kept on your phone">
        <Stepper label="Retained chat messages" value={settings.retainedChatMessages}
          suffix="" minimum={10} maximum={100} step={10}
          onChange={(retainedChatMessages) => onChange({ retainedChatMessages })} />
        <Text style={styles.detail}>Show the latest messages first. Scroll up in chat to load earlier messages in batches.</Text>
      </ModeSection>
      <MediaCacheSettings />
      <ModeSection title="Connection" editorialDisclosure summary="Reconnect & screen behavior">
        <ToggleRow label="Auto reconnect" value={settings.autoReconnect} onChange={(autoReconnect) => onChange({ autoReconnect })} />
        <ToggleRow label="Keep screen awake" value={settings.keepAwake} onChange={(keepAwake) => onChange({ keepAwake })} />
        <Stepper
          label="Polling interval"
          value={pollSeconds}
          suffix="s"
          minimum={0.9}
          maximum={15}
          step={0.5}
          onChange={(value) => onChange({ pollingIntervalMs: Math.round(value * 1000) })}
        />
      </ModeSection>



      <ModeSection>
        <View style={styles.cardHeaderRow}>
          <Text style={styles.cardTitle}>Diagnostics</Text>
          <Pressable accessibilityLabel={`${showDiagnostics ? 'Hide' : 'Show'} diagnostics`} accessibilityRole="button" accessibilityState={{ expanded: showDiagnostics }} style={styles.diagnosticsToggle} onPress={() => setDiagnosticsOpen((value) => !value)}>
            <Text style={styles.toggleText}>{showDiagnostics ? 'Hide' : 'Show'}</Text>
          </Pressable>
        </View>
        {showDiagnostics ? (
          <>
            <Diagnostics health={health} status={status} transport={transport} error={error} />
            <Text style={styles.detail}>Phone log: {phoneDebugFileName()}</Text>
            <Text selectable style={styles.detail}>Desktop log: runtime/main_chat_remote/phone_debug/phone_remote.log</Text>
            <SettingHelp>The diagnostic file includes request timing, runtime queue status, LLM counts, and phone-audio routing. Chat text, photos, credentials, and pairing codes are excluded.</SettingHelp>
            <Pressable
              accessibilityLabel="Send debug log to desktop"
              accessibilityRole="button"
              style={styles.sendDebugButton}
              onPress={() => {
                setDebugStatus('Sending...');
                onSendDebug()
                  .then((count) => setDebugStatus(count ? `Sent ${count} event(s) to desktop.` : 'No queued events to send.'))
                  .catch((exc) => setDebugStatus(exc instanceof Error ? exc.message : 'Debug upload failed.'));
              }}
            >
              <Text style={styles.toggleText}>Send diagnostic file</Text>
            </Pressable>
            {debugStatus ? <Text selectable style={styles.detail}>{debugStatus}</Text> : null}
          </>
        ) : (
          <Text style={styles.detail}>Hidden unless there is a connection error.</Text>
        )}
      </ModeSection>
      <RuntimeSummary state={state} />
      </> : null}
      </ScrollView>
      )}
      <View accessibilityLabel="Settings sections" accessibilityRole="tablist" style={[styles.settingsTabs, editorial && {display:'none'}]}>
        {(['companion', 'voice', 'look', 'tools'] as const).map(value => <Pressable key={value} accessibilityRole="tab" accessibilityLabel={value.charAt(0).toUpperCase() + value.slice(1)} accessibilityState={{ selected: activeSection === value }} onPress={() => selectSection(value)} style={[styles.settingsTab, activeSection === value && styles.settingsTabActive]}>
          <AppIcon name={value} size={20} color={activeSection === value ? colors.accent : colors.muted} />
          <Text style={[styles.settingsTabText, activeSection === value && styles.settingsTabTextActive]}>{value.charAt(0).toUpperCase() + value.slice(1)}</Text>
        </Pressable>)}
      </View>
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  helpToggle:{minHeight:44,justifyContent:'center'},
  panel: {
    flex: 1,
  },
  generalPanel: {
    flex: 1,
  },
  settingsTabs: { flexDirection: 'row', paddingHorizontal: 8, paddingVertical: 6, backgroundColor: colors.backgroundElevated, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.borderSoft, gap: 4 },
  settingsTab: { flex: 1, minHeight: 58, minWidth: 0, alignItems: 'center', justifyContent: 'center', gap: 4, borderRadius: 14 },
  settingsTabActive: { backgroundColor: colors.accentSoft },
  settingsTabText: { color: colors.muted, fontSize: 11, fontWeight: '500' },
  settingsTabTextActive: { color: colors.accent },
  sectionTitle: { color: colors.text, fontSize: 24, fontWeight: '600', marginTop: 10, marginBottom: 12 },
  backToLook: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 16 },
  content: {
    gap: spacing.sm,
    paddingBottom: spacing.xl,
    paddingHorizontal: spacing.lg,
  },
  card: {
    backgroundColor: colors.panel,
    borderColor: colors.border,
    borderRadius: 12,
    borderWidth: 1,
    gap: spacing.sm,
    padding: spacing.md,
  },
  cardTitle: {
    color: colors.text,
    fontSize: 14,
    fontWeight: '800',
  },
  cardHeaderRow: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  row: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: spacing.sm,
    justifyContent: 'space-between',
  },
  rowText: {
    flex: 1,
  },
  label: {
    color: colors.text,
    fontSize: 13,
    fontWeight: '700',
  },
  detail: {
    color: colors.muted,
    fontSize: 12,
    lineHeight: 16,
    marginTop: 2,
  },
  toggle: {
    alignItems: 'center',
    borderColor: colors.border,
    borderRadius: 12,
    borderWidth: 1,
    minWidth: 58,
    minHeight: 44,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  toggleActive: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.accent,
  },
  toggleText: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '800',
  },
  diagnosticsToggle: {
    borderColor: colors.border,
    borderRadius: 12,
    borderWidth: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  diagnosticsBody: {
    gap: spacing.xs,
  },
  sendDebugButton: { alignItems: 'center', borderColor: colors.border, borderRadius: 12, borderWidth: 1, marginTop: spacing.xs, padding: spacing.sm },
  group: {
    gap: spacing.xs,
  },
  segmented: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
  },
  segment: {
    borderColor: colors.border,
    borderRadius: 12,
    borderWidth: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  segmentActive: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.accent,
  },
  segmentText: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: '700',
  },
  segmentTextActive: {
    color: colors.text,
  },
  stepper: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: spacing.sm,
  },
  stepButton: {
    alignItems: 'center',
    backgroundColor: colors.panelAlt,
    borderColor: colors.border,
    borderRadius: 12,
    borderWidth: 1,
    height: 44,
    justifyContent: 'center',
    width: 44,
  },
  stepText: {
    color: colors.text,
    fontSize: 18,
    fontWeight: '800',
  },
  valueText: {
    color: colors.text,
    fontSize: 13,
    fontWeight: '800',
    minWidth: 48,
    textAlign: 'center',
  },
  diag: {
    color: colors.muted,
    fontSize: 12,
    lineHeight: 17,
  },
  error: {
    color: colors.danger,
  },
});
