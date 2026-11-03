import { usePresentationStyle, useThemedStyles, useThemeColors } from '../../styles/ThemeContext';
import type { ThemeColors } from '../../styles/theme';
import React from 'react';
import { Image, Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { RemoteClient } from '../../api/client';
import type { QuickPersonaChoice } from '../../api/types';
import { remoteActionError } from '../../api/envelope';
import { useAuthorizedMediaUrl } from '../../hooks/useAuthorizedMediaUrl';
import { colors, radii, spacing } from '../../styles/theme';
import { KeyboardSafeView } from '../KeyboardSafeView';
import { LlmModelPicker } from './LlmModelPicker';
import { TtsVoicePicker } from './TtsVoicePicker';
import { PersonaPromptEditor } from './PersonaPromptEditor';

type Props = {
  visible: boolean;
  initialTab?: 'persona' | 'model' | 'voice';
  enabled: boolean;
  storyActive?: boolean;
  client: RemoteClient;
  onClose: () => void;
  onSelected: () => Promise<unknown> | unknown;
};

function PersonaAvatar({ client, persona }: { client: RemoteClient; persona: QuickPersonaChoice }) {
  const styles = useThemedStyles(createStyles, 'QuickPersonaSheet');

  const media = useAuthorizedMediaUrl(client, persona.avatar_url_path || '');
  const [failed, setFailed] = React.useState(false);
  React.useEffect(() => setFailed(false), [media.url]);
  if (media.url && !failed) {
    return <Image source={{ uri: media.url }} onError={() => setFailed(true)} style={styles.avatar} />;
  }
  return (
    <View style={[styles.avatar, styles.initials]}>
      <Text style={styles.initialsText}>{persona.initials || 'NC'}</Text>
    </View>
  );
}

export function QuickPersonaSheet({ initialTab = 'persona', visible, enabled, storyActive = false, client, onClose, onSelected }: Props) {
  const styles = useThemedStyles(createStyles, 'QuickPersonaSheet');

  const editorial=usePresentationStyle()==='editorial';
  const [search,setSearch]=React.useState('');
  const SheetContainer=editorial?KeyboardSafeView:View;
  const insets = useSafeAreaInsets();
  const clientIdentityRef = React.useRef(client.identityKey);
  const requestGenerationRef = React.useRef(0);
  const [items, setItems] = React.useState<QuickPersonaChoice[]>([]);
  const [editing, setEditing] = React.useState<QuickPersonaChoice | null>(null);
  const editorClose = React.useRef<(() => void) | null>(null);
  const closeSheet = () => editing ? editorClose.current?.() : onClose();
  React.useEffect(() => { setEditing(null); }, [visible, client.identityKey]);
  const [loading, setLoading] = React.useState(false);
  const [selectingSlot, setSelectingSlot] = React.useState<number | null>(null);
  const [error, setError] = React.useState('');
  const [tab, setTab] = React.useState<'persona' | 'model' | 'voice'>('persona');
  React.useEffect(() => { if (visible) setTab(initialTab); }, [visible, initialTab]);
  const [modelSelectionPending, setModelSelectionPending] = React.useState(false);
  const [voiceSelectionPending, setVoiceSelectionPending] = React.useState(false);
  const selectionPending = selectingSlot !== null || modelSelectionPending || voiceSelectionPending;
  const selectingRef = React.useRef(false);
  clientIdentityRef.current = client.identityKey;

  const load = React.useCallback(async () => {
    const requestGeneration = requestGenerationRef.current + 1;
    const requestIdentity = client.identityKey;
    requestGenerationRef.current = requestGeneration;
    const isCurrentRequest = () => (
      requestGenerationRef.current === requestGeneration
      && clientIdentityRef.current === requestIdentity
    );
    if (!enabled) {
      setItems([]);
      setLoading(false);
      setError('Connect to the desktop to change Quick Persona.');
      return;
    }
    setLoading(true);
    setItems([]);
    setError('');
    try {
      const state = await client.quickPersonas();
      if (!isCurrentRequest()) return;
      setItems(state.items);
    } catch (exc) {
      if (!isCurrentRequest()) return;
      setError(exc instanceof Error ? exc.message : 'Quick Personas could not be loaded.');
    } finally {
      if (isCurrentRequest()) setLoading(false);
    }
  }, [client, client.identityKey, enabled]);

  React.useEffect(() => {
    if (visible && tab === 'persona') void load();
    return () => {
      requestGenerationRef.current += 1;
    };
  }, [load, tab, visible]);

  const select = React.useCallback(async (persona: QuickPersonaChoice) => {
    if (!enabled || loading || selectingRef.current || persona.active) return;
    const generation = requestGenerationRef.current;
    const identity = client.identityKey;
    const isCurrent = () => generation === requestGenerationRef.current && identity === clientIdentityRef.current;
    selectingRef.current = true;
    setSelectingSlot(persona.slot);
    setError('');
    try {
      const result = await client.selectQuickPersona(persona.slot);
      const message = remoteActionError(result, 'Quick Persona was not activated.');
      if (message) throw new Error(message);
      if (!isCurrent()) return;
      await Promise.resolve(onSelected()).catch(() => undefined);
      if (isCurrent()) onClose();
    } catch (exc) {
      if (isCurrent()) setError(exc instanceof Error ? exc.message : 'Quick Persona was not activated.');
    } finally {
      selectingRef.current = false;
      setSelectingSlot(null);
    }
  }, [client, enabled, loading, onClose, onSelected]);

  return (
    <Modal animationType="slide" onRequestClose={closeSheet} transparent visible={visible}>
      <SheetContainer style={styles.modal}>
        <Pressable accessibilityLabel="Close Quick Persona selector" onPress={closeSheet} style={StyleSheet.absoluteFill} />
        <View style={[styles.sheet, editing && { height: '94%', maxHeight: '94%' }, { paddingBottom: Math.max(spacing.md, insets.bottom) }]}>
          {editing ? <PersonaPromptEditor key={`${client.identityKey}:${editing.id}`} client={client} persona={editing}
            enabled={enabled} closeRef={editorClose} onClose={() => setEditing(null)} onSaved={() => {
              setEditing(null); void load(); void Promise.resolve(onSelected()).catch(() => undefined);
            }} /> : <>
          <View style={styles.handle} />
          <View style={styles.headingRow}>
            <View style={styles.headingCopy}>
              {!editorial?<Text style={styles.eyebrow}>COMPANION CONTROLS</Text>:null}
              <Text style={styles.title}>{tab === 'persona' ? 'Choose your companion' : tab === 'voice' ? 'Voice & TTS' : 'Choose a reply model'}</Text>
            </View>
            <Pressable accessibilityLabel="Close Quick Persona selector" accessibilityRole="button" onPress={onClose} style={styles.close}>
              <Text style={styles.closeText}>×</Text>
            </Pressable>
          </View>
          {!editorial?<Text style={styles.help}>Tap to select. Long-press a persona to edit its prompts.</Text>:null}
          {editorial&&tab==='persona'?<TextInput accessibilityLabel="Search personas" value={search} onChangeText={setSearch}
            placeholder="Search personas" placeholderTextColor={styles.personaState.color}
            style={[styles.persona,{color:styles.personaName.color,marginTop:16,paddingHorizontal:12}]}/>:null}
          <View accessibilityRole="tablist" style={styles.tabs}>
            {(['persona', 'model', 'voice'] as const).map((value) => (
              <Pressable key={value} accessibilityRole="tab" accessibilityState={{ selected: tab === value, disabled: selectionPending }} disabled={selectionPending} onPress={() => { if (!selectionPending) setTab(value); }} style={[styles.tab, tab === value && styles.personaActive]}>
                <Text style={styles.personaName}>{value === 'persona' ? 'Quick Persona' : value === 'voice' ? 'Voice & TTS' : 'LLM Model'}</Text>
              </Pressable>
            ))}
          </View>
          {tab === 'persona' && loading ? <Text style={styles.status}>Loading saved personas…</Text> : null}
          {tab === 'persona' && error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
          {tab === 'persona' && !loading && !error && !items.length ? (
            <Text style={styles.status}>No saved Quick Personas are available on the desktop.</Text>
          ) : null}
          <ScrollView keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" contentContainerStyle={styles.list} style={styles.scroll}>
            {tab === 'voice' ? <TtsVoicePicker key={client.identityKey} client={client} enabled={enabled && visible} storyActive={storyActive} onBusyChange={setVoiceSelectionPending} onClose={onClose} onSelected={onSelected} /> : null}
            {tab === 'model' ? <LlmModelPicker key={client.identityKey} client={client} enabled={enabled && visible} onBusyChange={setModelSelectionPending} onClose={onClose} onSelected={onSelected} /> : null}
            {tab === 'persona' ? items.filter(persona=>!editorial||persona.name.toLowerCase().includes(search.toLowerCase())).map((persona) => {
              const selecting = selectingSlot === persona.slot;
              return (
                <Pressable
                  accessibilityLabel={`${persona.name}${persona.active ? ', active' : ''}`}
                  accessibilityRole="button"
                  accessibilityState={{ disabled: loading || !enabled || selectingSlot !== null, selected: persona.active }}
                  disabled={loading || !enabled || selectingSlot !== null}
                  key={`${persona.slot}:${persona.id}`}
                  onPress={() => void select(persona)}
                  onLongPress={() => setEditing(persona)}
                  delayLongPress={450}
                  accessibilityHint="Long-press to edit master and technical prompts"
                  style={[styles.persona, persona.active && styles.personaActive]}
                >
                  <PersonaAvatar client={client} persona={persona} />
                  <View style={styles.personaCopy}>
                    <Text numberOfLines={1} style={styles.personaName}>{persona.name}</Text>
                    <Text style={styles.personaState}>{selecting ? 'Switching…' : persona.active ? 'Active now' : `Slot ${persona.slot + 1}`}</Text>
                  </View>
                  <Text style={[styles.check, persona.active && styles.checkActive]}>{persona.active ? '✓' : '›'}</Text>
                </Pressable>
              );
            }) : null}
          </ScrollView>
          {editorial&&tab==='persona'&&items.some(persona=>persona.active)?<Pressable accessibilityRole="button"
            disabled={selectionPending} onPress={()=>setEditing(items.find(persona=>persona.active)||null)} style={styles.closeEditor}>
            <Text style={styles.checkActive}>Edit current persona prompts</Text></Pressable>:null}
          </>}
        </View>
      </SheetContainer>
    </Modal>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  closeEditor: {minHeight:48,justifyContent:'center'},
  modal: { backgroundColor: 'rgba(0,0,0,0.62)', flex: 1, justifyContent: 'flex-end' },
  sheet: { backgroundColor: colors.backgroundElevated, borderColor: colors.border, borderTopLeftRadius: 26, borderTopRightRadius: 26, borderWidth: 1, maxHeight: '76%', paddingHorizontal: spacing.lg, paddingTop: spacing.sm },
  handle: { alignSelf: 'center', backgroundColor: colors.border, borderRadius: 999, height: 4, marginBottom: spacing.md, width: 44 },
  headingRow: { alignItems: 'center', flexDirection: 'row', gap: spacing.md },
  headingCopy: { flex: 1 },
  eyebrow: { color: colors.accent, fontSize: 10, fontWeight: '900', letterSpacing: 1.5 },
  title: { color: colors.text, fontSize: 22, fontWeight: '900', marginTop: 2 },
  help: { color: colors.muted, fontSize: 12, marginTop: spacing.xs },
  tabs: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md },
  tab: { alignItems: 'center', borderColor: colors.borderSoft, borderRadius: radii.md, borderWidth: 1, flex: 1, justifyContent: 'center', minHeight: 44 },
  close: { alignItems: 'center', borderColor: colors.border, borderRadius: 22, borderWidth: 1, height: 44, justifyContent: 'center', width: 44 },
  closeText: { color: colors.text, fontSize: 24, lineHeight: 26 },
  scroll: { marginTop: spacing.md },
  list: { gap: spacing.sm, paddingBottom: spacing.sm },
  persona: { alignItems: 'center', borderColor: colors.borderSoft, borderRadius: radii.lg, borderWidth: 1, flexDirection: 'row', gap: spacing.md, minHeight: 68, padding: spacing.sm },
  personaActive: { backgroundColor: colors.accentSoft, borderColor: colors.accentMuted },
  avatar: { borderColor: colors.border, borderRadius: 24, borderWidth: 1, height: 48, width: 48 },
  initials: { alignItems: 'center', backgroundColor: colors.panelAlt, justifyContent: 'center' },
  initialsText: { color: colors.text, fontSize: 14, fontWeight: '900' },
  personaCopy: { flex: 1, minWidth: 0 },
  personaName: { color: colors.text, fontSize: 15, fontWeight: '800' },
  personaState: { color: colors.muted, fontSize: 11, marginTop: 3 },
  check: { color: colors.muted, fontSize: 24, paddingHorizontal: spacing.xs },
  checkActive: { color: colors.accent },
  status: { color: colors.textSecondary, fontSize: 13, marginTop: spacing.lg },
  error: { color: colors.danger, fontSize: 13, lineHeight: 18, marginTop: spacing.md },
});
