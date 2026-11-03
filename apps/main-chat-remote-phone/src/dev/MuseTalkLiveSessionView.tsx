import React from 'react';
import { Animated, Pressable, StyleSheet, View } from 'react-native';
import type { RemoteClient } from '../api/client';
import type { PlaybackState } from '../hooks/useAudioQueue';
import type { OptionalVisualStart } from '../utils/optionalVisualStart';
import type { AvatarPresentationSnapshot } from '../hooks/useAvatarPresentationTarget';
import { MuseTalkLiveSession } from './museTalkLiveSession';
import { MuseTalkLiveTrialView } from './MuseTalkLiveTrialView';
import { useMuseTalkLayoutDiagnostics } from './useMuseTalkLayoutDiagnostics';
import { useMuseTalkFullscreenZoom } from '../hooks/useMuseTalkFullscreenZoom';
import type { MuseTalkZoomGestures } from '../hooks/useMuseTalkFullscreenZoom';
import type { BufferedPlaybackRuntime } from '../native/bufferedPlaybackRuntime';
import type { BufferedPresentation } from '../native/bufferedPresentation';
import { useAVPresentation } from '../native/useAVPresentation';
import { useIdleLoopCache } from '../native/useIdleLoopCache';
import { useUncachedIdle } from '../native/useUncachedIdle';
import { MuxedLiveTrialView } from './MuxedLiveTrialView';
import type { MuxedTrialRuntime } from './muxedTrialRuntime';

export type MuseTalkLiveSessionViewProps = { client: RemoteClient; playback: PlaybackState; eligible: boolean; liveEnabled: boolean; fullscreen: boolean;
  onStartHandler: (handler: OptionalVisualStart | null) => void; onRenderingChange: (rendering: boolean) => void;
  invalidationRevision: number; foreground?: boolean;
  presentation?: AvatarPresentationSnapshot;
  buffered?: BufferedPlaybackRuntime; bufferedPresentation?: BufferedPresentation;
  muxed?:Pick<MuxedTrialRuntime,'player'>;
  onPresentationReadyChange: (ready:boolean) => void;
  fullscreenControls: (gestures: MuseTalkZoomGestures) => React.ReactNode; presenceFallback: React.ReactNode };

// The session and renderer stay mounted while only their shell layout changes.
let visualSequence = 0;
export function MuseTalkLiveSessionView(props: MuseTalkLiveSessionViewProps) {
  if (props.muxed || (props.fullscreen && (!props.buffered || !props.bufferedPresentation)))
    return <MuxedMuseTalkLiveSessionView {...props} />;
  // Selection is owned by the app's authenticated buffered lifetime, not RTP
  // negotiation. Never allocate a competing player while that owner is absent.
  if (!props.buffered || !props.bufferedPresentation) return null;
  return <LegacyMuseTalkLiveSessionView {...props} />;
}

