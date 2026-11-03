import React from 'react';
import {Text,View} from 'react-native';
import type {ChatCharacter} from '../../api/types';
import type {ChatCharactersApi} from '../../hooks/useChatCharacters';
import {usePresentationStyle,useThemedStyles} from '../../styles/ThemeContext';
import {characterStyles,CharacterButton} from './characterUi';

export function AutomaticCharacterControls({card,api,dirty=false}: {
  card:ChatCharacter;api:ChatCharactersApi;dirty?:boolean;
}) {
  const editorial=usePresentationStyle()==='editorial';
  const s=useThemedStyles(characterStyles, 'characterUi'), auto=card.automation;
  if(!auto)return null;
  const busy=auto.status==='queued'||auto.status==='running';
  const current=card.conversation_id===api.snapshot?.conversation_id;
  const enabled=current&&api.snapshot?.automatic_creation_available&&api.snapshot.automatic_add_enabled&&
    api.snapshot.character_voices_enabled&&api.snapshot.allow_new_characters;
  const disabled=api.busy||!api.enabled||!enabled||busy||dirty;
  const request=(action:string)=>void api.mutate(`/${card.id}/${action}`,{
    expected_revision:card.revision,conversation_id:card.conversation_id}).catch(()=>undefined);
  return <View style={{gap:7,alignSelf:'stretch'}}>
    {editorial?<View style={[s.row,{justifyContent:'space-between'}]}>
      <Text style={s.badge} accessibilityLiveRegion="polite">
      {auto.status==='ready'?'Voice and portrait ready':busy?(auto.mode==='remake'?'Remaking voice and portrait':'Preparing voice and portrait'):
        auto.status==='cancelled'?'Automatic setup stopped':'Setup needs attention'}
    </Text>
<CharacterButton label={busy?'Remaking…':'Remake'} disabled={disabled} onPress={()=>request('remake')}/></View>:<>
      <Text style={s.badge} accessibilityLiveRegion="polite">
      {auto.status==='ready'?'Voice and portrait ready':busy?(auto.mode==='remake'?'Remaking voice and portrait':'Preparing voice and portrait'):
        auto.status==='cancelled'?'Automatic setup stopped':'Setup needs attention'}
    </Text>
</>}
    {busy?<Text style={s.subtitle}>Voice: {auto.voice_status||'queued'} · Portrait: {auto.portrait_status||'queued'}</Text>:null}
    {auto.error?<Text style={s.error}>{auto.error}</Text>:null}
    {!editorial?<CharacterButton label={busy?'Remaking…':'Remake'} disabled={disabled} onPress={()=>request('remake')}/>:null}
    <Text style={s.subtitle}>{editorial&&!dirty&&!busy?'Remake uses generation credits.':dirty?'Save your edited prompts before remaking.':busy?
      'Existing voice and portrait stay active.': 'Creates a new voice and portrait. Uses generation credits.'}</Text>
    {auto.status==='failed'?<CharacterButton label="Retry failed stage" disabled={disabled} onPress={()=>request('retry-automatic')}/>:null}
    {auto.status==='unknown'?<Text style={s.subtitle}>Check generation jobs in Voice and Portrait before Remake; the provider may have charged this request.</Text>:null}
  </View>;
}
