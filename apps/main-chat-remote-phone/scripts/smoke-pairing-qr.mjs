import assert from 'node:assert/strict';

const { parsePairingSetupUri } = await import('../src/utils/pairingSetup.ts');

assert.deepEqual(
  parsePairingSetupUri(
    'ncchatremote://pair?url=http%3A%2F%2F192.168.2.43%3A8777&code=533020',
  ),
  { baseUrl: 'http://192.168.2.43:8777', pairingCode: '533020' },
);

assert.deepEqual(
  parsePairingSetupUri(
    '  ncchatremote://pair?url=https%3A%2F%2Fnc.example.test%2Fhealth&code=112365  ',
  ),
  { baseUrl: 'https://nc.example.test', pairingCode: '112365' },
);

assert.equal(parsePairingSetupUri('https://example.test/?code=533020'), null);
assert.equal(parsePairingSetupUri('ncchatremote://other?url=http://192.168.2.43:8777&code=533020'), null);
assert.equal(parsePairingSetupUri('ncchatremote://pair?url=file:///etc/passwd&code=533020'), null);
assert.equal(parsePairingSetupUri('ncchatremote://pair?url=http://user:pass@192.168.2.43:8777&code=533020'), null);
assert.equal(parsePairingSetupUri('ncchatremote://pair?url=http://192.168.2.43:8777&code=12'), null);
assert.equal(parsePairingSetupUri('not a QR pairing value'), null);

console.log('Pairing QR parser smoke passed.');