function MuxedMuseTalkLiveSessionView(props:MuseTalkLiveSessionViewProps) {
  const zoom=useMuseTalkFullscreenZoom(props.fullscreen);
  const player=props.muxed?.player;
  const rendering=Boolean(player&&props.eligible&&props.foreground!==false);
  React.useEffect(()=>{props.onStartHandler(null);},[props.onStartHandler]);
  React.useEffect(()=>{props.onRenderingChange(rendering);},[rendering,props.onRenderingChange]);
  React.useEffect(()=>()=>props.onPresentationReadyChange(false),[props.muxed,props.onPresentationReadyChange]);
  const target=props.presentation?.target,bounds=props.presentation?.bounds??{x:0,y:0,width:1,height:1};
  const visible=rendering&&Boolean(props.presentation?.visible&&props.presentation.displayReady&&target);
  return <View onLayout={zoom.onLayout} pointerEvents={props.fullscreen||visible?'auto':'none'}
    style={[styles.host,props.fullscreen?styles.fullscreen:{left:bounds.x,top:bounds.y,width:bounds.width,height:bounds.height,
      borderRadius:target?.borderRadius??0,opacity:visible?1:0},!props.fullscreen&&styles.inline]}>
    <Animated.View style={[styles.viewport,props.fullscreen&&zoom.style]}>
      {rendering&&player?<MuxedLiveTrialView player={player} fallback={props.presenceFallback}
        hideFallbackWhenReady={props.fullscreen||target?.targetId==='companion'||target?.targetId==='portrait'}
        onReady={()=>props.onPresentationReadyChange(true)} />:props.presenceFallback}
    </Animated.View>
    {props.fullscreen?props.fullscreenControls(zoom.gestures):visible&&target?<View pointerEvents="box-none" style={styles.inlineControls}>
      {target.onLongPress?<Pressable accessibilityRole="button" accessibilityLabel={`${target.identity} avatar. Persona and model controls`}
        delayLongPress={450} onLongPress={target.onLongPress} style={styles.personaAction}/>:null}{target.overlay}
    </View>:null}
  </View>;
}

