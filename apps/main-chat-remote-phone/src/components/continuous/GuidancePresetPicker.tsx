import React from 'react';
import {Pressable, ScrollView, StyleSheet, Text, TextInput, View} from 'react-native';
import type {GuidancePreset} from '../../api/types';
import {useThemedStyles, usePresentationStyle} from '../../styles/ThemeContext';
import type {ThemeColors} from '../../styles/theme';

type Props = {presets:GuidancePreset[]; value?:string; disabled?:boolean; onChange:(id:string)=>void};
const categoryOf = (preset:GuidancePreset) => preset.category || 'general';

/** Browsing is local; only choosing a preset invokes the existing settings path. */
export function GuidancePresetPicker({presets,value,disabled=false,onChange}:Props) {
  const styles=useThemedStyles(createStyles, 'GuidancePresetPicker');
  const editorial=usePresentationStyle()==='editorial';
  const [search,setSearch]=React.useState('');
  const selected=presets.find(p=>p.id===value);
  const selectedCategory=selected?categoryOf(selected):'general';
  const [category,setCategory]=React.useState(selectedCategory);
  const [open,setOpen]=React.useState<'category'|'preset'|null>(null);
  React.useEffect(()=>{setCategory(selectedCategory);setOpen(null);},[value,selectedCategory]);
  const categories=[...new Map(presets.map(p=>[categoryOf(p),p.category_label || 'General'])).entries()];
  const currentCategory=categories.some(([id])=>id===category)?category:categories[0]?.[0] || 'general';
  const categoryLabel=categories.find(([id])=>id===currentCategory)?.[1] || 'General';
  const current=selected && categoryOf(selected)===currentCategory?selected:undefined;
  const blocked=disabled || !presets.length;
  return <View style={styles.container}>
    {editorial ? <TextInput accessibilityLabel="Search guidance presets" placeholder="Search guidance presets"
      placeholderTextColor={styles.label.color} value={search} onChangeText={value=>{setSearch(value);setOpen('preset');}}
      style={[styles.choice,styles.name]}/> : null}
    <Pressable accessibilityRole="button" accessibilityLabel={`Story type: ${categoryLabel}`}
      accessibilityState={{expanded:open==='category',disabled:blocked}} disabled={blocked}
      onPress={()=>setOpen(open==='category'?null:'category')} style={[styles.choice,blocked&&styles.disabled]}>
      <View style={styles.text}><Text style={styles.label}>Story type</Text><Text style={styles.name}>{categoryLabel}</Text></View>
      <Text style={styles.marker}>{open==='category'?'Close':'Change'}</Text>
    </Pressable>
    {open==='category'?<ScrollView nestedScrollEnabled keyboardShouldPersistTaps="handled" style={styles.list}>
      {categories.map(([id,label])=><Pressable key={id} accessibilityRole="button" accessibilityLabel={`Browse ${label}`}
        accessibilityState={{selected:id===currentCategory,disabled:blocked}} disabled={blocked}
        onPress={()=>{setCategory(id);setOpen('preset');}} style={[styles.option,id===currentCategory&&styles.selected]}>
        <Text style={styles.name}>{label}</Text>
      </Pressable>)}
    </ScrollView>:null}
    <Pressable accessibilityRole="button" accessibilityLabel={`Guidance preset: ${current?.label || 'Choose'}`}
      accessibilityState={{expanded:open==='preset',disabled:blocked}} disabled={blocked}
      onPress={()=>setOpen(open==='preset'?null:'preset')} style={[styles.choice,blocked&&styles.disabled]}>
      <View style={styles.text}><Text style={styles.label}>Preset</Text><Text style={styles.name}>{current?.label || 'Choose a preset'}</Text></View>
      <Text style={styles.marker}>{open==='preset'?'Close':'Change'}</Text>
    </Pressable>
    {open==='preset'?<ScrollView nestedScrollEnabled keyboardShouldPersistTaps="handled" style={styles.list}>
      {presets.filter(p=>categoryOf(p)===currentCategory && (!editorial || `${p.label} ${p.prompt}`.toLowerCase().includes(search.toLowerCase()))).map(p=><Pressable key={p.id} accessibilityRole="button"
        accessibilityLabel={`Use ${p.label} guidance`} accessibilityState={{selected:p.id===value,disabled:blocked}} disabled={blocked}
        onPress={()=>{onChange(p.id);setOpen(null);}} style={[styles.option,p.id===value&&styles.selected]}>
        {editorial ? <View style={styles.text}><Text style={styles.name}>{p.label}</Text><Text numberOfLines={2} style={styles.prompt}>{p.prompt}</Text></View> : <Text style={styles.name}>{p.label}</Text>}<Text style={styles.marker}>{p.id===value?'Selected':'Use'}</Text>
      </Pressable>)}
    </ScrollView>:null}
    {selected?<View style={styles.preview}>
      <Text style={styles.label}>Selected: {selected.label}</Text>
      <Text accessibilityLabel="Premade guidance preview" style={styles.prompt}>{selected.prompt}</Text>
    </View>:null}
  </View>;
}

const createStyles=(c:ThemeColors)=>StyleSheet.create({
  container:{gap:10},choice:{flexDirection:'row',alignItems:'center',gap:12,padding:12,minHeight:56,
    borderWidth:1,borderColor:c.border,borderRadius:10,backgroundColor:c.panelAlt},
  text:{flex:1,gap:4},label:{color:c.muted,fontSize:12},name:{color:c.text,fontWeight:'600',fontSize:14,flexShrink:1},
  marker:{color:c.accent,fontSize:12,fontWeight:'600',marginLeft:'auto'},list:{maxHeight:280},
  option:{minHeight:48,padding:12,marginBottom:6,borderWidth:1,borderColor:c.border,borderRadius:8,
    flexDirection:'row',alignItems:'center',gap:12,backgroundColor:c.panelAlt},
  selected:{borderColor:c.accent,backgroundColor:c.accentSoft},preview:{gap:5},prompt:{color:c.textSecondary,fontSize:13,lineHeight:20},disabled:{opacity:.5},
});
