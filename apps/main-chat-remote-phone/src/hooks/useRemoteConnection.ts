import { useRelaySession } from "../relay/useRelaySession";
import { useDiagnosticPolicy } from '../diagnostics/useDiagnosticPolicy';
import { useLocalAVConnection } from './useLocalAVConnection';
import { scopeOrderedRecoveryProfile } from '../dev/desktopOrderedRecovery';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as Network from 'expo-network';

import { RemoteClient, isRemoteAuthError } from '../api/client';
import { StateSyncDecoder, StateSyncResyncRequired, StateSyncVersionError } from '../api/stateSync';
import type { SendTextOptions } from '../api/client';
import type { MprcAction, MprcCastAction, MprcSendOptions } from '../api/client';
import type { VisualAction, VisualRequestOptions } from '../api/client';
import { isRecord, remoteActionError } from '../api/envelope';
import type { RemoteConnectionStatus, RemoteEnvelope, RemoteHealth, RemoteState, RemoteTransport, PhoneReplyAuth } from '../api/types';
import { mergeAudioSnapshot, mergeRemoteSnapshot } from '../utils/audioFastStart';
import { discoverRemoteBaseUrl } from '../utils/lanDiscovery';
import { recordPhoneDebug } from '../utils/phoneDebugBridge';
import {
  advancePendingReplyTraces,
  assistantMessageMarkers,
  matchedReplyTraceIds,
  type PendingReplyTrace,
} from '../utils/replyDiagnostics';
import { normalizeLanUrl } from '../utils/url';
import { mergePresenceSnapshot } from '../utils/presenceState';
import { useConnectionProfiles } from './useConnectionProfiles';
import { connectCandidates, connectionCandidates, type ConnectionRoute, type ConnectionTarget, type ProbeFailureReason } from '../utils/connectionProfiles';
import type { InternetPairingSetup } from '../utils/pairingSetup';

const DEFAULT_POLL_INTERVAL_MS = 1800;
const RECONNECT_BASE_DELAY_MS = 1000;
const RECONNECT_MAX_DELAY_MS = 15000;
const WEBSOCKET_STALE_MS = 8000;
const WEBSOCKET_COMMAND_TIMEOUT_MS = 10000;
const REPLY_DIAGNOSTIC_TIMEOUT_MS = 45000;
const MIN_PAIRING_CODE_DIGITS = 4;
const MAX_PAIRING_CODE_DIGITS = 9;

type SocketCommandType = 'send_text' | 'control' | 'visual' | 'engine_start' | 'engine_stop';
type SocketCommandResultType = 'send_result' | 'control_result' | 'visual_result' | 'engine_start_result' | 'engine_stop_result';
type PendingSocketCommand = {
  resultType: SocketCommandResultType;
  key: string;
  resolve: (payload: unknown) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
};
type PendingReplyDiagnostic = PendingReplyTrace & {
  timer: ReturnType<typeof setTimeout>;
};
type RemoteConnectionOptions = {
  mediaRequired?: boolean;
  autoReconnect?: boolean;
  pollingIntervalMs?: number;
};

type ConnectionInvalidationOrigin = 'identity_change' | 'refresh_failure' | 'poll_failure' | 'connect_auth_failure'
  | 'websocket_watchdog' | 'websocket_auth_failure' | 'websocket_error' | 'websocket_close'
  | 'explicit_disconnect' | 'websocket_state_rejected' | 'websocket_state_missing' | 'websocket_unsolicited_error';

function socketFailureEvidence(event: unknown, socket: WebSocket) {
  if (event === undefined) return undefined;
  try {
    const row = isRecord(event) ? event : {};
    // Never copy native messages or server close reasons: they may contain URLs,
    // pairing tokens or payload data. Only fixed categories cross this boundary.
    const message = typeof row.message === 'string' ? row.message : typeof row.reason === 'string' ? row.reason : '';
    const text = message.slice(0, 1024).toLowerCase();
    const category = !text ? 'unavailable' : /timeout|timed out/.test(text) ? 'timeout'
      : /econnreset|connection reset/.test(text) ? 'reset'
      : /end of stream|eofexception/.test(text) ? 'end_of_stream'
      : /econnrefused|connection refused/.test(text) ? 'refused'
      : /unknownhost|unable to resolve/.test(text) ? 'dns'
      : /sslhandshake|certificate/.test(text) ? 'tls' : 'unclassified';
    return {ready_state: Number.isInteger(socket.readyState) && socket.readyState >= 0 && socket.readyState <= 3 ? socket.readyState : null,
      close_code: typeof row.code === 'number' && Number.isInteger(row.code) && row.code >= 1000 && row.code <= 4999 ? row.code : null,
      was_clean: typeof row.wasClean === 'boolean' ? row.wasClean : null,
      error_category: category, message_present: message.length > 0};
  } catch { return {evidence_unavailable: true}; }
}

function recordConnectionInvalidation(origin: ConnectionInvalidationOrigin, revisionChanged: boolean, authFailure = false,
  socketEvidence?: ReturnType<typeof socketFailureEvidence>): void {
  try {
    void recordPhoneDebug('warning', 'remote_connection_invalidated', {
      origin, auth_failure: authFailure, transport_revision_changed: revisionChanged,
      ...(socketEvidence ? {socket_evidence: socketEvidence} : {}),
    }).catch(() => undefined);
  } catch { /* Logging cannot prevent connection-state or safety-fence changes. */ }
}

function normalizePairingCode(value: string): string {
  return String(value || '').replace(/\D/g, '').slice(0, MAX_PAIRING_CODE_DIGITS);
}

function healthError(payload: RemoteEnvelope<RemoteHealth>): string {
  if (payload.ok) {
    return '';
  }
  if (payload.status === 'bridge_unavailable') {
    return String(payload.bridge?.error || 'LAN backend is reachable, but the local NC bridge is unavailable.');
  }
  return String(payload.error || payload.bridge?.error || 'Remote backend is not ready.');
}

function normalizePollingInterval(value: number | undefined): number {
  const parsed = Number(value ?? DEFAULT_POLL_INTERVAL_MS);
  if (!Number.isFinite(parsed)) {
    return DEFAULT_POLL_INTERVAL_MS;
  }
  return Math.max(900, Math.min(15000, Math.round(parsed)));
}

function targetConnectionKey(target: ConnectionTarget): string { return `${target.route}|${target.baseUrl}|${target.gatewayId}|${target.deviceId}`; }
function probeFailureReason(exc: unknown): ProbeFailureReason {
  if (isRemoteAuthError(exc)) return 'auth_error';
  const message = exc instanceof Error ? exc.message.toLowerCase() : String(exc).toLowerCase();
  if (message.includes('gateway identity')) return 'gateway_identity_error';
  if (message.includes('certificate') || message.includes('ssl') || message.includes('tls')) return 'certificate_error';
  if (message.includes('timed out') || message.includes('timeout')) return 'timeout';
  if (message.includes('dns') || message.includes('name') || message.includes('host')) return 'dns_error';
  return 'unreachable';
}

