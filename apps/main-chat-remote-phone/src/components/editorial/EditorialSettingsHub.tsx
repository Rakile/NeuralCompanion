import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useThemeColors } from '../../styles/ThemeContext';
import { AppIcon } from '../app-shell/AppIcon';
import type { SettingsSection } from '../SettingsPanel';

const destinations = [
  {key:'companion', title:'Companion', detail:'Persona, conversation & presence'},
  {key:'voice', title:'Voice & playback', detail:'Speech, listening & microphone'},
  {key:'look', title:'Appearance', detail:'Design, reading & backgrounds'},
  {key:'tools', title:'Tools', detail:'Connection, storage & diagnostics'},
] as const;

export function EditorialSettingsHub({connected, onSelect}: {connected:boolean; onSelect:(section:SettingsSection)=>void}) {
  const colors = useThemeColors();
  return <View style={styles.hub}>
    <Text style={[styles.title,{color:colors.text}]}>Settings</Text>
    <View style={styles.connection}>
      <View style={[styles.dot,{backgroundColor:connected?colors.ok:colors.warning}]}/>
      <Text style={[styles.detail,{color:colors.muted}]}>{connected?'Desktop connected':'Desktop disconnected'}</Text>
    </View>
    <View style={styles.destinations}>{destinations.map(row=><Pressable key={row.key}
      accessibilityRole="button" accessibilityLabel={row.title}
      onPress={()=>onSelect(row.key)} style={[styles.row,{borderColor:colors.borderSoft}]}>
      <AppIcon name={row.key} size={23} color={colors.accent}/>
      <View style={styles.copy}><Text style={[styles.label,{color:colors.text}]}>{row.title}</Text>
        <Text style={[styles.detail,{color:colors.muted}]}>{row.detail}</Text></View>
      <Text accessibilityElementsHidden style={[styles.chevron,{color:colors.accent}]}>›</Text>
    </Pressable>)}</View>
  </View>;
}
const styles=StyleSheet.create({
  hub:{paddingHorizontal:24,paddingTop:20,paddingBottom:24},
  title:{fontSize:30,fontFamily:'serif',fontWeight:'400'},
  connection:{flexDirection:'row',alignItems:'center',gap:8,marginTop:16},
  dot:{width:8,height:8,borderRadius:4},
  destinations:{marginTop:30},
  row:{flexDirection:'row',alignItems:'center',gap:18,minHeight:90,borderBottomWidth:StyleSheet.hairlineWidth,paddingVertical:18},
  copy:{flex:1,gap:6},
  label:{fontSize:18,fontWeight:'500'},
  detail:{fontSize:13,lineHeight:20},
  chevron:{fontSize:24},
});
