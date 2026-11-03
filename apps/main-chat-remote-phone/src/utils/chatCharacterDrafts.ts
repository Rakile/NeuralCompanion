import type { ChatCharacter } from '../api/types';

export type CharacterDraft = Pick<ChatCharacter, 'name' | 'role' | 'description' | 'system_prompt' | 'voice_description' | 'preview_text' | 'portrait_prompt'>;
export function characterDraft(card: ChatCharacter): CharacterDraft {
  return {name:card.name, role:card.role, description:card.description, system_prompt:card.system_prompt ?? '', voice_description:card.voice_description,
    preview_text:card.preview_text, portrait_prompt:card.portrait_prompt};
}
export const characterPatch = (draft: CharacterDraft) => ({...draft});
export const draftChanged = (draft: CharacterDraft, card: ChatCharacter) => JSON.stringify(draft) !== JSON.stringify(characterDraft(card));
export function filterCharacters(cards: ChatCharacter[], conversation: string, search: string, filter: string) {
  return cards.filter(card => (!conversation || card.conversation_id === conversation)
    && `${card.name} ${card.role} ${card.description}`.toLowerCase().includes(search.trim().toLowerCase())
    && (filter !== 'voiced' || Boolean(card.voice_id)) && (filter !== 'needs_voice' || !card.voice_id));
}
export function activeChatCard<T extends Pick<ChatCharacter, 'id' | 'conversation_id' | 'source_character_id'>>(
    cards: readonly T[], card: T, conversation: string): T | null {
  if (!conversation) return null;
  if (card.conversation_id === conversation) return card;
  return cards.find(item => item.conversation_id === conversation && item.source_character_id === card.id) ?? null;
}
export class CharacterOperations {
  private pending = new Map<string, string>();
  constructor(private generate: () => string) {}
  get size() { return this.pending.size; }
  begin(scope: string, request: string) {
    const key = JSON.stringify([scope, request]);
    if (!this.pending.has(key)) this.pending.set(key, this.generate());
    return this.pending.get(key)!;
  }
  finish(scope: string, request: string) { this.pending.delete(JSON.stringify([scope, request])); }
}
export function canPreviewCharacterVoice(state: {connected: boolean; speaking: boolean; live: boolean; busy: boolean}) {
  return state.connected && !state.speaking && !state.live && !state.busy;
}

export function activeCharacterSpeaker<T extends Pick<ChatCharacter, 'id' | 'name'>>(enabled: boolean,
    speaker: string | undefined, characters: readonly T[]): T | null {
  if (!enabled || !speaker) return null;
  const identity = speaker.trim().toLocaleLowerCase();
  const matches = characters.filter(card => card.id.toLocaleLowerCase() === identity
    || card.name.trim().toLocaleLowerCase() === identity);
  return matches.length === 1 ? matches[0] ?? null : null;
}
