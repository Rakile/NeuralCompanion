// Presentation gate shared by Android and iOS. Keep Story code for later reuse.
export const PHONE_STORY_MODE_ENABLED: boolean = false;

const ALL_PRIMARY_DESTINATIONS = [
  { id: 'chat', label: 'Chat' },
  { id: 'story', label: 'Story' },
  { id: 'visual', label: 'Visual' },
  { id: 'tools', label: 'Settings' },
] as const;

export type PrimaryDestination = typeof ALL_PRIMARY_DESTINATIONS[number]['id'];
export function isPhoneDestinationEnabled(destination: PrimaryDestination): boolean {
  return destination !== 'story' || PHONE_STORY_MODE_ENABLED;
}
export const PRIMARY_DESTINATIONS = ALL_PRIMARY_DESTINATIONS.filter(({ id }) => isPhoneDestinationEnabled(id));
export type SecondarySurface = 'settings' | 'connection' | 'audio' | null;
export type ProductionSurface = PrimaryDestination | Exclude<SecondarySurface, null>;
export type ProductionBackAction = 'close_secondary' | 'open_chat' | 'exit';

export type ProductionSurfaceInput = {
  demoMode: boolean;
  primary: PrimaryDestination;
  secondary: SecondarySurface;
  sessionActive: boolean;
  reconnecting?: boolean;
};

export function resolveProductionSurface({
  demoMode,
  primary,
  secondary,
  sessionActive,
  reconnecting = false,
}: ProductionSurfaceInput): ProductionSurface {
  if (secondary === 'settings') return secondary;
  if (!sessionActive && !demoMode && !reconnecting) return 'connection';
  return secondary || (isPhoneDestinationEnabled(primary) ? primary : 'chat');
}

export function openSecondarySurface(surface: Exclude<SecondarySurface, null>): SecondarySurface {
  return surface;
}

export function closeSecondarySurface(): null {
  return null;
}

export function shouldShowPrimaryNavigation(surface: ProductionSurface): boolean {
  return surface === 'settings' || PRIMARY_DESTINATIONS.some(({ id }) => id === surface);
}

export function shouldShowConnectionBack(sessionActive: boolean): boolean {
  return sessionActive;
}

export function productionBackAction({
  primary,
  secondary,
}: {
  primary: PrimaryDestination;
  secondary: SecondarySurface;
}): ProductionBackAction {
  if (secondary) return 'close_secondary';
  return primary === 'chat' ? 'exit' : 'open_chat';
}

export function shouldShowVoiceTray({
  expanded,
  liveEnabled,
  error,
}: {
  expanded: boolean;
  liveEnabled: boolean;
  error: string;
}): boolean {
  return expanded || liveEnabled || Boolean(error.trim());
}
