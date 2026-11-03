import type {SavedCharacterVoice} from '../api/types';

export const VOICE_CATEGORIES = [
  {id:'narrator',label:'Narrator'}, {id:'everyday',label:'Everyday'},
  {id:'fantasy',label:'Fantasy'}, {id:'sci-fi',label:'Sci-Fi'},
  {id:'royal-noble',label:'Royal & Noble'}, {id:'warriors',label:'Warriors'},
  {id:'villains',label:'Villains'}, {id:'creatures',label:'Creatures'},
  {id:'comedy',label:'Comedy'}, {id:'soft-soothing',label:'Soft & Soothing'},
] as const;

export function voiceGroups(voices:SavedCharacterVoice[], category:string, search:string) {
  const query=search.trim().toLowerCase();
  const matches=voices.filter(v=>`${v.name} ${v.description||''}`.toLowerCase().includes(query));
  return {favorites:matches.filter(v=>v.favorite),
    others:matches.filter(v=>!v.favorite&&(category==='all'||v.category===category))};
}
