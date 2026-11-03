import { usePresentationStyle, useThemedStyles, useThemeColors } from '../../styles/ThemeContext';
import type { ThemeColors } from '../../styles/theme';
import React from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { remoteActionError } from '../../api/envelope';
import type {ChatPhotoDraft} from '../../hooks/useChatPhotoDraft';
import {PendingChatPhoto} from '../PendingChatPhoto';
import { spacing } from '../../styles/theme';
import {AppIcon} from '../app-shell/AppIcon';
import {FullscreenFrameGlow} from './FullscreenFrameGlow';
import {FullscreenShimmerScope} from './FullscreenFrameShimmer';

type Props = {
  visible: boolean;
  includeExit: boolean;
  // Avatar controls use an outside-tap target instead of a Close button.
  dismissOnBackdrop?: boolean;
  disabled: boolean;
  onSendText: (text: string) => Promise<unknown>;
  photoDraft?: ChatPhotoDraft;
  onClose: () => void;
  onExit: () => void;
  liveControls?: React.ReactNode;
  canStopSpeech?: boolean;
  onStopSpeech?: () => void;
};

export function LiveFullscreenActionTray({
  visible,
  includeExit,
  dismissOnBackdrop = false,
  disabled,
  onSendText,
  photoDraft,
  onClose,
  onExit,
  liveControls,
  canStopSpeech,
  onStopSpeech,
}: Props) {
  const styles = useThemedStyles(createStyles);
  const palette = useThemeColors();
  const editorial = usePresentationStyle() === 'editorial';

  const safeAreaInsets = useSafeAreaInsets();
  const [text, setText] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');
  const actionBusy = busy || !!photoDraft?.busy;
  const canSend = !disabled && !actionBusy && (!!text.trim() || !!photoDraft?.photo);
  if (!visible) return null;

  const sendText = async () => {
    const message = text.trim();
    if (!canSend) return;
    setBusy(true);
    setError('');
    try {
      const result = await onSendText(message);
      const messageError = remoteActionError(result, 'Message was not accepted.');
      if (messageError) throw new Error(messageError);
      setText('');
      onClose();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Message could not be sent.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <FullscreenShimmerScope enabled={!editorial&&!disabled&&!actionBusy}>
    <KeyboardAvoidingView
      pointerEvents="box-none"
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      style={StyleSheet.absoluteFill}
    >
      {dismissOnBackdrop ? <Pressable
        accessibilityRole="button" accessibilityLabel="Hide fullscreen controls"
        accessibilityState={{ disabled: busy }} disabled={busy}
        style={StyleSheet.absoluteFill} onPress={onClose} /> : null}
      <View style={[styles.tray, editorial && styles.editorialTray, editorial
        ? { bottom: 0, left: safeAreaInsets.left, right: safeAreaInsets.right,
          paddingBottom: safeAreaInsets.bottom + 12 }
        : { bottom: safeAreaInsets.bottom + 8,
          left: safeAreaInsets.left + 8, right: safeAreaInsets.right + 8 }]}>
        {!editorial ? <FullscreenFrameGlow radius={20} /> : null}
        {editorial ? <View style={styles.editorialHeader}>
          <Text style={styles.editorialEyebrow}>FULLSCREEN CONTROLS</Text>
          <Pressable accessibilityRole="button" accessibilityLabel="Close fullscreen controls"
            accessibilityState={{disabled:busy}} disabled={busy} onPress={onClose}>
            <Text style={styles.editorialDone}>Done</Text>
          </Pressable>
        </View> : null}
        <View style={styles.voiceActions}>
          <View style={styles.liveControls}>{liveControls}</View>
        </View>
        {canStopSpeech ? (
          <Pressable accessibilityRole="button" accessibilityLabel="Stop speech" onPress={onStopSpeech}
            style={[styles.exitButton, editorial && styles.editorialSecondary]}>
            <Text style={[styles.buttonText, editorial && styles.editorialSecondaryText]}>Stop speech</Text>
          </Pressable>
        ) : null}
        <View style={[styles.inputRow, editorial && styles.editorialInputRow]}>
          {!editorial ? <FullscreenFrameGlow radius={11} /> : null}
          <TextInput
            value={text}
            onChangeText={setText}
            editable={!actionBusy && !disabled}
            accessibilityLabel="Message or photo prompt"
            placeholder="Message or photo prompt…"
            placeholderTextColor={editorial ? palette.muted : '#7890a8'}
            style={[styles.input, editorial && styles.editorialInput]}
            multiline
          />
          <View pointerEvents="none" style={styles.inputIcon}><AppIcon name="visual" color={editorial ? palette.accent : '#93afc0'} size={20} /></View>
        </View>
        <PendingChatPhoto draft={photoDraft} disabled={actionBusy}/>
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <View style={styles.actions}>
          <Pressable accessibilityLabel="Send fullscreen message" accessibilityRole="button" accessibilityState={{ busy:actionBusy, disabled:!canSend }} style={[styles.primaryButton, editorial && styles.editorialPrimary]} disabled={!canSend} onPress={() => void sendText()}>
            {!editorial ? <FullscreenFrameGlow shimmer={canSend} /> : null}
            <AppIcon name="paper-plane" color={editorial ? palette.background : '#e7f7ff'} size={19} />
            <Text style={[styles.primaryText, editorial && styles.editorialPrimaryText]}>{busy ? 'Working...' : 'Send'}</Text>
          </Pressable>
          <Pressable accessibilityLabel="Open camera" accessibilityRole="button" accessibilityState={{ disabled: actionBusy || disabled }} style={[styles.button, editorial && styles.editorialSecondary]} disabled={actionBusy || disabled} onPress={() => void photoDraft?.pick('camera')}>
            {!editorial ? <FullscreenFrameGlow shimmer={!actionBusy&&!disabled} /> : null}
            <AppIcon name="camera" color={editorial ? palette.accent : '#e7f7ff'} size={19} />
            <Text style={[styles.buttonText, editorial && styles.editorialSecondaryText]}>Camera</Text>
          </Pressable>
          <Pressable accessibilityLabel="Choose photo" accessibilityRole="button" accessibilityState={{ disabled: actionBusy || disabled }} style={[styles.button, editorial && styles.editorialSecondary]} disabled={actionBusy || disabled} onPress={() => void photoDraft?.pick('gallery')}>
            {!editorial ? <FullscreenFrameGlow shimmer={!actionBusy&&!disabled} /> : null}
            <AppIcon name="visual" color={editorial ? palette.accent : '#e7f7ff'} size={19} />
            <Text style={[styles.buttonText, editorial && styles.editorialSecondaryText]}>Photo</Text>
          </Pressable>
        </View>
        {!editorial && !dismissOnBackdrop ? <Pressable accessibilityLabel="Close fullscreen controls" accessibilityRole="button" accessibilityState={{ disabled: busy }} style={styles.exitButton} disabled={busy} onPress={onClose}>
          <Text style={styles.buttonText}>Close</Text>
        </Pressable> : null}
        {includeExit ? (
          <Pressable accessibilityLabel="Exit fullscreen" accessibilityRole="button" accessibilityState={{ disabled: busy }} style={[styles.exitButton, editorial && styles.editorialExit]} disabled={busy} onPress={onExit}>
            {!editorial ? <FullscreenFrameGlow shimmer={!busy} /> : null}
            <AppIcon name="exit" color={editorial ? palette.accent : '#e7f7ff'} size={20} />
            <Text style={[styles.exitText, editorial && styles.editorialExitText]}>Exit fullscreen</Text>
          </Pressable>
        ) : null}
      </View>
    </KeyboardAvoidingView>
    </FullscreenShimmerScope>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  voiceActions: {flexDirection:'row',alignItems:'flex-start',gap:10},
  liveControls: {flex:1,minWidth:0},
  editorialHeader: { flexDirection:'row', alignItems:'center', justifyContent:'space-between', minHeight:34 },
  editorialEyebrow: { color:colors.accent, fontSize:11, fontWeight:'700', letterSpacing:1.3 },
  editorialDone: { color:colors.accent, fontSize:15, fontWeight:'600', paddingHorizontal:8, paddingVertical:8 },
  tray: {
    backgroundColor: 'rgba(4,18,29,0.97)',
    borderColor: '#3297b5',
    borderRadius: 20,
    borderWidth: 1,
    gap: 12,
    padding: 14,
    position: 'absolute',
  },
  editorialTray: { backgroundColor:colors.panel, borderColor:colors.borderSoft,
    borderRadius:0, borderTopLeftRadius:20, borderTopRightRadius:20,
    borderWidth:0, borderTopWidth:1, gap:18, paddingHorizontal:20, paddingTop:20 },
  inputRow: {
    flexDirection:'row',alignItems:'center',
    backgroundColor: '#0c1725',
    borderColor: '#38536f',
    borderRadius: 11,
    borderWidth: 1,
  },
  editorialInputRow: { backgroundColor:colors.backgroundElevated, borderColor:colors.borderSoft, borderRadius:12 },
  input: {
    flex:1,minWidth:0,color:'#e7f7ff',fontSize:13,
    maxHeight: 110,
    minHeight: 46,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  editorialInput: { color:colors.text, fontSize:16, minHeight:54 },
  inputIcon: {paddingRight:12},
  error: { color: colors.danger, fontSize: 12 },
  actions: { flexDirection: 'row', gap: 8 },
  button: {
    alignItems: 'center',
    flex:1,minWidth:0,flexDirection:'row',gap:6,backgroundColor:'#091c2b',
    borderColor: '#41617f',
    borderRadius: 10,
    borderWidth: 1,
    justifyContent: 'center',
    minHeight: 44,
    paddingHorizontal: 6,
    paddingVertical: spacing.sm,
  },
  buttonText: { color: '#e7f7ff', fontSize: 12, fontWeight: '500',flexShrink:1 },
  primaryButton: {
    alignItems: 'center',
    flex:1,minWidth:0,flexDirection:'row',gap:6,backgroundColor:'#091c2b',
    borderWidth:1,borderColor:'#41617f',borderRadius:10,
    justifyContent: 'center',
    minHeight: 44,
    paddingHorizontal: 6,
    paddingVertical: spacing.sm,
  },
  editorialPrimary: { backgroundColor:colors.accent, borderColor:colors.accent, borderRadius:10 },
  editorialPrimaryText: { color:colors.background, fontSize:15, fontWeight:'700' },
  editorialSecondary: { backgroundColor:'transparent', borderColor:colors.borderSoft, borderRadius:10 },
  editorialSecondaryText: { color:colors.accent, fontSize:14, fontWeight:'600' },
  editorialExit: { backgroundColor:'transparent', borderColor:colors.borderSoft, borderRadius:0,
    borderWidth:0, borderTopWidth:1, justifyContent:'flex-start', paddingHorizontal:4 },
  editorialExitText: { color:colors.accent, fontSize:14, fontWeight:'600' },
  primaryText: { color: '#e7f7ff', fontSize: 12, fontWeight: '500',flexShrink:1 },
  exitButton: {
    alignItems: 'center',
    flexDirection:'row',gap:9,backgroundColor:'#0c2030',
    borderColor: '#608da5',
    borderRadius: 10,
    borderWidth: 1,
    justifyContent: 'center',
    minHeight: 44,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  exitText: { color: '#e7f7ff', fontSize: 12, fontWeight: '500' },
});
