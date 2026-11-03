import React from 'react';
import type { AVRemoteOutput } from '../relay/av';
import type { AVObservation } from '../relay/av';
import { recordPhoneDebug } from '../utils/phoneDebugBridge';

/** Presentation lifecycle only. Native output owns audio timing and receipts. */
type PresentationOutput=Pick<AVRemoteOutput,'nativeHandle'|'visible'|'present'|'presentationActive'>
  & Partial<Pick<AVRemoteOutput,'report'>>;
export function useAVPresentation(output: PresentationOutput | null, enabled: boolean, report: (ready: boolean) => void): string {
  const [handle, setHandle] = React.useState('');
  React.useEffect(() => {
    let active = true, busy = false, admittedHandle = '', renewed = 0, retryAt = 0;
    let observedHandle: string | null = null, observedVisible: boolean | null = null, handleRevision = 0, sampledAt = 0;
    const observe = (phase: Parameters<AVObservation>[0]) => {
      // Transition/5s snapshots only. No native handle, media ID, URL or content.
      try {
        sampledAt = Date.now();
        output?.report?.(phase);
        void recordPhoneDebug('info', 'av_surface_state', { phase, enabled,
          handle_revision: handleRevision, handle_present: Boolean(output?.nativeHandle),
          visible: observedVisible, presentation_active: output?.presentationActive === true }).catch(() => undefined);
      } catch { /* Diagnostics cannot affect presentation or ownership. */ }
    };
    report(false); setHandle('');
    if (!output || !enabled) {
      if (output) void output.present(false).catch(() => undefined);
      return;
    }
    const tick = async () => {
      if (!active || busy) return;
      setHandle(output.nativeHandle);
      const visible = output.visible;
      report(visible);
      if (observedHandle !== output.nativeHandle) {
        observedHandle = output.nativeHandle; ++handleRevision; observe('visual_handle_changed');
      }
      if (observedVisible !== visible) {
        observedVisible = visible; observe(visible ? 'visual_visible' : 'visual_hidden');
      } else if (Date.now() - sampledAt >= 5000) observe('visual_sample');
      if (Date.now() < retryAt) return;
      if (admittedHandle && admittedHandle === output.nativeHandle && Date.now() - renewed < 300_000) return;
      busy = true;
      try {
        await output.present(true);
        if (!active) return;
        admittedHandle = output.nativeHandle; renewed = Date.now();
        setHandle(admittedHandle); report(output.visible);
      } catch {
        if (active) { report(false); observe('visual_error'); retryAt = Date.now() + 1000; }
      } finally { busy = false; }
    };
    void tick();
    const timer = setInterval(() => { void tick(); }, 100);
    return () => {
      active = false; clearInterval(timer); report(false);
      observe('visual_disabled');
      void output.present(false).catch(() => undefined);
    };
  }, [output, enabled, report]);
  return handle;
}
