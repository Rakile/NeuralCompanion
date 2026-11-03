import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import type { RemoteClient } from '../../api/client';
import type { VoiceState } from '../../api/types';
import { remoteActionError } from '../../api/envelope';
import { usePresentationStyle, useThemedStyles } from '../../styles/ThemeContext';
import { controlGlyphTypography, radii, spacing, type ThemeColors } from '../../styles/theme';

type Props = {
  client: RemoteClient;
  enabled: boolean;
  onSelected: () => Promise<unknown> | unknown;
  onClose: () => void;
  onBusyChange: (busy: boolean) => void;
};

export function VoicePicker({ client, enabled, onSelected, onClose, onBusyChange }: Props) {
  const styles = useThemedStyles(createStyles, 'VoicePicker');
  const editorial = usePresentationStyle() === 'editorial';
  const [helpOpen, setHelpOpen] = React.useState(false);
  const [catalog, setCatalog] = React.useState<VoiceState | null>(null);
  const [error, setError] = React.useState('');
  const [revision, setRevision] = React.useState(0);
  const [selecting, setSelecting] = React.useState('');
  const busy = React.useRef(false);
  const generation = React.useRef(0);
  React.useEffect(() => {
    const currentGeneration = ++generation.current;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setCatalog(null);
    setError('');
    const load = async () => {
      try {
        const next = await client.voices();
        if (currentGeneration !== generation.current) return;
        setCatalog(next);
        if (next.loading) timer = setTimeout(load, 800);
      } catch (exc) {
        if (currentGeneration === generation.current) {
          setError(exc instanceof Error ? exc.message : 'Voices could not be loaded.');
        }
      }
    };
    if (enabled) void load();
    return () => {
      generation.current += 1;
      if (timer) clearTimeout(timer);
      busy.current = false;
      setSelecting('');
      onBusyChange(false);
    };
  }, [client, client.identityKey, enabled, revision, onBusyChange]);

  const select = async (voiceId: string) => {
    if (!enabled || !catalog?.available || busy.current) return;
    const currentGeneration = generation.current;
    const current = () => currentGeneration === generation.current;
    busy.current = true;
    onBusyChange(true);
    setSelecting(voiceId);
    setError('');
    try {
      const result = await client.selectVoice(voiceId);
      const failure = remoteActionError(result, 'Voice could not be changed.');
      if (failure) throw new Error(failure);
      if (!current()) return;
      await Promise.resolve(onSelected()).catch(() => undefined);
      if (current()) onClose();
    } catch (exc) {
      if (current()) setError(exc instanceof Error ? exc.message : 'Voice could not be changed.');
    } finally {
      if (current()) {
        busy.current = false;
        setSelecting('');
        onBusyChange(false);
      }
    }
  };

  if (!enabled) return <Text style={styles.status}>Connect to the desktop to choose a voice.</Text>;
  return (
    <View style={styles.content}>
      {editorial ? <Text style={styles.current}>{catalog?.items.find(voice => voice.selected)?.label || 'Choose a voice'}</Text> : null}
      {!editorial || helpOpen ? <Text style={styles.help}>Choose a voice for future speech. Switching persona restores its saved voice. Audio already generated keeps its original voice.</Text> : null}
      {editorial ? <Pressable accessibilityRole="button" accessibilityState={{expanded:helpOpen}} style={styles.disclosure} onPress={()=>setHelpOpen(open=>!open)}><Text style={styles.help}>About voice changes <Text style={controlGlyphTypography}>{helpOpen ? '−' : '+'}</Text></Text></Pressable> : null}
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      {(!catalog && !error) || catalog?.loading ? <Text style={styles.status}>Loading voices…</Text> : null}
      {catalog?.message ? <Text style={styles.status}>{catalog.message}</Text> : null}
      {catalog?.items.map((voice) => (
        <Pressable key={voice.id} accessibilityRole="button"
          accessibilityLabel={`${voice.label}${voice.selected ? ', selected voice' : ''}`}
          accessibilityState={{ selected: voice.selected, disabled: Boolean(selecting) || !catalog.available }}
          disabled={Boolean(selecting) || !catalog.available}
          onPress={() => void select(voice.id)} style={[styles.voice, voice.selected && styles.selected, editorial && styles.editorialVoice]}>
          <Text style={styles.name}>{voice.label}</Text>
          <Text style={styles.marker}>{selecting === voice.id ? 'Switching…' : voice.selected ? '✓' : '›'}</Text>
        </Pressable>
      ))}
      {!catalog?.loading ? (
        <Pressable accessibilityRole="button" accessibilityLabel="Refresh voices" disabled={Boolean(selecting)} onPress={() => setRevision(value => value + 1)} style={styles.refresh}>
          <Text style={styles.marker}>Refresh voices</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  current: {color: colors.text, fontSize: 20, fontFamily: "serif", paddingVertical: 12},
  disclosure: {minHeight: 44, justifyContent: "center"},
  editorialVoice: {paddingHorizontal: 0, paddingVertical: 16},
  content: { gap: spacing.sm },
  help: { color: colors.muted, fontSize: 12, lineHeight: 18 },
  voice: { alignItems: 'center', borderColor: colors.borderSoft, borderRadius: radii.md, borderWidth: 1, flexDirection: 'row', gap: spacing.sm, minHeight: 52, padding: spacing.md },
  selected: { backgroundColor: colors.accentSoft, borderColor: colors.accentMuted },
  name: { color: colors.text, flex: 1, fontSize: 14, fontWeight: '600' },
  marker: { color: colors.accent, fontSize: 14 },
  status: { color: colors.muted, fontSize: 12, lineHeight: 18 },
  error: { color: colors.danger, fontSize: 13, lineHeight: 18 },
  refresh: { alignItems: 'center', justifyContent: 'center', minHeight: 44 },
});
