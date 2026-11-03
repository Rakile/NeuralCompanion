import { useEffect, useMemo, useRef, useState } from 'react';
import type { ChatMessage } from '../api/types';
import type { PlaybackState } from './useAudioQueue';
import { matchReadingChunk, readingWordAt } from '../utils/readingAlong';
import type { ReadingCursor, ReadingMatch } from '../utils/readingAlong';
import { visibleMessageText } from '../utils/chatText';

/** Read-only playback projection; observing user speech never owns its player. */
export type ReadingPlayback = Pick<PlaybackState, 'currentChunk' | 'lastCompletedChunk' | 'positionSeconds'
  | 'sourceClockRequired' | 'isPlaying' | 'paused' | 'activePlayer' | 'getPlaybackClock' | 'activeReplyId'>
  & { readingRole?: 'assistant' | 'user' };
type Options = { messages: ChatMessage[]; playback: ReadingPlayback; enabled: boolean; visible: boolean; scope: string };
type Snapshot = { scope: string; cursor: ReadingCursor | null; completion: PlaybackState['lastCompletedChunk']; finished: boolean };

export function useReadingAlong(options: Options) {
  const { messages, playback, enabled, visible, scope } = options;
  const latest = useRef(options); latest.current = options;
  const previous = useRef<{ scope: string; match: ReadingMatch } | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot>({ scope, cursor: null, completion: playback.lastCompletedChunk, finished: false });
  const chunk = playback.currentChunk;
  const match = useMemo(() => chunk ? matchReadingChunk(messages, chunk,
    previous.current?.scope === scope ? previous.current.match : null, playback.readingRole) : null,
  [messages, scope, chunk?.id, chunk?.text, chunk?.phone_request_id, chunk?.sequence_index, playback.readingRole]);
  useEffect(() => { if (match) previous.current = { scope, match }; }, [scope, match]);

  useEffect(() => {
    if (!enabled) { setSnapshot({ scope, cursor: null, completion: playback.lastCompletedChunk, finished: false }); return; }
    if (!visible) return;
    const update = () => {
      const current = latest.current;
      if (current.scope !== scope || !current.enabled || !current.visible) return;
      const p = current.playback;
      let cursor: ReadingCursor | null = null;
      if (match && p.currentChunk?.id === match.chunkId) {
        let seconds = p.positionSeconds, duration = Number(p.currentChunk.duration_seconds || 0);
        if (p.currentChunk.progressive_audio && !(duration > 0)) duration = Math.max(1,(p.currentChunk.text?.length || 0)/14);
        try {
          if (!(duration > 0) && !p.sourceClockRequired) duration = Number(p.activePlayer?.duration || 0);
          const clock = p.activePlayer ? p.getPlaybackClock(p.activePlayer, match.chunkId) : null;
          if (p.sourceClockRequired && !clock) seconds=Number.NaN;
          if (clock) {
            seconds = clock.seconds;
            // Only interpolate a fresh, advancing native sample. Buffering and
            // a stale clock must never paint unread words as spoken.
            const age = performance.now() - clock.sampledAtMs;
            if (p.isPlaying && !p.paused && clock.playing && !clock.buffering && age >= 0 && age <= 350) seconds += age / 1000 * (clock.rate ?? 1);
          }
        } catch { /* A player can be released between a render and this sample. */ }
        if (duration > 0 && Number.isFinite(duration) && Number.isFinite(seconds)) cursor = readingWordAt(match, seconds / duration);
      }
      setSnapshot(old => {
        const message = old.scope === scope && old.cursor
          ? current.messages.find(message => message.id === old.cursor!.messageId) : undefined;
        const text = message ? visibleMessageText(message.content, message.role === 'assistant', Object.keys(message.mood_avatar_url_paths || {})) : '';
        const retained = old.cursor && message && text.startsWith(old.cursor.text) ? {...old.cursor, text} : null;
        // The source has no duration until EOS. Keep already spoken text steady
        // when its estimate is replaced by the completed file's exact duration.
        if (p.currentChunk?.progressive_audio && retained && retained.chunkId === p.currentChunk.id
          && (!cursor || cursor.start < retained.start)) cursor = retained;
        let finished = false;
        if (p.paused && retained && (!cursor || cursor.chunkId === retained.chunkId)) {
          cursor = retained; finished = old.finished;
        } else if (!cursor && retained && match?.messageId === retained.messageId
          && p.lastCompletedChunk?.id === retained.chunkId && match.words[0]!.start >= retained.chunkEnd) {
          // A successor source may not have delivered its first native clock.
          // Preserve only the prefix proved complete by the prior player's end.
          cursor = {...retained,start:retained.chunkEnd,end:retained.chunkEnd};
        } else if (!p.currentChunk && retained) {
          finished = old.finished || (p.lastCompletedChunk !== old.completion && p.lastCompletedChunk?.id === retained.chunkId);
          const end = finished ? retained.chunkEnd : retained.start;
          cursor = { ...retained, start: end, end };
        }
        if (old.scope === scope && old.cursor?.messageId === cursor?.messageId && old.cursor?.text === cursor?.text
          && old.cursor?.chunkId === cursor?.chunkId && old.cursor?.start === cursor?.start && old.cursor?.end === cursor?.end
          && old.finished === finished && old.completion === p.lastCompletedChunk) return old;
        return { scope, cursor, completion: p.lastCompletedChunk, finished };
      });
    };
    update();
    const interval = playback.isPlaying && !playback.paused ? setInterval(update, 100) : null;
    return () => { if (interval !== null) clearInterval(interval); };
  }, [enabled, visible, scope, messages, match, playback.isPlaying, playback.paused, playback.lastCompletedChunk, playback.positionSeconds]);

  const cursor = enabled && snapshot.scope === scope ? snapshot.cursor : null;
  const status = playback.paused ? 'paused' : playback.isPlaying ? (cursor ? 'reading' : 'unavailable')
    : playback.currentChunk || playback.activeReplyId ? 'waiting' : snapshot.finished ? 'finished' : 'ready';
  return { cursor, status };
}
