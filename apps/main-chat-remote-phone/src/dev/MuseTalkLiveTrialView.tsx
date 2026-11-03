import React from 'react';
import {Keyboard, Pressable, StyleSheet, Text, View} from 'react-native';
import type {PlaybackState} from '../hooks/useAudioQueue';
import type {RemoteClient} from '../api/client';
import type {AudioChunk} from '../api/types';
import type {OptionalVisualStart} from '../utils/optionalVisualStart';
import {MuseTalkLiveTrial} from './museTalkLiveTrial';
import {MuseTalkSegmentVideo} from './MuseTalkSegmentVideo';
import {mediaSeconds, sameKey} from './museTalkProbeClock';
import type {ClockSample} from './museTalkProbeClock';
import {recordPhoneDebug} from '../utils/phoneDebugBridge';
import type {SegmentBudget, SegmentSession} from './museTalkSegmentSession';
import {liveWaitingMode} from './museTalkLiveWaiting';
import {registerPhonePositionReader} from '../utils/phonePresentation';
import type {PhonePositionReader} from '../utils/phonePresentation';
import type {ProbeVideoSegment} from './museTalkMatchedSample';
import {useMuseTalkLayoutDiagnostics} from './useMuseTalkLayoutDiagnostics';
import type {BufferedPlaybackRuntime} from '../native/bufferedPlaybackRuntime';

type Props = {client: RemoteClient; owner: string; playback: PlaybackState; active: boolean; allowed: boolean;
  buffered?:BufferedPlaybackRuntime; nativePresentation?:boolean;
  onStartHandler?: (handler: OptionalVisualStart | null) => void; expanded?: boolean; compact?: boolean;
  trial?: MuseTalkLiveTrial; sessionOwned?: boolean; beforeStart?: OptionalVisualStart; onPrefetch?: (chunk: AudioChunk | null | undefined) => void;
  showFallback?: boolean; presenceFallback?: React.ReactNode; presentationFill?: boolean;
  onPresentationReadyChange?: (ready:boolean)=>void};

