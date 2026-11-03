import { Buffer } from 'buffer';
import * as Protocol from '@nc-relay/protocol';
import type { Account, MfaPendingResponse } from '@nc-relay/protocol';

// The upstream protocol uses Buffer for exact UTF-8 byte limits.
(globalThis as unknown as { Buffer: typeof Buffer }).Buffer ??= Buffer;
export const RELAY_API = 'https://nc-relay.online';
export const RELAY_SIGNAL = 'wss://signal.nc-relay.online/v1/signaling';
export { Protocol };
export type TokenStore = { get(): Promise<string | null>; set(value: string): Promise<void>; clear(): Promise<void> };
export class RelayError extends Error {
  constructor(public code: string, public status = 0, public retryAfter = 0) { super(code); }
}
const schemas = {
  '/v1/auth/register': Protocol.RegisterRequestSchema, '/v1/auth/login': Protocol.LoginRequestSchema,
  '/v1/auth/refresh': Protocol.RefreshRequestSchema, '/v1/auth/logout': Protocol.LogoutRequestSchema,
  '/v1/auth/verify-email': Protocol.VerifyEmailRequestSchema, '/v1/auth/forgot-password': Protocol.ForgotPasswordRequestSchema,
  '/v1/auth/reset-password': Protocol.ResetPasswordRequestSchema,
  '/v1/auth/mfa/enroll': Protocol.MfaEnrollRequestSchema,
  '/v1/auth/mfa/confirm': Protocol.MfaConfirmRequestSchema,
  '/v1/auth/mfa/verify': Protocol.MfaVerifyRequestSchema,
};
const reads = new Set(['/v1/account', '/v1/desktops/current', '/v1/ice-servers', '/v1/auth/resend-verification']);
export async function relayHttp(path: string, body?: unknown, token?: string): Promise<Record<string, unknown>> {
  const schema = schemas[path as keyof typeof schemas];
  if (!schema && !reads.has(path)) throw new RelayError('FORBIDDEN');
  if (!schema && body !== undefined && (path !== '/v1/auth/resend-verification' || !body || typeof body !== 'object' || Object.keys(body).length)) throw new RelayError('VALIDATION_FAILED');
  const payload = schema ? schema.parse(body) : body;
  const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(RELAY_API + path, { method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: payload === undefined ? undefined : JSON.stringify(payload), signal: controller.signal, redirect: 'error' });
    if (response.status === 204) return {};
    const raw = await response.text(); if (Buffer.byteLength(raw) > 131072) throw new RelayError('PAYLOAD_TOO_LARGE');
    let data: unknown;
    try { data = JSON.parse(raw); }
    catch { if (response.ok) throw new RelayError('INVALID_RESPONSE'); }
    if (!response.ok) {
      const error = Protocol.ErrorResponseSchema.safeParse(data);
      const retry = Number(response.headers.get('Retry-After') || 0);
      throw new RelayError(error.success ? error.data.error.code : 'INVALID_RESPONSE', response.status, Number.isFinite(retry) ? Math.min(3600, Math.max(0, retry)) : 60);
    }
    if (path === '/v1/auth/login') return Protocol.LoginResponseSchema.parse(data);
    if (path === '/v1/auth/refresh' || path === '/v1/auth/mfa/verify') return Protocol.AuthResponseSchema.parse(data);
    if (path === '/v1/auth/mfa/enroll') return Protocol.MfaEnrollmentResponseSchema.parse(data);
    if (path === '/v1/auth/mfa/confirm') return Protocol.MfaConfirmResponseSchema.parse(data);
    if (path === '/v1/ice-servers') return Protocol.IceServersResponseSchema.parse(data);
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new RelayError('INVALID_RESPONSE');
    return data as Record<string, unknown>;
  } catch (error) {
    if (error instanceof RelayError) throw error;
    throw new RelayError('NETWORK_OR_VALIDATION_ERROR');
  } finally { clearTimeout(timer); }
}

