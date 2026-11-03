import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { createVideoPlayer, VideoView } from 'expo-video';
import type { ProbeVideoSegment } from './museTalkMatchedSample';
import { SegmentSession } from './museTalkSegmentSession';
import type { SegmentArrival, SegmentBudget, IdleVideo } from './museTalkSegmentSession';
import { recordPhoneDebug } from '../utils/phoneDebugBridge';
import { downloadIdleFile } from './museTalkIdleFile';
import type {PhonePositionReader} from '../utils/phonePresentation';
import {useMuseTalkLayoutDiagnostics} from './useMuseTalkLayoutDiagnostics';

type Props = {
  segments: readonly ProbeVideoSegment[]; durationSeconds: number; audioSeconds: number | null;
  paused: boolean; preparing: boolean; identity: string; arrival?: SegmentArrival; expanded?: boolean;
  resolveMedia: (uri: string, signal?: AbortSignal) => Promise<string>; onPrepared?: () => void; onUnavailable?: () => void;
  ownsLocalMedia?: (uri: string) => boolean;
  attachLocalVideo?: (player:import('expo-video').VideoPlayer,segment:ProbeVideoSegment,uri:string)=>Promise<()=>Promise<void>>;
  retainLocalMedia?: (uri:string,signal:AbortSignal)=>Promise<{release():Promise<void>}>;
  now?: () => number;
  startupDeadlineMs?: number;
  budget?: SegmentBudget;
  liveReply?: boolean;
  keepIdleReady?: boolean;
  speechClips?: 2 | 4;
  idle?: IdleVideo | null;
  idleVerified?: boolean;
  waiting?: 'hold' | 'idle';
  onNativeProgress?: (index: number, seconds: number, terminal: boolean) => void;
  hidden?: boolean;
  overlay?: boolean;
  anticipationTrack?: boolean;
  reserveSpeechOpening?: boolean;
  releaseOutgoing?: boolean;
  onDisplayCommitted?: (index: number) => void;
  onSession?: (session: SegmentSession | null) => void;
  onPositionReader?: (reader: PhonePositionReader | null) => void;
  showLabel?: boolean;
  presentationFill?: boolean;
  onPresentationReadyChange?: (ready:boolean)=>void;
};
let sequence = 0;
export function MuseTalkSegmentVideo(props: Props) {
  const reportLayout = useMuseTalkLayoutDiagnostics({scope:'video',expanded:Boolean(props.expanded),
    hidden:Boolean(props.hidden),overlay:Boolean(props.overlay)});
  const callbacks = React.useRef(props); callbacks.current = props;
  const retained = React.useRef<SegmentSession | null>(null);
  const [revision, update] = React.useState(0);
  const [display, setDisplay] = React.useState<{session: SegmentSession | null;
    entries: SegmentSession['entries']; selected: number | null; target: number | null}>
    ({session: null, entries: [], selected: null, target: null});
  const session = React.useMemo(() => {
    const run = ++sequence;
    return new SegmentSession({segments: props.segments, durationSeconds: props.durationSeconds,
      budget: props.budget,
      liveReply: props.liveReply,
      anticipationTrack: props.anticipationTrack,
      keepIdleReady: props.keepIdleReady,
      speechClips: props.speechClips,
      arrival: props.arrival ?? 'available', resolveMedia: props.resolveMedia,
      loadIdle:(uri,bytes,signal) => downloadIdleFile(uri,bytes,signal,props.ownsLocalMedia),
      createPlayer: () => createVideoPlayer(null), now: props.now ?? (() => performance.now()),
      attachLocalVideo:props.attachLocalVideo,
      retainLocalMedia:props.retainLocalMedia,
      changed: () => update(n => n+1), onPrepared: () => callbacks.current.onPrepared?.(),
      onUnavailable: () => callbacks.current.onUnavailable?.(),
      onNativeProgress: (index,seconds,terminal) => callbacks.current.onNativeProgress?.(index,seconds,terminal),
      startupDeadline: () => callbacks.current.startupDeadlineMs,
      report: (event, details) => { void recordPhoneDebug('info', 'musetalk_segment_probe',
        {run, phase: event, ...details}).catch(() => undefined); },
    });
  }, [props.identity, props.liveReply ? null : props.segments, props.resolveMedia, props.arrival, props.liveReply,props.keepIdleReady,props.speechClips,props.ownsLocalMedia,props.attachLocalVideo,props.retainLocalMedia]);
  const currentSession = React.useRef(session); currentSession.current = session;
  React.useEffect(() => { props.onSession?.(session); return () => props.onSession?.(null); }, [session,props.onSession]);
  React.useEffect(() => {
    const timeout = setTimeout(() => update(n => n+1), 1000);
    return () => {
      clearTimeout(timeout);
      if (props.liveReply && session.holdForReplacement(callbacks.current.audioSeconds === null && !callbacks.current.preparing)) {
        retained.current?.close('replaced_retained_surface');
        retained.current = session;
      } else session.close('scope_or_component_retired');
    };
  }, [session]);
  React.useEffect(() => () => {
    currentSession.current.close('component_retired');
    retained.current?.close('component_retired'); retained.current = null;
  }, []);
  // An intermediate re-arm session can have no selected picture. Do not let
  // that empty session mask the retained idle during the pre-effect render.
  const previous = display.session !== session ? display.session : null;
  const outgoing = previous?.entries.some(entry => entry.player && !entry.retired
    && entry.segment.index === previous.selectedIndex) ? previous : retained.current;
  const preserveArmedIdle = Boolean(props.liveReply && props.segments.length === 0 && outgoing?.entries.some(entry =>
    entry.segment.index === outgoing.selectedIndex && entry.player
      && (props.keepIdleReady || (entry.segment.index < 0 && entry.player.loop))));
  React.useEffect(() => { if (preserveArmedIdle) outgoing?.reportRetainedIdle(); }, [session,outgoing,preserveArmedIdle]);
  React.useEffect(() => {
    outgoing?.continueRetainedIdle();
    session.reserveForAnticipation(Boolean(props.reserveSpeechOpening));
    session.setTimeline(props.segments,props.durationSeconds);
    // A new arm is permission for a future reply, not an emotion change.
    // Keep the reply's emotion (including a pending idle/held speech frame)
    // instead of loading the arm's default.
    session.setIdle(preserveArmedIdle ? null : props.idle ?? null, props.idleVerified ?? true);
    session.update(props.audioSeconds, props.paused, props.preparing,props.waiting);
    setDisplay({session, entries: session.entries, selected: session.selectedIndex, target: session.targetIndex});
  }, [session, outgoing, props.audioSeconds, props.paused, props.preparing, props.segments, props.durationSeconds, props.idle, props.idleVerified, props.waiting, revision,preserveArmedIdle,props.reserveSpeechOpening,props.budget?.size]);
  React.useEffect(() => {
    if (props.releaseOutgoing && retained.current) {
      retained.current.close('anticipation_surface_committed'); retained.current = null; update(n=>n+1);
    }
  }, [props.releaseOutgoing,session]);
  const idleSeekPending = Boolean(props.liveReply && props.waiting === 'idle' && !props.preparing
    && props.audioSeconds === null && session.entries.some(entry => entry.segment.index === props.idle?.index
      && !entry.retired && entry.seek));
  React.useEffect(() => {
    if (!idleSeekPending && !outgoing?.retainedIdlePending) return;
    // Native seeks settle asynchronously. With no speech clock, stable props
    // alone cannot recheck readiness. Stop ticking as soon as idle is looping
    // or the existing bounded seek check fails; never drive speech with this.
    const timer = setInterval(() => update(n => n + 1), 50);
    return () => clearInterval(timer);
  }, [session, idleSeekPending, outgoing, outgoing?.retainedIdlePending]);
  const waitForSpeech = Boolean(props.liveReply && outgoing && outgoing.selectedIndex !== null
    && display.selected !== null && display.selected >= 0 && (props.preparing || props.paused));
  const outgoingSelected = outgoing?.selectedIndex ?? null;
  React.useEffect(() => {
    if (!outgoing || outgoingSelected === null || outgoingSelected >= 0) return;
    let frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() => outgoing.displayCommitted(outgoingSelected,outgoingSelected));
    });
    return () => cancelAnimationFrame(frame);
  }, [outgoing,outgoingSelected]);
  React.useEffect(() => {
    if (display.session !== session || display.target === null) return;
    // Reveal the already-mounted next surface before releasing the outgoing player.
    // Two animation callbacks leave a frame opportunity after this React commit;
    // this is ordering protection, not a native presentation acknowledgement.
    let frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() => {
        session.displayCommitted(display.target, display.selected);
        if (!waitForSpeech && display.selected !== null && session.selectedIndex === display.selected) {
          callbacks.current.onDisplayCommitted?.(display.selected);
          retained.current?.close('replacement_surface_committed'); retained.current = null;
          update(n => n+1);
        }
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [session, display.session, display.target, display.selected, waitForSpeech]);
  const incoming = display.session === session ? display : {entries: [], selected: null};
  // Keep the same native view/key through the render preceding effect cleanup,
  // then through loading of the new scope. Only one outgoing surface is held.
  const selected = waitForSpeech ? null : incoming.selected;
  const layers = [...(outgoing ? outgoing.entries.map(entry => ({entry, owner:outgoing,
    shown:selected === null && entry.segment.index === outgoing.selectedIndex})) : []),
    ...incoming.entries.map(entry => ({entry,owner:session,shown:selected === entry.segment.index}))];
  const presentationReady=Boolean(!props.hidden && layers.some(({entry,shown})=>shown && !entry.retired && entry.player && entry.first));
  React.useEffect(()=>{ callbacks.current.onPresentationReadyChange?.(presentationReady); },[presentationReady]);
  React.useEffect(()=>()=>callbacks.current.onPresentationReadyChange?.(false),[]);
  const visibleOwner = props.hidden ? null : layers.find(layer => layer.shown)?.owner ?? null;
  React.useEffect(() => {
    callbacks.current.onPositionReader?.(() => visibleOwner?.idlePosition() ?? null);
    return () => callbacks.current.onPositionReader?.(null);
  },[visibleOwner,props.hidden,props.onPositionReader]);
  return <View onLayout={event => reportLayout('stage',event.nativeEvent.layout)} style={[styles.stage, props.expanded ? styles.expanded : styles.inline,props.presentationFill && styles.presentationFill, props.hidden && styles.hidden,props.overlay && styles.overlay]}>
    {layers.filter(({entry}) => entry.player && (!props.attachLocalVideo || entry.segment.index<0)).map(({entry,owner,shown}) => <VideoView
      key={`${owner.surfaceKey}:${entry.segment.index}`} player={entry.player!} nativeControls={false}
      contentFit="contain" allowsPictureInPicture={false}
      // Android-only prop: overlapping preloaded clips need normal view compositing.
      surfaceType="textureView"
      style={[styles.picture, {opacity: shown ? 1 : 0}]}
      onLayout={event => {
        if (shown) reportLayout(`native:${owner.surfaceKey}:${entry.segment.index}`,event.nativeEvent.layout);
        owner.surfaceLayout(entry.segment.index,event.nativeEvent.layout.width,event.nativeEvent.layout.height);
      }}
      onFirstFrameRender={() => owner.firstFrame(entry.segment.index)} />)}
    {props.showLabel !== false ? <Text style={styles.label}>{selected === null ? 'Idle fallback — no timely segment'
      : selected < 0 ? 'Source idle animation · silent video'
      : `Segment ${selected + 1} · silent video · presentation drift unmeasured`}</Text> : null}
  </View>;
}
const styles = StyleSheet.create({
  // Fully specify both modes so leaving fullscreen restores a nonzero surface
  // without replacing the native player or relying on removed flex properties.
  stage: {backgroundColor: '#101820'}, inline: {flex: 0, height: 280, minHeight: 280},
  expanded: {flex: 1, height: 'auto', minHeight: 0, backgroundColor:'#000'}, hidden:{position:'absolute',opacity:0,width:'100%',height:'100%'},
  presentationFill:{flex:1,height:'100%',minHeight:0,width:'100%'},
  overlay:{position:'absolute',width:'100%',height:'100%',backgroundColor:'transparent'},
  picture: {...StyleSheet.absoluteFillObject, width: '100%', height: '100%'},
  label: {color: '#fff', backgroundColor: '#101820cc', fontSize: 11},
});
