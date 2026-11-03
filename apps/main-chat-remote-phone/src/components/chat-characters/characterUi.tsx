import React from 'react';
import {Image, Pressable, StyleSheet, Text, TextInput, View} from 'react-native';
import Svg, {Path} from 'react-native-svg';
import type {RemoteClient} from '../../api/client';
import {useAuthorizedMediaUrl} from '../../hooks/useAuthorizedMediaUrl';
import {usePresentationStyle, useThemedStyles} from '../../styles/ThemeContext';
import {controlGlyphTypography, type ThemeColors} from '../../styles/theme';

export const characterStyles = (c: ThemeColors) => StyleSheet.create({
  screen:{flex:1, backgroundColor:c.background}, body:{padding:20, gap:18, paddingBottom:28},
  header:{paddingHorizontal:20, paddingVertical:14, gap:10, flexDirection:'row', alignItems:'center'},
  title:{color:c.text, fontSize:26, fontWeight:'800', flexShrink:1}, subtitle:{color:c.muted, fontSize:14, lineHeight:21},
  section:{backgroundColor:c.panel, borderRadius:22, padding:18, gap:14}, row:{flexDirection:'row', alignItems:'center', gap:10, flexWrap:'wrap'},
  voiceTile:{backgroundColor:c.backgroundElevated, borderRadius:16, padding:14, gap:10, borderWidth:1, borderColor:c.border},
  voiceAssigned:{borderColor:c.accent, backgroundColor:c.accentSoft},
  label:{color:c.text, fontSize:15, fontWeight:'700'}, text:{color:c.text, fontSize:16, lineHeight:23},
  input:{color:c.text, backgroundColor:c.backgroundElevated, borderColor:c.border, borderWidth:1, borderRadius:14,
    padding:14, minHeight:48, fontSize:16, textAlignVertical:'top'},
  button:{minHeight:46, borderRadius:14, paddingHorizontal:16, paddingVertical:12, alignItems:'center',
    justifyContent:'center', backgroundColor:c.panelAlt}, primary:{backgroundColor:c.accentSoft},
  buttonText:{color:c.accent, fontSize:15, fontWeight:'700'}, disabled:{opacity:0.4},
  tabs:{flexDirection:'row', gap:6, padding:12, backgroundColor:c.backgroundElevated}, tab:{flex:1},
  selected:{backgroundColor:c.accentSoft}, footer:{padding:14, gap:10, backgroundColor:c.backgroundElevated},
  error:{color:c.danger, fontSize:14, lineHeight:21}, notice:{padding:12, backgroundColor:c.accentSoft, borderRadius:16, gap:6},
  grid:{flexDirection:'row', flexWrap:'wrap', gap:12}, tile:{backgroundColor:c.panel, borderRadius:22, padding:16, gap:10,
    flexGrow:1, flexBasis:'45%', minWidth:145}, listTile:{flexBasis:'100%', flexDirection:'row', alignItems:'center'},
  portrait:{width:84, height:100, borderRadius:16}, placeholder:{alignItems:'center', justifyContent:'center'},
  initial:{fontSize:38, color:c.accent, fontWeight:'700'}, badge:{color:c.accent, fontSize:12, fontWeight:'600'},
  actionOverlay:{flex:1, justifyContent:'flex-end', backgroundColor:'rgba(0,0,0,0.58)', padding:20},
  actionSheet:{backgroundColor:c.panel, borderRadius:22, padding:18, gap:10, marginBottom:8},
  actionDanger:{color:c.danger},
});

export function CharacterButton({label, onPress, disabled=false, primary=false, danger=false}: {
  label:string; onPress:()=>void; disabled?:boolean; primary?:boolean; danger?:boolean;
}) {
  const s=useThemedStyles(characterStyles, 'characterUi');
  return <Pressable accessibilityRole="button" accessibilityLabel={label} disabled={disabled}
    accessibilityState={{disabled}} onPress={onPress} style={[s.button, primary&&s.primary, disabled&&s.disabled]}>
    <Text style={[s.buttonText,label==='+'&&controlGlyphTypography,danger&&s.actionDanger]}>{label}</Text></Pressable>;
}

