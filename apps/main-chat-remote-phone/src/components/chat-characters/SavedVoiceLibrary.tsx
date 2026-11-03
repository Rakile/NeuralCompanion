import {KeyboardSafeView} from '../KeyboardSafeView';
import {Keyboard} from 'react-native';
import React from 'react';
import {Modal, Pressable, ScrollView, Text, View} from 'react-native';
import type {SavedCharacterVoice, VoiceOrganizationPatch} from '../../api/types';
import {usePresentationStyle,useThemedStyles} from '../../styles/ThemeContext';
import {VOICE_CATEGORIES, voiceGroups} from '../../utils/voiceLibrary';
import {characterStyles, CharacterButton, CharacterField} from './characterUi';

function CategoryPicker({value,onChange,filter=false,disabled=false}: {
  value:string;onChange:(value:string)=>void;filter?:boolean;disabled?:boolean;
}) {
  const s=useThemedStyles(characterStyles, 'characterUi');
  const editorial=usePresentationStyle()==='editorial';
  const [open,setOpen]=React.useState(false);
  const choices=[{id:filter?'all':'',label:filter?'Show all':'No category'},...VOICE_CATEGORIES];
  const label=choices.find(c=>c.id===value)?.label||'No category';
  return <View style={{gap:8}}>
    <Pressable accessibilityRole="button" accessibilityLabel={`Voice category: ${label}`}
      accessibilityState={{expanded:open,disabled}} disabled={disabled}
      style={s.input} onPress={()=>setOpen(!open)}>
      <Text style={s.label}>Category: {label} {open?'▴':'▾'}</Text>
    </Pressable>
    {open?<ScrollView nestedScrollEnabled keyboardShouldPersistTaps="handled" style={{maxHeight:260}}>
      {choices.map(c=><CharacterButton key={c.id} label={c.label} primary={c.id===value}
        disabled={disabled} onPress={()=>{onChange(c.id);setOpen(false);}}/>)}
    </ScrollView>:null}
  </View>;
}

export function SavedVoiceLibrary({voices,search,busy,renderVoice}: {
  voices:SavedCharacterVoice[];search:string;busy:boolean;renderVoice:(voice:SavedCharacterVoice)=>React.ReactNode;
}) {
  const s=useThemedStyles(characterStyles, 'characterUi');
  const editorial=usePresentationStyle()==='editorial';
  const [category,setCategory]=React.useState('all');
  const [limit,setLimit]=React.useState(25);
  React.useEffect(()=>setLimit(25),[category,search]);
  const groups=voiceGroups(voices,category,search);
  return <>
    <CategoryPicker value={category} onChange={setCategory} filter/>
    <Text style={[s.label,editorial&&{fontFamily:'serif',fontSize:18,fontWeight:'400'}]}>★ Favorites</Text>
    {groups.favorites.length?groups.favorites.map(renderVoice):<Text style={s.subtitle}>
      {search?'No favorites match your search.':'Long-press a voice to add it to favorites.'}</Text>}
    <Text style={[s.label,editorial&&{fontFamily:'serif',fontSize:18,fontWeight:'400'}]}>Other voices</Text>
    {!editorial?<Text style={s.subtitle}>Tap Use to assign. Long-press a card to edit its category, favorite, and description.</Text>:null}
    {groups.others.slice(0,limit).map(renderVoice)}
    {!groups.others.length?<Text style={s.subtitle}>No other voices match this filter.</Text>:null}
    {groups.others.length>limit?<CharacterButton label="Show more voices" disabled={busy}
      onPress={()=>setLimit(limit+25)}/>:null}
  </>;
}

export function VoiceDetailsSheet({voice,busy,onClose,onSave,onReload,onRemove}: {
  voice:SavedCharacterVoice;busy:boolean;onClose:()=>void;
  onSave:(voice:SavedCharacterVoice,patch:VoiceOrganizationPatch)=>Promise<void>;
  onReload:()=>Promise<SavedCharacterVoice[]>;onRemove?:(voiceId:string)=>void;
}) {
  const s=useThemedStyles(characterStyles, 'characterUi');
  const editorial=usePresentationStyle()==='editorial';
  const [base,setBase]=React.useState(voice);
  const [category,setCategory]=React.useState(voice.category||'');
  const [favorite,setFavorite]=React.useState(!!voice.favorite);
  const [description,setDescription]=React.useState(voice.description||'');
  const [saving,setSaving]=React.useState(false);
  const [error,setError]=React.useState('');
  const blocked=busy||saving;
  const save=async()=>{
    if(blocked)return;
    setSaving(true);setError('');
    try {await onSave(base,{category,favorite,description});onClose();}
    catch(e){setError(e instanceof Error?e.message:'Could not save voice details.');}
    finally{setSaving(false);}
  };
  const reload=async()=>{
    setSaving(true);setError('');
    try {
      const latest=(await onReload()).find(v=>v.id===voice.id);
      if(!latest)throw new Error('This voice is no longer in the library. Close this editor and refresh.');
      setBase(latest);setCategory(latest.category||'');setFavorite(!!latest.favorite);setDescription(latest.description||'');
    }catch(e){setError(e instanceof Error?e.message:'Could not reload voice details.');}
    finally{setSaving(false);}
  };
  return <Modal onShow={Keyboard.dismiss} visible transparent animationType="slide" onRequestClose={()=>{if(!blocked)onClose();}}>
    <KeyboardSafeView style={s.actionOverlay}>
      <View style={[s.actionSheet,{maxHeight:'90%',flexShrink:1,minHeight:0}]} accessibilityViewIsModal>
        <Text style={s.title}>{voice.name}</Text>
        <ScrollView style={{flexShrink:1}} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" contentContainerStyle={{gap:14}}>
          <Text style={s.subtitle}>Organize this saved voice across your chat characters.</Text>
          <CharacterButton label={favorite?'★ Favorite — remove from favorites':'☆ Add to favorites'}
            primary={favorite} disabled={blocked} onPress={()=>setFavorite(!favorite)}/>
          <CategoryPicker value={category} onChange={setCategory} disabled={blocked}/>
          <CharacterField label="Voice description" multiline value={description} onChange={setDescription} disabled={blocked}/>
          {error?<><Text accessibilityLiveRegion="polite" style={s.error}>{error}</Text>
            <CharacterButton label="Reload voice details" disabled={blocked} onPress={()=>void reload()}/>
            <Text style={s.subtitle}>Reload replaces these unsaved edits with the latest saved details.</Text></>:null}
        </ScrollView>
        {editorial&&onRemove?<CharacterButton label="Remove from library" danger disabled={blocked}
          onPress={()=>{onClose();onRemove(base.id);}}/>:null}
        <View style={s.row}>
          <CharacterButton label={saving?'Saving…':'Save voice details'} primary disabled={blocked} onPress={()=>void save()}/>
          <CharacterButton label="Cancel" disabled={blocked} onPress={onClose}/>
        </View>
      </View>
    </KeyboardSafeView>
  </Modal>;
}
