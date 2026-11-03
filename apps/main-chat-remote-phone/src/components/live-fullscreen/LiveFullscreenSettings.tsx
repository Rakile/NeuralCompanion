import { usePresentationStyle, useThemedStyles, useThemeColors } from '../../styles/ThemeContext';
import type { ThemeColors } from '../../styles/theme';
import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { PresenceActivity } from '../../api/types';
import type { VoiceThreadFrame } from '../../hooks/usePresenceSpectrum';
import { useReducedMotion } from '../../hooks/useReducedMotion';
import { colors, controlGlyphTypography, spacing } from '../../styles/theme';
import {
  importLiveFullscreenMedia,
  removePrivateLiveFullscreenMedia,
} from '../../utils/liveFullscreenMedia';
import { DEFAULT_LIVE_FULLSCREEN_SETTINGS } from '../../utils/liveFullscreenSettings';
import type {
  LiveFullscreenPalette,
  LiveFullscreenResizeMode,
  LiveFullscreenSettings as LiveFullscreenSettingsValue,
} from '../../utils/liveFullscreenSettings';
import {
  previewMicrophoneVuSpectrum,
  proceduralSpectrum,
  SPECTRUM_BARS,
  spectrumFrameIntervalMs,
} from '../../utils/liveFullscreenSpectrum';
import { LivingVoiceThread } from '../presence/LivingVoiceThread';
import { LiveFullscreenBackground } from './LiveFullscreenBackground';
import { LiveFullscreenSlider } from './LiveFullscreenSlider';

type Props = {
  settings: LiveFullscreenSettingsValue;
  onChange: (updates: Partial<LiveFullscreenSettingsValue>) => void;
};

type Option<T extends string> = { label: string; value: T };
type SpectrumActivity = 'idle' | 'listening' | 'thinking' | 'speaking';

function SettingsGroup({ title, children }: { title: string; children: React.ReactNode }) {
  const styles = useThemedStyles(createStyles, 'LiveFullscreenSettings');
  const editorial = usePresentationStyle() === 'editorial';

  return (
    <View style={[styles.group, editorial && styles.editorialGroup]}>
      <Text style={styles.groupTitle}>{title}</Text>
      {children}
    </View>
  );
}

function Toggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (value: boolean) => void;
}) {
  const styles = useThemedStyles(createStyles, 'LiveFullscreenSettings');
  const editorial = usePresentationStyle() === 'editorial';

  return (
    <View style={styles.toggleRow}>
      <Text style={styles.label}>{label}</Text>
      <Pressable
        accessibilityLabel={label}
        accessibilityRole="switch"
        accessibilityState={{ checked: value }}
        style={[styles.toggle, value && styles.toggleActive]}
        onPress={() => onChange(!value)}
      >
        <Text style={styles.buttonText}>{value ? 'On' : 'Off'}</Text>
      </Pressable>
    </View>
  );
}

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: Array<Option<T>>;
  onChange: (value: T) => void;
}) {
  const styles = useThemedStyles(createStyles, 'LiveFullscreenSettings');
  const editorial = usePresentationStyle() === 'editorial';

  return (
    <View style={styles.segmentGroup}>
      <Text style={styles.label}>{label}</Text>
      <View accessibilityLabel={label} accessibilityRole="radiogroup" style={styles.segmentRow}>
        {options.map((option) => (
          <Pressable
            key={option.value}
            accessibilityLabel={`${label}: ${option.label}`}
            accessibilityRole="radio"
            accessibilityState={{ checked: value === option.value }}
            style={[styles.segment, value === option.value && styles.segmentActive]}
            onPress={() => onChange(option.value)}
          >
            <Text style={[styles.segmentText, value === option.value && styles.segmentTextActive]}>
              {option.label}
            </Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

const activityOptions: Array<Option<SpectrumActivity>> = [
  { label: 'Idle', value: 'idle' },
  { label: 'Listen', value: 'listening' },
  { label: 'Think', value: 'thinking' },
  { label: 'Speak', value: 'speaking' },
];

const paletteOptions: Array<Option<LiveFullscreenPalette>> = [
  { label: 'Full spectrum', value: 'spectrum' },
  { label: 'Electric', value: 'electric' },
  { label: 'By state', value: 'state' },
];

const resizeOptions: Array<Option<LiveFullscreenResizeMode>> = [
  { label: 'Fill screen', value: 'fill' },
  { label: 'Fit inside', value: 'fit' },
];

export function LiveFullscreenSettings({ settings, onChange }: Props) {
  const styles = useThemedStyles(createStyles, 'LiveFullscreenSettings');
  const editorial = usePresentationStyle() === 'editorial';

  const reducedMotion = useReducedMotion();
  const [activity, setActivity] = React.useState<SpectrumActivity>('speaking');
  const [previewFrameTimeMs, setPreviewFrameTimeMs] = React.useState(0);
  const [previewLayout, setPreviewLayout] = React.useState({ width: 320, height: 280 });
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [displayOpen, setDisplayOpen] = React.useState(false);
  const [advancedBackground, setAdvancedBackground] = React.useState(false);
  const [advancedMotion, setAdvancedMotion] = React.useState(false);

  React.useEffect(() => {
    if (reducedMotion) {
      setPreviewFrameTimeMs(0);
      return undefined;
    }
    const startedAt = Date.now();
    const timer = setInterval(
      () => setPreviewFrameTimeMs(Math.max(0, Date.now() - startedAt)),
      spectrumFrameIntervalMs(settings.spectrumFps),
    );
    return () => clearInterval(timer);
  }, [reducedMotion, settings.spectrumFps]);

  const updateBackground = async (mediaType: 'image' | 'video') => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const imported = await importLiveFullscreenMedia(mediaType, settings.backgroundUri);
      if (imported) onChange(imported);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Background import failed.');
    } finally {
      setBusy(false);
    }
  };
  const chooseBundled = async (kind: 'bundled_still' | 'bundled_video' | 'none') => {
    await removePrivateLiveFullscreenMedia(settings.backgroundUri);
    onChange({ backgroundKind: kind, backgroundUri: '' });
    setError('');
  };
  const previewScale = settings.circleSizePct / 100;
  const previewBoxWidth = Math.max(140, previewLayout.width * 0.86) * previewScale;
  const previewBoxHeight = Math.max(54, Math.min(previewLayout.height * 0.38, 130) * previewScale);
  const previewTop = (previewLayout.height * settings.verticalPositionPct / 100) - previewBoxHeight / 2;
  const previewLeft = (
    previewLayout.width * settings.circleHorizontalPositionPct / 100
  ) - previewBoxWidth / 2;
  const energies = activity === 'idle'
    ? Array(SPECTRUM_BARS).fill(0)
    : proceduralSpectrum(
      previewFrameTimeMs / 1000,
      activity === 'thinking' ? 0.32 : 0.82,
    );
  const previewActivity: PresenceActivity = activity === 'idle' ? 'ready' : activity;
  const previewFrame: VoiceThreadFrame = {
    fps: settings.spectrumFps,
    energies: activity === 'listening' ? previewMicrophoneVuSpectrum(0.82) : energies,
    inputLevel: activity === 'listening' ? 0.82 : 0,
    frameTimeMs: previewFrameTimeMs,
    source: activity === 'listening' ? 'live' : 'procedural',
  };

  return (
    <View style={styles.root}>
      <View
        style={styles.preview}
        onLayout={(event) => {
          const { width, height } = event.nativeEvent.layout;
          if (width && height) setPreviewLayout({ width, height });
        }}
      >
        <LiveFullscreenBackground
          settings={settings}
          visible={!reducedMotion}
          visualReplyOpen={false}
          onError={setError}
        />
        <View
          style={[
            styles.previewSilk,
            {
              height: previewBoxHeight,
              left: previewLeft,
              top: previewTop,
              width: previewBoxWidth,
            },
          ]}
        >
          <LivingVoiceThread
            activity={previewActivity}
            mood="curious"
            frame={previewFrame}
            fullscreen
            heightOverride={previewBoxHeight}
            paletteMode={settings.palette}
            waveformDepthPct={settings.waveformDepthPct}
            glowStrengthPct={settings.glowStrengthPct}
            motionIntensityPct={settings.motionIntensityPct}
            reduceMotion={reducedMotion}
            lowPower={settings.spectrumFps <= 18}
          />
        </View>
        <View style={styles.previewBadge}>
          <Text style={styles.previewBadgeText}>LIVE PREVIEW</Text>
        </View>
      </View>

      <ScrollView style={styles.controls} contentContainerStyle={styles.controlsContent}>
        <SettingsGroup title="Background">
          <View style={styles.buttonGrid}>
            <Pressable accessibilityRole="button" style={styles.actionButton} onPress={() => void chooseBundled('bundled_still')}><Text style={styles.buttonText}>Still image</Text></Pressable>
            <Pressable accessibilityRole="button" style={styles.actionButton} onPress={() => void chooseBundled('bundled_video')}><Text style={styles.buttonText}>Moving background</Text></Pressable>
            <Pressable accessibilityRole="button" accessibilityState={{ disabled: busy }} style={styles.actionButton} disabled={busy} onPress={() => void updateBackground('image')}><Text style={styles.buttonText}>My image</Text></Pressable>
            <Pressable accessibilityRole="button" accessibilityState={{ disabled: busy }} style={styles.actionButton} disabled={busy} onPress={() => void updateBackground('video')}><Text style={styles.buttonText}>My video</Text></Pressable>
            <Pressable accessibilityRole="button" style={styles.actionButton} onPress={() => void chooseBundled('none')}><Text style={styles.buttonText}>Plain</Text></Pressable>
          </View>
          {busy ? <Text style={styles.detail}>Opening phone media library...</Text> : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}
          {editorial ? <Pressable accessibilityRole="button" accessibilityState={{ expanded: displayOpen }} onPress={() => setDisplayOpen(value => !value)} style={styles.editorialDisclosure}><Text style={styles.buttonText}>Display & intensity <Text style={controlGlyphTypography}>{displayOpen ? "−" : "+"}</Text></Text></Pressable> : null}
          {!editorial || displayOpen ? <>
          <Segmented label="Display mode" value={settings.backgroundResizeMode} options={resizeOptions} onChange={(backgroundResizeMode) => onChange({ backgroundResizeMode })} />
          <LiveFullscreenSlider label="Background intensity" value={settings.backgroundOpacityPct} minimum={0} maximum={200} onChange={(backgroundOpacityPct) => onChange({ backgroundOpacityPct })} />
          </> : null}
          <Pressable accessibilityRole="button" accessibilityState={{ expanded: advancedBackground }}
            style={editorial ? styles.editorialDisclosure : styles.actionButton} onPress={() => setAdvancedBackground(value => !value)}>
            <Text style={styles.buttonText}>{advancedBackground ? 'Hide adjustments' : 'Position, scale & softness'}</Text>
          </Pressable>
          {advancedBackground ? <View style={{ gap: spacing.md }}>
          <LiveFullscreenSlider label="Background scale" value={settings.backgroundScalePct} minimum={25} maximum={200} onChange={(backgroundScalePct) => onChange({ backgroundScalePct })} />
          <LiveFullscreenSlider label="Background horizontal position" value={settings.backgroundOffsetXPct} minimum={-100} maximum={100} onChange={(backgroundOffsetXPct) => onChange({ backgroundOffsetXPct })} />
          <LiveFullscreenSlider label="Background vertical position" value={settings.backgroundOffsetYPct} minimum={-100} maximum={100} onChange={(backgroundOffsetYPct) => onChange({ backgroundOffsetYPct })} />
          <LiveFullscreenSlider label="Background softness" value={settings.backgroundSoftnessPct} minimum={0} maximum={200} onChange={(backgroundSoftnessPct) => onChange({ backgroundSoftnessPct })} />
          <Pressable
            accessibilityLabel="Reset background transform"
            accessibilityRole="button"
            style={styles.actionButton}
            onPress={() => onChange({
              backgroundScalePct: DEFAULT_LIVE_FULLSCREEN_SETTINGS.backgroundScalePct,
              backgroundOffsetXPct: DEFAULT_LIVE_FULLSCREEN_SETTINGS.backgroundOffsetXPct,
              backgroundOffsetYPct: DEFAULT_LIVE_FULLSCREEN_SETTINGS.backgroundOffsetYPct,
            })}
          >
            <Text style={styles.buttonText}>Reset background transform</Text>
          </Pressable>
          </View> : null}
          <Toggle label="Pause MP4 for Visual Reply" value={settings.pauseVideoForVisual} onChange={(pauseVideoForVisual) => onChange({ pauseVideoForVisual })} />
        </SettingsGroup>
        <Pressable accessibilityRole="button" accessibilityState={{ expanded: advancedMotion }}
          style={editorial ? styles.editorialDisclosure : styles.actionButton} onPress={() => setAdvancedMotion(value => !value)}>
          <Text style={styles.buttonText}>{advancedMotion ? 'Hide animation controls' : 'Animation, reveal & gestures'}</Text>
        </Pressable>
        {advancedMotion ? <>
        <Segmented label="Preview state" value={activity} options={activityOptions} onChange={setActivity} />
        <SettingsGroup title="Voice silk">
          <Segmented label="Palette" value={settings.palette} options={paletteOptions} onChange={(palette) => onChange({ palette })} />
          <LiveFullscreenSlider label="Voice silk size" value={settings.circleSizePct} minimum={25} maximum={200} onChange={(circleSizePct) => onChange({ circleSizePct })} />
          <LiveFullscreenSlider label="Voice silk horizontal position" value={settings.circleHorizontalPositionPct} minimum={10} maximum={90} onChange={(circleHorizontalPositionPct) => onChange({ circleHorizontalPositionPct })} />
          <LiveFullscreenSlider label="Waveform depth" value={settings.waveformDepthPct} minimum={0} maximum={200} onChange={(waveformDepthPct) => onChange({ waveformDepthPct })} />
          <LiveFullscreenSlider label="Glow strength" value={settings.glowStrengthPct} minimum={0} maximum={200} onChange={(glowStrengthPct) => onChange({ glowStrengthPct })} />
          <LiveFullscreenSlider label="Audio smoothing" value={settings.audioSmoothingPct} minimum={0} maximum={200} onChange={(audioSmoothingPct) => onChange({ audioSmoothingPct })} />
          <LiveFullscreenSlider label="Voice silk FPS" value={settings.spectrumFps} minimum={12} maximum={60} step={1} suffix=" FPS" onChange={(spectrumFps) => onChange({ spectrumFps })} />
          <Text style={styles.detail}>Shared by Conversation, Companion, Portrait, Live Fullscreen, and this preview.</Text>
          <LiveFullscreenSlider label="Motion intensity" value={settings.motionIntensityPct} minimum={0} maximum={200} onChange={(motionIntensityPct) => onChange({ motionIntensityPct })} />
          <LiveFullscreenSlider label="Voice silk vertical position" value={settings.verticalPositionPct} minimum={10} maximum={90} onChange={(verticalPositionPct) => onChange({ verticalPositionPct })} />
          <Pressable
            accessibilityLabel="Reset voice silk transform"
            accessibilityRole="button"
            style={styles.actionButton}
            onPress={() => onChange({
              circleSizePct: DEFAULT_LIVE_FULLSCREEN_SETTINGS.circleSizePct,
              circleHorizontalPositionPct: DEFAULT_LIVE_FULLSCREEN_SETTINGS.circleHorizontalPositionPct,
              verticalPositionPct: DEFAULT_LIVE_FULLSCREEN_SETTINGS.verticalPositionPct,
            })}
          >
            <Text style={styles.buttonText}>Reset voice silk transform</Text>
          </Pressable>
        </SettingsGroup>

        <SettingsGroup title="Image reveal">
          <Toggle label="Reveal new Visual Replies" value={settings.autoRevealVisualReply} onChange={(autoRevealVisualReply) => onChange({ autoRevealVisualReply })} />
          <LiveFullscreenSlider label="Portal speed" value={settings.portalSpeedPct} minimum={25} maximum={200} onChange={(portalSpeedPct) => onChange({ portalSpeedPct })} />
          <LiveFullscreenSlider label="Edge softness" value={settings.edgeSoftnessPct} minimum={0} maximum={200} onChange={(edgeSoftnessPct) => onChange({ edgeSoftnessPct })} />
          <LiveFullscreenSlider label="Voice silk during reveal" value={settings.imageSpectrumOpacityPct} minimum={0} maximum={200} onChange={(imageSpectrumOpacityPct) => onChange({ imageSpectrumOpacityPct })} />
        </SettingsGroup>



        <SettingsGroup title="Gestures and feedback">
          <LiveFullscreenSlider label="Long-press time" value={settings.longPressSeconds} minimum={1} maximum={6} step={0.5} suffix="s" onChange={(longPressSeconds) => onChange({ longPressSeconds })} />
          <Toggle label="Slow hold vibration" value={settings.vibrationEnabled} onChange={(vibrationEnabled) => onChange({ vibrationEnabled })} />
          <Toggle label='Happy "plong" sound' value={settings.plongEnabled} onChange={(plongEnabled) => onChange({ plongEnabled })} />
        </SettingsGroup>
        </> : null}
      </ScrollView>
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  editorialGroup: { paddingHorizontal: 8, paddingVertical: 20, gap: 20 },
  editorialDisclosure: { minHeight: 52, justifyContent: "center", borderBottomWidth: 1, borderBottomColor: colors.borderSoft, paddingHorizontal: 8 },
  root: { flex: 1, minHeight: 420 },
  preview: {
    backgroundColor: '#000000',
    borderBottomColor: '#24405d',
    borderBottomWidth: 1,
    height: 156,
    minHeight: 120,
    overflow: 'hidden',
  },
  previewSilk: { justifyContent: 'center', position: 'absolute' },
  previewBadge: {
    backgroundColor: 'rgba(0,0,0,0.65)',
    borderColor: colors.accent,
    borderRadius: 9,
    borderWidth: 1,
    left: spacing.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    position: 'absolute',
    top: spacing.sm,
  },
  previewBadgeText: { color: colors.accent, fontSize: 10, fontWeight: '900', letterSpacing: 1 },
  controls: { flex: 1 },
  controlsContent: {
    gap: spacing.sm,
    padding: spacing.sm,
    paddingBottom: spacing.lg,
    paddingRight: 36,
  },
  group: {
    backgroundColor: colors.panel,
    borderColor: colors.border,
    borderRadius: 18,
    borderWidth: 1,
    gap: spacing.md,
    padding: spacing.md,
  },
  groupTitle: { color: colors.text, fontSize: 15, fontWeight: '900' },
  label: { color: colors.text, fontSize: 13, fontWeight: '700' },
  detail: { color: colors.muted, fontSize: 12 },
  error: { color: colors.danger, fontSize: 12 },
  toggleRow: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between' },
  toggle: {
    alignItems: 'center',
    borderColor: colors.border,
    borderRadius: 12,
    borderWidth: 1,
    minWidth: 58,
    minHeight: 44,
    justifyContent: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  toggleActive: { backgroundColor: colors.accentSoft, borderColor: colors.accent },
  segmentGroup: { gap: spacing.xs },
  segmentRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  segment: {
    alignItems: 'center',
    borderColor: colors.border,
    borderRadius: 12,
    borderWidth: 1,
    justifyContent: 'center',
    minHeight: 44,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  segmentActive: { backgroundColor: colors.accentSoft, borderColor: colors.accent },
  segmentText: { color: colors.muted, fontSize: 12, fontWeight: '700' },
  segmentTextActive: { color: colors.text },
  buttonGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  actionButton: {
    alignItems: 'center',
    borderColor: colors.border,
    borderRadius: 12,
    borderWidth: 1,
    justifyContent: 'center',
    minHeight: 44,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  buttonText: { color: colors.text, fontSize: 12, fontWeight: '800' },
});
