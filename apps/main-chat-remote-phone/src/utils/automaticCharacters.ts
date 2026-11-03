import type {ChatCharacterSnapshot} from '../api/types';

/** Snapshot restores are silent. Each live add event is consumed even if muted. */
export class CharacterAddSounds {
  private scope = '';
  private initialized = false;
  private seen = new Set<string>();
  private lastSound = 0;
  reset() {this.initialized=false;}
  observe(snapshot:ChatCharacterSnapshot, now=Date.now()):boolean {
    if(this.scope!==snapshot.conversation_id){this.scope=snapshot.conversation_id;this.initialized=false;this.seen.clear();}
    const fresh=snapshot.characters.filter(card=>card.conversation_id===snapshot.conversation_id||!card.conversation_id)
      .map(card=>card.automation).filter(auto=>auto?.added_event_id&&!this.seen.has(auto.added_event_id));
    for(const auto of fresh) this.seen.add(auto!.added_event_id!);
    while(this.seen.size>512)this.seen.delete(this.seen.values().next().value!);
    const ready=this.initialized;this.initialized=true;
    const serverTime=snapshot.server_time;
    const recent=typeof serverTime==='number'&&fresh.some(auto=>
      typeof auto?.added_at==='number'&&serverTime-auto.added_at>=0&&serverTime-auto.added_at<45);
    if(!ready||!recent||now-this.lastSound<3000||!snapshot.automatic_add_sound||!snapshot.automatic_add_enabled||
       !snapshot.character_voices_enabled||!snapshot.allow_new_characters)return false;
    this.lastSound=now;return true;
  }
}
