import React from 'react';
import { ActivityIndicator, Keyboard, Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import type { RemoteClient } from '../../api/client';
import type { LlmModelState, StoryPace, StoryPlan, StoryPlanDraft } from '../../api/types';
import { useThemeColors, useThemedStyles, usePresentationStyle } from '../../styles/ThemeContext';
import { requestCommandDraft } from '../../utils/commandDraft';
import { KeyboardSafeView } from '../KeyboardSafeView';

export type StoryRefineSettings = {text:string; beatCount:number; pace:StoryPace; provider:string; model:string;
  temperature:string; followPrompt:'closely'|'balanced'|'flexible'; beatDetail:'short'|'standard'|'detailed';
  useCurrentPlanReference:boolean};

type Props = {
  client: RemoteClient;
  initialText: string;
  isCurrent: () => boolean;
  onClose: (text: string) => void;
  onReady: (plan: StoryPlanDraft, settings: StoryRefineSettings) => void;
  extension?: StoryPlan;
  initialSettings?: StoryRefineSettings;
  referencePlan?: StoryPlanDraft;
};

/** Mounted only while setup is open. Closing or changing conversation retires its job. */
export function StoryRefinePanel({client, initialText, isCurrent, onClose, onReady, extension, initialSettings, referencePlan}: Props) {
  const colors = useThemeColors();
  const styles = useThemedStyles(createStyles, 'StoryRefinePanel');
  const editorial = usePresentationStyle() === 'editorial';
  const [text, setText] = React.useState(initialSettings?.text ?? initialText);
  const [count, setCount] = React.useState(String(initialSettings?.beatCount ?? 8));
  const [pace, setPace] = React.useState<StoryPace>(initialSettings?.pace ?? extension?.pace ?? 'medium');
  const [temperature, setTemperature] = React.useState(initialSettings?.temperature ?? '0.7');
  const [followPrompt, setFollowPrompt] = React.useState<StoryRefineSettings['followPrompt']>(initialSettings?.followPrompt ?? 'balanced');
  const [beatDetail, setBeatDetail] = React.useState<StoryRefineSettings['beatDetail']>(initialSettings?.beatDetail ?? 'standard');
  const [useReference, setUseReference] = React.useState(initialSettings?.useCurrentPlanReference ?? true);
  const [catalog, setCatalog] = React.useState<LlmModelState | null>(null);
  const [selection, setSelection] = React.useState<{provider: string; model: string} | null>(
    initialSettings ? {provider:initialSettings.provider,model:initialSettings.model} : null);
  const [expanded, setExpanded] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  const [modelError, setModelError] = React.useState('');
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const alive = React.useRef(true);
  const job = React.useRef<AbortController | null>(null);
  const loadGeneration = React.useRef(0);
  const load = async () => {
    const generation = ++loadGeneration.current;
    setLoading(true); setModelError('');
    try {
      const models = await client.llmModels();
      if (!alive.current || generation !== loadGeneration.current) return;
      setCatalog(models);
      // Resolve a concrete current-model choice, without switching the main chat model.
      setSelection(current => current ?? (models.selected_provider_id && models.selected_model_id
        ? {provider: models.selected_provider_id, model: models.selected_model_id} : null));
    } catch {
      if (alive.current && generation === loadGeneration.current)
        setModelError('Could not load configured models. Reconnect and retry.');
    } finally {
      if (alive.current && generation === loadGeneration.current) setLoading(false);
    }
  };
  React.useEffect(() => {
    alive.current = true;
    void load();
    return () => { alive.current = false; ++loadGeneration.current; job.current?.abort(); };
  }, [client]);
  const choices = (catalog?.providers ?? []).filter(provider => provider.available)
    .flatMap(provider => provider.models.map(model => ({provider: provider.id, model: model.id,
      label: `${provider.label} · ${model.label}`})));
  const selected = choices.find(choice => choice.provider === selection?.provider && choice.model === selection?.model);
  const beatCount = Number(count);
  const minimum = extension ? 5 : 2, maximum = extension ? 20 : 30;
  const validCount = /^\d+$/.test(count) && Number.isInteger(beatCount) && beatCount >= minimum && beatCount <= maximum;
  const validTemperature = temperature === '' || (/^\d+(?:\.\d{1,2})?$/.test(temperature) && Number(temperature) <= 2);
  const close = () => {
    job.current?.abort(); alive.current = false;
    onClose(text);
  };
  const refine = async () => {
    if (job.current || !validCount || !validTemperature || !selected || (!extension && !text.trim()) || text.length > 8000) return;
    const controller = new AbortController(); job.current = controller;
    setBusy(true); setError(''); Keyboard.dismiss();
    try {
      const result = await requestCommandDraft(client, extension ? 'story_extend' : 'story_refine',
        text.trim() || 'Continue naturally from the played story and its unresolved threads.', controller.signal,
        () => alive.current && isCurrent(), {beat_count: beatCount, pace,
          provider_id: selected.provider, model_id: selected.model,
          ...(referencePlan && !extension ? {
            ...(temperature !== '' ? {temperature:Number(temperature)} : {}),
            follow_prompt:followPrompt, beat_detail:beatDetail,
            ...(useReference ? {reference_plan:referencePlan} : {}),
          } : {}),
          ...(extension ? {plan_id:extension.plan_id, revision:extension.revision} : {})});
      if (!alive.current || controller.signal.aborted || !isCurrent()) return;
      if (!('storyPlan' in result) || !result.storyPlan) throw new Error('The model returned no Story Plan. Please retry.');
      onReady(result.storyPlan, {text, beatCount, pace, provider:selected.provider, model:selected.model,
        temperature, followPrompt, beatDetail, useCurrentPlanReference:useReference});
    } catch (failure) {
      if (alive.current && !controller.signal.aborted)
        setError(failure instanceof Error ? failure.message : 'Refinement failed. Your prompt is preserved.');
    } finally {
      if (job.current === controller) job.current = null;
      if (alive.current) setBusy(false);
    }
  };
  const button = (label: string, action: () => void, disabled = busy, active = false, primary = false) => (
    <Pressable accessibilityRole="button" accessibilityLabel={label} accessibilityState={{selected:active, disabled}}
      onPress={action} disabled={disabled} style={[styles.button, active && styles.selected, editorial&&primary&&{backgroundColor:colors.accent,borderColor:colors.accent,borderRadius:5,alignItems:'center'}, disabled && styles.disabled]}>
      <Text style={[styles.buttonText,editorial&&primary&&{color:colors.background,fontWeight:'600'}]}>{label}</Text>
    </Pressable>
  );
  return <Modal visible animationType="slide" onShow={Keyboard.dismiss} onRequestClose={close}>
    <KeyboardSafeView><SafeAreaView style={styles.screen}>
      <View style={styles.header}><Text style={[styles.heading,editorial&&{fontFamily:'serif',fontWeight:'400'}]}>{extension ? 'Extend story' : referencePlan ? 'Re-refine story' : 'Refine story'}</Text>{button('Cancel', close, false)}</View>
      {!editorial ? <View style={styles.header}>{button(extension ? 'Refine extra beats' : referencePlan ? 'Refine again' : 'Refine story', () => void refine(),
        busy || loading || !selected || !validCount || !validTemperature || (!extension && !text.trim()) || text.length > 8000)}</View> : null}
      <ScrollView keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" contentContainerStyle={styles.content}>
        {extension ? <Text style={styles.muted}>{editorial ? 'Continue with played history and existing characters.' : `Continue ${extension.title}. Uses the played conversation, existing plan and characters. Review new beats before adding them.`}</Text> : null}
        <Text style={styles.label}>{extension ? 'Next direction (optional)' : 'Story prompt'}</Text>
        <TextInput accessibilityLabel="Story prompt" multiline value={text} onChangeText={setText} maxLength={8000}
          editable={!busy} style={[styles.input, styles.prompt]} placeholder="Paste your story idea here"
          placeholderTextColor={colors.muted}/>
        {text.length > 8000 ? <Text style={styles.error}>Shorten the prompt to 8000 characters before refining.</Text> : null}
        <Text style={styles.label}>Refinement model</Text>
        {!editorial ? <Text style={styles.muted}>This choice is used to refine your plan. Your chat model stays selected.</Text> : null}
        {button(loading ? 'Loading models…' : selected?.label ?? 'Choose a model', () => setExpanded(!expanded), busy || loading)}
        {expanded && !loading ? <View style={styles.choices}>{choices.map(choice =>
          <View key={`${choice.provider}:${choice.model}`}>
            {button(choice.label, () => {setSelection(choice); setExpanded(false);}, busy,
              choice.provider === selected?.provider && choice.model === selected?.model)}
          </View>)}</View> : null}
        {modelError ? <Text accessibilityRole="alert" style={styles.error}>{modelError}</Text> : null}
        {!loading && !choices.length && !modelError ? <Text style={styles.muted}>No configured models available. Check the desktop provider, then reload.</Text> : null}
        {!editorial || modelError || !choices.length ? button('Reload models', () => void load(), busy || loading) : null}
        <Text style={styles.label}>Number of {extension ? 'extra ' : ''}beats ({minimum}–{maximum})</Text>
        <TextInput accessibilityLabel="Number of beats" value={count} onChangeText={setCount} keyboardType="number-pad"
          maxLength={2} editable={!busy} style={styles.input}/>
        {!validCount ? <Text style={styles.error}>Enter a whole number from {minimum} to {maximum}.</Text> : null}
        <Text style={styles.label}>Story pace</Text>
        <View style={styles.row}>{(['slow','medium','fast'] as const).map(value => <View key={value}>
          {button(value.charAt(0).toUpperCase() + value.slice(1), () => setPace(value), busy, pace === value)}
        </View>)}</View>
        <Text style={styles.muted}>Slow: about 5–8 replies per beat. Medium: 3–4. Fast: 1–2.</Text>
        {referencePlan && !extension ? <>
          <Text style={styles.label}>Temperature (0–2)</Text>
          <TextInput accessibilityLabel="Temperature" value={temperature} onChangeText={setTemperature}
            keyboardType="decimal-pad" editable={!busy} style={styles.input} />
          <Text style={styles.muted}>Clear this field to use the model default if your provider does not support temperature.</Text>
          {!validTemperature ? <Text style={styles.error}>Enter a number from 0 to 2, or leave it blank.</Text> : null}
          <Text style={styles.label}>Follow my prompt</Text>
          <View style={styles.row}>{(['closely','balanced','flexible'] as const).map(value => <View key={value}>
            {button(value.charAt(0).toUpperCase() + value.slice(1), () => setFollowPrompt(value), busy, followPrompt === value)}
          </View>)}</View>
          <Text style={styles.label}>Beat detail</Text>
          <View style={styles.row}>{(['short','standard','detailed'] as const).map(value => <View key={value}>
            {button(value.charAt(0).toUpperCase() + value.slice(1), () => setBeatDetail(value), busy, beatDetail === value)}
          </View>)}</View>
          {button(`Use current plan as reference: ${useReference ? 'On' : 'Off'}`, () => setUseReference(!useReference), busy, useReference)}
          <Text style={styles.muted}>The current plan stays unchanged until you review the new draft and choose Use new draft.</Text>
        </> : null}
        {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
        {busy ? <View style={styles.row}><ActivityIndicator color={colors.accent}/>
          <Text accessibilityLiveRegion="polite" style={styles.label}>Refining your story…</Text></View> : null}
        <Text style={styles.muted}>{extension ? 'Earlier beats and history stay unchanged. Add beats saves paused; Add & continue uses your enabled Continuous Mode.' : 'Review the result, then choose Send to Chat or Create Story Plan. Creating a plan saves it; Start story begins it.'}</Text>
      </ScrollView>
      {editorial ? <View style={{padding:18,gap:8}}>
        {button(extension ? 'Refine extra beats' : referencePlan ? 'Preview changes' : 'Refine story', () => void refine(),
          busy || loading || !selected || !validCount || !validTemperature || (!extension && !text.trim()) || text.length > 8000,false,true)}
        <Text style={styles.muted}>Review the draft before applying.</Text>
      </View> : null}
    </SafeAreaView></KeyboardSafeView>
  </Modal>;
}

const createStyles = (colors: ReturnType<typeof useThemeColors>) => StyleSheet.create({
  screen:{flex:1,backgroundColor:colors.background},
  header:{flexDirection:'row',justifyContent:'space-between',alignItems:'center',padding:16},
  heading:{color:colors.text,fontSize:22,fontWeight:'700'},
  content:{padding:18,paddingBottom:36,gap:12}, label:{color:colors.text,fontSize:16,fontWeight:'600'},
  muted:{color:colors.muted,fontSize:14,lineHeight:21}, error:{color:colors.danger,fontSize:14},
  input:{color:colors.text,backgroundColor:colors.panel,borderColor:colors.border,borderWidth:1,
    borderRadius:12,padding:14,minHeight:48,fontSize:16}, prompt:{minHeight:150,textAlignVertical:'top'},
  button:{backgroundColor:colors.panel,borderColor:colors.border,borderWidth:1,borderRadius:12,
    padding:14,minHeight:48,justifyContent:'center'}, buttonText:{color:colors.accent,fontSize:16,fontWeight:'600'},
  selected:{borderColor:colors.accent}, disabled:{opacity:0.45},
  row:{flexDirection:'row',flexWrap:'wrap',alignItems:'center',gap:10}, choices:{gap:6,paddingLeft:8},
});
