const MAX_TRACKED_SESSIONS = 256;
const MAX_TRACKED_REQUESTS = 256;
const MAX_PENDING_UPLOADS = 2;

type SessionRecord = {
  independentCapture?:boolean;
  suspended?: boolean;
  cancelled: boolean;
  inputStopped: boolean;
  sealedRequests: Set<string>;
};

type RequestRecord = {
  sessionId: string;
  cancelled: boolean;
  closed: boolean;
};

type PendingUpload = {
  sessionId: string;
  uploadId: string;
};

function normalizedId(value: string): string {
  return String(value || '').trim();
}

function uploadKey(sessionId: string, uploadId: string): string {
  return `${sessionId.length}:${sessionId}${uploadId}`;
}

/**
 * Correlates background Live uploads with their eventual backend audio chunks.
 * Create one fence per true backend connection identity.
 */
export class BackgroundReplyFence {
  private activeSessionId = '';
  private backgroundUsed = false;
  private latchedClosed = false;
  private readonly sessions = new Map<string, SessionRecord>();
  private readonly requests = new Map<string, RequestRecord>();
  private readonly pendingUploads = new Map<string, PendingUpload>();

  begin(sessionId: string,independentCapture=false): void {
    this.backgroundUsed = true;
    const normalizedSessionId = normalizedId(sessionId);
    if (!normalizedSessionId || !this.ensureSession(normalizedSessionId)) {
      this.activeSessionId = '';
      this.latchedClosed = true;
      return;
    }
    this.activeSessionId = normalizedSessionId;
    this.sessions.get(normalizedSessionId)!.independentCapture=independentCapture;
  }

  beginUpload(sessionId: string, uploadId: string): void {
    this.backgroundUsed = true;
    const normalizedSessionId = normalizedId(sessionId);
    const normalizedUploadId = normalizedId(uploadId);
    if (!normalizedSessionId || !normalizedUploadId || !this.ensureSession(normalizedSessionId)) {
      this.latchedClosed = true;
      return;
    }
    const key = uploadKey(normalizedSessionId, normalizedUploadId);
    if (this.pendingUploads.has(key)) return;
    if (this.pendingUploads.size >= MAX_PENDING_UPLOADS) {
      this.latchedClosed = true;
      return;
    }
    this.pendingUploads.set(key, { sessionId: normalizedSessionId, uploadId: normalizedUploadId });
  }

  settleUpload(sessionId: string, uploadId: string, requestId: string | null): void {
    const normalizedSessionId = normalizedId(sessionId);
    const normalizedUploadId = normalizedId(uploadId);
    const key = uploadKey(normalizedSessionId, normalizedUploadId);
    const pending = this.pendingUploads.get(key);
    if (pending) this.pendingUploads.delete(key);

    const normalizedRequestId = normalizedId(requestId || '');
    if (!normalizedRequestId) {
      this.latchedClosed = true;
      return;
    }

    const session = this.sessions.get(normalizedSessionId);
    const cancelled = !pending
      || !session
      || session.cancelled
      || (this.activeSessionId !== normalizedSessionId && !(session.independentCapture&&session.inputStopped));
    this.recordRequest(normalizedRequestId, normalizedSessionId, cancelled);
    if (!cancelled && session?.inputStopped) session.sealedRequests.add(normalizedRequestId);
  }

  abandonUpload(sessionId: string, uploadId: string): void {
    this.pendingUploads.delete(uploadKey(sessionId, uploadId));
  }

  stopListening(sessionId: string): void {
    const session = this.sessions.get(sessionId);
    if (!session || session.cancelled || this.activeSessionId !== sessionId) return;
    for (const id of this.tailPermit(sessionId).requestIds) session.sealedRequests.add(id);
    session.inputStopped = true;
    if(session.independentCapture)this.activeSessionId='';
  }

  tailPermit(sessionId: string): { requestIds: string[]; pendingUploadIds: string[] } {
    return {
      requestIds: [...this.requests].filter(([, r]) => r.sessionId === sessionId && !r.cancelled && !r.closed).map(([id]) => id),
      pendingUploadIds: [...this.pendingUploads.values()].filter(r => r.sessionId === sessionId).map(r => r.uploadId),
    };
  }

