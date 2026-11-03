import React from 'react';
import {Pressable,Text,View} from 'react-native';
import {LiveFullscreenSlider} from '../live-fullscreen/LiveFullscreenSlider';
import {useThemeColors} from '../../styles/ThemeContext';

/** Key by remote session, layer and asset to isolate unsaved volume intent. */
export function SoundVolumeControl({label,value,disabled,onApply}: {
  label:string;value:number;disabled:boolean;onApply:(value:number)=>Promise<void>;
}) {
  const colors=useThemeColors();
  const [draft,setDraft]=React.useState<number|null>(null);
  const [saving,setSaving]=React.useState(false);
  const [error,setError]=React.useState('');
  const latest=React.useRef<number|null>(null);
  const pending=React.useRef(false);
  const alive=React.useRef(true);
  React.useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  const apply=async()=>{
    const submitted=latest.current;
    if(disabled||pending.current||submitted===null)return;
    pending.current=true;setSaving(true);setError('');
    try {
      await onApply(submitted);
      // A slow acknowledgement must not erase a newer drag.
      if(alive.current&&latest.current===submitted){latest.current=null;setDraft(null);}
    } catch(failure) {
      if(alive.current)setError(failure instanceof Error?failure.message:'Volume could not be applied.');
    } finally {pending.current=false;if(alive.current)setSaving(false);}
  };
  return <View style={{gap:8}}>
    <LiveFullscreenSlider label={label} value={draft??value} minimum={0} maximum={100} step={5}
      onChange={next=>{latest.current=next;setDraft(next);setError('');}}/>
    {draft!==null?<View style={{flexDirection:'row',alignItems:'center',justifyContent:'space-between',gap:12}}>
      <Text accessibilityLiveRegion="polite" style={{color:colors.muted,fontSize:13}}>{saving?'Applying volume…':'Unsaved volume'}</Text>
      <Pressable accessibilityRole="button" accessibilityLabel={'Apply '+label.toLowerCase()}
        accessibilityState={{disabled:disabled||saving}} disabled={disabled||saving} onPress={()=>void apply()}
        style={{minHeight:44,paddingHorizontal:12,justifyContent:'center',opacity:(disabled||saving)?0.45:1}}>
        <Text style={{color:colors.accent,fontSize:14}}>Apply volume</Text>
      </Pressable>
    </View>:null}
    {error?<Text accessibilityRole="alert" style={{color:colors.danger}}>{error}</Text>:null}
  </View>;
}
