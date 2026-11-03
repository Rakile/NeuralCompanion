import type { ChatMessage } from '../api/types';

export type ChatParagraph = { start: number; end: number; body: string; separator: string };
export type ChatFeedEntry = ChatMessage & {
  feedKey?: string;
  feedParagraph?: ChatParagraph;
  feedPartIndex?: number;
  feedPartCount?: number;
  sourceMessage?: ChatMessage;
};

/** Keep original UTF-16 offsets so speech/read-along can target unchanged source text. */
export function splitChatParagraphs(text: string): ChatParagraph[] {
  const parts: ChatParagraph[] = [];
  const breaks = /(?:\r?\n[\t ]*){2,}/g;
  let start = 0;
  for (const match of text.matchAll(breaks)) {
    const end = match.index + match[0].length;
    parts.push({ start, end, body: text.slice(start, match.index), separator: match[0] });
    start = end;
  }
  parts.push({ start, end: text.length, body: text.slice(start), separator: '' });
  return parts;
}

/** Separator positions stay with the preceding paragraph; the next word starts the next. */
export function paragraphForOffset(parts: readonly ChatParagraph[], offset: number): number {
  for (let index = 0; index < parts.length - 1; index++) {
    if (offset < parts[index]!.end) return index;
  }
  return Math.max(0, parts.length - 1);
}

/** Expand only expensive multi-paragraph assistant text; ordinary rows retain identity. */
export function buildChatFeedEntries(messages: readonly ChatMessage[],
  textForMessage: (message: ChatMessage) => string = message => message.content): ChatFeedEntry[] {
  return messages.flatMap(message => {
    if (message.role !== 'assistant') return [message];
    const text = textForMessage(message);
    if (text.length < 480) return [message];
    const parts = splitChatParagraphs(text);
    if (parts.length < 2) return [message];
    const rowIdentity = message.stream_key || message.id;
    return parts.map((part, index) => ({ ...message, feedKey: index === 0
      ? `${message.index}:${rowIdentity}` : `${message.index}:${rowIdentity}:p:${part.start}`,
      feedParagraph: part, feedPartIndex: index, feedPartCount: parts.length, sourceMessage: message }));
  });
}
