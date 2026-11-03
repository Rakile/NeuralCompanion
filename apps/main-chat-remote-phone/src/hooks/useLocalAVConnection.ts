import { useEffect, useMemo, useState } from 'react';
import type { RemoteClient } from '../api/client';
import { LocalAVSession } from '../relay/localAVSession';

/** Keep media readiness distinct from the existing HTTP/WS command connection. */
export function useLocalAVConnection(client: RemoteClient, enabled: boolean) {
  const session = useMemo(() => new LocalAVSession((action, body) => client.localAVSignal(action, body),
    JSON.stringify([client.baseUrl,client.pairingCode])), [client]);
  const [revision, revise] = useState(0);
  const [failureRevision, fail] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let wasConnected = false;
    session.onChange = () => {
      if (wasConnected && session.state !== 'connected') fail(value => value + 1);
      wasConnected = session.state === 'connected';
      revise(value => value + 1);
    };
    client.bindLocalMedia(session);
    session.start();
    return () => {
      session.onChange = () => undefined;
      session.close(); client.bindLocalMedia(undefined);
    };
  }, [client, session, enabled]);
  return { ready: enabled && session.state === 'connected', error: enabled ? session.error : '',
    state: session.state, desktopInstance: session.desktopInstance, failureRevision, revision };
}
