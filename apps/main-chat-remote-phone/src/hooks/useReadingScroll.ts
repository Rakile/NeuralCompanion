import { useCallback, useEffect, useRef } from 'react';
import type { RefObject } from 'react';
import type { FlatList, NativeScrollEvent, NativeSyntheticEvent, Text, TextLayoutEventData, View } from 'react-native';
import type { ChatMessage } from '../api/types';
import { readingLineAt } from '../utils/readingAlong';
import type { ReadingCursor, ReadingLine } from '../utils/readingAlong';

type Options = {
  cursor?: ReadingCursor | null; tracking: boolean; following: boolean; request: number; identity: string;
  fontSize: number; index: number; scrollRef: RefObject<FlatList<ChatMessage> | null>;
  contentRef: RefObject<View | null>;
  bottomInset?: number;
  onDetached?: () => void; animate: boolean;
  isSuspended?: () => boolean;
  onScrollCommand?: (kind:'reading_index'|'reading_offset'|'reading_estimate',target:number)=>void;
};

export function useReadingScroll(options: Options) {
  const latest = useRef(options); latest.current = options;
  const textRef = useRef<Text | null>(null);
  const layout = useRef<{ key: string; lines: ReadingLine[] }>({ key: '', lines: [] });
  const frame = useRef<number | null>(null), retry = useRef<ReturnType<typeof setTimeout> | null>(null);
  const manual = useRef(false), programmatic = useRef(false), offset = useRef(0), attempts = useRef(0);
  const epoch = useRef(0), lastScroll = useRef(-Infinity);
  const lastTarget = useRef({ offset: -Infinity, at: -Infinity });
  const key = (o: Options) => `${o.identity}:${o.cursor?.messageId}:${o.fontSize}:${o.cursor?.text}`;
  const allowed = () => latest.current.tracking && latest.current.following && !manual.current
    && !latest.current.isSuspended?.() && !!latest.current.cursor;
  const cancel = useCallback(() => {
    epoch.current++;
    if (frame.current !== null) cancelAnimationFrame(frame.current);
    if (retry.current !== null) clearTimeout(retry.current);
    frame.current = null; retry.current = null;
  }, []);
  const follow = useCallback(() => {
    if (!allowed() || frame.current !== null) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = null;
      if (!allowed()) return;
      const o = latest.current, cursor = o.cursor!;
      if (!textRef.current || layout.current.key !== key(o)) {
        if (!textRef.current && o.index >= 0 && attempts.current < 3) {
          attempts.current++;
          programmatic.current = true;
          o.onScrollCommand?.('reading_index',o.index);
          o.scrollRef.current?.scrollToIndex({ index: o.index, viewPosition: .4, animated: false });
        }
        return;
      }
      const line = readingLineAt(cursor.text, layout.current.lines, cursor.start);
      const viewport = o.scrollRef.current?.getNativeScrollRef();
      const content = o.contentRef.current;
      if (!line || !viewport || !content || !('measureInWindow' in viewport)) return;
      const version = ++epoch.current, targetKey = key(o), start = cursor.start;
      const measuredText = textRef.current, measuredOffset = offset.current;
      // Native measurements arrive asynchronously. A later word, recycled row
      // or scroll makes this geometry obsolete even within the same reply.
      const current = () => allowed() && epoch.current === version && key(latest.current) === targetKey
        && latest.current.cursor?.start === start && textRef.current === measuredText
        && latest.current.contentRef.current === content
        && latest.current.bottomInset === o.bottomInset
        && Math.abs(offset.current - measuredOffset) < 1;
      // Measure against the scroll content, not the moving screen. Combining a
      // screen Y from one native frame with a delayed JS scroll offset creates
      // alternating destinations while Android is animating or recycling rows.
      measuredText.measureLayout(content, (_x, textY, textWidth, textHeight) => {
        if (!current() || ![textY, textWidth, textHeight, line.y, line.height].every(Number.isFinite)
          || textWidth <= 0 || textHeight <= 0 || line.height <= 0) return;
        viewport.measureInWindow((_vx: number, _viewY: number, _w: number, viewportHeight: number) => {
          const height = viewportHeight - Math.max(0, o.bottomInset || 0);
          if (!current() || !Number.isFinite(height) || !(height > 0)) return;
          const contentCenter = textY + line.y + line.height / 2;
          const center = contentCenter - measuredOffset;
          if (center >= height * .2 && center <= height * .66) return;
          const remaining = 350 - (performance.now() - lastScroll.current);
          if (remaining > 0) {
            // Resizing or opening the controls can move a paused word. Keep the
            // trailing layout update; there may be no next playback tick to retry it.
            if (retry.current === null) retry.current = setTimeout(() => { retry.current = null; follow(); }, remaining);
            return;
          }
          const target = Math.max(0, contentCenter - height * .44);
          if (Math.abs(target - lastTarget.current.offset) < 20 && performance.now() - lastTarget.current.at < 1000) return;
          lastScroll.current = performance.now(); lastTarget.current = { offset: target, at: lastScroll.current };
          programmatic.current = true;
          o.onScrollCommand?.('reading_offset',target);
          o.scrollRef.current?.scrollToOffset({ offset: target, animated: o.animate });
        });
      }, () => { /* A recycled/unmounted row has no usable position; wait for its next layout. */ });
    });
  }, []);
  const detach = useCallback(() => {
    cancel(); programmatic.current = false;
    if (!manual.current) { manual.current = true; latest.current.onDetached?.(); }
  }, [cancel]);
  useEffect(() => {
    cancel(); manual.current = false; programmatic.current = false; attempts.current = 0; lastScroll.current = -Infinity;
    lastTarget.current = { offset: -Infinity, at: -Infinity };
    follow();
  }, [options.identity, options.request, cancel, follow]);
  useEffect(() => {
    attempts.current = 0;
  }, [options.cursor?.messageId, options.fontSize]);
  useEffect(() => { follow(); }, [options.cursor?.messageId, options.cursor?.start, options.fontSize, options.tracking, options.following, follow]);
  useEffect(() => cancel, [cancel]);
  return {
    textRef, follow, detach, cancel,
    onTextLayout: (event: NativeSyntheticEvent<TextLayoutEventData>) => {
      layout.current = { key: key(latest.current), lines: event.nativeEvent.lines }; follow();
    },
    onScroll: (event: NativeSyntheticEvent<NativeScrollEvent>) => { offset.current = event.nativeEvent.contentOffset.y; },
    ignoreMomentum: () => programmatic.current && !manual.current,
    finishMomentum: () => { const ignore = programmatic.current && !manual.current; programmatic.current = false; return ignore; },
    onScrollToIndexFailed: (info: { index: number; averageItemLength: number }) => {
      if (!allowed() || info.index !== latest.current.index || attempts.current >= 3) return;
      programmatic.current = true;
      latest.current.onScrollCommand?.('reading_estimate',Math.max(0,info.averageItemLength*info.index));
      latest.current.scrollRef.current?.scrollToOffset({ offset: Math.max(0, info.averageItemLength * info.index), animated: false });
      if (retry.current !== null) clearTimeout(retry.current);
      retry.current = setTimeout(() => { retry.current = null; follow(); }, 120);
    },
  };
}
