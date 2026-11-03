import type {IdleManifest} from '../relay/idleLoopCache';
import type {OrderedIdleInventory} from './orderedIdleInventory';
import type {OrderedCachePolicy} from './orderedChunkStore';

type Dependencies={client:{readonly idleCacheScope:string;
  idleCacheManifest(signal:AbortSignal,sourceBinding:boolean,ordered:boolean):Promise<IdleManifest|null>};
  inventory:OrderedIdleInventory;policy():OrderedCachePolicy;current():boolean;
  onState?(reason:'disabled'|'inventory_pending'|'catalog_pending'|'reconnecting'|'manifest_failed'):void;
  onFailure?(error:unknown):void};

/** Connection control only. A manifest read never awaits the download worker
 * or native presentation; every new instance refreshes inventory on start. */
export class OrderedIdleInventoryConnection {
  private readonly abort=new AbortController();
  private requestAbort?:AbortController;
  private timer?:ReturnType<typeof setInterval>;
  private reading?:Promise<void>;private closing?:Promise<void>;private started=false;
  constructor(private readonly deps:Dependencies){}
  private current(){return !this.abort.signal.aborted&&this.deps.current();}
  start():Promise<void>{
    if(this.started)return this.reading??Promise.resolve();
    this.started=true;
    if(!this.current())return Promise.resolve();
    this.timer=setInterval(()=>{void this.refresh();},2000);
    return this.refresh();
  }
  refresh():Promise<void>{
    if(!this.current())return Promise.resolve();
    const policy=this.deps.policy();
    if(policy.mode!=='on'){
      this.requestAbort?.abort();
      const reason=policy.mode==='off'?'disabled':'inventory_pending';
      this.deps.onState?.(reason);return this.deps.inventory.pause(reason);
    }
    if(this.reading)return this.reading;
    const scope=this.deps.client.idleCacheScope;
    if(!scope){this.deps.onState?.('reconnecting');return Promise.resolve();}
    const requestAbort=this.requestAbort=new AbortController();
    return this.reading=(async()=>{
      try{
        const manifest=await this.deps.client.idleCacheManifest(requestAbort.signal,true,true);
        if(!this.current()||requestAbort.signal.aborted||this.deps.client.idleCacheScope!==scope)return;
        const now=this.deps.policy();if(now.mode!=='on')return;
        // A settings clear can win while the response is in flight. The pack
        // data remains current; apply the latest epoch, not the captured one.
        if(manifest)this.deps.inventory.update(manifest,now.epoch);
        else{
          await this.deps.inventory.pause('catalog_pending');
          if(this.current())this.deps.onState?.('catalog_pending');
        }
      }catch(error){
        if(this.current()&&!requestAbort.signal.aborted&&this.deps.client.idleCacheScope===scope){
          this.deps.onState?.('manifest_failed');
          try{this.deps.onFailure?.(error);}catch{}
        }
      }finally{this.reading=undefined;if(this.requestAbort===requestAbort)this.requestAbort=undefined;}
    })();
  }
  close():Promise<void>{
    if(this.closing)return this.closing;
    this.abort.abort();this.requestAbort?.abort();if(this.timer!==undefined)clearInterval(this.timer);this.timer=undefined;
    const joined=this.deps.inventory.close();
    return this.closing=Promise.all([this.reading,joined]).then(()=>undefined);
  }
}