export class RelayAuth {
  // Changes only when credentials are cleared/replaced, not on token rotation.
  credentialGeneration = 0;
  token = ''; expiresAt = 0; account: Account | null = null; private tail: Promise<unknown> = Promise.resolve(); private retryAt = 0;
  private requestRetryAt = new Map<string, number>();
  pending: (MfaPendingResponse & { expiresAt: number }) | null = null;
  enrollment: { secret: string; otpauthUri: string } | null = null;
  recoveryCodes: string[] = [];
  private mfaGeneration = 0;
  onChange: () => void = () => undefined;
  constructor(readonly store: TokenStore, private http = relayHttp) {}
  private serial<T>(operation: () => Promise<T>): Promise<T> {
    const next = this.tail.then(operation, operation); this.tail = next.catch(() => undefined); return next;
  }
  cancelMfa(): void { ++this.mfaGeneration; this.pending = null; this.enrollment = null; this.onChange(); }
  acknowledgeRecoveryCodes(): void { this.recoveryCodes = []; this.onChange(); }
  expireMfa(): void { if (this.pending && this.pending.expiresAt <= Date.now()) this.cancelMfa(); }
  private requirePending(status: MfaPendingResponse['status']) {
    if (this.pending && this.pending.expiresAt <= Date.now()) { this.cancelMfa(); throw new RelayError('MFA_EXPIRED', 401); }
    if (!this.pending || this.pending.status !== status) throw new RelayError('LOGIN_REQUIRED', 401);
    return this.pending;
  }
  private async clear() { ++this.credentialGeneration; this.cancelMfa(); this.recoveryCodes = []; this.token = ''; this.expiresAt = 0; this.account = null; await this.store.clear(); this.onChange(); }
  private async save(value: Record<string, unknown>, generation?: number) {
    const data = Protocol.AuthResponseSchema.parse(value);
    if (generation !== undefined && generation !== this.mfaGeneration) throw new RelayError('LOGIN_REQUIRED', 401);
    await this.store.set(data.refreshToken);
    if (generation !== undefined && generation !== this.mfaGeneration) {
      await this.store.clear(); throw new RelayError('LOGIN_REQUIRED', 401);
    }
    this.token = data.accessToken;
    this.expiresAt = Date.now() + data.expiresIn * 1000; this.account = data.account; this.onChange();
  }
  access(): Promise<string> {
    return this.serial(async () => {
      if (this.pending) { this.expireMfa(); throw new RelayError('MFA_REQUIRED', 401); }
      if (this.token && this.expiresAt - Date.now() > 180000) return this.token;
      if (Date.now() < this.retryAt) {
        if (this.token && this.expiresAt > Date.now()) return this.token;
        throw new RelayError('RATE_LIMITED', 429);
      }
      let token: string | null;
      try {
        token = await this.store.get();
        // Consume before submitting: a lost refresh response must not be replayed.
        if (token) await this.store.clear();
      } catch (error) {
        // No refresh request has been sent. Temporary local storage failure
        // cannot revoke valid access, nor may it extend its original deadline.
        if (this.token && this.expiresAt > Date.now()) return this.token;
        throw error;
      }
      if (!token) {
        if (this.token && this.expiresAt > Date.now()) return this.token;
        await this.clear(); throw new RelayError('LOGIN_REQUIRED', 401);
      }
      // Consume the single-use refresh token, but retain valid access authority
      // while the refresh is in flight. A lost response must never be replayed.
      try { await this.save(await this.http('/v1/auth/refresh', { refreshToken: token })); }
      catch (error) {
        if (error instanceof RelayError) this.retryAt = Date.now() + error.retryAfter * 1000;
        const temporary = error instanceof RelayError
          && (error.code === 'NETWORK_OR_VALIDATION_ERROR' || error.status === 429 || error.status >= 500);
        if (temporary && this.token && this.expiresAt > Date.now()) return this.token;
        await this.clear(); throw error;
      }
      return this.token;
    });
  }
  login(identifier: string, password: string): Promise<void> {
    return this.serial(async () => {
      if (Date.now() < this.retryAt) throw new RelayError('RATE_LIMITED', 429);
      const clearing = this.clear();
      const generation = this.mfaGeneration;
      await clearing;
      try {
        if (generation !== this.mfaGeneration) throw new RelayError('LOGIN_REQUIRED', 401);
        const data = Protocol.LoginResponseSchema.parse(await this.http('/v1/auth/login', { identifier, password, role: 'mobile', deviceLabel: 'NC Remote' }));
        if (generation !== this.mfaGeneration) throw new RelayError('LOGIN_REQUIRED', 401);
        if ('status' in data) { this.pending = { ...data, expiresAt: Date.now() + data.expiresIn * 1000 }; this.onChange(); }
        else await this.save(data, generation);
      }
      catch (error) { await this.clear(); if (error instanceof RelayError) this.retryAt = Date.now() + error.retryAfter * 1000; throw error; }
    });
  }
  beginEnrollment(): Promise<void> {
    return this.serial(async () => {
      const pending = this.requirePending('mfa_enrollment_required');
      if (pending.status !== 'mfa_enrollment_required') return;
      const generation = this.mfaGeneration;
      this.enrollment = null;
      try {
        const data = Protocol.MfaEnrollmentResponseSchema.parse(await this.http('/v1/auth/mfa/enroll', { enrollmentToken: pending.enrollmentToken }));
        if (generation !== this.mfaGeneration) throw new RelayError('LOGIN_REQUIRED', 401);
        const uri = new URL(data.otpauthUri);
        if (uri.protocol !== 'otpauth:' || uri.hostname !== 'totp' || uri.searchParams.get('secret') !== data.secret) throw new RelayError('INVALID_RESPONSE');
        this.enrollment = data; this.onChange();
      } catch (error) { this.cancelMfa(); throw error; }
    });
  }
  confirmEnrollment(code: string): Promise<void> {
    return this.serial(async () => {
      const pending = this.requirePending('mfa_enrollment_required');
      if (pending.status !== 'mfa_enrollment_required' || !this.enrollment) throw new RelayError('LOGIN_REQUIRED', 401);
      const body = Protocol.MfaConfirmRequestSchema.parse({ enrollmentToken: pending.enrollmentToken, code });
      const generation = this.mfaGeneration;
      try {
        const data = Protocol.MfaConfirmResponseSchema.parse(await this.http('/v1/auth/mfa/confirm', body));
        if (generation !== this.mfaGeneration) throw new RelayError('LOGIN_REQUIRED', 401);
        this.cancelMfa();
        // Show once even if secure storage fails after the server consumed enrollment.
        this.recoveryCodes = data.recoveryCodes; this.onChange();
        await this.save(data, generation + 1);
      } catch (error) { this.cancelMfa(); throw error; }
    });
  }
  verifyMfa(proof: string, recovery = false): Promise<void> {
    return this.serial(async () => {
      const pending = this.requirePending('mfa_required');
      if (pending.status !== 'mfa_required') return;
      const body = Protocol.MfaVerifyRequestSchema.parse({ challengeToken: pending.challengeToken, ...(recovery ? { recoveryCode: proof.trim() } : { code: proof }) });
      const generation = this.mfaGeneration;
      try {
        const data = Protocol.AuthResponseSchema.parse(await this.http('/v1/auth/mfa/verify', body));
        if (generation !== this.mfaGeneration) throw new RelayError('LOGIN_REQUIRED', 401);
        this.cancelMfa(); await this.save(data, generation + 1);
      } catch (error) { this.cancelMfa(); throw error; }
    });
  }
  logout(): Promise<void> {
    return this.serial(async () => { const token = await this.store.get(); await this.clear(); if (token) await this.http('/v1/auth/logout', { refreshToken: token, allSessions: false }); });
  }
  async request(path: string, body?: unknown): Promise<Record<string, unknown>> {
    const remaining = (this.requestRetryAt.get(path) || 0) - Date.now();
    if (remaining > 0) throw new RelayError('RATE_LIMITED', 429, Math.ceil(remaining / 1000));
    const perform = async (accessToken: string) => {
      try { return await this.http(path, body, accessToken); }
      catch (error) {
        if (error instanceof RelayError && error.status === 429) this.requestRetryAt.set(path, Date.now() + Math.max(60, error.retryAfter) * 1000);
        throw error;
      }
    };
    const token = await this.access();
    try { return await perform(token); }
    catch (error) {
      if (error instanceof RelayError && error.code === 'TOKEN_REUSED') await this.serial(() => this.clear());
      if (error instanceof RelayError && error.status === 401 && ['TOKEN_EXPIRED', 'INVALID_TOKEN'].includes(error.code)) {
        await this.serial(async () => { if (this.token === token) this.expiresAt = 0; });
        const renewed = await this.access();
        try { return await perform(renewed); }
        catch (retryError) { if (retryError instanceof RelayError && retryError.code === 'TOKEN_REUSED') await this.serial(() => this.clear()); throw retryError; }
      }
      throw error;
    }
  }
}
