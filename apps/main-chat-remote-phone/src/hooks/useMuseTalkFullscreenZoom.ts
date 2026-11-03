import React from 'react';
import {Animated} from 'react-native';
import type {LayoutChangeEvent} from 'react-native';
import type {TwoTouchMetrics} from '../utils/liveFullscreenTransform';

export type MuseTalkZoomGestures = {
  onTransformStart: (metrics: TwoTouchMetrics) => void;
  onTransformPreview: (metrics: TwoTouchMetrics) => void;
  onTransformCommit: () => void;
};
type Position = {scale: number; x: number; y: number};
const fitted = (): Position => ({scale:1,x:0,y:0});
const valid = (m: TwoTouchMetrics) => [m.distance,m.midpointX,m.midpointY].every(Number.isFinite) && m.distance > 0;
const clamp = (n: number, limit: number) => Math.max(-limit,Math.min(limit,n));

// Animated values update the presentation container without rerendering the
// player/session on every gesture event. No playback clock or media is touched.
export function useMuseTalkFullscreenZoom(fullscreen: boolean) {
  const enabled = React.useRef(fullscreen); enabled.current=fullscreen;
  const bounds = React.useRef({width:0,height:0});
  const position = React.useRef(fitted());
  const start = React.useRef<{metrics:TwoTouchMetrics; position:Position} | null>(null);
  const values = React.useMemo(()=>({x:new Animated.Value(0),y:new Animated.Value(0),scale:new Animated.Value(1)}),[]);
  const apply = React.useCallback((next: Position) => {
    const scale=Math.max(1,Math.min(3,next.scale));
    const x=clamp(next.x,(scale-1)*bounds.current.width/2);
    const y=clamp(next.y,(scale-1)*bounds.current.height/2);
    position.current={scale,x,y};
    values.x.setValue(x); values.y.setValue(y); values.scale.setValue(scale);
  },[values]);
  React.useEffect(()=>{
    if (!fullscreen) { start.current=null; apply(fitted()); }
  },[fullscreen,apply]);
  const onLayout=React.useCallback((event: LayoutChangeEvent)=>{
    const {width,height}=event.nativeEvent.layout;
    if (![width,height].every(Number.isFinite) || width<=0 || height<=0) return;
    bounds.current={width,height};
    start.current=null;
    apply(position.current);
  },[apply]);
  const gestures=React.useMemo<MuseTalkZoomGestures>(()=>({
    onTransformStart: metrics=>{
      start.current=enabled.current && valid(metrics) && bounds.current.width>0 && bounds.current.height>0
        ? {metrics,position:{...position.current}} : null;
    },
    onTransformPreview: metrics=>{
      const initial=start.current;
      if (!enabled.current || !initial || !valid(metrics)) return;
      apply({scale:initial.position.scale*metrics.distance/initial.metrics.distance,
        x:initial.position.x+metrics.midpointX-initial.metrics.midpointX,
        y:initial.position.y+metrics.midpointY-initial.metrics.midpointY});
    },
    onTransformCommit: ()=>{ start.current=null; },
  }),[apply]);
  const style=React.useMemo(()=>({transform:[{translateX:values.x},{translateY:values.y},{scale:values.scale}]}),[values]);
  return {style,gestures,onLayout};
}
