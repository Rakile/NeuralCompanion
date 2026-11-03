import { useThemedStyles, useThemeColors, usePresentationStyle } from '../styles/ThemeContext';
import type { ThemeColors } from '../styles/theme';
import React, { useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import Svg, {Path} from 'react-native-svg';

import { colors, controlGlyphTypography, spacing } from '../styles/theme';
import {QuickMenuActionButton} from './QuickMenuActionButton';
import type {QuickMenuPreferences} from '../utils/quickMenuActions';

const labels: Record<string, string> = {
  interrupt_response: 'Interrupt response',
  pause_speech: 'Pause',
  skip_speech: 'Skip',
  skip_user_reply: 'Skip User',
  regenerate_response: 'Regenerate',
  retry_user_input: 'Retry',
  replay_last_assistant: 'Replay Last',
  replay_chat_session: 'Replay Chat',
};

function TransportGlyph({kind,color}: {kind:string;color:string}) {
  const paths:Record<string,string>={
    Play:'M8 5v14l11-7Z',Pause:'M7 5h3v14H7ZM14 5h3v14h-3Z',
    Skip:'M5 5v14l10-7ZM17 5h3v14h-3Z',
    Force:'M3 5v14l9-7ZM12 5v14l9-7Z',
    Regenerate:'M19 7v5h-5M5 17v-5h5M6 8a7 7 0 0 1 12-2l1 1M18 16A7 7 0 0 1 6 18l-1-1',
    Replay:'M4 5v6h6M4 11a8 8 0 1 1 1 7',
  };
  const line=kind==='Regenerate'||kind==='Replay';
  return <Svg width={26} height={26} viewBox="0 0 24 24" accessibilityElementsHidden>
    <Path d={paths[kind]||paths.Play} fill={line?'none':color} stroke={line?color:'none'} strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round"/>
  </Svg>;
}

type Props = QuickMenuPreferences & {
  grouped?: boolean;
  actions: string[];
  disabled: boolean;
  onControl: (action: string) => Promise<void>;
  wrap?: boolean;
  paused?: boolean;
  onForceContinuation?: () => Promise<void>;
};

export function ControlsBar({ actions, disabled, onControl, wrap = false, paused = false, grouped = false,
  quickMenuActions, onQuickMenuActionsChange, onForceContinuation }: Props) {
  const styles = useThemedStyles(createStyles, 'ControlsBar');
  const palette = useThemeColors();
  const editorial = usePresentationStyle() === 'editorial';
  const [more, setMore] = useState(false);

  const [busyAction, setBusyAction] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    if (disabled) {
      setBusyAction('');
      setError('');
    }
  }, [disabled]);
  const trigger = async (action: string) => {
    if (disabled || busyAction) {
      return;
    }
    setBusyAction(action);
    setError('');
    try {
      if (action === '__force_continuation') await onForceContinuation?.();
      else await onControl(action);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Control action failed.');
    } finally {
      setBusyAction('');
    }
  };

  const button = (action: string) => {
          const label = action === 'pause_speech' && paused ? 'Play' : labels[action] ?? action;
          const busy = busyAction === action;
          const blocked = disabled || Boolean(busyAction);
          return (
            <QuickMenuActionButton action={action} quickMenuActions={quickMenuActions} onQuickMenuActionsChange={onQuickMenuActionsChange}
              accessibilityLabel={label} accessibilityRole="button" accessibilityState={{ busy, disabled: blocked }} key={action} disabled={blocked} style={[styles.button,
                editorial && grouped && ['pause_speech','play_speech','skip_speech'].includes(action) && {height:56,minWidth:72},
                blocked && styles.disabled]} onPress={() => trigger(action)}>
              <Text style={styles.text}>{busy ? 'Working' : label}</Text>
            </QuickMenuActionButton>
          );
        };
  const buttons = actions.map(button);
  if (editorial && grouped) {
    const primary = ['pause_speech', 'play_speech', 'skip_speech'].filter(action => actions.includes(action));
    const secondary = ['regenerate_response', 'replay_last_assistant'].filter(action => actions.includes(action));
    const remaining = actions.filter(action => !primary.includes(action) && !secondary.includes(action));
    const iconButton=(action:string,secondary=false)=>{
      const title=action==='pause_speech'?(paused?'Play':'Pause'):action==='play_speech'?'Play':action==='skip_speech'?'Skip':action==='regenerate_response'?'Regenerate':'Replay';
      const blocked=disabled||Boolean(busyAction);
      const filled=title==='Play'||title==='Pause';
      return <QuickMenuActionButton key={action} action={action} quickMenuActions={quickMenuActions} onQuickMenuActionsChange={onQuickMenuActionsChange}
        accessibilityRole="button" accessibilityLabel={title} accessibilityState={{busy:busyAction===action,disabled:blocked}}
        disabled={blocked} onPress={()=>void trigger(action)} style={[styles.editorialAction,blocked&&styles.disabled]}>
        <View style={[styles.editorialIcon,secondary&&styles.editorialSecondaryIcon,filled&&{backgroundColor:palette.accent}]}>
          <TransportGlyph kind={title} color={filled?palette.background:palette.text}/>
        </View>
        <Text style={styles.editorialLabel}>{busyAction===action?'Working…':title}</Text>
      </QuickMenuActionButton>;
    };
    return <View style={{gap:0}}>
      <View style={styles.editorialTransport}>
        {primary.map(action=>iconButton(action))}
        {onForceContinuation ? <Pressable accessibilityRole="button" accessibilityLabel="Force continuation"
          accessibilityState={{busy:busyAction==='__force_continuation',disabled:disabled||Boolean(busyAction)}}
          disabled={disabled||Boolean(busyAction)} onPress={()=>void trigger('__force_continuation')}
          style={[styles.editorialAction,(disabled||Boolean(busyAction))&&styles.disabled]}>
          <View style={styles.editorialIcon}><TransportGlyph kind="Force" color={palette.text}/></View>
          <Text style={styles.editorialLabel}>{busyAction==='__force_continuation'?'Continuing…':'Force\ncontinuation'}</Text>
        </Pressable> : null}
      </View>
      {secondary.length ? <View style={styles.editorialSecondary}>{secondary.map(action=>iconButton(action,true))}</View> : null}
      {remaining.length ? <><Pressable accessibilityRole="button" accessibilityLabel="More response actions"
        accessibilityState={{expanded:more}} onPress={()=>setMore(value=>!value)}
        style={{minHeight:48,justifyContent:'center'}}>
        <Text style={styles.groupTitle}>More actions <Text style={controlGlyphTypography}>{more?'−':'+'}</Text></Text>
      </Pressable>{more ? <View style={[styles.row,styles.wrapped]}>{remaining.map(button)}</View> : null}</> : null}
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
    </View>;
  }
  if (grouped) {
    const audio = new Set(['pause_speech', 'play_speech', 'skip_speech', 'skip_user_reply', 'replay_last_assistant', 'replay_chat_session']);
    const groups = [{ title: 'Reply audio', actions: actions.filter(action => audio.has(action)) },
      { title: 'Current conversation', actions: actions.filter(action => !audio.has(action)) }];
    return <View style={styles.groups}>
      {groups.filter(group => group.actions.length).map(group => <View key={group.title} style={styles.group}>
        <Text accessibilityRole="header" style={styles.groupTitle}>{group.title}</Text>
        <View style={[styles.row, styles.wrapped, styles.groupButtons]}>{group.actions.map(button)}</View>
      </View>)}
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
    </View>;
  }
  return (
    <View style={styles.panel}>
      {wrap ? <View style={[styles.row, styles.wrapped]}>{buttons}</View>
        : <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.scroller} contentContainerStyle={styles.row}>{buttons}</ScrollView>}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  editorialTransport:{flexDirection:'row',alignItems:'flex-start',paddingVertical:14,borderTopWidth:1,borderBottomWidth:1,borderColor:colors.borderSoft},
  editorialSecondary:{flexDirection:'row',alignItems:'center',paddingVertical:10,borderBottomWidth:1,borderColor:colors.borderSoft},
  editorialAction:{flex:1,minWidth:0,alignItems:'center',justifyContent:'flex-start',gap:7,paddingHorizontal:4,minHeight:64},
  editorialIcon:{width:52,height:52,borderRadius:26,alignItems:'center',justifyContent:'center'},
  editorialSecondaryIcon:{height:30},
  editorialLabel:{color:colors.text,fontSize:12,lineHeight:16,textAlign:'center'},
  groups: { gap: 16 },
  group: { gap: 10 },
  groupTitle: { color: colors.text, fontSize: 15, fontWeight: '700' },
  groupButtons: { padding: 0 },
  panel: {
    backgroundColor: colors.background,
    borderBottomColor: colors.border,
    borderBottomWidth: 1,
  },
  scroller: {
    maxHeight: 54,
  },
  row: {
    gap: spacing.sm,
    padding: spacing.sm,
  },
  wrapped: { flexDirection: 'row', flexWrap: 'wrap' },
  button: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    height: 44,
    justifyContent: 'center',
    paddingHorizontal: spacing.md,
  },
  disabled: {
    opacity: 0.35,
  },
  text: {
    color: colors.text,
    fontSize: 13,
    fontWeight: '700',
  },
  error: {
    color: colors.danger,
    fontSize: 12,
    lineHeight: 16,
    paddingBottom: spacing.sm,
    paddingHorizontal: spacing.sm,
  },
});
