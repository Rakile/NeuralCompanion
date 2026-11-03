import React from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import type { PlaybackState } from '../hooks/useAudioQueue';
import type { ChatReadingStyle, PhoneSettings } from '../hooks/usePhoneSettings';
import { useReadingAlong } from '../hooks/useReadingAlong';
import type { ReadingPlayback } from '../hooks/useReadingAlong';
import type { ChatMessage } from '../api/types';
import { useReducedMotion } from '../hooks/useReducedMotion';
import { useThemedStyles, useThemeColors, usePresentationStyle } from '../styles/ThemeContext';
import { controlGlyphTypography, type ThemeColors } from '../styles/theme';
import { ChatFeed } from './ChatFeed';
import {ComposerControls, type Composer} from './Composer';
import {ChatControlsOverlay} from './ChatControlsOverlay';
import { LiveFullscreenSlider } from './live-fullscreen/LiveFullscreenSlider';

type Props = React.ComponentProps<typeof ChatFeed> & {
  playback: PlaybackState; scope: string; visible: boolean; canReplay: boolean;
  automatedUserPlayback?: ReadingPlayback;
  settings: Pick<PhoneSettings, 'chatReadAlong' | 'chatBionicReading' | 'chatReadingAutoScroll' | 'chatFontSize' | 'chatReadingStyle' | 'retainedChatMessages' | 'showPlaybackRail'>;
  onSettingsChange: (change: Partial<PhoneSettings>) => void;
  onControl: (action: string) => Promise<void>;
  composer: React.ReactElement<React.ComponentProps<typeof Composer>>;
  onOpenResponseControls?: () => void;
  onGenerateVisual?: () => void;
  onVisualOptions?: () => void;
  visualDisabled?: boolean;
};

