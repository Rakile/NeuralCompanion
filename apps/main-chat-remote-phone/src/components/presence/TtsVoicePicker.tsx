import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { RemoteRequestError, type RemoteClient } from '../../api/client';
import type { TtsProviderState } from '../../api/types';
import { remoteActionError } from '../../api/envelope';
import { useThemedStyles } from '../../styles/ThemeContext';
import { radii, spacing, type ThemeColors } from '../../styles/theme';
import { VoicePicker } from './VoicePicker';

type Props = {
  client: RemoteClient;
  enabled: boolean;
  storyActive?: boolean;
  onSelected: () => Promise<unknown> | unknown;
  onClose: () => void;
  onBusyChange: (busy: boolean) => void;
};

export function TtsVoicePicker({client, enabled, storyActive = false, onSelected, onClose, onBusyChange}: Props) {
  const styles = useThemedStyles(createStyles, 'TtsVoicePicker');
  const [catalog, setCatalog] = React.useState<TtsProviderState | null>(null);
  const [draft, setDraft] = React.useState('');
  const [checking, setChecking] = React.useState(true);
  const [legacy, setLegacy] = React.useState(false);
  const [loadError, setLoadError] = React.useState('');
  const [actionError, setActionError] = React.useState('');
  const [revision, setRevision] = React.useState(0);
  const [posting, setPosting] = React.useState(false);
  const [target, setTarget] = React.useState('');
  const [voiceBusy, setVoiceBusy] = React.useState(false);
  const generation = React.useRef(0);
  const identity = React.useRef(client.identityKey);
  const applying = React.useRef(false);
  const targetRef = React.useRef('');
  const voiceBusyRef = React.useRef(false);
  const draftTouched = React.useRef(false);
  identity.current = client.identityKey;
  const selectedCallback = React.useRef(onSelected);
  const busyCallback = React.useRef(onBusyChange);
  selectedCallback.current = onSelected;
  busyCallback.current = onBusyChange;

  React.useEffect(() => {
    onBusyChange(posting || Boolean(target) || voiceBusy);
  }, [onBusyChange, posting, target, voiceBusy]);

  React.useEffect(() => {
    applying.current = false;
    targetRef.current = '';
    draftTouched.current = false;
    voiceBusyRef.current = false;
    setPosting(false);
    setTarget('');
    setVoiceBusy(false);
    setCatalog(null);
    setDraft('');
    setActionError('');
  }, [client.identityKey, enabled]);

  React.useEffect(() => {
    const currentGeneration = ++generation.current;
    const currentIdentity = client.identityKey;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const current = () => currentGeneration === generation.current && currentIdentity === identity.current;
    setChecking(true);
    setLoadError('');
    setLegacy(false);
    const load = async () => {
      if (!current()) return;
      try {
        const next = await client.ttsProviders();
        if (!current()) return;
        setCatalog(next);
        setChecking(false);
        setDraft(previous => draftTouched.current && previous && next.providers.some(provider => provider.id === previous && provider.available)
          ? previous : next.selected_provider_id);
        const requested = targetRef.current;
        if (requested && !next.loading) {
          targetRef.current = '';
          draftTouched.current = false;
          setTarget('');
          if (next.available && next.selected_provider_id === requested
            && next.providers.some(provider => provider.id === requested && provider.available)) {
            void Promise.resolve().then(() => current() ? selectedCallback.current() : undefined).catch(() => undefined);
          } else {
            setDraft(next.selected_provider_id);
            setActionError(next.message || 'The TTS provider was not activated. The previous provider remains selected.');
          }
        }
        // Keep busy/current-provider state fresh even when a story starts a reply
        // while this sheet is already open. Only one request/timer runs at a time.
        timer = setTimeout(load, 1200);
      } catch (exc) {
        if (!current()) return;
        setChecking(false);
        targetRef.current = '';
        setTarget('');
        if (exc instanceof RemoteRequestError && exc.status === 404) {
          setLegacy(true);
          setCatalog(null);
        } else {
          setLoadError(exc instanceof Error ? exc.message : 'TTS providers could not be loaded.');
        }
      }
    };
    if (enabled) void load();
    return () => {
      generation.current += 1;
      if (timer) clearTimeout(timer);
    };
  }, [client, client.identityKey, enabled, revision]);

  React.useEffect(() => () => {
    applying.current = false;
    targetRef.current = '';
    busyCallback.current(false);
  }, []);

  const onVoiceBusyChange = React.useCallback((value: boolean) => {
    voiceBusyRef.current = value;
    setVoiceBusy(value);
  }, []);

  const active = catalog?.providers.find(provider => provider.id === catalog.selected_provider_id);
  const choice = catalog?.providers.find(provider => provider.id === draft);
  const legacyVoiceControls = legacy || Boolean(catalog && !catalog.available && !catalog.providers.length
    && !catalog.loading && !catalog.busy && !checking && !loadError && !posting && !target);
  const pending = Boolean(choice && choice.id !== catalog?.selected_provider_id);
  const blocked = !enabled || checking || legacy || Boolean(loadError) || !catalog?.available
    || catalog.loading || catalog.busy || posting || Boolean(target) || voiceBusy;

  const apply = async () => {
    if (blocked || !pending || !choice?.available || applying.current || voiceBusyRef.current) return;
    applying.current = true;
    // Invalidate a poll issued before this POST so it cannot restore the old
    // selected provider after initialization has been accepted.
    const currentGeneration = ++generation.current;
    const currentIdentity = client.identityKey;
    const current = () => currentGeneration === generation.current && currentIdentity === identity.current;
    targetRef.current = choice.id;
    setTarget(choice.id);
    setPosting(true);
    setActionError('');
    try {
      const result = await client.selectTtsProvider(choice.id);
      if (!current()) return;
      const failure = remoteActionError(result, 'TTS provider could not be changed.');
      if (failure) throw new Error(failure);
    } catch (exc) {
      if (!current()) return;
      targetRef.current = '';
      setTarget('');
      setActionError(exc instanceof Error ? exc.message : 'TTS provider could not be changed.');
    } finally {
      if (current()) {
        applying.current = false;
        setPosting(false);
        setRevision(value => value + 1);
      }
    }
  };

  if (!enabled) return <Text style={styles.note}>Connect to the desktop to choose a TTS provider and voice.</Text>;
  const liquid = choice?.id === 'liquidai';
  const canChooseVoice = legacyVoiceControls || Boolean(catalog?.available && active?.story_voices
    && !catalog.loading && !catalog.busy && !posting && !target && !pending && !checking && !loadError);
  return <View style={styles.content}>
    <View style={styles.currentRow}>
      <Text style={styles.note}>Active on NC desktop</Text>
      <Text style={styles.active}>{active?.label || catalog?.selected_provider_id || (legacyVoiceControls ? 'Managed on desktop' : checking ? 'Checking…' : 'Unavailable')}</Text>
    </View>
    {legacyVoiceControls ? <Text style={styles.note}>Update NC desktop to choose a TTS provider here. Existing voice controls are still available.</Text> : <>
      <Text style={styles.heading}>TTS provider</Text>
      {checking ? <Text style={styles.note}>Checking desktop TTS providers…</Text> : null}
      {loadError ? <Text accessibilityRole="alert" style={styles.error}>{loadError}</Text> : null}
      <View accessibilityRole="radiogroup" accessibilityLabel="TTS provider">
        {catalog?.providers.map(provider => <Pressable key={provider.id} accessibilityRole="radio"
          accessibilityLabel={`Select TTS provider ${provider.label}`}
          accessibilityState={{checked: provider.id === draft, disabled: Boolean(blocked || !provider.available)}}
          disabled={Boolean(blocked || !provider.available)}
          onPress={() => {draftTouched.current = provider.id !== catalog.selected_provider_id; setDraft(provider.id); setActionError('');}}
          style={[styles.provider, provider.id === draft && styles.selected, !provider.available && styles.unavailable]}>
          <Text style={styles.marker}>{provider.id === draft ? '◉' : '○'}</Text>
          <View style={styles.providerCopy}>
            <View style={styles.providerTitle}><Text style={styles.name}>{provider.label}</Text>
              <Text style={styles.badge}>{provider.id.startsWith('chatterbox') ? 'Recommended for stories'
                : provider.progressive_audio ? 'Progressive audio' : ''}</Text></View>
            <Text style={styles.note}>{provider.message || (provider.story_voices
              ? 'Supports saved story character voices.' : 'Uses its configured desktop voice.')}</Text>
          </View>
        </Pressable>)}
      </View>
      {storyActive && choice ? <View style={styles.storyNote}>
        <Text style={styles.name}>{choice.story_voices ? 'Saved story voices supported' : 'Story character voices are limited'}</Text>
        <Text style={styles.note}>{choice.story_voices ? 'Each character keeps its saved voice from the story cast.'
          : liquid ? 'LiquidAI cannot use your different saved character voices. Choose Chatterbox for this story.'
            : 'This provider cannot use your saved character voice references. Choose a provider that supports story voices.'}</Text>
      </View> : liquid ? <Text style={styles.note}>For stories with different saved character voices, choose Chatterbox.</Text> : null}
      {catalog?.message ? <Text style={styles.note}>{catalog.message}</Text> : null}
      {actionError ? <Text accessibilityRole="alert" style={styles.error}>{actionError}</Text> : null}
      {catalog?.busy && !target ? <Text style={styles.note}>Finish the current reply before changing TTS provider or voice.</Text> : null}
      <Pressable accessibilityRole="button" accessibilityLabel="Apply TTS provider"
        accessibilityState={{disabled: Boolean(blocked || !pending || !choice?.available)}}
        disabled={Boolean(blocked || !pending || !choice?.available)} onPress={() => void apply()}
        style={[styles.apply, (blocked || !pending || !choice?.available) && styles.unavailable]}>
        <Text style={styles.applyText}>{target || posting ? 'Switching TTS provider…' : checking ? 'Checking providers…'
          : loadError || !catalog?.available ? 'TTS controls unavailable' : catalog?.loading ? 'TTS provider is loading…'
          : pending ? `Use ${choice?.label}` : `${active?.label || 'TTS provider'} is active`}</Text>
      </Pressable>
      <Text style={styles.note}>Changes the desktop TTS for new replies. Saved persona and cast voices stay intact.</Text>
      {loadError || !catalog?.available ? <Pressable accessibilityRole="button" accessibilityLabel="Refresh TTS providers"
        disabled={posting || Boolean(target)} onPress={() => {++generation.current; setRevision(value => value + 1);}} style={styles.refresh}>
        <Text style={styles.active}>Refresh providers</Text>
      </Pressable> : null}
    </>}
    <View style={styles.voices}>
      <Text style={styles.heading}>Companion voice</Text>
      {canChooseVoice ? <VoicePicker key={`${client.identityKey}:${catalog?.selected_provider_id || 'legacy'}`}
        client={client} enabled={enabled} onBusyChange={onVoiceBusyChange} onClose={onClose} onSelected={onSelected} />
        : <Text style={styles.note}>{pending || target || catalog?.loading
          ? 'Switch the provider first, then choose a voice once it is ready.'
          : catalog?.busy ? 'Voice changes are unavailable while a reply is active.'
            : active && !active.story_voices ? 'Uses this provider’s configured desktop voice. Voice selection for this provider is managed on desktop.'
              : 'Voice controls will be available when the desktop provider is ready.'}</Text>}
    </View>
  </View>;
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  content: {gap: spacing.sm},
  currentRow: {flexDirection:'row', justifyContent:'space-between', alignItems:'center', gap:spacing.sm, marginBottom:spacing.sm},
  active: {color:colors.accent, fontSize:13, fontWeight:'600', flexShrink:1},
  heading: {color:colors.text, fontSize:15, fontWeight:'700'},
  note: {color:colors.muted, fontSize:12, lineHeight:18},
  provider: {borderColor:colors.border, borderWidth:1, borderRadius:radii.lg, backgroundColor:colors.panelAlt,
    flexDirection:'row', alignItems:'flex-start', gap:spacing.sm, padding:spacing.md, minHeight:64, marginBottom:spacing.sm},
  providerCopy: {flex:1, minWidth:0, gap:spacing.xs},
  providerTitle: {flexDirection:'row', justifyContent:'space-between', alignItems:'center', flexWrap:'wrap', gap:spacing.xs},
  name: {color:colors.text, fontSize:14, fontWeight:'600'},
  badge: {color:colors.accent, fontSize:11},
  marker: {color:colors.accent, fontSize:20},
  selected: {borderColor:colors.accentMuted, backgroundColor:colors.accentSoft},
  storyNote: {borderLeftWidth:3, borderColor:colors.accent, backgroundColor:colors.accentSoft,
    borderRadius:radii.md, padding:spacing.md, gap:spacing.xs},
  apply: {minHeight:46, borderRadius:radii.md, backgroundColor:colors.accent, alignItems:'center', justifyContent:'center', padding:spacing.sm},
  applyText: {color:colors.background, fontSize:14, fontWeight:'700'},
  unavailable: {opacity:0.55},
  error: {color:colors.danger, fontSize:13, lineHeight:18},
  refresh: {minHeight:44, alignItems:'center', justifyContent:'center'},
  voices: {borderTopColor:colors.border, borderTopWidth:1, paddingTop:spacing.md, marginTop:spacing.sm, gap:spacing.sm},
});
