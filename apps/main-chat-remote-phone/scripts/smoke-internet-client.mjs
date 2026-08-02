import assert from 'node:assert/strict';

import { RemoteClient } from '../src/api/client.ts';
import { AuthorizedMediaResolver } from '../src/utils/authorizedMedia.ts';

const calls = [];
const originalFetch = globalThis.fetch;
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url: String(url), init });
  const path = new URL(String(url)).pathname;
  const payload = path === '/api/state'
    ? { ok: true, state: {} }
    : path === '/internet/ws-ticket'
      ? { ok: true, ticket: 'short-ticket' }
      : path === '/internet/media-ticket'
        ? { ok: true, url: '/media?signed=short-media', expires_at: 123456 }
        : { ok: true, service: 'nc_main_chat_internet', gateway_id: 'gateway-1' };
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
};

try {
  const client = RemoteClient.forInternet(
    'https://nc.example.test',
    'phone-1',
    'device-secret',
  );
  await client.state();
  assert.equal(calls[0].init.headers.Authorization, 'Bearer device-secret');
  assert.equal(calls[0].url.includes('device-secret'), false);
  const wsUrl = await client.websocketUrl();
  assert.equal(wsUrl, 'wss://nc.example.test/ws?ticket=short-ticket');
  assert.equal(wsUrl.includes('device-secret'), false);
  const media = await client.authorizedMediaUrl('/api/audio/file/a1');
  assert.equal(media.url, 'https://nc.example.test/media?signed=short-media');
  assert.equal(media.url.includes('device-secret'), false);
  await client.health('gateway-1');
  assert.equal(calls.every((call) => !call.url.includes('device-secret')), true);
  assert.equal(calls.some((call) => call.init.headers?.['X-NC-Phone-Code']), false);

  const lan = RemoteClient.forLan('http://192.168.1.20:8777', '654321');
  assert.equal(await lan.websocketUrl(), 'ws://192.168.1.20:8777/ws?code=654321');
  assert.equal((await lan.authorizedMediaUrl('/api/audio/file/a1')).url.includes('code=654321'), true);

  let now = 1000;
  let sequence = 0;
  const resolver = new AuthorizedMediaResolver({
    identityKey: 'internet|test|phone-1',
    authorizedMediaUrl: async () => ({
      url: `https://nc.example.test/media?signed=${++sequence}`,
      expiresAt: now + 120_000,
    }),
  }, () => now);
  const first = await resolver.resolve('/api/visual/image');
  assert.equal(first.url.includes('device-secret'), false);
  now += 95_000;
  const refreshed = await resolver.resolve('/api/visual/image');
  assert.notEqual(refreshed.url, first.url);
} finally {
  globalThis.fetch = originalFetch;
}

console.log('internet client smoke passed');
