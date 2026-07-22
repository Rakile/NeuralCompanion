import assert from 'node:assert/strict';

const {
  buildLanDiscoveryCandidates,
  discoverRemoteBaseUrl,
} = await import('../src/utils/lanDiscovery.ts');

const candidates = buildLanDiscoveryCandidates(
  '192.168.2.99',
  'http://192.168.2.43:8777',
);
assert.equal(candidates[0], 'http://192.168.2.43:8777');
assert.equal(candidates.includes('http://192.168.2.99:8777'), false);
assert.equal(new Set(candidates).size, candidates.length);
assert.equal(candidates.length, 253);

assert.deepEqual(
  buildLanDiscoveryCandidates('not-an-ip', 'http://192.168.2.43:8777'),
  ['http://192.168.2.43:8777'],
);

const calls = [];
const fetchImpl = async (url, init) => {
  calls.push({ url: String(url), init });
  const found = String(url) === 'http://192.168.2.43:8777/api/state';
  return {
    ok: found,
    status: found ? 200 : 404,
    json: async () => found ? { ok: true, state: { runtime_status: {} } } : { ok: false },
  };
};

const discovered = await discoverRemoteBaseUrl({
  phoneIp: '192.168.2.99',
  pairingCode: '112365',
  preferredBaseUrl: 'http://192.168.2.10:8777',
  fetchImpl,
  probeTimeoutMs: 50,
  batchSize: 32,
});
assert.equal(discovered, 'http://192.168.2.43:8777');
const successfulCall = calls.find((call) => call.url === `${discovered}/api/state`);
assert.equal(successfulCall?.init?.headers?.['X-NC-Phone-Code'], '112365');

let noCodeCalls = 0;
const withoutCode = await discoverRemoteBaseUrl({
  phoneIp: '192.168.2.99',
  pairingCode: '',
  preferredBaseUrl: 'http://192.168.2.43:8777',
  fetchImpl: async () => {
    noCodeCalls += 1;
    throw new Error('fetch must not run without a pairing code');
  },
});
assert.equal(withoutCode, '');
assert.equal(noCodeCalls, 0);

console.log('LAN discovery smoke passed.');
