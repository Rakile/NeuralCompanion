import React from 'react';
import {StyleSheet, View} from 'react-native';
import {FullscreenFrameShimmer,FullscreenShimmerContext} from './FullscreenFrameShimmer';

/** Static translucent edge layers keep the cyan glow visible on Android too. */
export function FullscreenFrameGlow({radius=10,shimmer=false}: {radius?:number;shimmer?:boolean}) {
  const context=React.useContext(FullscreenShimmerContext);
  const id=React.useRef(Symbol()).current;
  const [size,setSize]=React.useState({width:0,height:0});
  const register=context?.register;
  React.useEffect(()=>{
    if(shimmer&&size.width>0&&size.height>0)return register?.(id);
  },[shimmer,size.width,size.height,register,id]);
  return <View pointerEvents="none" accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={StyleSheet.absoluteFill}
    onLayout={shimmer?event=>{const {width,height}=event.nativeEvent.layout;
      setSize(old=>old.width===width&&old.height===height?old:{width,height});}:undefined}>
    <View style={[styles.outer,{borderRadius:radius+4}]} />
    <View style={[styles.middle,{borderRadius:radius+2}]} />
    <View style={[styles.inner,{borderRadius:radius+1}]} />
    <View style={[styles.core,{borderRadius:radius+1}]} />
    {shimmer&&context?.active===id&&size.width>0&&size.height>0?<FullscreenFrameShimmer
      width={size.width} height={size.height} radius={radius} progress={context.progress}/>:null}
  </View>;
}

const styles=StyleSheet.create({
  outer:{position:'absolute',top:-4,left:-4,right:-4,bottom:-4,borderWidth:6,borderColor:'rgba(18,196,255,0.06)'},
  middle:{position:'absolute',top:-2,left:-2,right:-2,bottom:-2,borderWidth:4,borderColor:'rgba(30,208,255,0.14)'},
  inner:{position:'absolute',top:-1,left:-1,right:-1,bottom:-1,borderWidth:3,borderColor:'rgba(62,222,255,0.3)'},
  core:{position:'absolute',top:-1,left:-1,right:-1,bottom:-1,borderWidth:1,borderColor:'rgba(131,240,255,0.9)'},
});
