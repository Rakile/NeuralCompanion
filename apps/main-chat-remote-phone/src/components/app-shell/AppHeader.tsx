import { useThemedStyles, useThemeColors, usePresentationStyle } from '../../styles/ThemeContext';
import type { ThemeColors } from '../../styles/theme';
import React from 'react';
import { Modal, Pressable, StyleSheet, Text, View, useWindowDimensions } from 'react-native';

import { colors, radii, spacing } from '../../styles/theme';
import type { EngineIndicatorStatus } from '../../utils/engineIndicator';

type AppHeaderProps = {
  companionName: string;
  demoMode: boolean;
  connected: boolean;
  runtimeRunning: boolean;
  engineStatus: EngineIndicatorStatus;
  onStartEngine: () => void;
  stateLabel: string;
  audioCount: number;
  playing: boolean;
  paused?: boolean;
  onOpenAudio: () => void;
  onOpenConnection: () => void;
  onOpenSettings?: () => void;
  avatar?: React.ReactNode;
};

export function AppHeader({
  companionName,
  demoMode,
  connected,
  runtimeRunning,
  engineStatus,
  onStartEngine,
  stateLabel,
  audioCount,
  playing,
  paused = false,
  onOpenAudio,
  onOpenConnection,
  onOpenSettings,
  avatar,
}: AppHeaderProps) {
  const styles = useThemedStyles(createStyles, 'AppHeader');
  const editorial = usePresentationStyle() === 'editorial';
  const [menuOpen, setMenuOpen] = React.useState(false);
  const compact = useWindowDimensions().width < 380;
  const connectionLabel = demoMode ? 'Demo' : connected ? 'Connected' : 'Reconnect';
  if (editorial) return <View style={styles.editorialHeader}>
    {avatar}
    <View style={styles.editorialIdentity}>
      <Text numberOfLines={1} style={styles.editorialName}>{companionName || 'NC Remote'}</Text>
      <Pressable accessibilityRole="button" accessibilityLabel={connectionLabel} onPress={onOpenConnection}
        style={styles.editorialStatus}>
        <View style={[styles.connectionDot,(connected || demoMode) && styles.connectionDotLive]}/>
        <Text style={styles.stateText}>{connectionLabel}</Text>
      </Pressable>
    </View>
    {engineStatus !== 'running' ? <Pressable accessibilityRole="button"
      accessibilityLabel={engineStatus === 'starting' ? 'Engine starting' : 'Engine stopped. Tap to start'}
      disabled={engineStatus !== 'stopped' || (!connected && !demoMode)} onPress={onStartEngine} style={styles.engineButton}>
      <View style={[styles.connectionDot, engineStatus === 'stopped' && styles.engineDotStopped]}/>
      <Text style={styles.engineText}>{engineStatus === 'starting' ? 'Starting' : 'Start'}</Text>
    </Pressable> : null}
    <Pressable accessibilityRole="button" accessibilityLabel="Companion menu" accessibilityState={{expanded:menuOpen}}
      onPress={()=>setMenuOpen(true)} style={styles.menuTrigger}><Text style={styles.menuGlyph}>⋮</Text></Pressable>
    <Modal transparent visible={menuOpen} animationType="fade" onRequestClose={()=>setMenuOpen(false)}>
      <View style={styles.menuBackdrop}>
        <Pressable accessibilityRole="button" accessibilityLabel="Dismiss companion menu" style={StyleSheet.absoluteFill} onPress={()=>setMenuOpen(false)}/>
        <View accessibilityViewIsModal style={styles.menuSheet}>
          <View style={styles.menuTitleRow}><Text style={styles.editorialName}>Companion</Text>
            <Pressable accessibilityRole="button" accessibilityLabel="Close companion menu" style={styles.menuTrigger} onPress={()=>setMenuOpen(false)}><Text style={styles.menuText}>Done</Text></Pressable></View>
          <Text style={styles.stateText}>Engine {engineStatus} · {stateLabel || 'Ready'}</Text>
          <Pressable accessibilityRole="button" accessibilityLabel="Phone audio" style={styles.menuRow} onPress={()=>{setMenuOpen(false);onOpenAudio();}}>
            <Text style={styles.menuText}>Voice & playback</Text><Text style={styles.stateText}>{paused?'Paused':playing?'Playing':`${audioCount} items`} ›</Text></Pressable>
          <Pressable accessibilityRole="button" accessibilityLabel="Desktop connection" style={styles.menuRow} onPress={()=>{setMenuOpen(false);onOpenConnection();}}>
            <Text style={styles.menuText}>Desktop connection</Text><Text style={styles.stateText}>{connectionLabel} ›</Text></Pressable>
          {onOpenSettings ? <Pressable accessibilityRole="button" accessibilityLabel="Settings" style={styles.menuRow} onPress={()=>{setMenuOpen(false);onOpenSettings();}}>
            <Text style={styles.menuText}>Settings</Text><Text style={styles.stateText}>›</Text></Pressable> : null}
        </View>
      </View>
    </Modal>
  </View>;
  return (
    <View style={styles.header}>
      <View style={styles.identity}>
        {avatar}
        <View style={styles.identityCopy}>
          <Text numberOfLines={1} maxFontSizeMultiplier={1.4} style={styles.name}>{companionName || 'NC Remote'}</Text>

        </View>
      </View>
      <View style={styles.actions}>
        {(playing || paused || audioCount > 0) ? (
          <Pressable
            accessibilityHint="Opens the phone audio queue"
            accessibilityLabel={paused ? 'Audio paused. Open audio to resume' : playing ? 'Audio playing' : `${audioCount} audio items`}
            accessibilityRole="button"
            hitSlop={8}
            onPress={onOpenAudio}
            style={[styles.iconButton, playing && styles.iconButtonActive]}
          >
            <View style={styles.audioBars} accessibilityElementsHidden>
              <View style={[styles.audioBar, styles.audioBarLow]} />
              <View style={styles.audioBar} />
              <View style={[styles.audioBar, styles.audioBarMid]} />
            </View>
          </Pressable>
        ) : null}
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={engineStatus === 'running' ? 'Engine running' : engineStatus === 'starting' ? 'Engine starting' : 'Engine stopped. Tap to start'}
          accessibilityState={{ disabled: engineStatus !== 'stopped' || (!connected && !demoMode), busy: engineStatus === 'starting' }}
          disabled={engineStatus !== 'stopped' || (!connected && !demoMode)}
          onPress={onStartEngine}
          style={styles.engineButton}
        >
          <View style={[styles.connectionDot, engineStatus === 'running' ? styles.connectionDotLive
            : engineStatus === 'stopped' ? styles.engineDotStopped : undefined]} />
          <Text style={styles.engineText}>Engine</Text>
        </Pressable>
        <Pressable
          accessibilityHint="Opens connection and pairing details"
          accessibilityLabel={connectionLabel}
          accessibilityRole="button"
          hitSlop={8}
          onPress={onOpenConnection}
          style={styles.connectionButton}
        >
          <View style={[styles.connectionDot, (connected || demoMode) && styles.connectionDotLive]} />
          {!compact ? <Text style={styles.connectionText}>{connectionLabel}</Text> : null}
        </Pressable>

      </View>
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  editorialHeader:{flexDirection:'row',alignItems:'center',gap:12,paddingHorizontal:20,paddingTop:10,paddingBottom:8,borderBottomWidth:StyleSheet.hairlineWidth,borderColor:colors.borderSoft},
  editorialIdentity:{flex:1,minWidth:0},
  editorialName:{fontFamily:'serif',fontSize:22,fontWeight:'400',color:colors.text},
  editorialStatus:{flexDirection:'row',gap:7,alignItems:'center',minHeight:32},
  menuTrigger:{minWidth:44,minHeight:44,alignItems:'center',justifyContent:'center'},
  menuGlyph:{fontSize:25,color:colors.accent},
  menuBackdrop:{flex:1,justifyContent:'flex-end',backgroundColor:'rgba(0,0,0,.55)'},
  menuSheet:{backgroundColor:colors.background,padding:24,paddingBottom:40,gap:12},
  menuTitleRow:{flexDirection:'row',alignItems:'center',justifyContent:'space-between'},
  menuRow:{minHeight:60,borderBottomWidth:StyleSheet.hairlineWidth,borderColor:colors.borderSoft,flexDirection:'row',alignItems:'center',justifyContent:'space-between',gap:12},
  menuText:{fontSize:16,color:colors.text},
  header: {
    alignItems: 'center',
    backgroundColor: colors.background,
    borderBottomColor: colors.borderSoft,
    borderBottomWidth: 0,
    flexDirection: 'row',
    minHeight: 74,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  identity: { alignItems: 'center', flex: 1, flexDirection: 'row', gap: spacing.sm, minWidth: 0 },
  mark: {
    alignItems: 'center',
    backgroundColor: colors.accentSoft,
    borderColor: colors.accentMuted,
    borderRadius: radii.md,
    borderWidth: 1,
    height: 38,
    justifyContent: 'center',
    width: 38,
  },
  markText: { color: colors.accent, fontSize: 17, fontWeight: '900' },
  identityCopy: { flex: 1, minWidth: 0, alignItems: 'center', paddingHorizontal: spacing.sm },
  eyebrow: { color: colors.muted, fontSize: 10, letterSpacing: 1.6, marginBottom: 4 },
  name: { color: colors.text, fontSize: 23, fontWeight: '600', letterSpacing: -0.6, textAlign: 'center' },
  stateRow: { alignItems: 'center', flexDirection: 'row', gap: 6, marginTop: 3 },
  stateDot: { backgroundColor: colors.warning, borderRadius: 999, height: 6, width: 6 },
  stateDotLive: { backgroundColor: colors.ok },
  stateText: { color: colors.muted, flexShrink: 1, fontSize: 11 },
  actions: { alignItems: 'center', flexDirection: 'row', gap: 6 },
  iconButton: {
    alignItems: 'center',
    borderColor: colors.borderSoft,
    borderRadius: radii.md,
    borderWidth: 1,
    height: 44,
    justifyContent: 'center',
    width: 44,
  },
  iconButtonActive: { backgroundColor: colors.accentSoft, borderColor: colors.accentMuted },
  settingsGlyph: { color: colors.text, fontSize: 19, lineHeight: 22 },
  connectionButton: {
    alignItems: 'center',
    borderColor: colors.borderSoft,
    borderRadius: radii.pill,
    borderWidth: 0,
    flexDirection: 'row',
    gap: 6,
    minHeight: 44,
    minWidth: 44,
    justifyContent: 'center',
    paddingHorizontal: 10,
  },
  connectionDot: { backgroundColor: colors.warning, borderRadius: 999, height: 11, width: 11 },
  connectionDotLive: { backgroundColor: colors.ok },
  engineDotStopped: { backgroundColor: colors.danger },
  engineButton: { alignItems: 'center', flexDirection: 'row', gap: 5, minHeight: 44, paddingHorizontal: 4 },
  engineText: { color: colors.textSecondary, fontSize: 11, fontWeight: '800' },
  connectionText: { color: colors.textSecondary, fontSize: 11, fontWeight: '800' },
  audioBars: { alignItems: 'flex-end', flexDirection: 'row', gap: 2, height: 16 },
  audioBar: { backgroundColor: colors.accent, borderRadius: 2, height: 15, width: 3 },
  audioBarLow: { height: 8 },
  audioBarMid: { height: 11 },
});