/** Classic keeps its original children; Editorial exposes secondary controls on demand. */
export function CharacterDisclosure({label,children}: {label:string;children:React.ReactNode}) {
  const editorial=usePresentationStyle()==='editorial';
  const s=useThemedStyles(characterStyles, 'characterUi');
  const [open,setOpen]=React.useState(false);
  if(!editorial)return <>{children}</>;
  return <>
    <Pressable accessibilityRole="button" accessibilityState={{expanded:open}}
      onPress={()=>setOpen(value=>!value)} style={[s.row,{minHeight:48,justifyContent:'space-between'}]}>
      <Text style={s.label}>{label}</Text><Text style={[s.buttonText,controlGlyphTypography]}>{open?'−':'+'}</Text>
    </Pressable>
    {open?children:null}
  </>;
}

export function CharacterTextAction({label,onPress,disabled=false,selected=false}: {
  label:string;onPress:()=>void;disabled?:boolean;selected?:boolean;
}) {
  const s=useThemedStyles(characterStyles, 'characterUi');
  return <Pressable accessibilityRole="button" accessibilityLabel={label} accessibilityState={{disabled,selected}}
    disabled={disabled} onPress={onPress} style={{minHeight:44,justifyContent:'center',paddingHorizontal:4,
      borderBottomWidth:selected?2:0,borderBottomColor:s.buttonText.color,opacity:disabled?0.4:1}}>
    <Text style={[s.buttonText,{fontWeight:'400'}]}>{label}</Text>
  </Pressable>;
}

export function CharacterPreviewButton({onPress, disabled=false, playing=false}: {onPress:()=>void;disabled?:boolean;playing?:boolean}) {
  const s=useThemedStyles(characterStyles, 'characterUi');
  const editorial=usePresentationStyle()==='editorial';
  const label=playing?'Stop preview':editorial?'Preview':'Preview voice';
  return <Pressable accessibilityRole="button" accessibilityLabel={label} accessibilityState={{disabled}}
    disabled={disabled} onPress={onPress} style={[s.button, {minHeight:38, paddingVertical:7, paddingHorizontal:12,
      flexDirection:'row', gap:7}, editorial&&{backgroundColor:'transparent',borderRadius:0,paddingHorizontal:4}, disabled&&s.disabled]}>
    <Svg width={16} height={16} viewBox="0 0 24 24" accessibilityElementsHidden>
      <Path d={playing?'M5 5h14v14H5Z':'M3 9v6h4l5 4V5L7 9H3Zm12-1a5 5 0 0 1 0 8m3-11a9 9 0 0 1 0 14'}
        fill="none" stroke={s.buttonText.color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"/>
    </Svg>
    <Text style={[s.buttonText,{fontSize:13}]}>{label}</Text>
  </Pressable>;
}
export function CharacterField({label,value,onChange,multiline=false,disabled=false}: {
  label:string; value:string; onChange:(value:string)=>void; multiline?:boolean;disabled?:boolean;
}) {
  const s=useThemedStyles(characterStyles, 'characterUi');
  return <View style={{gap:8}}><Text style={s.label}>{label}</Text><TextInput accessibilityLabel={label}
    value={value} onChangeText={onChange} multiline={multiline} editable={!disabled} maxLength={multiline?5000:160}
    style={[s.input,multiline&&{minHeight:100}]} /></View>;
}
export function CharacterPortrait({client,path,name,large=false}: {client:RemoteClient;path?:string;name:string;large?:boolean}) {
  const s=useThemedStyles(characterStyles, 'characterUi');
  const media=useAuthorizedMediaUrl(client,path||'');
  const size=large?{width:220,height:250}:null;
  return media.url?<Image accessibilityLabel={`${name} portrait`} source={{uri:media.url}} resizeMode="contain" style={[s.portrait,size]}/>
    :<View style={[s.portrait,s.placeholder,size]}><Text style={s.initial}>{name.slice(0,1).toUpperCase()||'◇'}</Text></View>;
}
