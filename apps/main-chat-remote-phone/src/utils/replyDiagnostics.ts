import type { RemoteState } from '../api/types';

export type AssistantMessageMarker = {
  id: string;
  createdAtMs: number;
};

export type PendingReplyTrace = {
  debugTraceId: string;
  connectionKey: string;
  acceptedAtMs: number;
  baselineAssistantIds: string[];
};

function timestampMs(value: number | string | null | undefined): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value > 0 && value < 1_000_000_000_000 ? value * 1000 : value;
  }
  const parsed = Date.parse(String(value || ''));
  return Number.isFinite(parsed) ? parsed : 0;
}

export function assistantMessageMarkers(state: RemoteState | null): AssistantMessageMarker[] {
  return (state?.chat?.messages || []).flatMap((message) => {
    if (String(message.role || '').toLowerCase() !== 'assistant') return [];
    const createdAtMs = timestampMs(message.created_at);
    const id = String(message.id || '').trim()
      || `index:${Number(message.index || 0)}:${createdAtMs}`;
    return [{ id, createdAtMs }];
  });
}

export function matchedReplyTraceIds(
  pending: readonly PendingReplyTrace[],
  state: RemoteState | null,
  connectionKey: string,
): string[] {
  const markers = assistantMessageMarkers(state);
  const consumedMessageIds = new Set<string>();
  const matched: string[] = [];
  const ordered = [...pending]
    .filter((item) => item.connectionKey === connectionKey)
    .sort((left, right) => left.acceptedAtMs - right.acceptedAtMs);

  for (const trace of ordered) {
    const baseline = new Set(trace.baselineAssistantIds);
    const reply = markers.find((marker) => (
      !baseline.has(marker.id)
      && !consumedMessageIds.has(marker.id)
      && (marker.createdAtMs <= 0 || marker.createdAtMs >= trace.acceptedAtMs - 2000)
    ));
    if (!reply) continue;
    consumedMessageIds.add(reply.id);
    matched.push(trace.debugTraceId);
  }
  return matched;
}

export function advancePendingReplyTraces<T extends PendingReplyTrace>(
  pending: readonly T[],
  state: RemoteState | null,
  connectionKey: string,
  matchedTraceIds: readonly string[],
): T[] {
  const matched = new Set(matchedTraceIds);
  const observedAssistantIds = assistantMessageMarkers(state).map((marker) => marker.id);
  return pending.flatMap((trace) => {
    if (matched.has(trace.debugTraceId)) return [];
    if (trace.connectionKey !== connectionKey) return [trace];
    return [{
      ...trace,
      baselineAssistantIds: Array.from(new Set([
        ...trace.baselineAssistantIds,
        ...observedAssistantIds,
      ])),
    }];
  });
}
