import { useThemedStyles, useThemeColors, usePhoneTheme, usePresentationStyle } from '../styles/ThemeContext';
import type { ThemeColors } from '../styles/theme';
import React, { useEffect, useRef } from 'react';
import { FlatList, Image, Pressable, StyleSheet, Text, View } from 'react-native';
import type { NativeScrollEvent, NativeSyntheticEvent } from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import Reanimated, { runOnJS, useAnimatedStyle, useSharedValue } from 'react-native-reanimated';
import type { ConversationActionTarget } from '../api/types';

import type { RemoteClient } from '../api/client';
import type { ChatMessage, InlineVisualReply as InlineVisualReplyItem, PresenceActivity, PresenceState } from '../api/types';
import type { ChatIndicatorStyle, ChatReadingStyle, ChatTextColor } from '../hooks/usePhoneSettings';
import { useInterfaceMode } from '../context/InterfaceModeContext';
import { colors, spacing } from '../styles/theme';
import { useAuthorizedMediaUrl } from '../hooks/useAuthorizedMediaUrl';
import { InlineVisualReply } from './InlineVisualReply';
import type { VisualDisplay } from '../utils/visualDisplay';
import { MoodAvatar } from './presence/MoodAvatar';
import { visibleMessageText } from '../utils/chatText';
export { visibleMessageText } from '../utils/chatText';
import type { ReadingCursor } from '../utils/readingAlong';
import { useReadingScroll } from '../hooks/useReadingScroll';
import { ReadingHighlight } from './ReadingHighlight';
import type { HighlightLine } from './ReadingHighlight';
import { pinchFontSize, pinchPreviewSize } from '../utils/chatZoom';
import { buildChatFeedEntries } from '../utils/chatParagraphs';
import type { ChatFeedEntry } from '../utils/chatParagraphs';
import {ChatScrollTrace, type ChatScrollEvent} from '../utils/chatScrollTrace';
import {recordPhoneDebug} from '../utils/phoneDebugBridge';

type Props = {
  soundMenu?:React.ReactNode;
  endWaitingTarget?: ConversationActionTarget | null;
  onEndWaiting?: (target: ConversationActionTarget) => Promise<void>;
  messages: ChatMessage[];
  automatedUserText?: string;
  presence?: PresenceState | null;
  client: RemoteClient;
  textColor?: ChatTextColor;
  indicatorStyle?: ChatIndicatorStyle;
  activity?: PresenceActivity | 'idle';
  presenceMode?: 'conversation' | 'companion';
  disabled?: boolean;
  onOpenVisualReply?: (item: InlineVisualReplyItem) => void;
  onRetryVisualReply?: (item: InlineVisualReplyItem) => Promise<void>;
  onOpenVisualPanel?: () => void;
  onAvatarLongPress?: () => void;
  onOpenDesktopControls?: (message: ChatMessage) => void;
  connected?: boolean;
  conversationAvatarSize?: number;
  messageFontSize?: number;
  bionicReading?: boolean;
  onMessageFontSizeChange?: (fontSize: number) => void;
  reading?: ReadingCursor | null;
  readingStyle?: ChatReadingStyle;
  readingTracking?: boolean;
  followReading?: boolean;
  preferSpokenFollow?: boolean;
  followSuspended?: boolean;
  readingFollowRequest?: number;
  readingScope?: string;
  onReadingDetached?: () => void;
  animateReadingScroll?: boolean;
  retainedMessages?: number;
  bottomInset?: number;
  visualDisplay?: VisualDisplay;
};

const lightTextColors = { white: '#172b38', green: '#17623a', amber: '#805300', cyan: '#006778' };
const cleanTextColors: Record<ChatTextColor, string> = {
  white: '#f4f7fa',
  green: '#8ff0b0',
  amber: '#ffd27a',
  cyan: '#83e6f5',
};
// The same native anchor handles history changes and pinch reflow. Do not add
// an independent JS height-delta correction on top of native compensation.
const visibleScrollAnchor = {minIndexForVisible: 0} as const;
const noOpenVisualReply = (_item: InlineVisualReplyItem) => undefined;
const noRetryVisualReply = async (_item: InlineVisualReplyItem) => undefined;
const noOpenVisualPanel = () => undefined;

function bionicParts(value: string): {text: string; bold: boolean}[] {
  const parts: {text: string; bold: boolean}[] = [];
  let offset = 0;
  for (const match of value.matchAll(/[\p{L}\p{N}][\p{L}\p{M}\p{N}]*/gu)) {
    const start = match.index;
    if (start > offset) parts.push({text:value.slice(offset,start),bold:false});
    const letters = Array.from(match[0]);
    const middle = Math.ceil(letters.length / 2);
    parts.push({text:letters.slice(0,middle).join(''),bold:true});
    if (middle < letters.length) parts.push({text:letters.slice(middle).join(''),bold:false});
    offset = start + match[0].length;
  }
  if (offset < value.length) parts.push({text:value.slice(offset),bold:false});
  return parts;
}

function AuthorizedChatImage({ client, path }: { client: RemoteClient; path: string }) {
  const styles = useThemedStyles(createStyles, 'ChatFeed');

  const media = useAuthorizedMediaUrl(client, path);
  return media.url ? <Image source={{ uri: media.url }} style={styles.attachment} resizeMode="cover" /> : null;
}

