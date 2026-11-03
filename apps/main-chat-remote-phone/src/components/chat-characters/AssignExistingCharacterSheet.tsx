import React from 'react';
import {FlatList, Keyboard, Modal, Pressable, Text, TextInput, View} from 'react-native';
import {SafeAreaView} from 'react-native-safe-area-context';
import type {ChatCharacter} from '../../api/types';
import type {ChatCharactersApi} from '../../hooks/useChatCharacters';
import {activeChatCard, filterCharacters} from '../../utils/chatCharacterDrafts';
import {useThemedStyles} from '../../styles/ThemeContext';
import {characterStyles, CharacterButton, CharacterPortrait} from './characterUi';

type Candidate = {id: string; name: string; conversationId: string};

export function AssignExistingCharacterSheet({candidate, api, onClose}: {
  candidate: Candidate | null;
  api: ChatCharactersApi;
  onClose: () => void;
}) {
  const s = useThemedStyles(characterStyles, 'characterUi');
  const [search, setSearch] = React.useState('');
  const [loading, setLoading] = React.useState(false);
  const [loaded, setLoaded] = React.useState(false);
  const [failure, setFailure] = React.useState('');
  React.useEffect(() => {
    if (!candidate) return;
    setSearch('');
    setFailure('');
    setLoading(true);
    setLoaded(false);
    void api.refresh(true).then(result => {
      if (result) setLoaded(true);
      else setFailure('Could not load saved characters. Try again.');
    }).finally(() => setLoading(false));
  }, [candidate?.id, candidate?.conversationId, api.connectionIdentity]);
  const snapshot = api.snapshot;
  const current = candidate?.conversationId || '';
  const sameConversation = snapshot?.conversation_id === current;
  const activeNames = new Set((snapshot?.characters || [])
    .filter(card => card.conversation_id === current)
    .flatMap(card => [card.name, ...card.aliases].map(name => name.trim().toLocaleLowerCase())));
  const available = filterCharacters(loaded && sameConversation ? snapshot?.characters || [] : [], '', search, 'all').filter(card =>
    !activeChatCard(snapshot?.characters || [], card, current)
    && ![card.name, ...card.aliases].some(name => activeNames.has(name.trim().toLocaleLowerCase())));
  const assign = (card: ChatCharacter) => {
    if (!candidate || api.busy || !loaded) return;
    if (!sameConversation) {
      setFailure('The conversation changed. Close this list and try again.');
      return;
    }
    setFailure('');
    void api.mutate<ChatCharacter>(`/${card.id}/assign-existing`, {
      conversation_id: candidate.conversationId,
      candidate_id: candidate.id,
      expected_revision: card.revision,
    }).then(() => {
      onClose();
      void api.refresh(false);
    }).catch(error => setFailure(error instanceof Error ? error.message : 'Could not assign character.'));
  };
  return <Modal visible={!!candidate} animationType="slide" presentationStyle="pageSheet"
      onRequestClose={onClose} onShow={Keyboard.dismiss}>
    <SafeAreaView style={s.screen}>
      <View style={s.header}>
        <View style={{flex:1}}>
          <Text style={s.title}>Assign existing character</Text>
          <Text style={s.subtitle}>Use a saved character for {candidate?.name || 'this speaker'} in this story.</Text>
        </View>
        <CharacterButton label="Close" onPress={onClose}/>
      </View>
      <View style={{paddingHorizontal:20, paddingBottom:8}}>
        <TextInput accessibilityLabel="Search saved characters" placeholder="Search saved characters"
          placeholderTextColor={s.subtitle.color} value={search} onChangeText={setSearch} style={s.input}/>
      </View>
      <FlatList data={available} keyExtractor={card => card.id}
        keyboardShouldPersistTaps="handled" contentContainerStyle={s.body}
        ListHeaderComponent={loading ? <Text style={s.subtitle}>Loading characters…</Text>
          : loaded && !sameConversation ? <Text style={s.error}>The conversation changed. Close this list and try again.</Text> : null}
        ListEmptyComponent={loaded && sameConversation
          ? <Text style={s.subtitle}>No available saved characters match this search.</Text> : null}
        renderItem={({item:card}) => <Pressable accessibilityRole="button"
          accessibilityLabel={`Assign ${card.name} to ${candidate?.name || 'speaker'}`}
          disabled={api.busy || loading || !loaded} onPress={() => assign(card)} style={s.voiceTile}>
          <View style={{flexDirection:'row', gap:14, alignItems:'center'}}>
            <CharacterPortrait client={api.client} path={card.portrait_url_path} name={card.name}/>
            <View style={{flex:1, gap:4}}>
              <Text style={s.label}>{card.name}</Text>
              {card.role ? <Text style={s.subtitle}>{card.role}</Text> : null}
              <Text style={s.subtitle}>{card.voice_id ? 'Voice ready' : 'Narrator until voice is assigned'}</Text>
              {candidate && card.name.toLocaleLowerCase() !== candidate.name.toLocaleLowerCase()
                ? <Text style={s.subtitle}>Also recognizes “{candidate.name}” in this story</Text> : null}
            </View>
          </View>
        </Pressable>}
        ListFooterComponent={failure || api.error
          ? <Text accessibilityRole="alert" style={s.error}>{failure || api.error}</Text> : null}/>
    </SafeAreaView>
  </Modal>;
}
