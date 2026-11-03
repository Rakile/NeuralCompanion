import { useRef, useState } from 'react';
import type { CommandResult } from '../utils/slashCommands';

export type ComposerDraft = { text: string; command: CommandResult | null };
const emptyDraft = (): ComposerDraft => ({ text: '', command: null });

/** Navigation does not own the draft. A new desktop/session does. */
export function useComposerDraft(identity: string, generation?: number) {
  const owner = useRef({ identity, generation });
  if (owner.current.identity !== identity
    || (generation !== undefined && owner.current.generation !== undefined && owner.current.generation !== generation)) {
    owner.current = { identity, generation };
  } else if (generation !== undefined) owner.current.generation = generation;
  const currentOwner = owner.current;
  const [stored, setStored] = useState({ owner: currentOwner, value: emptyDraft() });
  const value = stored.owner === currentOwner ? stored.value : emptyDraft();
  const setValue = (update: (draft: ComposerDraft) => ComposerDraft) => {
    if (owner.current !== currentOwner) return;
    setStored(previous => owner.current !== currentOwner ? previous
      : { owner: currentOwner, value: update(previous.owner === currentOwner ? previous.value : emptyDraft()) });
  };
  const clear = () => {
    if (owner.current !== currentOwner) return;
    // Retire in-flight callbacks, including sends accepted after a reset.
    owner.current = { ...currentOwner };
    setStored({ owner: owner.current, value: emptyDraft() });
  };
  return { value, setValue, clear };
}
