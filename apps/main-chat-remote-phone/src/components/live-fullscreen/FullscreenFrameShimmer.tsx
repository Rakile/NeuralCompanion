import React from 'react';
import {AccessibilityInfo, Animated, AppState, Easing, Platform, StyleSheet, View, type ViewProps} from 'react-native';

type ShimmerContext={active:symbol|null;progress:Animated.Value;register:(id:symbol)=>()=>void};
const SWEEP_DURATION_MS=Platform?.OS==='android'?Math.round(2400/1.7):2400/1.25;
export const FullscreenShimmerContext=React.createContext<ShimmerContext|null>(null);

/** One timer for the open card; no JS frame loop and no playback dependencies. */
export function FullscreenShimmerScope({enabled,children}:{enabled:boolean;children:React.ReactNode}) {
  const [reduceMotion,setReduceMotion]=React.useState(true);
  const [foreground,setForeground]=React.useState(AppState.currentState==='active');
  const [active,setActive]=React.useState<symbol|null>(null);
  const progress=React.useRef(new Animated.Value(0)).current;
  const candidates=React.useRef(new Set<symbol>());
  const selected=React.useRef<symbol|null>(null),last=React.useRef<symbol|null>(null);
  const scheduler=React.useRef<((afterPass?:boolean)=>void)|null>(null);
  const allowed=enabled&&!reduceMotion&&foreground;
  React.useEffect(()=>{
    let alive=true,changed=false;
    const motion=AccessibilityInfo.addEventListener('reduceMotionChanged',value=>{
      changed=true;if(alive)setReduceMotion(value);
    });
    const app=AppState.addEventListener('change',state=>{if(alive)setForeground(state==='active');});
    void AccessibilityInfo.isReduceMotionEnabled().then(value=>{
      if(alive&&!changed)setReduceMotion(value);
    }).catch(()=>{});
    return ()=>{alive=false;motion.remove();app.remove();};
  },[]);
  const register=React.useCallback((id:symbol)=>{
    candidates.current.add(id);
    return ()=>{
      candidates.current.delete(id);
      if(selected.current===id){selected.current=null;setActive(null);scheduler.current?.();}
    };
  },[]);
  React.useEffect(()=>{
    selected.current=null;setActive(null);
    if(!allowed)return;
    let alive=true,timer:ReturnType<typeof setTimeout>|undefined;
    const schedule=(afterPass=false)=>{
      if(!alive)return;
      clearTimeout(timer);
      timer=setTimeout(()=>{
        if(!alive)return;
        const available=[...candidates.current];
        const choices=available.length>1?available.filter(id=>id!==last.current):available;
        if(!choices.length){schedule();return;}
        const id=choices[Math.floor(Math.random()*choices.length)]!;
        selected.current=id;last.current=id;setActive(id);
      },5000+Math.floor(Math.random()*5001)-(afterPass?SWEEP_DURATION_MS:0));
    };
    scheduler.current=schedule;schedule();
    return ()=>{alive=false;clearTimeout(timer);scheduler.current=null;selected.current=null;setActive(null);};
  },[allowed]);
  React.useEffect(()=>{
    if(!allowed||active===null)return;
    let alive=true;
    const finish=()=>{
      if(!alive)return;
      selected.current=null;setActive(null);scheduler.current?.(true);
    };
    if(Platform?.OS==='android'){
      // The native view animates itself. An unbound Animated.Value may never
      // complete on a fresh Fabric surface; only time the mounted pass here.
      const timer=setTimeout(finish,SWEEP_DURATION_MS);
      return ()=>{alive=false;clearTimeout(timer);};
    }
    progress.setValue(0);
    const animation=Animated.timing(progress,{toValue:1,duration:SWEEP_DURATION_MS,
      easing:Easing.linear,useNativeDriver:true,isInteraction:false});
    animation.start(({finished})=>{
      if(!alive||!finished)return;
      finish();
    });
    return ()=>{alive=false;animation.stop();};
  },[active,allowed,progress]);
  const value=React.useMemo(()=>({active:allowed?active:null,progress,register}),[allowed,active,progress,register]);
  return <FullscreenShimmerContext.Provider value={value}>{children}</FullscreenShimmerContext.Provider>;
}

