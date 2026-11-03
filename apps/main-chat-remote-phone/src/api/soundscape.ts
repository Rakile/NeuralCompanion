export type SoundKind = 'ambience' | 'music' | 'effect';
export type SoundLayer = 'ambience' | 'music';
export interface SoundscapeCue {
  id:string;conversation_id:string;session_generation:number;assistant_id:string;
  reply_id:string;revision:number;story_revision:number|null;
  actions:Partial<Record<SoundLayer,string>>;
  effect?:{asset_id:string;asset_revision:number}|null;
  asset_revisions?:Record<string,number>;
}
export interface SoundChoice {
  id:string;conversation_id:string;session_generation:number;reply_id:string;cue_id:string;
  layer:SoundLayer|'effect';asset_id:string;asset_revision:number;excerpt:string;good:boolean;skipped:boolean;
}
export interface SoundEffectGrant {choice_id:string;conversation_id:string;session_generation:number;reply_id:string;cue_id:string;asset_id:string;asset_revision:number}
export interface SoundEffectPlayback {choiceId:string;status:'playing'|'finished'|'stopped'|'omitted';reason?:'not_ready'|'late'|'unavailable'}
export interface SoundLayerSettings { asset_id: string | null; follow_story: boolean; volume: number; muted: boolean }
export interface SoundscapeState {
  version: 1; conversation_id: string; revision: number; enabled: boolean; paused: boolean; duck_speech: boolean;
  ambience: SoundLayerSettings; music: SoundLayerSettings;
  effects?:{enabled:boolean;volume:number;muted:boolean};
}
export interface SoundMedia {
  asset_id: string; sha256: string; source_hash: string; profile: string; byte_length: number;
  duration_ms: number; channels: number; sample_rate: 48000; content_type: 'audio/ogg'; url_path: string;
}
export interface SoundAsset {
  id: string; revision: number; title: string; description: string; kind: SoundKind; category: string; gain: number;
  tags: string[]; duration_ms: number;
  source: string; loop: boolean; content_hash: string; media: SoundMedia;
  discarded?:boolean;
}
export interface SoundscapeScope { conversation_id: string; session_generation: number; playback_generation: number; revision: number }
export type SoundscapePatch = Partial<Pick<SoundscapeState, 'enabled' | 'paused' | 'duck_speech'>> & {
  ambience?: Partial<SoundLayerSettings>; music?: Partial<SoundLayerSettings>;
  effects?:Partial<NonNullable<SoundscapeState['effects']>>;
};

export function parseSoundChoice(input:unknown):SoundChoice|null {
  if(!input||typeof input!=='object')return null;
  const v=input as Record<string,unknown>;
  for(const [key,limit] of [['id',128],['conversation_id',128],['reply_id',160],['cue_id',300]] as const)
    if(typeof v[key]!=='string'||!v[key]||(v[key] as string).length>limit)return null;
  if(!['ambience','music','effect'].includes(String(v.layer))||typeof v.asset_id!=='string'||!/^[0-9a-f]{32}$/.test(v.asset_id)
    ||!Number.isSafeInteger(v.asset_revision)||(v.asset_revision as number)<0||!Number.isSafeInteger(v.session_generation)
    ||(v.session_generation as number)<0||typeof v.excerpt!=='string'||v.excerpt.length>500
    ||typeof v.good!=='boolean'||typeof v.skipped!=='boolean')return null;
  return {id:v.id as string,conversation_id:v.conversation_id as string,reply_id:v.reply_id as string,cue_id:v.cue_id as string,
    layer:v.layer as SoundChoice['layer'],asset_id:v.asset_id,asset_revision:v.asset_revision as number,
    session_generation:v.session_generation as number,excerpt:v.excerpt,good:v.good,skipped:v.skipped};
}
export function parseSoundEffectGrant(input:unknown):SoundEffectGrant|null {
  if(!input||typeof input!=='object')return null;
  const v=input as Record<string,unknown>;
  const choice=parseSoundChoice({...v,id:v.choice_id,layer:'effect',excerpt:'',good:false,skipped:false});
  return choice?{choice_id:choice.id,conversation_id:choice.conversation_id,session_generation:choice.session_generation,
    reply_id:choice.reply_id,cue_id:choice.cue_id,asset_id:choice.asset_id,asset_revision:choice.asset_revision}:null;
}