function LegacyMuseTalkLiveSessionView(props: MuseTalkLiveSessionViewProps) {
  const zoom = useMuseTalkFullscreenZoom(props.fullscreen);
  const client = React.useRef(props.client); client.current = props.client;
  const chunkMode=React.useRef(false);
  // The runtime is already scoped to the authenticated owner. A transient peer
  // replacement must update requests without destroying retained local video.
  const session = React.useMemo(() => {
    const current = new Proxy({} as RemoteClient,{get:(_target,key)=>{
      const value=Reflect.get(client.current,key);
      return typeof value==='function'?value.bind(client.current):value;
    }});
    return new MuseTalkLiveSession(current,{prepareReply:props.buffered?.prepareReply,idleChunks:()=>chunkMode.current});
  }, [props.buffered]);
  const NativeView = React.useMemo(() => (require('expo') as typeof import('expo'))
    .requireNativeView<import('react-native').ViewProps & {handle:string}>('ExpoAudio'),[]);
  // Retain frames between replies, never across revoked connection/owner scopes.
  const visualKey = React.useMemo(() => ++visualSequence, [session,props.invalidationRevision]);
  const [, revise] = React.useState(0);
  React.useEffect(() => () => session.close(), [session]);
  React.useEffect(() => session.subscribe(() => revise(value => value + 1)), [session]);
  // Backgrounding hides native surfaces, not the admitted audio reply. Real
  // route/engine/connection changes still revoke the session and its surfaces.
  const foreground = props.foreground !== false;
  const nativeEnabled=props.eligible&&foreground;
  const nativeHandle=useAVPresentation(props.bufferedPresentation??null,nativeEnabled,props.onPresentationReadyChange);
  const cacheEnabled=useIdleLoopCache(props.client,props.bufferedPresentation!,nativeEnabled,
    {freezeEnabled:true,revision:props.invalidationRevision});
  const chunkSupported=props.bufferedPresentation!.idleChunksSupported;
  chunkMode.current=cacheEnabled===false&&chunkSupported;
  useUncachedIdle(props.client,props.bufferedPresentation!,session,props.buffered!,nativeEnabled&&chunkMode.current);
  const eligible=props.eligible&&cacheEnabled!==null&&(cacheEnabled||chunkSupported);
  const previousInvalidation = React.useRef(props.invalidationRevision);
  React.useEffect(() => {
    const revisionChanged = previousInvalidation.current !== props.invalidationRevision;
    previousInvalidation.current = props.invalidationRevision;
    if (revisionChanged) {
      // setEligible(true) intentionally preserves an armed trial, so revoke
      // first when the connection/owner environment itself changed.
      session.setEligible(false, { invalidate: true });
      session.setEligible(eligible);
    } else session.setEligible(eligible, {
      invalidate: !props.eligible && props.liveEnabled && foreground,
      suspend: !foreground,
    });
  }, [session, eligible, props.eligible, props.liveEnabled, props.invalidationRevision,foreground]);
  const rendering = props.eligible || session.trial.busy;
  const beforeStart=React.useCallback<OptionalVisualStart>(async(chunk,signal,deadline)=>{
    await session.beforeStart(chunk,signal,deadline);
    if(!signal.aborted&&session.trial.snapshot.phase==='playing'&&session.trial.snapshot.chunk?.id===chunk.id)
      await props.buffered?.beforePlayback(chunk,signal);
  },[session,props.buffered]);
  const reportLayout = useMuseTalkLayoutDiagnostics({scope:'host',expanded:props.fullscreen,
    active:props.liveEnabled,rendering});
  React.useEffect(() => { props.onRenderingChange(rendering); }, [props.onRenderingChange, rendering]);
  const inlineVisible=rendering && Boolean(props.presentation?.visible && props.presentation.displayReady && props.presentation.target);
  const presentationBounds=props.presentation?.bounds ?? {x:0,y:0,width:1,height:1};
  const target=props.presentation?.target;
  const inlineStyle={left:presentationBounds.x,top:presentationBounds.y,width:presentationBounds.width,height:presentationBounds.height,
    borderRadius:target?.borderRadius ?? 0,opacity:inlineVisible ? 1 : 0};
  return <View onLayout={event => { zoom.onLayout(event); reportLayout('host',event.nativeEvent.layout); }}
    accessibilityElementsHidden={!props.fullscreen && !inlineVisible}
    importantForAccessibility={!props.fullscreen && !inlineVisible ? 'no-hide-descendants' : 'auto'}
    pointerEvents={props.fullscreen || inlineVisible ? 'auto' : 'none'}
    style={[styles.host, props.fullscreen ? styles.fullscreen : inlineStyle, !props.fullscreen && styles.inline]}>
    <Animated.View style={[styles.viewport,props.fullscreen && zoom.style]}>
    <MuseTalkLiveTrialView key={visualKey} client={props.client} owner="musetalk-live-session" playback={props.playback} active={rendering && foreground}
      buffered={props.buffered} nativePresentation
      allowed={rendering && foreground} trial={session.trial} sessionOwned beforeStart={beforeStart} onPrefetch={(chunk) => session.prefetch(chunk)}
      // Cached native idle can be displayed before any reply-player frame.
      // Its observed readiness must hide the trial's opaque portrait overlay.
      onStartHandler={props.onStartHandler} expanded={props.fullscreen} presentationFill showFallback={rendering && !props.presentation?.displayReady}
      presenceFallback={props.presenceFallback} />
    {nativeEnabled&&nativeHandle ? <NativeView handle={nativeHandle} style={StyleSheet.absoluteFill} /> : null}
    </Animated.View>
    {props.fullscreen ? props.fullscreenControls(zoom.gestures) : inlineVisible && target ? <View pointerEvents="box-none" style={styles.inlineControls}>
      {target.onLongPress ? <Pressable accessible accessibilityRole="button"
        accessibilityLabel={`${target.identity} avatar. Persona and model controls`}
        accessibilityHint="Long press to change persona or reply model" onAccessibilityTap={target.onLongPress}
        delayLongPress={450} onLongPress={target.onLongPress} style={styles.personaAction} /> : null}
      {target.overlay}
    </View> : null}
  </View>;
}

const styles = StyleSheet.create({
  host: { backgroundColor: '#000', position: 'absolute', overflow: 'hidden' }, inline: { overflow: 'hidden', zIndex: 100 },
  viewport: { flex: 1 },
  fullscreen: { ...StyleSheet.absoluteFillObject, zIndex: 2000, elevation: 30 },
  inlineControls: { ...StyleSheet.absoluteFillObject }, personaAction: { ...StyleSheet.absoluteFillObject },
});
