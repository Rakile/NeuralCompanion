import { createContext } from 'react';
import { DEFAULT_SILK_SETTINGS } from '../../utils/silkSettings';
import type { VoiceVisualizerStyle } from '../../utils/voiceVisualizer';

// Design only. Playback sampling stays with the existing app-level audio owner.
export const SilkSettingsContext = createContext(DEFAULT_SILK_SETTINGS);
export const VoiceVisualizerContext = createContext<VoiceVisualizerStyle>('silk');
