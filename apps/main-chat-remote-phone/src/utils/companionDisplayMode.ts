export const COMPANION_DISPLAY_MODES = ['conversation', 'companion', 'portrait'] as const;

export type CompanionDisplayMode = typeof COMPANION_DISPLAY_MODES[number];

const MODE_LABELS: Record<CompanionDisplayMode, string> = {
  conversation: 'Conversation',
  companion: 'Companion',
  portrait: 'Portrait Presence',
};

export function normalizeCompanionDisplayMode(value: unknown): CompanionDisplayMode {
  return COMPANION_DISPLAY_MODES.includes(value as CompanionDisplayMode)
    ? value as CompanionDisplayMode
    : 'conversation';
}

export function companionDisplayModeLabel(mode: CompanionDisplayMode): string {
  return MODE_LABELS[mode];
}
