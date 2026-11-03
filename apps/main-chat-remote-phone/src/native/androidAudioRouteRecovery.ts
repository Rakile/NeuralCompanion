import type {OutputState} from './iosLiveCapture';

export type AudioRouteRecoveryContext={
  scope:object;connection:object;ticket:string|null;foreground:boolean;enabled:boolean;live:boolean;
  output():Promise<OutputState>;
  close():Promise<void>;
  restorePlayback():Promise<void>;
  restoreLive():Promise<void>;
  report(stage:string,error?:unknown):void;
};

/** A route retirement is not permission to bypass native closure. Coalesce the
 * capture and player callbacks for the exact retired ticket, then use the same
 * stop-and-replace boundary as explicit controls. Never carry Live intent across
 * Stop, backgrounding, disconnection or a conversation change. */
export class AndroidAudioRouteRecovery {
  private epoch=0;
  private activeTicket:string|null=null;
  get pending(){return this.activeTicket!==null;}
  private readonly attempts=new Map<string,Promise<boolean>>();
  private readonly completed:string[]=[];
  constructor(private readonly context:()=>AudioRouteRecoveryContext){}
  cancel(){this.epoch++;this.activeTicket=null;}
  recover(ticket:string|null):Promise<boolean>{
    if(!ticket)return Promise.resolve(false);
    const prior=this.attempts.get(ticket);if(prior)return prior;
    const captured=this.context(),epoch=this.epoch;
    if(captured.ticket!==ticket||!captured.enabled)return Promise.resolve(false);
    // A failed replacement is a startup failure, not another recovered session.
    // Retain its receipt so delayed player callbacks cannot restart the loop.
    if(this.pending)return this.remember(ticket,Promise.resolve(false));
    const sameScope=()=>{
      const now=this.context();return this.epoch===epoch&&now.scope===captured.scope
        &&now.connection===captured.connection&&now.enabled;
    };
    const mayResume=()=>sameScope()&&this.context().foreground;
    const report=(stage:string,error?:unknown)=>{try{captured.report(stage,error);}catch{/* Diagnostics cannot own recovery. */}};
    const task=(async()=>{
      const output=await captured.output();
      if(output.open||output.ticket!==ticket||output.lastRetirementCause!=='route_change')return false;
      if(!sameScope()||this.context().ticket!==ticket)return true;
      if(this.pending)return false;
      this.activeTicket=ticket;
      let stage='close';
      report('begin');
      try{
        await captured.close();
        if(!mayResume()){report('cancelled');return true;}
        // Android reports SCO/A2DP input/output removals separately. Drain first,
        // then allow that burst to settle before a fresh native route admission.
        await new Promise(resolve=>setTimeout(resolve,350));
        if(!mayResume()){report('cancelled');return true;}
        stage='playback';await this.context().restorePlayback();
        if(!mayResume()){report('cancelled');return true;}
        if(captured.live){stage='microphone';await this.context().restoreLive();}
        if(mayResume())report('restored');
      }catch(error){
        if(sameScope()){
          const replacement=this.context().ticket;
          if(replacement&&replacement!==ticket&&!this.attempts.has(replacement))
            this.remember(replacement,Promise.resolve(false));
        }
        if(mayResume())report(`${stage}_failed`,error);
      }
      finally{if(this.activeTicket===ticket)this.activeTicket=null;}
      return true;
    })();
    return this.remember(ticket,task);
  }
  private remember(ticket:string,task:Promise<boolean>):Promise<boolean>{
    this.attempts.set(ticket,task);
    // Keep recent completed receipts too: a delayed old callback cannot retire
    // the replacement. This is evidence deduplication, not a retry loop.
    void task.finally(()=>{this.completed.push(ticket);if(this.completed.length>8)this.attempts.delete(this.completed.shift()!);}).catch(()=>undefined);
    return task;
  }
}
