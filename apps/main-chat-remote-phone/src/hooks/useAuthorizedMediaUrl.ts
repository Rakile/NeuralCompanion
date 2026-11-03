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
  retainWhileLoadingKey = '',
) {
  const [reloadVersion, setReloadVersion] = useState('');
  // A new version refreshes both authorization and the bounded peer/native caches.
  const resolvedParams = reloadVersion ? { ...params, v: `${params.v ?? ''}-reload-${reloadVersion}` } : params;
  const resolver = useMemo(() => new AuthorizedMediaResolver(client), [
    client.identityKey, client.pairingCode,
    client.auth.kind === 'internet' ? client.auth.deviceToken : '',
    retainWhileLoadingKey,
  ]);
  const paramsIdentity = authorizedMediaParamsKey(resolvedParams);
  const requestKey = `${path}\n${paramsIdentity}`;
  const [state, setState] = useState({ key: requestKey, resolver, url: '', loading: Boolean(path), error: '', expiresAt: 0 });
  const canRetain = (current: typeof state) => Boolean(retainWhileLoadingKey && path
    && current.resolver === resolver && current.url && !current.error
    && (!current.expiresAt || current.expiresAt > Date.now()));

  useEffect(() => {
    let alive = true;
    let refreshTimer: ReturnType<typeof setTimeout> | null = null;
    if (!path) {
      setState({ key: requestKey, resolver, url: '', loading: false, error: '', expiresAt: 0 });
      return () => undefined;
    }
    const resolve = async () => {
      setState((current) => current.key === requestKey && current.resolver === resolver
        ? { ...current, loading: !current.url, error: '' }
        : canRetain(current) ? { ...current, key: requestKey, loading: true, error: '' }
        : { key: requestKey, resolver, url: '', loading: true, error: '', expiresAt: 0 });
      try {
        const resolved = await resolver.resolve(path, resolvedParams);
        if (!alive) return;
        setState({ key: requestKey, resolver, url: resolved.url, loading: false, error: '', expiresAt: resolved.expiresAt });
        if (resolved.expiresAt) {
          const delay = Math.max(1000, resolved.expiresAt - Date.now() - 30_000);
          refreshTimer = setTimeout(() => {
            resolver.clear();
            void resolve();
          }, delay);
        }
      } catch (exc) {
        if (!alive) return;
        setState({
          key: requestKey,
          resolver,
          url: '',
          loading: false,
          error: exc instanceof Error ? exc.message : 'Media authorization failed.',
          expiresAt: 0,
        });
      }
    };
    void resolve();
    return () => {
      alive = false;
      if (refreshTimer) clearTimeout(refreshTimer);
    };
  }, [paramsIdentity, path, resolver]);

  // Keep the private resolver (and its credentials) out of the public hook result.
  const { resolver: stateResolver, ...result } = state;
  const current = state.key === requestKey && stateResolver === resolver
    ? result
    : canRetain(state) ? { ...result, key: requestKey, loading: true }
    : { key: requestKey, url: '', loading: Boolean(path), error: '', expiresAt: 0 };
  return { ...current, reload: () => {
    resolver.clear();
    setReloadVersion(`${Date.now()}-${Math.random().toString(36).slice(2)}`);
  } };
}
