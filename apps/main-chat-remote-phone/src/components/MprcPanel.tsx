import React, { useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import type { MprcAction, MprcCastAction, MprcSendOptions } from '../api/client';
import type { MprcCastDevice, MprcChoice, MprcMemoryState, MprcPersona, MprcSegment, MprcState } from '../api/types';
import { colors, spacing } from '../styles/theme';

type Props = {
  mprc: MprcState | undefined;
  disabled: boolean;
  onSend: (text: string, options?: MprcSendOptions) => Promise<void>;
  onChoice: (choice: string) => Promise<void>;
  onAction: (action: MprcAction) => Promise<void>;
  onCastAction: (action: MprcCastAction, deviceName?: string) => Promise<void>;
  onRefresh: () => Promise<void>;
};

const intentOptions = ['Auto', 'Continue', 'Act', 'Say'];

function clean(value: unknown, fallback = ''): string {
  const text = String(value ?? '').trim();
  return text || fallback;
}

function personaName(persona: MprcPersona): string {
  return clean(persona.display_name || persona.id, 'Persona');
}

function segmentTitle(segment: MprcSegment): string {
  const role = clean(segment.role, 'story');
  const speaker = clean(segment.speaker_name || segment.speaker_id, role);
  return `${speaker} - ${role}`;
}

function choiceText(choice: MprcChoice): string {
  return clean(choice.text || choice.id, 'Choice');
}

function castDeviceName(device: MprcCastDevice): string {
  return clean(device.name || device.label || device.uuid, 'Chromecast');
}

function castDeviceMeta(device: MprcCastDevice): string {
  const parts = [device.model_name, device.host, device.cast_type]
    .map((item) => clean(item))
    .filter(Boolean);
  return parts.join(' - ');
}

function memoryStatus(memory: MprcMemoryState | undefined): string {
  if (!memory?.available) {
    return clean(memory?.message, 'Unavailable');
  }
  const backend = clean(memory.backend, 'memory');
  const database = memory.database_available ? clean(memory.database_status, 'ready') : 'JSON only';
  const databank = memory.databank_available ? 'data bank on' : 'data bank off';
  return `${backend} - ${database} - ${databank}`;
}

export function MprcPanel({ mprc, disabled, onSend, onChoice, onAction, onCastAction, onRefresh }: Props) {
  const [text, setText] = useState('');
  const [intent, setIntent] = useState('Auto');
  const [speakerId, setSpeakerId] = useState('');
  const [selectedCastDevice, setSelectedCastDevice] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const available = !disabled && mprc?.available === true;
  const session = mprc?.session;
  const personas = useMemo(() => (mprc?.personas ?? []).filter((persona) => persona.enabled !== false), [mprc?.personas]);
  const cast = mprc?.cast;
  const memory = mprc?.memory;
  const castDevices = useMemo(() => cast?.devices ?? [], [cast?.devices]);
  const segments = mprc?.segments ?? [];
  const choices = mprc?.choices ?? [];
  const speechItems = mprc?.speech_audio?.items ?? [];
  const sceneTitle = clean(session?.scene_title, 'Story Mode');
  const modeText = clean(session?.mode, available ? 'active' : 'offline');
  const selectedSpeaker = personas.find((persona) => persona.id === speakerId);
  const castReady = available && cast?.available !== false && !cast?.dependency_error;
  const castBusy = Boolean(cast?.busy || busy);
  const castSelectedName = clean(selectedCastDevice || cast?.selected_device || cast?.active_device);
  const castStatus = cast?.casting
    ? `Casting to ${clean(cast?.active_device || castSelectedName, 'device')}`
    : clean(cast?.status, cast?.dependency_error ? 'Cast dependencies missing' : 'Not casting');

  useEffect(() => {
    if (!speakerId) {
      return;
    }
    if (!personas.some((persona) => persona.id === speakerId)) {
      setSpeakerId('');
    }
  }, [personas, speakerId]);

  useEffect(() => {
    setSelectedCastDevice((current) => {
      if (current && castDevices.some((device) => castDeviceName(device) === current)) {
        return current;
      }
      const configured = clean(cast?.selected_device || cast?.active_device);
      if (configured) {
        return configured;
      }
      const firstDevice = castDevices[0];
      return firstDevice ? castDeviceName(firstDevice) : '';
    });
  }, [cast?.active_device, cast?.selected_device, castDevices]);

  const run = async (label: string, action: () => Promise<void>, restoreText = '') => {
    if (busy) {
      return;
    }
    setBusy(label);
    setError('');
    try {
      await action();
    } catch (exc) {
      if (restoreText) {
        setText(restoreText);
      }
      setError(exc instanceof Error ? exc.message : 'Story action failed.');
    } finally {
      setBusy('');
    }
  };

  const send = () => {
    const next = text.trim();
    if (!next) {
      return;
    }
    setText('');
    run('send', () => onSend(next, { intent, speakerId }), next).catch(() => undefined);
  };

  const disabledControls = !available || Boolean(busy);

  return (
    <View style={styles.panel}>
      <View style={styles.header}>
        <View style={styles.headerText}>
          <Text style={styles.title}>Multi Persona Story</Text>
          <Text style={styles.meta} numberOfLines={1}>{sceneTitle} - {modeText}</Text>
        </View>
        <Text style={[styles.status, available ? styles.statusOk : styles.statusMuted]}>
          {available ? `Turn ${Number(session?.turn_index ?? 0)}` : clean(mprc?.message, 'Unavailable')}
        </Text>
      </View>

      <View style={styles.actions}>
        <Pressable disabled={disabledControls} style={[styles.secondaryButton, disabledControls && styles.disabled]} onPress={() => run('play', () => onAction('play'))}>
          <Text style={styles.buttonText}>{busy === 'play' ? 'Playing' : 'Play'}</Text>
        </Pressable>
        <Pressable disabled={disabledControls} style={[styles.secondaryButton, disabledControls && styles.disabled]} onPress={() => run('pause', () => onAction('pause'))}>
          <Text style={styles.buttonText}>Pause</Text>
        </Pressable>
        <Pressable disabled={disabledControls} style={[styles.secondaryButton, disabledControls && styles.disabled]} onPress={() => run('visual', () => onAction('visual'))}>
          <Text style={styles.buttonText}>Visual</Text>
        </Pressable>
        <Pressable disabled={Boolean(busy)} style={[styles.secondaryButton, busy && styles.disabled]} onPress={() => run('refresh', onRefresh)}>
          <Text style={styles.buttonText}>Refresh</Text>
        </Pressable>
      </View>

      <View style={styles.castBox}>
        <View style={styles.storyHeader}>
          <Text style={styles.sectionTitle}>Chromecast</Text>
          <Text style={[styles.meta, cast?.casting ? styles.castOk : cast?.dependency_error ? styles.castWarning : undefined]} numberOfLines={1}>
            {castStatus}
          </Text>
        </View>
        {cast?.stream?.url ? <Text style={styles.meta} numberOfLines={1}>{cast.stream.url}</Text> : null}
        {cast?.dependency_error ? <Text style={styles.warningText}>{cast.dependency_error}</Text> : null}
        <View style={styles.actions}>
          <Pressable disabled={!available || castBusy} style={[styles.secondaryButton, (!available || castBusy) && styles.disabled]} onPress={() => run('cast-refresh', () => onCastAction('refresh'))}>
            <Text style={styles.buttonText}>{busy === 'cast-refresh' ? 'Finding' : 'Find Cast'}</Text>
          </Pressable>
          {cast?.dependency_error ? (
            <Pressable disabled={!available || castBusy} style={[styles.secondaryButton, (!available || castBusy) && styles.disabled]} onPress={() => run('cast-install', () => onCastAction('install'))}>
              <Text style={styles.buttonText}>{busy === 'cast-install' ? 'Installing' : 'Install Cast'}</Text>
            </Pressable>
          ) : null}
          <Pressable
            disabled={!castReady || castBusy || !castSelectedName}
            style={[styles.secondaryButton, styles.activeButton, (!castReady || castBusy || !castSelectedName) && styles.disabled]}
            onPress={() => run('cast-start', () => onCastAction('start', castSelectedName))}
          >
            <Text style={styles.buttonText}>{busy === 'cast-start' ? 'Starting' : 'Start Cast'}</Text>
          </Pressable>
          <Pressable disabled={!available || castBusy || !cast?.casting} style={[styles.secondaryButton, (!available || castBusy || !cast?.casting) && styles.disabled]} onPress={() => run('cast-stop', () => onCastAction('stop'))}>
            <Text style={styles.buttonText}>Stop Cast</Text>
          </Pressable>
        </View>
        {castDevices.length ? (
          <View style={styles.personaRow}>
            {castDevices.map((device) => {
              const name = castDeviceName(device);
              const meta = castDeviceMeta(device);
              const selected = name === castSelectedName;
              return (
                <Pressable
                  key={`${device.uuid || name}-${device.host || ''}`}
                  disabled={!available || castBusy}
                  style={[styles.chip, selected && styles.chipSelected, (!available || castBusy) && styles.disabled]}
                  onPress={() => setSelectedCastDevice(name)}
                >
                  <Text style={styles.chipText}>{name}</Text>
                  {meta ? <Text style={styles.chipMeta}>{meta}</Text> : null}
                </Pressable>
              );
            })}
          </View>
        ) : (
          <Text style={styles.emptyText}>Use Find Cast to discover Chromecast devices on this LAN.</Text>
        )}
      </View>

      <View style={styles.sceneGrid}>
        <View style={styles.sceneCell}>
          <Text style={styles.label}>Location</Text>
          <Text style={styles.value} numberOfLines={2}>{clean(session?.location, 'Unset')}</Text>
        </View>
        <View style={styles.sceneCell}>
          <Text style={styles.label}>Mood</Text>
          <Text style={styles.value} numberOfLines={2}>{clean(session?.mood, 'Unset')}</Text>
        </View>
        <View style={styles.sceneCellWide}>
          <Text style={styles.label}>Objective</Text>
          <Text style={styles.value} numberOfLines={3}>{clean(session?.objective || session?.scene_summary, 'No active objective')}</Text>
        </View>
      </View>

      <View style={styles.memoryBox}>
        <View style={styles.storyHeader}>
          <Text style={styles.sectionTitle}>Story Memory</Text>
          <Text style={[styles.meta, memory?.database_available ? styles.castOk : undefined]} numberOfLines={1}>
            {memoryStatus(memory)}
          </Text>
        </View>
        <View style={styles.memoryGrid}>
          <View style={styles.memoryCell}>
            <Text style={styles.label}>Events</Text>
            <Text style={styles.memoryNumber}>{Number(memory?.event_count ?? 0)}</Text>
          </View>
          <View style={styles.memoryCell}>
            <Text style={styles.label}>Chapters</Text>
            <Text style={styles.memoryNumber}>{Number(memory?.chapter_count ?? 0)}</Text>
          </View>
          <View style={styles.memoryCell}>
            <Text style={styles.label}>Pinned</Text>
            <Text style={styles.memoryNumber}>{Number(memory?.pinned_fact_count ?? 0)}</Text>
          </View>
          <View style={styles.memoryCell}>
            <Text style={styles.label}>Cast Notes</Text>
            <Text style={styles.memoryNumber}>{Number(memory?.character_memory_count ?? 0)}</Text>
          </View>
        </View>
        <Text style={styles.meta}>
          Data bank sources: {Number(memory?.indexed_databank_source_count ?? 0)} indexed / {Number(memory?.configured_databank_source_count ?? 0)} configured
        </Text>
        {clean(memory?.fallback_note) ? <Text style={styles.warningText}>{clean(memory?.fallback_note)}</Text> : null}
      </View>

      <Text style={styles.sectionTitle}>Cast</Text>
      <View style={styles.personaRow}>
        <Pressable disabled={disabledControls} style={[styles.chip, !speakerId && styles.chipSelected, disabledControls && styles.disabled]} onPress={() => setSpeakerId('')}>
          <Text style={styles.chipText}>Auto speaker</Text>
        </Pressable>
        {personas.map((persona) => {
          const selected = speakerId === persona.id;
          return (
            <Pressable
              key={persona.id}
              disabled={disabledControls}
              style={[styles.chip, selected && styles.chipSelected, persona.current_speaker && styles.chipCurrent, disabledControls && styles.disabled]}
              onPress={() => setSpeakerId(persona.id)}
            >
              <Text style={styles.chipText}>{personaName(persona)}</Text>
              <Text style={styles.chipMeta}>
                {persona.narrator ? 'Narrator' : persona.current_speaker ? 'Speaking' : persona.active ? 'Active' : clean(persona.role, 'Cast')}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <Text style={styles.sectionTitle}>Reply Mode</Text>
      <View style={styles.actions}>
        {intentOptions.map((item) => (
          <Pressable
            key={item}
            disabled={disabledControls}
            style={[styles.secondaryButton, intent === item && styles.activeButton, disabledControls && styles.disabled]}
            onPress={() => setIntent(item)}
          >
            <Text style={styles.buttonText}>{item}</Text>
          </Pressable>
        ))}
      </View>

      <View style={styles.inputBlock}>
        <TextInput
          value={text}
          onChangeText={setText}
          editable={!disabledControls}
          multiline
          placeholder={selectedSpeaker ? `Message as ${personaName(selectedSpeaker)}` : 'Story message'}
          placeholderTextColor={colors.muted}
          style={styles.input}
        />
        <Pressable disabled={disabledControls || !text.trim()} style={[styles.sendButton, (disabledControls || !text.trim()) && styles.disabled]} onPress={send}>
          <Text style={styles.buttonText}>{busy === 'send' ? 'Sending' : 'Send'}</Text>
        </Pressable>
      </View>

      {choices.length ? (
        <>
          <Text style={styles.sectionTitle}>Choices</Text>
          <View style={styles.choiceList}>
            {choices.map((choice, index) => {
              const value = choiceText(choice);
              return (
                <Pressable
                  key={`${choice.id || index}-${value}`}
                  disabled={disabledControls}
                  style={[styles.choiceButton, disabledControls && styles.disabled]}
                  onPress={() => run(`choice-${index}`, () => onChoice(value))}
                >
                  <Text style={styles.choiceText}>{value}</Text>
                </Pressable>
              );
            })}
          </View>
        </>
      ) : null}

      <View style={styles.storyHeader}>
        <Text style={styles.sectionTitle}>Latest Story</Text>
        <Text style={styles.meta}>{speechItems.length} voice chunks</Text>
      </View>
      <View style={styles.segmentList}>
        {segments.length ? segments.map((segment, index) => (
          <View key={`${segment.segment_id || index}-${segmentTitle(segment)}`} style={styles.segment}>
            <Text style={styles.segmentSpeaker}>{segmentTitle(segment)}</Text>
            <Text style={styles.segmentText}>{clean(segment.text, '')}</Text>
          </View>
        )) : (
          <Text style={styles.emptyText}>{clean(mprc?.latest_reply, available ? 'No story reply yet.' : 'Connect to view story mode.')}</Text>
        )}
      </View>

      {clean(mprc?.visual?.latest_prompt) ? (
        <View style={styles.visualBox}>
          <Text style={styles.label}>Visual Reply Beat</Text>
          <Text style={styles.value}>{clean(mprc?.visual?.latest_prompt)}</Text>
        </View>
      ) : null}

      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    backgroundColor: colors.panel,
    borderTopColor: colors.border,
    borderTopWidth: 1,
    gap: spacing.sm,
    padding: spacing.md,
  },
  header: {
    alignItems: 'flex-start',
    flexDirection: 'row',
    gap: spacing.sm,
    justifyContent: 'space-between',
  },
  headerText: {
    flex: 1,
    minWidth: 0,
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
  status: {
    borderRadius: 6,
    borderWidth: 1,
    fontSize: 12,
    fontWeight: '700',
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  statusOk: {
    borderColor: colors.ok,
    color: colors.ok,
  },
  statusMuted: {
    borderColor: colors.border,
    color: colors.muted,
    maxWidth: '45%',
  },
  actions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  secondaryButton: {
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  activeButton: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.accent,
  },
  buttonText: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '700',
  },
  sceneGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  sceneCell: {
    backgroundColor: colors.panelAlt,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    flexGrow: 1,
    minWidth: 130,
    padding: spacing.sm,
  },
  sceneCellWide: {
    backgroundColor: colors.panelAlt,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    flexBasis: '100%',
    padding: spacing.sm,
  },
  label: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: '700',
    marginBottom: 2,
    textTransform: 'uppercase',
  },
  value: {
    color: colors.text,
    fontSize: 12,
  },
  sectionTitle: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '800',
  },
  personaRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  chip: {
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    minWidth: 118,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  chipSelected: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.accent,
  },
  chipCurrent: {
    borderColor: colors.ok,
  },
  chipText: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '700',
  },
  chipMeta: {
    color: colors.muted,
    fontSize: 10,
  },
  inputBlock: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  input: {
    backgroundColor: colors.panelAlt,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    color: colors.text,
    flex: 1,
    minHeight: 72,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    textAlignVertical: 'top',
  },
  sendButton: {
    alignItems: 'center',
    alignSelf: 'stretch',
    backgroundColor: colors.accentSoft,
    borderRadius: 6,
    justifyContent: 'center',
    minWidth: 72,
    paddingHorizontal: spacing.md,
  },
  choiceList: {
    gap: spacing.sm,
  },
  choiceButton: {
    backgroundColor: colors.panelAlt,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    padding: spacing.sm,
  },
  choiceText: {
    color: colors.text,
    fontSize: 12,
  },
  storyHeader: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  segmentList: {
    gap: spacing.sm,
  },
  segment: {
    borderColor: colors.border,
    borderLeftColor: colors.accent,
    borderLeftWidth: 3,
    borderRadius: 6,
    borderWidth: 1,
    padding: spacing.sm,
  },
  segmentSpeaker: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '800',
    marginBottom: 2,
  },
  segmentText: {
    color: colors.text,
    fontSize: 12,
    lineHeight: 17,
  },
  emptyText: {
    color: colors.muted,
    fontSize: 12,
  },
  visualBox: {
    backgroundColor: colors.panelAlt,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    padding: spacing.sm,
  },
  memoryBox: {
    backgroundColor: colors.panelAlt,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    gap: spacing.sm,
    padding: spacing.sm,
  },
  memoryGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  memoryCell: {
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    flexGrow: 1,
    minWidth: 92,
    padding: spacing.sm,
  },
  memoryNumber: {
    color: colors.text,
    fontSize: 18,
    fontWeight: '800',
  },
  castBox: {
    backgroundColor: colors.panelAlt,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    gap: spacing.sm,
    padding: spacing.sm,
  },
  castOk: {
    color: colors.ok,
  },
  castWarning: {
    color: colors.warning,
  },
  warningText: {
    color: colors.warning,
    fontSize: 12,
  },
  disabled: {
    opacity: 0.35,
  },
  error: {
    color: colors.danger,
    fontSize: 12,
  },
});
