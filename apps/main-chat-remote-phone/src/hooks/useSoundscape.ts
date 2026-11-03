import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import type {RemoteClient} from '../api/client';
import {parseSoundscapeState,parseSoundscapeCue,parseSoundChoice,parseSoundEffectGrant,type SoundChoice,type SoundEffectPlayback,type SoundscapeState,type SoundscapePatch,type SoundAsset,type SoundMedia,type SoundKind,type SoundscapeCue} from '../api/soundscape';
import {soundscapeNative} from '../native/soundscape';
import {SoundscapeTransfer,soundRequestId} from '../relay/soundscapeTransfer';
import {SoundscapePlayback} from '../utils/soundscapePlayback';
import {SoundBatchQueue,type SoundBatch,type SoundBatchDraft} from '../utils/soundBatch';
import {soundBatchStorage} from '../utils/soundBatchStorage';
import {recordPhoneDebug} from '../utils/phoneDebugBridge';

export interface SoundJob {id:string;state:string;error?:string;preview?:SoundMedia}
type Metadata={title:string;kind:SoundKind;category:string;gain:number;description:string;tags:string[];loop:boolean};
type Generation={kind:SoundKind;prompt:string;duration_seconds:number;loop:boolean;instrumental:boolean};
type Snapshot={state:SoundscapeState;session_generation:number;instance_id:string;conversation_available:boolean;follow_story_available:boolean;cue?:SoundscapeCue|null;context_version?:number;library_revision?:string;choices?:SoundChoice[];effect_grant?:unknown};
export interface SoundscapeControls {
  /** UI draft ownership; no volume draft survives a remote/session switch. */
  volumeScope:string;
  previewPaused:boolean;review(asset:SoundAsset):Promise<void>;
  importResults:{name:string;state:'imported'|'existing'|'failed'}[];
  choices:SoundChoice[];contextAvailable:boolean;effectsAvailable:boolean;effectPlayback:SoundEffectPlayback|null;
  feedback(choice:SoundChoice,decision:'good'|'skip'):Promise<void>;discardAsset(asset:SoundAsset,discarded:boolean):Promise<void>;
  state:SoundscapeState|null;assets:SoundAsset[];busy:boolean;error:string;status:string;previewId:string;job:SoundJob|null;batch:SoundBatch|null;available:boolean;followStoryAvailable:boolean;
  refresh(forceLibrary?:boolean):Promise<void>;change(patch:SoundscapePatch):Promise<void>;useAsset(asset:SoundAsset):Promise<void>;preview(asset:SoundAsset|SoundMedia):Promise<void>;stopPreview():Promise<void>;
  importFiles(kind:SoundKind,category:string):Promise<void>;generate(request:Generation):Promise<void>;saveGenerated(metadata:Metadata):Promise<void>;
  cancelGenerated():Promise<void>;discardGenerated():Promise<void>;updateAsset(asset:SoundAsset,metadata:Metadata):Promise<void>;
  removeAsset(asset:SoundAsset):Promise<void>;resume():Promise<void>;pause():Promise<void>;
  startBatch(category:string,drafts:SoundBatchDraft[]):Promise<void>;refreshBatch():Promise<void>;cancelBatch():Promise<void>;retryBatchSaves():Promise<void>;
}
export function useSoundscape(client:RemoteClient,enabled:boolean,session:unknown,contextSupported=false) {
  const available=enabled&&soundscapeNative.available();
  const [state,setState]=useState<SoundscapeState|null>(null),[assets,setAssets]=useState<SoundAsset[]>([]);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[status,setStatus]=useState('Off');
  const [previewId,setPreviewId]=useState(''),[job,setJob]=useState<SoundJob|null>(null);
  const [previewPaused,setPreviewPaused]=useState(false);
  const [batch,setBatch]=useState<SoundBatch|null>(null);
  const [effectPlayback,setEffectPlayback]=useState<SoundEffectPlayback|null>(null);
  const [importResults,setImportResults]=useState<SoundscapeControls['importResults']>([]);
  const rememberedPauses=useRef(new Map<string,string>());
  const owner=useMemo(()=>({client,available,session,contextSupported,cancel:new AbortController(),closed:false,mutation:false}),[client,available,session,contextSupported]);
  const current=useRef(owner);current.current=owner;
  const snapshot=useRef<Snapshot|null>(null),jobRef=useRef<SoundJob|null>(null);
  const refreshSequence=useRef(0);
  const cueApplying=useRef(false);
  const pendingOnset=useRef<{replyId:string}|null>(null);
  const retryOnset=useRef<()=>void>(()=>undefined);
  const libraryRef=useRef<SoundAsset[]|null>(null);
  const live=()=>current.current===owner&&!owner.closed;
  const transfer=useMemo(()=>new SoundscapeTransfer({scope:()=>client.soundscapeCacheScope,
    busy:()=>client.soundscapeTransferBusy,part:(...args)=>client.soundscapePart(...args),
    json:<T,>(method:'GET'|'POST',path:string,body?:Record<string,unknown>,signal?:AbortSignal)=>client.soundscapeRequest<T>(method,path,body,signal)}),[owner]);
  const playback=useMemo(()=>available?new SoundscapePlayback(transfer,(next,preview,effect,reviewPaused)=>{
    if(current.current!==owner||owner.closed)return;
    if(next)setStatus(next);if(preview!==undefined){setPreviewId(preview);if(!preview)setPreviewPaused(false);}
    if(reviewPaused!==undefined)setPreviewPaused(reviewPaused);
    if(effect)setEffectPlayback(effect);
    void recordPhoneDebug('info','soundscape_playback',{status:next.slice(0,80),preview:Boolean(preview)}).catch(()=>undefined);
  },soundscapeNative,rememberedPauses.current,()=>client.soundscapeCacheScope):null,[owner]);
  const batchQueue=useMemo(()=>available?new SoundBatchQueue(soundBatchStorage(()=>client.soundscapeCacheScope),{
    request:<T,>(method:'GET'|'POST',action:string,body?:Record<string,unknown>)=>
      client.soundscapeRequest<T>(method,`/api/soundscape/${action}`,body,owner.cancel.signal),
  },next=>{if(current.current===owner&&!owner.closed)setBatch(next);},soundRequestId):null,[owner]);
  const normalize=(next:Snapshot)=>{
    next.state=parseSoundscapeState(next.state);next.cue=parseSoundscapeCue(next.cue);
    if(next.choices!==undefined){
      if(!Array.isArray(next.choices)||next.choices.length>3)throw new Error('Invalid sound choices.');
      const choices=next.choices.map(parseSoundChoice);
      if(choices.some(choice=>!choice))throw new Error('Invalid sound choice.');
      next.choices=choices as SoundChoice[];
    }
    return next;
  };
  const refresh=useCallback(async(forceLibrary=true)=>{
    if(!owner.available||owner.closed)return;
    const sequence=++refreshSequence.current;
    const next=normalize(await client.soundscapeRequest<Snapshot>('GET',`/api/soundscape/state${owner.contextSupported?'?client_version=2':''}`,undefined,owner.cancel.signal));
    const missing=['ambience','music'].some(layer=>{
      const id=next.state[layer as 'ambience'|'music'].asset_id;return id&&!libraryRef.current?.some(asset=>asset.id===id);
    });
    const missingEffect=next.cue?.effect&&!libraryRef.current?.some(asset=>asset.id===next.cue!.effect!.asset_id);
    const library=forceLibrary||missing||missingEffect||libraryRef.current===null||next.library_revision!==snapshot.current?.library_revision
      ? await client.soundscapeRequest<{assets:SoundAsset[]}>('GET','/api/soundscape/library',undefined,owner.cancel.signal)
      : {assets:libraryRef.current};
    if(!live()||sequence!==refreshSequence.current)return;
    if(!Array.isArray(library.assets)||library.assets.length>2000)throw new Error('Invalid sound library.');
    const old=snapshot.current;
    if(old?.instance_id===next.instance_id && old.session_generation===next.session_generation
      && old.state.conversation_id===next.state.conversation_id && old.state.revision>next.state.revision)return;
    snapshot.current=next;libraryRef.current=library.assets;setState(next.state);setAssets(library.assets);
    playback?.setChoices(next.choices??[]);
    if(next.conversation_available)await playback?.adopt(next.state,next.session_generation,library.assets).catch(failure=>{
      if(live()&&!owner.cancel.signal.aborted)setError(failure instanceof Error?failure.message:'Sound could not load.');
    });
    if(live()&&sequence===refreshSequence.current)
      void playback?.stageCue(next.cue??null,next.state,next.session_generation,library.assets).then(()=>{
        const latest=snapshot.current;
        if(live()&&next.cue&&latest?.cue?.id===next.cue.id
          &&latest.state.revision===next.state.revision&&latest.session_generation===next.session_generation
          &&pendingOnset.current?.replyId===next.cue.reply_id)retryOnset.current();
      }).catch(()=>undefined);
  },[owner,playback]);
  useEffect(()=>{
    snapshot.current=null;pendingOnset.current=null;libraryRef.current=null;jobRef.current=null;setState(null);setAssets([]);setJob(null);setBatch(null);setError('');setBusy(false);setPreviewId('');setEffectPlayback(null);setImportResults([]);
    let fetching=false;
    const poll=async()=>{if(fetching||!owner.available||owner.closed)return;
      if(snapshot.current&&!snapshot.current.state.enabled&&!['queued','submitting','converting'].includes(jobRef.current?.state||''))return;
      fetching=true;
      try {
        await refresh(false);
        const active=jobRef.current;
        if(active&&['queued','submitting','converting'].includes(active.state)) {
          const next=await client.soundscapeRequest<SoundJob>('GET',`/api/soundscape/generate/status?id=${active.id}`,undefined,owner.cancel.signal);
          if(live()&&jobRef.current?.id===active.id){jobRef.current=next;setJob(next);}
        }
      }catch(failure){if(live())setError(failure instanceof Error?failure.message:'Soundscape unavailable.');}
      finally{fetching=false;}
    };
    void poll();const timer=setInterval(()=>void poll(),5000);
    return ()=>{owner.closed=true;owner.cancel.abort();clearInterval(timer);void playback?.close().catch(()=>undefined);};
  },[owner,playback,refresh]);
  useEffect(()=>{
    if(!batchQueue)return;
    let fetching=false;
    let savedCount=0;
    const poll=async()=>{
      if(fetching||owner.closed||!client.soundscapeCacheScope)return;
      fetching=true;
      try{
        await batchQueue.load();await batchQueue.tick();
        const next=batchQueue.snapshot?.items.filter(item=>item.state==='saved').length||0;
        if(next>savedCount){savedCount=next;await refresh();}
      }catch(failure){if(live())setError(failure instanceof Error?failure.message:'Sound batch unavailable.');}
      finally{fetching=false;}
    };
    void poll();const timer=setInterval(()=>void poll(),10000);
    return ()=>clearInterval(timer);
  },[batchQueue,owner,refresh]);
  const run=async<T,>(action:()=>Promise<T>):Promise<T>=>{
    if(!live()||!owner.available)throw new Error('Connect the updated Android app and desktop to use Soundscape.');
    if(owner.mutation)throw new Error('Wait for the current sound operation.');
    owner.mutation=true;setBusy(true);setError('');
    try{return await action();}catch(failure){if(live())setError(failure instanceof Error?failure.message:'Sound operation failed.');throw failure;}
    finally{owner.mutation=false;if(live())setBusy(false);}
  };
  const post=<T,>(action:string,body:Record<string,unknown>)=>client.soundscapeRequest<T>('POST',`/api/soundscape/${action}`,
    {client_request_id:soundRequestId(),...(owner.contextSupported?{client_version:2}:{}),...body},owner.cancel.signal);
  const change=async(patch:SoundscapePatch)=>run(async()=>{
    const old=snapshot.current;
    if(!old?.conversation_available)throw new Error('Start a conversation before selecting background sounds.');
    pendingOnset.current=null;playback?.cancelOnset();
    playback?.clearCue();
    await playback?.stopEffects();
    try { await post('control',{conversation_id:old.state.conversation_id,session_generation:old.session_generation,
      expected_revision:old.state.revision,patch}); }finally{if(live())await refresh();}
  });
  const attemptOnset=(replyId:string,refreshOnMiss:boolean)=>{
    const current=snapshot.current,library=libraryRef.current;
    if(!current||!library||owner.closed||owner.mutation||cueApplying.current||!playback)return;
    const patch=playback.assistantOnset(replyId,current.state,current.session_generation,library);
    if(!patch||!current.cue){
      if(!playback.canRetryOnset(replyId))pendingOnset.current=null;
      else if(refreshOnMiss)void refresh(false).catch(()=>undefined);
      return;
    }
    pendingOnset.current=null;
    cueApplying.current=true;
    void post('cue/apply',{conversation_id:current.state.conversation_id,
      session_generation:current.session_generation,expected_revision:current.state.revision,
      cue_id:current.cue.id,reply_id:replyId}).then(async(raw)=>{
      const next=normalize(raw as Snapshot);
      if(!live()||owner.mutation||snapshot.current?.state.conversation_id!==next.state.conversation_id
        ||snapshot.current.session_generation!==next.session_generation||snapshot.current.state.revision>next.state.revision){await playback.stopEffects();return;}
      snapshot.current=next;setState(next.state);playback.setChoices(next.choices??[]);
      await playback.adopt(next.state,next.session_generation,library,async()=>{
        if(live()&&!owner.mutation)await playback.playEffectAtOnset(parseSoundEffectGrant(next.effect_grant),replyId);
      });
      void recordPhoneDebug('info','soundscape_scene_applied',{reply_id:replyId,layer_count:Object.keys(patch).length}).catch(()=>undefined);
    }).catch(()=>playback.stopEffects().catch(()=>undefined)).finally(async()=>{
      cueApplying.current=false;
      if(live())await refresh(false).catch(()=>undefined);
    });
  };
  retryOnset.current=()=>{
    const pending=pendingOnset.current;
    if(pending&&playback?.canRetryOnset(pending.replyId))attemptOnset(pending.replyId,false);
    else pendingOnset.current=null;
  };
  const onAssistantOnset=(replyId:string)=>{
    pendingOnset.current={replyId};attemptOnset(replyId,true);
  };
  const resume=async()=>{
    if(owner.mutation)throw new Error('Wait for the current sound operation.');
    playback?.prepareResume(snapshot.current?.state.conversation_id);await change({enabled:true,paused:false});
  };
  const pause=async()=>{await playback?.pause();if(!owner.mutation)await change({paused:true});};
  const stopPreview=async()=>{await playback?.stopPreview();if(live())setPreviewId('');};
  const useAsset=async(asset:SoundAsset)=>{
    if(asset.kind==='effect')throw new Error('Effects are not background layers.');
    if(owner.mutation)throw new Error('Wait for the current sound operation.');
    await stopPreview();
    playback?.prepareResume(snapshot.current?.state.conversation_id);
    await change({enabled:true,paused:false,[asset.kind]:{asset_id:asset.id}});
  };
  const preview=async(asset:SoundAsset|SoundMedia,mixBackground=false)=>{
    const media='media' in asset?asset.media:asset;
    const gain='gain' in asset && Number.isFinite(asset.gain) && asset.gain>=0 && asset.gain<=1?asset.gain:1;
    if(previewId===media.asset_id){await stopPreview();return;}
    await run(async()=>{await playback?.preview(media,gain,mixBackground);});
  };
  const importFiles=async(kind:SoundKind,category:string)=>run(async()=>{
    if(!category.trim()||category.trim().length>64)throw new Error('Choose an import category of up to 64 characters.');
    const DocumentPicker=await import('expo-document-picker');
    const picked=await DocumentPicker.getDocumentAsync({type:'audio/*',multiple:true,copyToCacheDirectory:true});
    if(picked.canceled||!live())return;
    if(picked.assets.length>100)throw new Error('Choose at most 100 sounds per import.');
    let existing=0,failed=0,added=0;
    const results:SoundscapeControls['importResults']=[];setImportResults([]);
    for(const file of picked.assets) {
      if(!live())return;
      try{
      const title=file.name.replace(/\.[^.]+$/,'').slice(0,120);
      const tags=Array.from(new Set((title+' '+category).toLowerCase().match(/[^\W\d_]+/gu)??[])).filter(v=>v.length>2).map(v=>v.slice(0,32)).slice(0,20);
      const uploaded=await transfer.upload(file.uri,file.name,{title:file.name.replace(/\.[^.]+$/,'').slice(0,120),
        kind,category:category.trim(),gain:1,description:'',tags,loop:kind!=='effect'},owner.cancel.signal,p=>{if(live())setStatus(`Importing ${Math.round(p*100)}%`);});
      if(uploaded.existing)existing++;
      let result:{state:string;error?:string}=uploaded;
      for(let count=0;result.state==='converting'&&count<310;count++) {
        await new Promise(resolve=>setTimeout(resolve,1000));if(!live())return;
        result=await client.soundscapeRequest('GET',`/api/soundscape/import/status?id=${uploaded.id}`,undefined,owner.cancel.signal);
      }
      if(result.state!=='ready')throw new Error(result.error||'Import is still processing. Refresh the library shortly.');
      if(!uploaded.existing)added++;
      results.push({name:file.name,state:uploaded.existing?'existing':'imported'});
      }catch(failure){if(owner.cancel.signal.aborted||!live())return;failed++;results.push({name:file.name,state:'failed'});}
      if(live())setImportResults([...results]);
    }
    await refresh();if(live())setStatus(`Imported ${added}; ${existing} duplicates; ${failed} failed. Filename tags are suggestions — preview and edit them.`);
  });
  const generate=async(request:Generation)=>run(async()=>{
    const next=await post<SoundJob>('generate/start',{request});if(live()){jobRef.current=next;setJob(next);}
  });
  const jobAction=async(action:string,metadata?:Metadata)=>run(async()=>{
    const currentJob=jobRef.current;if(!currentJob)throw new Error('No sound generation is selected.');
    await stopPreview();
    await post(`generate/${action}`,{id:currentJob.id,...(metadata?{metadata}:{})});
    const next=await client.soundscapeRequest<SoundJob>('GET',`/api/soundscape/generate/status?id=${currentJob.id}`,undefined,owner.cancel.signal);
    if(live()){jobRef.current=next;setJob(next);}await refresh();
  });
  const contextAvailable=available&&owner.contextSupported&&snapshot.current?.context_version===1;
  const controls:SoundscapeControls={state,assets,busy,error,status,previewId,previewPaused,
    volumeScope:JSON.stringify([client.identityKey,snapshot.current?.instance_id,snapshot.current?.session_generation,state?.conversation_id]),
    review:asset=>previewId===asset.id?run(async()=>{await playback?.previewPlaying(previewPaused);}):preview(asset,true),
    job,batch,available,importResults,choices:snapshot.current?.choices??[],contextAvailable,
    effectsAvailable:contextAvailable&&soundscapeNative.effectsAvailable(),effectPlayback,
    feedback:(choice,decision)=>run(async()=>{
      const current=snapshot.current;if(!contextAvailable||!current||choice.conversation_id!==current.state.conversation_id||choice.session_generation!==current.session_generation)throw new Error('This sound choice expired. Refresh the menu.');
      if(decision==='skip')await playback?.stopChoice(choice);
      try{await post('feedback',{choice_id:choice.id,decision,conversation_id:choice.conversation_id,session_generation:choice.session_generation});}
      finally{if(live())await refresh();}
    }),
    discardAsset:(asset,discarded)=>run(async()=>{
      if(!contextAvailable)throw new Error('Connect an updated Desktop to discard sounds.');
      if(discarded){await playback?.stopEffects();for(const choice of snapshot.current?.choices??[])if(choice.asset_id===asset.id)await playback?.stopChoice(choice);}
      try{await post('library/discard',{asset_id:asset.id,discarded,expected_revision:asset.revision});}
      finally{if(live())await refresh();}
    }),
    followStoryAvailable:snapshot.current?.follow_story_available===true,refresh,change,useAsset,resume,pause,preview,stopPreview,importFiles,generate,
    startBatch:(category,drafts)=>run(async()=>{if(!batchQueue)throw new Error('Sound batch is unavailable.');
      await batchQueue.load();await batchQueue.start(category,drafts);
      void batchQueue.tick().catch(failure=>{if(live())setError(failure instanceof Error?failure.message:'Sound batch stopped.');});}),
    refreshBatch:()=>run(async()=>{await batchQueue?.load();await batchQueue?.tick();await refresh();}),
    cancelBatch:()=>run(async()=>{await batchQueue?.cancel();}),
    retryBatchSaves:()=>run(async()=>{await batchQueue?.retrySaves();await refresh();}),
    saveGenerated:metadata=>jobAction('save',metadata),cancelGenerated:()=>jobAction('cancel'),discardGenerated:()=>jobAction('discard'),
    updateAsset:(asset,metadata)=>run(async()=>{await post('library/update',{asset_id:asset.id,expected_revision:asset.revision,metadata});await refresh();}),
    removeAsset:asset=>run(async()=>{await stopPreview();await post('library/remove',{asset_id:asset.id});await refresh();})};
  return {controls,playback,onAssistantOnset};
}
