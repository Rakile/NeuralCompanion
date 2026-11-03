import type {SoundAsset,SoundKind} from '../api/soundscape';

export type SoundBatchDraft={title:string;prompt:string;duration_seconds:number;kind?:SoundKind;loop?:boolean;instrumental?:boolean};
export type SoundBatchItem=SoundBatchDraft&{
  request_id:string;save_request_id:string;job_id?:string;asset_id?:string;
  state:string;error?:string;
};
export type SoundBatch={version:1;id:string;category:string;created_at:number;stopped:boolean;items:SoundBatchItem[]};
export type SoundBatchStore={read():Promise<SoundBatch|null>;write(batch:SoundBatch):Promise<void>};
export type SoundBatchApi={request<T>(method:'GET'|'POST',action:string,body?:Record<string,unknown>):Promise<T>};

const presets:Record<string,string[]>={
  Weather:['Distant thunder','Close thunder','Gentle rain','Heavy rain','Wind gust','Window rattling','Hail on roof','Water dripping','Lightning crack','Branch snapping in storm','Storm rising','Storm fading'],
  Nature:['Morning birds','Night owl','Leaves rustling','Flowing stream','Insects at dusk','Wolf howl','Footsteps on leaves','Water splash','Forest wind','Frogs by pond','Falling tree branch','Distant waterfall'],
  City:['Street crowd','Car passing','Tram bell','Footsteps on pavement','Door chime','Distant siren','Traffic horn','Bicycle bell','Cafe dishes','Market murmur','Bus brakes','Rain on asphalt'],
  Interiors:['Fireplace crackle','Wooden door opening','Floorboard creak','Clock chime','Pages turning','Glass set down','Hallway footsteps','Chair moving','Window opening','Candle extinguishing','Room murmur','Key turning in lock'],
  Movement:['Fast footsteps','Slow footsteps','Horse walking','Horse galloping','Car engine starting','Vehicle passing','Train approaching','Boat rocking','Door opening','Door closing','Wheels rolling','Running through brush'],
  Combat:['Sword clash','Arrow released','Arrow impact','Shield strike','Heavy punch','Explosion distant','Explosion close','Armor moving','Battle crowd distant','Weapon drawn','Footsteps charging','Debris falling'],
  Fantasy:['Magic shimmer','Spell casting','Portal opening','Portal closing','Dragon roar distant','Dragon wing beat','Enchanted chime','Ancient rune activation','Mystic wind','Creature growl','Energy burst','Magic fading'],
  'Sci-Fi':['Spaceship hum','Airlock opening','Airlock closing','Computer alert','Laser blast','Robot footsteps','Engine ignition','Radio static','Hologram activation','Scanner sweep','Mechanical door','Power core surge'],
  Ambient:['Forest at night','Rain on a distant roof','Waves along a quiet shore','Wind across open fields','Low city traffic','Busy market bed','Tavern room tone','Old house at night','Mountain wind','Cave water drops','Spaceship interior hum','Distant battlefield'],
  Music:['Quiet exploration','Hopeful discovery','Tense investigation','Rising danger','Reflective aftermath','Warm reunion','Mystical wonder','Travel montage','Dark suspense','Triumphant return','Melancholy farewell','Restful interlude'],
  Horror:['Distant whisper-like wind','Floorboards upstairs','Scratching behind wall','Uneven footsteps','Door creaking open','Sudden impact','Low creature growl','Rattling chain','Breath in the dark','Window tapping','Basement machinery','Dread sting'],
  Mystery:['Secret door sliding','Paper clue unfolding','Clock ticking alone','Footsteps following','Drawer unlocking','Distant coded signal','Hidden mechanism','Library room tone','Rain on detective window','Quiet revelation','Object discovered','Unsettling transition'],
  Adventure:['Rope tightening','Cliff wind','Pack being opened','Bridge swaying','River crossing','Distant animal call','Map unfolding','Cave entrance','Quick escape','Treasure chest opening','Campfire at dusk','Summit arrival'],
  Romance:['Soft footsteps approaching','Letter unfolding','Fabric moving','Gentle door knock','Glass clinking','Garden fountain','Quiet laugh','Footsteps departing','Rain outside window','Fireplace warmth','Dance floor movement','Tender transition'],
  Maritime:['Ship deck creaking','Harbor gulls','Rope and rigging','Waves against hull','Sail unfurling','Distant foghorn','Rain on deck','Anchor dropping','Oars through water','Cabin door','Storm at sea','Quiet harbor'],
};

