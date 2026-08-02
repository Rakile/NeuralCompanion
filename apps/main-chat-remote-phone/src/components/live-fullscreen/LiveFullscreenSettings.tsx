import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { colors, spacing } from '../../styles/theme';
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
  directionalSpectrumSeconds,
  previewMicrophoneVuSpectrum,
  proceduralSpectrum,
  SPECTRUM_BARS,
  spectrumFrameIntervalMs,
} from '../../utils/liveFullscreenSpectrum';
import { CircularSpectrum } from './CircularSpectrum';
import type { SpectrumActivity } from './CircularSpectrum';
import { LiveFullscreenBackground } from './LiveFullscreenBackground';
import { LiveFullscreenSlider } from './LiveFullscreenSlider';

type Props = {
  settings: LiveFullscreenSettingsValue;
  onChange: (updates: Partial<LiveFullscreenSettingsValue>) => void;
};

type Option<T extends string> = { label: string; value: T };

function SettingsGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.group}>
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
  return (
    <View style={styles.toggleRow}>
      <Text style={styles.label}>{label}</Text>
      <Pressable style={[styles.toggle, value && styles.toggleActive]} onPress={() => onChange(!value)}>
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
  return (
    <View style={styles.segmentGroup}>
      <Text style={styles.label}>{label}</Text>
      <View style={styles.segmentRow}>
        {options.map((option) => (
          <Pressable
            key={option.value}
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
  const [activity, setActivity] = React.useState<SpectrumActivity>('speaking');
  const [previewFrameTimeMs, setPreviewFrameTimeMs] = React.useState(0);
  const [previewLayout, setPreviewLayout] = React.useState({ width: 320, height: 280 });
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    const startedAt = Date.now();
    const timer = setInterval(
      () => setPreviewFrameTimeMs(Math.max(0, Date.now() - startedAt)),
      spectrumFrameIntervalMs(settings.spectrumFps),
    );
    return () => clearInterval(timer);
  }, [settings.spectrumFps]);

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
  const previewBaseSize = Math.max(
    120,
    Math.min(previewLayout.width * 0.82, previewLayout.height * 0.82),
  );
  const previewBoxSize = previewBaseSize * settings.circleSizePct / 100;
  const previewTop = (previewLayout.height * settings.verticalPositionPct / 100) - previewBoxSize / 2;
  const previewLeft = (
    previewLayout.width * settings.circleHorizontalPositionPct / 100
  ) - previewBoxSize / 2;
  const energies = activity === 'idle'
    ? Array(SPECTRUM_BARS).fill(0)
    : proceduralSpectrum(
      directionalSpectrumSeconds(previewFrameTimeMs / 1000, settings.rotationSpeedPct),
      activity === 'thinking' ? 0.32 : 0.82,
    );
  const silentPreview = Array(SPECTRUM_BARS).fill(0);
  const previewOuterEnergies = activity === 'speaking' || activity === 'thinking'
    ? energies
    : silentPreview;
  const previewInnerEnergies = activity === 'listening'
    ? previewMicrophoneVuSpectrum(0.82)
    : silentPreview;

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
          visible
          visualReplyOpen={false}
          onError={setError}
        />
        <View
          style={[
            styles.previewSpectrum,
            {
              height: previewBoxSize,
              left: previewLeft,
              top: previewTop,
              width: previewBoxSize,
            },
          ]}
        >
          <CircularSpectrum
            activity={activity}
            outerEnergies={previewOuterEnergies}
            innerEnergies={previewInnerEnergies}
            palette={settings.palette}
            circleSizePct={100}
            waveformDepthPct={settings.waveformDepthPct}
            glowStrengthPct={settings.glowStrengthPct}
            motionIntensityPct={settings.motionIntensityPct}
            rotationSpeedPct={settings.rotationSpeedPct}
            barCount={settings.spectrumBarCount}
            frameTimeMs={previewFrameTimeMs}
          />
        </View>
        <View style={styles.previewBadge}>
          <Text style={styles.previewBadgeText}>LIVE PREVIEW</Text>
        </View>
      </View>

      <ScrollView style={styles.controls} contentContainerStyle={styles.controlsContent}>
        <Segmented label="Preview state" value={activity} options={activityOptions} onChange={setActivity} />
        <SettingsGroup title="Spectrum">
          <Segmented label="Palette" value={settings.palette} options={paletteOptions} onChange={(palette) => onChange({ palette })} />
          <LiveFullscreenSlider label="Circle size" value={settings.circleSizePct} minimum={25} maximum={200} onChange={(circleSizePct) => onChange({ circleSizePct })} />
          <LiveFullscreenSlider label="Circle horizontal position" value={settings.circleHorizontalPositionPct} minimum={10} maximum={90} onChange={(circleHorizontalPositionPct) => onChange({ circleHorizontalPositionPct })} />
          <LiveFullscreenSlider label="Waveform depth" value={settings.waveformDepthPct} minimum={0} maximum={200} onChange={(waveformDepthPct) => onChange({ waveformDepthPct })} />
          <LiveFullscreenSlider label="Glow strength" value={settings.glowStrengthPct} minimum={0} maximum={200} onChange={(glowStrengthPct) => onChange({ glowStrengthPct })} />
          <LiveFullscreenSlider label="Audio smoothing" value={settings.audioSmoothingPct} minimum={0} maximum={200} onChange={(audioSmoothingPct) => onChange({ audioSmoothingPct })} />
          <LiveFullscreenSlider label="Circle FPS" value={settings.spectrumFps} minimum={12} maximum={60} step={1} suffix=" FPS" onChange={(spectrumFps) => onChange({ spectrumFps })} />
          <LiveFullscreenSlider label="Motion intensity" value={settings.motionIntensityPct} minimum={0} maximum={200} onChange={(motionIntensityPct) => onChange({ motionIntensityPct })} />
          <LiveFullscreenSlider label="Rotation speed" value={settings.rotationSpeedPct} minimum={0} maximum={200} onChange={(rotationSpeedPct) => onChange({ rotationSpeedPct })} />
          <LiveFullscreenSlider label="Spectrum bars" value={settings.spectrumBarCount} minimum={16} maximum={96} step={4} suffix="" onChange={(spectrumBarCount) => onChange({ spectrumBarCount })} />
          <LiveFullscreenSlider label="Circle vertical position" value={settings.verticalPositionPct} minimum={10} maximum={90} onChange={(verticalPositionPct) => onChange({ verticalPositionPct })} />
          <Pressable
            style={styles.actionButton}
            onPress={() => onChange({
              circleSizePct: DEFAULT_LIVE_FULLSCREEN_SETTINGS.circleSizePct,
              circleHorizontalPositionPct: DEFAULT_LIVE_FULLSCREEN_SETTINGS.circleHorizontalPositionPct,
              verticalPositionPct: DEFAULT_LIVE_FULLSCREEN_SETTINGS.verticalPositionPct,
            })}
          >
            <Text style={styles.buttonText}>Reset circle transform</Text>
          </Pressable>
        </SettingsGroup>

        <SettingsGroup title="Image reveal">
          <Toggle label="Reveal new Visual Replies" value={settings.autoRevealVisualReply} onChange={(autoRevealVisualReply) => onChange({ autoRevealVisualReply })} />
          <LiveFullscreenSlider label="Portal speed" value={settings.portalSpeedPct} minimum={25} maximum={200} onChange={(portalSpeedPct) => onChange({ portalSpeedPct })} />
          <LiveFullscreenSlider label="Edge softness" value={settings.edgeSoftnessPct} minimum={0} maximum={200} onChange={(edgeSoftnessPct) => onChange({ edgeSoftnessPct })} />
          <LiveFullscreenSlider label="Spectrum during reveal" value={settings.imageSpectrumOpacityPct} minimum={0} maximum={200} onChange={(imageSpectrumOpacityPct) => onChange({ imageSpectrumOpacityPct })} />
        </SettingsGroup>

        <SettingsGroup title="Background">
          <View style={styles.buttonGrid}>
            <Pressable style={styles.actionButton} onPress={() => void chooseBundled('bundled_still')}><Text style={styles.buttonText}>Bundled still</Text></Pressable>
            <Pressable style={styles.actionButton} onPress={() => void chooseBundled('bundled_video')}><Text style={styles.buttonText}>Bundled MP4</Text></Pressable>
            <Pressable style={styles.actionButton} disabled={busy} onPress={() => void updateBackground('image')}><Text style={styles.buttonText}>Import image</Text></Pressable>
            <Pressable style={styles.actionButton} disabled={busy} onPress={() => void updateBackground('video')}><Text style={styles.buttonText}>Import MP4</Text></Pressable>
            <Pressable style={styles.actionButton} onPress={() => void chooseBundled('bundled_still')}><Text style={styles.buttonText}>Restore default</Text></Pressable>
            <Pressable style={styles.actionButton} onPress={() => void chooseBundled('none')}><Text style={styles.buttonText}>Clear</Text></Pressable>
          </View>
          {busy ? <Text style={styles.detail}>Opening phone media library...</Text> : null}
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <Segmented label="Display mode" value={settings.backgroundResizeMode} options={resizeOptions} onChange={(backgroundResizeMode) => onChange({ backgroundResizeMode })} />
          <LiveFullscreenSlider label="Background opacity / intensity" value={settings.backgroundOpacityPct} minimum={0} maximum={200} onChange={(backgroundOpacityPct) => onChange({ backgroundOpacityPct })} />
          <LiveFullscreenSlider label="Background scale" value={settings.backgroundScalePct} minimum={25} maximum={200} onChange={(backgroundScalePct) => onChange({ backgroundScalePct })} />
          <LiveFullscreenSlider label="Background horizontal position" value={settings.backgroundOffsetXPct} minimum={-100} maximum={100} onChange={(backgroundOffsetXPct) => onChange({ backgroundOffsetXPct })} />
          <LiveFullscreenSlider label="Background vertical position" value={settings.backgroundOffsetYPct} minimum={-100} maximum={100} onChange={(backgroundOffsetYPct) => onChange({ backgroundOffsetYPct })} />
          <LiveFullscreenSlider label="Background softness" value={settings.backgroundSoftnessPct} minimum={0} maximum={200} onChange={(backgroundSoftnessPct) => onChange({ backgroundSoftnessPct })} />
          <Pressable
            style={styles.actionButton}
            onPress={() => onChange({
              backgroundScalePct: DEFAULT_LIVE_FULLSCREEN_SETTINGS.backgroundScalePct,
              backgroundOffsetXPct: DEFAULT_LIVE_FULLSCREEN_SETTINGS.backgroundOffsetXPct,
              backgroundOffsetYPct: DEFAULT_LIVE_FULLSCREEN_SETTINGS.backgroundOffsetYPct,
            })}
          >
            <Text style={styles.buttonText}>Reset background transform</Text>
          </Pressable>
          <Toggle label="Pause MP4 for Visual Reply" value={settings.pauseVideoForVisual} onChange={(pauseVideoForVisual) => onChange({ pauseVideoForVisual })} />
        </SettingsGroup>

        <SettingsGroup title="Gestures and feedback">
          <LiveFullscreenSlider label="Long-press time" value={settings.longPressSeconds} minimum={1} maximum={6} step={0.5} suffix="s" onChange={(longPressSeconds) => onChange({ longPressSeconds })} />
          <Toggle label="Slow hold vibration" value={settings.vibrationEnabled} onChange={(vibrationEnabled) => onChange({ vibrationEnabled })} />
          <Toggle label='Happy "plong" sound' value={settings.plongEnabled} onChange={(plongEnabled) => onChange({ plongEnabled })} />
        </SettingsGroup>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, minHeight: 420 },
  preview: {
    backgroundColor: '#000000',
    borderBottomColor: '#24405d',
    borderBottomWidth: 1,
    flex: 1,
    minHeight: 210,
    overflow: 'hidden',
  },
  previewSpectrum: { position: 'absolute' },
  previewBadge: {
    backgroundColor: 'rgba(0,0,0,0.65)',
    borderColor: '#00eaff',
    borderRadius: 9,
    borderWidth: 1,
    left: spacing.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    position: 'absolute',
    top: spacing.sm,
  },
  previewBadgeText: { color: '#00eaff', fontSize: 10, fontWeight: '900', letterSpacing: 1 },
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
    borderRadius: 8,
    borderWidth: 1,
    gap: spacing.md,
    padding: spacing.md,
  },
  groupTitle: { color: '#ffffff', fontSize: 15, fontWeight: '900' },
  label: { color: colors.text, fontSize: 13, fontWeight: '700' },
  detail: { color: colors.muted, fontSize: 12 },
  error: { color: colors.danger, fontSize: 12 },
  toggleRow: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between' },
  toggle: {
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    minWidth: 58,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  toggleActive: { backgroundColor: '#005f73', borderColor: '#00eaff' },
  segmentGroup: { gap: spacing.xs },
  segmentRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  segment: {
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  segmentActive: { backgroundColor: '#004c66', borderColor: '#00eaff' },
  segmentText: { color: colors.muted, fontSize: 12, fontWeight: '700' },
  segmentTextActive: { color: '#ffffff' },
  buttonGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  actionButton: {
    borderColor: '#41617f',
    borderRadius: 6,
    borderWidth: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  buttonText: { color: '#ffffff', fontSize: 12, fontWeight: '800' },
});
