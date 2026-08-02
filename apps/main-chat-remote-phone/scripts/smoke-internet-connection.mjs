import assert from 'node:assert/strict';

import {
  connectCandidates,
  connectionCandidates,
  normalizeConnectionSettings,
} from '../src/utils/connectionProfiles.ts';
import { parseAnyPairingSetupUri } from '../src/utils/pairingSetup.ts';
import { normalizeInternetUrl } from '../src/utils/url.ts';

assert.equal(normalizeInternetUrl('nc.example.test'), 'https://nc.example.test');
assert.equal(normalizeInternetUrl('8.8.8.8:8443'), 'https://8.8.8.8:8443');
assert.equal(normalizeInternetUrl('http://8.8.8.8:8443'), '');
assert.equal(normalizeInternetUrl('https://user:pass@nc.example.test'), '');

const settings = normalizeConnectionSettings({
  version: 2,
  mode: 'auto',
  lan: { baseUrl: 'http://192.168.1.20:8777', pairingCode: '654321' },
  internet: {
    hostnameUrl: 'https://nc.example.test',
    ipUrl: 'https://8.8.8.8',
    deviceId: 'phone-1',
    gatewayId: 'gateway-1',
    deviceToken: 'device-secret',
  },
});
assert.deepEqual(connectionCandidates(settings).map((item) => item.route), [
  'lan',
  'internet_hostname',
  'internet_ip',
]);

const result = await connectCandidates(
  connectionCandidates(settings),
  async (target) => {
    if (target.route === 'lan') return { ok: false, reason: 'timeout' };
    if (target.route === 'internet_hostname') return { ok: false, reason: 'dns_error' };
    return { ok: true };
  },
);
assert.equal(result.activeRoute, 'internet_ip');
assert.deepEqual(result.attemptedRoutes, ['lan', 'internet_hostname', 'internet_ip']);

const stopped = await connectCandidates(
  connectionCandidates(settings),
  async () => ({ ok: false, reason: 'auth_error' }),
);
assert.equal(stopped.activeRoute, '');
assert.equal(stopped.terminalReason, 'auth_error');
assert.deepEqual(stopped.attemptedRoutes, ['lan']);

const migrated = normalizeConnectionSettings({ baseUrl: '192.168.1.5', pairingCode: '12-34-56' });
assert.equal(migrated.version, 2);
assert.equal(migrated.mode, 'auto');
assert.equal(migrated.lan.baseUrl, 'http://192.168.1.5:8777');
assert.equal(migrated.lan.pairingCode, '123456');

const parsed = parseAnyPairingSetupUri(
  'ncchatremote://pair?version=2&mode=internet&hostname_url=https%3A%2F%2Fnc.example.test&ip_url=https%3A%2F%2F8.8.8.8&enrollment_id=abcdefghijklmnop&secret=abcdefghijklmnopqrstuvwxyzABCDE123456789-_&gateway_id=gateway_12345678',
);
assert.equal(parsed?.mode, 'internet');
assert.equal(parsed?.hostnameUrl, 'https://nc.example.test');
assert.equal(parseAnyPairingSetupUri('ncchatremote://pair?version=2&mode=internet&hostname_url=http%3A%2F%2F8.8.8.8'), null);

console.log('internet connection smoke passed');
