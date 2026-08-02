import React from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import type { RemoteConnectionStatus, RemoteTransport } from '../api/types';
import { colors, spacing } from '../styles/theme';
import { normalizeLanUrl } from '../utils/url';
import type { ConnectionMode, InternetConnectionProfile } from '../utils/connectionProfiles';

const MIN_PAIRING_CODE_DIGITS = 4;
const MAX_PAIRING_CODE_DIGITS = 9;

type Props = {
  baseUrl: string;
  pairingCode: string;
  connected: boolean;
  status: RemoteConnectionStatus;
  transport: RemoteTransport;
  error: string;
  demoMode?: boolean;
  connectionMode: ConnectionMode;
  activeRoute: string;
  internetProfile: InternetConnectionProfile;
  enrollmentStatus: string;
  onBaseUrlChange: (value: string) => void;
  onPairingCodeChange: (value: string) => void;
  onScanQrCode: () => void;
  onConnect: () => void;
  onDisconnect: () => void;
  onRefresh: () => void;
  onDemoModeChange?: (enabled: boolean) => void;
  onConnectionModeChange: (mode: ConnectionMode) => void;
  onForgetInternet: () => void;
};

function WizardStep({ number, title, detail, active }: { number: string; title: string; detail: string; active?: boolean }) {
  return (
    <View style={[styles.stepRow, active && styles.stepRowActive]}>
      <View style={[styles.stepNumber, active && styles.stepNumberActive]}>
        <Text style={styles.stepNumberText}>{number}</Text>
      </View>
      <View style={styles.stepTextBlock}>
        <Text style={styles.stepTitle}>{title}</Text>
        <Text style={styles.stepDetail}>{detail}</Text>
      </View>
    </View>
  );
}

