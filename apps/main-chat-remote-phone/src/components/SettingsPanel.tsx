import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { RemoteConnectionStatus, RemoteEnvelope, RemoteHealth, RemoteState, RemoteTransport } from '../api/types';
import type { ChatIndicatorStyle, ChatTextColor, MicBehavior, MuseTalkQuality, PhoneSettings, SendMode } from '../hooks/usePhoneSettings';
import { AppearanceSelector } from './AppearanceSelector';
import { ModeSection } from './ModeSurface';
import { colors, spacing } from '../styles/theme';
import { phoneDebugFileName } from '../utils/phoneDebug';

type Props = {
  settings: PhoneSettings;
  onChange: (updates: Partial<PhoneSettings>) => void;
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
  { value: 'text_only', label: 'Text only' },
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
  { value: 'white', label: 'White' },
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

function ToggleRow({ label, value, onChange, detail }: { label: string; value: boolean; detail?: string; onChange: (value: boolean) => void }) {
  return (
    <View style={styles.row}>
      <View style={styles.rowText}>
        <Text style={styles.label}>{label}</Text>
        {detail ? <Text style={styles.detail}>{detail}</Text> : null}
      </View>
      <Pressable style={[styles.toggle, value && styles.toggleActive]} onPress={() => onChange(!value)}>
        <Text style={styles.toggleText}>{value ? 'On' : 'Off'}</Text>
      </Pressable>
    </View>
  );
}

function Segmented<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: Array<Option<T>>; onChange: (value: T) => void }) {
  return (
    <View style={styles.group}>
      <Text style={styles.label}>{label}</Text>
      <View style={styles.segmented}>
        {options.map((option) => {
          const selected = option.value === value;
          return (
            <Pressable key={option.value} style={[styles.segment, selected && styles.segmentActive]} onPress={() => onChange(option.value)}>
              <Text style={[styles.segmentText, selected && styles.segmentTextActive]}>{option.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

function Stepper({ label, value, suffix, minimum, maximum, step, onChange }: { label: string; value: number; suffix: string; minimum: number; maximum: number; step: number; onChange: (value: number) => void }) {
  const nextValue = (direction: -1 | 1) => Math.max(minimum, Math.min(maximum, value + step * direction));
  return (
    <View style={styles.row}>
      <Text style={styles.label}>{label}</Text>
      <View style={styles.stepper}>
        <Pressable style={styles.stepButton} onPress={() => onChange(nextValue(-1))}>
          <Text style={styles.stepText}>-</Text>
        </Pressable>
        <Text style={styles.valueText}>{value}{suffix}</Text>
        <Pressable style={styles.stepButton} onPress={() => onChange(nextValue(1))}>
          <Text style={styles.stepText}>+</Text>
        </Pressable>
      </View>
    </View>
  );
}

function Diagnostics({ health, status, transport, error }: { health: RemoteEnvelope<RemoteHealth> | null; status: RemoteConnectionStatus; transport: RemoteTransport; error: string }) {
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
      <ModeSection title="Runtime Settings">
        <Text style={styles.diag}>LLM: {settings?.chat_provider || runtime?.chat_provider || 'unknown'} {settings?.model_name || runtime?.model_name ? `/ ${settings?.model_name || runtime?.model_name}` : ''}</Text>
        <Text style={styles.diag}>STT: {settings?.stt_backend || 'unknown'} {settings?.stt_model_size ? `/ ${settings.stt_model_size}` : ''}</Text>
        <Text style={styles.diag}>TTS: {settings?.tts_backend || runtime?.tts_backend || 'unknown'}</Text>
        <Text style={styles.diag}>Visual Reply: {settings?.visual_reply_provider || visualProvider}</Text>
      </ModeSection>
      <ModeSection title="Buddy Chat">
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

export function SettingsPanel({ settings, onChange, state, health, status, transport, error, onSendDebug }: Props) {
  const [diagnosticsOpen, setDiagnosticsOpen] = React.useState(false);
  const [debugStatus, setDebugStatus] = React.useState('');
  const volumePercent = Math.round(settings.phoneTtsVolume * 100);
  const pollSeconds = Math.round(settings.pollingIntervalMs / 100) / 10;
  const showDiagnostics = Boolean(error || state?.buddy_chat?.last_provider_error) || diagnosticsOpen;
  return (
    <ScrollView style={styles.panel} contentContainerStyle={styles.content}>
      <ModeSection title="Appearance">
        <AppearanceSelector value={settings.interfaceStyle} onChange={(interfaceStyle) => onChange({ interfaceStyle })} />
        <Segmented label="Chat text color" value={settings.chatTextColor} options={textColorOptions} onChange={(chatTextColor) => onChange({ chatTextColor })} />
        <Segmented label="Activity indicator" value={settings.chatIndicatorStyle} options={indicatorOptions} onChange={(chatIndicatorStyle) => onChange({ chatIndicatorStyle })} />
      </ModeSection>
      <ModeSection title="Phone Audio">
        <ToggleRow label="Autoplay TTS on phone" value={settings.phoneTtsAutoplay} onChange={(phoneTtsAutoplay) => onChange({ phoneTtsAutoplay })} />
        <Stepper
          label="Phone TTS volume"
          value={volumePercent}
          suffix="%"
          minimum={0}
          maximum={100}
          step={10}
          onChange={(value) => onChange({ phoneTtsVolume: value / 100 })}
        />
        <ToggleRow
          label="Play on computer too"
          detail="Remote sends keep desktop audio off unless this is enabled."
          value={settings.playOnBackend}
          onChange={(playOnBackend) => onChange({ playOnBackend })}
        />
      </ModeSection>

      <ModeSection title="Voice Input">
        <Segmented label="Send mode" value={settings.sendMode} options={sendModeOptions} onChange={(sendMode) => onChange({ sendMode })} />
        <Segmented label="Microphone" value={settings.micBehavior} options={micOptions} onChange={(micBehavior) => onChange({ micBehavior })} />
      </ModeSection>

      <ModeSection title="Connection">
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

      <ModeSection title="Avatar Stream">
        <Segmented label="Quality mode" value={settings.museTalkQuality} options={qualityOptions} onChange={(museTalkQuality) => onChange({ museTalkQuality })} />
      </ModeSection>

      <ModeSection>
        <View style={styles.cardHeaderRow}>
          <Text style={styles.cardTitle}>Diagnostics</Text>
          <Pressable style={styles.diagnosticsToggle} onPress={() => setDiagnosticsOpen((value) => !value)}>
            <Text style={styles.toggleText}>{showDiagnostics ? 'Hide' : 'Show'}</Text>
          </Pressable>
        </View>
        {showDiagnostics ? (
          <>
            <Diagnostics health={health} status={status} transport={transport} error={error} />
            <Text style={styles.detail}>Phone log: {phoneDebugFileName()}</Text>
            <Pressable
              style={styles.sendDebugButton}
              onPress={() => {
                setDebugStatus('Sending...');
                onSendDebug()
                  .then((count) => setDebugStatus(count ? `Sent ${count} event(s) to desktop.` : 'No queued events to send.'))
                  .catch((exc) => setDebugStatus(exc instanceof Error ? exc.message : 'Debug upload failed.'));
              }}
            >
              <Text style={styles.toggleText}>Send debug now</Text>
            </Pressable>
            {debugStatus ? <Text selectable style={styles.detail}>{debugStatus}</Text> : null}
          </>
        ) : (
          <Text style={styles.detail}>Hidden unless there is a connection error.</Text>
        )}
      </ModeSection>
      <RuntimeSummary state={state} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  panel: {
    flex: 1,
  },
  content: {
    gap: spacing.sm,
    paddingBottom: spacing.lg,
  },
  card: {
    backgroundColor: colors.panel,
    borderColor: colors.border,
    borderRadius: 6,
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
    borderRadius: 6,
    borderWidth: 1,
    minWidth: 58,
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
    borderRadius: 6,
    borderWidth: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  diagnosticsBody: {
    gap: spacing.xs,
  },
  sendDebugButton: { alignItems: 'center', borderColor: colors.border, borderRadius: 6, borderWidth: 1, marginTop: spacing.xs, padding: spacing.sm },
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
    borderRadius: 6,
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
    borderRadius: 6,
    borderWidth: 1,
    height: 32,
    justifyContent: 'center',
    width: 36,
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
