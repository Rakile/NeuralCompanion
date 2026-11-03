import {useCallback, useEffect, useRef, useState} from 'react';
import * as Crypto from 'expo-crypto';
import type {RemoteClient} from '../api/client';
import type {ChatCharacterSnapshot} from '../api/types';
import {CharacterOperations} from '../utils/chatCharacterDrafts';
import {CharacterAddSounds} from '../utils/automaticCharacters';
import {playCharacterAddedSound} from '../native/characterAddedSound';

export function useChatCharacters(client: RemoteClient, connectionIdentity: string, enabled: boolean) {
  const owner = useRef({client, connectionIdentity, enabled});
  const [data, setData] = useState<{scope: string; value: ChatCharacterSnapshot} | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const operations = useRef(new CharacterOperations(() => Crypto.randomUUID()));
  const active = useRef(new Map<string, Promise<unknown>>());
  const includeAll = useRef(false);
  const readSequence = useRef(0);
  const addSounds = useRef(new CharacterAddSounds());
  if (owner.current.client !== client || owner.current.connectionIdentity !== connectionIdentity || owner.current.enabled !== enabled) {
    owner.current = {client, connectionIdentity, enabled};
    addSounds.current.reset();
  }
  const currentOwner = owner.current;
  const refresh = useCallback(async (all = includeAll.current) => {
    if (!currentOwner.enabled) return;
    includeAll.current = all;
    const sequence = ++readSequence.current;
    try {
      let next = await currentOwner.client.chatCharacters(all);
      if (next.version !== 1 || !Array.isArray(next.characters)) throw new Error('Update NC desktop to use Chat Characters.');
      // Fetch every saved card for library selection; guard against a repeated server cursor.
      const seenOffsets = new Set<number>();
      while (all && next.next_offset !== null && !seenOffsets.has(next.next_offset)) {
        if (owner.current !== currentOwner) return;
        const offset = next.next_offset;
        seenOffsets.add(offset);
        const page = await currentOwner.client.chatCharacters(all, offset);
        if (page.revision !== next.revision) break;
        if (!page.characters.length) break;
        next = {...page, characters:[...next.characters, ...page.characters]};
      }
      if (owner.current === currentOwner && readSequence.current === sequence) {
        if(addSounds.current.observe(next))playCharacterAddedSound();
        setData({scope:currentOwner.connectionIdentity, value:next}); setError('');
      }
      return next;
    } catch (failure) {
      if (owner.current === currentOwner) {addSounds.current.reset();setError(failure instanceof Error ? failure.message : 'Character library unavailable.');}
    }
  }, [currentOwner]);
  useEffect(() => {
    setError(''); setBusy(false);
    void refresh();
    const timer = enabled ? setInterval(() => {void refresh();}, 15000) : null;
    return () => {if (timer) clearInterval(timer);};
  }, [refresh, enabled]);
  const mutate = useCallback(async <T,>(route: string, body: Record<string, unknown>): Promise<T> => {
    if (!currentOwner.enabled || owner.current !== currentOwner) throw new Error('Reconnect before changing a character.');
    const signature = JSON.stringify([route, body]);
    const key = JSON.stringify([connectionIdentity, signature]);
    const previous = active.current.get(key);
    if (previous) return previous as Promise<T>;
    const operation_id = operations.current.begin(connectionIdentity, signature);
    setBusy(true); setError('');
    const promise = currentOwner.client.characterRequest<T>('POST', '/api/chat-characters' + route, {...body, operation_id})
      .then(async result => {
        operations.current.finish(connectionIdentity, signature);
        if (owner.current !== currentOwner) throw new Error('The connection changed. Refresh to see the saved result.');
        await refresh();
        return result;
      }).catch(failure => {
        if (owner.current === currentOwner) setError(failure instanceof Error ? failure.message : 'Character request failed.');
        throw failure;
      }).finally(() => {active.current.delete(key); if (owner.current === currentOwner) setBusy(false);});
    active.current.set(key, promise);
    return promise;
  }, [currentOwner, connectionIdentity, refresh]);
  // Preserve mounted editor drafts across a transient disconnect, but never across credentials or chats.
  return {snapshot: data && data.scope === connectionIdentity ? data.value : null, error, busy, refresh, mutate,
    enabled, client, connectionIdentity};
}
export type ChatCharactersApi = ReturnType<typeof useChatCharacters>;
