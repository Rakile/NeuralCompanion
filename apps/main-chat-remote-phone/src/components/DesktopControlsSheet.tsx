import {KeyboardSafeView} from './KeyboardSafeView';
import {Keyboard} from 'react-native';
import React from 'react';
import { Alert, Animated, Modal, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import type { ContinuousSettings, ContinuousState, RemoteState, StoryPlan, StoryPace } from '../api/types';
import { DEFAULT_RESPONSE_CARD_ORDER, moveResponseCard, normalizeResponseCardOrder } from '../utils/responseCardOrder';
import type { ResponseCardId } from '../utils/responseCardOrder';
import { useThemedStyles, usePresentationStyle } from '../styles/ThemeContext';
import { controlGlyphTypography, type ThemeColors } from '../styles/theme';
import { RuntimeBar } from './RuntimeBar';
import { ControlsBar } from './ControlsBar';
import { ResponseCardDragHandle } from './ResponseCardDragHandle';
import { GuidancePresetPicker } from './continuous/GuidancePresetPicker';
import type {QuickMenuPreferences} from '../utils/quickMenuActions';
import type {PhoneSettings} from '../hooks/usePhoneSettings';
import {QuickMenuActionButton} from './QuickMenuActionButton';
import {LiveFullscreenSlider} from './live-fullscreen/LiveFullscreenSlider';

type ChatSectionVisibility = Pick<PhoneSettings,
  'showVisualButton' | 'showStoryShortcuts' | 'showContinuousBar' | 'showCompanionHeader' | 'showSoundsMenu'>;
const CHAT_SECTION_TOGGLES = [
  ['showVisualButton', 'Show Visual button'],
  ['showStoryShortcuts', 'Show Story Plan / Library'],
  ['showContinuousBar', 'Show Continuous Mode bar'],
  ['showCompanionHeader', 'Show character name / view selector'],
  ['showSoundsMenu', 'Show sounds menu'],
] as const;

type Props = QuickMenuPreferences & {
  visible: boolean;
  autoClose: boolean;
  onAutoCloseChange: (value: boolean) => void;
  sectionVisibility?: ChatSectionVisibility;
  onSectionVisibilityChange?: (patch: Partial<ChatSectionVisibility>) => void;
  liveControls?: React.ReactNode;
  state: RemoteState | null;
  disabled: boolean;
  resetDisabled: boolean;
  onClose: () => void;
  onStart: () => Promise<void>;
  onStop: () => Promise<void>;
  onControl: (action: string) => Promise<void>;
  onForceContinuation?: () => Promise<void>;
  onQuickSave?: () => Promise<void>;
  onQuickLoad?: () => Promise<void>;
  onStoryLibrary?: () => void;
  onSoundscape?: () => void;
  onStoryTransport?: () => Promise<void>;
  storyTransport?: 'play' | 'pause' | 'resume';
  paused?: boolean;
  onGenerateImage?: () => Promise<void>;
  selectedMessageId?: string;
  selectedMessageText?: string;
  storyPlan?: StoryPlan | null;
  storyPlanLoading?: boolean;
  storyPlanError?: string;
  onNextStoryBeat?: () => Promise<void>;
  onStoryPaceChange?: (pace: StoryPace) => Promise<void>;
  onReset: () => void;
  continuousState?: ContinuousState | null;
  onContinuousSettingsChange?: (patch: Partial<ContinuousSettings>) => Promise<void>;
  cardOrder?: ResponseCardId[];
  onCardOrderChange?: (order: ResponseCardId[]) => void;
};

export function DesktopControlsSheet({ liveControls, visible, autoClose, onAutoCloseChange, sectionVisibility, onSectionVisibilityChange, state, disabled, resetDisabled, onClose, onStart, onStop, onControl, onForceContinuation, onQuickSave, onQuickLoad, onStoryLibrary, onSoundscape, onStoryTransport, storyTransport = 'play', onReset, paused, onGenerateImage, selectedMessageId, selectedMessageText, storyPlan, storyPlanLoading = false, storyPlanError = '', onNextStoryBeat, onStoryPaceChange, continuousState, onContinuousSettingsChange, cardOrder = [...DEFAULT_RESPONSE_CARD_ORDER], onCardOrderChange, quickMenuActions, onQuickMenuActionsChange }: Props) {
  const styles = useThemedStyles(createStyles, 'DesktopControlsSheet');
  const insets = useSafeAreaInsets();
  const [generating, setGenerating] = React.useState(false);
  const editorial = usePresentationStyle() === 'editorial';
  const [expandedSections, setExpandedSections] = React.useState<Record<string, boolean>>({controls: true});
  const [preferencesOpen, setPreferencesOpen] = React.useState(false);
  const [reorderSections, setReorderSections] = React.useState(false);
  const [imageStatus, setImageStatus] = React.useState('');
  const [imageError, setImageError] = React.useState('');
  const [continuousBusy, setContinuousBusy] = React.useState(false);
  const [continuousError, setContinuousError] = React.useState('');
  const [storyBusy, setStoryBusy] = React.useState(false);
  const [storyStatus, setStoryStatus] = React.useState('');
  const [storyError, setStoryError] = React.useState('');
  const [beatBusy, setBeatBusy] = React.useState(false);
  const [beatError, setBeatError] = React.useState('');
  const [paceBusy, setPaceBusy] = React.useState(false);
  // Controls with their own asynchronous errors stay visible. For the
  // collapsible sections, pending work and errors override manual collapse.
  const sectionOpen = (id: ResponseCardId) => !editorial ||
    !['continuous', 'selected', 'story', 'reset', 'session'].includes(id) ||
    Boolean(expandedSections[id]) ||
    (id === 'continuous' && Boolean(continuousBusy || continuousError)) ||
    (id === 'selected' && Boolean(generating || imageStatus || imageError)) ||
    (id === 'story' && Boolean(storyBusy || storyStatus || storyError));
  const planInFlight = React.useRef(false);
  const [guidanceDraft, setGuidanceDraft] = React.useState(continuousState?.settings?.guidance ?? '');
  const [guidanceDirty, setGuidanceDirty] = React.useState(false);
  const [strengthDraft, setStrengthDraft] = React.useState(continuousState?.settings?.guidance_strength ?? 60);
  const [strengthDirty, setStrengthDirty] = React.useState(false);
  const continuousInFlight = React.useRef(false);
  const [draggedId, setDraggedId] = React.useState<ResponseCardId | null>(null);
  const [targetId, setTargetId] = React.useState<ResponseCardId | null>(null);
  const dragOffset = React.useRef(new Animated.Value(0)).current;
  const scroll = React.useRef<ScrollView>(null);
  const scrollY = React.useRef(0);
  const restoreScroll = React.useRef(false);
  const layouts = React.useRef<Partial<Record<ResponseCardId, { y: number; height: number }>>>({});
  const drag = React.useRef<{ id: ResponseCardId; startScroll: number; dy: number } | null>(null);
  const drop = React.useRef<{ id: ResponseCardId; after: boolean } | null>(null);
  const viewport = React.useRef<{ top: number; bottom: number } | null>(null);
  const edgeDirection = React.useRef<-1 | 0 | 1>(0);
  const edgeTimer = React.useRef<ReturnType<typeof setInterval> | null>(null);
  const imageGeneration = React.useRef(0);
  const runtime = state?.runtime_status;
  const running = Boolean(state?.engine?.running ?? runtime?.running);
  const buddy = state?.buddy_chat;
  const buddyAvailable = buddy?.available !== false && state?.features?.buddy_chat !== false;
  const continuousSettings = continuousState?.settings;
  const presets = continuousState?.guidance_presets ?? [];
  const continuousDisabled = disabled || continuousBusy || !continuousState?.owned || !continuousSettings;
  React.useEffect(() => {
    if (!guidanceDirty) setGuidanceDraft(continuousSettings?.guidance ?? '');
  }, [continuousSettings?.guidance, visible]);
  React.useEffect(() => {
    if (!strengthDirty) setStrengthDraft(continuousSettings?.guidance_strength ?? 60);
  }, [continuousSettings?.guidance_strength, strengthDirty, visible]);
  const details = [
    ['Provider', runtime?.chat_provider], ['Model', runtime?.model_name],
    ['Voice engine', runtime?.tts_backend], ['Microphone', runtime?.microphone_state],
    ['Buddies', buddyAvailable ? (buddy?.enabled ? `${Number(buddy.active_persona_count ?? 0) || 'On'}` : 'Off') : ''],
  ].filter((row): row is [string, string] => Boolean(row[1]));
  React.useEffect(() => { imageGeneration.current++; setGenerating(false); setImageStatus(''); setImageError(''); }, [selectedMessageId, visible]);
  React.useEffect(() => { setBeatError(''); }, [storyPlan?.revision, selectedMessageId, visible]);
  const stopEdgeScroll = () => {
    edgeDirection.current = 0;
    if (edgeTimer.current) clearInterval(edgeTimer.current);
    edgeTimer.current = null;
  };
  React.useEffect(() => {
    if (!visible) {
      restoreScroll.current = true;
      setContinuousError(''); stopEdgeScroll();
      drag.current = null; drop.current = null; setDraggedId(null); setTargetId(null); dragOffset.setValue(0);
    } else if (restoreScroll.current) {
      requestAnimationFrame(() => scroll.current?.scrollTo({ y: scrollY.current, animated: false }));
    }
    return () => { if (edgeTimer.current) clearInterval(edgeTimer.current); edgeTimer.current = null; };
  }, [visible, dragOffset]);
  const changeContinuousSettings = async (patch: Partial<ContinuousSettings>) => {
    if (continuousInFlight.current || continuousDisabled || !onContinuousSettingsChange) return false;
    continuousInFlight.current = true;
    setContinuousBusy(true);
    setContinuousError('');
    try { await onContinuousSettingsChange(patch); return true; }
    catch (failure) { setContinuousError(failure instanceof Error ? failure.message : 'Could not save Continuous Mode settings.'); return false; }
    finally { continuousInFlight.current = false; setContinuousBusy(false); }
  };
  const runAction = async (action: () => Promise<void>) => {
    const generation = imageGeneration.current;
    await action();
    if (autoClose && generation === imageGeneration.current) onClose();
  };
  const runStoryAction = async (action: () => Promise<void>, success: string) => {
    if (storyBusy) return;
    setStoryBusy(true); setStoryStatus(''); setStoryError('');
    try { await action(); setStoryStatus(success); }
    catch (failure) { setStoryError(failure instanceof Error ? failure.message : 'Could not complete the chat save action.'); }
    finally { setStoryBusy(false); }
  };
  const advanceBeat = async () => {
    if (planInFlight.current || !onNextStoryBeat) return;
    planInFlight.current = true;
    setBeatBusy(true);
    setBeatError('');
    try {
      await onNextStoryBeat();
      if (autoClose) onClose();
    } catch (error) {
      setBeatError(error instanceof Error ? error.message : 'Could not advance the Story Plan beat.');
    } finally {
      planInFlight.current = false;
      setBeatBusy(false);
    }
  };
  const changePace = async (pace: StoryPace) => {
    if (planInFlight.current || !onStoryPaceChange || storyPlan?.pace === pace) return;
    planInFlight.current = true;
    setPaceBusy(true);
    setBeatError('');
    try {
      await onStoryPaceChange(pace);
      if (autoClose) onClose();
    } catch (error) {
      setBeatError(error instanceof Error ? error.message : 'Could not change story pace.');
    } finally {
      planInFlight.current = false;
      setPaceBusy(false);
    }
  };
  const sections: { id: ResponseCardId; title: string; body: React.ReactNode }[] = [
    ...(onContinuousSettingsChange ? [{ id: 'continuous' as const, title: 'Continuous Mode', body: <>
      <Text style={styles.caption}>Mode and premade save immediately. Custom guidance uses Save.</Text>
      <View style={styles.modeRow}>{(['off', 'simple', 'ai_guided'] as const).map(mode => <Pressable key={mode}
        accessibilityRole="button" accessibilityLabel={`Continuous Mode ${mode === 'ai_guided' ? 'AI Guided' : mode === 'simple' ? 'Simple' : 'Off'}`}
        accessibilityState={{ selected: continuousSettings?.mode === mode, disabled: Boolean(continuousDisabled) }}
        disabled={Boolean(continuousDisabled)} onPress={() => { void changeContinuousSettings({ mode }); }}
        style={[styles.modeButton, continuousSettings?.mode === mode && styles.modeSelected, continuousDisabled && styles.disabled]}>
        <Text style={[styles.modeText, continuousSettings?.mode === mode && styles.modeSelectedText]}>{mode === 'ai_guided' ? 'AI Guided' : mode === 'simple' ? 'Simple' : 'Off'}</Text>
      </Pressable>)}</View>
      <View style={styles.autoCloseRow}>
        <Text style={styles.autoCloseText}>Use premade</Text>
        <Switch accessibilityLabel="Use premade" value={Boolean(continuousSettings?.use_premade)}
          disabled={Boolean(continuousDisabled || !presets.length)}
          onValueChange={use_premade => { void changeContinuousSettings({ use_premade }); }} />
      </View>
      {!continuousSettings?.use_premade ? <>
        <Text style={styles.guidanceLabel}>Your AI Guidance prompt</Text>
        <TextInput accessibilityLabel="AI Guidance prompt" multiline value={guidanceDraft} maxLength={8000}
          editable={!continuousDisabled} onChangeText={value => { setGuidanceDraft(value); setGuidanceDirty(true); }}
          placeholder="Guide the next story beat…" placeholderTextColor={styles.caption.color}
          textAlignVertical="top" style={[styles.guidanceInput, continuousDisabled && styles.disabled]} />
        <Pressable accessibilityRole="button" accessibilityLabel="Save AI Guidance prompt"
          accessibilityState={{ disabled: Boolean(continuousDisabled || !guidanceDirty) }}
          disabled={Boolean(continuousDisabled || !guidanceDirty)}
          onPress={() => { void changeContinuousSettings({ guidance: guidanceDraft }).then(saved => { if (saved) setGuidanceDirty(false); }); }}
          style={[styles.guidanceSave, guidanceDirty && styles.guidanceSaveDirty, (continuousDisabled || !guidanceDirty) && styles.disabled]}>
          <Text style={[styles.guidanceSaveText, guidanceDirty && styles.guidanceSaveDirtyText]}>Save guidance</Text>
        </Pressable>
      </> : <>
      <GuidancePresetPicker presets={presets} value={continuousSettings?.guidance_preset} disabled={Boolean(continuousDisabled)}
        onChange={guidance_preset=>{void changeContinuousSettings({use_premade:true,guidance_preset});}}/>
      <Text style={styles.caption}>Switch off Use premade to edit your saved AI Guidance prompt.</Text>
      </>}
      {continuousState?.guidance_strength_supported ? <>
        <View pointerEvents={continuousDisabled?'none':'auto'}>
          <LiveFullscreenSlider label="Guidance strength" value={strengthDraft} minimum={0} maximum={100}
            onChange={value=>{setStrengthDraft(value);setStrengthDirty(true);}}/>
        </View>
        <Text style={styles.caption}>0% Story led · 25% Gentle · 50% Balanced · 75% Strong · 100% Director</Text>
        <Pressable accessibilityRole="button" accessibilityLabel="Save guidance strength"
          disabled={Boolean(continuousDisabled || !strengthDirty)}
          onPress={()=>{void changeContinuousSettings({guidance_strength:strengthDraft}).then(saved=>{
            if(saved)setStrengthDirty(false);
          });}}
          style={[styles.guidanceSave, strengthDirty&&styles.guidanceSaveDirty, (continuousDisabled||!strengthDirty)&&styles.disabled]}>
          <Text style={styles.guidanceSaveText}>Save strength</Text>
        </Pressable>
        <Text style={styles.caption}>Applies to the next automated reply. Current speech finishes normally.</Text>
      </> : null}
      {continuousError ? <Text accessibilityRole="alert" style={styles.error}>{continuousError}</Text> : null}
      {!continuousState?.owned ? <Text style={styles.caption}>{continuousState ? 'Another phone owns Continuous Mode.' : 'Waiting for Continuous Mode settings.'}</Text> : null}
    </> }] : []),
    ...(onGenerateImage ? [{ id: 'selected' as const, title: 'Selected response', body: <>
      {selectedMessageText ? <Text numberOfLines={3} style={styles.quote}>{selectedMessageText}</Text> : null}
      <Pressable accessibilityRole="button" accessibilityLabel="Generate image from selected response"
        disabled={disabled || generating} style={[styles.imageButton, (disabled || generating) && styles.disabled]}
        onPress={async () => {
          if (generating) return;
          const generation = imageGeneration.current;
          setGenerating(true); setImageStatus(''); setImageError('');
          try { await onGenerateImage(); if (generation === imageGeneration.current) { setImageStatus('Image requested for this response.'); if (autoClose) onClose(); } }
          catch (failure) { if (generation === imageGeneration.current) setImageError(failure instanceof Error ? failure.message : 'Image generation failed.'); }
          finally { if (generation === imageGeneration.current) setGenerating(false); }
        }}><Text style={styles.doneText}>{generating ? 'Requesting image…' : 'Generate image'}</Text></Pressable>
      <Text style={styles.caption}>Create a Visual Reply from this message.</Text>
      {imageStatus ? <Text accessibilityLiveRegion="polite" style={styles.caption}>{imageStatus}</Text> : null}
      {imageError ? <Text accessibilityRole="alert" style={styles.error}>{imageError}</Text> : null}
    </> }] : []),
    { id: 'controls', title: 'Chat controls', body: <ControlsBar actions={state?.controls?.actions ?? []} disabled={disabled}
      onControl={action => runAction(() => onControl(action))} wrap grouped paused={paused}
      quickMenuActions={quickMenuActions} onQuickMenuActionsChange={onQuickMenuActionsChange} /> },
    ...(state?.features?.story_checkpoint_version && onQuickSave && onQuickLoad ? [{ id: 'story' as const, title: 'Story saves', body: <>
      <Text style={styles.caption}>Your current story is saved automatically on the desktop. Quick Save keeps a separate manual copy.</Text>
      <View style={styles.modeRow}>
        {onStoryLibrary ? <Pressable accessibilityRole="button" accessibilityLabel="Open Story Library"
          style={styles.storyButton} onPress={() => { onClose(); onStoryLibrary(); }}>
          <Text style={styles.doneText}>Story Library</Text>
        </Pressable> : null}
        {onStoryTransport ? <Pressable accessibilityRole="button" accessibilityLabel={`${storyTransport} saved story`}
          disabled={disabled || storyBusy} style={[styles.storyButton, (disabled || storyBusy) && styles.disabled]}
          onPress={() => { void runStoryAction(onStoryTransport, 'Story playback updated.'); }}>
          <Text style={styles.doneText}>{storyTransport === 'play' ? 'Play story' : storyTransport === 'pause' ? 'Pause story' : 'Resume story'}</Text>
        </Pressable> : null}
        <Pressable accessibilityRole="button" accessibilityLabel="Quick Save chat" disabled={disabled || storyBusy}
          style={[styles.storyButton, (disabled || storyBusy) && styles.disabled]}
          onPress={() => { void runStoryAction(onQuickSave, 'Chat saved.'); }}>
          <Text style={styles.doneText}>Quick Save</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Quick Load chat" disabled={disabled || storyBusy}
          style={[styles.storyButton, (disabled || storyBusy) && styles.disabled]}
          onPress={() => {
            const load = () => { void runStoryAction(onQuickLoad, 'Saved chat loaded.'); };
            if (state?.chat?.messages?.length) Alert.alert('Replace current chat?', 'Quick Load replaces the story currently open on the phone and desktop.', [
              { text: 'Cancel', style: 'cancel' }, { text: 'Quick Load', onPress: load },
            ]);
            else load();
          }}>
          <Text style={styles.doneText}>Quick Load</Text>
        </Pressable>
      </View>
      {storyStatus ? <Text accessibilityLiveRegion="polite" style={styles.caption}>{storyStatus}</Text> : null}
      {storyError ? <Text accessibilityRole="alert" style={styles.error}>{storyError}</Text> : null}
    </> }] : []),
    ...(liveControls ? [{ id: 'microphone' as const, title: 'Live microphone', body: liveControls }] : []),
    { id: 'engine', title: 'Desktop engine', body: <RuntimeBar showDetails={false} state={state} disabled={disabled}
      onStart={onStart} onStop={onStop} /> },
    { id: 'reset', title: 'Reset Chat', body: <>
      <Text style={styles.caption}>Reset clears the shared conversation on your phone and desktop.</Text>
      <Pressable accessibilityRole="button" accessibilityLabel="Reset Chat" disabled={disabled || resetDisabled}
        style={[styles.resetButton, (disabled || resetDisabled) && styles.disabled]} onPress={() => { onReset(); if (autoClose) onClose(); }}>
        <Text style={styles.resetText}>Reset Chat</Text>
      </Pressable>
    </> },
    { id: 'session', title: 'Session information', body: <>
      <View style={styles.statusRow}>
        <View style={[styles.statusDot, running && !disabled ? styles.runningDot : styles.stoppedDot]} />
        <Text style={styles.statusText}>{disabled ? 'Disconnected' : running ? 'Desktop running' : 'Desktop stopped'}</Text>
        {paused ? <Text accessibilityLiveRegion="polite" style={styles.paused}>Audio paused</Text> : null}
      </View>
      {details.map(([label, value]) => <View key={label} style={styles.detailRow}>
        <Text style={styles.detailLabel}>{label}</Text><Text selectable style={styles.detailValue}>{value}</Text>
      </View>)}
    </> },
  ];
  const ordered = normalizeResponseCardOrder(cardOrder)
    .map(id => sections.find(section => section.id === id))
    .filter((section): section is typeof sections[number] => Boolean(section));
  const beginDrag = (id: ResponseCardId) => {
    if (!onCardOrderChange) return;
    drag.current = { id, startScroll: scrollY.current, dy: 0 };
    drop.current = null;
    dragOffset.setValue(0);
    setDraggedId(id);
    scroll.current?.getNativeScrollRef()?.measureInWindow((_x, y, _width, height) => { viewport.current = { top: y, bottom: y + height }; });
  };
  const updateDrop = (id: ResponseCardId, dy: number) => {
    const current = drag.current;
    const origin = layouts.current[id];
    if (!current || current.id !== id || !origin) return;
    dragOffset.setValue(dy + scrollY.current - current.startScroll);
    const center = origin.y + origin.height / 2 + dy + scrollY.current - current.startScroll;
    const nearest = ordered.filter(section => section.id !== id && layouts.current[section.id])
      .map(section => ({ id: section.id, layout: layouts.current[section.id]! }))
      .sort((a, b) => Math.abs(center - (a.layout.y + a.layout.height / 2)) - Math.abs(center - (b.layout.y + b.layout.height / 2)))[0];
    drop.current = nearest ? { id: nearest.id, after: center >= nearest.layout.y + nearest.layout.height / 2 } : null;
    setTargetId(nearest?.id ?? null);
  };
  const moveDrag = (id: ResponseCardId, dy: number, pageY: number) => {
    const current = drag.current;
    if (!current || current.id !== id) return;
    current.dy = dy;
    updateDrop(id, dy);
    const bounds = viewport.current;
    const direction = bounds && pageY < bounds.top + 55 ? -1 : bounds && pageY > bounds.bottom - 55 ? 1 : 0;
    if (direction === edgeDirection.current) return;
    stopEdgeScroll();
    edgeDirection.current = direction;
    if (direction) edgeTimer.current = setInterval(() => {
      if (drag.current?.id === id) scroll.current?.scrollTo({ y: Math.max(0, scrollY.current + direction * 12), animated: false });
    }, 40);
  };
  const cancelDrag = () => {
    stopEdgeScroll();
    drag.current = null;
    drop.current = null;
    dragOffset.setValue(0);
    setDraggedId(null);
    setTargetId(null);
  };
  const endDrag = (id: ResponseCardId) => {
    if (drag.current?.id === id && drop.current && onCardOrderChange) {
      const next = moveResponseCard(normalizeResponseCardOrder(cardOrder), id, drop.current.id, drop.current.after);
      if (next.some((card, index) => card !== cardOrder[index])) onCardOrderChange(next);
    }
    cancelDrag();
  };
  const stepCard = (id: ResponseCardId, direction: -1 | 1) => {
    const index = ordered.findIndex(section => section.id === id);
    const neighbor = ordered[index + direction];
    if (neighbor && onCardOrderChange) onCardOrderChange(moveResponseCard(normalizeResponseCardOrder(cardOrder), id, neighbor.id, direction > 0));
  };
  return (
    <Modal onShow={Keyboard.dismiss} visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardSafeView active={visible} style={styles.overlay}>
        <Pressable style={StyleSheet.absoluteFill} accessibilityRole="button" accessibilityLabel="Close response controls" onPress={onClose} />
        <View accessibilityViewIsModal style={[styles.sheet, { paddingBottom: Math.max(12, insets.bottom) }]}>
          <View style={styles.header}>
            <Text accessibilityRole="header" style={styles.title}>Response controls</Text>
            <Pressable accessibilityRole="button" accessibilityLabel="Close response controls" style={styles.done} onPress={onClose}>
              <Text style={styles.doneText}>Done</Text>
            </Pressable>
          </View>
          <ScrollView ref={scroll} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" contentContainerStyle={[styles.content,editorial&&{gap:0,paddingTop:8}]}
            onContentSizeChange={() => {
              if (visible && restoreScroll.current) {
                restoreScroll.current = false;
                requestAnimationFrame(() => scroll.current?.scrollTo({ y: scrollY.current, animated: false }));
              }
            }}
            scrollEnabled={!draggedId} scrollEventThrottle={16}
            onScroll={event => {
              scrollY.current = event.nativeEvent.contentOffset.y;
              if (drag.current) updateDrop(drag.current.id, drag.current.dy);
            }}>
            {editorial ? <ControlsBar actions={state?.controls?.actions ?? []} disabled={disabled}
              onControl={action => runAction(() => onControl(action))} wrap grouped paused={paused}
              onForceContinuation={onForceContinuation ? ()=>runAction(onForceContinuation) : undefined}
              quickMenuActions={quickMenuActions} onQuickMenuActionsChange={onQuickMenuActionsChange}/> : null}
            {editorial ? <Pressable accessibilityRole="button" accessibilityLabel="Menu preferences"
              accessibilityState={{expanded: preferencesOpen}} onPress={()=>setPreferencesOpen(value=>!value)}
              style={styles.autoCloseRow}><Text style={styles.sectionTitle}>Menu preferences <Text style={controlGlyphTypography}>{preferencesOpen ? '−' : '+'}</Text></Text></Pressable> : null}
            <View style={editorial && !preferencesOpen ? {display: 'none'} : undefined}>
            {editorial && onCardOrderChange ? <View style={styles.autoCloseRow}>
              <Text style={styles.autoCloseText}>Reorder sections</Text>
              <Switch accessibilityLabel="Reorder sections" value={reorderSections} onValueChange={setReorderSections}/>
            </View> : null}
            <View style={styles.autoCloseRow}>
              <Text style={styles.autoCloseText}>Auto close menu</Text>
              <Switch accessibilityLabel="Auto close menu" value={autoClose} onValueChange={onAutoCloseChange} />
            </View>
            {onSectionVisibilityChange ? <View style={styles.card}>
              <Text accessibilityRole="header" style={styles.autoCloseText}>Chat sections</Text>
              {CHAT_SECTION_TOGGLES.map(([key, label]) => <View key={key} style={styles.autoCloseRow}>
                <Text style={[styles.autoCloseText, {flex: 1, paddingRight: 12}]}>{label}</Text>
                <Switch accessibilityLabel={label} value={sectionVisibility?.[key] !== false}
                  onValueChange={value => onSectionVisibilityChange({[key]: value})} />
              </View>)}
              <Text style={styles.caption}>Saved on this phone. Hiding a section keeps its features running. Double-tap a response to show it again.</Text>
            </View> : null}
            </View>
            {onSoundscape ? <QuickMenuActionButton action="soundscape" quickMenuActions={quickMenuActions} onQuickMenuActionsChange={onQuickMenuActionsChange}
              accessibilityRole="button" accessibilityLabel="Open Soundscape" style={styles.storyButton}
              onPress={()=>{onClose();onSoundscape();}}><Text style={styles.doneText}>Soundscape · ambience and music</Text></QuickMenuActionButton> : null}
            {storyPlanLoading ? <Text style={styles.caption}>Checking Story Plan progress…</Text> : null}
            {storyPlan?.status === 'active' && !storyPlanLoading ? <View style={styles.storyBeatCard}>
              <View style={styles.storyBeatText}>
                <Text style={styles.storyBeatCount}>{`Beat ${storyPlan.current_beat + 1} of ${storyPlan.beats.length}`}</Text>
                <Text style={styles.storyBeatTitle} numberOfLines={2}>{storyPlan.beats[storyPlan.current_beat]?.title}</Text>
                <Text style={styles.caption}>{storyPlan.progression === 'automatic' ? 'Automatic progression' : 'Manual progression'}</Text>
              </View>
              <Pressable accessibilityRole="button" accessibilityLabel="Next story beat"
                accessibilityState={{disabled:disabled || beatBusy || storyPlan.current_beat + 1 >= storyPlan.beats.length}}
                disabled={disabled || beatBusy || storyPlan.current_beat + 1 >= storyPlan.beats.length}
                style={[styles.storyBeatButton, (disabled || beatBusy || storyPlan.current_beat + 1 >= storyPlan.beats.length) && styles.disabled]}
                onPress={() => { void advanceBeat(); }}>
                <Text style={styles.storyBeatButtonText}>Next beat</Text>
              </Pressable>
            </View> : null}
            {storyPlan?.status === 'active' && !storyPlanLoading
              && ['slow', 'medium', 'fast'].includes(storyPlan.pace) ? <View style={styles.storyPaceCard}>
              <Text style={styles.storyBeatCount}>Story pace: {storyPlan.pace === 'slow' ? 'Slow' : storyPlan.pace === 'fast' ? 'Fast' : 'Medium'}</Text>
              <Text style={styles.caption}>{storyPlan.pace === 'slow' ? 'About 5–8' : storyPlan.pace === 'fast' ? 'About 1–2' : 'About 3–4'} assistant replies per beat</Text>
              <View style={styles.storyPaceRow}>{(['slow', 'medium', 'fast'] as StoryPace[]).map(pace => {
                const selected = (storyPlan.pace ?? 'medium') === pace;
                const blocked = disabled || beatBusy || paceBusy || !onStoryPaceChange || selected;
                return <Pressable key={pace} accessibilityRole="button"
                  accessibilityLabel={`Story pace ${pace.charAt(0).toUpperCase()}${pace.slice(1)}`}
                  accessibilityState={{selected, disabled:blocked}} disabled={blocked}
                  style={[styles.storyPaceButton, selected && styles.storyPaceSelected, blocked && !selected && styles.disabled]}
                  onPress={() => { void changePace(pace); }}>
                  <Text style={styles.storyBeatButtonText}>{pace.charAt(0).toUpperCase()}{pace.slice(1)}</Text>
                </Pressable>;
              })}</View>
            </View> : null}
            {storyPlan?.status === 'complete' && !storyPlanLoading ? <Text style={styles.storyBeatCount}>Story Plan complete</Text> : null}
            {storyPlanError || beatError ? <Text accessibilityRole="alert" style={styles.error}>{beatError || storyPlanError}</Text> : null}
            {ordered.filter(section => !editorial || section.id !== 'controls').map(section => <Animated.View key={section.id}
              onLayout={event => { layouts.current[section.id] = event.nativeEvent.layout; }}
              style={[styles.card, editorial&&{paddingHorizontal:0,paddingVertical:4,gap:0}, draggedId === section.id && styles.draggedCard,
                targetId === section.id && styles.targetCard,
                draggedId === section.id && { transform: [{ translateY: dragOffset }] }]}>
              <View style={styles.cardHeader}>
                {editorial && ['continuous', 'selected', 'story', 'reset', 'session'].includes(section.id) ? <Pressable accessibilityRole="button"
                  accessibilityLabel={`${section.title} options`}
                  accessibilityState={{expanded: sectionOpen(section.id)}}
                  onPress={() => setExpandedSections(current => ({...current, [section.id]: !current[section.id]}))}
                  style={{flex: 1, minHeight: 48, justifyContent: 'center'}}>
                  <Text accessibilityRole="header" style={styles.sectionTitle}>{section.title} <Text style={controlGlyphTypography}>{sectionOpen(section.id) ? '−' : '+'}</Text></Text>
                </Pressable> : <Text accessibilityRole="header" style={styles.sectionTitle}>{section.title}</Text>}
                {!editorial || reorderSections ? <ResponseCardDragHandle id={section.id} title={section.title} active={draggedId === section.id}
                  onBegin={beginDrag} onMove={moveDrag} onEnd={endDrag} onCancel={cancelDrag} onStep={stepCard} /> : null}
              </View>
              <View style={[styles.cardBody, editorial&&{paddingBottom:8}, !sectionOpen(section.id) && {display: 'none'}]}>{section.body}</View>
            </Animated.View>)}
          </ScrollView>
        </View>
      </KeyboardSafeView>
    </Modal>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  overlay: { flex: 1, justifyContent: 'flex-end', backgroundColor: '#00000088' },
  sheet: { flexShrink: 1, minHeight: 0, maxHeight: '90%', width: '100%', maxWidth: 640, alignSelf: 'center', backgroundColor: colors.panel,
    borderTopLeftRadius: 24, borderTopRightRadius: 24, paddingTop: 8 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 16 },
  title: { flexShrink: 1, color: colors.text, fontSize: 20, fontWeight: '700' },
  done: { minHeight: 48, minWidth: 64, alignItems: 'center', justifyContent: 'center' },
  doneText: { color: colors.text, fontSize: 16, fontWeight: '700' },
  content: { padding: 16, gap: 18 },
  autoCloseRow: { minHeight: 44, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  autoCloseText: { color: colors.text, fontSize: 14, fontWeight: '700' },
  storyBeatCard: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 12,
    borderRadius: 12, borderWidth: 1, borderColor: colors.accent, backgroundColor: colors.panelAlt },
  storyBeatText: { flex: 1, gap: 2 },
  storyBeatCount: { color: colors.accent, fontSize: 13, fontWeight: '700' },
  storyBeatTitle: { color: colors.text, fontSize: 15, fontWeight: '700' },
  storyBeatButton: { minHeight: 44, paddingHorizontal: 12, justifyContent: 'center', borderRadius: 9,
    borderWidth: 1, borderColor: colors.accent, backgroundColor: colors.panel },
  storyBeatButtonText: { color: colors.accent, fontSize: 13, fontWeight: '700' },
  storyPaceCard: { gap: 8, paddingHorizontal: 12, paddingBottom: 4 },
  storyPaceRow: { flexDirection: 'row', gap: 8 },
  storyPaceButton: { flex: 1, minHeight: 44, alignItems: 'center', justifyContent: 'center',
    borderRadius: 9, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.panelAlt },
  storyPaceSelected: { borderColor: colors.accent, backgroundColor: colors.panel },
  card: { backgroundColor: colors.panelAlt, borderRadius: 14, borderWidth: 1, borderColor: colors.border, padding: 12, gap: 10 },
  cardHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  cardBody: { gap: 10 },
  draggedCard: { zIndex: 10, elevation: 8, opacity: 0.93, borderColor: colors.warning },
  targetCard: { borderColor: colors.warning, borderWidth: 2 },
  modeRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  modeButton: { minHeight: 44, paddingHorizontal: 12, justifyContent: 'center', borderRadius: 9, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.panel },
  modeSelected: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
  modeText: { color: colors.text, fontSize: 13, fontWeight: '700' },
  modeSelectedText: { color: colors.accent },
  presetButton: { minHeight: 48, borderRadius: 10, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.panel, paddingHorizontal: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  presetLabel: { color: colors.muted, fontSize: 13 },
  presetValue: { color: colors.text, fontSize: 14, fontWeight: '700' },
  presetList: { gap: 6 },
  presetOption: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 12, borderRadius: 8, backgroundColor: colors.panel, borderWidth: 1, borderColor: colors.border },
  presetSelected: { borderColor: colors.accent },
  guidanceLabel: { color: colors.text, fontSize: 13, fontWeight: '700' },
  guidanceInput: { minHeight: 110, borderRadius: 10, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.panel, color: colors.text, fontSize: 14, padding: 12 },
  guidanceSave: { minHeight: 44, alignSelf: 'flex-start', justifyContent: 'center', paddingHorizontal: 14,
    borderRadius: 9, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.panel },
  guidanceSaveDirty: { borderColor: colors.warning, backgroundColor: colors.accentSoft },
  guidanceSaveText: { color: colors.muted, fontSize: 13, fontWeight: '700' },
  guidanceSaveDirtyText: { color: colors.warning },
  storyButton: { minHeight: 46, minWidth: 112, paddingHorizontal: 14, alignItems: 'center', justifyContent: 'center',
    borderRadius: 10, borderWidth: 1, borderColor: colors.accent, backgroundColor: colors.panel },
  statusRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginBottom: 3 },
  statusDot: { width: 8, height: 8, borderRadius: 4 },
  runningDot: { backgroundColor: colors.ok },
  stoppedDot: { backgroundColor: colors.danger },
  statusText: { color: colors.text, fontSize: 14, fontWeight: '700' },
  paused: { color: colors.warning, fontSize: 13, fontWeight: '700' },
  detailRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 12 },
  detailLabel: { width: 86, color: colors.muted, fontSize: 12 },
  detailValue: { flex: 1, color: colors.text, fontSize: 12 },
  sectionTitle: { color: colors.text, fontSize: 15, fontWeight: '700' },
  quote: { color: colors.muted, fontSize: 13, lineHeight: 19, paddingLeft: 10, borderLeftColor: colors.accent, borderLeftWidth: 2 },
  resetButton: { minHeight: 48, borderRadius: 10, borderWidth: 1, borderColor: colors.danger, alignItems: 'center', justifyContent: 'center' },
  resetText: { color: colors.danger, fontSize: 14, fontWeight: '700' },
  imageButton: {minHeight: 48, borderRadius: 8, paddingHorizontal: 16, justifyContent: 'center', alignSelf: 'flex-start', backgroundColor: colors.accentSoft, borderWidth: 1, borderColor: colors.border},
  disabled: {opacity: 0.45},
  caption: {color: colors.muted, fontSize: 13, marginTop: 6},
  error: {color: colors.danger, fontSize: 13, marginTop: 6},
});