function ActivityIndicator({ activity, styleName }: { activity: NonNullable<Props['activity']>; styleName: ChatIndicatorStyle }) {
  const styles = useThemedStyles(createStyles, 'ChatFeed');

  return (
    <View style={styles.activityRow}>
      {styleName === 'dot' ? <View style={styles.activityDot} /> : null}
      {styleName === 'pulse' ? <View style={styles.activityPulse}><View style={styles.activityDot} /></View> : null}
      {styleName === 'line' ? <View style={styles.activityLine} /> : null}
      {styleName === 'text' ? <Text style={styles.activityText}>{activity}</Text> : null}
    </View>
  );
}

export function ChatFeed({
  soundMenu,
  endWaitingTarget, onEndWaiting,
  messages,
  automatedUserText = '',
  presence,
  client,
  textColor = 'white',
  indicatorStyle = 'dot',
  activity = 'idle',
  presenceMode = 'conversation',
  disabled = false,
  onOpenVisualReply = noOpenVisualReply,
  onRetryVisualReply = noRetryVisualReply,
  onOpenVisualPanel = noOpenVisualPanel,
  visualDisplay,
  onAvatarLongPress,
  onOpenDesktopControls,
  connected = false,
  conversationAvatarSize = 72,
  messageFontSize = 15,
  bionicReading = false,
  onMessageFontSizeChange,
  reading = null,
  readingStyle = 'quiet_underline',
  readingTracking = false,
  followReading = false,
  preferSpokenFollow = false,
  followSuspended = false,
  readingFollowRequest = 0,
  readingScope,
  onReadingDetached,
  animateReadingScroll = false,
  retainedMessages = 20,
  bottomInset = 0,
}: Props) {
  const lightTheme = usePhoneTheme().appearance === 'light';
  const editorial = usePresentationStyle() === 'editorial';
  const styles = useThemedStyles(createStyles, 'ChatFeed');
  const colors = useThemeColors();
  const messageColor = textColor === 'white' ? colors.text : (lightTheme ? lightTextColors : cleanTextColors)[textColor];
  const [readingLayout, setReadingLayout] = React.useState<{key:string; lines:HighlightLine[]}>({key:'',lines:[]});

  const [playbackMoods, setPlaybackMoods] = React.useState<Record<string, string>>({});
  const playback = presence?.portrait_playback;
  React.useEffect(() => {
    if (!playback?.mood) return;
    const target = messages.find(message => message.role === 'assistant' &&
      (message.id === playback.message_id || Boolean(playback.portrait_key && message.portrait_key === playback.portrait_key)));
    if (!target) return;
    setPlaybackMoods(current => current[target.id] === playback.mood ? current : { ...current, [target.id]: playback.mood });
  }, [messages, playback?.message_id, playback?.portrait_key, playback?.mood]);
  const portraitRevision = React.useMemo(() => ({ playback, playbackMoods }),
    [playback?.message_id, playback?.portrait_key, playback?.mood, playbackMoods]);
  const { mode } = useInterfaceMode();
  const classicMode = mode === 'classic';
  const adaptiveMode = mode === 'adaptive';
  const flatMode = mode === 'flat';
  const immersiveMode = mode === 'immersive';
  const scrollRef = useRef<FlatList<ChatMessage> | null>(null);
  const scrollContentRef = useRef<View>(null!);
  const feedRef = useRef<View | null>(null);
  const [visibleCount, setVisibleCount] = React.useState(retainedMessages);
  const previousLength = useRef(messages.length);
  const expandedHistory = useRef(false);
  const pendingPrepend = useRef<{ height: number; offset: number } | null>(null);
  const contentHeight = useRef(0);
  const viewportHeight = useRef(0);
  const topLoadArmed = useRef(true);
  const viewportOffset = useRef(0);
  const additions = expandedHistory.current ? Math.max(0, messages.length - previousLength.current) : 0;
  const shownCount = Math.max(retainedMessages, visibleCount + additions);
  const visibleMessages = React.useMemo(() => messages.slice(-shownCount), [messages, shownCount]);
  const feedEntries = React.useMemo(() => buildChatFeedEntries(visibleMessages, message =>
    visibleMessageText(message.content, true, Object.keys(message.mood_avatar_url_paths || {}))), [visibleMessages]);
  const segmentedFeed = feedEntries.length !== visibleMessages.length;
  const latestMessage = messages[messages.length - 1];
  // Reserve the beginning of a new reply before its audio clock arrives. This
  // is a position target only: highlighting still uses the real reading cursor.
  // An active/paused spoken passage wins even when another reply is appended.
  const scrollReading: ReadingCursor | null = reading && (readingTracking || reading.messageId === latestMessage?.id)
    ? reading : preferSpokenFollow && latestMessage ? {
      messageId:latestMessage.id,
      text:visibleMessageText(latestMessage.content,latestMessage.role === 'assistant',Object.keys(latestMessage.mood_avatar_url_paths || {})),
      chunkId:'pending-position',start:0,end:0,chunkEnd:0,
    } : reading;
  const scrollTracking = readingTracking || preferSpokenFollow;
  const readingIndex = scrollReading ? feedEntries.findIndex(entry => entry.id === scrollReading.messageId &&
    (!entry.feedParagraph || (scrollReading.start >= entry.feedParagraph.start && scrollReading.start < entry.feedParagraph.end)
      || (entry.feedPartIndex === entry.feedPartCount! - 1 && scrollReading.start === entry.feedParagraph.end))) : -1;
  const readingEntry = readingIndex >= 0 ? feedEntries[readingIndex] : undefined;
  const readingPart = readingEntry?.feedParagraph;
  const localScrollReading = scrollReading && readingPart ? {...scrollReading, text:readingPart.body,
    start:Math.max(0,Math.min(readingPart.body.length,scrollReading.start-readingPart.start)),
    end:Math.max(0,Math.min(readingPart.body.length,scrollReading.end-readingPart.start)),
    chunkEnd:Math.max(0,Math.min(readingPart.body.length,scrollReading.chunkEnd-readingPart.start))} : scrollReading;
  const localReading = scrollReading === reading ? localScrollReading : reading;
  const activeReadingRowId = readingEntry?.feedKey || (readingEntry?.stream_key
    ? `${readingEntry.index}:${readingEntry.stream_key}` : readingEntry?.id);
  const layoutKey = JSON.stringify([readingScope,scrollReading?.messageId,scrollReading?.text,readingPart?.start,messageFontSize,bionicReading,editorial]);
  const currentLayoutKey = useRef(layoutKey); currentLayoutKey.current = layoutKey;
  const visualLayoutKey = visibleMessages.flatMap(message => (message.visual_replies || [])
    .map(item => `${message.id}:${item.id}:${item.status}:${item.updated_at || ''}`)).join('|');
  const followContentRevision = React.useMemo(() => ({}),
    [messages.length, latestMessage?.id, latestMessage?.content, automatedUserText, messageFontSize]);
  const traceData = useRef({revision:0, source:followContentRevision});
  if (traceData.current.source !== followContentRevision) traceData.current = {revision:traceData.current.revision+1,source:followContentRevision};
  const traceMetadata = useRef({});
  traceMetadata.current = {messageCount:messages.length,visibleMessages:visibleMessages.length,rows:feedEntries.length,
    fontSize:messageFontSize,bionicReading,bottomInset,editorial};
  const scrollTrace = useRef<ChatScrollTrace | null>(null);
  if (!scrollTrace.current) scrollTrace.current = new ChatScrollTrace(report => {
    void recordPhoneDebug('warning','chat_scroll_oscillation',{...report,...traceMetadata.current}).catch(()=>undefined);
  });
  useEffect(()=>{scrollTrace.current?.reset();},[readingScope,client.identityKey]);
  const listExtraData = React.useMemo(() => ({portraitRevision, reading, messageFontSize,
    bionicReading, readingStyle, readingLayout}),
  [portraitRevision, reading, messageFontSize, bionicReading, readingStyle, readingLayout]);
  const measuredVisualLayoutKey = useRef(visualLayoutKey);
  const visualSizeChange = useRef(false);
  const animatedFollow = useRef(false);
  const followedContentRevision = useRef<object | null>(null);
  const layoutGrowthFollowUsed = useRef(false);
  const markVisualSizeChange = React.useCallback(() => { visualSizeChange.current = true; }, []);
  useEffect(() => {
    if (additions) setVisibleCount(count => count + additions);
    previousLength.current = messages.length;
  }, [messages.length, additions]);
  useEffect(() => {
    setVisibleCount(retainedMessages);
    expandedHistory.current = false;
    pendingPrepend.current = null;
    previousLength.current = messages.length;
    topLoadArmed.current = true;
  }, [client.identityKey, retainedMessages, messages.length === 0]);
  const readingScroll = useReadingScroll({ cursor: localScrollReading, tracking: scrollTracking, following: followReading,
    request: readingFollowRequest, identity: readingScope || client.identityKey, fontSize: messageFontSize,
    index: readingIndex, scrollRef, contentRef: scrollContentRef, bottomInset,
    onDetached: onReadingDetached, animate: animateReadingScroll,
    isSuspended:()=>pinch.current || followSuspended,
    onScrollCommand:(kind,target)=>traceScroll(kind,target) });
  const readingState = useRef({ readingTracking:scrollTracking, readingScroll });
  readingState.current = { readingTracking:scrollTracking, readingScroll };
  const holdSpokenFollow = useRef(false);
  holdSpokenFollow.current = preferSpokenFollow || followSuspended;
  const messageSize = React.useMemo(() => ({ fontSize: messageFontSize,
    lineHeight: Math.round(messageFontSize * 1.5) }), [messageFontSize]);
  const displayTextContent = React.useCallback((value: string) => bionicReading ? bionicParts(value).map((part,index) =>
    part.bold ? <Text key={index} style={styles.bionicBold}>{part.text}</Text> : part.text) : value,
  [bionicReading,styles.bionicBold]);
  const pinch = useRef(false);
  const pinchContactsDown = useRef(false);
  const pinchCompleted = useRef(false);
  const [scrollLocked, setScrollLocked] = React.useState(false);
  const [liveRowIds, setLiveRowIds] = React.useState<ReadonlySet<string>>(() => new Set());
  const savedFontSize = useRef(messageFontSize);
  const onFontSizeChangeRef = useRef(onMessageFontSizeChange);
  onFontSizeChangeRef.current = onMessageFontSizeChange;
  const nativeFontSize = useSharedValue(messageFontSize);
  const liveFontSize = useSharedValue(messageFontSize);
  const liveTextSize = useAnimatedStyle(() => {
    const preview = pinchPreviewSize(liveFontSize.value);
    return {fontSize:preview.fontSize,lineHeight:preview.lineHeight,
      transform:[{scale:preview.scale}]};
  });
  const rowRefs = useRef(new Map<string, View>());
  const pendingZoom = useRef<{size:number} | null>(null);
  const settlingZoom = useRef(false);
  const followEnd = useRef(true);
  const userScrolling = useRef(false);
  const scrollFrame = useRef<number | null>(null);
  const traceScroll = (kind:ChatScrollEvent, value=viewportOffset.current, height=contentHeight.current, viewport=viewportHeight.current) => {
    const flags=(userScrolling.current?1:0)|(pinch.current?2:0)|(readingTracking?4:0)|(followReading?8:0)
      |(followSuspended?16:0)|(followEnd.current?32:0)|(preferSpokenFollow?64:0)|(scrollLocked?128:0);
    scrollTrace.current?.record(kind,value,height,viewport,flags,traceData.current.revision);
  };
  const traceLatest = useRef(traceScroll); traceLatest.current=traceScroll;
  const cancelFollow = React.useCallback(() => {
    if (scrollFrame.current !== null) cancelAnimationFrame(scrollFrame.current);
    scrollFrame.current = null;
    animatedFollow.current = false;
  }, []);
  useEffect(() => {
    savedFontSize.current = messageFontSize;
    nativeFontSize.value = messageFontSize;
    if (!pinch.current) liveFontSize.value = messageFontSize;
  }, [messageFontSize, nativeFontSize, liveFontSize]);
  const lastPinchAt = useRef(0);
  const unlockScroll = React.useCallback(() => {
    // Pinch recognition may end when the first finger lifts. The remaining
    // finger must not inherit the old fling or start a fresh one.
    if (pinchContactsDown.current) return;
    pinch.current = false;
    scrollRef.current?.setNativeProps({scrollEnabled:true});
    setScrollLocked(false);
  }, []);
  const lockScroll = React.useCallback(() => {
    if (pinch.current) return;
    pinchContactsDown.current = true;
    pinchCompleted.current = false;
    pinch.current = true;
    cancelFollow();
    readingState.current.readingScroll.cancel();
    // An idle list may have moved since its last JS scroll event. Avoid
    // snapping to that stale offset; only cancel an active drag or fling.
    if (userScrolling.current) { traceLatest.current('pinch_stop'); scrollRef.current?.scrollToOffset({offset:viewportOffset.current,animated:false}); }
    scrollRef.current?.setNativeProps({scrollEnabled:false});
    setScrollLocked(true);
  }, [cancelFollow]);
  const captureVisibleRows = React.useCallback(() => {
    lockScroll();
    feedRef.current?.measureInWindow((_x,feedY) => {
      const rows: {id:string;top:number;bottom:number}[]=[];
      const mounted=[...rowRefs.current];
      let remaining=mounted.length;
      if (!remaining) return;
      mounted.forEach(([id,view]) => view.measureInWindow((_left,top,_width,height) => {
        rows.push({id,top,bottom:top+height});
        if (--remaining === 0 && pinch.current) {
          const bottom=feedY+viewportHeight.current;
          setLiveRowIds(new Set(rows.filter(row=>row.bottom>=feedY-80 && row.top<=bottom+80)
            .map(row=>row.id)));
        }
      }));
    });
  }, [lockScroll]);
  const settleZoom = React.useCallback(() => {
    const pending = pendingZoom.current;
    if (!pending || pending.size !== savedFontSize.current || settlingZoom.current) return;
    settlingZoom.current = true;
    let completed = false;
    const finish = () => {
      if (completed) return;
      completed = true;
      clearTimeout(timeout);
      pendingZoom.current = null;
      settlingZoom.current = false;
      liveFontSize.value = pending.size;
      if (readingState.current.readingTracking) readingState.current.readingScroll.follow();
      unlockScroll();
    };
    const timeout = setTimeout(finish, 180);
    // Replacing animated text with normal text can trigger another native
    // layout pass. Let that settle while scrolling is still locked; the list's
    // native anchor has already kept the touched paragraph in place.
    setLiveRowIds(new Set());
    requestAnimationFrame(() => requestAnimationFrame(finish));
  }, [liveFontSize, unlockScroll]);
  useEffect(() => {
    if (pendingZoom.current?.size === messageFontSize) {
      const frame = requestAnimationFrame(() => requestAnimationFrame(settleZoom));
      return () => cancelAnimationFrame(frame);
    }
  }, [messageFontSize, settleZoom]);
  const finishPinch = React.useCallback((size:number) => {
    lastPinchAt.current = Date.now();
    pinchCompleted.current = true;
    const finalSize=Math.round(size);
    if (!pinch.current || finalSize === savedFontSize.current || !onFontSizeChangeRef.current) {
      liveFontSize.value=savedFontSize.current;
      setLiveRowIds(new Set());
      unlockScroll();return;
    }
    pendingZoom.current={size:finalSize};
    onFontSizeChangeRef.current(finalSize);
  }, [liveFontSize, unlockScroll]);
  const cancelPinch = React.useCallback(() => {
    pinchCompleted.current = true;
    if (pendingZoom.current) return;
    liveFontSize.value=savedFontSize.current;
    setLiveRowIds(new Set());
    unlockScroll();
  }, [liveFontSize, unlockScroll]);
  const releasePinchContacts = React.useCallback(() => {
    pinchContactsDown.current = false;
    if (pinchCompleted.current && !pendingZoom.current) unlockScroll();
  }, [unlockScroll]);
  const pinchGesture = React.useMemo(() => Gesture.Pinch()
    .onTouchesDown(event => { if (event.allTouches.length >= 2) runOnJS(lockScroll)(); })
    .onTouchesUp(event => { if (event.allTouches.length === 0) runOnJS(releasePinchContacts)(); })
    .onTouchesCancelled(event => { if (event.allTouches.length === 0) runOnJS(releasePinchContacts)(); })
    .onStart(event => {
      runOnJS(captureVisibleRows)();
    })
    .onUpdate(event => {
      liveFontSize.value=pinchFontSize(nativeFontSize.value,event.scale);
    })
    .onEnd(event => runOnJS(finishPinch)(pinchFontSize(nativeFontSize.value,event.scale)))
    .onFinalize((_event,success) => { if (!success) runOnJS(cancelPinch)(); }),
   [captureVisibleRows,cancelPinch,finishPinch,lockScroll,releasePinchContacts,nativeFontSize,liveFontSize]);
  const replyTap = useRef<{ id: string; time: number } | null>(null);
  const pressReply = React.useCallback((message: ChatMessage) => {
    const id = message.id;
    const now = Date.now();
    if (now - lastPinchAt.current < 450) return;
    const previous = replyTap.current;
    if (previous?.id === id && now - previous.time >= 0 && now - previous.time <= 320) {
      replyTap.current = null;
      onOpenDesktopControls?.(message);
    } else replyTap.current = { id, time: now };
  }, [onOpenDesktopControls]);
  const followLayout = React.useCallback(() => {
    if (pinch.current) return;
    if (pendingPrepend.current) return;
    if (readingState.current.readingTracking) { readingState.current.readingScroll.follow(); return; }
    if (holdSpokenFollow.current) return;
    if (!scrollRef.current || !followEnd.current || userScrolling.current || scrollFrame.current !== null) return;
    // Text streaming and late image loads grow an existing row. Wait for its
    // layout, coalescing updates instead of queuing animated scrolls per token.
    scrollFrame.current = requestAnimationFrame(() => {
      scrollFrame.current = null;
      if (pinch.current) return;
      const animated = animatedFollow.current;
      animatedFollow.current = false;
      if (readingState.current.readingTracking) { readingState.current.readingScroll.follow(); return; }
      if (holdSpokenFollow.current) return;
      if (followEnd.current && !userScrolling.current) {
        // FlatList.scrollToEnd uses cached/estimated cell frames. A Visual
        // Reply can resize before those frames catch up and pull us upward.
        if (viewportHeight.current > 0) {
          traceLatest.current('bottom', Math.max(0, contentHeight.current-viewportHeight.current));
          scrollRef.current?.scrollToOffset({
          offset: Math.max(0, contentHeight.current - viewportHeight.current), animated,
          });
        }
      }
    });
  }, []);
  const updateFollowPosition = React.useCallback((event: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, contentSize, layoutMeasurement } = event.nativeEvent;
    followEnd.current = layoutMeasurement.height > 0
      && contentSize.height - layoutMeasurement.height - Math.max(0, contentOffset.y) <= 48;
  }, []);
  const loadEarlier = React.useCallback(() => {
    if (pendingPrepend.current || shownCount >= messages.length || !topLoadArmed.current) return;
    topLoadArmed.current = false;
    pendingPrepend.current = { height: contentHeight.current, offset: viewportOffset.current };
    followEnd.current = false;
    expandedHistory.current = true;
    setVisibleCount(count => Math.min(messages.length, count + retainedMessages));
  }, [messages.length, retainedMessages, shownCount]);
  const beginUserScroll = React.useCallback(() => {
    if (pinch.current) return;
    readingState.current.readingScroll.detach();
    replyTap.current = null;
    userScrolling.current = true;
    traceLatest.current('drag');
    followEnd.current = false;
    layoutGrowthFollowUsed.current = false;
    animatedFollow.current = false;
    cancelFollow();
  }, [cancelFollow]);
  const finishUserScroll = React.useCallback((event: NativeSyntheticEvent<NativeScrollEvent>) => {
    if (pinch.current) return;
    traceLatest.current('drag_end',event.nativeEvent.contentOffset.y);
    userScrolling.current = false;
    updateFollowPosition(event);
    followLayout();
  }, [followLayout, updateFollowPosition]);
  useEffect(() => {
    replyTap.current = null;
    followEnd.current = true;
    userScrolling.current = false;
    cancelFollow();
    followLayout();
  }, [client.identityKey, messages.length === 0, cancelFollow, followLayout]);
  useEffect(() => cancelFollow, [cancelFollow]);
  useEffect(() => {
    if (!followSuspended) followLayout();
  }, [followSuspended, followLayout]);
  const renderMessage = React.useCallback(({ item: message }: { item: ChatMessage }) => {
        const entry = message as ChatFeedEntry;
        const original = entry.sourceMessage || message;
        const partIndex = entry.feedPartIndex || 0;
        const partCount = entry.feedPartCount || 1;
        const firstPart = partIndex === 0;
        const lastPart = partIndex === partCount - 1;
        const rowKey = entry.feedKey || (message.stream_key
          ? `${message.index}:${message.stream_key}` : message.id);
        const user = message.role === 'user';
        const playbackMood = playback && (message.id === playback.message_id
          || Boolean(playback.portrait_key && message.portrait_key === playback.portrait_key))
          ? playback.mood : playbackMoods[message.id];
        const avatarMood = playbackMood || message.mood || 'neutral';
        const avatarPath = message.mood_avatar_url_paths
          ? message.mood_avatar_url_paths[avatarMood] || message.neutral_avatar_url_path
          : message.avatar_url_path;
        const visualReplies = message.visual_replies || [];
        const imageIsVisualReply = visualReplies.some((item) => item.url_path === message.image_url_path);
        const displayText = entry.feedParagraph?.body ?? visibleMessageText(message.content, !user, Object.keys(message.mood_avatar_url_paths || {}));
        const scrollFocus = activeReadingRowId === rowKey && localScrollReading?.text === displayText;
        const focus = scrollFocus && localReading?.messageId === message.id && localReading.text === displayText ? localReading : null;
        // Paragraph virtualization moves the active ref, not the read prefix.
        // Paint every row from the original message offsets; only focus measures
        // or scrolls. Replay therefore also restores unread paragraphs correctly.
        const readPrefix = reading?.messageId === message.id && reading.text === visibleMessageText(
          original.content, !user, Object.keys(original.mood_avatar_url_paths || {}))
          ? Math.max(0, Math.min(displayText.length, reading.start - (entry.feedParagraph?.start || 0))) : 0;
        const painted = focus || (readPrefix > 0 ? {start:readPrefix,end:readPrefix} : null);
        const liveText = liveRowIds.has(rowKey);
        const blankLines = Math.max(0, (entry.feedParagraph?.separator.match(/\n/g)?.length || 0) - 1);
        const MessageText = liveText ? Reanimated.Text : Text;
        return (
          <View key={rowKey}
            ref={view => {if (view) rowRefs.current.set(rowKey,view);else rowRefs.current.delete(rowKey);}}
            style={[styles.messageRow, user ? styles.userMessageRow : styles.assistantMessageRow,
              segmentedFeed && lastPart && {marginBottom:flatMode?0:classicMode?spacing.sm:spacing.lg}]}>
            {!user && !editorial && firstPart ? (
              <MoodAvatar
                client={client}
                presence={null}
                variant="message"
                size={presenceMode === 'conversation' ? conversationAvatarSize : undefined}
                overridePath={avatarPath}
                initials={original.avatar_initials}
                mood={avatarMood}
                onLongPress={onAvatarLongPress}
              />
            ) : null}
            <View
              style={[
                styles.messageColumn,
                presenceMode === 'companion' && styles.companionMessageColumn,
                 classicMode
                  ? [styles.bubble, user ? styles.user : styles.assistant]
                  : [styles.cleanMessageBlock, adaptiveMode && styles.adaptiveMessage, flatMode && styles.flatMessage, immersiveMode && styles.immersiveMessage],
                 partCount > 1 && classicMode && [styles.segmentedBubble,
                   firstPart ? styles.segmentedBubbleFirst : lastPart ? styles.segmentedBubbleLast : styles.segmentedBubbleMiddle],
                 partCount > 1 && flatMode && !lastPart && styles.segmentedFlatBody,
              ]}
            >
              {firstPart ? <View style={styles.messageMeta}>
                <Text style={[styles.role, !classicMode && styles.cleanRole]}>{message.display_name || (user ? 'You' : message.role || 'Companion')}</Text>
                {message.mood && !user && !editorial ? <Text style={styles.mood}>{message.mood}</Text> : null}
              </View> : null}
              {firstPart && message.image_url_path && !imageIsVisualReply ? (
                <AuthorizedChatImage client={client} path={message.image_url_path} />
              ) : null}
              {focus && readingLayout.key === layoutKey && !liveText ? <ReadingHighlight cursor={focus} lines={readingLayout.lines}
                styleName={readingStyle} textStyle={[styles.message,messageSize]} /> : null}
              <MessageText selectable={!classicMode}
                ref={scrollFocus ? readingState.current.readingScroll.textRef : undefined}
                onTextLayout={scrollFocus ? event => {
                  if ((pinch.current && !pendingZoom.current) || currentLayoutKey.current !== layoutKey) return;
                  readingState.current.readingScroll.onTextLayout(event);
                  const lines = event.nativeEvent.lines;
                  setReadingLayout(previous => previous.key === layoutKey && previous.lines.length === lines.length
                    && previous.lines.every((line,index) => { const next = lines[index]!; return line.text === next.text
                      && Math.abs(line.x-next.x) < .5 && Math.abs(line.y-next.y) < .5
                      && Math.abs(line.width-next.width) < .5 && Math.abs(line.height-next.height) < .5; })
                    ? previous : {key:layoutKey,lines});
                } : undefined}
                onPress={message.role === 'assistant' && !message.provisional && onOpenDesktopControls ? () => pressReply(original) : undefined}
                onLongPress={() => { replyTap.current = null; }}
                accessibilityHint={!user && !message.provisional && onOpenDesktopControls ? 'Double tap the reply to open Desktop Controls' : undefined}
                accessibilityActions={!user && !message.provisional && onOpenDesktopControls ? [{ name: 'desktopControls', label: 'Open Desktop Controls' }] : undefined}
                onAccessibilityAction={event => { if (message.role === 'assistant' && !message.provisional && event.nativeEvent.actionName === 'desktopControls') onOpenDesktopControls?.(original); }}
                style={[styles.message, messageSize, liveText && liveTextSize,
                  editorial && {fontFamily:user?'sans-serif':'serif'}, {color:messageColor}]}>{painted ? <>
                  <Text style={styles.readText}>{displayTextContent(displayText.slice(0, painted.start))}</Text>
                  <Text style={[styles.currentWord,{color:messageColor},readingStyle === 'quiet_underline' && styles.wordUnderline,
                    readingStyle === 'soft_focus' && styles.wordGlow]}>{displayTextContent(displayText.slice(painted.start, painted.end))}</Text>
                  <Text>{displayTextContent(displayText.slice(painted.end))}</Text>
                </> : displayTextContent(displayText)}</MessageText>
              {blankLines > 0 ? <View style={{height:blankLines*Math.round(messageFontSize*1.5)}} /> : null}
              {lastPart && user && original === messages[messages.length - 1] && endWaitingTarget?.message_id === message.id && onEndWaiting ? (
                <Pressable accessibilityRole="button" accessibilityLabel="End waiting" disabled={disabled}
                  onPress={() => { void onEndWaiting(endWaitingTarget); }}>
                  <Text style={styles.mood}>End waiting</Text>
                </Pressable>
              ) : null}
              {lastPart && visualReplies.length ? (
                <InlineVisualReply
                  items={visualReplies}
                  client={client}
                  disabled={disabled}
                  onOpen={onOpenVisualReply}
                  onRetry={onRetryVisualReply}
                  onOpenVisual={onOpenVisualPanel}
                  onImageSizeResolved={markVisualSizeChange}
                  display={visualDisplay}
                />
              ) : null}
            </View>

          </View>
        );
  }, [messages,playback,playbackMoods,client,presenceMode,conversationAvatarSize,onAvatarLongPress,
    messageSize,messageFontSize,liveRowIds,liveTextSize,reading,localReading,localScrollReading,activeReadingRowId,readingLayout,layoutKey,readingStyle,displayTextContent,onOpenDesktopControls,
    pressReply,styles,colors,messageColor,editorial,classicMode,adaptiveMode,flatMode,
    immersiveMode,visualDisplay,onOpenVisualReply,onRetryVisualReply,onOpenVisualPanel,disabled,
    endWaitingTarget,onEndWaiting,markVisualSizeChange,segmentedFeed]);

  return (
    <GestureDetector gesture={pinchGesture}>
    <View ref={feedRef} style={styles.feedGestureSurface}
      onTouchEnd={event => {if (event.nativeEvent.touches.length === 0) releasePinchContacts();}}
      onTouchCancel={releasePinchContacts}>
    <View style={styles.feedGestureSurface}>
    <FlatList
      ref={scrollRef}
      innerViewRef={scrollContentRef}
      maintainVisibleContentPosition={visibleScrollAnchor}
      style={[styles.feed, adaptiveMode && styles.adaptiveFeed, flatMode && styles.flatFeed, immersiveMode && styles.immersiveFeed]}
      contentContainerStyle={[styles.content, !classicMode && styles.cleanContent, flatMode && styles.flatContent,
        segmentedFeed && styles.segmentedContent, bottomInset > 0 && {paddingBottom:spacing.md+bottomInset}]}
      data={feedEntries}
      scrollEnabled={!scrollLocked}
      extraData={listExtraData}
      initialNumToRender={12}
      maxToRenderPerBatch={8}
      windowSize={7}
      onContentSizeChange={(_width, height) => {
        traceScroll('content',viewportOffset.current,height);
        const pending = pendingPrepend.current;
        const previousHeight = contentHeight.current;
        const contentChanged = followedContentRevision.current !== followContentRevision;
        const visualChanged = measuredVisualLayoutKey.current !== visualLayoutKey || visualSizeChange.current;
        measuredVisualLayoutKey.current = visualLayoutKey;
        visualSizeChange.current = false;
        if (!pending && !holdSpokenFollow.current && height > contentHeight.current && contentHeight.current > 0 && visualChanged
          && followEnd.current && !userScrolling.current && !readingState.current.readingTracking) {
          animatedFollow.current = true;
        }
        contentHeight.current = height;
        if (pendingZoom.current) {
          followedContentRevision.current = followContentRevision;
          return;
        }
        if (height <= 0 || (viewportHeight.current > 0 && height <= viewportHeight.current)) return;
        if (pending) {
          pendingPrepend.current = null;
          // Native anchoring preserves the existing row, including when its
          // new measured height is smaller than a virtualized estimate.
        } else if (!pending && (contentChanged || visualChanged
          || (height > previousHeight && !layoutGrowthFollowUsed.current))) {
          // Scrolling can make FlatList remeasure virtualized paragraphs. Do
          // not chase alternating extents for the same reply indefinitely.
          followedContentRevision.current = followContentRevision;
          layoutGrowthFollowUsed.current = true;
          followLayout();
        }
      }}
      onLayout={event => {
        const height = event.nativeEvent?.layout?.height;
        if (typeof height === 'number') {viewportHeight.current = height;traceScroll('layout');}
        followLayout();
      }}
      onScrollBeginDrag={beginUserScroll}
      onMomentumScrollBegin={() => { if (!readingState.current.readingScroll.ignoreMomentum()) beginUserScroll(); }}
      onScrollEndDrag={finishUserScroll}
      onMomentumScrollEnd={event => { traceScroll('momentum_end',event.nativeEvent.contentOffset.y); if (!readingState.current.readingScroll.finishMomentum()) finishUserScroll(event); }}
      onScrollToIndexFailed={readingScroll.onScrollToIndexFailed}
      onScroll={(event) => {
        traceScroll('scroll',event.nativeEvent.contentOffset.y,event.nativeEvent.contentSize.height,event.nativeEvent.layoutMeasurement.height);
        readingState.current.readingScroll.onScroll(event);
        viewportHeight.current = event.nativeEvent.layoutMeasurement.height;
        viewportOffset.current = Math.max(0, event.nativeEvent.contentOffset.y);
        if (viewportOffset.current > 120) topLoadArmed.current = true;
        if (userScrolling.current && viewportOffset.current < 40) loadEarlier();
        // Native layout/programmatic scrolling must not mistake content growth
        // for the reader deliberately leaving the bottom of the conversation.
        if (userScrolling.current) updateFollowPosition(event);
      }}
      scrollEventThrottle={16}
      keyExtractor={(message) => (message as ChatFeedEntry).feedKey || `${message.index}:${message.stream_key || message.id}`}
      ListHeaderComponent={!classicMode && !editorial ? <ActivityIndicator activity={activity} styleName={indicatorStyle} /> : null}
      ListFooterComponent={<>{soundMenu}{automatedUserText ? (
        <View style={[styles.messageRow, styles.userMessageRow]}>
          <View style={styles.messageColumn}>
            <Text style={styles.role}>You - Reading aloud</Text>
          <Reanimated.Text selectable style={[styles.message,messageSize,liveTextSize,
            {color:messageColor}]}>
            {displayTextContent(automatedUserText)}
          </Reanimated.Text>
          </View>
        </View>
      ) : null}</>}
      ListEmptyComponent={automatedUserText ? null : (
        <View style={[styles.emptyCard, !classicMode && styles.cleanEmpty]}>
          <Text style={styles.emptyTitle}>{connected ? 'Start a conversation' : 'No chat loaded'}</Text>
          <Text style={styles.emptyText}>{connected ? 'Send a message or turn on Live Mode to talk.' : 'Connect to desktop or tap Demo.'}</Text>
        </View>
      )}
      renderItem={renderMessage}
    />
    </View>
    </View>
    </GestureDetector>
  );
}

