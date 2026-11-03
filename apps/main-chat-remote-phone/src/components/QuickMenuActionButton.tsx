import React, {useRef, useState} from 'react';
import {Modal, Pressable, StyleSheet, Switch, Text, View} from 'react-native';
import {usePresentationStyle,useThemedStyles} from '../styles/ThemeContext';
import type {ThemeColors} from '../styles/theme';
import {normalizeQuickMenuActions, QUICK_MENU_ACTIONS} from '../utils/quickMenuActions';
import type {QuickMenuAction, QuickMenuPreferences} from '../utils/quickMenuActions';

type Props = React.ComponentProps<typeof Pressable> & QuickMenuPreferences & {action: string};

/** Configuration gestures never execute the action, even when it is unavailable. */
export function QuickMenuActionButton({action, quickMenuActions, onQuickMenuActionsChange,
  disabled, onPress, onPressIn, children, ...props}: Props) {
  const styles = useThemedStyles(createStyles);
  const editorial = usePresentationStyle() === 'editorial';
  const [editing, setEditing] = useState(false);
  const held = useRef(false);
  const configurable = Boolean(onQuickMenuActionsChange && QUICK_MENU_ACTIONS.includes(action as QuickMenuAction));
  const selected = normalizeQuickMenuActions(quickMenuActions);
  const checked = selected.includes(action as QuickMenuAction);
  const open = () => { if (configurable) { held.current = true; setEditing(true); } };
  return <>
    <Pressable {...props} disabled={Boolean(disabled && !configurable)}
      accessibilityState={{...props.accessibilityState, disabled:Boolean(disabled)}}
      accessibilityHint={configurable ? 'Long press to show or remove this button in the quick menu.' : props.accessibilityHint}
      accessibilityActions={configurable ? [{name:'longpress',label:'Show in quick menu'}] : props.accessibilityActions}
      onAccessibilityAction={event => {
        if (configurable && event.nativeEvent.actionName === 'longpress') open();
        else props.onAccessibilityAction?.(event);
      }}
      delayLongPress={450} onLongPress={configurable ? open : undefined}
      onPressIn={event => {held.current=false;onPressIn?.(event);}}
      onPress={event => {if (!held.current && !disabled) onPress?.(event);}}>{children}</Pressable>
    <Modal visible={editing} transparent animationType="fade" onRequestClose={()=>setEditing(false)}>
      <View style={[styles.backdrop, editorial && styles.editorialBackdrop]}>
        <View style={[styles.card, editorial && styles.editorialSheet]} accessibilityViewIsModal>
          <Text accessibilityRole="header" style={styles.title}>{props.accessibilityLabel || 'Chat control'}</Text>
          <View style={styles.row}>
            <Text style={styles.label}>Show in quick menu</Text>
            <Switch accessibilityLabel="Show in quick menu" value={checked}
              onValueChange={value => onQuickMenuActionsChange?.(value
                ? normalizeQuickMenuActions([...selected,action]) : selected.filter(item=>item!==action))}/>
          </View>
          <Text style={styles.detail}>{editorial ? "A shortcut above the message box." : "A shortcut above the message box. The original button stays in Chat controls."}</Text>
          <Pressable accessibilityRole="button" accessibilityLabel="Done" style={styles.done} onPress={()=>setEditing(false)}>
            <Text style={styles.label}>Done</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  </>;
}
const createStyles=(colors:ThemeColors)=>StyleSheet.create({
  editorialBackdrop:{justifyContent:"flex-end",padding:0},
  editorialSheet:{backgroundColor:colors.background,borderRadius:0,borderWidth:0,borderTopWidth:1,padding:24,paddingBottom:36,gap:20},
  backdrop:{flex:1,backgroundColor:'rgba(0,0,0,0.55)',justifyContent:'center',padding:24},
  card:{backgroundColor:colors.panel,borderColor:colors.border,borderWidth:1,borderRadius:20,padding:20,gap:16},
  title:{color:colors.text,fontSize:20,fontWeight:'700'},
  row:{flexDirection:'row',alignItems:'center',justifyContent:'space-between',gap:12},
  label:{color:colors.text,fontWeight:'700',fontSize:15,flexShrink:1},
  detail:{color:colors.muted,fontSize:14,lineHeight:20},
  done:{alignSelf:'flex-end',minHeight:44,justifyContent:'center',paddingHorizontal:20,
    backgroundColor:colors.accentSoft,borderRadius:10},
});
