import React from 'react';
import {StyleSheet,View} from 'react-native';
import type {StyleProp,ViewStyle} from 'react-native';

import type {AvatarPresentationRegistry} from '../../hooks/useAvatarPresentationTarget';

type Props={
  presentationTarget?:AvatarPresentationRegistry;
  targetId:string;
  identity:string;
  borderRadius:number;
  onLongPress?:()=>void;
  overlay?:React.ReactNode;
  metadataRevision?:string|number;
  children:React.ReactNode;
  style?:StyleProp<ViewStyle>;
};

export function AvatarPresentationTarget({presentationTarget,targetId,identity,borderRadius,onLongPress,overlay,metadataRevision,children,style}:Props) {
  const targetRef=React.useRef<View|null>(null);
  const [,revise]=React.useState(0);
  const metadata=React.useRef({identity,borderRadius,onLongPress,overlay});
  metadata.current={identity,borderRadius,onLongPress,overlay};
  React.useEffect(()=>presentationTarget?.registerTarget({targetId,ref:targetRef,metadata}),[presentationTarget,targetId]);
  React.useEffect(()=>presentationTarget?.subscribe(()=>revise(value=>value+1)),[presentationTarget]);
  React.useEffect(()=>presentationTarget?.refreshTarget(targetId),
    [presentationTarget,targetId,identity,borderRadius,onLongPress,metadataRevision]);
  const presented=Boolean(presentationTarget?.isPresented(targetId));
  return <View ref={targetRef} onLayout={presentationTarget?.remeasure} style={[styles.target,style]}>
    <View accessibilityElementsHidden={presented} importantForAccessibility={presented?'no-hide-descendants':'auto'}
      style={[styles.fill,presented && styles.covered]}>{children}</View>
    {presented ? null : overlay}
  </View>;
}

const styles=StyleSheet.create({
  target:{position:'relative'},
  fill:{height:'100%',width:'100%'},
  covered:{opacity:0},
});
