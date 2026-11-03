import {KeyboardSafeView} from '../KeyboardSafeView';
import {Keyboard} from 'react-native';
import React from 'react';
import { Alert, Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import type { StoryLibraryEntry } from '../../api/types';
import { useThemeColors, useThemedStyles, usePresentationStyle } from '../../styles/ThemeContext';

type Props = {
  visible: boolean; entries: StoryLibraryEntry[]; activeEntryId: string | null;
  busy: boolean; activity: string; error: string; recoveryId: string | null; playback: 'play' | 'pause' | 'resume';
  onClose: () => void; onRefresh: () => Promise<void>; onSave: (name: string) => Promise<void>;
  onSaveAs: (name: string) => Promise<void>; onOpen: (entry: StoryLibraryEntry, saveCurrent: boolean, currentName: string) => Promise<void>;
  onRename: (entry: StoryLibraryEntry, name: string) => Promise<void>; onDelete: (entry: StoryLibraryEntry) => Promise<void>;
  onTransport: () => Promise<void>;
  onRecover: () => Promise<void>;
  onOpenCharacters?: () => void;
};

export function StoryLibraryPanel({ visible, entries, activeEntryId, busy, activity, error, recoveryId, playback,
  onClose, onRefresh, onSave, onSaveAs, onOpen, onRename, onDelete, onTransport, onRecover, onOpenCharacters }: Props) {
  const colors = useThemeColors();
  const editorial = usePresentationStyle() === 'editorial';
  const [search, setSearch] = React.useState('');
  const [saveOpen, setSaveOpen] = React.useState(false);
  const [saveAsNew, setSaveAsNew] = React.useState(true);
  const [entryMenu, setEntryMenu] = React.useState<string | null>(null);
  const styles = useThemedStyles(colors => StyleSheet.create({
    screen: { flex: 1, backgroundColor: colors.background },
    header: { padding: 18, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
    heading: { color: colors.text, fontSize: 23, fontWeight: '700' },
    content: { padding: 18, paddingBottom: 48, gap: 12 },
    libraryLink: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 8, marginBottom: 6 },
    card: { backgroundColor: colors.panel, borderRadius: 16, padding: 16, gap: 10 },
    title: { color: colors.text, fontSize: 18, fontWeight: '700' },
    note: { color: colors.muted, fontSize: 14 },
    input: { color: colors.text, borderColor: colors.border, borderWidth: 1, borderRadius: 10, padding: 12 },
    row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
    button: { borderColor: colors.border, borderWidth: 1, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 11 },
    buttonText: { color: colors.accent, fontWeight: '700' },
    error: { color: colors.danger },
  }), 'StoryLibraryPanel');
  const [name, setName] = React.useState('');
  const [selected, setSelected] = React.useState<string | null>(null);
  const [rename, setRename] = React.useState('');
  const selectedEntry = entries.find(entry => entry.entry_id === selected);
  const run = (work: Promise<unknown>) => { void work.catch(() => undefined); };
  const button = (label: string, action: () => void, disabled = busy, primary = false) => <Pressable
    key={label} accessibilityRole="button" accessibilityLabel={label} disabled={disabled}
    onPress={action} style={[styles.button,editorial&&primary&&{backgroundColor:colors.accent,borderColor:colors.accent,borderRadius:5,alignItems:'center'}, disabled && {opacity: .45}]}><Text style={[styles.buttonText,editorial&&primary&&{color:colors.background}]}>{label}</Text></Pressable>;
  const confirmOpen = (entry: StoryLibraryEntry) => Alert.alert('Open saved story?',
    `Opening “${entry.name}” replaces the current chat and opens paused.`, [
      {text: 'Cancel', style: 'cancel'},
      {text: 'Replace', onPress: () => run(onOpen(entry, false, name))},
      {text: 'Save current', onPress: () => run(onOpen(entry, true, name))},
    ]);
  const activeEntry = entries.find(entry => entry.entry_id === activeEntryId);
  return <><Modal onShow={Keyboard.dismiss} visible={visible} animationType="slide" onRequestClose={onClose}>
    <KeyboardSafeView active={visible}><SafeAreaView style={styles.screen}>
      <View style={styles.header}><Text style={[styles.heading,editorial&&{fontFamily:'serif',fontWeight:'400'}]}>Story Library</Text>{button('Done', onClose, false)}</View>
      <ScrollView keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" contentContainerStyle={styles.content}>
        {onOpenCharacters ? <Pressable accessibilityRole="button" accessibilityLabel="Open chat character library"
          onPress={onOpenCharacters} style={styles.libraryLink}>
          <Text style={styles.note}>Chat character library</Text><Text style={styles.buttonText}>View ›</Text>
        </Pressable> : null}
        {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
        {busy ? <Text accessibilityLiveRegion="polite" style={styles.note}>{activity || 'Working…'}</Text> : null}
        {recoveryId ? <View style={styles.card}>
          <Text style={styles.title}>Previous chat needs recovery</Text>
          <Text style={styles.note}>The saved story could not open, and NC could not restore the previous chat automatically.</Text>
          {button('Recover previous chat', () => run(onRecover()))}
        </View> : null}
        {editorial ? <>
          {button('Save current story', () => {setSaveAsNew(!activeEntryId);setSaveOpen(true);}, false,true)}
          {activeEntryId ? button(playback === 'play' ? 'Play story' : playback === 'pause' ? 'Pause story' : 'Resume story',
            () => run(onTransport())) : null}
          <TextInput accessibilityLabel="Search stories" placeholder="Search stories" placeholderTextColor={colors.muted}
            value={search} onChangeText={setSearch} style={styles.input}/>
        </> : null}
        <View style={[styles.card, editorial && {display: 'none'}]}>
          <Text style={styles.title}>Current story</Text>
          <Text style={styles.note}>{entries.find(entry => entry.entry_id === activeEntryId)?.name || 'Not named yet'}</Text>
          <TextInput accessibilityLabel="New story name" placeholder="Name for Save Story As" placeholderTextColor={colors.muted}
            value={name} onChangeText={setName} editable={!busy} maxLength={120} style={styles.input}/>
          <View style={styles.row}>
            {button('Save', () => run(onSave(name.trim())), busy || (!activeEntryId && !name.trim()))}
            {button('Save Story As', () => run(onSaveAs(name.trim())), busy || !name.trim())}
            {activeEntryId ? button(playback === 'play' ? 'Play story' : playback === 'pause' ? 'Pause story' : 'Resume story',
              () => run(onTransport())) : null}
          </View>
          <Text style={styles.note}>Save keeps the current chat and audio running. Open restores a saved version silently.</Text>
        </View>
        <View style={styles.row}>{button('Refresh library', () => run(onRefresh()))}</View>
        {entries.length === 0 ? <Text style={styles.note}>No named stories yet. Enter a name and choose Save Story As.</Text> : null}
        {entries.filter(entry => !editorial || entry.name.toLowerCase().includes(search.trim().toLowerCase())).map(entry => <View key={entry.entry_id} style={styles.card}>
          <Text style={styles.title}>{entry.name}{entry.entry_id === activeEntryId ? ' · Open now' : ''}</Text>
          <Text style={styles.note}>{`Saved ${new Date(entry.saved_at).toLocaleString()} · Version ${entry.version}`}</Text>
          <Text style={styles.note}>{entry.beat_count ? `Beat ${(entry.current_beat ?? 0) + 1} of ${entry.beat_count}` : 'No Story Plan'}</Text>
          {!editorial || entryMenu === entry.entry_id ? <Text style={styles.note}>{entry.character_names.length ? `Characters: ${entry.character_names.join(', ')}` : 'No saved chat characters'}</Text> : null}
          <View style={styles.row}>
            {button(editorial ? 'Open paused' : 'Open ' + entry.name, () => confirmOpen(entry))}
            {editorial ? button(entryMenu === entry.entry_id ? 'Less' : 'More', () => setEntryMenu(id => id === entry.entry_id ? null : entry.entry_id), false) : null}
            {!editorial || entryMenu === entry.entry_id ? <>
            {button('Rename ' + entry.name, () => { setSelected(entry.entry_id); setRename(entry.name); })}
            {button('Delete ' + entry.name, () => Alert.alert('Delete saved story?', `Delete “${entry.name}” and its saved versions? The current chat stays open.`, [
              {text: 'Cancel', style: 'cancel'},
              {text: 'Delete', style: 'destructive', onPress: () => run(onDelete(entry))},
            ]))}
            </> : null}
          </View>
          {selectedEntry?.entry_id === entry.entry_id ? <View style={styles.row}>
            <TextInput accessibilityLabel="Rename story" value={rename} onChangeText={setRename}
              editable={!busy} maxLength={120} style={[styles.input, {flexGrow: 1}]}/>
            {button('Save name', () => run(onRename(entry, rename.trim()).then(() => setSelected(null))), busy || !rename.trim())}
          </View> : null}
        </View>)}
      </ScrollView>
    </SafeAreaView></KeyboardSafeView>
  </Modal>
  {editorial ? <Modal onShow={Keyboard.dismiss} visible={visible && saveOpen} transparent animationType="slide"
    onRequestClose={()=>setSaveOpen(false)}>
    <KeyboardSafeView active={visible && saveOpen} style={{flex:1,justifyContent:'flex-end',backgroundColor:'#00000088'}}>
      <Pressable style={StyleSheet.absoluteFill} accessibilityRole="button" accessibilityLabel="Close save story"
        onPress={()=>setSaveOpen(false)}/>
      <SafeAreaView style={[styles.screen,{flex:0,maxHeight:'85%'}]} accessibilityViewIsModal>
        <View style={styles.header}><Text style={[styles.heading,{fontFamily:'serif',fontWeight:'400'}]}>Save story as</Text>{button('Done',()=>setSaveOpen(false),false)}</View>
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.content}>
          <Text style={styles.title}>{activeEntry?.name || 'Current story'}</Text>
          <Text style={styles.note}>Conversation and progress included.</Text>
          <TextInput accessibilityLabel="Save story name" placeholder={activeEntry?.name || 'Story name'}
            placeholderTextColor={colors.muted} value={name} onChangeText={setName} editable={!busy} maxLength={120} style={styles.input}/>
          <View style={styles.row}>
            <Pressable accessibilityRole="button" accessibilityState={{selected:saveAsNew}} style={styles.button}
              onPress={()=>setSaveAsNew(true)}><Text style={styles.buttonText}>Save as new{saveAsNew?' ✓':''}</Text></Pressable>
            <Pressable accessibilityRole="button" accessibilityState={{selected:!saveAsNew,disabled:!activeEntryId}}
              disabled={!activeEntryId} style={[styles.button,!activeEntryId&&{opacity:.45}]}
              onPress={()=>setSaveAsNew(false)}><Text style={styles.buttonText}>Save version{!saveAsNew?' ✓':''}</Text></Pressable>
          </View>
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
          {busy ? <Text accessibilityLiveRegion="polite" style={styles.note}>{activity || 'Saving…'}</Text> : null}
          {button('Save to library',()=>run((saveAsNew ? onSaveAs(name.trim()) : onSave(name.trim()))
            .then(()=>setSaveOpen(false))),busy || (saveAsNew && !name.trim()),true)}
        </ScrollView>
      </SafeAreaView>
    </KeyboardSafeView>
  </Modal> : null}</>;
}
