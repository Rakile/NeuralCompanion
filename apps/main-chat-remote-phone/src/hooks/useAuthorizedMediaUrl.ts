import { useEffect, useMemo, useState } from 'react';

import type { RemoteClient } from '../api/client';
import {
  AuthorizedMediaResolver,
  authorizedMediaParamsKey,
} from '../utils/authorizedMedia';

export function useAuthorizedMediaUrl(
  client: RemoteClient,
  path: string,
  params: Record<string, unknown> = {},
) {
  const resolver = useMemo(() => new AuthorizedMediaResolver(client), [client.identityKey]);
  const paramsIdentity = authorizedMediaParamsKey(params);
  const [state, setState] = useState({ url: '', loading: Boolean(path), error: '', expiresAt: 0 });

  useEffect(() => {
    let alive = true;
    let refreshTimer: ReturnType<typeof setTimeout> | null = null;
    if (!path) {
      setState({ url: '', loading: false, error: '', expiresAt: 0 });
      return () => undefined;
    }
    const resolve = async () => {
      setState((current) => ({ ...current, loading: !current.url, error: '' }));
      try {
        const resolved = await resolver.resolve(path, params);
        if (!alive) return;
        setState({ url: resolved.url, loading: false, error: '', expiresAt: resolved.expiresAt });
        if (resolved.expiresAt) {
          const delay = Math.max(1000, resolved.expiresAt - Date.now() - 30_000);
          refreshTimer = setTimeout(() => {
            resolver.clear();
            void resolve();
          }, delay);
        }
      } catch (exc) {
        if (!alive) return;
        setState((current) => ({
          ...current,
          loading: false,
          error: exc instanceof Error ? exc.message : 'Media authorization failed.',
        }));
      }
    };
    void resolve();
    return () => {
      alive = false;
      if (refreshTimer) clearTimeout(refreshTimer);
    };
  }, [paramsIdentity, path, resolver]);

  return state;
}