export const soundBatchCategories=Object.keys(presets);
export function makeSoundBatchPlan(category:string,count=12,refiner=''):SoundBatchDraft[]{
  const name=category.trim();
  if(!name||name.length>64)throw new Error('Choose a sound category of up to 64 characters.');
  if(!Number.isInteger(count)||count<1||count>12)throw new Error('Choose between 1 and 12 sounds.');
  if(refiner.length>1000)throw new Error('Keep the category prompt refiner under 1000 characters.');
  const preset=Object.keys(presets).find(value=>value.toLowerCase()===name.toLowerCase());
  const kind:SoundKind=preset==='Music'?'music':preset==='Ambient'?'ambience':'effect';
  const names=(preset?presets[preset]:undefined)||['Ambient detail','Approach','Departure','Footsteps','Opening','Closing',
    'Small impact','Large impact','Warning','Discovery','Transition','Ending sting'];
  return names.slice(0,count).map(sound=>({title:`${name} - ${sound}`,
    prompt:(kind==='music'
      ?`Instrumental music cue for ${sound.toLowerCase()} in a ${name.toLowerCase()} scene. Clear musical arc, no vocals, no speech.`
      :kind==='ambience'
        ?`Seamless environmental ambience: ${sound.toLowerCase()}. Natural spatial detail, no speech, no narration, no music.`
        :`Clean isolated sound effect: ${sound.toLowerCase()} in a ${name.toLowerCase()} scene. Natural dynamics, clear detail, no speech, no narration, no music.`)
      +(refiner.trim()?` Direction: ${refiner.trim()}`:''),
    duration_seconds:kind==='music'?60:kind==='ambience'?20:8,
    kind,loop:kind!=='effect',instrumental:true}));
}

export function withSoundBatchDurationMs(item:SoundBatchDraft,value:string):SoundBatchDraft{
  if(!/^\d+$/.test(value.trim()))throw new Error('Enter a duration in whole milliseconds.');
  const milliseconds=Number(value.trim());
  if(!Number.isSafeInteger(milliseconds))throw new Error('Enter a valid duration in milliseconds.');
  const seconds=milliseconds/1000;
  if(item.kind==='music'?![30,60,120,180].includes(seconds):seconds<.5||seconds>30)
    throw new Error(item.kind==='music'?'Music duration must be 30000, 60000, 120000 or 180000 ms.':'Sound duration must be 500–30000 ms.');
  return {...item,duration_seconds:seconds};
}

function validate(category:string,drafts:SoundBatchDraft[]):void{
  if(!category.trim()||category.length>64||drafts.length<1||drafts.length>12)throw new Error('Choose one category with up to twelve sounds.');
  for(const item of drafts){
    if(!item.title.trim()||item.title.length>120||!item.prompt.trim()||item.prompt.length>4100
      ||!['effect','ambience','music'].includes(item.kind||'effect')
      ||!Number.isFinite(item.duration_seconds)
      ||(item.kind==='music'?![30,60,120,180].includes(item.duration_seconds):item.duration_seconds<.5||item.duration_seconds>30))
      throw new Error('Check every sound title, description and duration.');
  }
}
function tags(item:SoundBatchItem,category:string):string[]{
  return [...new Set(`${category} ${item.title.replace(`${category} - `,'')}`.toLowerCase()
    .match(/[a-z0-9]{3,32}/g)||[])].slice(0,20);
}

