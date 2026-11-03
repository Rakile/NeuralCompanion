import React, {useEffect} from 'react';
import {BackHandler, Pressable, ScrollView, StyleSheet, Text, View} from 'react-native';
import {useThemedStyles} from '../styles/ThemeContext';
import {controlGlyphTypography, type ThemeColors} from '../styles/theme';

/** Hosted inside the chat area, above its composer; never changes list geometry. */
export function ChatControlsOverlay({children, onClose}: {children: React.ReactNode; onClose: () => void}) {
  const styles = useThemedStyles(createStyles);
  useEffect(() => {
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {onClose(); return true;});
    return () => subscription.remove();
  }, [onClose]);
  return <View style={styles.overlay} onAccessibilityEscape={onClose}>
    <Pressable style={StyleSheet.absoluteFill} accessibilityRole="button"
      accessibilityLabel="Dismiss chat controls" onPress={onClose}/>
    <View style={styles.panel}>
      <View style={styles.heading}>
        <Text accessibilityRole="header" style={styles.title}>Quick controls</Text>
        <Pressable accessibilityRole="button" accessibilityLabel="Close chat controls"
          onPress={onClose} style={styles.close}><Text style={styles.glyph}>×</Text></Pressable>
      </View>
      <ScrollView style={styles.body} keyboardShouldPersistTaps="handled" nestedScrollEnabled>
        {children}
      </ScrollView>
    </View>
  </View>;
}
const createStyles = (colors: ThemeColors) => StyleSheet.create({
  overlay: {...StyleSheet.absoluteFillObject, justifyContent:'flex-end', zIndex:10},
  panel: {maxHeight:'100%', backgroundColor:colors.panel, borderColor:colors.accent,
    borderWidth:1, borderTopLeftRadius:18, borderTopRightRadius:18, overflow:'hidden'},
  heading: {flexDirection:'row', alignItems:'center', justifyContent:'space-between', paddingLeft:16},
  title: {color:colors.text, fontSize:16, fontWeight:'600'},
  close: {minWidth:48, minHeight:48, alignItems:'center', justifyContent:'center'},
  glyph: {...controlGlyphTypography, color:colors.accent},
  body: {flexShrink:1},
});
