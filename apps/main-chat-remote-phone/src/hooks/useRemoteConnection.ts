import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as Network from 'expo-network';

import { RemoteClient, isRemoteAuthError } from '../api/client';
import type { SendTextOptions } from '../api/client';
import type { MprcAction, MprcCastAction, MprcSendOptions } from '../api/client';
import type { VisualAction } from '../api/client';
import { isRecord, remoteActionError } from '../api/envelope';
import type { RemoteConnectionStatus, RemoteEnvelope, RemoteHealth, RemoteState, RemoteTransport } from '../api/types';
import { mergeAudioSnapshot, mergeRemoteSnapshot } from '../utils/audioFastStart';
import { discoverRemoteBaseUrl } from '../utils/lanDiscovery';
import { recordPhoneDebug } from '../utils/phoneDebugBridge';
import { normalizeLanUrl } from '../utils/url';
import { useConnectionProfiles } from './useConnectionProfiles';
import { connectCandidates, connectionCandidates, type ConnectionRoute, type ConnectionTarget, type ProbeFailureReason } from '../utils/connectionProfiles';
import type { InternetPairingSetup } from '../utils/pairingSetup';

const DEFAULT_POLL_INTERVAL_MS = 1800;
const RECONNECT_BASE_DELAY_MS = 1000;
const RECONNECT_MAX_DELAY_MS = 15000;
const WEBSOCKET_STALE_MS = 8000;
const WEBSOCKET_COMMAND_TIMEOUT_MS = 10000;
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
type RemoteConnectionOptions = {
  autoReconnect?: boolean;
  pollingIntervalMs?: number;
};

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
  const socketRef = useRef<WebSocket | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const socketWatchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectEnabledRef = useRef(false);
  const reconnectAttemptsRef = useRef(0);
  const pollInFlightRef = useRef<{ key: string; id: number } | null>(null);
  const pollSequenceRef = useRef(0);
  const openSocketRef = useRef<() => void>(() => undefined);
  const activeConnectionKeyRef = useRef('');
  const socketCommandSequenceRef = useRef(0);
  const pendingSocketCommandsRef = useRef<Map<string, PendingSocketCommand>>(new Map());
  const startupAutoConnectStartedRef = useRef(false);
  const startupAutoConnectCompletedRef = useRef(false);
  const enrollmentAbortRef = useRef<AbortController | null>(null);

  const client = useMemo(() => {
    if (activeTarget?.auth.kind === 'internet') return RemoteClient.forInternet(activeTarget.baseUrl, activeTarget.auth.deviceId, activeTarget.auth.deviceToken);
    if (activeTarget?.auth.kind === 'lan') return RemoteClient.forLan(activeTarget.baseUrl, activeTarget.auth.pairingCode);
    return RemoteClient.forLan(normalizeLanUrl(baseUrl), pairingCode.trim());
  }, [activeTarget, baseUrl, pairingCode, profiles.credentialGeneration]);
  const autoReconnect = options.autoReconnect !== false;
  const pollingIntervalMs = normalizePollingInterval(options.pollingIntervalMs);
  const hasValidPairingCode = client.auth.kind === 'internet' || (client.pairingCode.length >= MIN_PAIRING_CODE_DIGITS && client.pairingCode.length <= MAX_PAIRING_CODE_DIGITS);
  const hasConnectionConfig = Boolean(client.baseUrl && hasValidPairingCode);
  const activeRoute: ConnectionRoute = activeTarget?.route || 'lan';
  const connectionKey = `${activeRoute}|${client.baseUrl}|${activeTarget?.gatewayId || ''}|${activeTarget?.deviceId || ''}`;
  const connected = status === 'connected';

  useEffect(() => {
    if (!profiles.loaded) return;
    const savedLan = profiles.settings.lan;
    if (savedLan.baseUrl) setBaseUrlValue(savedLan.baseUrl);
    if (savedLan.pairingCode) setPairingCode(savedLan.pairingCode);
    const candidates = connectionCandidates(profiles.settings);
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

  const stopActiveConnectionAfterAuthFailure = useCallback((message: string, key: string) => {
    if (activeConnectionKeyRef.current !== key) {
      return;
    }
    reconnectEnabledRef.current = false;
    clearReconnect();
    clearSocketWatchdog();
    rejectPendingSocketCommands('Pairing authorization failed before the command result was confirmed.', key);
    const socket = socketRef.current;
    socketRef.current = null;
    socket?.close();
    stopPolling();
    activeConnectionKeyRef.current = '';
    setError(message);
    setStatus('error');
    setTransport('none');
  }, [clearReconnect, clearSocketWatchdog, rejectPendingSocketCommands, stopPolling]);

  const refreshActiveConnection = useCallback(async () => {
    if (!client.baseUrl) {
      throw new Error('A saved LAN or Internet connection is required.');
    }
    if (!hasValidPairingCode) {
      throw new Error(`Pairing code must be ${MIN_PAIRING_CODE_DIGITS}-${MAX_PAIRING_CODE_DIGITS} digits.`);
    }
    const health = await client.health(activeTarget?.gatewayId || '');
    setHealth(health);
    const readinessError = healthError(health);
    if (readinessError) {
      throw new Error(readinessError);
    }
    const nextState = await client.state();
    if (activeConnectionKeyRef.current !== connectionKey) {
      return false;
    }
    setState((current) => mergeRemoteSnapshot(current, nextState));
    setStatus('connected');
    setTransport((current) => (current === 'websocket' ? current : 'polling'));
    setError('');
    return true;
  }, [activeTarget?.gatewayId, client, connectionKey, hasValidPairingCode]);

  const refresh = useCallback(async () => {
    try {
      await refreshActiveConnection();
    } catch (exc) {
      if (activeConnectionKeyRef.current !== connectionKey) {
        return;
      }
      if (isRemoteAuthError(exc)) {
        stopActiveConnectionAfterAuthFailure(exc instanceof Error ? exc.message : 'Pairing authorization failed.', connectionKey);
        return;
      }
      setError(exc instanceof Error ? exc.message : 'Refresh failed.');
      setStatus('error');
      setTransport((current) => (current === 'websocket' ? current : pollingRef.current ? 'polling' : 'none'));
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
            stopActiveConnectionAfterAuthFailure(exc instanceof Error ? exc.message : 'Pairing authorization failed.', connectionKey);
            return;
          }
          setError(exc instanceof Error ? exc.message : 'Polling failed.');
          setStatus('error');
          setTransport('polling');
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
      if (!autoReconnect) {
        setError('WebSocket stopped receiving state.');
        setStatus('error');
        setTransport('none');
        socket.close();
        return;
      }
      setError('WebSocket stopped receiving state. Polling fallback is active while reconnecting.');
      setStatus('error');
      setTransport('polling');
      startPolling();
      scheduleReconnect();
      socket.close();
    }, WEBSOCKET_STALE_MS);
  }, [autoReconnect, clearSocketWatchdog, connectionKey, scheduleReconnect, startPolling]);

  const openSocket = useCallback(async () => {
    if (!hasConnectionConfig) {
      return;
    }
    let websocketUrl = '';
    try {
      websocketUrl = await client.websocketUrl();
    } catch (exc) {
      if (activeConnectionKeyRef.current !== connectionKey) return;
      setError(exc instanceof Error ? exc.message : 'WebSocket authorization failed.');
      setStatus('error'); setTransport('polling'); startPolling(); scheduleReconnect(); return;
    }
    if (activeConnectionKeyRef.current !== connectionKey) return;
    const socket = new WebSocket(websocketUrl);
    socketRef.current = socket;
    socket.onopen = () => {
      if (activeConnectionKeyRef.current !== connectionKey || socketRef.current !== socket) {
        socket.close();
        return;
      }
      reconnectAttemptsRef.current = 0;
      clearReconnect();
      stopPolling();
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
        if (message.type === 'state') {
          const payload = message.payload;
          if (isRecord(payload) && 'ok' in payload) {
            if (payload.ok === false) {
              setError(String(payload.error || 'Remote state request failed.'));
              setStatus('error');
              return;
            }
            if (isRecord(payload.state)) {
              setState((current) => mergeRemoteSnapshot(current, payload.state as RemoteState));
              setStatus('connected');
              setError('');
              return;
            }
            setError('Remote state payload was missing state data.');
            setStatus('error');
            return;
          }
          if (isRecord(payload)) {
            setState((current) => mergeRemoteSnapshot(current, payload as RemoteState));
            setStatus('connected');
            setError('');
          }
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
          setStatus('error');
        }
      } catch {
        return;
      }
    };
    socket.onerror = () => {
      if (activeConnectionKeyRef.current !== connectionKey || socketRef.current !== socket) {
        socket.close();
        return;
      }
      if (!autoReconnect) {
        setError('WebSocket failed.');
        setStatus('error');
        setTransport('none');
        socket.close();
        return;
      }
      setError('WebSocket failed. Polling fallback is active while reconnecting.');
      setStatus('error');
      setTransport('polling');
      startPolling();
      socket.close();
    };
    socket.onclose = () => {
      if (socketRef.current === socket) {
        socketRef.current = null;
        clearSocketWatchdog();
        rejectPendingSocketCommands('WebSocket disconnected before the command result was confirmed.', connectionKey);
        if (autoReconnect && reconnectEnabledRef.current && activeConnectionKeyRef.current === connectionKey) {
          setError('WebSocket disconnected. Polling fallback is active while reconnecting.');
          setStatus('error');
          setTransport('polling');
          startPolling();
          scheduleReconnect();
        }
      }
    };
  }, [autoReconnect, clearReconnect, clearSocketWatchdog, client, connectionKey, hasConnectionConfig, rejectPendingSocketCommands, scheduleReconnect, scheduleSocketWatchdog, startPolling, stopPolling]);

  useEffect(() => {
    openSocketRef.current = openSocket;
  }, [openSocket]);

  useEffect(() => () => {
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
    enrollmentAbortRef.current?.abort();
    enrollmentAbortRef.current = null;
    setEnrollmentStatus('');
    reconnectEnabledRef.current = false;
    clearReconnect();
    clearSocketWatchdog();
    rejectPendingSocketCommands('Disconnected before the command result was confirmed.');
    activeConnectionKeyRef.current = '';
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
    reconnectEnabledRef.current = autoReconnect;
    reconnectAttemptsRef.current = 0;
    activeConnectionKeyRef.current = connectionKey;
    setStatus('connecting');
    setTransport('none');
    try {
      const applied = await refreshActiveConnection();
      if (!applied || activeConnectionKeyRef.current !== connectionKey) {
        return;
      }
      openSocket();
      startPolling();
    } catch (exc) {
      if (activeConnectionKeyRef.current !== connectionKey) {
        return;
      }
      if (isRemoteAuthError(exc)) {
        stopActiveConnectionAfterAuthFailure(exc instanceof Error ? exc.message : 'Pairing authorization failed.', connectionKey);
        return;
      }
      setError(exc instanceof Error ? exc.message : 'Connection failed.');
      setStatus('error');
      if (autoReconnect && hasConnectionConfig) {
        setTransport('polling');
        startPolling();
        scheduleReconnect();
      } else {
        setTransport('none');
      }
    }
  }, [autoReconnect, connectionKey, disconnect, hasConnectionConfig, openSocket, refreshActiveConnection, scheduleReconnect, startPolling, stopActiveConnectionAfterAuthFailure]);

  const connect = useCallback(async () => {
    const candidates = connectionCandidates({ ...profiles.settings, lan: { baseUrl: normalizeLanUrl(baseUrl), pairingCode: normalizePairingCode(pairingCode) } });
    if (!candidates.length) { setError('Save a valid LAN pairing or enroll this phone for Internet access first.'); setStatus('error'); return; }
    setStatus('connecting'); setTransport('none'); setError('');
    const selected = await connectCandidates(candidates, async (target) => {
      const probeClient = target.auth.kind === 'lan' ? RemoteClient.forLan(target.baseUrl, target.auth.pairingCode) : RemoteClient.forInternet(target.baseUrl, target.auth.deviceId, target.auth.deviceToken);
      try {
        const result = await probeClient.health(target.gatewayId); const readinessError = healthError(result);
        return readinessError ? { ok: false as const, reason: 'unreachable' as const, error: readinessError } : { ok: true as const };
      } catch (exc) { return { ok: false as const, reason: probeFailureReason(exc), error: exc instanceof Error ? exc.message : String(exc) }; }
    });
    if (!selected.target) {
      setError(selected.terminalReason ? `Connection stopped for safety: ${selected.terminalReason.replace(/_/g, ' ')}.` : 'No saved connection route could reach NeuralCompanion.');
      setStatus('error'); setTransport('none'); return;
    }
    const nextKey = targetConnectionKey(selected.target);
    if (nextKey === connectionKey) { await connectActive(); return; }
    setActiveTarget(selected.target); setPendingPairingConnectionKey(nextKey);
  }, [baseUrl, connectActive, connectionKey, pairingCode, profiles.settings]);

  useEffect(() => {
    if (
      !settingsLoaded
      || !startupAutoConnectRequested
      || !hasConnectionConfig
      || startupAutoConnectStartedRef.current
    ) {
      return;
    }
    startupAutoConnectStartedRef.current = true;
    let alive = true;
    setStatus('connecting');
    setTransport('none');
    setError('');

    const discover = async () => {
      let discoveredBaseUrl = '';
      try {
        const phoneIp = await Network.getIpAddressAsync();
        discoveredBaseUrl = await discoverRemoteBaseUrl({
          phoneIp,
          pairingCode: client.pairingCode,
          preferredBaseUrl: client.baseUrl,
        });
      } catch {
        discoveredBaseUrl = '';
      }
      if (!alive) {
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
  }, [client.auth.kind, client.baseUrl, client.pairingCode, hasConnectionConfig, settingsLoaded, startupAutoConnectRequested]);

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
      void recordPhoneDebug('info', 'text_turn_submit_started', {
        started_at_ms: submitStartedAtMs,
        capture_phone_audio: sendOptions.capturePhoneAudio !== false,
        play_on_backend: Boolean(sendOptions.playOnBackend),
      });
      const payload = {
        play_on_backend: Boolean(sendOptions.playOnBackend),
        capture_phone_audio: sendOptions.capturePhoneAudio !== false,
        visual_after_send: Boolean(sendOptions.visualAfterSend),
      };
      try {
        const result = await sendSocketCommand('send_text', 'send_result', { text: message, payload }) ?? await client.sendText(message, sendOptions);
        const errorMessage = remoteActionError(result, 'Main chat message was not accepted.');
        if (errorMessage) {
          throw new Error(errorMessage);
        }
        const acceptedAtMs = Date.now();
        void recordPhoneDebug('info', 'text_turn_accepted', {
          accepted_at_ms: acceptedAtMs,
          submit_to_accept_ms: Math.max(0, acceptedAtMs - submitStartedAtMs),
          transport: socketRef.current?.readyState === WebSocket.OPEN ? 'websocket' : 'http',
        });
      } catch (exc) {
        void recordPhoneDebug('error', 'text_turn_rejected', {
          elapsed_ms: Math.max(0, Date.now() - submitStartedAtMs),
          error: exc instanceof Error ? exc.message : 'Main chat message was not accepted.',
        });
        throw exc;
      }
      await refresh();
    },
    [client, refresh, sendSocketCommand],
  );

  const sendImage = useCallback(async (
    imageBase64: string,
    format: string,
    prompt: string,
    sendOptions: SendTextOptions = {},
  ) => {
    const result = await client.sendImage(imageBase64, format, prompt, sendOptions);
    const errorMessage = remoteActionError(result, 'Phone photo was not accepted.');
    if (errorMessage) {
      throw new Error(errorMessage);
    }
    await refresh();
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
      const payload = {
        play_on_backend: Boolean(sendOptions.playOnBackend),
        capture_phone_audio: sendOptions.capturePhoneAudio !== false,
      };
      const result = await sendSocketCommand('control', 'control_result', { action, payload }) ?? await client.control(action, sendOptions);
      const errorMessage = remoteActionError(result, 'Runtime control was not accepted.');
      if (errorMessage) {
        throw new Error(errorMessage);
      }
      await refresh();
    },
    [client, refresh, sendSocketCommand],
  );

  const visualGenerate = useCallback(async (prompt: string) => {
    const text = prompt.trim();
    const result = await sendSocketCommand('visual', 'visual_result', {
      payload: { prompt: text, action: 'generate' },
    });
    return result ?? await client.visual(text);
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

  const enrollInternetAndConnect = useCallback(async (setup: InternetPairingSetup, deviceName = 'NeuralCompanion phone') => {
    enrollmentAbortRef.current?.abort();
    const controller = new AbortController(); enrollmentAbortRef.current = controller;
    setEnrollmentStatus('Requesting approval from desktop...'); setStatus('connecting'); setError('');
    const deviceId = `phone-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    const origins = [setup.hostnameUrl, setup.ipUrl].filter((value, index, values) => value && values.indexOf(value) === index);
    let selectedOrigin = '';
    const readJson = async (response: Response) => {
      const payload = await response.json() as Record<string, unknown>;
      if (!response.ok || payload.ok === false) throw new Error(String(payload.error || `Enrollment failed with HTTP ${response.status}.`));
      return payload;
    };
    try {
      let lastError: unknown = null;
      for (const origin of origins) {
        try {
          const response = await fetch(`${origin}/internet/enroll/submit`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enrollment_id: setup.enrollmentId, secret: setup.secret, device_id: deviceId, device_name: String(deviceName || 'NeuralCompanion phone').trim().slice(0, 128) }), signal: controller.signal });
          await readJson(response); selectedOrigin = origin; break;
        } catch (exc) { if (controller.signal.aborted) throw exc; lastError = exc; }
      }
      if (!selectedOrigin) throw lastError || new Error('Internet enrollment endpoint is unreachable.');
      setEnrollmentStatus('Waiting for approval on desktop');
      const deadline = Date.now() + 10 * 60 * 1000;
      while (Date.now() < deadline && !controller.signal.aborted) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        if (controller.signal.aborted) break;
        const query = new URLSearchParams({ enrollment_id: setup.enrollmentId, secret: setup.secret });
        const payload = await readJson(await fetch(`${selectedOrigin}/internet/enroll/status?${query.toString()}`, { signal: controller.signal }));
        if (String(payload.status || '') !== 'complete') continue;
        const deviceToken = String(payload.device_token || ''); const returnedGatewayId = String(payload.gateway_id || '');
        if (deviceToken.length < 43 || returnedGatewayId !== setup.gatewayId) throw new Error('Desktop approval returned invalid or mismatched credentials.');
        const internet = { hostnameUrl: setup.hostnameUrl, ipUrl: setup.ipUrl, deviceId, gatewayId: setup.gatewayId, deviceToken };
        profiles.setInternet(internet); profiles.setMode('internet');
        const target: ConnectionTarget = { route: selectedOrigin === setup.hostnameUrl ? 'internet_hostname' : 'internet_ip', baseUrl: selectedOrigin, deviceId, gatewayId: setup.gatewayId, auth: { kind: 'internet', deviceId, deviceToken } };
        setActiveTarget(target); setPendingPairingConnectionKey(targetConnectionKey(target)); setEnrollmentStatus('Approved. Connecting securely...'); return true;
      }
      if (controller.signal.aborted) { setEnrollmentStatus('Enrollment cancelled.'); return false; }
      throw new Error('Desktop approval timed out. Create a new enrollment QR and try again.');
    } catch (exc) {
      if (!controller.signal.aborted) { setError(exc instanceof Error ? exc.message : 'Internet enrollment failed.'); setStatus('error'); setEnrollmentStatus('Enrollment failed.'); }
      return false;
    } finally { if (enrollmentAbortRef.current === controller) enrollmentAbortRef.current = null; }
  }, [profiles.setInternet, profiles.setMode]);

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
    setBaseUrlValue(normalizedBaseUrl);
    setPairingCode(normalizedPairingCode);
    profiles.setMode('lan');
    const target: ConnectionTarget = { route: 'lan', baseUrl: normalizedBaseUrl, gatewayId: '', deviceId: '', auth: { kind: 'lan', pairingCode: normalizedPairingCode } };
    setActiveTarget(target);
    setPendingPairingConnectionKey(targetConnectionKey(target));
    return true;
  }, [profiles.setMode]);

  return {
    baseUrl,
    pairingCode,
    connectionMode: profiles.settings.mode,
    internetProfile: profiles.settings.internet,
    activeRoute,
    enrollmentStatus,
    status,
    transport,
    error,
    health,
    settingsLoaded,
    state,
    connected,
    client,
    pollToken,
    setBaseUrl,
    setPairingCode: setPairingCodeValue,
    pairAndConnect,
    enrollInternetAndConnect,
    setConnectionMode: profiles.setMode,
    forgetInternet: profiles.forgetInternet,
    connect,
    disconnect,
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
