import type { ChatMessage, StreamingReplyPreview } from '../api/types';

export function withStreamingReplyPreview(messages: ChatMessage[], preview?: StreamingReplyPreview): ChatMessage[] {
  if (preview?.generation_complete !== true || !preview.id || !preview.stream_key || !preview.content.trim()
      || messages.some(message => message.stream_key === preview.stream_key)) return messages;
  return [...messages, {
    id: preview.id,
    index: (messages[messages.length - 1]?.index ?? -1) + 1,
    role: 'assistant',
    content: preview.content,
    stream_key: preview.stream_key,
    provisional: true,
    phone_request_id: preview.phone_request_id,
    phone_audio_mode: preview.phone_audio_mode,
    display_name: preview.display_name,
    avatar_initials: preview.avatar_initials,
  }];
}
