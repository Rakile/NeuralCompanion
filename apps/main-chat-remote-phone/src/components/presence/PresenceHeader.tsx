import { useThemedStyles, useThemeColors } from '../../styles/ThemeContext';
import type { ThemeColors } from '../../styles/theme';
import React from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';

import type { RemoteClient } from '../../api/client';
import type { MuseTalkState, PresenceState } from '../../api/types';
import type { VoiceThreadFrame } from '../../hooks/usePresenceSpectrum';
import type { CompanionDisplayMode } from '../../utils/companionDisplayMode';
import { COMPANION_DISPLAY_MODES, companionDisplayModeLabel } from '../../utils/companionDisplayMode';
import { presenceHeaderVisibility } from '../../utils/presenceControls';
import type { VoiceThreadPalette } from '../../utils/presenceControls';
import { colors, spacing } from '../../styles/theme';
import { LivingVoiceThread } from './LivingVoiceThread';
import { MoodAvatar } from './MoodAvatar';

type PresenceHeaderProps = {
  presence: PresenceState | null;
  musetalk?: MuseTalkState;
  client: RemoteClient;
  frame: VoiceThreadFrame;
  reduceMotion?: boolean;
  mode: CompanionDisplayMode;
  onModeChange: (mode: CompanionDisplayMode) => void;
  onAvatarLongPress: () => void;
  paletteMode: VoiceThreadPalette;
  showControls: boolean;
  showThread?: boolean;
  compact?: boolean;
};

export function PresenceHeader({
  presence,
  musetalk,
  client,
  frame,
  reduceMotion = false,
  mode,
  onModeChange,
  onAvatarLongPress,
  paletteMode,
  showControls,
  showThread = true,
  compact = false,
}: PresenceHeaderProps) {
  const styles = useThemedStyles(createStyles);
  const [selectorOpen, setSelectorOpen] = React.useState(false);

  const activity = presence?.activity || 'ready';
  const mood = presence?.mood || 'neutral';
  const visible = presenceHeaderVisibility(showControls);
  // View navigation is independent of the optional identity/wave controls.
  if (compact) return <View style={styles.compactHeader}>
    <Text numberOfLines={1} style={styles.compactName}>{presence?.persona?.name || 'Companion'}</Text>
    <Pressable accessibilityRole="button" accessibilityLabel="Choose chat view"
      accessibilityValue={{text: companionDisplayModeLabel(mode)}} accessibilityState={{expanded:selectorOpen}}
      onPress={() => setSelectorOpen(true)} style={styles.selector}>
      <Text style={styles.selectorText}>{companionDisplayModeLabel(mode)} ⌄</Text>
    </Pressable>
    <Modal transparent visible={selectorOpen} animationType="fade" onRequestClose={() => setSelectorOpen(false)}>
      <Pressable accessibilityLabel="Dismiss chat view selector" onPress={() => setSelectorOpen(false)} style={styles.selectorBackdrop}>
        <View accessibilityViewIsModal style={styles.selectorMenu}>
          {COMPANION_DISPLAY_MODES.map(value => <Pressable key={value} accessibilityRole="radio"
            accessibilityLabel={`${companionDisplayModeLabel(value)} chat view`} accessibilityState={{checked:mode === value}}
            onPress={() => {setSelectorOpen(false); onModeChange(value);}} style={[styles.selectorOption, mode === value && styles.modeActive]}>
            <Text style={styles.selectorText}>{companionDisplayModeLabel(value)}{mode === value ? ' ✓' : ''}</Text>
          </Pressable>)}
        </View>
      </Pressable>
    </Modal>
  </View>;
  if (!showControls && !showThread) return null;
  return (
    <View style={[styles.container, !showControls && styles.threadOnly]}>
      {visible.identity && !compact ? <View style={styles.identity}>
        <MoodAvatar presence={presence} musetalk={musetalk} client={client} variant="header" onLongPress={onAvatarLongPress} />
        <View style={styles.copy}>
          <Text style={styles.name}>{presence?.persona?.name || 'Companion'}</Text>
          <Text style={styles.state}>{presence?.state_label || 'Ready'} · {mood}</Text>
        </View>
      </View> : null}
      {visible.thread && showThread && !compact ? <LivingVoiceThread activity={activity} mood={mood} frame={frame} compact heightOverride={58} reduceMotion={reduceMotion} paletteMode={paletteMode} /> : null}
      {visible.modes ? <View accessibilityRole="tablist" style={styles.modes}>
        {COMPANION_DISPLAY_MODES.map((value) => (
          <Pressable
            accessibilityRole="tab"
            accessibilityLabel={`${companionDisplayModeLabel(value)} chat view`}
            accessibilityState={{ selected: mode === value }}
            key={value}
            onPress={() => onModeChange(value)}
            style={[styles.mode, mode === value && styles.modeActive]}
          >
            <Text style={[styles.modeText, mode === value && styles.modeTextActive]}>
              {companionDisplayModeLabel(value)}
            </Text>
          </Pressable>
        ))}
      </View> : null}
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  compactHeader: {backgroundColor:colors.background,flexDirection:'row',alignItems:'center',gap:8,paddingHorizontal:spacing.md,paddingVertical:spacing.xs},
  compactName: {flex:1,minWidth:0,color:colors.text,fontSize:16,fontWeight:'700'},
  selector: {minHeight:44,maxWidth:'65%',justifyContent:'center',paddingHorizontal:12,borderWidth:1,borderColor:colors.border,borderRadius:12,backgroundColor:colors.panel},
  selectorText: {color:colors.text,fontSize:13,fontWeight:'600'},
  selectorBackdrop: {flex:1,backgroundColor:'rgba(0,0,0,0.45)',justifyContent:'center',padding:spacing.lg},
  selectorMenu: {backgroundColor:colors.panel,borderRadius:16,padding:8,gap:4,width:'100%',maxWidth:400,alignSelf:'center'},
  selectorOption: {minHeight:48,justifyContent:'center',paddingHorizontal:16,paddingVertical:12,borderRadius:10},
  container: { backgroundColor: colors.background, gap: spacing.xs, paddingHorizontal: spacing.lg, paddingVertical: spacing.xs },
  threadOnly: { paddingBottom: spacing.xs, paddingTop: spacing.xs },
  identity: { alignItems: 'center', flexDirection: 'row', gap: spacing.sm },
  copy: { flex: 1 },
  name: { color: colors.text, fontSize: 18, fontWeight: '900' },
  state: { color: colors.muted, fontSize: 12, marginTop: 2, textTransform: 'capitalize' },
  modes: { flexDirection: 'row', gap: spacing.xs },
  mode: { alignItems: 'center', borderColor: colors.border, borderRadius: 999, borderWidth: 1, flex: 1, justifyContent: 'center', minHeight: 44, paddingHorizontal: 8 },
  modeActive: { backgroundColor: colors.accentSoft, borderColor: colors.accent },
  modeText: { color: colors.muted, fontSize: 10, fontWeight: '800', textAlign: 'center' },
  modeTextActive: { color: colors.text },
});
