import React from 'react';
import { recordPhoneDebug } from '../utils/phoneDebugBridge';

type AvailabilityEvidence = Partial<Record<'playerPresent'|'bufferedRuntimePresent'|'bufferedPresentationPresent'|'muxedSelected'|'demoMode'|'foreground'|'storyActive'|'nativePlayback'|'hqSelected'|'musetalkAvailable',boolean>>;
export type MuseTalkPresentationInput = { liveEnabled: boolean; museTalkSelected: boolean; available: boolean;
  retainSelectionWhileUnavailable?: boolean; owner?: object; diagnosticAvailability?:AvailabilityEvidence };
export type MuseTalkPresentationState = { fullscreen: boolean; entryActive: boolean };

function report(step:string,input:MuseTalkPresentationInput,state?:MuseTalkPresentationState):void {
  try{
    const evidence:AvailabilityEvidence={};
    for(const key of ['playerPresent','bufferedRuntimePresent','bufferedPresentationPresent','muxedSelected','demoMode','foreground','storyActive','nativePlayback','hqSelected','musetalkAvailable'] as const){
      const value=input.diagnosticAvailability?.[key];if(typeof value==='boolean')evidence[key]=value;
    }
    void recordPhoneDebug('info','musetalk_fullscreen_transaction',{step,liveEnabled:input.liveEnabled,
      museTalkSelected:input.museTalkSelected,available:input.available,
      retainSelectionWhileUnavailable:input.retainSelectionWhileUnavailable===true,...evidence,...state}).catch(()=>undefined);
  }catch{}
}

export function transitionMuseTalkLivePresentation(previous: MuseTalkPresentationState, input: MuseTalkPresentationInput): MuseTalkPresentationState {
  const entryActive = input.museTalkSelected && input.available;
  // Permission activities and player replacement affect media readiness, not
  // the user's selected view. This retains UI intent only, never a player grant.
  if (input.museTalkSelected && input.retainSelectionWhileUnavailable) return {...previous, entryActive};
  if (!entryActive) return { fullscreen: false, entryActive: false };
  return previous.entryActive ? { ...previous, entryActive } : { fullscreen: false, entryActive };
}

export function useMuseTalkLivePresentation(input: MuseTalkPresentationInput) {
  const inputRef = React.useRef(input); inputRef.current = input;
  const [state, setState] = React.useState(() => transitionMuseTalkLivePresentation({ fullscreen: false, entryActive: false }, input));
  const previous = React.useRef(input);
  React.useEffect(() => {
    const next = inputRef.current;
    const ownerChanged = previous.current.owner !== next.owner;
    const changed = ownerChanged || previous.current.retainSelectionWhileUnavailable !== next.retainSelectionWhileUnavailable
      || previous.current.liveEnabled !== next.liveEnabled || previous.current.museTalkSelected !== next.museTalkSelected || previous.current.available !== next.available;
    previous.current = next;
    if (changed) {
      report('eligibility_change',next);
      setState(value => transitionMuseTalkLivePresentation(ownerChanged ? {fullscreen:false,entryActive:false} : value, next));
    }
  }, [input.liveEnabled, input.museTalkSelected, input.available, input.retainSelectionWhileUnavailable, input.owner]);
  React.useEffect(()=>{report('state_observed',inputRef.current,state);},[state.fullscreen,state.entryActive]);
  const dismiss = React.useCallback(() => {
    report('dismiss_requested',inputRef.current);
    setState(value => ({ ...value, fullscreen: false }));
  }, []);
  const open = React.useCallback(() => {
    const value = inputRef.current;
    report('open_requested',value);
    if (value.museTalkSelected && value.available) setState(current => ({ ...current, fullscreen: true }));
  }, []);
  return { fullscreen: state.fullscreen, open, dismiss };
}
