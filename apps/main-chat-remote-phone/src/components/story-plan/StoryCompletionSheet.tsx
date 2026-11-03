import React from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { usePresentationStyle, useThemeColors, useThemedStyles } from '../../styles/ThemeContext';

type Props = {
  visible: boolean;
  onAdd: () => void;
  onLibrary: () => void;
  onDiscard: () => void;
};

export function StoryCompletionSheet({ visible, onAdd, onLibrary, onDiscard }: Props) {
  const colors = useThemeColors();
  const editorial = usePresentationStyle() === 'editorial';
  const styles = useThemedStyles(theme => StyleSheet.create({
    backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: '#00000099' },
    sheet: { backgroundColor: theme.panel, borderTopLeftRadius: 24, borderTopRightRadius: 24,
      paddingHorizontal: 24, paddingTop: 26, paddingBottom: 16, gap: 16 },
    eyebrow: { color: theme.accent, fontSize: 13, fontWeight: '700', letterSpacing: 1.5 },
    heading: { color: theme.text, fontSize: 28, fontWeight: '600' },
    note: { color: theme.muted, fontSize: 15, lineHeight: 22 },
    row: { flexDirection: 'row', gap: 10 },
    action: { flex: 1, minHeight: 50, alignItems: 'center', justifyContent: 'center',
      borderWidth: 1, borderColor: theme.border, borderRadius: 10 },
    primary: { backgroundColor: theme.accent, borderColor: theme.accent },
    actionText: { color: theme.accent, fontSize: 15, fontWeight: '700' },
    primaryText: { color: theme.background },
    dismiss: { alignSelf: 'center', paddingHorizontal: 18, paddingVertical: 14 },
  }), 'StoryCompletionSheet');
  return <Modal visible={visible} transparent animationType="slide" onRequestClose={onDiscard}>
    <View style={styles.backdrop}>
      <Pressable accessibilityRole="button" accessibilityLabel="Dismiss finished story prompt"
        style={StyleSheet.absoluteFill} onPress={onDiscard}/>
      <SafeAreaView style={styles.sheet} accessibilityViewIsModal>
        <Text style={styles.eyebrow}>STORY COMPLETE</Text>
        <Text style={[styles.heading, editorial && {fontFamily:'serif',fontWeight:'400'}]}>Keep the story going?</Text>
        <Text style={styles.note}>Add 5–20 beats from the story so far, or open your saved stories. Your completed story stays here.</Text>
        <View style={styles.row}>
          <Pressable accessibilityRole="button" accessibilityLabel="Add more story beats" style={[styles.action,styles.primary]} onPress={onAdd}>
            <Text style={[styles.actionText,styles.primaryText]}>Add more beats</Text>
          </Pressable>
          <Pressable accessibilityRole="button" accessibilityLabel="Open Story Library" style={styles.action} onPress={onLibrary}>
            <Text style={styles.actionText}>Story Library</Text>
          </Pressable>
        </View>
        <Pressable accessibilityRole="button" accessibilityLabel="Discard finished story prompt" style={styles.dismiss} onPress={onDiscard}>
          <Text style={styles.note}>Discard</Text>
        </Pressable>
      </SafeAreaView>
    </View>
  </Modal>;
}
