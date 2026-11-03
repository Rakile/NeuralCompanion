import React from 'react';
import { setBackgroundInterval as setInterval, clearBackgroundTimer as clearInterval } from '../utils/backgroundClock';
import * as Crypto from 'expo-crypto';
import type { RemoteClient } from '../api/client';
import type { ContinuousState, PhoneReplyAuth } from '../api/types';
import { recordPhoneDebug } from '../utils/phoneDebug';

const traceContinuous = (phase:string, details:Record<string,unknown>={}) => {
  void recordPhoneDebug('info','continuous_phone_stage',{phase,...details});
};

const futureReplyTextSettings = new Set(['default_reply','guidance','use_premade','guidance_preset','guidance_strength']);
const preservesCurrentReply = (kind:string, data:Record<string,unknown>) => {
  if ((kind==='pause' || kind==='resume') && data.preserve_user_speech===true) return true;
  const settings=data.settings;
  return kind==='settings' && !!settings && typeof settings==='object' && !Array.isArray(settings)
    && Object.keys(settings).length>0 && Object.keys(settings).every(key=>futureReplyTextSettings.has(key));
};

export function useContinuousConversation(options: {
  client: RemoteClient; owner: object; enabled: boolean; canClaim: boolean;
  canReadUser?: boolean;
  readUser?: (speech:NonNullable<ContinuousState['user_speech']>, signal:AbortSignal)=>Promise<void>;
  auth: () => Promise<PhoneReplyAuth>; claim: (id: string) => Promise<unknown>;
}) {
  const latest = React.useRef(options); latest.current = options;
  const [state,setState] = React.useState<ContinuousState | null>(null);
  const [error,setError] = React.useState('');
  const [busy,setBusy] = React.useState(false);
  const [readingUser,setReadingUser] = React.useState(false);
  const reader = React.useRef<{id:string;text:string;voiceId:string;owner:object;abort:AbortController}|null>(null);
  const automatedTurn = React.useRef<{id:string;owner:object;waiters:{resolve:()=>void;reject:(error:Error)=>void}[]}|null>(null);
  const settleAutomatedTurn=(turn:NonNullable<typeof automatedTurn.current>,error?:Error)=>{
    if(automatedTurn.current!==turn)return;
    automatedTurn.current=null;
    for(const waiter of turn.waiters) error?waiter.reject(error):waiter.resolve();
  };
  const cancelReading=()=>{
    reader.current?.abort.abort();reader.current=null;setReadingUser(false);
    if(automatedTurn.current)settleAutomatedTurn(automatedTurn.current,new Error('Automated reply stopped. Your message was not sent.'));
  };
  const stateRef = React.useRef(state); stateRef.current = state;
  const ownerRef = React.useRef(options.owner); ownerRef.current = options.owner;
  const handled = React.useRef(new Set<string>());
  const commandBusy = React.useRef(false);
  const commandRevision = React.useRef(0);
  const replyRevision = React.useRef(0);
  const manualInputs = React.useRef(0);
  const manualRevision = React.useRef(0);
  React.useEffect(()=>{
    let active=true, polling=false, claiming=false;
    const owner = options.owner;
    const current=()=>active && ownerRef.current===owner;
    handled.current.clear(); setState(null); setError('');
    const poll=async()=>{
      if (!current() || polling || commandBusy.current || !latest.current.enabled) return;
      const beforeCommand=commandRevision.current;
       const beforeReply=replyRevision.current;
      const beforeManual=manualRevision.current;
      polling=true;
      try {
        const opts=latest.current, auth=await opts.auth();
        if (!current()) return;
        const next=await opts.client.continuousStatus(auth);
        if (!current() || beforeCommand!==commandRevision.current || beforeManual!==manualRevision.current || commandBusy.current) return;
        if (stateRef.current?.state!==next.state || stateRef.current?.prepared_id!==next.prepared_id) {
          traceContinuous('status',{state:next.state,revision:next.revision,operation_id:next.prepared_id||''});
        }
        stateRef.current=next; setState(next);
        if(reader.current && (!next.owned || !['ready','paused'].includes(next.state) || next.prepared_id!==reader.current.id
          || next.user_speech?.text!==reader.current.text || next.user_speech.voice_id!==reader.current.voiceId)) cancelReading();
        if (next.state==='suspended' && next.owned && latest.current.enabled && latest.current.canClaim && !manualInputs.current) {
          traceContinuous('resume_requested',{revision:next.revision});
          const resumed=await opts.client.continuousCommand(auth,{kind:'resume',revision:next.revision,operation_id:Crypto.randomUUID()});
          if(current() && beforeCommand===commandRevision.current && beforeManual===manualRevision.current) {
            stateRef.current=resumed;setState(resumed);
            traceContinuous('resumed',{state:resumed.state,revision:resumed.revision});
          }
          return;
        }
        if (!latest.current.canClaim && latest.current.enabled && next.owned && !['stopped','paused','suspended'].includes(next.state)) {
          const paused=await opts.client.continuousCommand(auth,{kind:'pause',revision:next.revision,operation_id:Crypto.randomUUID()});
          if(current()) {stateRef.current=paused;setState(paused);}
          return;
        }
        if (next.prepared_id && next.owned && next.state==='ready' && latest.current.canClaim && latest.current.enabled && !manualInputs.current && !claiming && !commandBusy.current && !handled.current.has(next.prepared_id)) {
          const id=next.prepared_id;
          claiming=true; handled.current.add(id);
          if (handled.current.size>512) handled.current.delete(handled.current.values().next().value!);
          const abort=new AbortController();
          const turn={id,owner,waiters:[] as {resolve:()=>void;reject:(error:Error)=>void}[]};
          automatedTurn.current=turn;
          if(next.user_speech) {reader.current={id,text:next.user_speech.text,voiceId:next.user_speech.voice_id,owner,abort};setReadingUser(true);}
          traceContinuous(next.user_speech?'speech_started':'claim_ready',{operation_id:id,revision:next.revision});
          void (async()=>{
            let accepted=false;
            let stage='speech';
            try {
              if(next.user_speech) {
                if(!opts.readUser || latest.current.canReadUser===false) {
                  stage='audio_busy';
                  throw new Error('User speech is unavailable or other audio is playing.');
                }
                await opts.readUser(next.user_speech,abort.signal);
                traceContinuous('speech_played',{operation_id:id});
                if(abort.signal.aborted || !current() || !latest.current.enabled || !latest.current.canClaim || manualInputs.current) return;
                // Revalidate after speech: never submit an old prepared reply.
                const fresh=await opts.client.continuousStatus(await opts.auth());
                if(abort.signal.aborted || !current() || !latest.current.enabled || !latest.current.canClaim || manualInputs.current ||
                  !fresh.owned || fresh.state!=='ready' || fresh.prepared_id!==id
                  || fresh.user_speech?.text!==next.user_speech.text || fresh.user_speech.voice_id!==next.user_speech.voice_id) return;
              }
              // Retire the speech reader before the desktop claim changes status
              // to waiting; polling must not mistake that handoff for a cancelled read.
              if(reader.current?.abort===abort) {reader.current=null;setReadingUser(false);}
              if(manualInputs.current || beforeReply!==replyRevision.current || beforeManual!==manualRevision.current) return;
              stage='claim';
              traceContinuous('claim_started',{operation_id:id});
              await opts.claim(id);
              accepted=true;
              traceContinuous('claim_accepted',{operation_id:id});
            } catch(failure) {
              // A settings save can retire an unspoken draft while its start
              // request is in flight. That is replacement, not a playback fault.
              if(current() && beforeCommand!==commandRevision.current) {
                try {
                  const fresh=await opts.client.continuousStatus(await opts.auth());
                  if(!fresh.owned || fresh.prepared_id!==id)return;
                } catch { /* Keep the normal failure handling when status is unknown. */ }
              }
              const cancelled=abort.signal.aborted || !current() || beforeReply!==replyRevision.current || beforeManual!==manualRevision.current;
              traceContinuous(cancelled?'speech_cancelled':'claim_or_speech_failed',{
                operation_id:id,stage,error_type:failure instanceof Error?failure.name:'Unknown'});
              settleAutomatedTurn(turn,new Error('Automated reply did not finish. Your message was not sent.'));
              if(current() && !abort.signal.aborted) {
                setError(failure instanceof Error?failure.message:'Automatic reply failed.');
                if(next.user_speech) {
                  try {
                    const paused=await opts.client.continuousCommand(await opts.auth(),{kind:'pause',revision:next.revision,operation_id:Crypto.randomUUID()});
                    if(current()) {stateRef.current=paused;setState(paused);}
                  } catch { /* Host heartbeat pauses when disconnected. */ }
                }
              }
            } finally {
              if(reader.current?.abort===abort) {reader.current=null;if(current())setReadingUser(false);}
              settleAutomatedTurn(turn,accepted?undefined:new Error('Automated reply did not finish. Your message was not sent.'));
              claiming=false;
            }
          })();
        }
      } catch(failure) {if(!current() || beforeCommand!==commandRevision.current || beforeManual!==manualRevision.current)return;cancelReading();if(current()) setError(failure instanceof Error?failure.message:'Continuous Mode unavailable.');}
      finally {polling=false;}
    };
    if (options.enabled) {void poll();}
    const timer=setInterval(()=>{void poll();},1000);
    return ()=>{active=false;cancelReading();clearInterval(timer);};
  },[options.owner,options.enabled]);

  // Transport loss/backgrounding suspends the host run through its heartbeat.
  // Only competing foreground voice activity requests a user-visible pause.
  React.useEffect(()=>{
    if (options.enabled && options.canClaim) return;
    cancelReading();
    const previous=stateRef.current, opts=latest.current;
    if (options.enabled && previous?.owned && !['stopped','paused','suspended'].includes(previous.state)) {
      void opts.auth().then(auth=>opts.client.continuousCommand(auth,{kind:'pause',revision:previous.revision,
        operation_id:Crypto.randomUUID()})).catch(()=>undefined);
    }
  },[options.enabled,options.canClaim]);

  React.useEffect(()=>{
    if(options.canReadUser===false && reader.current) {
      cancelReading();
      const opts=latest.current, previous=stateRef.current;
      if(previous?.owned) void opts.auth().then(auth=>opts.client.continuousCommand(auth,
        {kind:'pause',revision:previous.revision,operation_id:Crypto.randomUUID()})).catch(()=>undefined);
    }
  },[options.canReadUser]);

  const command=async(kind:string, data:Record<string,unknown>={})=>{
    const opts=latest.current, owner=opts.owner, previous=stateRef.current;
    if (!opts.enabled || !previous) throw new Error('Connect before changing Continuous Mode.');
    if (commandBusy.current && !['pause','stop'].includes(kind)) throw new Error('A change is still being saved.');
    const keepCurrent=preservesCurrentReply(kind,data);
    if(!keepCurrent){cancelReading();replyRevision.current++;}
    const revision=++commandRevision.current;
    commandBusy.current=true;setBusy(true);setError('');
    try {
      const auth=await opts.auth();
      if(ownerRef.current!==owner) throw new Error('Connection changed.');
      if(revision!==commandRevision.current) throw new Error('Command superseded by a newer control action.');
      const next=await opts.client.continuousCommand(auth,{...data,kind,revision:previous.revision,operation_id:Crypto.randomUUID()});
      if(ownerRef.current===owner && revision===commandRevision.current) {
        if(keepCurrent && reader.current && reader.current.id!==next.prepared_id)cancelReading();
        stateRef.current=next;setState(next);
      }
    } catch(failure) {
      if(ownerRef.current===owner && revision===commandRevision.current) setError(failure instanceof Error?failure.message:'Change was not accepted.');
      throw failure;
    } finally {if(revision===commandRevision.current){commandBusy.current=false;if(ownerRef.current===owner)setBusy(false);}}
  };
  const userSpeechText=readingUser && options.enabled && options.canClaim && reader.current?.owner===options.owner
    ? reader.current.text : '';
  const withManualInput=async(operation:()=>Promise<unknown>, options:{afterAutomatedUser?:boolean}={})=>{
    if(options.afterAutomatedUser && automatedTurn.current){
      const turn=automatedTurn.current;
      if(turn.waiters.length)throw new Error('A message is already waiting for the automated reply.');
      traceContinuous('manual_input_queued',{operation_id:turn.id});
      await new Promise<void>((resolve,reject)=>turn.waiters.push({resolve,reject}));
      if(ownerRef.current!==turn.owner || !latest.current.enabled)
        throw new Error('Connection changed. Your queued message was not sent.');
    }
    manualInputs.current++;
    manualRevision.current++;
    cancelReading();
    traceContinuous('manual_input_started');
    try {await operation();}
    finally {manualInputs.current--;manualRevision.current++;traceContinuous('manual_input_finished');}
  };
  return {state,error,busy,readingUser,userSpeechText,command,withManualInput};
}
