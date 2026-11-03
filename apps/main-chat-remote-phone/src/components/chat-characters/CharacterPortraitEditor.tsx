import React from 'react';
import {Text, View} from 'react-native';
import type {RemoteClient} from '../../api/client';
import type {CharacterJob} from '../../api/types';
import {useThemedStyles} from '../../styles/ThemeContext';
import {characterStyles, CharacterButton, CharacterField, CharacterPortrait, CharacterDisclosure} from './characterUi';

export function CharacterPortraitEditor({client,name,prompt,onPrompt,job,busy,available,onGenerate,onUse,onCancel}: {
  client:RemoteClient;name:string;prompt:string;onPrompt:(value:string)=>void;job?:CharacterJob;busy:boolean;available:boolean;
  onGenerate:(style:string)=>void;onUse:(candidate:CharacterJob['candidates'][number])=>void;onCancel:()=>void;
}) {
  const s=useThemedStyles(characterStyles, 'characterUi');
  const [style,setStyle]=React.useState('natural');
  return <View style={s.section}><Text style={s.label}>Create a portrait</Text>
    <Text style={s.subtitle}>Uses your desktop’s Visual Reply provider. Review the image, then choose Use portrait.</Text>
    <CharacterField label="Portrait prompt" multiline value={prompt} onChange={onPrompt}/>
    <CharacterDisclosure label="Portrait style"><View style={s.row}>{['natural','painted','illustrated'].map(v=><CharacterButton key={v} label={v}
      primary={style===v} onPress={()=>setStyle(v)}/>)}</View></CharacterDisclosure>
    {!available?<Text style={s.subtitle}>Configure a Visual Reply provider on the desktop.</Text>:null}
    <CharacterButton label="Generate portrait" primary disabled={!available||busy||!prompt.trim()||job?.status==='queued'||job?.status==='running'} onPress={()=>onGenerate(style)}/>
    {job?<Text style={job.error?s.error:s.subtitle}>{job.error||`Generation: ${job.status}`}</Text>:null}
      {job&&(job.status==='queued'||job.status==='running')?<CharacterButton label="Cancel generation" disabled={busy} onPress={onCancel}/>:null}
    {job?.candidates.map(c=><View key={c.id} style={{gap:12,alignItems:'center'}}>
      <CharacterPortrait client={client} path={c.url_path} name={name} large/>
      <CharacterButton label="Use portrait" primary disabled={busy} onPress={()=>onUse(c)}/>
    </View>)}
  </View>;
}
