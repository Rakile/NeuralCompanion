import { useCallback, useEffect, useRef, useState } from 'react';
import * as SecureStore from 'expo-secure-store';
import { AppState } from 'react-native';
import { RelayAuth, RelayError, relayHttp } from './auth';
import { RelaySession } from './session';
import {beginPeerConnectionBackground,type PeerBackgroundLease} from '../native/peerConnectionBackground';

const KEY = 'nc-relay-refresh-v1';
const AUTH_MESSAGES: Record<string, string> = {
  MFA_INVALID: 'Authenticator verification failed or expired. Sign in again and use a fresh code.',
  MFA_EXPIRED: 'Authenticator sign-in expired. Enter your password to start again.',
  MFA_REQUIRED: 'Complete authenticator verification before connecting.',
  INVITE_INVALID: 'This invitation is invalid, expired, revoked, or already used. Request a new invitation.',
  SAVE_RECOVERY_CODES_FIRST: 'Save and acknowledge your recovery codes before continuing.',
  NETWORK_OR_VALIDATION_ERROR: 'The relay response could not be confirmed. Sign in again if verification was interrupted.',
  RATE_LIMITED: 'Too many requests. Wait before trying again.',
  SERVICE_UNAVAILABLE: 'The relay is temporarily unavailable. Try again later.',
};
export function useRelaySession() {
  const [, render] = useState(0); const [busy, setBusy] = useState(false); const [message, setMessage] = useState('');
  const ref = useRef<RelaySession | null>(null);
  const running = useRef(false);
  if (!ref.current) ref.current = new RelaySession(new RelayAuth({
    // Background Live must rotate credentials with the screen locked. Keep
    // them device-only and inaccessible until the first unlock after reboot.
    get: () => SecureStore.getItemAsync(KEY), set: value => SecureStore.setItemAsync(KEY, value, { keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY }), clear: () => SecureStore.deleteItemAsync(KEY),
  }));
  const session = ref.current;
  const wantsConnection=session.wantsConnection;
  useEffect(()=>{
    if(!wantsConnection)return;
    let closed=false,lease:PeerBackgroundLease|undefined;
    void beginPeerConnectionBackground(()=>session.disconnect('background_connection_stopped'))
      .then(async value=>{if(closed)await value?.close();else lease=value;})
      .catch(error=>{if(!closed)setMessage(error instanceof Error?error.message:'Background connection unavailable.');});
    return ()=>{closed=true;void lease?.close().catch(()=>undefined);};
  },[session,wantsConnection]);
  useEffect(() => {
    let alive = true; const update = () => { if (alive) render(value => value + 1); };
    session.onChange = update; session.auth.onChange = update;
    const foreground = AppState.addEventListener('change', state => {
      if (state === 'active') { session.auth.expireMfa(); void session.resumeAfterForeground(); }
    });
    // Credentials stay in secure storage until Internet is requested.
    return () => { alive = false; foreground.remove(); session.onChange = () => undefined; session.auth.onChange = () => undefined; session.auth.cancelMfa(); session.auth.acknowledgeRecoveryCodes(); session.disconnect('hook_unmounted'); };
  }, [session]);
  const pendingDeadline = session.auth.pending?.expiresAt;
  useEffect(() => {
    if (!pendingDeadline) return;
    const timer = setTimeout(() => session.auth.expireMfa(), Math.max(0, pendingDeadline - Date.now()));
    return () => clearTimeout(timer);
  }, [session, pendingDeadline]);
  const action = useCallback(async (name: string, fields: Record<string, string> = {}) => {
    if (running.current) return; running.current = true; setBusy(true); setMessage('');
    try {
      if (session.auth.recoveryCodes.length && !['ack-recovery', 'copy-key', 'copy-recovery'].includes(name)) throw new RelayError('SAVE_RECOVERY_CODES_FIRST');
      if (name === 'login') {
        session.disconnect('user_login'); await session.auth.login(fields.identifier || '', fields.password || '');
        setMessage(session.auth.pending ? 'Complete authenticator verification to sign in.' : 'Signed in. Connect to your desktop.');
      }
      else if (name === 'enroll') { await session.auth.beginEnrollment(); setMessage('Add the key to your authenticator, then enter its six-digit code.'); }
      else if (name === 'confirm-mfa') { await session.auth.confirmEnrollment(fields.code || ''); setMessage('Authenticator confirmed. Save the recovery codes before continuing.'); }
      else if (name === 'verify-mfa') { await session.auth.verifyMfa(fields.code || ''); setMessage('Signed in. Connect to your desktop.'); }
      else if (name === 'recover-mfa') { await session.auth.verifyMfa(fields.recoveryCode || '', true); setMessage('Signed in with a recovery code. That recovery code is now used.'); }
      else if (name === 'cancel-mfa') { session.auth.cancelMfa(); setMessage('Sign-in cancelled. Enter your password to start again.'); }
      else if (name === 'ack-recovery') { session.auth.acknowledgeRecoveryCodes(); setMessage(session.auth.account ? 'Recovery codes acknowledged. Connect to your desktop.' : 'Recovery codes acknowledged. Sign in again to connect.'); }
      else if (name === 'copy-key' || name === 'copy-recovery') {
        const value = name === 'copy-key' ? session.auth.enrollment?.secret : session.auth.recoveryCodes.join('\n');
        if (!value) throw new RelayError('LOGIN_REQUIRED');
        // Pinned RN 0.81 still provides this native clipboard API on Android/iOS.
        const { Clipboard } = require('react-native') as typeof import('react-native');
        Clipboard.setString(value); setMessage('Copied. Store it privately; clear the clipboard when finished.');
      }
      else if (name === 'logout') { session.disconnect('user_logout'); await session.auth.logout(); }
      else if (name === 'connect') await session.connect();
      else if (name === 'disconnect') session.disconnect('user_disconnect');
      else if (name === 'register') { await relayHttp('/v1/auth/register', fields); setMessage('Account created. Verify your email, then sign in to set up your authenticator.'); }
      else if (name === 'verify') { await relayHttp('/v1/auth/verify-email', { token: fields.token }); setMessage('Email verified.'); }
      else if (name === 'forgot') { await relayHttp('/v1/auth/forgot-password', { email: fields.email }); setMessage('Password reset email requested.'); }
      else if (name === 'reset') { await relayHttp('/v1/auth/reset-password', fields); session.disconnect('password_reset'); await session.auth.logout().catch(() => undefined); setMessage('Password reset. Sign in again.'); }
      else if (name === 'resend') { await session.auth.request('/v1/auth/resend-verification', {}); setMessage('Verification email requested.'); }
    } catch (error) {
      setMessage(session.auth.recoveryCodes.length && !session.auth.account
        ? 'Authenticator confirmed, but this phone could not save the session. Save these recovery codes, then sign in again.'
        : error instanceof RelayError ? AUTH_MESSAGES[error.code] || error.code : 'NC Relay request failed. Try again.');
    }
    finally { running.current = false; setBusy(false); }
  }, [session]);
  return { session, peer: session.peer, online: session.online, status: session.status, error: session.error,
    account: session.auth.account, pending: session.auth.pending, enrollment: session.auth.enrollment,
    recoveryCodes: session.auth.recoveryCodes, busy, message, action };
}
