import React from 'react';
import { Pressable, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import type { PersonaRuleCatalog, PersonaTechnicalRules } from '../../api/types';
import { useThemedStyles, useThemeColors } from '../../styles/ThemeContext';
import type { ThemeColors } from '../../styles/theme';

export function PersonaRulesEditor({ rules, catalog, disabled, onChange }: {
  rules: PersonaTechnicalRules; catalog: PersonaRuleCatalog; disabled: boolean;
  onChange: (rules: PersonaTechnicalRules) => void;
}) {
  const styles = useThemedStyles(createStyles);
  const colors = useThemeColors();
  const [kind, setKind] = React.useState<'avatar' | 'tts'>('avatar');
  const [selected, setSelected] = React.useState({ avatar: catalog.activeAvatar, tts: catalog.activeTts });
  const [choosing, setChoosing] = React.useState(false);
  const providers = catalog[kind];
  const provider = providers.find(row => row.id === selected[kind]) ?? providers[0];
  const entry = provider ? rules[kind][provider.id] : undefined;
  const label = kind === 'avatar' ? 'Visual avatar' : 'TTS voice';
  const update = (patch: Partial<{ enabled: boolean; text: string }>) => {
    if (!provider || disabled) return;
    onChange({ ...rules, [kind]: { ...rules[kind], [provider.id]: {
      enabled: entry?.enabled ?? false, text: entry?.text ?? provider.defaultText, ...patch,
    } } });
  };
  return <View style={styles.root}>
    <Text style={styles.title}>Provider rules</Text>
    <View style={styles.tabs}>
      {(['avatar', 'tts'] as const).map(value => <Pressable key={value} accessibilityRole="tab"
        accessibilityState={{ selected: value === kind }} style={[styles.tab, value === kind && styles.selected]}
        onPress={() => { setKind(value); setChoosing(false); }}>
        <Text style={styles.text}>{value === 'avatar' ? 'Visual avatar' : 'TTS voice'}</Text>
      </Pressable>)}
    </View>
    <Pressable accessibilityRole="button" accessibilityLabel={`Choose ${label.toLowerCase()} provider`}
      accessibilityState={{ expanded: choosing }} style={styles.button} onPress={() => setChoosing(!choosing)}>
      <Text style={styles.text}>{provider?.label ?? 'No providers available'} ▾</Text>
    </Pressable>
    {choosing ? <View>{providers.map(row => <Pressable key={row.id} accessibilityRole="radio"
      accessibilityState={{ checked: row.id === provider?.id }} style={styles.button}
      onPress={() => { setSelected({ ...selected, [kind]: row.id }); setChoosing(false); }}>
      <Text style={styles.text}>{row.label}{row.id === provider?.id ? ' ✓' : ''}</Text>
    </Pressable>)}</View> : null}
    <View style={styles.toggle}>
      <Text style={[styles.text, styles.grow]}>Override for this persona</Text>
      <Switch accessibilityLabel={`Override ${label.toLowerCase()} rules`} disabled={disabled || !provider}
        value={entry?.enabled ?? false} onValueChange={enabled => update({ enabled })}
        trackColor={{ true: colors.accent, false: colors.border }} />
    </View>
    <Text style={styles.help}>{entry?.enabled ? 'Custom rules for this provider.' : 'Inherited provider defaults.'}</Text>
    <TextInput accessibilityLabel={`${label} rules`} multiline textAlignVertical="top" maxLength={100000}
      editable={!disabled && !!entry?.enabled} value={entry?.enabled ? entry.text : provider?.defaultText ?? ''}
      onChangeText={text => update({ text })} style={[styles.input, entry?.enabled && styles.selected]}
      placeholder="No default rules for this provider." placeholderTextColor={colors.muted} />
    <Pressable accessibilityRole="button" disabled={disabled || !provider || !entry?.enabled}
      style={styles.button} onPress={() => update({ text: provider?.defaultText ?? '' })}>
      <Text style={styles.text}>Copy provider default</Text>
    </Pressable>
    <Text style={styles.help}>Each provider keeps its own rules. Turning an override off keeps your draft. This does not switch the active provider.</Text>
    {catalog.hasLegacy ? <View style={styles.legacy}>
      <View style={styles.toggle}>
        <Text style={[styles.text, styles.grow]}>Use combined custom rules</Text>
        <Switch accessibilityLabel="Use combined custom rules" disabled={disabled} value={rules.legacy_enabled}
          onValueChange={legacy_enabled => onChange({ ...rules, legacy_enabled })}
          trackColor={{ true: colors.accent, false: colors.border }} />
      </View>
      <Text style={styles.help}>{rules.legacy_enabled
        ? 'Your existing combined rules currently take priority. Turn this off to use the separate provider rules.'
        : 'Combined rules are preserved below, but separate provider rules will be used.'}</Text>
    </View> : null}
  </View>;
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  root: { gap: 8, marginVertical: 12 },
  title: { color: colors.text, fontSize: 18, fontWeight: '700' },
  text: { color: colors.text, fontSize: 15 },
  help: { color: colors.muted, fontSize: 13, lineHeight: 19 },
  tabs: { flexDirection: 'row', gap: 8 },
  tab: { flex: 1, minHeight: 48, padding: 12, borderBottomWidth: 2, borderColor: colors.border },
  selected: { borderColor: colors.accent },
  button: { minHeight: 48, padding: 12, justifyContent: 'center', backgroundColor: colors.panelAlt, borderRadius: 12 },
  toggle: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 48 },
  grow: { flex: 1 },
  input: { minHeight: 170, color: colors.text, backgroundColor: colors.panel, borderWidth: 1,
    borderColor: colors.border, borderRadius: 14, padding: 14, fontSize: 16, lineHeight: 23 },
  legacy: { borderTopWidth: 1, borderColor: colors.border, paddingTop: 8 },
});
