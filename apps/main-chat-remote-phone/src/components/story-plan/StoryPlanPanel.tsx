import {KeyboardSafeView} from '../KeyboardSafeView';
import {Keyboard} from 'react-native';
import React from 'react';
import { Alert, Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import type { StoryBeat, StoryPlan, StoryPlanDraft } from '../../api/types';
import { useThemeColors, useThemedStyles, usePresentationStyle } from '../../styles/ThemeContext';
import { controlGlyphTypography } from '../../styles/theme';

type Props = {
  visible: boolean;
  plan: StoryPlanDraft | StoryPlan | null;
  busy: boolean;
  error: string;
  onClose: () => void;
  onOpenLibrary?: () => void;
  onCreate?: () => void;
  onSave: (plan: StoryPlanDraft) => Promise<void>;
  onSendToChat: (plan: StoryPlanDraft) => Promise<void>;
  onStart: () => Promise<void>;
  onSendOpening: () => Promise<void>;
  openingPending: boolean;
  onProgression: (mode: 'automatic' | 'manual') => Promise<void>;
  onBeat: (index: number) => Promise<void>;
  onRemove: () => Promise<void>;
  onRefresh: () => Promise<void>;
  onExtend?: () => Promise<void>;
  onTransport?: () => Promise<void>;
  transportLabel?: string;
  extension?: { source: StoryPlan; onAppend: (plan: StoryPlanDraft, resume: boolean) => Promise<void> };
  onBackToRefine?: (plan: StoryPlanDraft) => void;
  comparison?: { onKeep: () => void; onUse: (plan: StoryPlanDraft) => void };
};
type EditorBeat = StoryBeat & { editorId: number };
type EditorPlan = Omit<StoryPlanDraft, 'beats'> & { beats: EditorBeat[] };

function isSaved(plan: StoryPlanDraft | StoryPlan): plan is StoryPlan {
  return 'status' in plan && 'revision' in plan;
}

export function StoryPlanPanel({ visible, plan, busy, error, onClose, onSave, onSendToChat,
  onStart, onSendOpening, openingPending, onProgression, onBeat, onRemove, onRefresh, onOpenLibrary,
  onExtend, onTransport, transportLabel, extension, onBackToRefine, comparison, onCreate }: Props) {
  const colors = useThemeColors();
  const styles = useThemedStyles(createStyles, 'StoryPlanPanel');
  const [draft, setDraft] = React.useState<EditorPlan | null>(null);
  const nextBeatId = React.useRef(0);
  const [more, setMore] = React.useState(false);
  const editorial = usePresentationStyle() === 'editorial';
  const [expandedBeats, setExpandedBeats] = React.useState<Record<number, boolean>>({});
  const [showDetails, setShowDetails] = React.useState(false);
  const [editingBeatId, setEditingBeatId] = React.useState<number | null>(null);
  React.useEffect(() => {
    setExpandedBeats({});
    setEditingBeatId(null);
    setDraft(plan ? { title: plan.title, premise: plan.premise, constraints: plan.constraints,
      opening_cue: plan.opening_cue, pace: plan.pace, beats: plan.beats.map(beat => ({ ...beat, editorId: ++nextBeatId.current })) } : null);
  }, [plan]);
  const saved = plan && isSaved(plan) ? plan : null;
  const editable = !saved || saved.status === 'saved';
  const cleanDraft: StoryPlanDraft | null = draft ? { ...draft,
    beats: draft.beats.map(({ editorId: _editorId, ...beat }) => beat) } : null;
  const dirty = Boolean(cleanDraft && plan && JSON.stringify(cleanDraft) !== JSON.stringify({
    title: plan.title, premise: plan.premise, constraints: plan.constraints,
    opening_cue: plan.opening_cue, pace: plan.pace, beats: plan.beats }));
  const close = () => {
    if (!dirty) { onClose(); return; }
    Alert.alert('Discard unsaved edits?', 'Your Story Plan changes have not been saved.', [
      { text: 'Keep editing', style: 'cancel' },
      { text: 'Discard edits', style: 'destructive', onPress: onClose },
    ]);
  };
  const update = (field: keyof Omit<StoryPlanDraft, 'beats'>, value: string) =>
    setDraft(current => current ? { ...current, [field]: value } : current);
  const updateBeat = (id: number, field: keyof StoryBeat, value: string) => setDraft(current => {
    if (!current) return current;
    const beats = current.beats.map(beat => beat.editorId === id ? { ...beat, [field]: value } : beat);
    return { ...current, beats };
  });
  const moveBeat = (id: number, direction: -1 | 1) => setDraft(current => {
    const index = current?.beats.findIndex(beat => beat.editorId === id) ?? -1;
    if (!current || index < 0 || index + direction < 0 || index + direction >= current.beats.length) return current;
    const beats = [...current.beats];
    const first = beats[index]!, second = beats[index + direction]!;
    beats[index] = second; beats[index + direction] = first;
    return { ...current, beats };
  });
  const button = (label: string, action: () => void, disabled = busy) => (
    <Pressable accessibilityRole="button" accessibilityLabel={label} disabled={disabled}
      style={[styles.button, disabled && styles.disabled]} onPress={action}>
      <Text style={styles.buttonText}>{label}</Text>
    </Pressable>
  );
  const field = (label: string, value: string, onChange: (text: string) => void, multiline = false) => (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <TextInput accessibilityLabel={label} value={value} onChangeText={onChange} editable={editable && !busy}
        multiline={multiline} style={[styles.input, multiline && styles.multiline]}
        placeholderTextColor={colors.muted} />
    </View>
  );
  return <Modal onShow={Keyboard.dismiss} visible={visible} animationType="slide" onRequestClose={close}>
    <KeyboardSafeView active={visible}><SafeAreaView style={styles.screen}>
      <View style={styles.header}><Text style={styles.heading}>{extension ? 'Review extra beats' : 'Story Plan'}</Text>
        {onOpenLibrary ? button('Library', () => {
          if (!dirty) { onOpenLibrary(); return; }
          Alert.alert('Discard unsaved edits?', 'Your Story Plan changes have not been saved.', [
            {text:'Keep editing', style:'cancel'},
            {text:'Discard edits', style:'destructive', onPress:onOpenLibrary},
          ]);
        }, busy) : null}
        {button('Done', close, false)}</View>
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      {draft ? <View style={styles.controls}>
        <Text accessibilityLiveRegion="polite" style={styles.label}>{extension
          ? `${draft.beats.length} new beats after beat ${extension.source.beats.length}`
          : saved?.status === 'complete' ? 'Story finished — add more beats?'
          : saved ? `Beat ${saved.current_beat + 1} of ${saved.beats.length} · ${saved.status}`
          : comparison ? 'Review new draft · current draft is preserved' : 'Review your refined plan'}</Text>
        <ScrollView horizontal keyboardShouldPersistTaps="handled" contentContainerStyle={styles.row}>
          {comparison ? <>
            {button('Keep current', comparison.onKeep)}
            {button('Use new draft', () => {if(cleanDraft) comparison.onUse(cleanDraft);})}
          </> : extension ? <>
            {button('Add beats', () => {if(cleanDraft) void extension.onAppend(cleanDraft, false);}, busy || draft.beats.length < 5 || draft.beats.length > 20)}
            {button('Add & continue', () => {if(cleanDraft) void extension.onAppend(cleanDraft, true);}, busy || draft.beats.length < 5 || draft.beats.length > 20)}
          </> : <>
            {onBackToRefine && !saved ? button('Back to refine', () => {if(cleanDraft) onBackToRefine(cleanDraft);}) : null}
            {editable ? button(saved ? 'Save changes' : 'Create Story Plan', () => { if(cleanDraft) void onSave(cleanDraft); }) : null}
            {editable && !saved ? button('Send to Chat', () => {if(cleanDraft) void onSendToChat(cleanDraft);}) : null}
            {saved?.status === 'saved' ? button('Start story', () => void onStart(), busy || dirty) : null}
            {saved && saved.status !== 'saved' && onTransport ? button(transportLabel ?? 'Resume', () => void onTransport()) : null}
            {saved?.status === 'active' ? button('Next beat', () => void onBeat(saved.current_beat + 1), busy || saved.current_beat >= saved.beats.length - 1) : null}
            {onExtend && saved && saved.status !== 'saved' ? button('Add beats', () => void onExtend(), busy || dirty) : null}
          </>}
          {!comparison ? button(more ? 'Less' : 'More', () => setMore(!more), false) : null}
        </ScrollView>
        {more && !comparison ? <ScrollView horizontal keyboardShouldPersistTaps="handled" contentContainerStyle={styles.row}>
          {editable && draft.beats.length < (extension ? 20 : 30) ? button('Add beat', () => setDraft(current => current ? {
            ...current, beats:[...current.beats,{title:'',summary:'',editorId:++nextBeatId.current}]} : current)) : null}
          {saved?.status === 'active' ? <>
            {button(`Automatic${saved.progression === 'automatic' ? ' ✓' : ''}`, () => void onProgression('automatic'))}
            {button(`Manual${saved.progression === 'manual' ? ' ✓' : ''}`, () => void onProgression('manual'))}
            {button(openingPending ? 'Retry opening cue' : 'Send opening cue again', () => void onSendOpening())}
          </> : null}
          {saved ? button('Refresh progress', () => void onRefresh(), busy || dirty) : null}
          {saved ? button('Remove Story Plan', () => Alert.alert('Remove Story Plan?',
            'This removes the plan from the current conversation.',[
              {text:'Keep plan',style:'cancel'}, {text:'Remove',style:'destructive',onPress:()=>void onRemove()}])) : null}
        </ScrollView> : null}
      </View> : null}
      <ScrollView keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" contentContainerStyle={styles.content}>
        {!draft ? editorial && onCreate ? <View style={{gap:16,paddingVertical:24}}>
          <Text style={styles.heading}>Where does your story begin?</Text>
          <Text style={styles.muted}>Start with an idea, then review your story beats.</Text>
          {button('Refine a story',onCreate)}
        </View> : <Text style={styles.muted}>No Story Plan in this conversation. Use /story_refine followed by your story idea.</Text> : <>
          <Text style={styles.muted}>{saved ? `Status: ${saved.status} · Beat ${saved.current_beat + 1}/${saved.beats.length}`
            : comparison ? 'New candidate · edit it, then keep the current draft or use this one.'
            : 'Refined draft · review and edit before choosing what to do.'}</Text>
          {draft.pace ? <Text style={styles.muted}>Story pace: {draft.pace.charAt(0).toUpperCase() + draft.pace.slice(1)}</Text> : null}
          {editorial && !extension ? <Pressable accessibilityRole="button" accessibilityLabel="Story details"
            accessibilityState={{expanded: showDetails}} onPress={() => setShowDetails(value => !value)}
            style={{minHeight: 48, justifyContent: 'center'}}>
            <Text style={styles.heading}>{draft.title || 'Untitled story'}</Text>
            <Text style={styles.muted}>{showDetails ? 'Hide story details ' : 'Story details '}<Text style={controlGlyphTypography}>{showDetails ? '−' : '+'}</Text></Text>
          </Pressable> : null}
          {!extension ? <View style={editorial && !showDetails ? {display: 'none'} : undefined}>{field('Title', draft.title, value => update('title', value))}
          {field('Premise', draft.premise, value => update('premise', value), true)}
          {field('Story constraints', draft.constraints, value => update('constraints', value), true)}
          {field('Opening cue', draft.opening_cue, value => update('opening_cue', value), true)}</View> :
            <Text style={styles.muted}>Only these new beats will be appended. Earlier beats, characters, voices and history stay unchanged. Save to Library separately to update a named snapshot.</Text>}
          <Text style={styles.heading}>Ordered beats</Text>
          {draft.beats.map((beat, index) => <View key={beat.editorId} style={styles.beat}>
            {editorial ? <Pressable accessibilityRole="button" accessibilityLabel={`Beat ${index + 1}: ${beat.title || 'Untitled beat'}`}
              accessibilityState={{expanded: expandedBeats[beat.editorId] ?? (saved ? saved.current_beat === index : index === 0)}}
              onPress={() => setExpandedBeats(current => ({...current, [beat.editorId]: !(current[beat.editorId] ?? (saved ? saved.current_beat === index : index === 0))}))}
              style={{minHeight: 48, justifyContent: 'center'}}>
              <Text style={styles.label}>{index + 1}. {beat.title || 'Untitled beat'}{saved?.current_beat === index ? ' · Current' : ''} <Text style={controlGlyphTypography}>{expandedBeats[beat.editorId] ?? (saved ? saved.current_beat === index : index === 0) ? '−' : '+'}</Text></Text>
            </Pressable> : <Text style={styles.label}>{index + 1}. {beat.title || 'Untitled beat'}{saved?.current_beat === index ? ' · Current' : ''}</Text>}
            <View style={editorial && !(expandedBeats[beat.editorId] ?? (saved ? saved.current_beat === index : index === 0)) ? {display: 'none'} : {gap: 10}}>
            {editorial ? <>
              <Text style={[styles.muted, {fontFamily: 'serif', fontSize: 18, lineHeight: 28}]}>{beat.summary || 'No summary yet.'}</Text>
              {editable ? <Pressable accessibilityRole="button" accessibilityLabel={`Edit beat ${index + 1}`}
                accessibilityState={{expanded: editingBeatId === beat.editorId}}
                onPress={() => setEditingBeatId(id => id === beat.editorId ? null : beat.editorId)}
                style={{minHeight: 48, justifyContent: 'center'}}>
                <Text style={styles.buttonText}>{editingBeatId === beat.editorId ? 'Done editing' : 'Edit beat'}</Text>
              </Pressable> : null}
            </> : null}
            <View style={editorial && editingBeatId !== beat.editorId ? {display: 'none'} : {gap: 10}}>
            {field(`Beat ${index + 1} title`, beat.title, value => updateBeat(beat.editorId, 'title', value))}
            {field(`Beat ${index + 1} summary`, beat.summary, value => updateBeat(beat.editorId, 'summary', value), true)}
            {editable ? <View style={styles.row}>
              {button('Move up', () => moveBeat(beat.editorId, -1), busy || index === 0)}
              {button('Move down', () => moveBeat(beat.editorId, 1), busy || index === draft.beats.length - 1)}
              {button('Remove beat', () => setDraft(current => current ? {
                ...current, beats: current.beats.filter(item => item.editorId !== beat.editorId) } : current),
                busy || draft.beats.length <= (extension ? 5 : 2))}
            </View> : !editorial && saved && saved.status !== 'saved' ? button('Set current beat', () => void onBeat(index), busy) : null}
            </View>
            {editorial && saved && saved.status !== 'saved' ? button('Set current beat', () => void onBeat(index), busy) : null}
            </View>
          </View>)}
        </>}
      </ScrollView>
    </SafeAreaView></KeyboardSafeView>
  </Modal>;
}

const createStyles = (colors: ReturnType<typeof useThemeColors>) => StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: 16 },
  controls: {paddingHorizontal:16, paddingBottom:12, gap:8, borderBottomWidth:1, borderColor:colors.border},
  content: { gap: 14, padding: 16, paddingBottom: 40 },
  heading: { color: colors.text, fontSize: 20, fontWeight: '700' },
  muted: { color: colors.muted, fontSize: 14, lineHeight: 20 },
  field: { gap: 6 }, label: { color: colors.text, fontSize: 15, fontWeight: '600' },
  input: { color: colors.text, backgroundColor: colors.panel, borderColor: colors.border,
    borderWidth: 1, borderRadius: 10, minHeight: 48, paddingHorizontal: 12, paddingVertical: 10, fontSize: 16 },
  multiline: { minHeight: 90, textAlignVertical: 'top' },
  beat: { gap: 10, padding: 12, backgroundColor: colors.backgroundElevated,
    borderColor: colors.border, borderWidth: 1, borderRadius: 12 },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  button: { backgroundColor: colors.panel, borderColor: colors.border, borderWidth: 1,
    borderRadius: 10, minHeight: 44, justifyContent: 'center', paddingHorizontal: 14, alignSelf: 'flex-start' },
  buttonText: { color: colors.accent, fontSize: 14, fontWeight: '700' },
  disabled: { opacity: 0.4 }, error: { color: colors.danger, fontSize: 14, paddingHorizontal: 16 },
});