/** Phone review and persistence; the desktop's existing job journal owns paid calls. */
export class SoundBatchQueue {
  private batch:SoundBatch|null=null;
  private running:Promise<void>|null=null;
  constructor(private store:SoundBatchStore,private api:SoundBatchApi,
    private changed:(batch:SoundBatch|null)=>void,private id:()=>string=()=>`sound-${Date.now()}-${Math.random().toString(36).slice(2)}`){}
  get snapshot():SoundBatch|null{return this.batch;}
  private async persist():Promise<void>{
    if(!this.batch)return;
    const copy=JSON.parse(JSON.stringify(this.batch)) as SoundBatch;
    await this.store.write(copy);
    this.changed(copy);
  }
  async load():Promise<SoundBatch|null>{
    if(this.batch)return this.batch;
    const value=await this.store.read();
    if(value){
      const states=new Set(['planned','submitting','queued','converting','ready','saving','saved','failed','cancelled','outcome_unknown','expired','save_failed']);
      if(value.version!==1||typeof value.id!=='string'||typeof value.category!=='string'
        ||typeof value.stopped!=='boolean'||!Array.isArray(value.items)
        ||value.items.length<1||value.items.length>12)throw new Error('Saved sound batch is damaged.');
      try{validate(value.category,value.items);}catch{throw new Error('Saved sound batch is damaged.');}
      if(value.items.some(item=>!item||typeof item.request_id!=='string'||!item.request_id.trim()||item.request_id.length>128
        ||typeof item.save_request_id!=='string'||!item.save_request_id.trim()||item.save_request_id.length>128
        ||typeof item.state!=='string'||!states.has(item.state)
        ||(item.job_id!==undefined&&!/^[0-9a-f]{32}$/.test(item.job_id))
        ||(item.asset_id!==undefined&&!/^[0-9a-f]{32}$/.test(item.asset_id))))
        throw new Error('Saved sound batch is damaged.');
    }
    this.batch=value;this.changed(value);return value;
  }
  async start(category:string,drafts:SoundBatchDraft[]):Promise<void>{
    validate(category,drafts);
    if(this.batch&&!this.batch.stopped&&this.batch.items.some(item=>!['saved','failed','cancelled','outcome_unknown'].includes(item.state)))
      throw new Error('Finish or cancel the current sound batch first.');
    this.batch={version:1,id:this.id(),category:category.trim(),created_at:Date.now(),stopped:false,
      items:drafts.map(item=>({...item,title:item.title.trim(),prompt:item.prompt.trim(),request_id:this.id(),save_request_id:this.id(),state:'planned'}))};
    await this.persist();
  }
  async tick():Promise<void>{
    if(this.running)return this.running;
    if(!this.batch||this.batch.stopped)return;
    const work=this.performTick();this.running=work;
    try{await work;}finally{if(this.running===work)this.running=null;}
  }
  private async performTick():Promise<void>{
    if(!this.batch||this.batch.stopped)return;
      for(const item of this.batch.items){
        if(this.batch.stopped)break;
        if(!item.job_id){
          item.state='submitting';await this.persist();
          try{
            const job=await this.api.request<{id:string;state:string}>('POST','generate/start',{
              client_request_id:item.request_id,request:{kind:item.kind||'effect',prompt:item.prompt,duration_seconds:item.duration_seconds,
                loop:item.loop??false,instrumental:item.instrumental??true}});
            item.job_id=job.id;item.state=job.state;item.error='';await this.persist();
            if(this.batch.stopped)break;
          }catch(error){item.error=error instanceof Error?error.message:'Could not submit sound.';await this.persist();break;}
        }
      }
      for(const item of this.batch.items){
        if(this.batch.stopped||!item.job_id||['saved','failed','cancelled','outcome_unknown','expired','save_failed'].includes(item.state))continue;
        const job=await this.api.request<{id:string;state:string;error?:string;saved_asset_id?:string}>('GET',`generate/status?id=${item.job_id}`);
        if(this.batch.stopped)break;
        item.state=job.state;item.error=job.error||'';
        if(job.state==='saved')item.asset_id=job.saved_asset_id;
        await this.persist();
        if(job.state!=='ready'||this.batch.stopped)continue;
        try{
          const result=await this.api.request<{asset:SoundAsset}>('POST','generate/save',{
            client_request_id:item.save_request_id,id:item.job_id,
            metadata:{title:item.title,description:item.prompt.slice(0,2000),kind:item.kind||'effect',category:this.batch.category,
              gain:1,tags:tags(item,this.batch.category),loop:item.loop??false}});
          item.state='saved';item.asset_id=result.asset.id;item.error='';await this.persist();
        }catch(error){item.state='save_failed';item.error=error instanceof Error?error.message:'Could not save sound.';await this.persist();}
      }
  }
  async retrySaves():Promise<void>{
    if(!this.batch||this.batch.stopped) return;
    if(this.running)await this.running;
    for(const item of this.batch.items)if(item.state==='save_failed')item.state='ready';
    await this.persist();await this.tick();
  }
  async cancel():Promise<void>{
    if(!this.batch)return;
    this.batch.stopped=true;await this.persist();
    await this.running?.catch(()=>undefined);
    for(const item of this.batch.items){
      if(!item.job_id||['saved','failed','cancelled','outcome_unknown'].includes(item.state))continue;
      try{await this.api.request('POST','generate/cancel',{client_request_id:this.id(),id:item.job_id});item.state='cancelled';await this.persist();}
      catch{item.error='Could not cancel this submitted request. It may still be charged.';await this.persist();}
    }
  }
}
