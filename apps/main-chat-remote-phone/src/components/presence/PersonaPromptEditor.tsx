import React from 'react';
import { Alert, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import type { RemoteClient } from '../../api/client';
import type { PersonaPrompts, PersonaTechnicalRules, QuickPersonaChoice } from '../../api/types';
import { PersonaRulesEditor } from './PersonaRulesEditor';
import { usePresentationStyle, useThemedStyles, useThemeColors } from '../../styles/ThemeContext';
import { controlGlyphTypography, type ThemeColors } from '../../styles/theme';

export function PersonaPromptEditor({ client, persona, enabled, onClose, onSaved, closeRef }: {
  client: RemoteClient; persona: QuickPersonaChoice; enabled: boolean;
  onClose: () => void; onSaved: () => void; closeRef: React.MutableRefObject<(() => void) | null>;
}) {
  const styles = useThemedStyles(createStyles);
  const colors = useThemeColors();
  const editorial=usePresentationStyle()==='editorial';
  const [advanced,setAdvanced]=React.useState(false);
  const [record, setRecord] = React.useState<PersonaPrompts | null>(null);
  const [system, setSystem] = React.useState('');
  const [technical, setTechnical] = React.useState('');
  const [rules, setRules] = React.useState<PersonaTechnicalRules | undefined>();
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');
  const alive = React.useRef(true);
  const saving = React.useRef(false);
  const generation = React.useRef(0);
  React.useEffect(() => {
    alive.current = true;
    generation.current++;
    setRecord(null); setRules(undefined); setSystem(''); setTechnical(''); setError('');
    let cancelled = false;
    client.personaPrompts(persona.id).then(value => {
      if (cancelled) return;
      setRecord(value); setSystem(value.system_prompt); setTechnical(value.technical_prompt);
      setRules(value.technical_rules);
    }).catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : 'Could not load prompts.'); });
    return () => { cancelled = true; alive.current = false; };
  }, [client, persona.id]);
  const dirty = !!record && (system !== record.system_prompt || technical !== record.technical_prompt
    || JSON.stringify(rules) !== JSON.stringify(record.technical_rules));
  const close = React.useCallback(() => {
    if (saving.current) return;
    if (!dirty) { onClose(); return; }
    Alert.alert('Discard changes?', 'Your saved persona will stay unchanged.', [
      { text: 'Keep editing', style: 'cancel' }, { text: 'Discard', style: 'destructive', onPress: onClose },
    ]);
  }, [dirty, onClose]);
  React.useEffect(() => { closeRef.current = close; return () => { closeRef.current = null; }; }, [close, closeRef]);
  const save = async () => {
    if (!record || record.id !== persona.id || !enabled || saving.current) return;
    saving.current = true; setBusy(true); setError('');
    const mine = generation.current;
    try {
      await client.personaPrompts(persona.id, { revision: record.revision, system_prompt: system, technical_prompt: technical,
        ...(rules && record.rule_catalog ? { technical_rules: rules } : {}) });
      if (alive.current && mine === generation.current) onSaved();
    } catch (e) { if (alive.current && mine === generation.current) setError(e instanceof Error ? e.message : 'Could not save prompts.'); }
    finally { saving.current = false; if (alive.current) setBusy(false); }
  };
  return <KeyboardAvoidingView style={styles.root} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
    <Text style={styles.title}>{persona.name}</Text>
    <Text style={styles.help}>Persona prompts · changes apply to future replies.</Text>
    <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.content}>
      {!record && !error ? <Text style={styles.help}>Loading prompts…</Text> : null}
      {record ? <>
        <Text style={styles.label}>Master / system prompt</Text>
        <TextInput accessibilityLabel="Master / system prompt" multiline textAlignVertical="top" value={system}
          onChangeText={setSystem} editable={!busy && enabled} maxLength={100000} style={styles.input}
          placeholderTextColor={colors.muted} />
        {rules && record.rule_catalog ? <PersonaRulesEditor key={record.id} rules={rules} catalog={record.rule_catalog}
          disabled={busy || !enabled} onChange={setRules} />
          : <Text style={styles.help}>Separate provider rules need an updated desktop. Your combined rules remain editable below.</Text>}
        {editorial?<Pressable accessibilityRole="button" accessibilityState={{expanded:advanced}} onPress={()=>setAdvanced(value=>!value)}
          style={styles.button}><Text style={styles.buttonText}>Technical prompt <Text style={controlGlyphTypography}>{advanced?'−':'+'}</Text></Text></Pressable>:null}
        {!editorial||advanced?<>
        <Text style={styles.label}>Technical prompt</Text>
        <Text style={styles.help}>Preserved combined emotion and voice rules. The switch above controls their priority when separate provider rules are available.</Text>
        <TextInput accessibilityLabel="Technical prompt" multiline textAlignVertical="top" value={technical}
          onChangeText={setTechnical} editable={!busy && enabled} maxLength={100000} style={styles.input}
          placeholderTextColor={colors.muted} />
        </>:null}
        <Pressable accessibilityRole="button" disabled={busy || !enabled} style={styles.button} onPress={() => {
          Alert.alert('Restore original prompts?', 'Loads this persona’s originals into the editor. Tap Save to apply.', [
            { text: 'Cancel', style: 'cancel' }, { text: 'Restore', onPress: () => {
              setSystem(record.defaults.system_prompt); setTechnical(record.defaults.technical_prompt);
            } },
          ]);
        }}><Text style={styles.buttonText}>Revert to default</Text></Pressable>
      </> : null}
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      {!enabled ? <Text style={styles.error}>Reconnect to save your changes.</Text> : null}
    </ScrollView>
    <View style={styles.actions}>
      <Pressable accessibilityRole="button" disabled={busy} onPress={close} style={styles.button}><Text style={styles.buttonText}>Cancel</Text></Pressable>
      <Pressable accessibilityRole="button" disabled={!record || busy || !enabled} onPress={() => void save()}
        style={[styles.button, styles.save, (!record || busy || !enabled) && styles.disabled]}>
        <Text style={styles.buttonText}>{busy ? 'Saving…' : 'Save'}</Text>
      </Pressable>
    </View>
  </KeyboardAvoidingView>;
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  root: { flex: 1, paddingTop: 12 },
  title: { color: colors.text, fontSize: 24, fontWeight: '800' },
  help: { color: colors.muted, fontSize: 13, marginVertical: 8 },
  content: { paddingVertical: 12, gap: 8 },
  label: { color: colors.text, fontSize: 16, fontWeight: '700' },
  input: { color: colors.text, backgroundColor: colors.panel, borderColor: colors.border, borderWidth: 1,
    borderRadius: 14, padding: 14, minHeight: 160, fontSize: 16, lineHeight: 23 },
  actions: { flexDirection: 'row', gap: 12, paddingVertical: 12 },
  button: { minHeight: 48, padding: 14, borderRadius: 14, backgroundColor: colors.panelAlt, justifyContent: 'center', alignItems: 'center' },
  buttonText: { color: colors.text, fontSize: 16, fontWeight: '700' },
  save: { flex: 1, backgroundColor: colors.accentSoft, borderColor: colors.accent, borderWidth: 1 },
  disabled: { opacity: 0.45 },
  error: { color: colors.danger, fontSize: 14 },
});
