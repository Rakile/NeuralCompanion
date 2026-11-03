import type { PhoneReplyAuth } from '../api/types';
import type { NativeReplyContinuation } from '../native/iosLiveCapture';

export type ReplyContinuation = Readonly<{
  scopeKey: string; sessionId: string; ticket: string; recoveryEpoch: number;
  checkpoint: NativeReplyContinuation;
  replies: readonly Readonly<{ requestId: string; auth: PhoneReplyAuth }>[];
  deadlineMs: number;
}>;

export function createReplyContinuation(scopeKey: string, sessionId: string, ticket: string,
  checkpoint: NativeReplyContinuation, replies: ReplyContinuation['replies'], nowMs: number,
  previous?: ReplyContinuation | null): ReplyContinuation {
  const sameReply = previous?.scopeKey === scopeKey && previous.sessionId === sessionId && previous.ticket === ticket
    && replies.some(r => previous.replies.some(old => old.requestId === r.requestId));
  return Object.freeze({ scopeKey, sessionId, ticket, recoveryEpoch: checkpoint.recoveryEpoch, checkpoint,
    replies: Object.freeze(replies.map(r => Object.freeze({ requestId: r.requestId, auth: Object.freeze({ ...r.auth }) }))),
    deadlineMs: sameReply ? previous!.deadlineMs : nowMs + 900_000 });
}

export function continuationIsCurrent(record: ReplyContinuation, scopeKey: string, epoch: number, nowMs: number): boolean {
  return record.scopeKey === scopeKey && record.recoveryEpoch === epoch && Number.isFinite(nowMs) && nowMs < record.deadlineMs;
}