export function MuseTalkLiveTrialView(props: Props) {
  const client=React.useRef(props.client);client.current=props.client;
  const ownsLocalMedia = React.useCallback((uri: string) => props.buffered?.ownsLocalVideo(uri)
    || client.current.ownsRelayMediaUrl(uri), [props.buffered]);
  const callbacks = React.useRef(props); callbacks.current = props;
  const [presentationLayers,setPresentationLayers]=React.useState({anticipation:false,reply:false});
  const observeAnticipationReady=React.useCallback((ready:boolean)=>setPresentationLayers(value=>
    value.anticipation===ready ? value : {...value,anticipation:ready}),[]);
  const observeReplyReady=React.useCallback((ready:boolean)=>setPresentationLayers(value=>
    value.reply===ready ? value : {...value,reply:ready}),[]);
  const presentationReady=presentationLayers.anticipation || presentationLayers.reply;
  React.useEffect(()=>{ callbacks.current.onPresentationReadyChange?.(presentationReady); },[presentationReady]);
  React.useEffect(()=>()=>callbacks.current.onPresentationReadyChange?.(false),[]);
  const budget = React.useRef<SegmentBudget>(new Set());
  const visiblePosition = React.useRef<PhonePositionReader | null>(null);
  const observePositionReader = React.useCallback((reader: PhonePositionReader | null) => { visiblePosition.current = reader; },[]);
  React.useEffect(() => {
    if (!props.active || !props.allowed || props.nativePresentation) return;
    return registerPhonePositionReader(props.client,() => visiblePosition.current?.() ?? null);
  },[props.client,props.active,props.allowed,props.nativePresentation]);
  const [, revise] = React.useState(0);
  const localLive = React.useMemo(() => new MuseTalkLiveTrial(props.client), [props.owner,props.client.identityKey,
    props.client.pairingCode,props.client.auth.kind,props.client.auth.kind === 'internet' ? props.client.auth.deviceToken : '']);
  const live = props.trial ?? localLive;
  const sample = React.useRef<{player: PlaybackState['activePlayer']; clock: ClockSample} | null>(null);
  const clockSource = React.useRef<{reply:string; emotion:string} | null>(null);
  const heard = React.useRef<string | null>(null);
  const snapshot = live.snapshot;
  // Releasing the audio gate retires transport ownership, not the visible native
  // picture. Keep that picture until speech has actually been selected/committed.
  const outgoingAnticipation = React.useRef<typeof snapshot.anticipation>(null);
  if (!props.active || !props.allowed) outgoingAnticipation.current = null;
  else if (snapshot.anticipation) outgoingAnticipation.current = snapshot.anticipation;
  else if (snapshot.phase !== 'playing') outgoingAnticipation.current = null;
  const anticipation = snapshot.anticipation ?? outgoingAnticipation.current;
  const anticipationCursor = anticipation?.cursor ?? null;
  const anticipationTimeline = React.useRef<{identity:string; baseCursor:number; segments:ProbeVideoSegment[]}>
    ({identity:'',baseCursor:0,segments:[]});
  const anticipationIdentity = anticipation ? `anticipation:${anticipation.planId}:${anticipation.mediaId}` : '';
  if (anticipationTimeline.current.identity !== anticipationIdentity) {
    anticipationTimeline.current = {identity:anticipationIdentity,baseCursor:anticipationCursor ?? 0,segments:[]};
  }
  const anticipationLocalIndex = anticipationCursor === null ? null : anticipationCursor-anticipationTimeline.current.baseCursor;
  const [preAudioProgress, setPreAudioProgress] = React.useState({planId:'',cursor:-1,seconds:0});
  const preAudioSeconds = preAudioProgress.planId === anticipation?.planId && preAudioProgress.cursor === anticipationCursor
    ? preAudioProgress.seconds : 0;
  const [committedAnticipation, setCommittedAnticipation] = React.useState<string | null>(null);
  const anticipationSession = React.useRef<{session: SegmentSession; planId: string; cursor: number | null} | null>(null);
  const observeAnticipationSession = React.useCallback((session: SegmentSession | null) => {
    anticipationSession.current = session && anticipation ? {session,planId:anticipation.planId,cursor:anticipationCursor} : null;
  },[anticipation?.planId,anticipationCursor]);
  let displayedAnticipationSeconds: number | null = null;
  if (anticipation && committedAnticipation === anticipation.planId) {
    const observed = anticipationSession.current;
    const session = observed?.planId === anticipation.planId && observed.cursor === anticipationCursor ? observed.session : null;
    const entry = session?.entries.find(item => item.segment.index === session.selectedIndex && !item.retired);
    if (entry?.segment.index === anticipationLocalIndex && entry.first && entry.player) {
      try { const time = entry.player.currentTime; if (Number.isFinite(time) && time >= 0) displayedAnticipationSeconds = time; } catch { /* No invented frame on native failure. */ }
    }
  }
  React.useEffect(() => {
    if (anticipation && anticipationCursor !== null && displayedAnticipationSeconds !== null) {
      live.anticipationFrame?.(anticipation.planId,anticipationCursor,displayedAnticipationSeconds);
    }
  },[live,anticipation?.planId,anticipationCursor,displayedAnticipationSeconds]);
  const key = {owner:props.owner,reply:snapshot.chunk?.phone_request_id ?? '',chunk:snapshot.chunk?.id ?? '',revision:props.playback.recoveryEpoch ?? 0};
  React.useEffect(() => {
    const unsubscribe = live.subscribe(() => revise(n=>n+1));
    if (callbacks.current.sessionOwned) callbacks.current.onStartHandler?.(callbacks.current.beforeStart ?? null);
    else callbacks.current.onStartHandler?.((chunk,signal,deadline) => {
      if (!callbacks.current.active || !callbacks.current.allowed) { live.cancel(); return; }
      return live.beforeStart(chunk,signal,deadline);
    });
    return () => { unsubscribe(); if (!callbacks.current.sessionOwned) live.cancel(); callbacks.current.onStartHandler?.(null); };
  }, [live, props.sessionOwned]);
  React.useEffect(() => { if ((!props.active || !props.allowed) && !props.sessionOwned) live.cancel(); }, [live,props.active,props.allowed,props.sessionOwned]);
  React.useEffect(() => {
    if (props.active && props.allowed) (props.onPrefetch ?? live.prefetch)(props.playback.preparedChunk);
  }, [live,props.active,props.allowed,props.onPrefetch,props.playback.preparedChunk,snapshot.chunk?.id,snapshot.audioDuration]);
  React.useEffect(() => {
    // Restore the native video surface before its first-frame readiness gate.
    // This runs only for an admitted dev trial, never merely while typing.
    if (snapshot.phase === 'preparing') {
      void recordPhoneDebug('info','musetalk_live_layout',{event:'keyboard_dismiss_requested',compact:Boolean(callbacks.current.compact),presentationMeasured:false}).catch(()=>{});
      Keyboard.dismiss();
    }
  }, [live,snapshot.phase]);
  React.useEffect(() => { if (!anticipation) setCommittedAnticipation(null); }, [anticipation?.planId]);
  React.useEffect(() => {
    if (snapshot.phase !== 'preparing' && snapshot.phase !== 'playing') return;
    const idlePosition = visiblePosition.current?.() ?? null;
    void recordPhoneDebug('info','musetalk_live_layout',{event:'layout_state',phase:snapshot.phase,
      compact:Boolean(props.compact),atMs:performance.now(),
      idleSourceFrame:idlePosition?.sourceFrame ?? null,idlePlaying:idlePosition?.playing ?? null,
      planId:anticipation?.planId ?? null,trialId:snapshot.trialId,presentationMeasured:false}).catch(()=>{});
  }, [live,snapshot.phase,props.compact]);
  React.useEffect(() => {
    if (!live.busy) return;
    const timer = setInterval(()=>{ live.refresh(); revise(n=>n+1); },1000/24);
    return () => clearInterval(timer);
  }, [live,snapshot.phase]);
  React.useEffect(() => {
    const player = props.playback.activePlayer;
    if (!player || !snapshot.chunk || props.playback.currentChunk?.id !== snapshot.chunk.id) return;
    if (props.playback.isPlaying) heard.current = snapshot.trialId;
    const attachedAt = performance.now();
    const previousSource = clockSource.current;
    const sameReply = previousSource?.reply === snapshot.chunk.phone_request_id;
    const emotion = snapshot.chunk.emotion ?? '';
    clockSource.current = {reply:snapshot.chunk.phone_request_id ?? '',emotion};
    const reportClock = (phase: string, extra: Record<string, unknown> = {}) => {
      try {
        void recordPhoneDebug('info','musetalk_live_clock',{phase,
          sequenceIndex:snapshot.chunk?.sequence_index ?? null,sameReply,
          emotionChanged:sameReply ? previousSource!.emotion !== emotion : null,
          confirmedPlaying:props.playback.isPlaying,atMs:performance.now(),
          elapsedMs:Math.max(0,performance.now()-attachedAt),...extra}).catch(()=>{});
      } catch { /* Diagnostic failure cannot affect clock admission. */ }
    };
    reportClock('attached');
    let firstStatus = true;
    let alive = true;
    const sub = player.addListener('playbackStatusUpdate',status => {
      if (alive && status.playing) heard.current = live.snapshot.trialId;
      if (alive) {
        // Native status events can wait in the main/JS queues. Their old position
        // must not acquire a new timestamp and rewind the visual clock on arrival.
        let seconds = status.currentTime;
        try { const native = player.currentTime; if (Number.isFinite(native) && native >= 0) seconds = native; } catch { /* Use the fenced status fallback. */ }
        const previous = sample.current;
        if (previous?.player === player && sameKey(previous.clock.key,key)) {
          seconds = Math.max(seconds,previous.clock.seconds);
        }
        sample.current = {player,clock:{key,seconds,sampledAtMs:performance.now(),
          playing:status.playing,buffering:status.isBuffering || !status.isLoaded}};
        if (firstStatus) {
          firstStatus = false;
          reportClock('first_status',{playing:status.playing,buffering:status.isBuffering || !status.isLoaded,
            nativeSeconds:seconds,statusSeconds:status.currentTime});
        }
      }
    });
    // The queue received confirmation before exposing activePlayer, so this
    // listener missed it. Seed from that exact slot instead of waiting for the
    // next native notification. Subsequent progress still follows native audio.
    const initial = props.playback.getPlaybackClock?.(player,snapshot.chunk.id);
    if (initial) {
      sample.current = {player,clock:{key,...initial}};
      reportClock('initial_status',{playing:initial.playing,buffering:initial.buffering,
        statusSeconds:initial.seconds,statusAgeMs:Math.max(0,performance.now()-initial.sampledAtMs)});
      revise(n=>n+1);
    }
    return () => { alive=false; sample.current=null; sub.remove(); };
  }, [live,props.playback.activePlayer,props.playback.currentChunk?.id,snapshot.chunk?.id,props.playback.recoveryEpoch]);
  let current = sample.current?.player === props.playback.activePlayer ? sample.current?.clock : null;
  let extrapolationMs = 100;
  if (current && sameKey(current.key,key) && props.playback.activePlayer) {
    try {
      const seconds = props.playback.activePlayer.currentTime;
      if (Number.isFinite(seconds) && seconds >= 0) {
        // Native audio remains the authority between delayed status callbacks.
        // A freshly read position needs no synthetic forward extrapolation.
        current = {...current,seconds:Math.max(seconds,current.seconds),sampledAtMs:performance.now()};
        sample.current = {player:props.playback.activePlayer,clock:current};
        extrapolationMs = 0;
      }
    } catch { /* Retain the bounded, stale-expiring status fallback. */ }
  }
  const target = current ? mediaSeconds(current,key,performance.now(),{maxSampleAgeMs:300,maxExtrapolationMs:extrapolationMs}) : null;
  const preparing = snapshot.phase === 'preparing';
  const waiting = ['off','arming','armed'].includes(snapshot.phase) && snapshot.idle ? 'idle'
    : liveWaitingMode(heard.current === snapshot.trialId,props.playback.currentChunk,props.playback.preparedChunk);
  const localSeconds = preparing ? 0 : props.playback.currentChunk?.id === snapshot.chunk?.id
    && target !== null && target < snapshot.audioDuration ? target : null;
  const seconds = localSeconds === null ? null : snapshot.offsetSeconds + Math.min(localSeconds,
    Math.max(0,Math.floor(snapshot.audioDuration*24)/24 - .000001));
  React.useEffect(() => { if (!preparing) live.advance(localSeconds); }, [live,localSeconds,preparing]);
  const allowed = props.allowed && props.active && props.client.auth.kind === 'lan' && !props.playback.activePlayer && !props.playback.isPlaying;
  const visualLifetime = React.useMemo(() => ({seen:false}), [live,props.owner]);
  const visualAllowed = props.active && props.allowed && (props.client.auth.kind === 'lan'||Boolean(props.buffered));
  const [resumeReady,setResumeReady] = React.useState(true);
  React.useEffect(() => {
    if (!visualAllowed) { setResumeReady(false); return; }
    let alive = true;
    // Child native effects can run before this parent's regular advance effect.
    // After suspension, admit the current audio window before recreating clips.
    // A replacement audio player is seeded by the earlier attachment effect;
    // the render-time sample can still refer to its predecessor on this turn.
    const attached = sample.current && sample.current.player === props.playback.activePlayer ? sample.current.clock : null;
    const resumeSeconds = attached && sameKey(attached.key,key) ? attached.seconds : localSeconds;
    Promise.resolve(live.advance(preparing ? null : resumeSeconds)).then(() => {
      if (alive) setResumeReady(true);
    });
    return () => { alive=false; };
  }, [live,visualAllowed,snapshot.chunk?.id,props.playback.activePlayer]);
  if (!visualAllowed) visualLifetime.seen = false;
  else if (snapshot.segments.length > 0 || snapshot.idle) visualLifetime.seen = true;
  // Empty off/arming snapshots release reply ownership, not the last displayed
  // native frame. The renderer retains it until the replacement commits.
  const showRenderer = visualAllowed && resumeReady && (snapshot.segments.length > 0 || snapshot.idle
    || (props.sessionOwned && visualLifetime.seen));
  const hideManualChrome = props.compact && !props.sessionOwned;
  const reportLayout = useMuseTalkLayoutDiagnostics({scope:'trial',expanded:Boolean(props.expanded),
    active:visualAllowed,showRenderer:Boolean(showRenderer),showFallback:Boolean(props.showFallback),hidden:Boolean(hideManualChrome)});
  // Cursor acknowledgements append to one native timeline. Rekeying each range
  // would discard its prepared lookahead and decode that same clip again.
  if (anticipation?.state === 'active' && anticipationLocalIndex !== null) {
    let rows = anticipationTimeline.current.segments;
    while (rows.length <= anticipationLocalIndex+1 && rows.length < 2160) {
      const row = anticipation.segments[(anticipationTimeline.current.baseCursor+rows.length) % anticipation.segments.length];
      if (!row || row.state !== 'ready' || !row.uri || !row.bytes) break;
      const last = rows[rows.length-1];
      const startFrame = last ? last.startFrame+last.frameCount : 0;
      if (startFrame+row.frameCount > 90*24) break;
      rows = [...rows,{index:rows.length,startFrame,frameCount:row.frameCount,uri:row.uri,bytes:row.bytes}];
    }
    anticipationTimeline.current.segments = rows;
  }
  const anticipationSegments = anticipationTimeline.current.segments;
  const anticipationSegment = anticipationLocalIndex === null ? null : anticipationSegments[anticipationLocalIndex] ?? null;
  const anticipationStartFrame = anticipationSegment?.startFrame ?? anticipationSegments.reduce((total,row)=>total+row.frameCount,0);
  // During anticipation the speech opener prepares invisibly. After the audio
  // gate opens, silent lookahead is released and speech can admit its current
  // target while the outgoing silent surface waits for the display handoff.
  // Keep the full timeline valid even when this renderer mounts after a plan
  // arrives. reserveSpeechOpening limits native admission, not timeline shape.
  const speechSegments = snapshot.segments;
  return <View onLayout={event => reportLayout('panel',event.nativeEvent.layout)} style={[styles.panel,props.expanded ? styles.expanded : styles.inline,props.presentationFill && styles.presentationFill]}>
    {props.compact && !props.sessionOwned ? <Text testID="live-trial-keyboard-status" numberOfLines={1} style={styles.text}>{snapshot.message}</Text> : null}
    <View onLayout={event => reportLayout('content',event.nativeEvent.layout)} style={[styles.content,props.expanded ? styles.expanded : styles.inline,props.sessionOwned && !props.expanded && styles.inlineAvatar,props.presentationFill && styles.presentationFill,hideManualChrome && styles.hidden]}>
    {!props.sessionOwned ? <><Text style={styles.text}>DEV ONLY · Live delivery · 0.5s segments · one complete reply</Text>
    <Text style={styles.text}>{snapshot.message}</Text>
    <View style={styles.row}>
      <Pressable testID="arm-live-delivery" disabled={!allowed || live.busy}
        onPress={() => { if (allowed && !live.busy) void live.arm(); }}>
        <Text style={[styles.button,(!allowed || live.busy) && styles.disabled]}>Arm live delivery trial</Text>
      </Pressable>
      <Pressable onPress={()=>live.cancel()}><Text style={styles.button}>Stop visual trial</Text></Pressable>
    </View>
    <Text style={styles.text}>Connect over LAN with Live off. Arm, then send one new message. Speech keeps its normal timing. Delayed video holds the frame; an audio gap uses the avatar’s source idle cycle. Visuals follow reply completion or cancellation.</Text></> : null}
    {visualAllowed && anticipation?.state === 'active' ? <MuseTalkSegmentVideo
      identity={anticipationIdentity} budget={budget.current} liveReply anticipationTrack
      onSession={observeAnticipationSession}
      expanded={props.expanded} overlay={committedAnticipation !== anticipation?.planId}
      onDisplayCommitted={() => setCommittedAnticipation(anticipation!.planId)}
      segments={anticipationSegments} durationSeconds={anticipationSegments.reduce((total,row)=>total+row.frameCount,0)/24}
      audioSeconds={anticipationStartFrame/24+Math.min(displayedAnticipationSeconds ?? preAudioSeconds,
        Math.max(0,((anticipationSegment?.frameCount ?? 1)-1)/24))}
      paused={snapshot.phase !== 'preparing'} preparing={false} resolveMedia={live.resolveSegment} ownsLocalMedia={ownsLocalMedia}
      presentationFill={props.presentationFill} onPresentationReadyChange={observeAnticipationReady}
      showLabel={false} onNativeProgress={(index,seconds,terminal) => {
        if (index !== anticipationLocalIndex || !anticipationSegment || anticipationCursor === null) return;
        setPreAudioProgress({planId:anticipation.planId,cursor:anticipationCursor,
          seconds:Math.min(seconds,(anticipationSegment.frameCount-1)/24)});
        if (terminal) live.anticipationProgress(anticipationCursor+1);
      }} /> : null}
    {showRenderer ? <MuseTalkSegmentVideo
      attachLocalVideo={props.buffered?.attachLocalVideo} retainLocalMedia={props.buffered?.retainLocalMedia}
      identity={`${props.sessionOwned ? `${snapshot.trialId}:${snapshot.chunk?.phone_request_id ?? snapshot.idle?.uri ?? 'armed'}` : snapshot.trialId}:recovery-${props.playback.recoveryEpoch ?? 0}`} budget={budget.current} liveReply
      onPositionReader={observePositionReader}
      segments={speechSegments} durationSeconds={snapshot.duration}
      startupDeadlineMs={live.startupDeadlineMs}
      idle={props.nativePresentation?null:snapshot.idle} idleVerified={snapshot.idleVerified} waiting={waiting} keepIdleReady={props.sessionOwned} speechClips={4}
      // Native "playing" can precede actual audio progress (notably on Bluetooth).
      // Do not run the opening video ahead and then freeze it for audio to catch up.
      audioSeconds={seconds} paused={preparing || localSeconds === 0 || !current?.playing || Boolean(current?.buffering) || !props.playback.isPlaying}
      preparing={preparing} resolveMedia={live.resolveSegment} ownsLocalMedia={ownsLocalMedia} onPrepared={live.firstReady}
      onUnavailable={live.startupUnavailable}
      expanded={props.expanded} hidden={Boolean(snapshot.anticipation && committedAnticipation === anticipation?.planId)}
      overlay={Boolean(anticipation)}
      onDisplayCommitted={index => {
        if (index >= 0 && !live.snapshot.anticipation && outgoingAnticipation.current) {
          outgoingAnticipation.current = null; setCommittedAnticipation(null); revise(n=>n+1);
        }
      }}
      releaseOutgoing={Boolean(anticipation && committedAnticipation === anticipation.planId)}
      reserveSpeechOpening={Boolean(snapshot.anticipation || snapshot.anticipationPending)} showLabel={!props.sessionOwned}
      presentationFill={props.presentationFill} onPresentationReadyChange={observeReplyReady} /> : null}
    {props.sessionOwned && props.showFallback && !presentationReady ? <View testID="musetalk-live-presence-fallback"
      style={[styles.fallback, props.expanded ? styles.fallbackExpanded : styles.fallbackInline,props.presentationFill && styles.presentationFill,styles.presentationFallback]}>{props.presenceFallback}</View> : null}
    </View>
  </View>;
}
const styles = StyleSheet.create({panel:{padding:10,gap:10},content:{gap:10},hidden:{display:'none'},expanded:{flex:1},inline:{flex:0},inlineAvatar:{minHeight:280},presentationFill:{flex:1,height:'100%',minHeight:0,padding:0,width:'100%'},row:{flexDirection:'row',flexWrap:'wrap',gap:18},
  text:{color:'#b9ced8'},button:{color:'#70d5ee',paddingVertical:10},disabled:{opacity:.4},fallback:{justifyContent:'center',alignItems:'center'},fallbackInline:{flex:0,height:280,minHeight:280},fallbackExpanded:{flex:1,height:'auto',minHeight:0},presentationFallback:{...StyleSheet.absoluteFillObject,zIndex:1}});
