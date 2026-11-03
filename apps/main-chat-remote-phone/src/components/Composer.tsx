import { useThemedStyles, useThemeColors, usePresentationStyle } from '../styles/ThemeContext';
import type { ThemeColors } from '../styles/theme';
import { AppIcon } from './app-shell/AppIcon';
import React, { useEffect, useRef, useState } from 'react';
import { Keyboard, PanResponder, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { colors, controlGlyphTypography, radii, spacing } from '../styles/theme';
import { LiveModeControl } from './LiveModeControl';
import { DismissibleFault } from './DismissibleFault';
import { PendingChatPhoto } from './PendingChatPhoto';
import type { ChatPhotoDraft } from '../hooks/useChatPhotoDraft';
import { SlashCommandMenu } from './SlashCommandMenu';
import { executeSlashCommand, filterSlashCommands, parseComposerText } from '../utils/slashCommands';
import type { CommandResult, SlashCommand } from '../utils/slashCommands';
import type { ComposerDraft } from '../hooks/useComposerDraft';

export type ComposerProps = {
  pendingVoice?:React.ReactNode;
  presenceMode?: boolean;
  draftState?: ComposerDraft;
  onDraftChange?: (update: (draft: ComposerDraft) => ComposerDraft) => void;
  disabled: boolean;
  commands?: SlashCommand[];
  conversationControls?: React.ReactNode;
  readingControls?: React.ReactNode;
  playbackControls?: React.ReactNode;
  controlsExpanded?: boolean;
  onControlsExpandedChange?: (expanded: boolean) => void;
  controlsInOverlay?: boolean;
  commandScopeKey?: string;
  photoAvailable: boolean;
  photoDraft?: ChatPhotoDraft;
  voiceAvailable: boolean;
  recording: boolean;
  busy: boolean;
  recordingError: string;
  liveEnabled: boolean;
  liveStatus: string;
  canStopSpeech?: boolean;
  onStopSpeech?: () => void;
  fullscreenAvailable: boolean;
  transcript?: string;
  onTranscriptConsumed?: () => void;
  onSend: (text: string) => Promise<void>;
  queuedMessage?: boolean;
  onProcessQueued?: () => Promise<void>;
  onRecordPress: () => Promise<void>;
  onLivePress: () => Promise<void>;
  onFullscreenPress: () => void;
  onInputFocus?: () => void;
  onInputBlur?: () => void;
  onPhotoPress: () => void;
};

type ControlsProps = Pick<ComposerProps, 'conversationControls' | 'readingControls' | 'presenceMode'
  | 'liveEnabled' | 'busy' | 'disabled' | 'voiceAvailable' | 'recording' | 'liveStatus' | 'onLivePress'
  | 'canStopSpeech' | 'onStopSpeech' | 'fullscreenAvailable' | 'onFullscreenPress'>;

/** Shared contents: the conversation hosts these in an overlay; other surfaces keep their layout. */
export function ComposerControls(props: ControlsProps) {
  const liveDisabled = !props.liveEnabled && (props.busy || props.disabled || !props.voiceAvailable || props.recording);
  return <>
    {props.conversationControls}
    {props.readingControls}
    {!props.presenceMode ? <LiveModeControl enabled={props.liveEnabled} disabled={liveDisabled}
      available={props.voiceAvailable} status={props.liveStatus} error="" onToggle={props.onLivePress}
      canStopSpeech={props.canStopSpeech} onStopSpeech={props.onStopSpeech}
      onFullscreen={props.fullscreenAvailable ? props.onFullscreenPress : undefined}/> : null}
  </>;
}

export function Composer({ pendingVoice, presenceMode = false, photoDraft, draftState, onDraftChange, conversationControls, readingControls, playbackControls, controlsExpanded: controlledExpanded, onControlsExpandedChange, controlsInOverlay = false, commands = [], commandScopeKey = '', disabled, photoAvailable, voiceAvailable, recording, busy, recordingError, liveEnabled, liveStatus, fullscreenAvailable, transcript = '', onTranscriptConsumed, onSend, queuedMessage = false, onProcessQueued, onRecordPress, onLivePress, onFullscreenPress, onInputFocus, onInputBlur, onPhotoPress, canStopSpeech, onStopSpeech }: ComposerProps) {
  const styles = useThemedStyles(createStyles);
  const colors = useThemeColors();
  const editorial = usePresentationStyle() === 'editorial';
  const [attachmentsOpen, setAttachmentsOpen] = useState(false);
  const [localControlsExpanded, setLocalControlsExpanded] = useState(false);
  const controlsExpanded = controlledExpanded ?? localControlsExpanded;
  const setControlsExpanded = React.useCallback((expanded: boolean) => {
    if (onControlsExpandedChange) onControlsExpandedChange(expanded);
    else setLocalControlsExpanded(expanded);
  }, [onControlsExpandedChange]);
  const controlsGesture = React.useMemo(() => PanResponder.create({
    onMoveShouldSetPanResponderCapture: (_event, gesture) =>
      Math.abs(gesture.dy) > 24 && Math.abs(gesture.dy) > Math.abs(gesture.dx) * 1.5,
    onPanResponderRelease: (_event, gesture) => {
      if (Math.abs(gesture.dy) >= 40 && Math.abs(gesture.dy) > Math.abs(gesture.dx) * 1.5)
        setControlsExpanded(gesture.dy < 0);
    },
  }), [setControlsExpanded]);
  const [localDraft, setLocalDraft] = useState<ComposerDraft>({ text: '', command: null });
  const value = draftState ?? localDraft;
  const changeDraft = onDraftChange ?? setLocalDraft;
  const text = value.text, draft = value.command;
  const setText = (update: React.SetStateAction<string>) => changeDraft(current => ({ ...current,
    text: typeof update === 'function' ? update(current.text) : update }));
  const setDraft = (command: CommandResult | null) => changeDraft(current => ({ ...current, command }));
  const commandRequest = useRef<AbortController | null>(null);
  const cancelCommand = () => {
    commandRequest.current?.abort(); commandRequest.current = null;
    sendInFlight.current = false; setSending(false);
  };
  useEffect(() => {
    cancelCommand(); setSendError('');
    return () => { commandRequest.current?.abort(); commandRequest.current = null; };
  }, [commandScopeKey]);
  const [sendError, setSendError] = useState('');
  const [sending, setSending] = useState(false);
  // A ref closes the gap before React renders the disabled button.
  const sendInFlight = useRef(false);
  const [inputFocused, setInputFocused] = useState(false);
  const [composerHeight, setComposerHeight] = useState(56);
  const recordDisabled = liveEnabled || busy || ((disabled || !voiceAvailable) && !recording);
  useEffect(() => {
    if (disabled) {
      setSendError('');
    }
  }, [disabled]);
  useEffect(() => {
    const next = transcript.trim();
    if (!next) {
      return;
    }
    setText((current) => (current.trim() ? `${current.trim()} ${next}` : next));
    onTranscriptConsumed?.();
  }, [onTranscriptConsumed, transcript]);
  const processQueued = queuedMessage && !photoDraft?.photo && !text.trim() && Boolean(onProcessQueued);
  const parsed = parseComposerText(text);
  const commandMode = parsed.kind === 'command';
  const showCommands = commandMode && commands.length > 0 && !sending && !sendError;
  const sendDisabled = sending || busy || recording || Boolean(photoDraft?.busy) || (disabled && !commandMode) || (!text.trim() && !processQueued && !photoDraft?.photo);
  const send = async (commandText?: string) => {
    const message = commandText ?? text.trim();
    const parsedMessage = parseComposerText(message);
    if ((disabled && parsedMessage.kind === 'chat') || busy || recording || photoDraft?.busy || sendInFlight.current || (!message && !processQueued && !photoDraft?.photo)) {
      return;
    }
    if (parsedMessage.kind === 'command') {
      if (!parsedMessage.name || (parsedMessage.name === 'commands' && !parsedMessage.argument)) {
        setText('/'); setInputFocused(true); setSendError(''); return;
      }
      const controller = new AbortController(); commandRequest.current = controller;
      sendInFlight.current = true; setSending(true); setSendError(''); setDraft(null);
      try {
        const result = await executeSlashCommand(message, commands, controller.signal);
        if (commandRequest.current !== controller || controller.signal.aborted) return;
        if (result) setDraft(result);
        else {
          setText(current => current === text ? '' : current);
          Keyboard.dismiss(); setInputFocused(false);
        }
      } catch (error) {
        if (commandRequest.current === controller && !controller.signal.aborted)
          setSendError(error instanceof Error ? error.message : String(error));
      } finally {
        if (commandRequest.current === controller) cancelCommand();
      }
      return;
    }
    sendInFlight.current = true;
    setSendError('');
    setSending(true);
    try {
      if (processQueued) await onProcessQueued?.();
      else {
        await onSend(parsedMessage.text);
        changeDraft(current => ({
          text: current.text === text ? '' : current.text,
          command: current.command === draft ? null : current.command,
        }));
        Keyboard.dismiss();
        setInputFocused(false);
      }
    } catch (exc) {
      setSendError(exc instanceof Error ? exc.message : 'Message send failed.');
    } finally {
      sendInFlight.current = false;
      setSending(false);
    }
  };
  return (
    <View style={[styles.wrap, editorial && styles.editorialWrap]}>
      {playbackControls}
      {pendingVoice}
      {inputFocused ? <Pressable accessibilityRole="button" accessibilityLabel="Hide keyboard"
        style={styles.hideKeyboard} onPress={() => { Keyboard.dismiss(); setInputFocused(false); }}>
        <Text style={styles.hideKeyboardText}>Hide keyboard</Text>
      </Pressable> : null}
      <DismissibleFault message={sendError}/>
      <PendingChatPhoto draft={photoDraft} disabled={busy || recording || sending}/>
      {controlsExpanded && !controlsInOverlay ? <View {...controlsGesture.panHandlers}>
        {ComposerControls({conversationControls, readingControls, presenceMode, liveEnabled, busy,
          disabled, voiceAvailable, recording, liveStatus, onLivePress, canStopSpeech, onStopSpeech,
          fullscreenAvailable, onFullscreenPress})}
      </View> : null}
      <DismissibleFault message={recordingError}/>
      <Pressable accessibilityRole="button" accessibilityLabel={controlsExpanded ? 'Hide chat controls' : 'Show chat controls'}
        accessibilityHint="Swipe up from the message field to show controls; swipe down to hide."
        accessibilityState={{ expanded: controlsExpanded }} hitSlop={10}
        onPress={() => setControlsExpanded(!controlsExpanded)} style={[styles.controlsHandle,editorial && {height:44}]} {...controlsGesture.panHandlers}>
        {editorial ? <View style={styles.quickHeading}><Text style={styles.quickLabel}>Quick controls</Text>
          <Text style={styles.quickExpandGlyph}>{controlsExpanded ? '−' : '+'}</Text></View>
          : <View style={[styles.handleLine, liveEnabled && { backgroundColor: colors.ok }]} />}
      </Pressable>
      {queuedMessage && !commandMode ? <Text accessibilityLiveRegion="polite" style={styles.queueHint}>
        {processQueued ? 'Message queued — tap amber to send now' : 'Message queued · Send updates your queued message'}
      </Text> : null}
      {commandRequest.current ? <Pressable accessibilityRole="button" accessibilityLabel="Cancel command"
        style={styles.commandButton} onPress={() => { cancelCommand(); setSendError('Command cancelled. Your text is preserved.'); }}>
        <Text style={styles.commandText}>Working… Cancel</Text>
      </Pressable> : null}
      {draft ? <ScrollView style={styles.draft} keyboardShouldPersistTaps="always" nestedScrollEnabled>
        <Text style={styles.commandText}>Draft ready · Not sent</Text>
        {(draft.ideas?.length ? draft.ideas : [draft.draft]).map((value, index) => <View key={index}>
          <Text style={styles.draftText} numberOfLines={3}>{value}</Text>
          <Pressable accessibilityRole="button" accessibilityLabel={draft.ideas?.length ? `Use idea ${index + 1}` : 'Use draft'}
            style={styles.commandButton} onPress={() => {
              setText(value.trimStart().startsWith('/') ? '/' + value.trimStart() : value);
              setDraft(null); setSendError('');
            }}><Text style={styles.commandText}>Use {draft.ideas?.length ? `idea ${index + 1}` : 'draft'} → edit, then Send</Text></Pressable>
        </View>)}
        <Pressable accessibilityRole="button" accessibilityLabel="Discard draft" style={styles.commandButton} onPress={() => setDraft(null)}>
          <Text style={styles.commandText}>Discard draft</Text>
        </Pressable>
      </ScrollView> : null}
      {showCommands && !draft ? <View style={[styles.slashMenuOverlay, { bottom: composerHeight + spacing.md + 6 }]}><SlashCommandMenu commands={filterSlashCommands(text, commands)} busy={sending}
        onChoose={command => {
          if (command.usage?.includes('<')) {
            if (parsed.kind === 'command' && parsed.name === command.name && parsed.argument) void send();
            else { setText(`/${command.name} ${parsed.kind === 'command' ? parsed.argument : ''}`); setSendError(''); }
          }
          else void send(`/${command.name}`);
        }} /></View> : null}
      {editorial && attachmentsOpen ? <View style={styles.attachmentRow}>
        <Pressable accessibilityRole="button" accessibilityLabel="Open camera"
          disabled={disabled || busy || recording || sending || !!photoDraft?.busy || !photoAvailable}
          style={styles.attachmentAction} onPress={()=>{setAttachmentsOpen(false);onPhotoPress();}}>
          <AppIcon name="camera" color={colors.accent} size={22}/><Text style={styles.quickLabel}>Camera</Text></Pressable>
        {photoDraft ? <Pressable accessibilityRole="button" accessibilityLabel="Choose photo"
          disabled={disabled || busy || recording || sending || photoDraft.busy || !photoAvailable}
          style={styles.attachmentAction} onPress={()=>{setAttachmentsOpen(false);void photoDraft.pick('gallery');}}>
          <AppIcon name="visual" color={colors.accent} size={22}/><Text style={styles.quickLabel}>Photo library</Text></Pressable> : null}
        {commands.length ? <Pressable accessibilityRole="button" accessibilityLabel="Show commands"
          style={styles.attachmentAction} onPress={()=>{setAttachmentsOpen(false);setText('/');}}>
          <Text style={styles.commandText}>/</Text><Text style={styles.quickLabel}>Commands</Text></Pressable> : null}
      </View> : null}
      <View style={styles.composer} onLayout={event => setComposerHeight(event.nativeEvent.layout.height)} {...controlsGesture.panHandlers}>
        {editorial ? <Pressable accessibilityRole="button" accessibilityLabel="Add to conversation" accessibilityState={{expanded:attachmentsOpen}}
          style={styles.photoButton} onPress={()=>setAttachmentsOpen(v=>!v)}>
          <Text style={styles.attachmentGlyph}>{attachmentsOpen?'×':'+'}</Text></Pressable> : null}
        <TextInput
          accessibilityLabel="Message"
          value={text}
          onChangeText={value => { setText(value); if (sendError) setSendError(''); }}
          editable={!disabled || commands.length > 0}
          placeholder="Message or /command"
          placeholderTextColor={colors.muted}
          style={styles.input}
          multiline
          onFocus={() => { setInputFocused(true); onInputFocus?.(); }}
          onBlur={() => { setInputFocused(false); onInputBlur?.(); }}
        />
        {!editorial ? <Pressable
          accessibilityLabel="Open camera"
          accessibilityRole="button"
          accessibilityState={{ disabled: disabled || busy || recording || sending || !!photoDraft?.busy || !photoAvailable }}
          disabled={disabled || busy || recording || sending || !!photoDraft?.busy || !photoAvailable}
          style={[styles.photoButton, (disabled || busy || !photoAvailable) && styles.disabled]}
          onPress={onPhotoPress}
        >
          <AppIcon name="camera" color={colors.textSecondary} size={21} />
        </Pressable> : null}
        {photoDraft && !editorial ? <Pressable accessibilityLabel="Choose photo" accessibilityRole="button"
          disabled={disabled || busy || recording || sending || photoDraft.busy || !photoAvailable}
          style={styles.photoButton} onPress={() => void photoDraft.pick('gallery')}>
          <AppIcon name="visual" color={colors.textSecondary} size={21}/>
        </Pressable> : null}
        {!presenceMode ? <Pressable
          accessibilityLabel={recording
            ? 'Stop voice recording'
            : voiceAvailable
              ? 'Record a voice message'
              : 'Speech to text unavailable'}
          accessibilityRole="button"
          accessibilityState={{ disabled: recordDisabled }}
          disabled={recordDisabled}
          style={[styles.micButton, recording && styles.recording, recordDisabled && styles.disabled]}
          onPress={onRecordPress}
        >
          <AppIcon name="voice" color={recording ? colors.danger : colors.textSecondary} size={21} />
        </Pressable> : null}
        <Pressable
          accessibilityLabel={commandMode ? 'Run command' : processQueued ? 'Process queued message now' : 'Send message'}
          accessibilityHint={processQueued ? 'Stops the current reply audio and processes your waiting message.' : undefined}
          accessibilityRole="button"
          accessibilityState={{ busy: sending, disabled: sendDisabled }}
          disabled={sendDisabled}
          style={[styles.sendButton, queuedMessage && !commandMode && styles.queuedSendButton, sendDisabled && styles.disabled]}
          onPress={() => send()}
        >
          <AppIcon name="send" color={colors.background} size={23} />
        </Pressable>
      </View>
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  editorialWrap:{backgroundColor:colors.background,paddingTop:0,gap:0},
  quickHeading:{flexDirection:'row',alignItems:'center',justifyContent:'space-between',width:'100%',paddingHorizontal:4},
  quickLabel:{color:colors.muted,fontSize:12},
  quickExpandGlyph:{color:colors.accent,...controlGlyphTypography},
  attachmentGlyph:{color:colors.accent,...controlGlyphTypography},
  attachmentRow:{flexDirection:'row',flexWrap:'wrap',gap:12,paddingVertical:14,borderTopWidth:StyleSheet.hairlineWidth,borderColor:colors.borderSoft},
  attachmentAction:{minHeight:52,flex:1,minWidth:90,alignItems:'center',justifyContent:'center',gap:8},
  controlsHandle: { height: 20, alignItems: 'center', justifyContent: 'center' },
  handleLine: { width: 32, height: 3, borderRadius: 2, backgroundColor: colors.muted },
  commandButton: { minHeight: 44, justifyContent: 'center', paddingHorizontal: 10 },
  commandText: { color: colors.accent, fontSize: 13, fontWeight: '600' },
  draft: { maxHeight: 200, padding: 10, borderRadius: 12, backgroundColor: colors.panel, marginBottom: 6 },
  draftText: { color: colors.text, fontSize: 13, marginTop: 6 },
  queuedSendButton: { backgroundColor: colors.warning },
  queueHint: { color: colors.warning, fontSize: 12, lineHeight: 17, paddingHorizontal: spacing.sm },
  hideKeyboard: { alignSelf: 'flex-end', minHeight: 44, justifyContent: 'center', paddingHorizontal: spacing.sm },
  hideKeyboardText: { color: colors.accent, fontSize: 13 },
  wrap: {
    backgroundColor: colors.backgroundElevated,
    borderTopColor: colors.borderSoft,
    borderTopWidth: StyleSheet.hairlineWidth,
    gap: spacing.xs,
    padding: spacing.md,
  },
  slashMenuOverlay: { position: 'absolute', left: spacing.md, right: spacing.md, zIndex: 10, elevation: 10 },
  composer: { alignItems: 'center', flexDirection: 'row', gap: 2, padding: 4, borderRadius: 24, backgroundColor: colors.panel, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border },
  voiceDisclosure: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 7,
    minHeight: 44,
    paddingHorizontal: spacing.xs,
  },
  voiceDisclosureActive: { backgroundColor: colors.accentSoft, borderRadius: radii.md },
  voiceDot: { backgroundColor: colors.muted, borderRadius: 999, height: 7, width: 7 },
  voiceDotActive: { backgroundColor: colors.ok },
  voiceDisclosureTitle: { color: colors.textSecondary, fontSize: 11, fontWeight: '800' },
  voiceDisclosureStatus: { color: colors.muted, flex: 1, fontSize: 10 },
  chevron: { color: colors.muted, fontSize: 14, fontWeight: '900' },
  voiceTray: {
    backgroundColor: colors.panel,
    borderColor: colors.borderSoft,
    borderRadius: radii.lg,
    borderWidth: 1,
    gap: spacing.sm,
    padding: spacing.md,
  },
  voiceTrayActive: { borderColor: colors.accentMuted },
  voiceTrayCopy: { gap: 2 },
  liveActions: {
    flexDirection: 'row',
    gap: spacing.xs,
  },
  voiceTrayTitle: { color: colors.text, fontSize: 13, fontWeight: '800' },
  voiceTrayStatus: {
    color: colors.muted,
    fontSize: 11,
    lineHeight: 15,
  },
  liveButton: {
    alignItems: 'center',
    borderColor: colors.border,
    borderRadius: radii.md,
    borderWidth: 1,
    height: 44,
    justifyContent: 'center',
    minWidth: 58,
    paddingHorizontal: spacing.sm,
  },
  liveButtonActive: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.accent,
  },
  input: {
    backgroundColor: colors.panel,
    borderColor: colors.borderSoft,
    borderRadius: radii.lg,
    borderWidth: 0,
    color: colors.text,
    flex: 1,
    fontSize: 16,
    minWidth: 0,
    maxHeight: 96,
    minHeight: 48,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  micButton: {
    alignItems: 'center',
    backgroundColor: 'transparent',
    borderColor: colors.border,
    borderRadius: radii.md,
    borderWidth: 0,
    height: 48,
    justifyContent: 'center',
    width: 44,
  },
  photoButton: {
    alignItems: 'center',
    backgroundColor: 'transparent',
    borderColor: colors.border,
    borderRadius: radii.md,
    borderWidth: 0,
    height: 48,
    justifyContent: 'center',
    width: 44,
  },
  recording: {
    backgroundColor: colors.panelAlt,
    borderColor: colors.danger,
  },
  buttonText: {
    color: colors.text,
    fontSize: 13,
    fontWeight: '700',
  },
  sendButton: {
    alignItems: 'center',
    backgroundColor: colors.accent,
    borderRadius: radii.pill,
    height: 44,
    justifyContent: 'center',
    width: 44,
  },
  disabled: {
    opacity: 0.4,
  },
  sendText: {
    color: colors.background,
    fontSize: 24,
    fontWeight: '500',
    lineHeight: 26,
  },
});
