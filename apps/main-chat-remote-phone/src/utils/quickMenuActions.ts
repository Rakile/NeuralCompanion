export const QUICK_MENU_ACTIONS = [
  'pause_speech', 'skip_speech', 'skip_user_reply', 'replay_last_assistant',
  'replay_chat_session', 'interrupt_response', 'regenerate_response', 'retry_user_input', 'soundscape',
] as const;
export type QuickMenuAction = typeof QUICK_MENU_ACTIONS[number];
export const DEFAULT_QUICK_MENU_ACTIONS: QuickMenuAction[] = ['regenerate_response', 'retry_user_input'];

export function normalizeQuickMenuActions(value: unknown): QuickMenuAction[] {
  if (!Array.isArray(value)) return [...DEFAULT_QUICK_MENU_ACTIONS];
  return [...new Set(value.filter((item): item is QuickMenuAction =>
    QUICK_MENU_ACTIONS.includes(item as QuickMenuAction)))];
}

/** Regenerate/Retry retain their existing message-target-aware controls. */
export function extraQuickMenuActions(selected: unknown, available: string[]): QuickMenuAction[] {
  return normalizeQuickMenuActions(selected).filter(action => available.includes(action)
    && action !== 'regenerate_response' && action !== 'retry_user_input');
}

export type QuickMenuPreferences = {
  quickMenuActions?: QuickMenuAction[];
  onQuickMenuActionsChange?: (actions: QuickMenuAction[]) => void;
};