export function ConnectionPanel(props: Props) {
  const routeText = props.activeRoute ? props.activeRoute.replace(/_/g, ' ') : 'no route';
  const statusText = props.demoMode ? 'demo mode' : props.transport !== 'none' ? `${props.status} / ${props.transport} / ${routeText}` : `${props.status} / ${routeText}`;
  const connecting = props.status === 'connecting';
  const disconnectMode = !props.demoMode && (props.connected || connecting || props.transport !== 'none');
  const pairingDigits = props.pairingCode.trim().length;
  const hasValidPairingCode = pairingDigits >= MIN_PAIRING_CODE_DIGITS && pairingDigits <= MAX_PAIRING_CODE_DIGITS;
  const canConnect = !props.demoMode && Boolean(normalizeLanUrl(props.baseUrl) && hasValidPairingCode) && !connecting;
  const actionDisabled = !disconnectMode && !canConnect;
  const actionLabel = disconnectMode ? 'Disconnect' : 'Connect';
  const refreshDisabled = props.demoMode || (!props.connected && props.transport === 'none');
  const connectedLike = props.demoMode || props.connected;
  if (connectedLike) {
    return (
      <View style={styles.compactPanel}>
        <View style={styles.compactText}>
          <Text style={styles.compactTitle}>{props.demoMode ? 'Demo Mode' : 'Connected to desktop'}</Text>
          <Text style={styles.compactMeta} numberOfLines={1}>
            {props.demoMode ? 'Offline phone app tour' : `${normalizeLanUrl(props.baseUrl) || props.baseUrl} - ${statusText}`}
          </Text>
        </View>
        <View style={styles.compactButtons}>
          <Pressable
            style={[styles.compactButton, refreshDisabled && styles.disabled]}
            onPress={props.onRefresh}
            disabled={refreshDisabled}
          >
            <Text style={styles.compactButtonText}>Refresh</Text>
          </Pressable>
          <Pressable
            style={styles.compactButton}
            onPress={props.demoMode ? () => props.onDemoModeChange?.(false) : props.onDisconnect}
          >
            <Text style={styles.compactButtonText}>{props.demoMode ? 'Exit' : 'Disconnect'}</Text>
          </Pressable>
        </View>
      </View>
    );
  }
  return (
    <View style={styles.panel}>
      <View style={styles.statusRow}>
        <Text style={styles.title}>Pair Phone to NC</Text>
        <Text style={[styles.status, props.connected || props.demoMode ? styles.ok : styles.warn]}>{statusText}</Text>
      </View>
      {props.error && !props.demoMode ? <Text style={styles.error}>{props.error}</Text> : null}
      <View style={styles.modeRow}>
        {(['auto', 'lan', 'internet'] as ConnectionMode[]).map((mode) => (
          <Pressable key={mode} style={[styles.modeButton, props.connectionMode === mode && styles.modeButtonActive]} onPress={() => props.onConnectionModeChange(mode)}>
            <Text style={styles.modeButtonText}>{mode.toUpperCase()}</Text>
          </Pressable>
        ))}
      </View>
      {props.connectionMode !== 'lan' ? (
        <View style={styles.internetSummary}>
          <Text style={styles.stepTitle}>Secure Internet profile</Text>
          <Text style={styles.stepDetail}>{props.internetProfile.deviceId ? `${props.internetProfile.hostnameUrl || 'No hostname'} · certified IP fallback ${props.internetProfile.ipUrl || 'not set'}` : 'Not enrolled. Scan an Internet enrollment QR from the desktop Internet tab.'}</Text>
          {props.enrollmentStatus ? <Text style={styles.enrollmentStatus}>{props.enrollmentStatus}</Text> : null}
          <View style={styles.modeRow}>
            <Pressable style={styles.scanButtonCompact} onPress={props.onScanQrCode}><Text style={styles.scanButtonText}>Scan enrollment QR</Text></Pressable>
            {props.internetProfile.deviceId ? <Pressable style={styles.modeButton} onPress={props.onForgetInternet}><Text style={styles.modeButtonText}>Forget Internet</Text></Pressable> : null}
          </View>
        </View>
      ) : null}
      <View style={styles.wizard}>
        <WizardStep
          number="1"
          title="Start desktop bridge"
          detail="In NC, open Main Chat Remote and enable the local bridge."
        />
        <WizardStep
          number="2"
          title="Start LAN backend"
          detail="Saved pairings are found automatically. The manual LAN URL remains available below."
        />
        <WizardStep
          number="3"
          title="Enter pairing code"
          detail="Use the numeric code from the desktop addon. Codes are 4-9 digits."
          active
        />
        <Pressable style={styles.scanButton} onPress={props.onScanQrCode}>
          <Text style={styles.scanButtonText}>Scan QR code</Text>
        </Pressable>
        <View style={styles.formRow}>
          <View style={styles.inputGroup}>
            <Text style={styles.inputLabel}>LAN URL</Text>
            <TextInput
              value={props.baseUrl}
              onChangeText={props.onBaseUrlChange}
              editable={!props.demoMode}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
              placeholder="http://192.168.1.10:8777"
              placeholderTextColor={colors.muted}
              style={styles.input}
            />
          </View>
          <View style={styles.codeGroup}>
            <Text style={styles.inputLabel}>Code</Text>
            <TextInput
              value={props.pairingCode}
              onChangeText={props.onPairingCodeChange}
              editable={!props.demoMode}
              keyboardType="number-pad"
              maxLength={MAX_PAIRING_CODE_DIGITS}
              placeholder="4-9 digits"
              placeholderTextColor={colors.muted}
              style={styles.input}
            />
          </View>
        </View>
        <WizardStep
          number="4"
          title="Test connection"
          detail="Connect on the same LAN, or use Demo to review the phone UI offline."
          active={Boolean(canConnect || connecting)}
        />
      </View>
      <View style={styles.buttonRow}>
        <Pressable
          disabled={actionDisabled}
          style={[styles.button, actionDisabled && styles.disabled]}
          onPress={disconnectMode ? props.onDisconnect : props.onConnect}
        >
          <Text style={styles.buttonText}>{actionLabel}</Text>
        </Pressable>
        <Pressable
          style={[styles.secondaryButton, refreshDisabled && styles.disabled]}
          onPress={props.onRefresh}
          disabled={refreshDisabled}
        >
          <Text style={styles.secondaryButtonText}>Refresh</Text>
        </Pressable>
        <Pressable
          style={[styles.secondaryButton, props.demoMode && styles.demoButtonActive]}
          onPress={() => props.onDemoModeChange?.(!props.demoMode)}
        >
          <Text style={styles.secondaryButtonText}>Demo</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    backgroundColor: colors.panel,
    borderBottomColor: colors.border,
    borderBottomWidth: 1,
    padding: spacing.md,
    gap: spacing.sm,
  },
  compactPanel: {
    alignItems: 'center',
    backgroundColor: colors.panel,
    borderBottomColor: colors.border,
    borderBottomWidth: 1,
    flexDirection: 'row',
    gap: spacing.sm,
    minHeight: 58,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  compactText: {
    flex: 1,
    minWidth: 0,
  },
  compactTitle: {
    color: colors.text,
    fontSize: 14,
    fontWeight: '900',
  },
  compactMeta: {
    color: colors.muted,
    fontSize: 12,
    marginTop: 2,
  },
  compactButtons: {
    flexDirection: 'row',
    gap: spacing.xs,
  },
  compactButton: {
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    minHeight: 34,
    justifyContent: 'center',
    paddingHorizontal: spacing.sm,
  },
  compactButtonText: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '800',
  },
  statusRow: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  title: {
    color: colors.text,
    flex: 1,
    fontSize: 17,
    fontWeight: '700',
    marginRight: spacing.sm,
  },
  status: {
    fontSize: 12,
    fontWeight: '700',
    maxWidth: 150,
    textAlign: 'right',
    textTransform: 'uppercase',
  },
  ok: {
    color: colors.ok,
  },
  warn: {
    color: colors.warning,
  },
  error: {
    color: colors.danger,
    fontSize: 12,
    lineHeight: 16,
  },
  modeRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  modeButton: { borderColor: colors.border, borderRadius: 6, borderWidth: 1, justifyContent: 'center', minHeight: 34, paddingHorizontal: spacing.sm },
  modeButtonActive: { backgroundColor: colors.accentSoft, borderColor: colors.accent },
  modeButtonText: { color: colors.text, fontSize: 11, fontWeight: '900' },
  internetSummary: { backgroundColor: colors.panelAlt, borderColor: colors.border, borderRadius: 7, borderWidth: 1, gap: spacing.xs, padding: spacing.sm },
  enrollmentStatus: { color: colors.warning, fontSize: 12, fontWeight: '800' },
  scanButtonCompact: { alignItems: 'center', backgroundColor: colors.accent, borderRadius: 6, justifyContent: 'center', minHeight: 34, paddingHorizontal: spacing.sm },
  wizard: {
    gap: spacing.sm,
  },
  stepRow: {
    alignItems: 'flex-start',
    flexDirection: 'row',
    gap: spacing.sm,
  },
  stepRowActive: {
    opacity: 1,
  },
  stepNumber: {
    alignItems: 'center',
    backgroundColor: colors.panelAlt,
    borderColor: colors.border,
    borderRadius: 999,
    borderWidth: 1,
    height: 28,
    justifyContent: 'center',
    width: 28,
  },
  stepNumberActive: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.accent,
  },
  stepNumberText: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '900',
  },
  stepTextBlock: {
    flex: 1,
    minWidth: 0,
  },
  stepTitle: {
    color: colors.text,
    fontSize: 13,
    fontWeight: '800',
  },
  stepDetail: {
    color: colors.muted,
    fontSize: 12,
    lineHeight: 16,
    marginTop: 1,
  },
  formRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  scanButton: {
    alignItems: 'center',
    backgroundColor: colors.accent,
    borderRadius: 6,
    height: 42,
    justifyContent: 'center',
  },
  scanButtonText: {
    color: '#061019',
    fontSize: 14,
    fontWeight: '800',
  },
  inputGroup: {
    flex: 1,
    gap: spacing.xs,
  },
  codeGroup: {
    gap: spacing.xs,
    width: 112,
  },
  inputLabel: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: '800',
    textTransform: 'uppercase',
  },
  input: {
    backgroundColor: colors.panelAlt,
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    color: colors.text,
    fontSize: 14,
    height: 42,
    paddingHorizontal: spacing.md,
  },
  buttonRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  button: {
    alignItems: 'center',
    backgroundColor: colors.accent,
    borderRadius: 6,
    height: 40,
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
  },
  buttonText: {
    color: '#061019',
    fontSize: 14,
    fontWeight: '700',
  },
  secondaryButton: {
    alignItems: 'center',
    borderColor: colors.border,
    borderRadius: 6,
    borderWidth: 1,
    height: 40,
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
  },
  secondaryButtonText: {
    color: colors.text,
    fontSize: 14,
    fontWeight: '700',
  },
  demoButtonActive: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.accent,
  },
  disabled: {
    opacity: 0.35,
  },
});
