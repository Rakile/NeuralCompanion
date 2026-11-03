import {Platform} from 'react-native';
import {AudioModule} from 'expo-audio';

export type ManualDeparture={recordingId:string;revision:number;reason:'app_switch'|'locked'|'unknown';
  departed:boolean;stopped:boolean;uri:string|null;error:string|null};
export type ManualDeparturePermit={isCurrent():boolean;assertSend():void;markDispatched():void};
type Native={ncManualDepartureState?(id:string):ManualDeparture|null;
  ncManualDepartureClaim?(id:string,revision:number):boolean;
  ncManualDepartureCanSend?(id:string):boolean;ncManualDepartureRelease?(id:string):void;
  addListener?(name:string,listener:(value:ManualDeparture)=>void):{remove():void}};
const native=()=>Platform.OS==='android'?AudioModule as unknown as Native:undefined;
export const manualDeparture={
  begin(recorder:unknown,id:string){
    if(!native()?.ncManualDepartureState)return false;
    (recorder as {ncBeginManualRecording(id:string):void}).ncBeginManualRecording(id);return true;
  },
  state:(id:string)=>native()?.ncManualDepartureState?.(id)??null,
  claim:(id:string,revision:number)=>native()?.ncManualDepartureClaim?.(id,revision)===true,
  canSend:(id:string)=>native()?.ncManualDepartureCanSend?.(id)===true,
  release:(id:string)=>native()?.ncManualDepartureRelease?.(id),
  subscribe(listener:(value:ManualDeparture)=>void){return native()?.addListener?.('ncManualDeparture',listener)??{remove(){}};},
};