export function useRemoteConnection(options: RemoteConnectionOptions = {}) {
  const profiles = useConnectionProfiles();
  const relay = useRelaySession();
  const [baseUrl, setBaseUrlValue] = useState('http://192.168.1.10:8777');
  const [pairingCode, setPairingCode] = useState('');
  const [activeTarget, setActiveTarget] = useState<ConnectionTarget | null>(null);
  const [enrollmentStatus, setEnrollmentStatus] = useState('');
  const [status, setStatus] = useState<RemoteConnectionStatus>('disconnected');
  const [transport, setTransport] = useState<RemoteTransport>('none');
  const [error, setError] = useState('');
  const [health, setHealth] = useState<RemoteEnvelope<RemoteHealth> | null>(null);
  const settingsLoaded = profiles.loaded;
  const [startupAutoConnectRequested, setStartupAutoConnectRequested] = useState(false);
  const [startupDiscoveryComplete, setStartupDiscoveryComplete] = useState(false);
  const [pendingPairingConnectionKey, setPendingPairingConnectionKey] = useState('');
  const [state, setState] = useState<RemoteState | null>(null);
  const [pollToken, setPollToken] = useState(0);
  const [transportFailureRevision, setTransportFailureRevision] = useState(0);
  const snapshotEpoch = useRef(0);
  const syncClientRef = useRef<RemoteClient | null>(null);
  const socketStateDecoder = useRef(new StateSyncDecoder());
  const fullSnapshotEpoch = useRef(-1);
  const socketStateRevision = useRef(0);
  const [recoverySnapshot, setRecoverySnapshot] = useState<{ client: RemoteClient; epoch: number } | null>(null);
  const invalidateRecoverySnapshot = useCallback(() => {
    snapshotEpoch.current++;
    socketStateDecoder.current.reset();
    syncClientRef.current?.resetStateSync();
    fullSnapshotEpoch.current = -1;
    setRecoverySnapshot(null);
  }, []);
  const noteTransportFailure = useCallback((origin: ConnectionInvalidationOrigin, authFailure = false,
    socketEvidence?: ReturnType<typeof socketFailureEvidence>) => {
    recordConnectionInvalidation(origin, true, authFailure, socketEvidence);
    invalidateRecoverySnapshot();
    setTransportFailureRevision(value => value + 1);
  }, [invalidateRecoverySnapshot]);
  const socketRef = useRef<WebSocket | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const socketWatchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectEnabledRef = useRef(false);
  const reconnectAttemptsRef = useRef(0);
  const pollInFlightRef = useRef<{ key: string; id: number } | null>(null);
  const pollSequenceRef = useRef(0);
  // Retry status is not reachability: a confirmed polling session remains usable
  // until a poll fails, the route disconnects, or an opened socket replaces it.
  const pollingReachableRef = useRef(false);
  const openSocketRef = useRef<() => void>(() => undefined);
  const activeConnectionKeyRef = useRef('');
  const connectionAttemptRef = useRef(0);
  const socketCommandSequenceRef = useRef(0);
  const pendingSocketCommandsRef = useRef<Map<string, PendingSocketCommand>>(new Map());
  const pendingReplyDiagnosticsRef = useRef<Map<string, PendingReplyDiagnostic>>(new Map());
  const latestStateRef = useRef<RemoteState | null>(null);
  const startupAutoConnectStartedRef = useRef(false);
  const startupAutoConnectCompletedRef = useRef(false);
  const enrollmentAbortRef = useRef<AbortController | null>(null);
  const connectionProbeEpoch=useRef(0);

  const client = useMemo(() => {
    if (relay.peer) return RemoteClient.forPeer(relay.peer);
    if (activeTarget?.auth.kind === 'internet') return RemoteClient.forInternet(activeTarget.baseUrl, activeTarget.auth.deviceId, activeTarget.auth.deviceToken);
    if (activeTarget?.auth.kind === 'lan') return RemoteClient.forLan(activeTarget.baseUrl, activeTarget.auth.pairingCode);
    return RemoteClient.forLan(normalizeLanUrl(baseUrl), pairingCode.trim());
  }, [activeTarget, baseUrl, pairingCode, profiles.credentialGeneration, relay.peer]);
  syncClientRef.current = client;
  const autoReconnect = options.autoReconnect !== false;
  const pollingIntervalMs = normalizePollingInterval(options.pollingIntervalMs);
  const hasValidPairingCode = client.isRelay || client.auth.kind === 'internet' || (client.pairingCode.length >= MIN_PAIRING_CODE_DIGITS && client.pairingCode.length <= MAX_PAIRING_CODE_DIGITS);
  const activeRoute: ConnectionRoute = relay.peer || profiles.settings.mode === 'internet'
    || (profiles.settings.mode === 'auto' && relay.session.wantsConnection) ? 'internet_relay' : activeTarget?.route || 'lan';
  const hasConnectionConfig = Boolean(client.baseUrl && hasValidPairingCode) && (activeRoute !== 'internet_relay' || Boolean(relay.peer));
  const connectionKey = relay.peer ? `relay|${relay.peer.id}` : `${activeRoute}|${client.baseUrl}|${activeTarget?.gatewayId || ''}|${activeTarget?.deviceId || ''}`;
  const commandConnected = status === 'connected'
    && (activeRoute !== 'internet_relay' || Boolean(relay.peer && relay.session.commandReady));
  const needsLocalMedia = options.mediaRequired === true && activeRoute === 'lan';
  // Command reachability is not the lifetime of the established media peer.
  // Keep its buffered output during a transient outage; explicit disconnect,
  // credential replacement and pairing rejection still terminate this lease.
  const localMediaWanted=needsLocalMedia&&hasConnectionConfig&&(commandConnected||reconnectEnabledRef.current);
  const localMedia = useLocalAVConnection(client, localMediaWanted);
  const connected = commandConnected && (!needsLocalMedia || localMedia.ready);
  const playbackConnected=connected||(localMediaWanted&&localMedia.ready);
  useDiagnosticPolicy(client,commandConnected);
  const connectionRecoveryReady = connected && recoverySnapshot?.client === client
    && recoverySnapshot.epoch === snapshotEpoch.current;
  const confirmRecoverySnapshot = useCallback((snapshot: RemoteState, epoch: number) => {
    const generation = snapshot.conversation_actions?.session_generation;
    if (epoch === snapshotEpoch.current && Number.isSafeInteger(generation) && generation! >= 0) {
      setRecoverySnapshot({ client, epoch });
    }
  }, [client]);
  // Private capability is memory-only and survives a transient transport reconnect.
  // Credential replacement creates a different owner even at the same URL.
  const privateRelayScope=activeRoute==='internet_relay'&&relay.session.wantsConnection?relay.session.recoveryKey:'';
  const replyOwner = useRef<{ client: RemoteClient; relayScope:string; credentialGeneration: number; auth?: PhoneReplyAuth; opening?: Promise<PhoneReplyAuth>; openingSharedQueueVersion?: 1; openingContinuationVersion?: 1 }>({ client, relayScope:privateRelayScope, credentialGeneration: profiles.credentialGeneration });
  const priorClient = replyOwner.current.client;
  const sameRelayOwner=!!privateRelayScope&&replyOwner.current.relayScope===privateRelayScope
    &&profiles.credentialGeneration===replyOwner.current.credentialGeneration;
  if (!sameRelayOwner&&(priorClient.identityKey !== client.identityKey || profiles.credentialGeneration !== replyOwner.current.credentialGeneration
    ||replyOwner.current.relayScope!==privateRelayScope
    || priorClient.auth.kind !== client.auth.kind
    || (priorClient.auth.kind === 'lan' && client.auth.kind === 'lan' && priorClient.auth.pairingCode !== client.auth.pairingCode)
    || (priorClient.auth.kind === 'internet' && client.auth.kind === 'internet' && priorClient.auth.deviceToken !== client.auth.deviceToken))) {
    replyOwner.current = { client, relayScope:privateRelayScope, credentialGeneration: profiles.credentialGeneration };
  }
  const phoneReplyOwner = replyOwner.current;
  const getPhoneReplyAuth = useCallback(async (renew = false, sharedQueueVersion?: 1, continuationVersion?: 1): Promise<PhoneReplyAuth> => {
    const owner = replyOwner.current;
    if (owner !== phoneReplyOwner) throw new Error('Phone reply connection changed.');
    if (renew) owner.auth = undefined;
    if (owner.auth && owner.auth.shared_queue_version === sharedQueueVersion && owner.auth.reply_continuation_version === continuationVersion) return owner.auth;
    if (owner.auth) owner.auth = undefined;
    if (owner.opening && owner.openingSharedQueueVersion === sharedQueueVersion && owner.openingContinuationVersion === continuationVersion) return owner.opening;
    if (owner.opening) {
      const opened = await owner.opening;
      if (owner !== replyOwner.current) throw new Error('Phone reply connection changed.');
      if (opened.shared_queue_version === sharedQueueVersion && opened.reply_continuation_version === continuationVersion) return opened;
      owner.auth = undefined;
    }
    const opening = client.openPhoneReplySession(sharedQueueVersion, continuationVersion).then(auth => {
      if (owner !== replyOwner.current) throw new Error('Phone reply connection changed.');
      owner.auth = auth; return auth;
    });
    owner.opening = opening; owner.openingSharedQueueVersion = sharedQueueVersion; owner.openingContinuationVersion = continuationVersion;
    try { return await opening; } finally { if (owner.opening === opening) { owner.opening = undefined; owner.openingSharedQueueVersion = undefined; } }
  }, [client, phoneReplyOwner]);
  const previousIdentity = useRef(client.identityKey);
  useEffect(() => {
    if (previousIdentity.current === client.identityKey) return;
    previousIdentity.current = client.identityKey;
    connectionProbeEpoch.current++;
    noteTransportFailure('identity_change');
  }, [client.identityKey, noteTransportFailure]);
  latestStateRef.current = state;

  useEffect(() => {
    const assistantCount = assistantMessageMarkers(state).length;
    const pendingTraces = Array.from(pendingReplyDiagnosticsRef.current.values());
    const matchedTraceIds = matchedReplyTraceIds(
      pendingTraces,
      state,
      connectionKey,
    );
    for (const debugTraceId of matchedTraceIds) {
      const pending = pendingReplyDiagnosticsRef.current.get(debugTraceId);
      if (!pending) continue;
      clearTimeout(pending.timer);
      pendingReplyDiagnosticsRef.current.delete(debugTraceId);
      void recordPhoneDebug('info', 'text_turn_reply_observed', {
        debug_trace_id: debugTraceId,
        reply_wait_ms: Math.max(0, Date.now() - pending.acceptedAtMs),
        assistant_message_count: assistantCount,
      });
    }
    const advancedTraces = advancePendingReplyTraces(
      pendingTraces,
      state,
      connectionKey,
      matchedTraceIds,
    );
    pendingReplyDiagnosticsRef.current = new Map(
      advancedTraces.map((pending) => [pending.debugTraceId, pending]),
    );
  }, [connectionKey, state]);

  useEffect(() => {
    for (const [debugTraceId, pending] of pendingReplyDiagnosticsRef.current.entries()) {
      if (pending.connectionKey === connectionKey) continue;
      clearTimeout(pending.timer);
      pendingReplyDiagnosticsRef.current.delete(debugTraceId);
      void recordPhoneDebug('info', 'text_reply_tracking_cancelled', {
        debug_trace_id: debugTraceId,
        reason: 'connection_changed',
      });
    }
  }, [connectionKey]);

  useEffect(() => () => {
    for (const pending of pendingReplyDiagnosticsRef.current.values()) {
      clearTimeout(pending.timer);
    }
    pendingReplyDiagnosticsRef.current.clear();
  }, []);

  useEffect(() => {
    if (!profiles.loaded) return;
    const savedLan = profiles.settings.lan;
    if (savedLan.baseUrl) setBaseUrlValue(savedLan.baseUrl);
    if (savedLan.pairingCode) setPairingCode(savedLan.pairingCode);
    const candidates = connectionCandidates({ ...profiles.settings, mode: 'lan' });
    if (profiles.settings.mode === 'internet') { setStartupAutoConnectRequested(true); return; }
    if (candidates.length) { setActiveTarget((current) => current || candidates[0] || null); setStartupAutoConnectRequested(true); }
  }, [profiles.loaded]);

  useEffect(() => {
    if (!settingsLoaded) {
      return;
    }
    profiles.setLan({ baseUrl, pairingCode });
  }, [baseUrl, pairingCode, settingsLoaded]);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    pollInFlightRef.current = null;
  }, []);

  const clearReconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const clearSocketWatchdog = useCallback(() => {
    if (socketWatchdogRef.current) {
      clearTimeout(socketWatchdogRef.current);
      socketWatchdogRef.current = null;
    }
  }, []);

  const rejectPendingSocketCommands = useCallback((message: string, key = '') => {
    for (const [requestId, pending] of pendingSocketCommandsRef.current.entries()) {
      if (key && pending.key !== key) {
        continue;
      }
      clearTimeout(pending.timer);
      pending.reject(new Error(message));
      pendingSocketCommandsRef.current.delete(requestId);
    }
  }, []);

  const stopActiveConnectionAfterAuthFailure = useCallback((message: string, key: string,
    origin: 'refresh_failure' | 'poll_failure' | 'websocket_auth_failure' | 'connect_auth_failure') => {
    if (activeConnectionKeyRef.current !== key) {
      return;
    }
    noteTransportFailure(origin, true);
    reconnectEnabledRef.current = false;
    clearReconnect();
    clearSocketWatchdog();
    rejectPendingSocketCommands('Pairing authorization failed before the command result was confirmed.', key);
    const socket = socketRef.current;
    socketRef.current = null;
    socket?.close();
    stopPolling();
    activeConnectionKeyRef.current = '';
    pollingReachableRef.current = false;
    setError(message);
    setStatus('error');
    setTransport('none');
  }, [clearReconnect, clearSocketWatchdog, rejectPendingSocketCommands, stopPolling]);

  const refreshActiveConnection = useCallback(async () => {
    const epoch = snapshotEpoch.current;
    const socketRevision = socketStateRevision.current;
    if (!client.baseUrl) {
      throw new Error('A saved LAN or Internet connection is required.');
    }
    if (!hasValidPairingCode) {
      throw new Error(`Pairing code must be ${MIN_PAIRING_CODE_DIGITS}-${MAX_PAIRING_CODE_DIGITS} digits.`);
    }
    let health: RemoteEnvelope<RemoteHealth>;
    try { health = await client.health(activeTarget?.gatewayId || ''); }
    catch (failure) {
      if (epoch !== snapshotEpoch.current || activeConnectionKeyRef.current !== connectionKey) return false;
      throw failure;
    }
    if (epoch !== snapshotEpoch.current || activeConnectionKeyRef.current !== connectionKey) return false;
    setHealth(health);
    const readinessError = healthError(health);
    if (readinessError) {
      throw new Error(readinessError);
    }
    let nextState: RemoteState;
    try { nextState = await client.state({forceFull: fullSnapshotEpoch.current !== epoch}); }
    catch (failure) {
      if (epoch !== snapshotEpoch.current || activeConnectionKeyRef.current !== connectionKey) return false;
      throw failure;
    }
    if (activeConnectionKeyRef.current !== connectionKey || epoch !== snapshotEpoch.current) {
      return false;
    }
    if (socketRevision !== socketStateRevision.current) return false;
    setState((current) => mergeRemoteSnapshot(current, nextState));
    fullSnapshotEpoch.current = epoch;
    confirmRecoverySnapshot(nextState, epoch);
    pollingReachableRef.current = true;
    setStatus('connected');
    setTransport((current) => (client.isRelay ? 'webrtc' : current === 'websocket' ? current : 'polling'));
    setError('');
    return true;
  }, [activeTarget?.gatewayId, client, connectionKey, hasValidPairingCode, confirmRecoverySnapshot]);

  const refresh = useCallback(async () => {
    try {
      await refreshActiveConnection();
    } catch (exc) {
      if (activeConnectionKeyRef.current !== connectionKey) {
        return;
      }
      if (isRemoteAuthError(exc)) {
        stopActiveConnectionAfterAuthFailure(exc instanceof Error ? exc.message : 'Pairing authorization failed.', connectionKey, 'refresh_failure');
        return;
      }
      setError(exc instanceof Error ? exc.message : 'Refresh failed.');
      noteTransportFailure('refresh_failure');
      pollingReachableRef.current = false;
      setStatus('error');
      setTransport((current) => (client.isRelay ? 'webrtc' : current === 'websocket' ? current : pollingRef.current ? 'polling' : 'none'));
    }
  }, [connectionKey, refreshActiveConnection, stopActiveConnectionAfterAuthFailure]);

  const startPolling = useCallback(() => {
    stopPolling();
    if (!hasConnectionConfig) {
      return;
    }
    const pollOnce = () => {
      if (pollInFlightRef.current?.key === connectionKey) {
        return;
      }
      const pollId = pollSequenceRef.current + 1;
      pollSequenceRef.current = pollId;
      pollInFlightRef.current = { key: connectionKey, id: pollId };
      refreshActiveConnection()
        .catch((exc) => {
          const currentPoll = pollInFlightRef.current;
          if (
            activeConnectionKeyRef.current !== connectionKey
            || currentPoll?.key !== connectionKey
            || currentPoll.id !== pollId
          ) {
            return;
          }
          if (isRemoteAuthError(exc)) {
            stopActiveConnectionAfterAuthFailure(exc instanceof Error ? exc.message : 'Pairing authorization failed.', connectionKey, 'poll_failure');
            return;
          }
          setError(exc instanceof Error ? exc.message : 'Polling failed.');
          noteTransportFailure('poll_failure');
          pollingReachableRef.current = false;
          setStatus('error');
          setTransport(client.isRelay ? 'webrtc' : 'polling');
        })
        .finally(() => {
          if (pollInFlightRef.current?.key === connectionKey && pollInFlightRef.current.id === pollId) {
            pollInFlightRef.current = null;
          }
        });
    };
    pollOnce();
    pollingRef.current = setInterval(pollOnce, pollingIntervalMs);
  }, [connectionKey, hasConnectionConfig, pollingIntervalMs, refreshActiveConnection, stopActiveConnectionAfterAuthFailure, stopPolling]);

  const sendSocketCommand = useCallback(async (
    messageType: SocketCommandType,
    resultType: SocketCommandResultType,
    body: Record<string, unknown>,
  ): Promise<unknown | null> => {
    const socket = socketRef.current;
    if (activeConnectionKeyRef.current !== connectionKey || !socket || socket.readyState !== 1) {
      return null;
    }
    socketCommandSequenceRef.current += 1;
    const requestId = `phone_${Date.now()}_${socketCommandSequenceRef.current}`;
    return new Promise<unknown>((resolve, reject) => {
      const timer = setTimeout(() => {
        pendingSocketCommandsRef.current.delete(requestId);
        reject(new Error('WebSocket command timed out. The command result was not confirmed.'));
      }, WEBSOCKET_COMMAND_TIMEOUT_MS);
      pendingSocketCommandsRef.current.set(requestId, {
        resultType,
        key: connectionKey,
        resolve,
        reject,
        timer,
      });
      try {
        socket.send(JSON.stringify({ ...body, type: messageType, request_id: requestId }));
      } catch {
        clearTimeout(timer);
        pendingSocketCommandsRef.current.delete(requestId);
        resolve(null);
      }
    });
  }, [connectionKey]);

  const scheduleReconnect = useCallback(() => {
    clearReconnect();
    if (!autoReconnect || !reconnectEnabledRef.current || !hasConnectionConfig) {
      return;
    }
    reconnectAttemptsRef.current += 1;
    const exponent = Math.min(reconnectAttemptsRef.current - 1, 4);
    const delayMs = Math.min(RECONNECT_MAX_DELAY_MS, RECONNECT_BASE_DELAY_MS * 2 ** exponent);
    reconnectTimerRef.current = setTimeout(() => {
      reconnectTimerRef.current = null;
      if (!reconnectEnabledRef.current) {
        return;
      }
      openSocketRef.current();
    }, delayMs);
  }, [autoReconnect, clearReconnect, hasConnectionConfig]);

  const scheduleSocketWatchdog = useCallback((socket: WebSocket) => {
    clearSocketWatchdog();
    socketWatchdogRef.current = setTimeout(() => {
      socketWatchdogRef.current = null;
      if (activeConnectionKeyRef.current !== connectionKey || socketRef.current !== socket) {
        return;
      }
      noteTransportFailure('websocket_watchdog');
      if (!autoReconnect) {
        setError('WebSocket stopped receiving state.');
        setStatus('error');
        setTransport('none');
        socket.close();
        return;
      }
      setError('WebSocket stopped receiving state. Polling fallback is active while reconnecting.');
      setStatus(pollingReachableRef.current ? 'connected' : 'error');
      setTransport(client.isRelay ? 'webrtc' : 'polling');
      startPolling();
      scheduleReconnect();
      socket.close();
    }, WEBSOCKET_STALE_MS);
  }, [autoReconnect, clearSocketWatchdog, connectionKey, scheduleReconnect, startPolling]);

  const openSocket = useCallback(async () => {
    const attempt = connectionAttemptRef.current;
    if (client.isRelay) { setTransport("webrtc"); startPolling(); return; }
    if (!hasConnectionConfig) {
      return;
    }
    let websocketUrl = '';
    try {
      websocketUrl = await client.websocketUrl();
    } catch (exc) {
      if (activeConnectionKeyRef.current !== connectionKey || attempt !== connectionAttemptRef.current) return;
      if (isRemoteAuthError(exc)) {
        stopActiveConnectionAfterAuthFailure(exc instanceof Error ? exc.message : 'Pairing authorization failed.', connectionKey, 'websocket_auth_failure');
        return;
      }
      setError(exc instanceof Error ? exc.message : 'WebSocket authorization failed.');
      noteTransportFailure('websocket_auth_failure');
      setStatus(pollingReachableRef.current ? 'connected' : 'error'); setTransport(client.isRelay ? 'webrtc' : 'polling'); startPolling(); scheduleReconnect(); return;
    }
    if (activeConnectionKeyRef.current !== connectionKey || attempt !== connectionAttemptRef.current) return;
    const socket = new WebSocket(websocketUrl);
    let waitingForFull = false;
    socketRef.current = socket;
    socket.onopen = () => {
      if (activeConnectionKeyRef.current !== connectionKey || socketRef.current !== socket) {
        socket.close();
        return;
      }
      reconnectAttemptsRef.current = 0;
      // Opening a transport is not proof of its current conversation. A fresh
      // state message must validate it before paused Live can resume.
      invalidateRecoverySnapshot();
      clearReconnect();
      stopPolling();
      pollingReachableRef.current = false;
      setStatus('connected');
      setTransport('websocket');
      setError('');
      setPollToken((value) => value + 1);
      scheduleSocketWatchdog(socket);
    };
    socket.onmessage = (event) => {
      if (activeConnectionKeyRef.current !== connectionKey || socketRef.current !== socket) {
        return;
      }
      scheduleSocketWatchdog(socket);
      try {
        const message = JSON.parse(String(event.data)) as { type?: string; payload?: unknown; error?: string; request_id?: unknown };
        if (
          message.type === 'send_result'
          || message.type === 'control_result'
          || message.type === 'visual_result'
          || message.type === 'engine_start_result'
          || message.type === 'engine_stop_result'
        ) {
          const requestId = String(message.request_id || '');
          const pending = requestId ? pendingSocketCommandsRef.current.get(requestId) : undefined;
          if (pending && pending.key === connectionKey && pending.resultType === message.type) {
            clearTimeout(pending.timer);
            pendingSocketCommandsRef.current.delete(requestId);
            pending.resolve(message.payload);
          }
          return;
        }
        if (message.type === 'state') throw new StateSyncVersionError();
        if (message.type === 'state_sync') {
          const payload = message.payload;
          if (!isRecord(payload) || payload.ok !== true) {
            recordConnectionInvalidation('websocket_state_rejected', false);
            invalidateRecoverySnapshot();
            setError(isRecord(payload) ? String(payload.error || 'Remote state request failed.') : 'Remote state payload missing.');
            setStatus('error');
            return;
          }
          const decoded = socketStateDecoder.current.apply(payload.state_sync);
          socketStateRevision.current++;
          setState((current) => mergeRemoteSnapshot(current, decoded.state));
          if (decoded.full) {
            waitingForFull = false;
            fullSnapshotEpoch.current = snapshotEpoch.current;
            confirmRecoverySnapshot(decoded.state, snapshotEpoch.current);
          }
          setStatus('connected');
          setError('');
          return;
        }
        if (message.type === 'audio') {
          const payload = message.payload;
          setState((current) => mergeAudioSnapshot(current, payload));
          if (isRecord(payload)) {
            const items = Array.isArray(payload.items) ? payload.items : [];
            const latest = items.length && isRecord(items[items.length - 1])
              ? items[items.length - 1]
              : null;
            void recordPhoneDebug('info', 'audio_ws_received', {
              generation: Number(payload.generation || 0),
              item_count: items.length,
              latest_id: latest ? String(latest.id || '') : '',
              backend_created_at: latest ? Number(latest.created_at || 0) : 0,
              received_at_ms: Date.now(),
            });
          }
          return;
        }
        if (message.type === 'presence') {
          setState((current) => mergePresenceSnapshot(current, message.payload));
          return;
        }
        if (message.type === 'error') {
          const requestId = String(message.request_id || '');
          const pending = requestId ? pendingSocketCommandsRef.current.get(requestId) : undefined;
          if (pending && pending.key === connectionKey) {
            clearTimeout(pending.timer);
            pendingSocketCommandsRef.current.delete(requestId);
            pending.reject(new Error(String(message.error || 'Remote backend reported an error.')));
            return;
          }
          setError(String(message.error || 'Remote backend reported an error.'));
          recordConnectionInvalidation('websocket_unsolicited_error', false);
          setStatus('error');
        }
      } catch (failure) {
        if (failure instanceof StateSyncResyncRequired && !waitingForFull) {
          waitingForFull = true;
          invalidateRecoverySnapshot();
          try {
            socket.send(JSON.stringify({type:'state_sync_reset'}));
            return;
          } catch {
            // A lost socket cannot provide the requested full snapshot.
            // Recover below, just as when the reset response is invalid.
          }
        }
        if (failure instanceof StateSyncResyncRequired || failure instanceof StateSyncVersionError) {
          noteTransportFailure('websocket_state_missing');
          setError(failure.message);
          socketRef.current = null;
          clearSocketWatchdog();
          rejectPendingSocketCommands('State synchronization lost before the command result was confirmed.', connectionKey);
          socket.close();
          if (failure instanceof StateSyncResyncRequired && autoReconnect
            && reconnectEnabledRef.current && activeConnectionKeyRef.current === connectionKey) {
            setStatus('error');
            setTransport(client.isRelay ? 'webrtc' : 'polling');
            startPolling();
            scheduleReconnect();
          } else {
            clearReconnect();
            stopPolling();
            setStatus('error');
            setTransport('none');
          }
        }
      }
    };
    socket.onerror = event => {
      if (activeConnectionKeyRef.current !== connectionKey || socketRef.current !== socket) {
        socket.close();
        return;
      }
      noteTransportFailure('websocket_error', false, socketFailureEvidence(event, socket));
      if (!autoReconnect) {
        setError('WebSocket failed.');
        setStatus('error');
        setTransport('none');
        socket.close();
        return;
      }
      setError('WebSocket failed. Polling fallback is active while reconnecting.');
      setStatus(pollingReachableRef.current ? 'connected' : 'error');
      setTransport(client.isRelay ? 'webrtc' : 'polling');
      startPolling();
      socket.close();
    };
    socket.onclose = event => {
      if (socketRef.current === socket) {
        noteTransportFailure('websocket_close', false, socketFailureEvidence(event, socket));
        socketRef.current = null;
        clearSocketWatchdog();
        rejectPendingSocketCommands('WebSocket disconnected before the command result was confirmed.', connectionKey);
        if (autoReconnect && reconnectEnabledRef.current && activeConnectionKeyRef.current === connectionKey) {
          setError('WebSocket disconnected. Polling fallback is active while reconnecting.');
          setStatus(pollingReachableRef.current ? 'connected' : 'error');
          setTransport(client.isRelay ? 'webrtc' : 'polling');
          startPolling();
          scheduleReconnect();
        } else if (activeConnectionKeyRef.current === connectionKey) {
          setStatus('error');
          setTransport('none');
        }
      }
    };
  }, [autoReconnect, clearReconnect, clearSocketWatchdog, client, connectionKey, hasConnectionConfig, rejectPendingSocketCommands, scheduleReconnect, scheduleSocketWatchdog, startPolling, stopActiveConnectionAfterAuthFailure, stopPolling, invalidateRecoverySnapshot, confirmRecoverySnapshot]);

  useEffect(() => {
    openSocketRef.current = openSocket;
  }, [openSocket]);

  useEffect(() => () => {
    connectionProbeEpoch.current++;
    connectionAttemptRef.current++;
    reconnectEnabledRef.current = false;
    clearReconnect();
    clearSocketWatchdog();
    rejectPendingSocketCommands('Disconnected before the command result was confirmed.');
    const socket = socketRef.current;
    socketRef.current = null;
    socket?.close();
    stopPolling();
  }, [clearReconnect, clearSocketWatchdog, rejectPendingSocketCommands, stopPolling]);

  const disconnect = useCallback(() => {
    connectionProbeEpoch.current++;
    connectionAttemptRef.current++;
    startupAutoConnectStartedRef.current = true;
    startupAutoConnectCompletedRef.current = true;
    setPendingPairingConnectionKey('');
    noteTransportFailure('explicit_disconnect');
    enrollmentAbortRef.current?.abort();
    enrollmentAbortRef.current = null;
    setEnrollmentStatus('');
    reconnectEnabledRef.current = false;
    clearReconnect();
    clearSocketWatchdog();
    rejectPendingSocketCommands('Disconnected before the command result was confirmed.');
    activeConnectionKeyRef.current = '';
    pollingReachableRef.current = false;
    const socket = socketRef.current;
    socketRef.current = null;
    socket?.close();
    stopPolling();
    setStatus('disconnected');
    setTransport('none');
    setError('');

    if (client.auth.kind === 'internet') {
      setStartupDiscoveryComplete(true);
      return;
    }
    setHealth(null);
    setState(null);
  }, [clearReconnect, clearSocketWatchdog, rejectPendingSocketCommands, stopPolling]);

  useEffect(() => {
    if (!activeConnectionKeyRef.current || activeConnectionKeyRef.current === connectionKey) {
      return;
    }
    disconnect();
  }, [connectionKey, disconnect]);

  const connectActive = useCallback(async () => {
    disconnect();
    const attempt = connectionAttemptRef.current;
    reconnectEnabledRef.current = autoReconnect;
    reconnectAttemptsRef.current = 0;
    activeConnectionKeyRef.current = connectionKey;
    setStatus('connecting');
    setTransport('none');
    try {
      const applied = await refreshActiveConnection();
      if (!applied || activeConnectionKeyRef.current !== connectionKey || attempt !== connectionAttemptRef.current) {
        return;
      }
      openSocket();
      startPolling();
    } catch (exc) {
      if (activeConnectionKeyRef.current !== connectionKey || attempt !== connectionAttemptRef.current) {
        return;
      }
      if (isRemoteAuthError(exc)) {
        stopActiveConnectionAfterAuthFailure(exc instanceof Error ? exc.message : 'Pairing authorization failed.', connectionKey, 'connect_auth_failure');
        return;
      }
      setError(exc instanceof Error ? exc.message : 'Connection failed.');
      setStatus('error');
      if (autoReconnect && hasConnectionConfig) {
        setTransport(client.isRelay ? 'webrtc' : 'polling');
        startPolling();
        scheduleReconnect();
      } else {
        setTransport('none');
      }
    }
  }, [autoReconnect, connectionKey, disconnect, hasConnectionConfig, openSocket, refreshActiveConnection, scheduleReconnect, startPolling, stopActiveConnectionAfterAuthFailure]);

  const connect = useCallback(async () => {
    const probeEpoch=++connectionProbeEpoch.current;
    if (profiles.settings.mode === "internet") { disconnect(); await relay.action("connect"); return; }
    const candidates = connectionCandidates({ ...profiles.settings, mode: 'lan', lan: { baseUrl: normalizeLanUrl(baseUrl), pairingCode: normalizePairingCode(pairingCode) } });
    const firstCandidate=candidates[0];
    if (!firstCandidate) { if (profiles.settings.mode === 'auto') { await relay.action('connect'); return; } setError('Save a valid LAN pairing first.'); setStatus('error'); return; }
    setStatus('connecting'); setTransport('none'); setError('');
    const selected = await connectCandidates(candidates, async (target) => {
      const probeClient = target.auth.kind === 'lan' ? RemoteClient.forLan(target.baseUrl, target.auth.pairingCode) : RemoteClient.forInternet(target.baseUrl, target.auth.deviceId, target.auth.deviceToken);
      try {
        const result = await probeClient.health(target.gatewayId); const readinessError = healthError(result);
        return readinessError ? { ok: false as const, reason: 'unreachable' as const, error: readinessError } : { ok: true as const };
      } catch (exc) { return { ok: false as const, reason: probeFailureReason(exc), error: exc instanceof Error ? exc.message : String(exc) }; }
    });
    if(probeEpoch!==connectionProbeEpoch.current)return;
    let target=selected.target;
    if (!target) {
      if (profiles.settings.mode === "auto" && !selected.terminalReason) { await relay.action("connect"); return; }
      if(!selected.terminalReason&&autoReconnect){
        // Preserve saved LAN intent even if Desktop is offline at launch.
        // connectActive reuses authenticated polling/backoff; it cannot admit
        // commands or playback until the actual route becomes ready.
        target=firstCandidate;
      }else{
        setError(selected.terminalReason ? `Connection stopped for safety: ${selected.terminalReason.replace(/_/g, ' ')}.` : 'No saved connection route could reach NeuralCompanion.');
        setStatus('error'); setTransport('none'); return;
      }
    }
    const nextKey = targetConnectionKey(target);
    const pairingChanged = target.auth.kind === 'lan' && client.auth.kind === 'lan'
      && target.auth.pairingCode !== client.auth.pairingCode;
    if (nextKey === connectionKey && !pairingChanged) { await connectActive(); return; }
    setActiveTarget(target); setPendingPairingConnectionKey(nextKey);
  }, [autoReconnect,baseUrl, client, connectActive, connectionKey, pairingCode, profiles.settings, relay.action]);

  useEffect(() => {
    if (relay.peer && !relay.peer.closed) void connectActive();
  }, [relay.peer]);

  useEffect(() => {
    if (!profiles.loaded || !settingsLoaded || !startupAutoConnectRequested || startupAutoConnectStartedRef.current || profiles.settings.mode !== 'internet') return;
    startupAutoConnectStartedRef.current = true;
    startupAutoConnectCompletedRef.current = true;
    setStartupDiscoveryComplete(true);
    void relay.action('connect');
  }, [profiles.loaded, profiles.settings.mode, settingsLoaded, startupAutoConnectRequested, relay.action]);

  useEffect(() => {
    if (
      !settingsLoaded
      || profiles.settings.mode === 'internet'
      || !startupAutoConnectRequested
      || !hasConnectionConfig
      || startupAutoConnectStartedRef.current
    ) {
      return;
    }
    startupAutoConnectStartedRef.current = true;
    let alive = true;
    const attempt = connectionAttemptRef.current;
    setStatus('connecting');
    setTransport('none');
    setError('');

    const discover = async () => {
      let discoveredBaseUrl = '';
      try {
        const phoneIp = await Network.getIpAddressAsync();
        if (!alive || attempt !== connectionAttemptRef.current) return;
        discoveredBaseUrl = await discoverRemoteBaseUrl({
          phoneIp,
          pairingCode: client.pairingCode,
          preferredBaseUrl: client.baseUrl,
        });
      } catch {
        discoveredBaseUrl = '';
      }
      if (!alive || attempt !== connectionAttemptRef.current) {
        return;
      }
      if (discoveredBaseUrl && discoveredBaseUrl !== client.baseUrl) {
        setBaseUrlValue(discoveredBaseUrl);
      }
      setStartupDiscoveryComplete(true);
    };

    void discover();
    return () => {
      alive = false;
    };
  }, [client.auth.kind, client.baseUrl, client.pairingCode, hasConnectionConfig, settingsLoaded, startupAutoConnectRequested, profiles.settings.mode]);

  useEffect(() => {
    if (
      !startupDiscoveryComplete
      || !hasConnectionConfig
      || startupAutoConnectCompletedRef.current
    ) {
      return;
    }
    startupAutoConnectCompletedRef.current = true;
    void connect();
  }, [connect, hasConnectionConfig, startupDiscoveryComplete]);

  useEffect(() => {
    if (!pendingPairingConnectionKey || connectionKey !== pendingPairingConnectionKey) {
      return;
    }
    setPendingPairingConnectionKey('');
    void connectActive();
  }, [connectActive, connectionKey, pendingPairingConnectionKey]);

  const sendText = useCallback(
    async (text: string, sendOptions: SendTextOptions = {}) => {
      const message = text.trim();
      if (!message) {
        return;
      }
      const submitStartedAtMs = Date.now();
      const debugTraceId = `text-${submitStartedAtMs}-${Math.random().toString(16).slice(2, 10)}`;
      const baselineAssistantIds = assistantMessageMarkers(state).map((item) => item.id);
      void recordPhoneDebug('info', 'text_turn_submit_started', {
        debug_trace_id: debugTraceId,
        started_at_ms: submitStartedAtMs,
        character_count: message.length,
        capture_phone_audio: sendOptions.audioMode !== 'phone_native',
        play_on_backend: false,
      });
      const payload = {
        play_on_backend: false,
        capture_phone_audio: sendOptions.audioMode !== 'phone_native',
        audio_mode: sendOptions.audioMode ?? 'backend_hq',
        visual_after_send: Boolean(sendOptions.visualAfterSend),
        debug_trace_id: debugTraceId,
        ...(sendOptions.phoneReplyAuth ? { phone_reply_auth: sendOptions.phoneReplyAuth } : {}),
      };
      try {
        // An opt-in explicit turn has no retry identity: one HTTP dispatch only.
        const result = sendOptions.phoneReplyAuth
          ? await client.sendText(message, { ...sendOptions, debugTraceId })
          : await sendSocketCommand('send_text', 'send_result', { text: message, payload }) ?? await client.sendText(message, { ...sendOptions, debugTraceId });
        const errorMessage = remoteActionError(result, 'Main chat message was not accepted.');
        if (errorMessage) {
          throw new Error(errorMessage);
        }
        const acceptedAtMs = Date.now();
        void recordPhoneDebug('info', 'text_turn_accepted', {
          debug_trace_id: debugTraceId,
          accepted_at_ms: acceptedAtMs,
          submit_to_accept_ms: Math.max(0, acceptedAtMs - submitStartedAtMs),
          transport: socketRef.current?.readyState === WebSocket.OPEN ? 'websocket' : 'http',
        });
        const timer = setTimeout(() => {
          pendingReplyDiagnosticsRef.current.delete(debugTraceId);
          void recordPhoneDebug('warning', 'text_turn_reply_timeout', {
            debug_trace_id: debugTraceId,
            waited_ms: REPLY_DIAGNOSTIC_TIMEOUT_MS,
            assistant_message_count: assistantMessageMarkers(latestStateRef.current).length,
          }).then(() => client.uploadDebug('text_reply_timeout')).catch(() => undefined);
        }, REPLY_DIAGNOSTIC_TIMEOUT_MS);
        pendingReplyDiagnosticsRef.current.set(debugTraceId, {
          debugTraceId,
          connectionKey,
          acceptedAtMs,
          baselineAssistantIds,
          timer,
        });
        void refresh().catch(() => undefined);
        return result;
      } catch (exc) {
        void recordPhoneDebug('error', 'text_turn_rejected', {
          debug_trace_id: debugTraceId,
          elapsed_ms: Math.max(0, Date.now() - submitStartedAtMs),
          error: exc instanceof Error ? exc.message : 'Main chat message was not accepted.',
        }).then(() => client.uploadDebug('text_rejected')).catch(() => undefined);
        throw exc;
      }
    },
    [client, connectionKey, refresh, sendSocketCommand, state],
  );

  const sendImage = useCallback(async (
    imageBase64: string,
    format: string,
    prompt: string,
    sendOptions: SendTextOptions = {},
  ) => {
    const startedAtMs = Date.now();
    const debugTraceId = `photo-${startedAtMs}-${Math.random().toString(16).slice(2, 10)}`;
    void recordPhoneDebug('info', 'photo_turn_upload_started', {
      debug_trace_id: debugTraceId,
      encoded_character_count: imageBase64.length,
      format,
      prompt_character_count: prompt.length,
    });
    try {
      const result = await client.sendImage(imageBase64, format, prompt, { ...sendOptions, debugTraceId });
      const errorMessage = remoteActionError(result, 'Phone photo was not accepted.');
      if (errorMessage) {
        throw new Error(errorMessage);
      }
      void recordPhoneDebug('info', 'photo_turn_accepted', {
        debug_trace_id: debugTraceId,
        upload_to_accept_ms: Math.max(0, Date.now() - startedAtMs),
      });
      void refresh().catch(() => undefined);
      return result;
    } catch (exc) {
      void recordPhoneDebug('error', 'photo_turn_rejected', {
        debug_trace_id: debugTraceId,
        elapsed_ms: Math.max(0, Date.now() - startedAtMs),
        error: exc instanceof Error ? exc.message : 'Phone photo was not accepted.',
      }).then(() => client.uploadDebug('photo_rejected')).catch(() => undefined);
      throw exc;
    }
  }, [client, refresh]);

  const clearAudio = useCallback(async () => {
    const result = await client.clearAudio();
    const errorMessage = remoteActionError(result, 'Phone audio queue could not be cleared.');
    if (errorMessage) {
      throw new Error(errorMessage);
    }
    await refresh();
  }, [client, refresh]);

  const sendControl = useCallback(
    async (action: string, sendOptions: SendTextOptions = {}) => {
      const payload = {};
      const result = await sendSocketCommand('control', 'control_result', { action, payload }) ?? await client.control(action, sendOptions);
      const errorMessage = remoteActionError(result, 'Runtime control was not accepted.');
      if (errorMessage) {
        throw new Error(errorMessage);
      }
      await refresh();
    },
    [client, refresh, sendSocketCommand],
  );

  const visualGenerate = useCallback(async (prompt: string, options: VisualRequestOptions = {}) => {
    const text = prompt.trim();
    const result = await sendSocketCommand('visual', 'visual_result', {
      payload: {
        prompt: text,
        action: 'generate',
        turn_id: options.turnId || '',
        normal_chat_transaction_id: options.normalChatTransactionId || '',
        refine_prompt: options.refinePrompt === true,
      },
    });
    return result ?? await client.visual(text, options);
  }, [client, sendSocketCommand]);

  const visualAction = useCallback(async (action: VisualAction) => {
    const result = await sendSocketCommand('visual', 'visual_result', {
      payload: { action },
    });
    return result ?? await client.visualAction(action);
  }, [client, sendSocketCommand]);

  const sendStoryText = useCallback(async (text: string, options: MprcSendOptions = {}) => {
    const message = text.trim();
    if (!message) {
      return;
    }
    const result = await client.mprcSend(message, options);
    const errorMessage = remoteActionError(result, 'Story message was not accepted.');
    if (errorMessage) {
      throw new Error(errorMessage);
    }
    await refresh();
  }, [client, refresh]);

  const selectStoryChoice = useCallback(async (choice: string) => {
    const value = choice.trim();
    if (!value) {
      return;
    }
    const result = await client.mprcChoice(value);
    const errorMessage = remoteActionError(result, 'Story choice was not accepted.');
    if (errorMessage) {
      throw new Error(errorMessage);
    }
    await refresh();
  }, [client, refresh]);

  const storyAction = useCallback(async (action: MprcAction) => {
    const result = await client.mprcAction(action);
    const errorMessage = remoteActionError(result, 'Story action was not accepted.');
    if (errorMessage) {
      throw new Error(errorMessage);
    }
    await refresh();
  }, [client, refresh]);

  const storyCastAction = useCallback(async (action: MprcCastAction, deviceName = '') => {
    const result = await client.mprcCast(action, deviceName);
    const errorMessage = remoteActionError(result, 'Chromecast action was not accepted.');
    if (errorMessage) {
      throw new Error(errorMessage);
    }
    await refresh();
  }, [client, refresh]);

  const startEngine = useCallback(async () => {
    const result = await sendSocketCommand('engine_start', 'engine_start_result', {}) ?? await client.engineStart();
    const errorMessage = remoteActionError(result, 'Engine start was not accepted.');
    if (errorMessage) {
      throw new Error(errorMessage);
    }
    await refresh();
  }, [client, refresh, sendSocketCommand]);

  const stopEngine = useCallback(async () => {
    const result = await sendSocketCommand('engine_stop', 'engine_stop_result', {}) ?? await client.engineStop();
    const errorMessage = remoteActionError(result, 'Engine stop was not accepted.');
    if (errorMessage) {
      throw new Error(errorMessage);
    }
    await refresh();
  }, [client, refresh, sendSocketCommand]);

  const setBaseUrl = useCallback((value: string) => {
    setBaseUrlValue(value);
  }, []);

  const setPairingCodeValue = useCallback((value: string) => {
    setPairingCode(normalizePairingCode(value));
  }, []);

  const enrollInternetAndConnect = useCallback(async (_setup: InternetPairingSetup, _deviceName = 'NeuralCompanion phone') => {
    disconnect();
    relay.session.disconnect();
    profiles.setMode('internet');
    setActiveTarget(null);
    setEnrollmentStatus('Internet pairing now uses NC Relay. Sign in to the same account as your desktop.');
    setError('This QR belongs to the previous Internet gateway. Use NC Relay sign-in below.');
    return false;
  }, [disconnect, profiles.setMode, relay.session]);

  const pairAndConnect = useCallback((nextBaseUrl: string, nextPairingCode: string) => {
    const normalizedBaseUrl = normalizeLanUrl(nextBaseUrl);
    const normalizedPairingCode = normalizePairingCode(nextPairingCode);
    if (
      !normalizedBaseUrl
      || normalizedPairingCode.length < MIN_PAIRING_CODE_DIGITS
      || normalizedPairingCode.length > MAX_PAIRING_CODE_DIGITS
    ) {
      setError('The scanned pairing QR code is invalid.');
      setStatus('error');
      return false;
    }
    disconnect();
    relay.session.disconnect();
    setBaseUrlValue(normalizedBaseUrl);
    setPairingCode(normalizedPairingCode);
    profiles.setMode('lan');
    const target: ConnectionTarget = { route: 'lan', baseUrl: normalizedBaseUrl, gatewayId: '', deviceId: '', auth: { kind: 'lan', pairingCode: normalizedPairingCode } };
    setActiveTarget(target);
    setPendingPairingConnectionKey(targetConnectionKey(target));
    return true;
  }, [disconnect, profiles.setMode, relay.session]);

  return {
    relay,
    // Private durable recovery scope; do not include transient peer IDs, reply
    // epochs or transport credential generations. The desktop authority marker
    // changes only when its recovery registry is replaced. Never log this value.
    orderedRecoveryProfile: scopeOrderedRecoveryProfile(activeRoute === 'internet_relay' ? relay.session.orderedRecoveryProfile
      : client.auth.kind === 'lan' ? JSON.stringify(['lan', normalizeLanUrl(client.baseUrl), client.pairingCode])
      : JSON.stringify(['internet', profiles.settings.internet.gatewayId, client.auth.deviceId, client.auth.deviceToken, client.baseUrl]),
      state?.ordered_output_instance),
    chatCharacterScope: JSON.stringify([client.identityKey, profiles.credentialGeneration, state?.conversation_actions?.session_generation]),
    chatCharactersAvailable: state?.features?.chat_characters_version === 1,
    continuousAvailable: state?.features?.continuous_version === 1,
    // Stable across transport replacement, never across credentials or an
    // intentional disconnect. Private, in-memory scope only; never log this key.
    liveRecoveryKey: activeRoute === 'internet_relay'
      ? (relay.session.wantsConnection ? relay.session.recoveryKey : '')
      : (reconnectEnabledRef.current && autoReconnect
        ? (needsLocalMedia && !localMedia.desktopInstance ? ''
          : JSON.stringify([client.identityKey, profiles.credentialGeneration, client.pairingCode,
            needsLocalMedia ? localMedia.desktopInstance : ''])) : ''),
    // Historical name; both media routes now have a verified desktop binding.
    relayRecoveryKey: activeRoute === 'internet_relay' ? relay.session.recoveryKey
      : needsLocalMedia && localMedia.desktopInstance
        ? JSON.stringify([client.identityKey, profiles.credentialGeneration, client.pairingCode, localMedia.desktopInstance]) : '',
    baseUrl,
    pairingCode,
    connectionMode: profiles.settings.mode,
    internetProfile: profiles.settings.internet,
    activeRoute,
    enrollmentStatus,
    status,
    transport,
    error: error || localMedia.error,
    health,
    settingsLoaded,
    state,
    connected,
    playbackConnected,
    mediaContinuity: activeRoute === 'internet_relay' && relay.session.mediaContinuity,
    connectionRecoveryReady,
    client,
    phoneReplyOwner,
    getPhoneReplyAuth,
    pollToken,
    transportFailureRevision: transportFailureRevision + localMedia.failureRevision,
    setBaseUrl,
    setPairingCode: setPairingCodeValue,
    pairAndConnect,
    enrollInternetAndConnect,
    setConnectionMode: (mode: typeof profiles.settings.mode) => { disconnect(); relay.session.disconnect(); profiles.setMode(mode); },
    forgetInternet: profiles.forgetInternet,
    connect,
    disconnect: () => { disconnect(); relay.session.disconnect(); },
    refresh,
    sendText,
    sendImage,
    clearAudio,
    sendControl,
    visualGenerate,
    visualAction,
    sendStoryText,
    selectStoryChoice,
    storyAction,
    storyCastAction,
    startEngine,
    stopEngine,
  };
}
import { setBackgroundInterval as setInterval, setBackgroundTimeout as setTimeout, clearBackgroundTimer as clearInterval, clearBackgroundTimer as clearTimeout } from '../utils/backgroundClock';
