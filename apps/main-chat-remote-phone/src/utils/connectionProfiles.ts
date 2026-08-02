import { normalizeInternetUrl, normalizeLanUrl } from './url.ts';

export type ConnectionMode = 'auto' | 'lan' | 'internet';
export type ConnectionRoute = 'lan' | 'internet_hostname' | 'internet_ip';

export type LanConnectionProfile = {
  baseUrl: string;
  pairingCode: string;
};

export type InternetConnectionProfile = {
  hostnameUrl: string;
  ipUrl: string;
  deviceId: string;
  gatewayId: string;
  deviceToken: string;
};

export type StoredConnectionSettingsV2 = {
  version: 2;
  mode: ConnectionMode;
  lan: LanConnectionProfile;
  internet: InternetConnectionProfile;
};

export type ConnectionTarget = {
  route: ConnectionRoute;
  baseUrl: string;
  gatewayId: string;
  deviceId: string;
  auth:
    | { kind: 'lan'; pairingCode: string }
    | { kind: 'internet'; deviceId: string; deviceToken: string };
};

export type ProbeFailureReason =
  | 'discovery'
  | 'dns_error'
  | 'timeout'
  | 'unreachable'
  | 'auth_error'
  | 'certificate_error'
  | 'gateway_identity_error';

export type CandidateProbeResult = { ok: true } | { ok: false; reason: ProbeFailureReason; error?: string };
export type CandidateSelectionResult = {
  target: ConnectionTarget | null;
  activeRoute: ConnectionRoute | '';
  attemptedRoutes: ConnectionRoute[];
  terminalReason: ProbeFailureReason | '';
};

const EMPTY_SETTINGS: StoredConnectionSettingsV2 = {
  version: 2,
  mode: 'auto',
  lan: { baseUrl: '', pairingCode: '' },
  internet: { hostnameUrl: '', ipUrl: '', deviceId: '', gatewayId: '', deviceToken: '' },
};

function bounded(value: unknown, maximum = 256): string {
  return String(value || '').trim().slice(0, maximum);
}

function normalizePairingCode(value: unknown): string {
  return String(value || '').replace(/\D/g, '').slice(0, 9);
}

export function normalizeConnectionSettings(value: unknown): StoredConnectionSettingsV2 {
  const source = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const versionTwo = Number(source.version) === 2;
  const rawLan = versionTwo && source.lan && typeof source.lan === 'object'
    ? source.lan as Record<string, unknown>
    : source;
  const rawInternet = versionTwo && source.internet && typeof source.internet === 'object'
    ? source.internet as Record<string, unknown>
    : {};
  const requestedMode = String(source.mode || 'auto');
  const mode: ConnectionMode = requestedMode === 'lan' || requestedMode === 'internet' ? requestedMode : 'auto';
  return {
    version: 2,
    mode,
    lan: {
      baseUrl: normalizeLanUrl(String(rawLan.baseUrl || '')),
      pairingCode: normalizePairingCode(rawLan.pairingCode),
    },
    internet: {
      hostnameUrl: normalizeInternetUrl(String(rawInternet.hostnameUrl || '')),
      ipUrl: normalizeInternetUrl(String(rawInternet.ipUrl || '')),
      deviceId: bounded(rawInternet.deviceId, 128),
      gatewayId: bounded(rawInternet.gatewayId, 128),
      deviceToken: bounded(rawInternet.deviceToken, 512),
    },
  };
}

export function emptyConnectionSettings(): StoredConnectionSettingsV2 {
  return normalizeConnectionSettings(EMPTY_SETTINGS);
}

export function connectionCandidates(settingsValue: StoredConnectionSettingsV2): ConnectionTarget[] {
  const settings = normalizeConnectionSettings(settingsValue);
  const candidates: ConnectionTarget[] = [];
  const lanReady = /^\d{4,9}$/.test(settings.lan.pairingCode) && Boolean(settings.lan.baseUrl);
  const internetReady = Boolean(
    settings.internet.deviceId
      && settings.internet.gatewayId
      && settings.internet.deviceToken,
  );
  if ((settings.mode === 'auto' || settings.mode === 'lan') && lanReady) {
    candidates.push({
      route: 'lan',
      baseUrl: settings.lan.baseUrl,
      gatewayId: '',
      deviceId: '',
      auth: { kind: 'lan', pairingCode: settings.lan.pairingCode },
    });
  }
  if ((settings.mode === 'auto' || settings.mode === 'internet') && internetReady) {
    if (settings.internet.hostnameUrl) {
      candidates.push({
        route: 'internet_hostname',
        baseUrl: settings.internet.hostnameUrl,
        gatewayId: settings.internet.gatewayId,
        deviceId: settings.internet.deviceId,
        auth: {
          kind: 'internet',
          deviceId: settings.internet.deviceId,
          deviceToken: settings.internet.deviceToken,
        },
      });
    }
    if (settings.internet.ipUrl && settings.internet.ipUrl !== settings.internet.hostnameUrl) {
      candidates.push({
        route: 'internet_ip',
        baseUrl: settings.internet.ipUrl,
        gatewayId: settings.internet.gatewayId,
        deviceId: settings.internet.deviceId,
        auth: {
          kind: 'internet',
          deviceId: settings.internet.deviceId,
          deviceToken: settings.internet.deviceToken,
        },
      });
    }
  }
  return candidates;
}

export async function connectCandidates(
  candidates: ConnectionTarget[],
  probe: (target: ConnectionTarget) => Promise<CandidateProbeResult>,
): Promise<CandidateSelectionResult> {
  const attemptedRoutes: ConnectionRoute[] = [];
  for (const target of candidates) {
    attemptedRoutes.push(target.route);
    const result = await probe(target);
    if (result.ok) {
      return { target, activeRoute: target.route, attemptedRoutes, terminalReason: '' };
    }
    if (result.reason === 'auth_error' || result.reason === 'certificate_error' || result.reason === 'gateway_identity_error') {
      return { target: null, activeRoute: '', attemptedRoutes, terminalReason: result.reason };
    }
  }
  return { target: null, activeRoute: '', attemptedRoutes, terminalReason: '' };
}
