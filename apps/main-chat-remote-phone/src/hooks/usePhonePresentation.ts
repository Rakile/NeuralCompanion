import {useEffect, useRef} from 'react';
import type {PhoneReplyAuth} from '../api/types';
import {phoneReplyErrorCode} from '../api/client';
import {PhonePresentationReporter,hasPhonePositionReader,readPhonePosition,exchangePhoneHandoff} from '../utils/phonePresentation';
import type {PhonePresentationPosition} from '../utils/phonePresentation';
import {recordPhoneDebug} from '../utils/phoneDebugBridge';

function tracePresentation(step:string,details:Record<string,unknown>){
  try{void recordPhoneDebug('info','phone_presentation_transaction',{
    step,monotonic_ms:performance.now(),...details,
  }).catch(()=>undefined);}catch{}
}

type Client = {reportPhonePresentation(auth: PhoneReplyAuth, active: boolean, sequence: number, position?: PhonePresentationPosition,handoff?:Record<string,unknown>): Promise<unknown>};
export function usePhonePresentation(client: Client, getAuth: (renew?: boolean) => Promise<PhoneReplyAuth>, active: boolean) {
  const current = useRef(active); current.current = active;
  const reporter = useRef<PhonePresentationReporter | null>(null);
  useEffect(() => {
    let alive = true;
    let lastAuth: PhoneReplyAuth | undefined;
    const owner = new PhonePresentationReporter(async (owns, sequence) => {
      let auth = !owns && lastAuth ? lastAuth : await getAuth();
      if (owns && (!alive || !current.current)) return;
      lastAuth = auth;
      const publish=async()=>{
        const position=owns?readPhonePosition(client)??undefined:undefined;
        // Desktop validates every declaration against the accompanying native
        // position. A transient unavailable position must defer declaration.
        const exchange=position?exchangePhoneHandoff(client):null;
        const detail={sequence,active:owns,position_present:Boolean(position),
          reader_registered:hasPhonePositionReader(client),source_frame:position?.sourceFrame??null,
          media_id:position?.mediaId??null,handoff_present:Boolean(exchange)};
        tracePresentation('send_start',detail);
        let answer:unknown;
        try{answer=await client.reportPhonePresentation(auth, owns, sequence, position,exchange?.payload);}
        catch(error){tracePresentation('send_failed',{...detail,failure_kind:phoneReplyErrorCode(error)??'unclassified'});throw error;}
        tracePresentation('send_done',{...detail,response_dispatch_allowed:owns&&alive&&current.current,
          dispatch_reason:!owns?'presentation_inactive':!alive?'reporter_closed':!current.current?'presentation_ended'
            :!exchange?'exchange_absent':'dispatch_to_exchange'});
        if(owns && alive && current.current)exchange?.accept(answer);
      };
      try { await publish(); }
      catch (failure) {
        if (!owns || !alive || !current.current || phoneReplyErrorCode(failure) !== 'phone_reply_authentication') throw failure;
        auth = await getAuth(true);
        if (!alive || !current.current) return;
        lastAuth = auth;
        await publish();
      }
    });
    reporter.current = owner;
    owner.update(current.current);
    let lastHeartbeat = performance.now();
    const timer = setInterval(() => {
      const now = performance.now();
      if (hasPhonePositionReader(client) || now-lastHeartbeat >= 2000) {
        lastHeartbeat = now; owner.update(current.current);
      }
    },250);
    return () => { alive = false; clearInterval(timer); owner.close(); if (reporter.current === owner) reporter.current = null; };
  }, [client,getAuth]);
  useEffect(() => {tracePresentation('active_changed',{active});reporter.current?.update(active); }, [active]);
}
