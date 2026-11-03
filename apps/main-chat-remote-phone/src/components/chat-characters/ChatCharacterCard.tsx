import React from 'react';
import {Alert, ScrollView, Text, View} from 'react-native';
import type {ChatCharacter, CharacterJob, CharacterProvider, CharacterVoiceRemoval, SavedCharacterVoice, VoiceOrganizationPatch} from '../../api/types';
import type {ChatCharactersApi} from '../../hooks/useChatCharacters';
import {characterDraft, characterPatch, draftChanged, type CharacterDraft} from '../../utils/chatCharacterDrafts';
import {usePresentationStyle, useThemedStyles} from '../../styles/ThemeContext';
import {CharacterVoiceEditor} from './CharacterVoiceEditor';
import {CharacterPortraitEditor} from './CharacterPortraitEditor';
import {characterStyles, CharacterButton, CharacterField, CharacterPortrait, CharacterDisclosure, CharacterTextAction} from './characterUi';
import {readableVoiceName} from '../../utils/voiceName';
import {AutomaticCharacterControls} from './AutomaticCharacterControls';

export function ChatCharacterCard({card,api,onBack,onAddedToChat,previewAllowed,onPreview,onBackRequestReady,previewId,onStopPreview}: {
  card:ChatCharacter;api:ChatCharactersApi;onBack:()=>void;onAddedToChat:(name:string)=>void;previewAllowed:boolean;
  onPreview:(candidate:CharacterJob['candidates'][number])=>void;
  previewId:string;onStopPreview:()=>void;
  onBackRequestReady:(handler:(()=>void)|null)=>void;
}) {
  const s=useThemedStyles(characterStyles, 'characterUi');
  const editorial=usePresentationStyle()==='editorial';
  const [tab,setTab]=React.useState<'Character'|'Voice'|'Portrait'>('Character');
  const [base,setBase]=React.useState(card);
  const [draft,setDraft]=React.useState(()=>characterDraft(card));
  const [jobs,setJobs]=React.useState<Record<string,CharacterJob>>({});
  const [submitted,setSubmitted]=React.useState<Record<string,string>>({});
  const [voices,setVoices]=React.useState<SavedCharacterVoice[]>([]);
  const [error,setError]=React.useState('');
  const [confirmation,setConfirmation]=React.useState('');
  const [voiceRefresh,setVoiceRefresh]=React.useState(0);
  const dirty=draftChanged(draft,base);
  const unavailable=api.busy||!api.enabled;
  React.useEffect(()=>{if(!dirty) {setBase(card);setDraft(characterDraft(card));}},[card.revision]);
  React.useEffect(()=>{
    if(!api.enabled)return;
    let alive=true;
    api.client.characterRequest<{voices:typeof voices}>('GET','/api/chat-characters/voices')
      .then(r=>{if(alive)setVoices(r.voices);}).catch(()=>undefined);
    return ()=>{alive=false;};
  },[api.client,api.enabled,jobs.voice?.status,base.voice_id,voiceRefresh]);
  const jobIds=JSON.stringify({...card.jobs,...submitted});
  React.useEffect(()=>{
    if(!api.enabled)return;
    let alive=true, timer:ReturnType<typeof setTimeout>|undefined;
    const poll=async()=>{
      const next:Record<string,CharacterJob>={};
      await Promise.all(Object.entries(JSON.parse(jobIds) as Record<string,string>).map(async([kind,id])=>{
        try {next[kind]=await api.client.characterRequest<CharacterJob>('GET',`/api/chat-characters/jobs/${id}`);} catch {}
      }));
      if(!alive)return;
      setJobs(next);
      if(Object.values(next).some(j=>j.status==='queued'||j.status==='running'))timer=setTimeout(poll,2500);
    };
    void poll();return()=>{alive=false;if(timer)clearTimeout(timer);};
  },[api.client,api.enabled,jobIds]);
  const change=(key:keyof CharacterDraft,value:string)=>setDraft(d=>({...d,[key]:value}));
  const run=async(action:()=>Promise<unknown>)=>{setError('');setConfirmation('');try{await action();}catch(e){setError(e instanceof Error?e.message:'Character action failed.');}};
  const mutate=<T,>(action:string,body:Record<string,unknown>={})=>api.mutate<T>(`/${card.id}/${action}`,{expected_revision:base.revision,...body});
  const apply=async(action:string,body:Record<string,unknown>)=>{
    const saved=await mutate<ChatCharacter>(action,body);setBase(saved);
    if(!dirty)setDraft(characterDraft(saved));
    if(action==='voice')setConfirmation(saved.voice_id?`Assigned ${saved.voice_name||'saved voice'} to ${saved.name}. New replies use it for this character’s dialogue and inner thoughts while Character voices is on. Audio already prepared or playing keeps its current voice.`:'Narrator voice selected.');
  };
  const back=()=>{if(!dirty){onBack();return;}Alert.alert('Unsaved character changes','Discard your changes and return to the library?',[
    {text:'Keep editing',style:'cancel'},{text:'Discard',style:'destructive',onPress:onBack}]);};
  React.useEffect(()=>{onBackRequestReady(back);return()=>onBackRequestReady(null);},[dirty,onBack]);
  const cancel=async(kind:'voice'|'portrait')=>{
    const job=jobs[kind];if(!job)return;
    const saved=await api.mutate<CharacterJob>(`/jobs/${job.id}/cancel`,{expected_revision:base.revision});
    setJobs(previous=>({...previous,[kind]:saved}));
  };
  const remove=()=>Alert.alert('Remove '+base.name+'?',
    'Remove this character from the chat library? Saved voice files and copied NC personas are kept. Current audio keeps playing; future dialogue uses the narrator until added again.',[
      {text:'Cancel',style:'cancel'},
      {text:'Remove character',style:'destructive',onPress:()=>void run(async()=>{
        await mutate('remove');onBack();
      })},
    ]);
  const addToChat=()=>void run(async()=>{
    const conversation_id=api.snapshot?.conversation_id;
    if(!conversation_id)throw new Error('Open a conversation and refresh the library first.');
    const added=await mutate<ChatCharacter>('add-to-chat',{conversation_id});
    onAddedToChat(added.name);
  });
  const generate=async(kind:'voice'|'portrait',body:Record<string,unknown>)=>{
    const job=await mutate<CharacterJob>(`${kind}-jobs`,body);
    setSubmitted(j=>({...j,[kind]:job.id}));setJobs(j=>({...j,[kind]:job}));
  };
  const reloadVoices=async()=>{
    const result=await api.client.characterRequest<{voices:SavedCharacterVoice[]}>('GET','/api/chat-characters/voices');
    setVoices(result.voices);return result.voices;
  };
  const organizeVoice=async(voice:SavedCharacterVoice,patch:VoiceOrganizationPatch)=>{
    const saved=await api.mutate<SavedCharacterVoice>(`/voices/${voice.id}/metadata`,
      {expected_revision:voice.metadata_revision||0,patch});
    setVoices(previous=>previous.map(v=>v.id===saved.id?saved:v));
  };
  const removeVoice=(voiceId:string)=>void run(async()=>{
    const review=await api.client.characterRequest<CharacterVoiceRemoval>('GET',`/api/chat-characters/voices/${voiceId}/removal`);
    const names=review.characters.map(c=>c.name).join(', ');
    Alert.alert(`Remove ${readableVoiceName(review.name)}?`,
      `Delete this saved voice from NC’s library?${names?`\n\nUsed by: ${names}. These characters will use the narrator until you assign another voice.`:''}\n\nAny other NC persona using this recording will also need a replacement. Saved story backups are kept.`,[
        {text:'Cancel',style:'cancel'},
        {text:'Remove voice',style:'destructive',onPress:()=>void run(async()=>{
          if(previewId===voiceId)onStopPreview();
          await api.mutate(`/voices/${voiceId}/remove`,{expected_revision:review.revision});
          setVoices(previous=>previous.filter(v=>v.id!==voiceId));
          setJobs(previous=>Object.fromEntries(Object.entries(previous).map(([kind,job])=>[kind,{...job,
            candidates:job.candidates.map(c=>c.voice_id===voiceId?{...c,available:false}:c)}])));
          const saved=await api.client.characterRequest<ChatCharacter>('GET',`/api/chat-characters/${card.id}`);
          setBase(saved);
          setVoiceRefresh(value=>value+1);
          setConfirmation(`${readableVoiceName(review.name)} removed from the voice library.`);
        })},
      ]);
  });
  return <View style={s.screen}>
    <View style={s.header}>{editorial?<CharacterTextAction label={tab==='Character'?'‹ Library':'‹ Character'}
      onPress={()=>tab==='Character'?back():setTab('Character')}/>:<CharacterButton label="‹ Library" onPress={back}/>}
      <Text style={[s.title,editorial&&{fontFamily:'serif',fontWeight:'400',fontSize:23}]}>{base.name}</Text></View>
    <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={[s.body,editorial&&tab!=='Character'&&{gap:10,paddingTop:4}]}>
      {!editorial?<CharacterButton label="Remove character" disabled={unavailable} onPress={remove}/>:null}
      {!editorial?<CharacterButton label="Add to chat" disabled={unavailable||!api.snapshot?.conversation_id||dirty} onPress={addToChat}/>:null}
      {!editorial||tab==='Character'?<>
      <View style={s.row}><CharacterPortrait client={api.client} path={card.portrait_url_path} name={base.name}/>
        <View style={{flex:1,gap:6}}><Text style={s.title}>{base.name}</Text><Text style={s.subtitle}>{base.role||'Story character'}</Text>
          <Text style={s.badge}>{base.voice_id?`Assigned: ${base.voice_name||'saved voice'}`:'No character voice assigned · narrator playing'}</Text></View></View>
      </>:null}
      {dirty&&card.revision!==base.revision?<Text style={s.error}>This card changed on the desktop. Your draft is kept; discard it to load the latest revision.</Text>:null}
      {!editorial||tab==='Character'?<AutomaticCharacterControls card={card} api={api} dirty={dirty}/>
        :card.automation?.error?<Text accessibilityRole="alert" style={s.error}>{card.automation.error}</Text>:null}
      {tab==='Character'?<View style={s.section}>
        <CharacterField label="Name" value={draft.name} onChange={v=>change('name',v)}/>
        {editorial?<CharacterField label="Character description" multiline value={draft.description} onChange={v=>change('description',v)}/>:null}
        {editorial?<>
          <View style={[s.row,{justifyContent:'space-between'}]}><Text style={s.label}>Voice</Text>
            <CharacterButton label={base.voice_name||'Choose voice'} onPress={()=>setTab('Voice')}/></View>
          <View style={[s.row,{justifyContent:'space-between'}]}><Text style={s.label}>Portrait</Text>
            <CharacterButton label="Change portrait" onPress={()=>setTab('Portrait')}/></View>
        </>:null}
        <CharacterDisclosure label="Personality & details">
        <CharacterField label="Role" value={draft.role} onChange={v=>change('role',v)}/>
        {!editorial?<CharacterField label="Character description" multiline value={draft.description} onChange={v=>change('description',v)}/>:null}
        <CharacterField label="Character and interaction instructions" multiline value={draft.system_prompt} onChange={v=>change('system_prompt',v)}/>
        <Text style={s.subtitle}>Optional. Guides this character's portrayal when Character voices is on. The main persona and narrator keep their own prompts.</Text>
        <Text style={s.subtitle}>Add to chat keeps the original card in its conversation. Copy to NC Personas creates an independent standard persona without activating it.</Text>
        </CharacterDisclosure>
        <CharacterButton label={base.copied_persona_id?'Copied to NC Personas':'Copy to NC Personas'} disabled={unavailable||!!base.copied_persona_id||dirty}
          onPress={()=>Alert.alert('Copy to NC Personas',`Create a separate persona for ${base.name}? Your current persona and conversation stay active.`,[
            {text:'Cancel',style:'cancel'},{text:'Create persona',onPress:()=>void run(()=>apply('persona-copy',{}))}])}/>
      </View>:null}
      {tab==='Voice'?<CharacterVoiceEditor assignedVoiceId={base.voice_id} characterName={base.name} draft={draft} onChange={change} voices={voices} providers={api.snapshot?.providers||[]}
        previewId={previewId} onStopPreview={onStopPreview} onRemove={removeVoice} onOrganize={organizeVoice} onReloadVoices={reloadVoices}
        onCancel={()=>void run(()=>cancel('voice'))} job={jobs.voice} busy={unavailable} previewAllowed={previewAllowed}
        onAssign={id=>void run(()=>apply('voice',{voice_id:id}))}
        onGenerate={(p:CharacterProvider)=>void run(()=>generate('voice',{provider:p.id,model_id:p.model_id,
          voice_description:draft.voice_description,preview_text:draft.preview_text}))}
        onPreview={onPreview} onUse={c=>{if(jobs.voice)void run(()=>apply('voice',{job_id:jobs.voice!.id,candidate_id:c.id}));}}/>:null}
      {tab==='Portrait'?<CharacterPortraitEditor client={api.client} name={base.name} prompt={draft.portrait_prompt}
        onPrompt={v=>change('portrait_prompt',v)} onCancel={()=>void run(()=>cancel('portrait'))} job={jobs.portrait} busy={unavailable} available={!!api.snapshot?.portrait_available}
        onGenerate={style=>void run(()=>generate('portrait',{prompt:draft.portrait_prompt,style}))}
        onUse={c=>{if(jobs.portrait)void run(()=>apply('portrait',{job_id:jobs.portrait!.id,candidate_id:c.id}));}}/>:null}
      {editorial?<CharacterDisclosure label="More actions"><CharacterButton label="Add to chat" disabled={unavailable||!api.snapshot?.conversation_id||dirty} onPress={addToChat}/><CharacterButton label="Remove character" danger disabled={unavailable} onPress={remove}/></CharacterDisclosure>:null}
      {confirmation?<Text accessibilityLiveRegion="polite" style={s.badge}>{confirmation}</Text>:null}
      {error||api.error?<Text accessibilityLiveRegion="polite" style={s.error}>{error||api.error}</Text>:null}
    </ScrollView>
    {dirty?<View style={s.footer}><CharacterButton label="Save changes" primary disabled={unavailable||!draft.name.trim()}
      onPress={()=>void run(async()=>{const saved=await mutate<ChatCharacter>('update',{patch:characterPatch(draft)});setBase(saved);setDraft(characterDraft(saved));})}/>
      <CharacterButton label="Discard changes" disabled={unavailable} onPress={()=>{setBase(card);setDraft(characterDraft(card));setError('');}}/></View>:null}
    {!editorial?<View style={s.tabs}>{(['Character','Voice','Portrait'] as const).map(t=><View key={t} style={s.tab}>
      <CharacterButton label={t} primary={tab===t} onPress={()=>setTab(t)}/></View>)}</View>:null}
  </View>;
}
