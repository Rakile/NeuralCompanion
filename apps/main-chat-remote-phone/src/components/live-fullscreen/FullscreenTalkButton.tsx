import React from 'react';
import {Pressable, StyleSheet, Text, View} from 'react-native';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import type {ComposerProps} from '../Composer';
import {FullscreenMicIndicator} from './FullscreenMicIndicator';
import {FullscreenFrameGlow} from './FullscreenFrameGlow';

export type FullscreenTalkProps = Pick<ComposerProps,
  'pendingVoice' | 'disabled' | 'voiceAvailable' | 'recording' | 'busy' | 'liveEnabled' | 'recordingError' | 'onRecordPress'>;

/** Presentation only: both placements use the existing recorder and its state. */
export function FullscreenTalkButton({talk, floating = false}: {talk: FullscreenTalkProps; floating?: boolean}) {
  const insets = useSafeAreaInsets();
  const disabled = talk.liveEnabled || talk.busy || ((talk.disabled || !talk.voiceAvailable) && !talk.recording);
  const label = talk.recording ? 'Recording' : talk.busy ? 'Working…' : 'Talk';
  return <View style={floating ? [styles.floating, {bottom: insets.bottom + 16, right: insets.right + 16}] : styles.inline}>
    <Pressable accessibilityRole="button"
      accessibilityLabel={talk.recording ? 'Send recording' : 'Record a voice message'}
      accessibilityHint={talk.recording ? 'Stop recording and submit your voice message.' : 'Tap to record. Tap again to send.'}
      accessibilityState={{disabled, busy: talk.busy}} disabled={disabled} onPress={talk.onRecordPress}
      style={[styles.button, floating && styles.circle, disabled && styles.disabled]}>
      <FullscreenFrameGlow radius={floating?28:30} shimmer={!floating&&!disabled&&!talk.recording} />
      <FullscreenMicIndicator recording={talk.recording} />
      {!floating ? <Text style={styles.label}>{label}</Text> : null}
    </Pressable>
    {floating ? <Text style={styles.caption}>{label}</Text> : null}
    {floating && talk.recordingError ? <Text accessibilityRole="alert" style={styles.error}>{talk.recordingError}</Text> : null}
  </View>;
}

const styles = StyleSheet.create({
  floating: {position:'absolute',alignItems:'flex-end',maxWidth:240},
  inline: {flex:1,minWidth:0,justifyContent:'center'},
  button: {minHeight:56,minWidth:48,paddingLeft:4,paddingRight:14,paddingVertical:4,borderRadius:30,
    borderWidth:1,borderColor:'#55d6f5',backgroundColor:'rgba(6,25,37,0.88)',
    flexDirection:'row',gap:8,alignItems:'center',justifyContent:'center'},
  circle: {width:56,height:56,borderRadius:28,paddingLeft:0,paddingRight:0},
  label: {color:'#e7f7ff',fontWeight:'600',fontSize:13,flexShrink:1,textAlign:'center'},
  caption: {color:'#e7f7ff',fontSize:12,marginTop:5,paddingHorizontal:8,paddingVertical:3,
    backgroundColor:'rgba(6,25,37,0.88)',borderRadius:8},
  disabled: {opacity:0.45},
  error: {color:'#ffb4b4',backgroundColor:'rgba(6,25,37,0.94)',padding:8,borderRadius:8,marginTop:6,fontSize:12},
});
