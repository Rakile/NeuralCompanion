import { useThemedStyles, useThemeColors } from '../styles/ThemeContext';
import type { ThemeColors } from '../styles/theme';
import React, { useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { spacing } from '../styles/theme';
import type { useRelaySession } from './useRelaySession';
import { EnrollmentQr } from './EnrollmentQr';

export function RelayAccountPanel({ relay }: { relay: ReturnType<typeof useRelaySession> }) {
  const styles = useThemedStyles(createStyles);
  const colors = useThemeColors();

  const [identifier, setIdentifier] = useState(''), [email, setEmail] = useState(''), [password, setPassword] = useState(''), [token, setToken] = useState('');
  const [registering, setRegistering] = useState(false), [recovery, setRecovery] = useState(false);
  const [inviteCode, setInviteCode] = useState(''), [proof, setProof] = useState(''), [useRecoveryCode, setUseRecoveryCode] = useState(false);
  const run = (action: string, fields: Record<string, string> = {}) => {
    const values = { ...fields }; setPassword(''); setToken(''); setProof(''); setInviteCode(''); void relay.action(action, values);
  };
  const button = (label: string, action: () => void, disabled = false) => (
    <Pressable accessibilityRole="button" accessibilityLabel={label} style={[styles.button, (relay.busy || disabled) && styles.disabled]} onPress={action} disabled={relay.busy || disabled}><Text style={styles.buttonText}>{label}</Text></Pressable>
  );
  return <View style={styles.panel}>
    <Text style={styles.title}>NC Relay · Internet</Text>
    <Text style={styles.copy}>Sign into the same account on your desktop and phone. Your chat and media use an encrypted peer connection.</Text>
    <Text style={styles.copy}>{relay.account ? `Signed in as ${relay.account.username}` : 'Not signed in'}</Text>
    <Text accessibilityLiveRegion="polite" style={styles.copy}>{relay.message || relay.error || relay.status}</Text>
    {relay.recoveryCodes.length ? <>
      <Text style={styles.title}>Save your recovery codes</Text>
      <Text style={styles.copy}>Each code can be used once if your authenticator is unavailable. Save all ten somewhere private before continuing. They are shown only now.</Text>
      <Text selectable style={styles.secret}>{relay.recoveryCodes.join('\n')}</Text>
      <View style={styles.row}>{button('Copy recovery codes', () => run('copy-recovery'))}{button('I have saved my recovery codes', () => run('ack-recovery'))}</View>
    </> : relay.pending ? <>
      <Text style={styles.title}>{relay.pending.status === 'mfa_enrollment_required' ? 'Set up your authenticator' : 'Verify your sign-in'}</Text>
      {relay.pending.status === 'mfa_enrollment_required' ? <>
        <Text style={styles.copy}>Authenticator verification is required for every relay account. Setup expires after ten minutes; sign in again if needed.</Text>
        {relay.enrollment ? <>
          <EnrollmentQr uri={relay.enrollment.otpauthUri} />
          <Text style={styles.copy}>Scan with your authenticator, or enter this manual key (time based, SHA1, six digits, 30 seconds).</Text>
          <Text selectable style={styles.secret}>{relay.enrollment.secret}</Text>
          {button('Copy authenticator key', () => run('copy-key'))}
        </> : button('Create authenticator setup', () => run('enroll'))}
      </> : <>
        <Text style={styles.copy}>{useRecoveryCode ? 'Enter one unused recovery code.' : 'Enter the current six-digit code from your authenticator. Sign-in expires after five minutes.'}</Text>
        {button(useRecoveryCode ? 'Use authenticator code' : 'Use a recovery code', () => { setProof(''); setUseRecoveryCode(!useRecoveryCode); })}
      </>}
      {relay.pending.status === 'mfa_required' || relay.enrollment ? <>
        <TextInput accessibilityLabel={useRecoveryCode && relay.pending.status === 'mfa_required' ? 'MFA recovery code' : 'Authenticator code'} style={styles.input} placeholder={useRecoveryCode && relay.pending.status === 'mfa_required' ? 'xxxxxxxx-xxxxxxxx' : 'Six-digit authenticator code'} placeholderTextColor={colors.textSecondary} secureTextEntry autoCapitalize="none" autoCorrect={false} keyboardType={useRecoveryCode && relay.pending.status === 'mfa_required' ? 'default' : 'number-pad'} maxLength={useRecoveryCode && relay.pending.status === 'mfa_required' ? 17 : 6} value={proof} onChangeText={setProof} />
        {button('Verify authenticator', () => relay.pending?.status === 'mfa_enrollment_required' ? run('confirm-mfa', { code: proof }) : useRecoveryCode ? run('recover-mfa', { recoveryCode: proof }) : run('verify-mfa', { code: proof }), !(useRecoveryCode && relay.pending.status === 'mfa_required' ? /^[a-fA-F0-9]{8}-[a-fA-F0-9]{8}$/.test(proof) : /^\d{6}$/.test(proof)))}
      </> : null}
      {button('Cancel sign-in', () => run('cancel-mfa'))}
    </> : relay.account ? <>
      <Text style={styles.copy}>{relay.online ? 'Desktop online' : 'Desktop offline or not connected'}</Text>
      <View style={styles.row}>{button(['connecting', 'waiting', 'connected', 'reconnecting'].includes(relay.status) ? 'Disconnect Internet' : 'Connect Internet', () => run(['connecting', 'waiting', 'connected', 'reconnecting'].includes(relay.status) ? 'disconnect' : 'connect'))}{button('Sign out', () => run('logout'))}</View>
      {!relay.account.emailVerified ? button('Resend verification email', () => run('resend')) : null}
    </> : <>
      <TextInput accessibilityLabel={registering ? 'New username' : 'Username or email'} style={styles.input} placeholder={registering ? 'New username' : 'Username or email'} placeholderTextColor={colors.textSecondary} autoCapitalize="none" autoCorrect={false} value={identifier} onChangeText={setIdentifier} />
      {registering || recovery ? <TextInput accessibilityLabel="Account email" style={styles.input} placeholder="Email" placeholderTextColor={colors.textSecondary} keyboardType="email-address" autoCapitalize="none" value={email} onChangeText={setEmail} /> : null}
      {registering ? <TextInput accessibilityLabel="Invitation code" style={styles.input} placeholder="Invitation code from your administrator" placeholderTextColor={colors.textSecondary} secureTextEntry autoCapitalize="none" autoCorrect={false} maxLength={128} value={inviteCode} onChangeText={setInviteCode} /> : null}
      <TextInput accessibilityLabel="Relay password" style={styles.input} placeholder={registering ? 'Password · at least 12 characters' : 'Password'} placeholderTextColor={colors.textSecondary} secureTextEntry autoCapitalize="none" autoCorrect={false} value={password} onChangeText={setPassword} />
      <View style={styles.row}>
        {button(registering ? 'Create account' : 'Sign in', () => run(registering ? 'register' : 'login', registering ? { username: identifier, email, password, inviteCode } : { identifier, password }), !identifier || !password || (registering && (!email || password.length < 12 || inviteCode.length < 20)))}
        {button(registering ? 'Use existing account' : 'Register instead', () => setRegistering(!registering))}
      </View>
    </>}
    {!relay.pending && !relay.recoveryCodes.length ? button(recovery ? 'Hide account help' : 'Email verification / password help', () => setRecovery(!recovery)) : null}
    {recovery && !relay.pending && !relay.recoveryCodes.length ? <>
      {relay.account ? <>
        <TextInput accessibilityLabel="Account email" style={styles.input} placeholder="Email" placeholderTextColor={colors.textSecondary} keyboardType="email-address" autoCapitalize="none" value={email} onChangeText={setEmail} />
        <TextInput accessibilityLabel="New relay password" style={styles.input} placeholder="New password · at least 12 characters" placeholderTextColor={colors.textSecondary} secureTextEntry autoCapitalize="none" autoCorrect={false} value={password} onChangeText={setPassword} />
      </> : null}
      <TextInput accessibilityLabel="Email verification or reset code" style={styles.input} placeholder="Code from email" placeholderTextColor={colors.textSecondary} secureTextEntry autoCapitalize="none" value={token} onChangeText={setToken} />
      <View style={styles.row}>{button('Verify email', () => run('verify', { token }), !token)}{button('Send reset email', () => run('forgot', { email }), !email)}{button('Reset password', () => run('reset', { token, password }), !token || password.length < 12)}</View>
    </> : null}
  </View>;
}
const createStyles = (colors: ThemeColors) => StyleSheet.create({
  panel: { gap: spacing.sm, padding: spacing.md, borderRadius: 14, backgroundColor: colors.panelAlt, borderWidth: 1, borderColor: colors.border },
  title: { color: colors.text, fontSize: 17, fontWeight: '700' }, copy: { color: colors.textSecondary, fontSize: 13 },
  secret: { color: colors.text, fontSize: 15, fontFamily: 'monospace', paddingVertical: 8 },
  input: { color: colors.text, borderColor: colors.border, borderWidth: 1, padding: 12, borderRadius: 10 },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 }, button: { paddingHorizontal: 14, paddingVertical: 11, borderWidth: 1, borderColor: colors.border, borderRadius: 10 },
  buttonText: { color: colors.text, fontWeight: '600' }, disabled: { opacity: .45 },
});