export function parseSoundscapeCue(input:unknown):SoundscapeCue|null {
  if(!input||typeof input!=='object')return null;
  const value=input as Record<string,unknown>,actions=value.actions;
  if(typeof value.id!=='string'||!value.id||value.id.length>300
    ||typeof value.conversation_id!=='string'||!value.conversation_id||value.conversation_id.length>128
    ||typeof value.assistant_id!=='string'||!value.assistant_id||value.assistant_id.length>160
    ||typeof value.reply_id!=='string'||!value.reply_id||value.reply_id.length>160
    ||!Number.isSafeInteger(value.session_generation)||!Number.isSafeInteger(value.revision)
    ||(value.story_revision!==null&&!Number.isSafeInteger(value.story_revision))
    ||!actions||typeof actions!=='object'||Array.isArray(actions))return null;
  const decisions=actions as Record<string,unknown>;
  if(Object.keys(decisions).some(key=>!['ambience','music'].includes(key)))return null;
  for(const action of Object.values(decisions))if(typeof action!=='string'
    ||(action!=='keep'&&action!=='clear'&&!/^[0-9a-f]{32}$/.test(action)))return null;
  let effect:SoundscapeCue['effect'];
  if(value.effect!==undefined){
    if(value.effect===null)effect=null;
    else {
      const e=value.effect as Record<string,unknown>;
      if(typeof e!=='object'||Array.isArray(e)||typeof e.asset_id!=='string'||!/^[0-9a-f]{32}$/.test(e.asset_id)
        ||!Number.isSafeInteger(e.asset_revision)||(e.asset_revision as number)<0)return null;
      effect={asset_id:e.asset_id,asset_revision:e.asset_revision as number};
    }
  }
  let revisions:Record<string,number>|undefined;
  if(value.asset_revisions!==undefined){
    if(!value.asset_revisions||typeof value.asset_revisions!=='object'||Array.isArray(value.asset_revisions))return null;
    const entries=Object.entries(value.asset_revisions);
    if(entries.length>32||entries.some(([id,rev])=>!/^[0-9a-f]{32}$/.test(id)||!Number.isSafeInteger(rev)||(rev as number)<0))return null;
    revisions=Object.fromEntries(entries) as Record<string,number>;
  }
  return {id:value.id,conversation_id:value.conversation_id,assistant_id:value.assistant_id,
    reply_id:value.reply_id,session_generation:value.session_generation as number,
    revision:value.revision as number,story_revision:value.story_revision as number|null,
    actions:decisions as SoundscapeCue['actions'],...(effect!==undefined?{effect}:{}),...(revisions?{asset_revisions:revisions}:{})};
}

export function parseSoundscapeState(value: unknown): SoundscapeState {
  const invalid = () => { throw new Error('Invalid soundscape state.'); };
  if (!value || typeof value !== 'object') return invalid();
  const v = value as Record<string, unknown>;
  if (v.version !== 1 || !Number.isSafeInteger(v.revision) || (v.revision as number) < 0
      || typeof v.conversation_id !== 'string' || !v.conversation_id.trim() || v.conversation_id.length > 128) return invalid();
  for (const key of ['enabled', 'paused', 'duck_speech']) if (typeof v[key] !== 'boolean') return invalid();
  const layer = (input: unknown): SoundLayerSettings => {
    if (!input || typeof input !== 'object') return invalid();
    const l = input as Record<string, unknown>;
    if ((l.asset_id !== null && (typeof l.asset_id !== 'string' || !/^[0-9a-f]{32}$/.test(l.asset_id)))
        || typeof l.volume !== 'number' || !Number.isFinite(l.volume) || l.volume < 0 || l.volume > 1
        || typeof l.follow_story !== 'boolean' || typeof l.muted !== 'boolean') return invalid();
    return {asset_id:l.asset_id as string|null, volume:l.volume, follow_story:l.follow_story, muted:l.muted};
  };
  const effects=v.effects===undefined?{enabled:false,volume:.2,muted:false}:v.effects as Record<string,unknown>;
  if(!effects||typeof effects!=='object'||typeof effects.enabled!=='boolean'||typeof effects.muted!=='boolean'
    ||typeof effects.volume!=='number'||!Number.isFinite(effects.volume)||effects.volume<0||effects.volume>1)return invalid();
  return {version:1, conversation_id:v.conversation_id, revision:v.revision as number,
    enabled:v.enabled as boolean, paused:v.paused as boolean, duck_speech:v.duck_speech as boolean,
    ambience:layer(v.ambience), music:layer(v.music),effects:{enabled:effects.enabled,volume:effects.volume,muted:effects.muted}};
}
