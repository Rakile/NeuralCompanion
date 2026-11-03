import { useThemedStyles, useThemeColors } from '../styles/ThemeContext';
import type { ThemeColors } from '../styles/theme';
import React, { useEffect, useState } from 'react';
import { Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import type { PhoneSettings } from '../hooks/usePhoneSettings';
import { getIosLiveCapture } from '../native/iosLiveCapture';
import { androidBackgroundLivePlatformEligible, completeAndroidContinuousCaptureCapabilities,
  continuousCaptureEnabled } from '../native/iosContinuousCapturePolicy';
import { colors, spacing } from '../styles/theme';

type Props = {
  settings: Pick<PhoneSettings, 'allowBackgroundLive' | 'liveDuckingUseSystemDefault' | 'liveDuckingLevel'>;
  onChange: (updates: Partial<PhoneSettings>) => void;
};
const levels = [
  { value: 'min', label: 'Min' }, { value: 'mid', label: 'Med' }, { value: 'max', label: 'Max' },
] as const;

export function IosLiveAudioSettings({ settings, onChange }: Props) {
  const styles = useThemedStyles(createStyles);

  const [duckingSupported, setDuckingSupported] = useState(false);
  const [backgroundSupported, setBackgroundSupported] = useState(false);
  const [checking, setChecking] = useState(true);
  useEffect(() => {
    if (!continuousCaptureEnabled) return;
    let alive = true;
    getIosLiveCapture().capabilities().then((caps) => {
      if (!alive) return;
      setDuckingSupported(caps.available && caps.duckingSupported === true);
      setBackgroundSupported(Platform.OS === 'android'
        ? androidBackgroundLivePlatformEligible() && completeAndroidContinuousCaptureCapabilities(caps)
        : caps.available && caps.backgroundLiveVersion === 1 && caps.playbackGuardVersion === 1);
    }).catch(() => undefined).finally(() => { if (alive) setChecking(false); });
    return () => { alive = false; };
  }, []);
  if (!continuousCaptureEnabled) return null;
  const disabled = !duckingSupported || settings.liveDuckingUseSystemDefault;
  const defaultDisabled = !duckingSupported && settings.liveDuckingUseSystemDefault;
  const androidBackgroundUnavailable = Platform.OS === 'android' && !backgroundSupported;
  const backgroundDisabled = androidBackgroundUnavailable || (!backgroundSupported && !settings.allowBackgroundLive);
  const backgroundChecked = androidBackgroundUnavailable ? false : settings.allowBackgroundLive;
  return (
    <View style={styles.group}>
      <View style={styles.row}>
        <Text style={styles.detail}>Allow background Live Mode</Text>
        <Pressable accessibilityRole="switch" accessibilityLabel="Allow background Live Mode"
          accessibilityState={{ checked: backgroundChecked, disabled: backgroundDisabled }}
          disabled={backgroundDisabled} style={[styles.button, backgroundDisabled && styles.disabled]}
          onPress={() => { if (!backgroundDisabled) onChange({ allowBackgroundLive: !settings.allowBackgroundLive }); }}>
          <Text style={styles.label}>{backgroundChecked ? 'On' : 'Off'}</Text>
        </Pressable>
      </View>
      <Text style={styles.detail}>Headphones only. Start Live Mode before locking your phone. Disconnecting headphones stops the conversation. Applies when Live Mode next starts. Bluetooth asks you to confirm the route in the foreground. System Pause or Stop means Stop conversation; Live Mode does not restart automatically.</Text>
      {!checking && !backgroundSupported ? <Text style={styles.detail}>{Platform.OS === 'android' && !androidBackgroundLivePlatformEligible()
        ? 'Requires Android 12 or later for background Live Mode.'
        : 'Requires an updated app build with background capture and protected playback support.'}</Text> : null}
      <Text style={styles.label}>Live Mode volume reduction</Text>
      <View style={styles.row}>
        <Text style={styles.detail}>Use system default</Text>
        <Pressable accessibilityRole="switch" accessibilityLabel="Use system default"
          accessibilityState={{ checked: settings.liveDuckingUseSystemDefault, disabled: defaultDisabled }}
          disabled={defaultDisabled} style={[styles.button, defaultDisabled && styles.disabled]}
          onPress={() => { if (!defaultDisabled) onChange({ liveDuckingUseSystemDefault: !settings.liveDuckingUseSystemDefault }); }}>
          <Text style={styles.label}>{settings.liveDuckingUseSystemDefault ? 'On' : 'Off'}</Text>
        </Pressable>
      </View>
      <View style={styles.row} accessibilityRole="radiogroup" accessibilityLabel="Live Mode volume reduction">
        {levels.map(({ value, label }) => (
          <Pressable key={value} accessibilityRole="radio" accessibilityLabel={label}
            accessibilityState={{ checked: !settings.liveDuckingUseSystemDefault && settings.liveDuckingLevel === value, disabled }}
            disabled={disabled}
            style={[styles.button, styles.choice, !settings.liveDuckingUseSystemDefault && settings.liveDuckingLevel === value && styles.selected, disabled && styles.disabled]}
            onPress={() => { if (!disabled) onChange({ liveDuckingLevel: value }); }}>
            <Text style={styles.label}>{label}</Text>
          </Pressable>
        ))}
      </View>
      <Text style={styles.detail}>{checking ? 'Checking availability…' : !duckingSupported
        ? Platform.OS === 'android'
          ? 'Live Mode volume reduction is unavailable on Android. Your saved iOS preference is preserved; normal playback volume is unchanged.'
          : 'Requires iOS 17 or later and an updated app build with volume-reduction support.'
        : 'Min keeps replies louder; Max reduces them most. Applies when Live Mode next starts. Echo cancellation stays on. Normal playback is unchanged.'}</Text>
    </View>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  group: { gap: spacing.md, marginTop: spacing.lg },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap' },
  button: { minHeight: 44, minWidth: 64, padding: spacing.md, borderWidth: 1, borderRadius: 10,
    borderColor: colors.border, backgroundColor: colors.panelAlt, alignItems: 'center', justifyContent: 'center' },
  choice: { flex: 1 },
  selected: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
  disabled: { opacity: 0.45 },
  label: { color: colors.text, fontSize: 15, fontWeight: '600' },
  detail: { color: colors.muted, fontSize: 14, flexShrink: 1 },
});