/** This view observes playback. All audio commands still belong to App's existing dispatcher. */
export function ReadingConversation({ playback, automatedUserPlayback, scope, visible, canReplay, settings, onSettingsChange, onControl, composer,
  onOpenResponseControls, onGenerateVisual, onVisualOptions, visualDisabled, ...feed }: Props) {
  const styles = useThemedStyles(createStyles, 'ReadingConversation');
  const editorial = usePresentationStyle() === 'editorial';
  const reducedMotion = useReducedMotion();
  const [controlsOpen, setControlsOpen] = React.useState(false);
  const [railHeight, setRailHeight] = React.useState(0);
  const railVisible = editorial && settings.showPlaybackRail !== false;
  const bottomInset = railVisible ? railHeight : 0;
  const closeControls = React.useCallback(() => setControlsOpen(false), []);
  React.useEffect(() => { closeControls(); }, [scope, visible, closeControls]);
  const userOperation = feed.automatedUserText ? automatedUserPlayback?.activeReplyId : null;
  const readingPlayback = userOperation ? automatedUserPlayback! : playback;
  // The existing automated-user preview is display-only until its normal
  // submission. Put it in the shared list so Follow voice uses the same layout.
  const readingMessages = React.useMemo<ChatMessage[]>(() => userOperation ? [...feed.messages, {
    id:`continuous-user:${userOperation}`,index:(feed.messages.at(-1)?.index ?? -1)+1,role:'user',
    phone_request_id:userOperation,content:feed.automatedUserText || '',display_name:'You · reading aloud',provisional:true,
  }] : feed.messages, [feed.messages, feed.automatedUserText, userOperation]);
  const reading = useReadingAlong({ playback:readingPlayback, scope, visible, enabled: settings.chatReadAlong, messages: readingMessages });
  const [detached, setDetached] = React.useState(false);
  const [followRequest, setFollowRequest] = React.useState(0);
  React.useEffect(() => { setDetached(false); setFollowRequest(n => n + 1); }, [scope]);
  const tracking = !!reading.cursor && ['reading', 'paused', 'waiting'].includes(reading.status);
  const follow = () => { setDetached(false); setFollowRequest(n => n + 1); };
  const [busy, setBusy] = React.useState(false), [error, setError] = React.useState('');
  const commandBusy = React.useRef(false), currentScope = React.useRef(scope); currentScope.current = scope;
  React.useEffect(() => { setError(''); }, [scope]);
  const action = readingPlayback.paused ? 'play_speech'
    : userOperation || playback.isPlaying || playback.currentChunk || playback.hasReplyAudio ? 'pause_speech' : 'replay_last_assistant';
  const label = action === 'play_speech' ? 'Play' : action === 'pause_speech' ? 'Pause' : 'Replay';
  const unavailable = !!feed.disabled || busy || (action === 'replay_last_assistant' && !canReplay);
  const play = async () => {
    if (unavailable || commandBusy.current) return;
    commandBusy.current = true; setBusy(true); setError('');
    const owner = scope;
    try { await onControl(action); }
    catch (failure) { if (currentScope.current === owner) setError(failure instanceof Error ? failure.message : 'Playback control failed. Try again.'); }
    finally { commandBusy.current = false; setBusy(false); }
  };
  const skip = async () => {
    if (feed.disabled || commandBusy.current) return;
    commandBusy.current = true; setBusy(true); setError('');
    const owner = scope;
    try { await onControl('skip_speech'); }
    catch (failure) { if (currentScope.current === owner) setError(failure instanceof Error ? failure.message : 'Skip failed. Try again.'); }
    finally { commandBusy.current = false; setBusy(false); }
  };
  const status = readingPlayback.paused ? 'Paused here' : userOperation ? 'Reading your reply' : playback.isPlaying ? 'Reading reply'
    : reading.status === 'waiting' ? 'Waiting for audio' : reading.status === 'finished' ? 'Reply finished' : 'Ready to listen';
  const detail = !settings.chatReadAlong ? 'Read along off' : reading.status === 'unavailable' ? 'Text timing unavailable'
    : !settings.chatReadingAutoScroll ? 'Auto-follow off' : controlsOpen ? 'Auto-follow paused · controls open'
      : detached ? 'Auto-follow paused' : 'Auto-follow on';
  const playbackRail = railVisible ? <View testID="chat-playback-overlay" style={styles.playbackOverlay}
    onLayout={event => setRailHeight(event.nativeEvent.layout.height)}><View style={styles.editorialPlayback}>
        <Text style={styles.editorialStatus} accessibilityLiveRegion="polite">{status}</Text>
        <View style={styles.editorialTransport}>
          <Pressable accessibilityRole="button" accessibilityLabel={`${label} reply audio`} disabled={unavailable}
            accessibilityState={{disabled:unavailable,busy}} onPress={()=>{void play();}}
            style={[styles.editorialPlay,unavailable && styles.disabled]}><Text style={styles.playText}>{label==='Pause'?'Ⅱ':label==='Play'?'▶':'↶'} {label}</Text></Pressable>
          <Pressable accessibilityRole="button" accessibilityLabel="Skip reply audio" disabled={!!feed.disabled || busy || !(playback.hasReplyAudio || playback.currentChunk || playback.isPlaying)}
            onPress={()=>{void skip();}} style={styles.editorialAction}><Text style={styles.editorialActionText}>Skip</Text></Pressable>
          {onGenerateVisual ? <Pressable accessibilityRole="button" accessibilityLabel="Generate Visual Reply"
            accessibilityHint={visualDisabled ? 'Generation unavailable. Hold to open Visual Reply settings.' : 'Hold for Visual Reply settings'}
            accessibilityActions={onVisualOptions ? [{name:'longpress',label:'Visual Reply settings'}] : undefined}
            onAccessibilityAction={event=>{if(event.nativeEvent.actionName==='longpress') onVisualOptions?.();}}
            onPress={()=>{if(!visualDisabled) onGenerateVisual();}}
            onLongPress={onVisualOptions} delayLongPress={450} style={styles.editorialAction}>
            <Text style={[styles.editorialActionText,visualDisabled && styles.disabled]}>Visual</Text></Pressable> : null}
          {onOpenResponseControls ? <Pressable accessibilityRole="button" accessibilityLabel="Open response controls"
            onPress={onOpenResponseControls} style={styles.editorialAction}><Text style={styles.editorialActionText}>More ⋯</Text></Pressable> : null}
        </View>
        {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      </View></View> : null;
  const readingControls = <ReadingControls playback={playback} scope={scope}
    settings={settings} onSettingsChange={onSettingsChange} onFollow={follow} onPlay={play}
    label={label} status={status} detail={detail} unavailable={unavailable} busy={busy} error={error}/>;
  return <View style={styles.surface}>
    <View style={styles.surface}>
      <ChatFeed {...feed} messages={readingMessages} automatedUserText={userOperation ? '' : feed.automatedUserText}
        messageFontSize={settings.chatFontSize} bionicReading={settings.chatBionicReading}
        onMessageFontSizeChange={chatFontSize => onSettingsChange({chatFontSize})} reading={reading.cursor}
        retainedMessages={settings.retainedChatMessages}
        readingStyle={settings.chatReadingStyle}
        bottomInset={bottomInset}
        readingTracking={tracking} followReading={!controlsOpen && settings.chatReadingAutoScroll && !detached}
        followSuspended={controlsOpen}
        preferSpokenFollow={settings.chatReadAlong && settings.chatReadingAutoScroll && !detached}
        readingFollowRequest={followRequest} readingScope={scope} animateReadingScroll={!reducedMotion}
        onReadingDetached={() => setDetached(true)} />
      {playbackRail}
      {settings.chatReadAlong && settings.chatReadingAutoScroll && detached && tracking ? <View pointerEvents="box-none" style={[styles.followRow,{bottom:bottomInset+8}]}>
        <Pressable accessibilityRole="button" onPress={follow} style={styles.followButton}><Text style={styles.followText}>Follow voice</Text></Pressable>
      </View> : null}
      {controlsOpen ? <ChatControlsOverlay onClose={closeControls}>
        <ComposerControls {...composer.props} readingControls={readingControls}/>
      </ChatControlsOverlay> : null}
    </View>
    {React.cloneElement(composer, {
      playbackControls: undefined, controlsExpanded: controlsOpen,
      onControlsExpandedChange: setControlsOpen, controlsInOverlay: true,
      onInputFocus: () => {closeControls(); composer.props.onInputFocus?.();},
      readingControls})}
  </View>;
}

type ControlsProps = Pick<Props, 'playback' | 'scope' | 'settings' | 'onSettingsChange'> & {
  label: string; status: string; detail: string; unavailable: boolean; busy: boolean; error: string;
  onFollow: () => void; onPlay: () => Promise<void>;
};

const readingStyles: readonly {id: ChatReadingStyle; label: string; description: string}[] = [
  {id:'quiet_underline',label:'Quiet underline',description:'A delicate line beneath the spoken word.'},
  {id:'soft_focus',label:'Soft focus',description:'A gentle glow on the spoken word.'},
  {id:'reading_rail',label:'Reading rail',description:'A gentle guide alongside the current line.'},
];

/** Mounted inside Composer's existing drawer; hiding it keeps the reading observer alive. */
export function ReadingControls({playback, scope, settings, onSettingsChange, label, status, detail, unavailable, busy, error,
  onFollow: follow, onPlay: play}: ControlsProps) {
  const styles = useThemedStyles(createStyles, 'ReadingConversation'), colors = useThemeColors();
  const editorial = usePresentationStyle() === 'editorial';
  const [optionsOpen, setOptionsOpen] = React.useState(false);
  const [styleOpen, setStyleOpen] = React.useState(false);
  const selectedStyle = readingStyles.find(item => item.id === settings.chatReadingStyle) || readingStyles[0]!;
  const closeOptions = () => { setOptionsOpen(false); setStyleOpen(false); };
  React.useEffect(() => { closeOptions(); }, [scope]);
  const adjustSize = (amount: number) => onSettingsChange({ chatFontSize: Math.max(14, Math.min(28, settings.chatFontSize + amount)) });
  return <View>
    {editorial ? <View style={styles.playbackRailToggle}>
      <Text style={styles.label}>Show playback rail</Text>
      <Switch accessibilityLabel="Show playback rail" value={settings.showPlaybackRail !== false}
        trackColor={{false:colors.border,true:colors.accentMuted}}
        thumbColor={settings.showPlaybackRail !== false ? colors.accent : colors.muted}
        onValueChange={showPlaybackRail => onSettingsChange({showPlaybackRail})} />
    </View> : null}
    <View style={styles.bar}>
      <View style={styles.row}>
        <View style={styles.toggle}>
          <Switch accessibilityLabel="Read along" value={settings.chatReadAlong}
            trackColor={{false:colors.border,true:colors.accentMuted}} thumbColor={settings.chatReadAlong ? colors.accent : colors.muted}
            onValueChange={value => { onSettingsChange({chatReadAlong:value}); follow(); }} />
          <Text style={styles.label}>Read along</Text>
        </View>
        <View style={styles.toggle}>
          <Switch accessibilityLabel="Bionic reading" value={settings.chatBionicReading}
            trackColor={{false:colors.border,true:colors.accentMuted}} thumbColor={settings.chatBionicReading ? colors.accent : colors.muted}
            onValueChange={chatBionicReading => onSettingsChange({chatBionicReading})} />
          <Text style={styles.label}>Bionic</Text>
        </View>
        <Pressable accessibilityRole="button" accessibilityLabel="Text size and reading options" accessibilityState={{expanded:optionsOpen}}
          onPress={() => setOptionsOpen(value => !value)} style={styles.typeButton}><Text style={styles.typeText}>Aa</Text></Pressable>
      </View>
      <View style={styles.playRow}>
        <Pressable accessibilityRole="button" accessibilityLabel={`${label} reply audio`} accessibilityState={{disabled:unavailable,busy}}
          disabled={unavailable} onPress={() => { void play(); }} style={[styles.playButton,unavailable && styles.disabled]}>
          <Text style={styles.playText}>{busy ? 'Wait…' : label}</Text>
        </Pressable>
        <View style={styles.statusBlock}>
          <Text numberOfLines={1} accessibilityLiveRegion="polite" style={[styles.status,playback.paused && {color:colors.warning}]}>{status}</Text>
          <Text numberOfLines={2} style={styles.detail}>{detail}</Text>
        </View>
      </View>
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
    </View>
    {optionsOpen ? <Modal transparent animationType="fade" onRequestClose={closeOptions}>
      <View style={styles.optionsBackdrop}>
        <Pressable style={StyleSheet.absoluteFill} accessibilityRole="button" accessibilityLabel="Dismiss reading options"
          onPress={closeOptions} />
        <View accessibilityLabel="Reading options" accessibilityViewIsModal style={styles.options}>
      <ScrollView contentContainerStyle={styles.optionsContent}>
      <View style={styles.row}><Text style={styles.label}>Reading options</Text>
        <Pressable accessibilityRole="button" accessibilityLabel="Close reading options" onPress={closeOptions} style={styles.typeButton}><Text style={styles.label}>Done</Text></Pressable></View>
      <View style={styles.styleSection}>
        <Text style={styles.styleHeading}>Reading style</Text>
        <Pressable accessibilityRole="combobox" accessibilityLabel="Reading style"
          accessibilityValue={{text:selectedStyle.label}} accessibilityState={{expanded:styleOpen}}
          onPress={() => setStyleOpen(value => !value)} style={[styles.styleSelect,styleOpen && styles.styleSelected]}>
          <Text style={styles.optionLabel}>{selectedStyle.label}</Text><Text style={styles.chevron}>{styleOpen ? '⌃' : '⌄'}</Text>
        </Pressable>
        {styleOpen ? <View style={styles.styleMenu}>{readingStyles.map(item => (
          <Pressable key={item.id} accessibilityRole="button" accessibilityLabel={item.label}
            accessibilityHint={item.description} accessibilityState={{selected:item.id===settings.chatReadingStyle}}
            onPress={() => { onSettingsChange({chatReadingStyle:item.id}); setStyleOpen(false); }}
            style={[styles.styleChoice,item.id===settings.chatReadingStyle && styles.styleSelected]}>
            <View style={styles.styleCopy}><Text style={styles.label}>{item.label}</Text><Text style={styles.detail}>{item.description}</Text></View>
            {item.id===settings.chatReadingStyle ? <Text style={styles.check}>✓</Text> : null}
          </Pressable>
        ))}</View> : <Text style={styles.detail}>{selectedStyle.description}</Text>}
      </View>
      <LiveFullscreenSlider label="Conversation text" value={settings.chatFontSize} minimum={14} maximum={28} step={1} suffix=" px" touchHeight={40}
        onChange={chatFontSize => onSettingsChange({chatFontSize})} />
      <View style={styles.row}>
        <Pressable accessibilityRole="button" accessibilityLabel="Decrease conversation text size" disabled={settings.chatFontSize <= 14}
          onPress={() => adjustSize(-1)} style={[styles.typeButton,settings.chatFontSize <= 14 && styles.disabled]}><Text style={styles.label}>A<Text style={controlGlyphTypography}>−</Text></Text></Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Increase conversation text size" disabled={settings.chatFontSize >= 28}
          onPress={() => adjustSize(1)} style={[styles.typeButton,settings.chatFontSize >= 28 && styles.disabled]}><Text style={styles.label}>A<Text style={controlGlyphTypography}>+</Text></Text></Pressable>
      </View>
      <View style={styles.row}><Text style={styles.optionLabel}>Auto-scroll with voice</Text>
        <Switch accessibilityLabel="Auto-scroll with voice" value={settings.chatReadingAutoScroll} disabled={!settings.chatReadAlong}
          trackColor={{false:colors.border,true:colors.accentMuted}} thumbColor={settings.chatReadingAutoScroll ? colors.accent : colors.muted}
          onValueChange={value => { onSettingsChange({chatReadingAutoScroll:value}); follow(); }} /></View>
      </ScrollView>
        </View>
      </View>
    </Modal> : null}
  </View>;
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  playbackOverlay:{position:'absolute',bottom:0,left:0,right:0,paddingHorizontal:16,backgroundColor:colors.background,zIndex:1},
  playbackRailToggle:{minHeight:52,paddingHorizontal:14,flexDirection:'row',alignItems:'center',justifyContent:'space-between'},
  editorialPlayback:{paddingTop:8,paddingBottom:6,gap:5,borderBottomWidth:StyleSheet.hairlineWidth,borderColor:colors.borderSoft},
  editorialStatus:{color:colors.muted,fontSize:12},
  editorialTransport:{flexDirection:'row',alignItems:'center',gap:4,flexWrap:'wrap'},
  editorialPlay:{minHeight:44,paddingHorizontal:16,borderRadius:22,backgroundColor:colors.accent,justifyContent:'center',alignItems:'center'},
  editorialAction:{minHeight:44,minWidth:48,flexGrow:1,paddingHorizontal:8,alignItems:'center',justifyContent:'center'},
  editorialActionText:{color:colors.accent,fontSize:13},
  surface: {flex:1},
  bar: {backgroundColor:colors.panel,borderTopWidth:1,borderBottomWidth:1,borderColor:colors.border,paddingHorizontal:14,paddingTop:6,paddingBottom:10,gap:5},
  row: {flexDirection:'row',alignItems:'center',justifyContent:'space-between',gap:6},
  toggle: {flexDirection:'row',alignItems:'center',gap:4,flexShrink:1,minHeight:44},
  label: {color:colors.text,fontSize:14,fontWeight:'700'},
  typeButton: {minHeight:44,minWidth:44,paddingHorizontal:12,borderRadius:12,borderWidth:1,borderColor:colors.border,backgroundColor:colors.panelAlt,alignItems:'center',justifyContent:'center'},
  typeText: {color:colors.text,fontSize:19},
  playRow: {flexDirection:'row',alignItems:'center',gap:12},
  playButton: {minWidth:84,minHeight:44,paddingHorizontal:14,paddingVertical:10,borderRadius:12,backgroundColor:colors.accent,alignItems:'center',justifyContent:'center'},
  playText: {color:colors.background,fontSize:14,fontWeight:'700'},
  statusBlock: {flex:1,gap:2},
  status: {color:colors.text,fontSize:13,fontWeight:'700'},
  detail: {color:colors.muted,fontSize:12},
  disabled: {opacity:.45},
  followRow: {position:'absolute',left:0,right:0,bottom:8,alignItems:'center',zIndex:2},
  followButton: {minHeight:44,paddingHorizontal:16,paddingVertical:11,backgroundColor:colors.panel,borderColor:colors.accent,borderWidth:1,borderRadius:20},
  followText: {color:colors.accent,fontSize:14,fontWeight:'700'},
  optionsBackdrop: {flex:1,justifyContent:'center',padding:20,backgroundColor:'rgba(0,0,0,0.55)'},
  options: {backgroundColor:colors.panel,borderColor:colors.border,borderWidth:1,borderRadius:16,maxHeight:'90%',width:'100%',maxWidth:460,alignSelf:'center',overflow:'hidden'},
  optionsContent: {padding:16,gap:16},
  styleSection: {gap:8},
  styleHeading: {color:colors.muted,fontSize:12,fontWeight:'600'},
  styleSelect: {flexDirection:'row',alignItems:'center',gap:12,minHeight:48,paddingHorizontal:14,borderRadius:12,borderWidth:1,borderColor:colors.border,backgroundColor:colors.panelAlt},
  chevron: {color:colors.accent,fontSize:22},
  styleMenu: {gap:6},
  styleChoice: {flexDirection:'row',alignItems:'center',gap:12,padding:12,minHeight:60,borderRadius:10,borderWidth:1,borderColor:colors.border,backgroundColor:colors.panelAlt},
  styleSelected: {borderColor:colors.accentMuted,backgroundColor:colors.accentSoft},
  styleCopy: {flex:1,gap:4},
  check: {color:colors.accent,fontSize:18},
  optionLabel: {color:colors.text,fontSize:14,flex:1},
  error: {color:colors.danger,fontSize:13},
});
