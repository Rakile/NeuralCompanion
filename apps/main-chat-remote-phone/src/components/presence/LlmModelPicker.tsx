import { usePresentationStyle, useThemedStyles, useThemeColors } from '../../styles/ThemeContext';
import type { ThemeColors } from '../../styles/theme';
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { RemoteClient } from '../../api/client';
import type { LlmModelState } from '../../api/types';
import { remoteActionError } from '../../api/envelope';
import { colors, controlGlyphTypography, radii, spacing } from '../../styles/theme';

type Props = {
  client: RemoteClient;
  enabled: boolean;
  onSelected: () => Promise<unknown> | unknown;
  onClose: () => void;
  onBusyChange: (busy: boolean) => void;
};

export function LlmModelPicker({ client, enabled, onSelected, onClose, onBusyChange }: Props) {
  const styles = useThemedStyles(createStyles, 'LlmModelPicker');

  const editorial = usePresentationStyle() === 'editorial';
  const [providersOpen, setProvidersOpen] = React.useState<Record<string, boolean>>({});
  const [catalog, setCatalog] = React.useState<LlmModelState | null>(null);
  const [error, setError] = React.useState('');
  const [revision, setRevision] = React.useState(0);
  const [selecting, setSelecting] = React.useState('');
  const selectingRef = React.useRef(false);
  const alive = React.useRef(true);
  React.useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  React.useEffect(() => {
    let current = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setCatalog(null);
    setError('');
    if (!enabled) return;
    const load = async () => {
      try {
        const next = await client.llmModels();
        if (!current) return;
        setCatalog(next);
        if (next.loading) timer = setTimeout(load, 1200);
      } catch (exc) {
        if (current) setError(exc instanceof Error ? exc.message : 'Models could not be loaded.');
      }
    };
    void load();
    return () => {
      current = false;
      if (timer) clearTimeout(timer);
    };
  }, [client, client.identityKey, enabled, revision]);

  const select = async (providerId: string, modelId: string) => {
    if (!enabled || selectingRef.current) return;
    selectingRef.current = true;
    onBusyChange(true);
    setSelecting(`${providerId}:${modelId}`);
    setError('');
    try {
      const result = await client.selectLlmModel(providerId, modelId);
      const failure = remoteActionError(result, 'Model could not be changed.');
      if (failure) throw new Error(failure);
      if (!alive.current) return;
      await Promise.resolve(onSelected()).catch(() => undefined);
      if (alive.current) onClose();
    } catch (exc) {
      if (alive.current) setError(exc instanceof Error ? exc.message : 'Model could not be changed.');
    } finally {
      selectingRef.current = false;
      onBusyChange(false);
      if (alive.current) setSelecting('');
    }
  };

  if (!enabled) return <Text style={styles.status}>Connect to the desktop to choose a reply model.</Text>;
  return (
    <View style={styles.content}>
      <Text style={styles.help}>Choose which model answers your next message.</Text>
      {error ? <Text accessibilityRole="alert" style={styles.error}>{error}</Text> : null}
      {!catalog && !error ? <Text style={styles.status}>Loading available models…</Text> : null}
      {catalog?.message ? <Text style={styles.status}>{catalog.message}</Text> : null}
      {catalog?.providers.map((provider) => (
        <View key={provider.id} style={styles.provider}>
          {editorial ? <Pressable accessibilityRole="button" accessibilityLabel={`${provider.label} models`}
            accessibilityState={{expanded: providersOpen[provider.id] ?? provider.models.some(model => model.selected)}}
            style={styles.providerDisclosure} onPress={()=>setProvidersOpen(open=>({...open,[provider.id]:!(open[provider.id] ?? provider.models.some(model=>model.selected))}))}>
            <View style={{flex:1}}><Text style={styles.providerName}>{provider.label}</Text><Text style={styles.status}>{provider.models.find(model=>model.selected)?.label || `${provider.models.length} models`}</Text></View>
            <Text style={styles.marker}>{(providersOpen[provider.id] ?? provider.models.some(model=>model.selected)) ? '−' : '+'}</Text>
          </Pressable> : <Text style={styles.providerName}>{provider.label}</Text>}
          {provider.loading ? <Text style={styles.status}>Loading models…</Text> : null}
          {provider.message ? <Text style={styles.status}>{provider.message}</Text> : null}
          {(!editorial || (providersOpen[provider.id] ?? provider.models.some(model=>model.selected))) ? provider.models.map((model) => (
            <Pressable
              key={model.id}
              accessibilityRole="button"
              accessibilityLabel={`${model.label}${model.selected ? ', selected model' : ''}`}
              accessibilityState={{ selected: model.selected, disabled: Boolean(selecting) || !provider.available }}
              disabled={Boolean(selecting) || !provider.available}
              onPress={() => void select(provider.id, model.id)}
              style={[styles.model, model.selected && styles.selected, editorial && styles.editorialModel]}
            >
              <Text style={styles.name}>{model.label}</Text>
              <Text style={styles.marker}>{selecting === `${provider.id}:${model.id}` ? 'Switching…' : model.selected ? '✓' : '›'}</Text>
            </Pressable>
          )) : null}
        </View>
      ))}
      {!catalog?.loading ? (
        <Pressable accessibilityRole="button" disabled={Boolean(selecting)} onPress={() => setRevision((value) => value + 1)} style={styles.refresh}>
          <Text style={styles.refreshText}>Refresh models</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  providerDisclosure: {minHeight: 60, flexDirection: "row", alignItems: "center", gap: 12},
  editorialModel: {paddingHorizontal: 0, paddingVertical: 16},
  content: { gap: spacing.sm },
  help: { color: colors.muted, fontSize: 12, lineHeight: 18 },
  provider: { gap: spacing.sm },
  providerName: { color: colors.textSecondary, fontSize: 12, fontWeight: '800', marginTop: spacing.sm },
  model: { alignItems: 'center', borderColor: colors.borderSoft, borderRadius: radii.md, borderWidth: 1, flexDirection: 'row', gap: spacing.sm, minHeight: 52, padding: spacing.md },
  selected: { backgroundColor: colors.accentSoft, borderColor: colors.accentMuted },
  name: { color: colors.text, flex: 1, fontSize: 14, fontWeight: '600' },
  marker: { color: colors.accent, ...controlGlyphTypography },
  status: { color: colors.muted, fontSize: 12, lineHeight: 18 },
  error: { color: colors.danger, fontSize: 13, lineHeight: 18 },
  refresh: { alignItems: 'center', justifyContent: 'center', minHeight: 44 },
  refreshText: { color: colors.accent, fontSize: 13, fontWeight: '700' },
});