const createStyles = (colors: ThemeColors) => StyleSheet.create({
  feedGestureSurface: {flex:1,overflow:'hidden'},
  bionicBold: {fontWeight:'700'},
  readText: { color: colors.muted },
  currentWord: { color: colors.text },
  wordUnderline: { textDecorationLine: 'underline', textDecorationColor: colors.accent, textDecorationStyle: 'solid' },
  wordGlow: { textShadowColor: `${colors.accent}A6`, textShadowOffset: {width:0,height:0}, textShadowRadius:4 },
  feed: {
    flex: 1,
  },
  content: {
    gap: spacing.sm,
    padding: spacing.md,
  },
  segmentedContent: {gap:0},
  emptyCard: {
    backgroundColor: colors.panel,
    borderColor: colors.border,
    borderRadius: 8,
    borderWidth: 1,
    gap: spacing.xs,
    padding: spacing.md,
  },
  emptyTitle: {
    color: colors.text,
    fontSize: 14,
    fontWeight: '900',
  },
  emptyText: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
  },
  bubble: {
    borderRadius: 8,
    borderWidth: 1,
    maxWidth: '94%',
    padding: spacing.md,
  },
  segmentedBubble: {alignSelf:'stretch',width:'94%'},
  segmentedBubbleFirst: {borderBottomWidth:0,borderBottomLeftRadius:0,borderBottomRightRadius:0,paddingBottom:0},
  segmentedBubbleMiddle: {borderTopWidth:0,borderBottomWidth:0,borderRadius:0,paddingTop:0,paddingBottom:0},
  segmentedBubbleLast: {borderTopWidth:0,borderTopLeftRadius:0,borderTopRightRadius:0,paddingTop:0},
  segmentedFlatBody: {borderBottomWidth:0},
  messageRow: { alignItems: 'flex-end', flexDirection: 'row', gap: spacing.sm },
  userMessageRow: { justifyContent: 'flex-end', alignSelf: 'flex-end', maxWidth: '88%', backgroundColor: colors.panelAlt, borderRadius: 18, padding: spacing.md },
  assistantMessageRow: { flexDirection: 'column', alignItems: 'flex-start', gap: spacing.md },
  messageColumn: { flexShrink: 1, maxWidth: '100%', alignSelf: 'stretch' },
  companionMessageColumn: { maxWidth: '88%' },
  messageMeta: { alignItems: 'center', flexDirection: 'row', gap: spacing.sm, justifyContent: 'space-between' },
  user: {
    alignSelf: 'flex-end',
    backgroundColor: colors.accentSoft,
    borderColor: '#2d5e7e',
  },
  assistant: {
    alignSelf: 'flex-start',
    backgroundColor: colors.panel,
    borderColor: colors.border,
  },
  role: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: '700',
    marginBottom: spacing.xs,
  },
  mood: { color: colors.accent, fontSize: 10, fontWeight: '800', textTransform: 'uppercase' },
  message: {
    color: colors.text,
    fontSize: 15,
    lineHeight: 21,
  },
  adaptiveFeed: { backgroundColor: colors.background },
  flatFeed: { backgroundColor: colors.background },
  immersiveFeed: { backgroundColor: colors.background },
  cleanContent: { gap: spacing.lg, paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  flatContent: { gap: 0 },
  cleanMessageBlock: { alignSelf: 'stretch' },
  adaptiveMessage: { maxWidth: '100%' },
  flatMessage: { borderBottomColor: colors.border, borderBottomWidth: 1, paddingVertical: spacing.md },
  immersiveMessage: { paddingVertical: spacing.sm },
  cleanRole: { color: colors.muted, marginBottom: spacing.sm },
  cleanEmpty: { backgroundColor: 'transparent', borderWidth: 0, paddingHorizontal: 0 },
  activityRow: { alignItems: 'center', height: 18, justifyContent: 'center' },
  activityDot: { backgroundColor: '#56d89b', borderRadius: 4, height: 7, width: 7 },
  activityPulse: { alignItems: 'center', borderColor: '#56d89b', borderRadius: 8, borderWidth: 1, height: 16, justifyContent: 'center', width: 16 },
  activityLine: { backgroundColor: '#56d89b', borderRadius: 1, height: 2, width: 52 },
  activityText: { color: colors.muted, fontSize: 11, fontWeight: '700', textTransform: 'uppercase' },
  attachment: {
    aspectRatio: 4 / 3,
    borderRadius: 6,
    marginBottom: spacing.sm,
    maxWidth: 360,
    width: '100%',
  },
});