const breathInput=Array.from({length:33},(_,i)=>i/32);

/** Static thin strokes on the rounded frame; only luminance animates natively. */
export function risingFrameStrokes(width:number,height:number,radius:number) {
  const w=Math.max(0,width-2),h=Math.max(0,height-2);
  const r=Math.max(0,Math.min(radius-1,w/2,h/2));
  const lengths=[w-2*r,Math.PI*r/2,h-2*r,Math.PI*r/2,w-2*r,Math.PI*r/2,h-2*r,Math.PI*r/2];
  const perimeter=lengths.reduce((a,b)=>a+b,0);
  const points=Array.from({length:129},(_,i)=>{
    let d=i/128*perimeter,k=0;
    while(k<7&&d>=lengths[k]!){d-=lengths[k]!;k++;}
    const a=(lengths[k]?d/lengths[k]!:0)*Math.PI/2;
    let x=0,y=0;
    switch(k){
      case 0:x=r+d;break;
      case 1:x=w-r+r*Math.sin(a);y=r-r*Math.cos(a);break;
      case 2:x=w;y=r+d;break;
      case 3:x=w-r+r*Math.cos(a);y=h-r+r*Math.sin(a);break;
      case 4:x=w-r-d;y=h;break;
      case 5:x=r-r*Math.sin(a);y=h-r+r*Math.cos(a);break;
      case 6:y=h-r-d;break;
      case 7:x=r-r*Math.cos(a);y=r-r*Math.sin(a);break;
    }
    return {x:x+1,y:y+1};
  });
  return points.slice(0,-1).map((p,i)=>{
    const end=points[i+1]!,dx=end.x-p.x,dy=end.y-p.y;
    const x=(p.x+end.x)/2,y=(p.y+end.y)/2,length=Math.hypot(dx,dy)+.5;
    return {x,y,length,angle:`${Math.atan2(dy,dx)*180/Math.PI}deg`,
      // 19C preview: center rises from 1.5h to -0.5h; soft half-width 55/64h.
      opacity:breathInput.map(t=>Math.max(0,1-Math.abs(y-(1.5-2*t)*height)/(height*55/64))
        *Math.max(0,Math.min(1,t*8,(1-t)*8)))};
  });
}

/** Android: selected 15E halo crescent. Other platforms retain the earlier rising breath. */
export function FullscreenFrameShimmer({width,height,radius,progress}:{width:number;height:number;radius:number;progress:Animated.Value}) {
  const NativeFrame=React.useMemo(()=>Platform?.OS==='android'
    ? (require('expo') as typeof import('expo')).requireNativeView<ViewProps&{cornerRadius:number;durationMs:number}>('NCFrameShimmer') : null,[]);
  const strokes=React.useMemo(()=>NativeFrame?[]:risingFrameStrokes(width,height,radius),[NativeFrame,width,height,radius]);
  if(NativeFrame)return <NativeFrame pointerEvents="none" cornerRadius={radius} durationMs={SWEEP_DURATION_MS}
    style={{position:'absolute',top:-6,bottom:-6,left:-6,right:-6}}/>;
  return <View pointerEvents="none" style={StyleSheet.absoluteFill}>
    <Animated.View style={[styles.halo,{borderRadius:radius+2,opacity:progress.interpolate({
      inputRange:breathInput,outputRange:breathInput.map(t=>.15*Math.pow(Math.sin(Math.PI*t),2)),
    })}]}/>
    {strokes.map((s,index)=><Animated.View key={index} style={[styles.stroke,{
      left:s.x-s.length/2,top:s.y-3,width:s.length,transform:[{rotate:s.angle}],
      opacity:progress.interpolate({inputRange:breathInput,outputRange:s.opacity}),
    }]}><View style={styles.core}/></Animated.View>)}
  </View>;
}
const styles=StyleSheet.create({
  halo:{position:'absolute',top:-2,left:-2,right:-2,bottom:-2,borderWidth:5,borderColor:'#58ddff'},
  stroke:{position:'absolute',height:6,justifyContent:'center'},
  core:{height:2.5,width:'100%',borderRadius:1.25,backgroundColor:'#efffff'},
});
