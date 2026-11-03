import React from 'react';
import {AccessibilityInfo, Animated, Easing, StyleSheet, View} from 'react-native';
import {AppIcon} from '../app-shell/AppIcon';

/** Decorative only. Recording and submission remain owned by the shared recorder. */
export function FullscreenMicIndicator({recording}: {recording:boolean}) {
  const progress=React.useRef(new Animated.Value(0)).current;
  const [reduceMotion,setReduceMotion]=React.useState(true);
  React.useEffect(()=>{
    let active=true,changed=false;
    const subscription=AccessibilityInfo.addEventListener('reduceMotionChanged',value=>{
      changed=true;if(active)setReduceMotion(value);
    });
    void AccessibilityInfo.isReduceMotionEnabled().then(value=>{
      if(active&&!changed)setReduceMotion(value);
    }).catch(()=>{}); // Unknown preference stays static.
    return ()=>{active=false;subscription.remove();};
  },[]);
  React.useEffect(()=>{
    progress.setValue(0);
    if(!recording||reduceMotion)return;
    const animation=Animated.loop(Animated.timing(progress,{toValue:1,duration:1800,
      easing:Easing.linear,useNativeDriver:true,isInteraction:false}));
    animation.start();
    return ()=>{animation.stop();progress.setValue(0);};
  },[recording,reduceMotion,progress]);
  const moving=recording&&!reduceMotion;
  return <View pointerEvents="none" accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
    style={[styles.ring,recording&&styles.recordingRing]}>
    <Animated.View style={[styles.halo,recording&&styles.recordingHalo,moving&&{
      opacity:progress.interpolate({inputRange:[0,.5,1],outputRange:[.3,.8,.3]}),
      transform:[{scale:progress.interpolate({inputRange:[0,.5,1],outputRange:[1,1.12,1]})}],
    }]} />
    <Animated.View style={[styles.sweep,recording&&styles.recordingSweep,moving&&{
      transform:[{rotate:progress.interpolate({inputRange:[0,1],outputRange:['0deg','360deg']})}],
    }]} />
    <AppIcon name="voice" size={26} color={recording?'#ff526f':'#e7f7ff'} />
  </View>;
}

const styles=StyleSheet.create({
  ring:{width:44,height:44,borderRadius:22,borderWidth:1,borderColor:'rgba(55,214,255,0.55)',
    alignItems:'center',justifyContent:'center',backgroundColor:'#081e2d'},
  halo:{position:'absolute',top:-3,left:-3,right:-3,bottom:-3,borderRadius:25,
    borderWidth:3,borderColor:'rgba(42,204,255,0.14)'},
  sweep:{position:'absolute',top:-1,left:-1,right:-1,bottom:-1,borderRadius:22,borderWidth:2,
    borderColor:'transparent',borderTopColor:'#54ddff',borderRightColor:'#29b9e2'},
  recordingRing:{borderColor:'rgba(255,82,111,0.35)'},
  recordingHalo:{borderColor:'rgba(255,82,111,0.35)'},
  recordingSweep:{borderTopColor:'#ff526f',borderRightColor:'#ff9eac'},
});
