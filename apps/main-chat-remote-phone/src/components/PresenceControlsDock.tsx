import React from 'react';
import {BackHandler, Keyboard, Pressable, ScrollView, StyleSheet, Text, View} from 'react-native';
import type {LayoutChangeEvent} from 'react-native';
import type {ComposerProps} from './Composer';
import type {ConversationActionTarget} from '../api/types';
import {AppIcon} from './app-shell/AppIcon';
import {useThemedStyles, useThemeColors} from '../styles/ThemeContext';
import type {ThemeColors} from '../styles/theme';
import {rememberCaptureControl} from '../diagnostics/captureControlTrail';

type Props = {
  mode: 'portrait' | 'companion';
  composer: React.ReactElement<ComposerProps>;
  actions: React.ReactNode;
  navigation: React.ReactNode;
  onOpenChat: () => void;
  onOpenMore: () => void;
  bottomInset: number;
  onCollapsedHeight: (height: number) => void;
  endWaitingTarget?: ConversationActionTarget | null;
  onEndWaiting: (target: ConversationActionTarget) => Promise<void>;
};

/** UI-only drawer. Neither expansion nor collapse changes the media owner/target. */
export function PresenceControlsDock({mode, composer, actions, navigation, onOpenChat, onOpenMore, bottomInset, onCollapsedHeight, endWaitingTarget, onEndWaiting}: Props) {
  const styles = useThemedStyles(createStyles, 'PresenceControlsDock');
  const colors = useThemeColors();
  const [expanded, setExpanded] = React.useState(false);
  const heights = React.useRef({header:54, quick:52});
  const p = composer.props;
  const recordDisabled = p.liveEnabled || p.busy || ((p.disabled || !p.voiceAvailable) && !p.recording);
  const liveDisabled = !p.liveEnabled && (p.busy || p.disabled || !p.voiceAvailable || p.recording);
  const collapse = React.useCallback(() => { Keyboard.dismiss(); setExpanded(false); }, []);
  React.useEffect(() => {
    if (p.transcript?.trim()) setExpanded(true);
  }, [p.transcript]);
  React.useEffect(() => {
    if (!expanded) return;
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => { collapse(); return true; });
    return () => subscription.remove();
  }, [expanded, collapse]);
  React.useEffect(() => {
    onCollapsedHeight(heights.current.header + heights.current.quick + bottomInset + 16);
  }, [bottomInset, onCollapsedHeight]);
  const measure = (part: 'header' | 'quick', event: LayoutChangeEvent) => {
    heights.current[part] = Math.ceil(event.nativeEvent.layout.height);
    onCollapsedHeight(heights.current.header + heights.current.quick + bottomInset + 16);
  };
  return <View testID="presence-controls-dock" style={[styles.dock, {paddingBottom: bottomInset + 8}]}>
    <View onLayout={event => measure('header', event)}>
      <View style={styles.handle} />
      <View style={styles.heading}>
        <Pressable accessibilityRole="button" accessibilityLabel={expanded ? 'Hide controls' : 'Show controls'}
          accessibilityState={{expanded}} onPress={() => expanded ? collapse() : setExpanded(true)} style={styles.disclosure}>
          <Text style={styles.title}>{expanded ? 'Hide controls' : 'Controls'}</Text>
          {p.liveEnabled && p.liveStatus ? <Text numberOfLines={1} accessibilityLiveRegion="polite" style={styles.hint}>{p.liveStatus}</Text>
            : !expanded ? <Text numberOfLines={1} style={styles.hint}>Message · Actions</Text> : null}
          <Text style={styles.chevron}>{expanded ? '⌄' : '⌃'}</Text>
        </Pressable>
        {p.fullscreenAvailable ? <Pressable accessibilityRole="button" accessibilityLabel="Open live full screen"
          onPress={p.onFullscreenPress} style={styles.square}><Text style={styles.chevron}>⛶</Text></Pressable> : null}
      </View>
    </View>
    {/* Keep composer mounted, including its draft/send state, while hidden. */}
    <ScrollView testID="presence-expanded-controls" style={[styles.body, !expanded && styles.hidden]}
      accessibilityElementsHidden={!expanded} importantForAccessibility={expanded ? 'auto' : 'no-hide-descendants'}
      keyboardShouldPersistTaps="handled" contentContainerStyle={styles.bodyContent}>
      {actions}
      {endWaitingTarget ? <Pressable accessibilityRole="button" accessibilityLabel="End waiting" disabled={p.disabled || p.recording || p.busy}
        onPress={() => { void onEndWaiting(endWaitingTarget); }} style={styles.button}><Text style={styles.text}>End waiting</Text></Pressable> : null}
      {composer}
      <View style={styles.tools}>
        <Pressable accessibilityRole="button" accessibilityLabel="Open conversation chat" onPress={onOpenChat} style={styles.button}><Text style={styles.text}>Open chat</Text></Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Open tools" onPress={onOpenMore} style={styles.button}><Text style={styles.text}>More</Text></Pressable>
      </View>
      {navigation}
    </ScrollView>
    <View onLayout={event => measure('quick', event)}>
      <View style={styles.quick}>
        <Pressable accessibilityRole="button" accessibilityLabel={p.recording ? 'Stop voice recording' : 'Record a voice message'}
          accessibilityState={{disabled:recordDisabled,busy:p.busy}} disabled={recordDisabled}
          onPress={() => { if (mode === 'portrait') rememberCaptureControl('portrait_talk'); void p.onRecordPress(); }}
          style={[styles.button, styles.talk, recordDisabled && styles.disabled]}>
          <AppIcon name="voice" size={19} color={p.recording ? colors.danger : colors.accent} />
          <Text style={styles.text}>{p.recording ? 'Send voice' : p.busy ? 'Working…' : 'Talk'}</Text>
        </Pressable>
        <Pressable accessibilityRole="switch" accessibilityLabel="Live Mode"
          accessibilityState={{checked:p.liveEnabled,disabled:liveDisabled}} disabled={liveDisabled}
          onPress={p.onLivePress} style={[styles.button, p.liveEnabled && styles.talk, liveDisabled && styles.disabled]}>
          <Text style={styles.text}>{p.liveEnabled ? 'Stop Live' : 'Start Live'}</Text>
        </Pressable>
        {p.canStopSpeech ? <Pressable accessibilityRole="button" accessibilityLabel="Stop speech" onPress={p.onStopSpeech} style={styles.button}>
          <Text style={styles.text}>Stop speech</Text>
        </Pressable> : null}
      </View>
      {p.recordingError ? <Text accessibilityRole="alert" style={styles.error}>{p.recordingError}</Text> : null}
    </View>
  </View>;
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  // Root sibling of the native video host (inline z=100; fullscreen z=2000).
  dock:{position:'absolute',bottom:0,left:0,right:0,zIndex:150,maxHeight:'90%',backgroundColor:colors.panel,
    borderTopWidth:1,borderColor:colors.border,borderTopLeftRadius:22,borderTopRightRadius:22,paddingTop:8,paddingHorizontal:12},
  handle:{height:4,width:30,borderRadius:4,backgroundColor:colors.muted,alignSelf:'center',marginBottom:6},
  heading:{flexDirection:'row',alignItems:'center',gap:6},
  disclosure:{flex:1,flexDirection:'row',alignItems:'center',gap:8,minHeight:44,paddingHorizontal:4},
  title:{color:colors.text,fontWeight:'700',fontSize:14,flex:1}, hint:{color:colors.muted,fontSize:11,flexShrink:1,maxWidth:'60%'},
  chevron:{color:colors.text,fontSize:20}, square:{minHeight:44,minWidth:44,alignItems:'center',justifyContent:'center'},
  body:{flexShrink:1},bodyContent:{paddingVertical:8,gap:6},hidden:{display:'none'},
  quick:{flexDirection:'row',flexWrap:'wrap',gap:7,paddingTop:6},tools:{flexDirection:'row',gap:7},
  button:{flexGrow:1,flexBasis:80,minHeight:44,borderWidth:1,borderColor:colors.border,borderRadius:12,
    paddingHorizontal:8,paddingVertical:8,alignItems:'center',justifyContent:'center',flexDirection:'row',gap:6},
  talk:{backgroundColor:colors.accentSoft,borderColor:colors.accent},text:{color:colors.text,fontWeight:'700',fontSize:12},
  disabled:{opacity:0.4},error:{color:colors.danger,fontSize:12,paddingTop:4},
});
