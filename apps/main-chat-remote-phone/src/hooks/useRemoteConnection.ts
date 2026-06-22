import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as SecureStore from 'expo-secure-store';

import { RemoteClient, isRemoteAuthError } from '../api/client';
import type { SendTextOptions } from '../api/client';
import type { MprcAction, MprcCastAction, MprcSendOptions } from '../api/client';
import type { VisualAction } from '../api/client';
import { isRecord, remoteActionError } from '../api/envelope';
import type { RemoteConnectionStatus, RemoteEnvelope, RemoteHealth, RemoteState, RemoteTransport } from '../api/types';
import { normalizeLanUrl } from '../utils/url';

const CONNECTION_SETTINGS_KEY = 'nc-main-chat-remote.connection';
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

export function useRemoteConnection(options: RemoteConnectionOptions = {}) {
  const [baseUrl, setBaseUrlValue] = useState('http://192.168.1.10:8777');
  const [pairingCode, setPairingCode] = useState('');
  const [status, setStatus] = useState<RemoteConnectionStatus>('disconnected');
  const [transport, setTransport] = useState<RemoteTransport>('none');
  const [error, setError] = useState('');
  const [health, setHealth] = useState<RemoteEnvelope<RemoteHealth> | null>(null);
  const [settingsLoaded, setSettingsLoaded] = useState(false);
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

  const client = useMemo(() => new RemoteClient(normalizeLanUrl(baseUrl), pairingCode.trim()), [baseUrl, pairingCode]);
  const autoReconnect = options.autoReconnect !== false;
  const pollingIntervalMs = normalizePollingInterval(options.pollingIntervalMs);
  const hasValidPairingCode = client.pairingCode.length >= MIN_PAIRING_CODE_DIGITS && client.pairingCode.length <= MAX_PAIRING_CODE_DIGITS;
  const hasConnectionConfig = Boolean(client.baseUrl && hasValidPairingCode);
  const connectionKey = `${client.baseUrl}|${client.pairingCode}`;
  const connected = status === 'connected';

  useEffect(() => {
    let alive = true;
    SecureStore.getItemAsync(CONNECTION_SETTINGS_KEY)
      .then((raw) => {
        if (!alive || !raw) {
          return;
        }
        const payload = JSON.parse(raw) as { baseUrl?: string; pairingCode?: string };
        if (typeof payload.baseUrl === 'string' && payload.baseUrl.trim()) {
          setBaseUrlValue(payload.baseUrl);
        }
        if (typeof payload.pairingCode === 'string') {
          setPairingCode(normalizePairingCode(payload.pairingCode));
        }
      })
      .catch(() => undefined)
      .finally(() => {
        if (alive) {
          setSettingsLoaded(true);
        }
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!settingsLoaded) {
      return;
    }
    const payload = JSON.stringify({ baseUrl, pairingCode });
    SecureStore.setItemAsync(CONNECTION_SETTINGS_KEY, payload).catch(() => undefined);
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
      throw new Error('LAN URL and pairing code are required.');
    }
    if (!hasValidPairingCode) {
      throw new Error(`Pairing code must be ${MIN_PAIRING_CODE_DIGITS}-${MAX_PAIRING_CODE_DIGITS} digits.`);
    }
    const health = await client.health();
    setHealth(health);
    const readinessError = healthError(health);
    if (readinessError) {
      throw new Error(readinessError);
    }
    const nextState = await client.state();
    if (activeConnectionKeyRef.current !== connectionKey) {
      return false;
    }
    setState(nextState);
    setStatus('connected');
    setTransport((current) => (current === 'websocket' ? current : 'polling'));
    setError('');
    return true;
  }, [client, connectionKey, hasValidPairingCode]);

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

  const openSocket = useCallback(() => {
    if (!hasConnectionConfig) {
      return;
    }
    const socket = new WebSocket(client.websocketUrl());
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
              setState(payload.state as RemoteState);
              setStatus('connected');
              setError('');
              return;
            }
            setError('Remote state payload was missing state data.');
            setStatus('error');
            return;
          }
          if (isRecord(payload)) {
            setState(payload as RemoteState);
            setStatus('connected');
            setError('');
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
    setHealth(null);
    setState(null);
  }, [clearReconnect, clearSocketWatchdog, rejectPendingSocketCommands, stopPolling]);

  useEffect(() => {
    if (!activeConnectionKeyRef.current || activeConnectionKeyRef.current === connectionKey) {
      return;
    }
    disconnect();
  }, [connectionKey, disconnect]);

  const connect = useCallback(async () => {
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

  const sendText = useCallback(
    async (text: string, sendOptions: SendTextOptions = {}) => {
      const message = text.trim();
      if (!message) {
        return;
      }
      const payload = {
        play_on_backend: Boolean(sendOptions.playOnBackend),
        capture_phone_audio: sendOptions.capturePhoneAudio !== false,
        visual_after_send: Boolean(sendOptions.visualAfterSend),
      };
      const result = await sendSocketCommand('send_text', 'send_result', { text: message, payload }) ?? await client.sendText(message, sendOptions);
      const errorMessage = remoteActionError(result, 'Main chat message was not accepted.');
      if (errorMessage) {
        throw new Error(errorMessage);
      }
      await refresh();
    },
    [client, refresh, sendSocketCommand],
  );

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

  return {
    baseUrl,
    pairingCode,
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
    connect,
    disconnect,
    refresh,
    sendText,
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
