import { useRef } from 'react';
import type { RemoteClient } from '../api/client';

/** Keep one authorized thumbnail while H264 owns the animated presentation.
 * LAN/older peers and inactive tracks retain the original preview behavior.
 * The media resolver still owns credentials/expiry; this retains only a path.
 */
export function useAVPreview(client: RemoteClient, path: string, version: string, owner: string) {
  const held = useRef({ client, owner, path, version });
  if (!client.avPresentationActive || held.current.client !== client || held.current.owner !== owner || !path || !held.current.path) {
    held.current = { client, owner, path, version };
  }
  return { path: held.current.path, version: held.current.version };
}
