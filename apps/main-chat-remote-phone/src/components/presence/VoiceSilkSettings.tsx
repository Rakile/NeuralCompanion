import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { usePresentationStyle, useThemedStyles } from '../../styles/ThemeContext';
import { controlGlyphTypography, type ThemeColors } from '../../styles/theme';
import type { VoiceThreadFrame } from '../../hooks/usePresenceSpectrum';
import { useReducedMotion } from '../../hooks/useReducedMotion';
import type { VoiceThreadPalette } from '../../utils/presenceControls';
import { DEFAULT_SILK_SETTINGS, SILK_SLIDERS } from '../../utils/silkSettings';
import type { SilkSettings } from '../../utils/silkSettings';
import { VOICE_VISUALIZER_STYLES } from '../../utils/voiceVisualizer';
import type { VoiceVisualizerStyle } from '../../utils/voiceVisualizer';
import { LiveFullscreenSlider } from '../live-fullscreen/LiveFullscreenSlider';
import { LivingVoiceThread } from './LivingVoiceThread';
import { SilkSettingsContext } from './SilkSettingsContext';

type Props = { value: SilkSettings; palette: VoiceThreadPalette; onChange: (value: SilkSettings) => void;
  visualizerStyle: VoiceVisualizerStyle; onStyleChange: (style: VoiceVisualizerStyle) => void };

