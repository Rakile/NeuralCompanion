import type {SoundscapeCue,SoundscapePatch,SoundscapeState,SoundAsset} from '../api/soundscape';

/** A cue is only eligible for the exact assistant reply's first audible onset. */
export function cuePatchAtOnset(cue:SoundscapeCue|null,state:SoundscapeState,session:number,
  assets:SoundAsset[],replyId:string):SoundscapePatch|null {
  if(!cue||!state.enabled||state.paused||cue.conversation_id!==state.conversation_id
    ||cue.session_generation!==session||cue.reply_id!==replyId||cue.revision!==state.revision)return null;
  const patch:SoundscapePatch={};
  for(const layer of ['ambience','music'] as const){
    if(!state[layer].follow_story)continue;
    const action=cue.actions[layer];
    if(action===undefined||action==='keep')continue;
    if(action==='clear'){patch[layer]={asset_id:null,follow_story:true};continue;}
    if(!/^[0-9a-f]{32}$/.test(action)||!assets.some(asset=>asset.id===action&&asset.kind===layer&&!asset.discarded
      &&(!cue.asset_revisions||asset.revision===cue.asset_revisions[action]&&asset.tags?.length)))return null;
    patch[layer]={asset_id:action,follow_story:true};
  }
  return Object.keys(patch).length||cue.effect!==undefined?patch:null;
}

export function cueEffectAsset(cue:SoundscapeCue,state:SoundscapeState,assets:SoundAsset[]):SoundAsset|null {
  const effect=cue.effect;
  if(!effect||!state.effects?.enabled||state.effects.muted)return null;
  return assets.find(asset=>asset.id===effect.asset_id&&asset.kind==='effect'&&!asset.discarded
    &&asset.revision===effect.asset_revision&&asset.tags?.length)??null;
}
