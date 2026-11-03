import React from 'react';
import {Pressable,StyleSheet,Text,View} from 'react-native';
import type {SoundAsset,SoundChoice} from '../../api/soundscape';
import type {SoundscapeControls} from '../../hooks/useSoundscape';
import {usePresentationStyle,useThemedStyles} from '../../styles/ThemeContext';
import type {ThemeColors} from '../../styles/theme';

export function ChatSoundsMenu({sound,onLibrary,onEditAsset}:{sound:SoundscapeControls;onLibrary:()=>void;onEditAsset:(asset:SoundAsset)=>void}) {
  const styles=useThemedStyles(createStyles, 'ChatSoundsMenu');
  const editorial=usePresentationStyle()==='editorial';
  const [expanded,setExpanded]=React.useState('');
  const [failure,setFailure]=React.useState('');
  React.useEffect(()=>setFailure(''),[sound.choices?.map(c=>c.id).join('|')]);
  const run=(task:()=>Promise<unknown>)=>{setFailure('');void task().catch(error=>setFailure(error instanceof Error?error.message:'Sound operation failed.'));};
  const button=(label:string,action:()=>void,disabled=false,selected=false,danger=false)=><Pressable accessibilityRole="button"
    accessibilityState={{disabled,selected}} disabled={disabled} onPress={action} style={[styles.button,selected&&styles.selected]}>
    <Text style={[styles.buttonText,danger&&styles.danger]}>{label}</Text></Pressable>;
  const choices=sound.choices??[];
  return <View style={styles.root} accessibilityLabel="Sounds for this response">
    <View style={styles.headingRow}><Text style={styles.heading}>Sounds</Text>{button('Library',onLibrary)}</View>
    {!sound.available||!sound.contextAvailable?<Text style={styles.caption}>Connect the updated app and Desktop to use sound feedback.</Text>:null}
    {choices.map(choice=>{
      const asset=sound.assets.find(item=>item.id===choice.asset_id);if(!asset)return null;
      const effect=choice.layer==='effect';
      const effectState=sound.effectPlayback?.choiceId===choice.id?sound.effectPlayback.status:'omitted';
      const omittedReason=sound.effectPlayback?.choiceId===choice.id?sound.effectPlayback.reason:undefined;
      const active=effect?effectState==='playing':!choice.skipped&&sound.state?.[choice.layer as 'ambience'|'music'].asset_id===asset.id;
      const disabled=sound.busy||!sound.available||!sound.contextAvailable;
      const status=asset.discarded?'Excluded from automatic selection':choice.skipped?'Skipped for this reply':effect?
        effectState==='playing'?'Playing once':effectState==='finished'?'Played once':effectState==='stopped'?'Stopped':
          omittedReason==='not_ready'?'Not played · audio was not ready':omittedReason==='late'?'Not played · missed the reply start':'Not played':
        !active?'Not playing':sound.state?.paused?'Paused':asset.loop?'Playing · loop':'Playing';
      return <View key={choice.id} style={styles.sound}>
        <View style={styles.headingRow}><Text style={styles.name}>{asset.title}</Text><Text style={styles.caption}>{effect?'Effect':choice.layer==='music'?'Music':'Ambience'}</Text></View>
        <Text style={styles.caption}>{status}</Text>
        {!editorial||expanded===choice.id?<><View style={styles.tags}>{asset.tags.map(tag=><Text key={tag} style={styles.tag}>{tag}</Text>)}</View>
        {choice.excerpt?<Text numberOfLines={3} style={styles.excerpt}>{choice.excerpt}</Text>:null}
        </>:null}
        <View style={styles.actions}>
          {button(sound.previewId===asset.id&&!sound.previewPaused?'Pause':'Play',()=>run(()=>sound.review(asset)),sound.busy||!sound.available)}
          {sound.previewId===asset.id?button('Stop review',()=>run(()=>sound.stopPreview()),sound.busy):null}
          {button(effect&&!active?(effectState==='finished'?'Finished':effectState==='omitted'?'Not played':'Stopped'):'Skip',()=>run(()=>sound.feedback(choice,'skip')),disabled||!active||Boolean(asset.discarded))}
          {editorial?button(expanded===choice.id?'Less':'More',()=>setExpanded(value=>value===choice.id?'':choice.id)):null}
          {!editorial||expanded===choice.id?<>
          {button(choice.good?'Good match ✓':'Good match',()=>run(()=>sound.feedback(choice,'good')),disabled||!choice.excerpt||Boolean(asset.discarded),choice.good)}
          {button('Edit tags',()=>onEditAsset(asset),disabled)}
          {button(asset.discarded?'Restore sound':'Discard',()=>run(()=>sound.discardAsset(asset,!asset.discarded)),disabled,false,!asset.discarded)}
          </>:null}
        </View>
      </View>;
    })}
    {!choices.length?<Text style={styles.caption}>{sound.state?.enabled?'Sounds appear here when the next spoken reply starts.':'Open Library to enable Soundscape and choose automatic sounds.'}</Text>:null}
    {!editorial&&choices.length?<Text style={styles.caption}>Good match rates this sound for this text. Discard excludes it from future choices; original files are kept.</Text>:null}
    {failure?<Text accessibilityRole="alert" style={styles.danger}>{failure}</Text>:null}
  </View>;
}
const createStyles=(colors:ThemeColors)=>StyleSheet.create({
  root:{padding:16,gap:10,borderTopWidth:1,borderColor:colors.border},headingRow:{flexDirection:'row',justifyContent:'space-between',alignItems:'center',gap:12},
  heading:{fontSize:18,fontWeight:'700',color:colors.text},name:{fontSize:16,fontWeight:'600',color:colors.text,flexShrink:1},
  caption:{fontSize:12,color:colors.muted,lineHeight:18},sound:{backgroundColor:colors.panel,borderColor:colors.border,borderWidth:1,borderRadius:16,padding:14,gap:8},
  tags:{flexDirection:'row',flexWrap:'wrap',gap:6},tag:{fontSize:11,color:colors.muted,backgroundColor:colors.panelAlt,paddingHorizontal:8,paddingVertical:4,borderRadius:6},
  excerpt:{fontSize:13,lineHeight:19,color:colors.muted,borderLeftWidth:2,borderColor:colors.accent,paddingLeft:10},
  actions:{flexDirection:'row',flexWrap:'wrap',gap:8},button:{minHeight:44,minWidth:100,flexGrow:1,flexBasis:'45%',borderWidth:1,borderColor:colors.border,borderRadius:10,paddingHorizontal:10,paddingVertical:12,alignItems:'center',justifyContent:'center'},
  selected:{borderColor:colors.accent,backgroundColor:colors.accentSoft},buttonText:{fontSize:13,fontWeight:'600',color:colors.accent},danger:{color:colors.danger,fontSize:13},
});
