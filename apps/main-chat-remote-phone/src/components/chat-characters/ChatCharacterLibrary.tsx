import {KeyboardSafeView} from '../KeyboardSafeView';
import {Keyboard} from 'react-native';
import React from 'react';
import {Alert, Modal, Pressable, ScrollView, Switch, Text, View} from 'react-native';
import {SafeAreaView} from 'react-native-safe-area-context';
import * as SecureStore from 'expo-secure-store';
import type {ChatCharacter, CharacterJob} from '../../api/types';
import type {ChatCharactersApi} from '../../hooks/useChatCharacters';
import {activeChatCard, filterCharacters} from '../../utils/chatCharacterDrafts';
import {usePresentationStyle, useThemedStyles, useThemeColors} from '../../styles/ThemeContext';
import {ChatCharacterCard} from './ChatCharacterCard';
import {AutomaticCharacterControls} from './AutomaticCharacterControls';
import {characterStyles, CharacterButton, CharacterField, CharacterPortrait, CharacterDisclosure} from './characterUi';

export function ChatCharacterLibrary({visible,initialCharacterId,api,onClose,previewAllowed,onPreview,previewId,onStopPreview}: {
  visible:boolean;initialCharacterId?:string;api:ChatCharactersApi;onClose:()=>void;previewAllowed:boolean;
  onPreview:(candidate:CharacterJob['candidates'][number])=>void;
  previewId:string;onStopPreview:()=>void;
}) {
  const s=useThemedStyles(characterStyles, 'characterUi'), colors=useThemeColors();
  const editorial=usePresentationStyle()==='editorial';
  const [selected,setSelected]=React.useState('');
  const [search,setSearch]=React.useState('');
  const [filter,setFilter]=React.useState('all');
  const [all,setAll]=React.useState(false);
  const [list,setList]=React.useState(false);
  const [editorialList,setEditorialList]=React.useState(true);
  const shownAsList=editorial?editorialList:list;
  const [actionId,setActionId]=React.useState('');
  const actionIdRef=React.useRef('');
  const cardBack=React.useRef<(()=>void)|null>(null);
  React.useEffect(()=>{void SecureStore.getItemAsync('nc.characters.layout').then(v=>setList(v==='list')).catch(()=>undefined);},[]);
  React.useEffect(()=>{if(visible){setSelected(initialCharacterId||'');void api.refresh(all);}else{setActionId('');actionIdRef.current='';}},[visible,initialCharacterId]);
  const snapshot=api.snapshot;
  const card=snapshot?.characters.find(c=>c.id===selected);
  const cards=filterCharacters(snapshot?.characters||[],all?'':snapshot?.conversation_id||'',search,filter);
  const actionCard=snapshot?.characters.find(c=>c.id===actionId);
  const currentConversation=snapshot?.conversation_id||'';
  const activeCard=actionCard?activeChatCard(snapshot?.characters||[],actionCard,currentConversation):null;
  const closeAction=()=>{actionIdRef.current='';setActionId('');};
  const openAction=(character:ChatCharacter)=>{actionIdRef.current=character.id;setActionId(character.id);};
  const removeCard=(character:ChatCharacter)=>{
    closeAction();
    Alert.alert(`Remove ${character.name}?`,
      'Delete this card from the character library? Saved voice files and copied NC personas are kept.',[
        {text:'Cancel',style:'cancel'},
        {text:'Remove',style:'destructive',onPress:()=>void api.mutate(`/${character.id}/remove`,
          {expected_revision:character.revision}).catch(()=>undefined)},
      ]);
  };
  const addCard=(character:ChatCharacter)=>{
    closeAction();
    if(!currentConversation)return;
    void api.mutate<ChatCharacter>(`/${character.id}/add-to-chat`,
      {conversation_id:currentConversation,expected_revision:character.revision})
      .then(()=>{setAll(false);void api.refresh(false);
        Alert.alert('Added to this conversation', `${character.name} is now in this chat.`);})
      .catch(()=>undefined);
  };
  const removeCardFromChat=(character:ChatCharacter)=>{
    closeAction();
    if(!currentConversation)return;
    void api.mutate(`/${character.id}/remove-from-chat`,
      {conversation_id:currentConversation,expected_revision:character.revision})
      .then(()=>{setAll(true);void api.refresh(true);
        Alert.alert('Removed from this conversation', `${character.name} remains in the character library.`);})
      .catch(()=>undefined);
  };
  return <Modal onShow={Keyboard.dismiss} visible={visible} animationType="slide" presentationStyle="fullScreen" onRequestClose={()=>{if(cardBack.current)cardBack.current();else onClose();}}>
    <KeyboardSafeView active={visible} style={s.screen}><SafeAreaView style={s.screen}>
      {card?<ChatCharacterCard key={card.id+api.connectionIdentity} card={card} api={api} onBack={()=>setSelected('')}
        onAddedToChat={name=>{
          setSelected(''); setAll(false);
          void api.refresh(false);
          Alert.alert('Added to this conversation', `${name} is now in this chat. Character voices are on; Allow new characters is unchanged.`);
        }}
        onBackRequestReady={handler=>{cardBack.current=handler;}}
        previewAllowed={previewAllowed} onPreview={onPreview} previewId={previewId} onStopPreview={onStopPreview}/>:<>
        <View style={s.header}><CharacterButton label="‹ Tools" onPress={onClose}/><Text style={s.title}>Chat characters</Text></View>
        <ScrollView keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" contentContainerStyle={s.body}>
          <Text style={s.subtitle}>Your story’s cast. Their own voices, only when they speak.</Text>
          <CharacterDisclosure label="Automatic characters">
          <View style={s.section}>
            <View style={[s.row,{justifyContent:'space-between'}]}><Text style={s.label}>Character voices</Text>
              <Switch accessibilityLabel="Use character voices in this conversation" value={snapshot?.character_voices_enabled===true}
                disabled={!snapshot?.structured_character_voices_available||api.busy||!api.enabled}
                trackColor={{true:colors.accentMuted,false:colors.border}}
                onValueChange={character_voices_enabled=>{if(snapshot)void api.mutate('/settings',{
                  enabled:snapshot.allow_new_characters,character_voices_enabled,conversation_id:snapshot.conversation_id,
                  expected_revision:snapshot.revision}).catch(()=>undefined);}}/>
            </View>
            <Text style={s.subtitle}>{editorial?'Assigned voices apply to the next reply.':'Off: normal single-voice replies. On: assigned voices for each character’s dialogue and inner thoughts. Changes apply to the next reply.'}</Text>
            {snapshot&&!snapshot.structured_character_voices_available?<Text style={s.subtitle}>Update and restart NC desktop to enable character voices.</Text>:null}
          </View>
          <View style={s.section}><View style={[s.row,{justifyContent:'space-between'}]}><Text style={s.label}>Allow new characters</Text>
            <Switch accessibilityLabel="Allow new characters in this conversation" value={snapshot?.allow_new_characters===true}
              disabled={!snapshot||api.busy||!api.enabled} trackColor={{true:colors.accentMuted,false:colors.border}}
              onValueChange={enabled=>{if(snapshot)void api.mutate('/settings',{enabled,conversation_id:snapshot.conversation_id,
                expected_revision:snapshot.revision}).catch(()=>undefined);}}/></View>
            <Text style={s.label}>Maximum characters</Text>
            <View style={s.row}>
              <CharacterButton label="−" disabled={!snapshot||api.busy||!api.enabled||(snapshot.max_characters??6)<=1}
                onPress={()=>{if(snapshot)void api.mutate('/settings',{enabled:snapshot.allow_new_characters,
                  max_characters:(snapshot.max_characters??6)-1,conversation_id:snapshot.conversation_id,
                  expected_revision:snapshot.revision}).catch(()=>undefined);}}/>
              <Text accessibilityLiveRegion="polite" style={s.title}>{snapshot?.max_characters??6}</Text>
              <CharacterButton label="+" disabled={!snapshot||api.busy||!api.enabled||(snapshot.max_characters??6)>=20}
                onPress={()=>{if(snapshot)void api.mutate('/settings',{enabled:snapshot.allow_new_characters,
                  max_characters:(snapshot.max_characters??6)+1,conversation_id:snapshot.conversation_id,
                  expected_revision:snapshot.revision}).catch(()=>undefined);}}/>
            </View>
            <Text style={s.subtitle}>{editorial?'1–20 per conversation. Extra speakers use the narrator.':'1–20 per conversation. Extra speakers use the narrator. Lowering this limit never removes existing characters.'}</Text>
            <Text style={s.subtitle}>{editorial?'New speakers appear as suggestions.':'Off by default, for this conversation. New speakers appear as suggestions while Character voices is on. Add the ones you want; the narrator keeps playing.'}</Text>
            {snapshot&&!snapshot.voice_playback_available?<Text style={s.subtitle}>Distinct voices need Backend HQ and a reference-capable desktop TTS engine. Cards remain available.</Text>:null}
          </View>
          <View style={s.section}>
            <View style={[s.row,{justifyContent:'space-between'}]}><Text style={s.label}>Automatic add characters</Text>
              <Switch accessibilityLabel="Automatic add characters" value={snapshot?.automatic_add_enabled===true}
                disabled={!api.enabled||api.busy||!snapshot?.automatic_creation_available||!snapshot.character_voices_enabled||!snapshot.allow_new_characters||
                  (!!snapshot.automatic_creation_error&&!snapshot.automatic_add_enabled)}
                trackColor={{true:colors.accentMuted,false:colors.border}}
                onValueChange={automatic_add_enabled=>{if(snapshot)void api.mutate('/settings',{
                  enabled:snapshot.allow_new_characters,automatic_add_enabled,conversation_id:snapshot.conversation_id,
                  expected_revision:snapshot.revision}).catch(()=>undefined);}}/>
            </View>
            <Text style={s.subtitle}>{editorial?'Description, ElevenLabs voice and portrait. Uses generation credits.':'Automatically add new characters with a description, an ElevenLabs voice and a portrait. Uses generation credits. Requires both switches above.'}</Text>
            {snapshot?.automatic_creation_error?<Text style={s.subtitle}>{snapshot.automatic_creation_error}</Text>:null}
            {!snapshot?.automatic_creation_available?<Text style={s.subtitle}>Update and restart NC desktop to enable automatic creation.</Text>:null}
            <View style={[s.row,{justifyContent:'space-between'}]}><Text style={s.label}>Soft sound when added</Text>
              <Switch accessibilityLabel="Soft sound when added" value={snapshot?.automatic_add_sound!==false}
                disabled={!api.enabled||api.busy||!snapshot?.automatic_creation_available}
                trackColor={{true:colors.accentMuted,false:colors.border}}
                onValueChange={automatic_add_sound=>{if(snapshot)void api.mutate('/settings',{
                  enabled:snapshot.allow_new_characters,automatic_add_sound,conversation_id:snapshot.conversation_id,
                  expected_revision:snapshot.revision}).catch(()=>undefined);}}/>
            </View><Text style={s.subtitle}>{editorial?'Respects silent mode; paused audio stays paused.':'A gentle pling while NC is speaking. Respects silent mode and never starts paused audio.'}</Text>
          </View>
          </CharacterDisclosure>
          {(snapshot?.candidates||[]).map(candidate=><View key={candidate.id} style={s.section}>
            <Text style={s.label}>{candidate.name}</Text><Text style={s.subtitle}>New character suggestion · narrator voice</Text>
            <Text style={s.subtitle}>{candidate.excerpt}</Text>
            <CharacterButton label="Add to library" disabled={!api.enabled||api.busy||!snapshot?.allow_new_characters}
              onPress={()=>{if(snapshot)void api.mutate('/'+candidate.id+'/accept-candidate',{
                expected_revision:snapshot.revision}).catch(()=>undefined);}}/>
          </View>)}
          <CharacterField label="Find a character" value={search} onChange={setSearch}/>
          <View style={s.row}><CharacterButton label={all?'All conversations':'This conversation'} onPress={()=>{setAll(!all);void api.refresh(!all);}}/>
            <CharacterButton label={shownAsList?'List view':'Grid view'} onPress={()=>{if(editorial)setEditorialList(!editorialList);else{setList(!list);void SecureStore.setItemAsync('nc.characters.layout',!list?'list':'grid').catch(()=>undefined);}}}/></View>
          <View style={s.row}>{([['all','All'],['needs_voice','Needs a voice'],['voiced','Voiced']] as const).map(([value,label])=><CharacterButton
            key={value} label={label} primary={filter===value} onPress={()=>setFilter(value)}/>)}</View>
          {!cards.length?<View style={s.section}><Text style={s.label}>Your cast starts here</Text><Text style={s.subtitle}>
            Enable Character voices and Allow new characters, then continue your story. Add suggested characters below. Choose All conversations to find saved characters.</Text></View>:null}
          <View style={s.grid}>{cards.map(c=><View key={c.id} style={[s.tile,shownAsList&&s.listTile,editorial&&{backgroundColor:'transparent',borderRadius:0,paddingHorizontal:0},{flexDirection:'column'}]}><Pressable accessibilityRole="button" accessibilityLabel={`Open ${c.name} character card`}
            accessibilityHint="Long press for character actions" key={c.id}
            onPress={()=>{if(actionIdRef.current!==c.id)setSelected(c.id);}}
            onLongPress={()=>openAction(c)} delayLongPress={450} style={{alignSelf:'stretch',gap:10,...(editorial&&shownAsList?{flexDirection:'row',alignItems:'center'} as const:{})}}>
            <CharacterPortrait client={api.client} path={c.portrait_url_path} name={c.name}/>
            <View style={{flexShrink:1,gap:6}}><Text style={s.label}>{c.name}</Text><Text style={s.subtitle}>{c.role||'Story character'}</Text>
              <Text style={s.badge}>{c.voice_id?'Voice assigned':'Narrator for now'}</Text>{c.copied_persona_id?<Text style={s.badge}>NC Persona saved</Text>:null}</View>
          </Pressable><AutomaticCharacterControls card={c} api={api}/></View>)}</View>
          {api.error?<Text style={s.error}>{api.error}</Text>:null}
          {!api.enabled?<Text style={s.subtitle}>Connect to an updated NC desktop to use this library.</Text>:null}
          <CharacterButton label="Refresh library" disabled={!api.enabled||api.busy} onPress={()=>void api.refresh(all)}/>
        </ScrollView>
      </>}
      <Modal visible={!!actionCard} transparent animationType="fade" onRequestClose={closeAction}>
        <View style={s.actionOverlay}>
          <Pressable accessibilityLabel="Close character actions" onPress={closeAction}
            style={{position:'absolute',top:0,bottom:0,left:0,right:0}}/>
          {actionCard?<View style={s.actionSheet}>
            <Text style={s.label}>{actionCard.name}</Text>
            <Text style={s.subtitle}>Character actions</Text>
            <CharacterButton label="Add to chat" disabled={!api.enabled||api.busy||!currentConversation||!!activeCard}
              onPress={()=>addCard(actionCard)}/>
            <CharacterButton label="Remove from chat" disabled={!api.enabled||api.busy||!activeCard}
              onPress={()=>removeCardFromChat(actionCard)}/>
            <Pressable accessibilityRole="button" accessibilityLabel="Remove character from library"
              disabled={!api.enabled||api.busy} accessibilityState={{disabled:!api.enabled||api.busy}}
              onPress={()=>removeCard(actionCard)} style={[s.button,(!api.enabled||api.busy)&&s.disabled]}>
              <Text style={[s.buttonText,s.actionDanger]}>Remove</Text>
            </Pressable>
            <CharacterButton label="Cancel" onPress={closeAction}/>
          </View>:null}
        </View>
      </Modal>
    </SafeAreaView></KeyboardSafeView>
  </Modal>;
}
