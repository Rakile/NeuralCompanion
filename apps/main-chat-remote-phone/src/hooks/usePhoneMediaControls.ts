import { useEffect, useRef } from 'react';
import { requireOptionalNativeModule } from 'expo';

export type PhoneMediaCommand = 'play' | 'pause' | 'toggle' | 'next' | 'stop' | 'regenerate' | 'force_continue' | 'auto_toggle';
export type PhoneNotification = {
  title:string; subtitle:string; artwork:string;
  canRegenerate:boolean; canForce:boolean; canAuto:boolean; autoOn:boolean;
  buffering?:boolean;
};
type MediaBridge = {
  configureReplyMediaControls?(scope: string | null, playing: boolean, nextToggles: boolean): Promise<void>;
  configureReplyNotification?(scope:string|null, playing:boolean, nextToggles:boolean, info:PhoneNotification):Promise<void>;
  addListener(event: string, listener: (event: { scope: string; command: PhoneMediaCommand }) => void): {remove(): void};
};
const bridge = requireOptionalNativeModule<MediaBridge>('NcLiveCapture');

/** One reply-level media session, independent of short-lived TTS chunk players. */
export function usePhoneMediaControls(scope: string | null, playing: boolean, nextToggles: boolean,
  dispatch: (command: PhoneMediaCommand) => Promise<void>, onError: (message: string) => void, info?:PhoneNotification) {
  const current = useRef({scope, dispatch, onError});
  const inFlight = useRef<string|null>(null);
  current.current = {scope, dispatch, onError};
  useEffect(() => {
    if (!bridge?.configureReplyMediaControls) return;
    const subscription = bridge.addListener('replyMediaCommand', event => {
      const owner = current.current;
      if (!owner.scope || event.scope !== owner.scope || inFlight.current !== null) return;
      inFlight.current = owner.scope;
      void Promise.resolve().then(()=>{
        if(current.current.scope === owner.scope) return owner.dispatch(event.command);
      }).catch(error => {
        if (current.current.scope === owner.scope) owner.onError(error instanceof Error ? error.message : 'Playback command failed.');
      }).finally(()=>{if(inFlight.current===owner.scope)inFlight.current=null;});
    });
    return () => { subscription.remove(); void bridge.configureReplyMediaControls?.(null, false, false); };
  }, []);
  useEffect(() => {
    const update = info && bridge?.configureReplyNotification
      ? bridge.configureReplyNotification(scope, playing, nextToggles, info)
      : bridge?.configureReplyMediaControls?.(scope, playing, nextToggles);
    void update?.catch(error => {
      if (scope && current.current.scope === scope) onError(error instanceof Error ? error.message : 'Headphone controls unavailable.');
    });
  }, [scope, playing, nextToggles, info?.title, info?.subtitle, info?.artwork,
    info?.canRegenerate, info?.canForce, info?.canAuto, info?.autoOn, info?.buffering]);
}
