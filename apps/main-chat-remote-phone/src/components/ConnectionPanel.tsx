import React from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import type { RemoteConnectionStatus, RemoteTransport } from '../api/types';
import { colors, spacing } from '../styles/theme';
import { normalizeLanUrl } from '../utils/url';

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
  onBaseUrlChange: (value: string) => void;
  onPairingCodeChange: (value: string) => void;
  onConnect: () => void;
  onDisconnect: () => void;
  onRefresh: () => void;
  onDemoModeChange?: (enabled: boolean) => void;
};

export function ConnectionPanel(props: Props) {
  const statusText = props.demoMode ? 'demo mode' : props.transport !== 'none' ? `${props.status} / ${props.transport}` : props.status;
  const connecting = props.status === 'connecting';
  const disconnectMode = !props.demoMode && (props.connected || connecting || props.transport !== 'none');
  const pairingDigits = props.pairingCode.trim().length;
  const hasValidPairingCode = pairingDigits >= MIN_PAIRING_CODE_DIGITS && pairingDigits <= MAX_PAIRING_CODE_DIGITS;
  const canConnect = !props.demoMode && Boolean(normalizeLanUrl(props.baseUrl) && hasValidPairingCode) && !connecting;
  const actionDisabled = !disconnectMode && !canConnect;
  const actionLabel = disconnectMode ? 'Disconnect' : 'Connect';
  const refreshDisabled = props.demoMode || (!props.connected && props.transport === 'none');
  return (
    <View style={styles.panel}>
      <View style={styles.statusRow}>
        <Text style={styles.title}>NC Main Chat Remote</Text>
        <Text style={[styles.status, props.connected || props.demoMode ? styles.ok : styles.warn]}>{statusText}</Text>
      </View>
      {props.error && !props.demoMode ? <Text style={styles.error}>{props.error}</Text> : null}
      <View style={styles.formRow}>
        <TextInput
          value={props.baseUrl}
          onChangeText={props.onBaseUrlChange}
          editable={!props.demoMode}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          placeholder="http://192.168.1.10:8777"
          placeholderTextColor={colors.muted}
          style={[styles.input, styles.urlInput]}
        />
        <TextInput
          value={props.pairingCode}
          onChangeText={props.onPairingCodeChange}
          editable={!props.demoMode}
          keyboardType="number-pad"
          maxLength={MAX_PAIRING_CODE_DIGITS}
          placeholder="4-9 digits"
          placeholderTextColor={colors.muted}
          style={[styles.input, styles.codeInput]}
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
          <Text style={styles.secondaryButtonText}>{props.demoMode ? 'Exit Demo' : 'Demo'}</Text>
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
  formRow: {
    flexDirection: 'row',
    gap: spacing.sm,
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
  urlInput: {
    flex: 1,
  },
  codeInput: {
    width: 112,
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
