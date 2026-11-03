export const colors = {
  background: '#070A0E',
  backgroundElevated: '#0B1016',
  panel: '#10161D',
  panelAlt: '#151E27',
  border: '#263340',
  borderSoft: '#1B2732',
  text: '#F4F7FA',
  textSecondary: '#B6C3CE',
  muted: '#95A6B4',
  accent: '#68D9FF',
  accentMuted: '#2383A3',
  accentSoft: '#102A36',
  danger: '#ff6b6b',
  ok: '#5ee0a0',
  warning: '#ffc857',
};

export type ThemeColors = typeof colors;
export type PhoneThemeId = 'midnight' | 'graphite' | 'forest' | 'daylight';
export type PhoneTheme = { id: PhoneThemeId; name: string; appearance: 'dark' | 'light'; colors: ThemeColors };
export const PHONE_THEMES: readonly PhoneTheme[] = [
  { id: 'midnight', name: 'Midnight', appearance: 'dark', colors },
  { id: 'graphite', name: 'Graphite', appearance: 'dark', colors: {
    background: '#111115', backgroundElevated: '#16161C', panel: '#1C1C24', panelAlt: '#24242E',
    border: '#41414E', borderSoft: '#30303B', text: '#F5F3FA', textSecondary: '#CDC7D8', muted: '#ADA6BB',
    accent: '#C7B8FF', accentMuted: '#8D79C3', accentSoft: '#322A49', danger: '#FF8D99', ok: '#83D8AD', warning: '#E9C785',
  } },
  { id: 'forest', name: 'Forest', appearance: 'dark', colors: {
    background: '#09120F', backgroundElevated: '#0D1914', panel: '#132019', panelAlt: '#1C2A22',
    border: '#354B3E', borderSoft: '#283B30', text: '#EEF6EF', textSecondary: '#C0D2C4', muted: '#A2B8A8',
    accent: '#8BD9AD', accentMuted: '#53966F', accentSoft: '#1E3C2B', danger: '#FF9494', ok: '#8BE6B1', warning: '#EAD08A',
  } },
  { id: 'daylight', name: 'Daylight', appearance: 'light', colors: {
    background: '#F4F7F9', backgroundElevated: '#FFFFFF', panel: '#FFFFFF', panelAlt: '#E7EEF2',
    border: '#B8C8D1', borderSoft: '#D1DFE6', text: '#172D38', textSecondary: '#344F5D', muted: '#4D6571',
    accent: '#00728A', accentMuted: '#28798B', accentSoft: '#D9EDF1', danger: '#B62E41', ok: '#167143', warning: '#886200',
  } },
];

export function normalizeThemeId(value: unknown): PhoneThemeId {
  return PHONE_THEMES.some(theme => theme.id === value) ? value as PhoneThemeId : 'midnight';
}

export function phoneTheme(value: unknown): PhoneTheme {
  return PHONE_THEMES.find(theme => theme.id === normalizeThemeId(value))!;
}

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
};

export const radii = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 22,
  pill: 999,
};

/** Match the Chat Quick controls expand affordance across phone screens. */
export const controlGlyphTypography = {
  fontSize: 26,
  fontWeight: '500' as const,
  lineHeight: 32,
};
