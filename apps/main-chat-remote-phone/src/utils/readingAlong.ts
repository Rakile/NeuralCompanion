import type { AudioChunk, ChatMessage } from '../api/types';
import { visibleMessageText } from './chatText';

type ReadingWord = { start: number; end: number; normalized: string; weight: number };
export type ReadingMatch = {
  messageId: string; text: string; chunkId: string; requestId?: string; sequence: number;
  words: ReadingWord[]; chunkEnd: number;
};
export type ReadingCursor = {
  messageId: string; text: string; chunkId: string; start: number; end: number; chunkEnd: number;
};
export type ReadingLine = { text: string; y: number; height: number };

function wordsIn(text: string): ReadingWord[] {
  const words: ReadingWord[] = [];
  const pattern = /[\p{L}\p{N}]+(?:['’][\p{L}\p{N}]+)*/gu;
  for (const match of text.matchAll(pattern)) {
    const start = match.index!, end = start + match[0].length;
    const suffix = text.slice(end).match(/^[^\p{L}\p{N}\s]*/u)?.[0] || '';
    // Same length/punctuation weighting as desktop ConversationSpeechSync.
    const weight = .19 + Math.min(match[0].length, 14) * .025 + (/[.!?]/.test(suffix) ? .16 : /[;:]/.test(suffix) ? .08 : 0);
    words.push({ start, end, normalized: match[0].replace(/’/g, "'").toLocaleLowerCase(), weight });
  }
  return words;
}

/** Match the complete audio chunk; never guess a different reply on an ownership mismatch. */
export function matchReadingChunk(messages: readonly ChatMessage[], chunk: AudioChunk, previous?: ReadingMatch | null,
  role: 'assistant' | 'user' = 'assistant'): ReadingMatch | null {
  const nativeOwner = !chunk.phone_request_id ? /^local-(.+)-\d+$/.exec(chunk.id)?.[1] : undefined;
  const assistants = messages.filter(m => m.role === role);
  const owned = chunk.phone_request_id ? assistants.filter(m => m.phone_request_id === chunk.phone_request_id) : [];
  // HQ audio has request IDs, but desktop public chat currently only publishes
  // them for Phone Native. Permit a unique complete-text match on untagged rows;
  // never override an explicit owner or an encoded native message ID.
  const candidates = role === 'user' ? owned : nativeOwner ? assistants.filter(m => m.id === nativeOwner)
    : chunk.phone_request_id ? (owned.length ? owned : assistants.filter(m => !m.phone_request_id)) : assistants;
  const matches: ReadingMatch[] = [];
  let matchingMessages = 0;
  const sequence = chunk.sequence_index ?? chunk.index;
  for (const message of candidates) {
    const moods = Object.keys(message.mood_avatar_url_paths || {});
    const text = visibleMessageText(message.content, role === 'assistant', moods);
    const spoken = wordsIn(visibleMessageText(chunk.text || '', role === 'assistant', moods));
    const display = wordsIn(text);
    if (!spoken.length || !display.length) continue;
    const advancing = previous?.messageId === message.id && previous.chunkId !== chunk.id
      && previous.requestId === chunk.phone_request_id && sequence > previous.sequence;
    const starts: number[] = [];
    for (let i = 0; i + spoken.length <= display.length; i++) {
      if (spoken.every((word, n) => word.normalized === display[i + n]!.normalized)) starts.push(i);
    }
    // Even an unresolved offset is a possible owner. Dropping it would let an
    // older untagged HQ reply with the same phrase appear uniquely matched.
    if (starts.length) matchingMessages++;
    const sameChunk = previous?.messageId === message.id && previous.chunkId === chunk.id;
    let first: number | undefined;
    if (sameChunk) first = starts.find(i => display[i]!.start === previous!.words[0]!.start);
    else if (advancing) {
      const following = starts.filter(i => display[i]!.start >= previous!.chunkEnd);
      if (following.length === 1 || sequence === previous!.sequence + 1) first = following[0];
    } else if (starts.length === 1 || (sequence === 0 && starts[0] === 0)) {
      first = starts[0];
    }
    // Reopening mid-reply or skipping chunks loses positional evidence. Leave
    // ambiguous phrases unhighlighted instead of jumping to an earlier repeat.
    if (first === undefined) continue;
    const words = spoken.map((word, n) => ({ ...word, start: display[first + n]!.start, end: display[first + n]!.end }));
    matches.push({ messageId: message.id, text, chunkId: chunk.id, requestId: chunk.phone_request_id,
      sequence, words, chunkEnd: words[words.length - 1]!.end });
  }
  return matchingMessages === 1 && matches.length === 1 ? matches[0]! : null;
}

export function readingWordAt(match: ReadingMatch, progress: number): ReadingCursor {
  const bounded = Number.isFinite(progress) ? Math.max(0, Math.min(.999999, progress)) : 0;
  const target = match.words.reduce((total, word) => total + word.weight, 0) * bounded;
  let elapsed = 0, current = match.words[match.words.length - 1]!;
  for (const word of match.words) { elapsed += word.weight; if (elapsed > target) { current = word; break; } }
  return { messageId: match.messageId, text: match.text, chunkId: match.chunkId,
    start: current.start, end: current.end, chunkEnd: match.chunkEnd };
}

/** Native text layout supplies actual wrapped lines, including font scaling. */
export function readingLineAt(text: string, lines: readonly ReadingLine[], offset: number): ReadingLine | null {
  let searchFrom = 0;
  for (const line of lines) {
    const value = line.text.trim();
    if (!value) continue;
    const start = text.indexOf(value, searchFrom);
    if (start < 0) return null;
    const end = start + value.length;
    if (offset >= start && offset <= end) return line;
    searchFrom = end;
  }
  return null;
}
