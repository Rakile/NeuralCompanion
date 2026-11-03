import React from 'react';
import { Keyboard, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import type { VisualAutoMode, VisualAutoStatus } from '../api/types';
import type { VisualDisplay } from '../utils/visualDisplay';
import { KeyboardSafeView } from './KeyboardSafeView';
import { usePresentationStyle, useThemeColors, useThemedStyles } from '../styles/ThemeContext';
import { controlGlyphTypography, type ThemeColors } from '../styles/theme';

type Props = {
  visible: boolean;
  display: VisualDisplay;
  status: VisualAutoStatus | null;
  busy: boolean;
  error: string;
  onDisplayChange: (value: VisualDisplay) => void;
  onAutoChange: (mode: VisualAutoMode, imagesPerBeat: number) => Promise<void>;
  onRefresh: () => Promise<void>;
  onClose: () => void;
};

const modes: { mode: VisualAutoMode; title: string; detail: string }[] = [
  { mode: 'off', title: 'Off', detail: 'Generate only when you ask.' },
  { mode: 'user', title: 'Every user reply', detail: 'After the assistant answers a text-only user message.' },
  { mode: 'assistant', title: 'Every assistant reply', detail: 'After each completed assistant reply.' },
  { mode: 'story', title: 'Story beats', detail: 'Use the first eligible replies in each active story beat.' },
];

export function VisualReplySettingsSheet({ visible, display, status, busy, error,
  onDisplayChange, onAutoChange, onRefresh, onClose }: Props) {
  const colors = useThemeColors();
  const editorial = usePresentationStyle() === 'editorial';
  const [ruleOpen, setRuleOpen] = React.useState(false);
  const styles = useThemedStyles(createStyles, 'VisualReplySettingsSheet');
  const choose = (mode: VisualAutoMode, quota = status?.images_per_beat ?? 1) => {
    if (status && !busy) void onAutoChange(mode, quota);
  };
  return <Modal visible={visible} animationType="slide" onShow={Keyboard.dismiss} onRequestClose={onClose}>
    <KeyboardSafeView active={visible}><SafeAreaView style={styles.screen}>
      <View style={styles.header}>
        <View><Text style={styles.title}>Visual Reply</Text><Text style={styles.subtitle}>Images for this conversation</Text></View>
        <Pressable accessibilityRole="button" accessibilityLabel="Done with Visual Reply settings" onPress={onClose} style={styles.done}>
          <Text style={styles.doneText}>Done</Text>
        </Pressable>
      </View>
      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.content}>
        <View style={[styles.card, editorial && styles.editorialSection]}>
          <Text style={styles.section}>Show images in chat</Text>
          {!editorial ? <Text style={styles.hint}>Changes apply to images already in the chat.</Text> : null}
          <View style={styles.row}>
            {(['fit', 'fill'] as const).map(layout => <Pressable key={layout} accessibilityRole="button"
              accessibilityLabel={layout === 'fit' ? 'Fit image' : 'Fill width'}
              accessibilityState={{ selected: display.layout === layout }}
              onPress={() => onDisplayChange({ ...display, layout })}
              style={[styles.option, display.layout === layout && styles.selected]}>
              <Text style={styles.optionText}>{layout === 'fit' ? 'Fit image' : 'Fill width'}</Text>
            </Pressable>)}
          </View>
          <Pressable accessibilityRole="switch" accessibilityLabel="Frame" accessibilityState={{ checked: display.frame }}
            onPress={() => onDisplayChange({ ...display, frame: !display.frame })} style={styles.toggle}>
            <Text style={styles.optionText}>Frame</Text><Text style={styles.toggleValue}>{display.frame ? 'On' : 'Off'}</Text>
          </Pressable>
        </View>
        <View style={[styles.card, editorial && styles.editorialSection]}>
          <Text style={styles.section}>Auto generate</Text>
          {editorial ? <Pressable accessibilityRole="button" accessibilityState={{ expanded: ruleOpen }} onPress={() => setRuleOpen(value => !value)} style={styles.toggle}><Text style={styles.optionText}>{modes.find(item => item.mode === status?.mode)?.title || "Unavailable"}</Text><Text style={[styles.toggleValue,controlGlyphTypography]}>{ruleOpen ? "−" : "+"}</Text></Pressable> : <Text style={styles.hint}>Choose one rule. Images use your desktop provider; chat and speech keep moving.</Text>}
          {(!editorial || ruleOpen) ? modes.map(item => <Pressable key={item.mode} accessibilityRole="radio"
            accessibilityLabel={item.title} accessibilityState={{ checked: status?.mode === item.mode, disabled: busy || !status }}
            disabled={busy || !status} onPress={() => choose(item.mode)}
            style={[styles.mode, editorial && styles.editorialMode, status?.mode === item.mode && styles.selected]}>
            <Text style={styles.optionText}>{status?.mode === item.mode ? '◉' : '○'}  {item.title}</Text>
            <Text style={styles.hint}>{item.detail}</Text>
          </Pressable>) : null}
          {status?.mode === 'story' ? <View style={styles.quota}>
            <Text style={styles.optionText}>Images per beat</Text>
            <View style={styles.row}>
              <Pressable accessibilityRole="button" accessibilityLabel="Fewer images per beat"
                disabled={busy || status.images_per_beat <= 1} onPress={() => choose('story', status.images_per_beat - 1)} style={styles.step}>
                <Text style={[styles.optionText,controlGlyphTypography]}>−</Text></Pressable>
              <Text style={styles.count}>{status.images_per_beat}</Text>
              <Pressable accessibilityRole="button" accessibilityLabel="More images per beat"
                disabled={busy || status.images_per_beat >= 5} onPress={() => choose('story', status.images_per_beat + 1)} style={styles.step}>
                <Text style={[styles.optionText,controlGlyphTypography]}>+</Text></Pressable>
            </View>
            <Text style={styles.hint}>{status.story_dormant ? 'Start a Story Plan to use this rule.'
              : `${status.beat_count} of ${status.images_per_beat} used in this beat.`}</Text>
          </View> : null}
          {status?.active ? <Text style={styles.hint}>Image request: {status.active}</Text> : null}
          {busy ? <Text style={styles.hint}>Saving…</Text> : null}
          {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
          <Pressable accessibilityRole="button" accessibilityLabel="Refresh Visual Reply settings" onPress={() => void onRefresh()} style={styles.refresh}>
            <Text style={styles.optionText}>Refresh</Text>
          </Pressable>
        </View>
      </ScrollView>
    </SafeAreaView></KeyboardSafeView>
  </Modal>;
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  editorialSection: { paddingHorizontal: 0, paddingVertical: 20, gap: 16 },
  editorialMode: { borderWidth: 0, borderBottomWidth: 1, borderRadius: 0, paddingHorizontal: 0 },
  screen: { flex: 1, backgroundColor: colors.background },
  header: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between', padding: 20 },
  title: { color: colors.text, fontSize: 26, fontWeight: '800' },
  subtitle: { color: colors.muted, fontSize: 14, marginTop: 4 },
  done: { borderColor: colors.border, borderWidth: 1, borderRadius: 12, minHeight: 44, justifyContent: 'center', paddingHorizontal: 16 },
  doneText: { color: colors.accent, fontWeight: '700' },
  content: { gap: 16, padding: 20, paddingBottom: 40 },
  card: { backgroundColor: colors.panel, borderColor: colors.border, borderWidth: 1, borderRadius: 18, gap: 12, padding: 16 },
  section: { color: colors.text, fontSize: 20, fontWeight: '800' },
  hint: { color: colors.muted, fontSize: 13, lineHeight: 19 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  option: { borderColor: colors.border, borderWidth: 1, borderRadius: 12, minHeight: 44, padding: 12, flex: 1 },
  selected: { borderColor: colors.accent, backgroundColor: colors.background },
  optionText: { color: colors.text, fontSize: 15, fontWeight: '700' },
  toggle: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', minHeight: 48 },
  toggleValue: { color: colors.accent, fontWeight: '800' },
  mode: { borderColor: colors.border, borderWidth: 1, borderRadius: 12, gap: 4, minHeight: 62, padding: 12 },
  quota: { gap: 10, marginTop: 8 },
  step: { borderColor: colors.border, borderWidth: 1, borderRadius: 10, minHeight: 44, minWidth: 44, alignItems: 'center', justifyContent: 'center' },
  count: { color: colors.text, fontSize: 20, fontWeight: '800', minWidth: 32, textAlign: 'center' },
  refresh: { borderColor: colors.border, borderWidth: 1, borderRadius: 10, alignItems: 'center', justifyContent: 'center', minHeight: 44 },
  error: { color: colors.danger, fontSize: 13 },
});
