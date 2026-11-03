import React from 'react';
import type {ReactNode} from 'react';
import type {View} from 'react-native';

export type AvatarPresentationBounds = {x:number;y:number;width:number;height:number};
export type AvatarPresentationMetadata = {
  identity:string;
  borderRadius:number;
  onLongPress?:()=>void;
  overlay?:ReactNode;
};
export type AvatarPresentationTarget = AvatarPresentationMetadata & {
  targetId:string;
  bounds:AvatarPresentationBounds;
};
export type AvatarPresentationSnapshot = {
  bounds:AvatarPresentationBounds;
  displayReady:boolean;
  visible:boolean;
  target:AvatarPresentationTarget|null;
};

type Measurable = Pick<View,'measureInWindow'>;
type MetadataRef = {current:AvatarPresentationMetadata};
type Registration = {targetId:string;ref:{current:Measurable|null};metadata:MetadataRef;token:object};
export type AvatarPresentationTargetRegistration = Omit<Registration,'token'>;

export type AvatarPresentationRegistry = {
  getSnapshot:()=>AvatarPresentationSnapshot;
  isPresented:(targetId:string)=>boolean;
  refreshTarget:(targetId:string)=>void;
  registerTarget:(registration:AvatarPresentationTargetRegistration)=>(()=>void);
  remeasure:()=>void;
  setDisplayReady:(ready:boolean)=>void;
  setRoot:(node:Measurable|null)=>void;
  subscribe:(listener:()=>void)=>(()=>void);
};

const INITIAL_BOUNDS:AvatarPresentationBounds={x:0,y:0,width:1,height:1};
const finite=(value:number)=>Number.isFinite(value);

export function createAvatarPresentationRegistry():AvatarPresentationRegistry {
  let root:Measurable|null=null;
  let registration:Registration|null=null;
  let bounds=INITIAL_BOUNDS;
  let visible=false;
  let displayReady=false;
  let generation=0;
  const listeners=new Set<()=>void>();
  const notify=()=>listeners.forEach(listener=>listener());
  const snapshot=():AvatarPresentationSnapshot=>({
    bounds,
    displayReady,
    visible,
    target:registration ? {...registration.metadata.current,targetId:registration.targetId,bounds}:null,
  });
  const hide=()=>{ if (visible) { visible=false; notify(); } };
  const remeasure=()=>{
    const measurementGeneration=++generation;
    const measuredRegistration=registration;
    if (!root || !measuredRegistration?.ref.current) { hide(); return; }
    root.measureInWindow((rootX,rootY,rootWidth,rootHeight)=>{
      if (measurementGeneration!==generation || registration!==measuredRegistration) return;
      if (![rootX,rootY,rootWidth,rootHeight].every(finite) || rootWidth<=0 || rootHeight<=0) { hide(); return; }
      const node=measuredRegistration.ref.current;
      if (!node) { hide(); return; }
      node.measureInWindow((targetX,targetY,width,height)=>{
        if (measurementGeneration!==generation || registration!==measuredRegistration) return;
        if (![targetX,targetY,width,height].every(finite) || width<=0 || height<=0) { hide(); return; }
        bounds={x:targetX-rootX,y:targetY-rootY,width,height};
        visible=true;
        notify();
      });
    });
  };
  return {
    getSnapshot:snapshot,
    isPresented:targetId=>visible && displayReady && registration?.targetId===targetId,
    refreshTarget:targetId=>{ if (registration?.targetId===targetId) notify(); },
    registerTarget:value=>{
      const token={};
      registration={...value,token};
      visible=false;
      generation++;
      notify();
      remeasure();
      return ()=>{
        if (registration?.token!==token) return;
        registration=null;
        visible=false;
        generation++;
        notify();
      };
    },
    remeasure,
    setDisplayReady:ready=>{ if (displayReady!==ready) { displayReady=ready; notify(); } },
    setRoot:node=>{ root=node; generation++; if (!node) hide(); else remeasure(); },
    subscribe:listener=>{ listeners.add(listener); return ()=>listeners.delete(listener); },
  };
}

export function useAvatarPresentationTarget() {
  const registry=React.useMemo(()=>createAvatarPresentationRegistry(),[]);
  const [,revise]=React.useState(0);
  React.useEffect(()=>registry.subscribe(()=>revise(value=>value+1)),[registry]);
  const rootRef=React.useCallback((node:View|null)=>registry.setRoot(node),[registry]);
  return {rootRef,remeasure:registry.remeasure,setDisplayReady:registry.setDisplayReady,
    targetBinding:registry,presentation:registry.getSnapshot()};
}
