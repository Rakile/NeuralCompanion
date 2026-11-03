import React from 'react';
import {Pressable, Text, View} from 'react-native';
import type {CharacterDraft} from '../../utils/chatCharacterDrafts';
import type {CharacterJob, CharacterProvider, SavedCharacterVoice, VoiceOrganizationPatch} from '../../api/types';
import {usePresentationStyle,useThemedStyles} from '../../styles/ThemeContext';
import {characterStyles, CharacterButton, CharacterField, CharacterPreviewButton, CharacterDisclosure, CharacterTextAction} from './characterUi';
import {readableVoiceName} from '../../utils/voiceName';

import {SavedVoiceLibrary, VoiceDetailsSheet} from './SavedVoiceLibrary';
import {VOICE_CATEGORIES} from '../../utils/voiceLibrary';
type Voice = SavedCharacterVoice;
export function CharacterVoiceEditor({draft,onChange,voices,providers,job,busy,previewAllowed,onAssign,onGenerate,onPreview,onUse,onCancel,assignedVoiceId,characterName,previewId,onStopPreview,onRemove,onOrganize,onReloadVoices}: {
  draft:CharacterDraft;onChange:(key:keyof CharacterDraft,value:string)=>void;voices:Voice[];providers:CharacterProvider[];
  assignedVoiceId:string;characterName:string;job?:CharacterJob;busy:boolean;previewAllowed:boolean;onAssign:(id:string)=>void;
  onGenerate:(provider:CharacterProvider)=>void;onPreview:(candidate:CharacterJob['candidates'][number])=>void;
  onUse:(candidate:CharacterJob['candidates'][number])=>void;onCancel:()=>void;
  previewId:string;onStopPreview:()=>void;onRemove:(voiceId:string)=>void;
  onOrganize:(voice:Voice,patch:VoiceOrganizationPatch)=>Promise<void>;onReloadVoices:()=>Promise<Voice[]>;
}) {
  const s=useThemedStyles(characterStyles, 'characterUi');
  const editorial=usePresentationStyle()==='editorial';
  const [view,setView]=React.useState<'library'|'create'>('library');
  const [search,setSearch]=React.useState('');
  const [organizing,setOrganizing]=React.useState<Voice|null>(null);
  const [providerIndex,setProviderIndex]=React.useState(0);
  const namedVoices=React.useMemo(()=>{
    const counts=new Map<string,number>();
    return voices.map(voice=>{
      const name=readableVoiceName(voice.name), count=(counts.get(name)||0)+1;
      counts.set(name,count);
      return {...voice,name:count===1?name:`${name} (${count})`};
    });
  },[voices]);
  const assigned=namedVoices.find(v=>v.id===assignedVoiceId);
  const provider=providers[providerIndex]||providers[0];
  const elevenlabs=provider?.id==='elevenlabs';
  const descriptionLength=draft.voice_description.trim().length;
  const dialogueLength=draft.preview_text.trim().length;
  const validSample=!elevenlabs||(descriptionLength>=20&&descriptionLength<=1000&&dialogueLength>=100&&dialogueLength<=1000);
  const preview=(candidate:CharacterJob['candidates'][number])=>{
    const id=candidate.voice_id||candidate.id;
    const playing=previewId===id;
    return <CharacterPreviewButton playing={playing}
      disabled={!playing&&(!candidate.url_path||candidate.available===false||!previewAllowed||busy)}
      onPress={()=>playing?onStopPreview():onPreview({...candidate,id})}/>;
  };
  return <>
    {editorial?<View style={s.row}>
      <CharacterTextAction label="Saved voices" selected={view==='library'} onPress={()=>setView('library')}/>
      <CharacterTextAction label="Create voice" selected={view==='create'} onPress={()=>setView('create')}/>
    </View>:null}
    {editorial&&view==='library'&&job?<View style={s.row}>
      <Text accessibilityLiveRegion="polite" style={job.error?s.error:s.subtitle}>{job.error||'Voice generation: '+job.status}</Text>
      <CharacterButton label="View candidates" onPress={()=>setView('create')}/>
      {job.status==='queued'||job.status==='running'?<CharacterButton label="Cancel generation" disabled={busy} onPress={onCancel}/>:null}
    </View>:null}
    {editorial?<Pressable disabled={busy||!assigned} onLongPress={()=>assigned&&setOrganizing(assigned)} delayLongPress={450}
      style={[s.row,{justifyContent:'space-between',paddingVertical:4}]}>
      <Text style={[s.subtitle,{flex:1}]}>{assigned?.name||'Narrator'}</Text>
      {assigned?.url_path?preview({id:assigned.id,url_path:assigned.url_path}):null}
      {!previewAllowed?<Text style={s.subtitle}>Preview after playback.</Text>:null}
    </Pressable>:<>
    <Pressable style={s.section} disabled={busy||!assigned} onLongPress={()=>assigned&&setOrganizing(assigned)} delayLongPress={450}><Text style={s.label}>Assigned voice</Text>
      <Text style={s.subtitle}>{assigned?.name||'Narrator / no saved character voice'}</Text>
      {assigned?.url_path?preview({id:assigned.id,url_path:assigned.url_path}):null}
      {!previewAllowed?<Text style={s.subtitle}>Listen when the reply finishes and Live Mode is off.</Text>:null}
    </Pressable>
    </>}
    <View style={[s.section,editorial&&{padding:0,gap:10},editorial&&view!=='library'&&{display:'none'}]}>{!editorial?<Text style={s.label}>Use a saved voice</Text>:null}
      {!editorial?<Text style={s.subtitle}>Clearly attributed dialogue and inner thoughts use this voice while the character toggle is on. Narration keeps your normal voice.</Text>:null}
      <CharacterField label="Search voices" value={search} onChange={setSearch}/>
      {editorial?<CharacterTextAction label="Use narrator" disabled={busy} onPress={()=>onAssign('')}/>:<CharacterButton label="Use narrator" disabled={busy} onPress={()=>onAssign('')}/>}
      <SavedVoiceLibrary voices={namedVoices} search={search} busy={busy} renderVoice={v=><Pressable key={v.id}
        accessibilityRole="button" accessibilityLabel={`Edit ${v.name} voice details`}
        accessibilityHint="Long-press to organize this voice" delayLongPress={450} disabled={busy}
        onLongPress={()=>setOrganizing(v)} style={[s.voiceTile,assignedVoiceId===v.id&&s.voiceAssigned,editorial&&{paddingHorizontal:0,paddingVertical:10,gap:6}]}>
        <Text style={s.label}>{v.favorite?'★ ':''}{v.name}</Text>
        {v.category?<Text style={s.badge}>{VOICE_CATEGORIES.find(c=>c.id===v.category)?.label}</Text>:null}
        <View style={s.row}>
          <CharacterButton label={assignedVoiceId===v.id?'✓ Assigned':'Use'}
            primary={assignedVoiceId===v.id} disabled={busy} onPress={()=>onAssign(v.id)}/>
          {preview({id:v.id,url_path:v.url_path||''})}
          {editorial?<CharacterButton label="Details" disabled={busy} onPress={()=>setOrganizing(v)}/>
            :<CharacterButton label="Remove" danger disabled={busy} onPress={()=>onRemove(v.id)}/>}
        </View>
        {!editorial&&v.description?<Text style={s.subtitle}>{v.description.slice(0,180)}</Text>:null}
      </Pressable>}/>
    </View>
    <View style={[s.section,editorial&&{paddingHorizontal:0,gap:10},editorial&&view!=='create'&&{display:'none'}]}><Text style={s.label}>Create a voice for {characterName}</Text>
      <Text style={s.subtitle}>{editorial?'Uses provider credits. Preview candidates before assigning a voice.':<>Review the suggested prompt first. Generating may use provider credits. New voices get this character’s name and are saved in NC’s voices folder. Preview a sample, then tap Use this voice to assign it immediately.</>}</Text>
      <CharacterField label="Voice description" multiline value={draft.voice_description} onChange={v=>onChange('voice_description',v)}/>
      <CharacterDisclosure label="Preview dialogue & requirements">
      <CharacterField label="Preview dialogue" multiline value={draft.preview_text} onChange={v=>onChange('preview_text',v)}/>

      {!editorial&&elevenlabs?<Text style={validSample?s.subtitle:s.error}>ElevenLabs requires 20–1000 characters of voice description and 100–1000 characters of preview dialogue. Current: {descriptionLength} / {dialogueLength}.</Text>:null}
      {elevenlabs&&dialogueLength<100?<CharacterButton label="Fill example preview dialogue" onPress={()=>onChange('preview_text',
        `${characterName}, listen carefully. The road ahead is uncertain, but I know we can find our way together. Take a breath, and tell me what you see beyond the next turning.`)}/>:null}
      </CharacterDisclosure>
      {editorial&&elevenlabs?<Text style={validSample?s.subtitle:s.error}>ElevenLabs requires 20–1000 characters of voice description and 100–1000 characters of preview dialogue. Current: {descriptionLength} / {dialogueLength}.</Text>:null}
      <View style={s.row}>{providers.map((p,i)=><CharacterButton key={p.id+p.model_id} label={p.label}
        primary={p===provider} onPress={()=>setProviderIndex(i)}/>)}</View>
      {!provider?<Text style={s.subtitle}>Configure and check a voice-design provider in desktop Voice Studio.</Text>:null}
      {provider?.instruction_mode==='tags'?<Text style={s.subtitle}>Use comma-separated traits: {provider.vocabulary?.join(', ')}</Text>:null}
      <CharacterButton label="Generate voice candidates" primary disabled={busy||!provider||!validSample||job?.status==='queued'||job?.status==='running'}
        onPress={()=>provider&&onGenerate(provider)}/>
      {job?<Text style={job.error?s.error:s.subtitle}>{job.error||`Generation: ${job.status}`}</Text>:null}
      {job&&(job.status==='queued'||job.status==='running')?<CharacterButton label="Cancel generation" disabled={busy} onPress={onCancel}/>:null}
      {!previewAllowed?<Text style={s.subtitle}>Preview after the reply finishes and Live Mode is off. Your story keeps playing.</Text>:null}
      {job?.candidates.map((c,i)=><Pressable key={c.id} disabled={busy||c.available===false} delayLongPress={450}
        onLongPress={()=>{const voice=namedVoices.find(v=>v.id===c.voice_id);if(voice)setOrganizing(voice);}} style={[s.voiceTile,c.voice_id===assignedVoiceId&&s.voiceAssigned]}>
        <Text style={s.label}>{c.name?readableVoiceName(c.name):`${characterName} — Voice ${i+1}`}</Text>
        <Text style={s.subtitle}>{c.available===false?'Removed / unavailable':c.voice_id===assignedVoiceId?'Assigned to this character':c.saved?'Created · saved in NC voices':'Candidate ready'}</Text>
        <View style={s.row}>
          <CharacterButton label="Use this voice" disabled={busy||c.available===false} onPress={()=>onUse(c)}/>
          {preview(c)}
          {c.voice_id&&c.available!==false?<CharacterButton label="Remove" danger disabled={busy} onPress={()=>onRemove(c.voice_id!)}/>:null}
        </View>
      </Pressable>)}
    </View>
    {organizing?<VoiceDetailsSheet key={organizing.id} voice={organizing} busy={busy} onClose={()=>setOrganizing(null)}
      onSave={onOrganize} onReload={onReloadVoices} onRemove={onRemove}/>:null}
  </>;
}
