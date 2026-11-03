import React from 'react';
import { phoneTheme } from './theme';
import type { PhoneTheme, PhoneThemeId, ThemeColors } from './theme';
import {applyPresentation, normalizePresentationStyle, resolvePresentationTheme} from './presentation';
import type {PresentationStyle} from './presentation';

const ThemeContext = React.createContext<PhoneTheme>(phoneTheme('midnight'));
const PresentationContext = React.createContext<PresentationStyle>('classic');

export function PhoneThemeProvider({ theme, presentationStyle = 'classic', children }: {
  theme: PhoneThemeId; presentationStyle?: PresentationStyle; children: React.ReactNode;
}) {
  const presentation = normalizePresentationStyle(presentationStyle);
  const value = React.useMemo(() => resolvePresentationTheme(theme, presentation), [theme, presentation]);
  return <PresentationContext.Provider value={presentation}>
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  </PresentationContext.Provider>;
}

export function usePresentationStyle(): PresentationStyle { return React.useContext(PresentationContext); }
export function usePhoneTheme(): PhoneTheme { return React.useContext(ThemeContext); }
export function useThemeColors(): ThemeColors { return usePhoneTheme().colors; }
export function useThemedStyles<T>(factory: (colors: ThemeColors) => T, profile?: string): T {
  const palette = useThemeColors();
  const presentation = usePresentationStyle();
  return React.useMemo(() => applyPresentation(factory(palette), presentation, profile), [factory, palette, presentation, profile]);
}
