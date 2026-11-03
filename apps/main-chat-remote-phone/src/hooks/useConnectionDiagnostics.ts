import {useEffect} from 'react';
import {AppState, NativeModules} from 'react-native';
import * as Network from 'expo-network';
import {connectionTrace} from '../utils/connectionTrace';

export function useConnectionDiagnostics(): void {
  useEffect(() => {
    let alive = true, changed = false;
    let appState = AppState.currentState;
    let lastTick = performance.now(), stateSince = lastTick;
    let lastPower='', powerBusy=false;
    const power=async()=>{
      if(powerBusy || !NativeModules?.NcPhoneNativeAudio?.connectionPowerState) return;
      powerBusy=true;
      try {
        const value=await NativeModules.NcPhoneNativeAudio.connectionPowerState();
        const fields={power_save:Number(value.powerSave===true),device_idle:Number(value.deviceIdle===true),interactive:Number(value.interactive===true)};
        const key=JSON.stringify(fields);
        if(alive && key!==lastPower) {lastPower=key;connectionTrace.event('phone_power',fields);}
      } catch { /* Optional diagnostics on older APKs. */ }
      finally {powerBusy=false;}
    };
    void power();
    const powerTimer=setInterval(()=>{void power();},30000);
    connectionTrace.event('diagnostics_started', {phase:'peer_incidents_v4', state:appState});
    const sampleDelay = () => {
      if (!alive) return;
      const now = performance.now(), delay = Math.max(0, now-lastTick-5000);
      lastTick = now;
      if (delay >= 3000) connectionTrace.event('js_timer_delayed', {state:appState, delay_ms:delay}, true);
    };
    // Observe scheduling only: no wake lock, network probe or background keepalive.
    const timer = setInterval(sampleDelay, 5000);
    const lifecycle = AppState.addEventListener('change', state => {
      void power();
      sampleDelay();
      connectionTrace.event('phone_lifecycle_duration', {state:appState, phase:state,
        duration_ms:Math.max(0, performance.now()-stateSince)});
      appState = state; stateSince = performance.now();
    });
    let subscription: {remove(): void} | undefined;
    const record = (state: Network.NetworkState) => {
      if (!alive) return;
      connectionTrace.event('phone_network', {network_type:state.type,
        connected:state.isConnected === undefined ? undefined : Number(state.isConnected),
        reachable:state.isInternetReachable === undefined ? undefined : Number(state.isInternetReachable)},
      state.isConnected === false || state.isInternetReachable === false);
    };
    try {
      subscription = Network.addNetworkStateListener(state => { changed = true; record(state); });
      void Network.getNetworkStateAsync().then(state => { if (!changed) record(state); }).catch(() => {
        if (alive) connectionTrace.event('phone_network_unavailable');
      });
    } catch { connectionTrace.event('phone_network_unavailable'); }
    return () => { alive = false; clearInterval(timer);clearInterval(powerTimer);
      try { lifecycle.remove(); } catch { /* Observation only. */ }
      try { subscription?.remove(); } catch { /* Observation only. */ }
    };
  }, []);
}