export function VoiceSilkSettings({ value, palette, onChange, visualizerStyle, onStyleChange }: Props) {
  const styles = useThemedStyles(createStyles, 'VoiceSilkSettings');
  const editorial = usePresentationStyle() === 'editorial';
  const [tuningOpen, setTuningOpen] = React.useState(false);
  const [helpOpen, setHelpOpen] = React.useState(false);
  const [styleOpen, setStyleOpen] = React.useState(false);
  const selectedStyle = VOICE_VISUALIZER_STYLES.find(option => option.value === visualizerStyle)!;
  const isSilk = visualizerStyle === 'silk';
  const [group, setGroup] = React.useState<'Voice' | 'Motion' | 'Light'>('Voice');
  const [preview, setPreview] = React.useState(false);
  const reduced = useReducedMotion();
  const [level, setLevel] = React.useState(0);
  React.useEffect(() => {
    if (!preview || reduced) { setLevel(0); return; }
    // Local visual rehearsal only: no audio player, microphone, network or speech requests.
    const started = Date.now();
    const timer = setInterval(() => {
      const t = (Date.now() - started) / 1000;
      const phrase = t % 4.3;
      setLevel(phrase > 3.1 ? 0 : .035 + .25 * Math.max(0, Math.sin(t * 12.7)) ** 2 * (.55 + .45 * Math.sin(t * 2.3) ** 2));
    }, 40);
    return () => clearInterval(timer);
  }, [preview, reduced]);
  const frame: VoiceThreadFrame = {
    enabled: preview, fps: 25, energies: [level, level * .7, level * .35],
    inputLevel: 0, frameTimeMs: 0, source: 'analyzed',
  };
  return <View style={styles.content}>
    <View style={styles.selector}>
      <Text style={styles.heading}>Visualizer style</Text>
      <Pressable accessibilityRole="combobox" accessibilityLabel="Visualizer style"
        accessibilityValue={{ text: selectedStyle.label }} accessibilityState={{ expanded: styleOpen }}
        style={[styles.selectButton, styleOpen && styles.selected]} onPress={() => setStyleOpen(open => !open)}>
        <Text style={styles.heading}>{selectedStyle.label}</Text><Text style={styles.chevron}>{styleOpen ? '⌃' : '⌄'}</Text>
      </Pressable>
      {styleOpen ? <View style={styles.menu}>{VOICE_VISUALIZER_STYLES.map(option => <Pressable key={option.value}
        accessibilityRole="button" accessibilityLabel={option.label} accessibilityHint={option.detail}
        accessibilityState={{ selected: visualizerStyle === option.value }}
        onPress={() => { onStyleChange(option.value); setStyleOpen(false); }}
        style={[styles.choice, visualizerStyle === option.value && styles.selected]}>
        <View style={styles.choiceCopy}><Text style={styles.heading}>{option.label}</Text><Text style={styles.detail}>{option.detail}</Text></View>
        {visualizerStyle === option.value ? <Text style={styles.chevron}>✓</Text> : null}
      </Pressable>)}</View> : <Text style={styles.detail}>{selectedStyle.detail}</Text>}
    </View>
    <SilkSettingsContext.Provider value={value}>
      <LivingVoiceThread activity={preview ? 'speaking' : 'ready'} mood="neutral" frame={frame} reduceMotion={reduced} paletteMode={palette} visualizerStyle={visualizerStyle} />
    </SilkSettingsContext.Provider>
    <Pressable accessibilityRole="button" accessibilityLabel={preview ? 'Stop visualizer preview' : 'Preview visualizer motion'} style={styles.button} onPress={() => setPreview(v => !v)}>
      <Text style={styles.buttonText}>{preview ? 'Stop preview' : 'Preview motion'}</Text>
    </Pressable>
    {editorial ? <><Text style={styles.detail}>{reduced ? "Reduce Motion is on. Changes save automatically." : "Silent preview · Changes save automatically"}</Text><Pressable accessibilityRole="button" accessibilityLabel="Visualizer adjustments" accessibilityState={{expanded:tuningOpen}} style={styles.editorialDisclosure} onPress={()=>setTuningOpen(open=>!open)}><Text style={styles.heading}>Voice, motion & light</Text><Text style={styles.chevron}>{tuningOpen ? "−" : "+"}</Text></Pressable></> : null}
    {!editorial ? <Text style={styles.detail}>{reduced ? 'System Reduce Motion is on. The visualizer stays still.' : 'Preview uses a silent speech rhythm. In chat, the visualizer follows the actual voice.'} Changes save automatically for chat, Companion, Portrait and Live view.</Text> : null}
    {!editorial || tuningOpen ? <>
    {isSilk ? <View accessibilityRole="tablist" style={styles.tabs}>
      {(['Voice', 'Motion', 'Light'] as const).map(name => <Pressable key={name} accessibilityRole="tab" accessibilityState={{ selected: group === name }}
        accessibilityLabel={`Silk ${name} controls`} style={[styles.tab, group === name && styles.selected, editorial && styles.editorialTab, editorial && group === name && styles.editorialTabSelected]} onPress={() => setGroup(name)}>
        <Text style={styles.buttonText}>{name}</Text>
      </Pressable>)}
    </View> : null}
    {editorial ? <Pressable accessibilityRole="button" accessibilityLabel="About visualizer adjustments" accessibilityState={{expanded:helpOpen}} style={styles.editorialDisclosure} onPress={()=>setHelpOpen(open=>!open)}><Text style={styles.detail}>About these controls</Text><Text style={styles.chevron}>{helpOpen ? "−" : "+"}</Text></Pressable> : null}
    {!editorial || helpOpen ? <Text style={styles.detail}>{!isSilk ? 'Each bar follows its own playback frequency range. Bass to treble runs left to right, or clockwise from the top of Halo. Gain and quiet voice curve adjust sensitivity; attack and release smooth the response. Microphone input shows its measured loudness. Audio volume is unchanged.'
      : group === 'Voice' ? 'Lower quiet voice curve lifts softer syllables. Attack controls response speed; release controls the fade.'
      : group === 'Motion' ? 'Seed chooses a flow pattern, not its strength. Higher variation lets currents drift and turn more. The same seed keeps your chosen character.'
      : 'Color response makes hues and saturation follow each syllable; 0% keeps steady state colors. A small radius keeps glow close to each thread. Density adds brightness, and core highlight adds a fine luminous centre. Ribbon height changes normal chat views.'}</Text> : null}
    {SILK_SLIDERS.filter(slider => isSilk ? slider.group === group : ['gain', 'quietLift', 'attack', 'release'].includes(slider.key)).map(slider => <LiveFullscreenSlider key={slider.key}
      label={slider.label} value={value[slider.key]} minimum={slider.minimum} maximum={slider.maximum}
      step={slider.step} suffix={slider.suffix} touchHeight={44}
      onChange={next => onChange({ ...value, [slider.key]: next })} />)}
    <Pressable accessibilityRole="button" accessibilityLabel={isSilk ? 'Reset silk to saved design' : 'Reset visualizer voice response'} style={styles.button}
      onPress={() => onChange(isSilk ? { ...DEFAULT_SILK_SETTINGS } : { ...value,
        gain: DEFAULT_SILK_SETTINGS.gain, quietLift: DEFAULT_SILK_SETTINGS.quietLift,
        attack: DEFAULT_SILK_SETTINGS.attack, release: DEFAULT_SILK_SETTINGS.release })}>
      <Text style={styles.buttonText}>{isSilk ? 'Reset to saved design' : 'Reset voice response'}</Text>
    </Pressable>
    </> : null}
  </View>;
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  editorialDisclosure: { minHeight: 52, borderBottomWidth: 1, borderBottomColor: colors.borderSoft, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  editorialTab: { backgroundColor: "transparent", borderRadius: 0, borderWidth: 0, borderBottomWidth: 2, borderBottomColor: "transparent" },
  editorialTabSelected: { borderBottomColor: colors.accent },
  content: { gap: 16 },
  selector: { gap: 8 },
  heading: { color: colors.text, fontSize: 14, fontWeight: '700' },
  selectButton: { minHeight: 48, padding: 12, borderRadius: 14, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.panelAlt, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  menu: { gap: 6 },
  choice: { minHeight: 60, borderRadius: 12, padding: 12, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.panelAlt, flexDirection: 'row', alignItems: 'center', gap: 10 },
  choiceCopy: { flex: 1, gap: 3 },
  chevron: { color: colors.accent, ...controlGlyphTypography },
  tabs: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  tab: { flexGrow: 1, flexBasis: 80, minHeight: 48, padding: 12, alignItems: 'center', justifyContent: 'center', borderRadius: 14, backgroundColor: colors.panelAlt },
  selected: { backgroundColor: colors.accentSoft, borderWidth: 1, borderColor: colors.accent },
  button: { minHeight: 48, padding: 12, borderRadius: 14, borderWidth: 1, borderColor: colors.border, alignItems: 'center', justifyContent: 'center' },
  buttonText: { color: colors.text, fontSize: 13, fontWeight: '700', textAlign: 'center' },
  detail: { color: colors.muted, fontSize: 12, lineHeight: 18 },
});
