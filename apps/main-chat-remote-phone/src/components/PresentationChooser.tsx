import React from 'react';
import {Pressable, StyleSheet, Text, View} from 'react-native';
import {useThemedStyles} from '../styles/ThemeContext';
import type {ThemeColors} from '../styles/theme';
import type {PresentationStyle} from '../styles/presentation';

const options = [
  {id: 'classic', title: 'Classic', detail: 'Original design and your saved color theme.'},
  {id: 'editorial', title: 'Editorial', detail: 'Open layouts, warm ivory text and copper accents.'},
] as const;
export function PresentationChooser({value, onChange}: {
  value: PresentationStyle; onChange: (value: PresentationStyle) => void;
}) {
  const styles = useThemedStyles(createStyles);
  return <View accessibilityRole="radiogroup" accessibilityLabel="Interface design">
    {options.map(option => <Pressable key={option.id} accessibilityRole="radio"
      accessibilityLabel={`${option.title} design`} accessibilityState={{checked: value === option.id}}
      onPress={() => onChange(option.id)} style={styles.option}>
      <Text style={[styles.marker, value === option.id && styles.selected]}>{value === option.id ? '●' : '○'}</Text>
      <View style={styles.copy}><Text style={styles.title}>{option.title}</Text>
        <Text style={styles.detail}>{option.detail}</Text></View>
    </Pressable>)}
    <Text style={styles.note}>Switch anytime. Your conversation and playback stay active.</Text>
  </View>;
}
const createStyles = (colors: ThemeColors) => StyleSheet.create({
  option: {minHeight: 68, flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: colors.borderSoft},
  marker: {color: colors.muted, fontSize: 24}, selected: {color: colors.accent},
  copy: {flex: 1}, title: {color: colors.text, fontSize: 16, fontWeight: '600'},
  detail: {color: colors.muted, fontSize: 13, lineHeight: 19, marginTop: 4},
  note: {color: colors.muted, fontSize: 12, lineHeight: 18, marginTop: 12},
});
