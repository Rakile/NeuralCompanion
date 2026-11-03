import { randomUUID } from 'expo-crypto';
import type { RemoteClient } from '../api/client';
import type { StoryRefineOptions } from '../api/types';
import { parseDraftResult } from './slashCommands';

export async function requestCommandDraft(client: RemoteClient, command: string, text: string,
  signal: AbortSignal, isCurrent: () => boolean, options?: StoryRefineOptions) {
  if (!text.trim() || text.length > 8000) throw new Error(`Use /${command} followed by 1–8000 characters.`);
  const id = randomUUID().replace(/-/g, '');
  const check = () => {
    if (signal.aborted || !isCurrent()) throw new Error('Draft cancelled because the conversation changed.');
  };
  const cancel = () => { void client.commandDraft('cancel', { id }).catch(() => undefined); };
  signal.addEventListener('abort', cancel, { once: true });
  try {
    check();
    let result = await client.commandDraft('start', { id, command, text, ...(options ? { options } : {}) });
    const deadline = Date.now() + 180_000;
    while (result.status === 'working') {
      check();
      if (Date.now() >= deadline) throw new Error('Draft timed out. Your original text is preserved.');
      await new Promise<void>(resolve => {
        const done = () => { clearTimeout(timer); signal.removeEventListener('abort', done); resolve(); };
        const timer = setTimeout(done, 750);
        signal.addEventListener('abort', done, { once: true });
      });
      check();
      result = await client.commandDraft('status', { id, command });
    }
    check();
    if (result.status !== 'ready') throw new Error(result.error || 'Draft cancelled. Your original text is preserved.');
    if (command === 'story_refine' || command === 'story_extend') {
      const plan = result.plan;
      if (!plan || typeof plan.title !== 'string' || typeof plan.opening_cue !== 'string'
        || !Array.isArray(plan.beats) || plan.beats.length < 2)
        throw new Error('Story Plan was invalid. Your original text is preserved.');
      return { storyPlan: plan };
    }
    if (!result.text) throw new Error(result.error || 'Draft cancelled. Your original text is preserved.');
    return parseDraftResult(result.text, command);
  } finally {
    signal.removeEventListener('abort', cancel);
    // Also clears the transient desktop copy after the result is received.
    cancel();
  }
}