  retainedRequestIds(sessionId?: string): string[] {
    if (sessionId && this.sessions.get(sessionId)?.inputStopped) return [...this.sessions.get(sessionId)!.sealedRequests];
    return [...this.requests].filter(([, r]) => !r.cancelled && (!sessionId || r.sessionId === sessionId)).map(([id]) => id);
  }

  closeReply(requestId: string): void {
    const request = this.requests.get(requestId);
    if (request) request.closed = true;
  }
  suspend(sessionId: string): void {
    const session = this.sessions.get(sessionId);
    if (!session || session.cancelled || session.inputStopped || this.activeSessionId !== sessionId) return;
    session.suspended = true;
    for (const [key, upload] of this.pendingUploads) if (upload.sessionId === sessionId) this.pendingUploads.delete(key);
  }
  resume(sessionId: string, requestIds: string[]): boolean {
    const session = this.sessions.get(sessionId);
    if (!session?.suspended || session.cancelled || session.inputStopped || this.activeSessionId !== sessionId
      || requestIds.length > 3 || new Set(requestIds).size !== requestIds.length
      || requestIds.some(id => { const r = this.requests.get(id); return !r || r.sessionId !== sessionId || r.closed || r.cancelled; })) return false;
    for (const [id, request] of this.requests) if (request.sessionId === sessionId && !requestIds.includes(id)) request.closed = true;
    session.suspended = false;
    return true;
  }

  finishListening(sessionId: string): void {
    if (this.activeSessionId === sessionId) this.activeSessionId = '';
  }

  cancel(sessionId: string): void {
    this.backgroundUsed = true;
    const normalizedSessionId = normalizedId(sessionId);
    if (!normalizedSessionId || !this.ensureSession(normalizedSessionId)) {
      this.latchedClosed = true;
      return;
    }
    const session = this.sessions.get(normalizedSessionId);
    if (session) session.cancelled = true;
    if (this.activeSessionId === normalizedSessionId) this.activeSessionId = '';
    for (const request of this.requests.values()) {
      if (request.sessionId === normalizedSessionId) request.cancelled = true;
    }
  }

  allowsAutomatic(requestId?: string): boolean {
    if (this.latchedClosed) return false;
    for (const upload of this.pendingUploads.values()) {
      if (this.sessions.get(upload.sessionId)?.cancelled) return false;
    }
    if (!this.backgroundUsed) return true;
    const normalizedRequestId = normalizedId(requestId || '');
    if (!normalizedRequestId) return false;
    const request = this.requests.get(normalizedRequestId);
    const retained=request?this.sessions.get(request.sessionId):undefined;
    if(retained?.independentCapture&&retained.inputStopped)return !retained.cancelled&&!retained.suspended&&!request!.cancelled&&!request!.closed;
    if (!this.activeSessionId) return request?.cancelled !== true;
    if (!request || request.cancelled || request.closed || request.sessionId !== this.activeSessionId) return false;
    return this.sessions.get(request.sessionId)?.cancelled === false && !this.sessions.get(request.sessionId)?.suspended;
  }

  automaticBlockReason(): 'waiting-for-ack' | 'latched-closed' | null {
    if (this.latchedClosed) return 'latched-closed';
    for (const upload of this.pendingUploads.values()) {
      if (this.sessions.get(upload.sessionId)?.cancelled) return 'waiting-for-ack';
    }
    return null;
  }

  private ensureSession(sessionId: string): boolean {
    if (this.sessions.has(sessionId)) return true;
    if (this.sessions.size >= MAX_TRACKED_SESSIONS) return false;
    this.sessions.set(sessionId, { cancelled: false, inputStopped: false, sealedRequests: new Set() });
    return true;
  }

  private recordRequest(requestId: string, sessionId: string, cancelled: boolean): void {
    const existing = this.requests.get(requestId);
    if (existing) {
      // A cancellation tombstone is monotonic and a correlated ID is never rebound.
      if (cancelled || existing.sessionId !== sessionId) existing.cancelled = true;
      return;
    }
    if (this.requests.size >= MAX_TRACKED_REQUESTS) {
      this.latchedClosed = true;
      return;
    }
    this.requests.set(requestId, { sessionId, cancelled, closed: false });
  }
}
