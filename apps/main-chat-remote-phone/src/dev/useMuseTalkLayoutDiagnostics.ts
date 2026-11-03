import React from 'react';
import type { LayoutRectangle } from 'react-native';
import { recordPhoneDebug } from '../utils/phoneDebugBridge';

type LayoutState = {
  scope: 'host' | 'trial' | 'video';
  expanded: boolean;
  active?: boolean;
  rendering?: boolean;
  showRenderer?: boolean;
  showFallback?: boolean;
  hidden?: boolean;
  overlay?: boolean;
};

// Observe geometry only: never seek, resize, remount or read native players.
export function useMuseTalkLayoutDiagnostics(state: LayoutState) {
  const key = JSON.stringify(state);
  const audit = React.useMemo(() => ({state, count:0, layouts:new Map<string,string>()}), [key]);
  const alive = React.useRef(true);
  React.useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const report = React.useCallback((part: string, layout?: LayoutRectangle) => {
    if (!alive.current || audit.count >= 32) return;
    const geometry = layout ? {x:layout.x,y:layout.y,width:layout.width,height:layout.height} : {};
    if (Object.values(geometry).some(value => !Number.isFinite(value))) return;
    const signature = JSON.stringify(geometry);
    if (audit.layouts.get(part) === signature) return;
    audit.layouts.set(part,signature); audit.count++;
    try {
      void recordPhoneDebug('info','musetalk_presentation_layout',{
        ...audit.state,part,...geometry,atMs:performance.now(),presentationMeasured:false,
      }).catch(() => {});
    } catch { /* Diagnostics cannot affect avatar or audio playback. */ }
  }, [audit]);
  React.useEffect(() => { report('state'); }, [report]);
  return report;
}
