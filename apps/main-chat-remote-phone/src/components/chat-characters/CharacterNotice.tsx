import React from 'react';
import {Text, View} from 'react-native';
import type {ChatCharacter} from '../../api/types';
import {useThemedStyles} from '../../styles/ThemeContext';
import {characterStyles, CharacterButton} from './characterUi';

export function CharacterNotice({card,onOpen,onDismiss,onDiscard,busy,error}: {
  card?:ChatCharacter;onOpen:()=>void;onDismiss:()=>void;onDiscard:()=>void;busy?:boolean;error?:string;
}) {
  const s=useThemedStyles(characterStyles, 'characterUi');
  if(!card) return null;
  return <View style={s.notice}><Text style={s.label}>{card.name} joined this story</Text>
    <Text style={s.subtitle}>{card.automation?card.automation.status==='ready'?
      'Voice and portrait ready. Newly prepared replies use this voice.':
      card.automation.status==='running'||card.automation.status==='queued'?
      'Preparing voice and portrait automatically. Chat keeps playing.':
      'Automatic setup needs attention. Open the character card to review.':
      'The narrator keeps playing. Choose a voice whenever you like.'}</Text>
    <View style={s.row}><CharacterButton label="Character card" onPress={onOpen}/><CharacterButton label="Later" onPress={onDismiss}/>
      <CharacterButton label="Discard" disabled={busy} onPress={onDiscard}/></View>
    {error?<Text accessibilityRole="alert" style={s.subtitle}>{error}</Text>:null}
  </View>;
}

export function CharacterCandidateNotice({candidate,onReview,onAssignExisting,onDiscard,busy,error}: {
  candidate?:{id:string;name:string};onReview:()=>void;onAssignExisting:()=>void;onDiscard:()=>void;busy?:boolean;error?:string;
}) {
  const s=useThemedStyles(characterStyles, 'characterUi');
  const [dismissed,setDismissed]=React.useState<string[]>([]);
  if(!candidate||dismissed.includes(candidate.id))return null;
  return <View style={s.notice} accessibilityLiveRegion="polite">
    <Text style={s.label}>New character found: {candidate.name}</Text>
    <Text style={s.subtitle}>Review or assign a saved character. The narrator keeps playing.</Text>
    <View style={s.row}>
      <CharacterButton label="Review character" onPress={onReview}/>
      <CharacterButton label="Assign existing character" disabled={busy} onPress={onAssignExisting}/>
      <CharacterButton label="Later" onPress={()=>setDismissed(ids=>[...ids,candidate.id])}/>
      <CharacterButton label="Discard" disabled={busy} onPress={onDiscard}/>
    </View>
    {error?<Text accessibilityRole="alert" style={s.subtitle}>{error}</Text>:null}
  </View>;
}
