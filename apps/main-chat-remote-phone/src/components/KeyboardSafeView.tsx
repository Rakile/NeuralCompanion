import React from 'react';
import {Keyboard, KeyboardAvoidingView, Platform, type KeyboardAvoidingViewProps} from 'react-native';
import {keyboardAvoidingBehavior} from '../utils/keyboardLayout';

/** One owner inside each native form window; the root avoider cannot reach Modals. */
export function KeyboardSafeView({active=true,style,children,...props}:
  Omit<KeyboardAvoidingViewProps,'behavior'|'enabled'> & {active?:boolean}) {
  const [visible,setVisible]=React.useState(()=>Keyboard.isVisible());
  React.useEffect(()=>{
    const show=Keyboard.addListener('keyboardDidShow',()=>setVisible(true));
    const hide=Keyboard.addListener('keyboardDidHide',()=>setVisible(false));
    return ()=>{show.remove();hide.remove();};
  },[]);
  return <KeyboardAvoidingView {...props} style={[{flex:1},style]}
    behavior={keyboardAvoidingBehavior(Platform.OS)} keyboardVerticalOffset={0}
    enabled={active&&(Platform.OS!=='android'||visible)}>{children}</KeyboardAvoidingView>;
}
