import {phoneTheme} from './theme';
import type {PhoneTheme} from './theme';
import type {TextStyle, ViewStyle, ImageStyle} from 'react-native';

export type PresentationStyle = 'classic' | 'editorial';
export function normalizePresentationStyle(value: unknown): PresentationStyle {
  return value === 'editorial' ? 'editorial' : 'classic';
}

const editorialTheme: PhoneTheme = {
  id: 'midnight', name: 'Editorial', appearance: 'dark',
  colors: {
    background: '#171918', backgroundElevated: '#1B1D1C',
    panel: '#202321', panelAlt: '#262A27',
    border: '#515650', borderSoft: '#363B37',
    text: '#E9E3D7', textSecondary: '#CAC5BB', muted: '#B4B4A9',
    accent: '#D9AB87', accentMuted: '#A07959', accentSoft: '#393028',
    danger: '#FF9993', ok: '#A3CBA6', warning: '#E8C28A',
  },
};
export function resolvePresentationTheme(theme: unknown, presentation: unknown): PhoneTheme {
  return normalizePresentationStyle(presentation) === 'editorial' ? editorialTheme : phoneTheme(theme);
}

type NamedStyles = Record<string, ViewStyle | TextStyle | ImageStyle>;
const openSection: ViewStyle = {
  backgroundColor: 'transparent', borderRadius: 0, borderWidth: 0,
  borderBottomWidth: 1, borderBottomColor: editorialTheme.colors.borderSoft,
  elevation: 0, shadowOpacity: 0,
};
// Explicit component/style pairs: never infer roles from color, names or size.
// Input borders, modal roots, drag/disabled/error states and press handlers are
// deliberately absent. Profiles change presentation, not component identity.
const sections: Record<string, readonly string[]> = {
  ModeSurface: ['card', 'cleanSection'],
  SettingsPanel: ['panel', 'generalPanel', 'card'],
  DesktopControlsSheet: ['card', 'storyBeatCard', 'storyPaceCard'],
  ContinuousPanel: ['card', 'voiceChoice', 'queueItem'],
  StoryPlanPanel: ['beat'],
  StoryLibraryPanel: ['card'],
  SoundscapePanel: ['card'],
  ChatSoundsMenu: ['sound'],
  VisualReplySettingsSheet: ['card'],
  ConnectionPanel: ['panel', 'compactPanel', 'wizard', 'internetSummary'],
  MediaPanel: ['panel', 'row', 'emptyCard'],
  ControlsBar: ['panel', 'group'],
  MprcPanel: ['panel', 'emptyCard', 'sceneCell', 'segment', 'memoryBox', 'memoryCell', 'castBox'],
  MuseTalkPanel: ['panel'],
  VisualPanel: ['panel'],
  characterUi: ['section', 'voiceTile', 'listTile'],
  PresenceControlsDock: ['tools'],
  ReadingConversation: ['bar', 'styleSection'],
  LiveFullscreenSettings: ['group'],
  VoiceSilkSettings: ['content'],
  VoicePicker: ['voice'],
  LlmModelPicker: ['provider', 'model'],
  QuickPersonaSheet: ['persona'],
  GuidancePresetPicker: ['option'],
  ToolsScreen: ['link'],
  ChatFeed: ['emptyCard', 'assistant', 'userMessageRow'],
};

const overrides: Record<string, NamedStyles> = {
  SettingsPanel: {sectionTitle:{fontFamily:'serif',fontWeight:'400',fontSize:24}},
  PrimaryNavigation: {
    container: {backgroundColor: '#171918'},
    item: {borderRadius: 0, borderBottomWidth: 2, borderBottomColor: 'transparent'},
    itemActive: {backgroundColor: 'transparent', borderBottomColor: '#D9AB87'},
    label: {fontSize: 11, fontWeight: '400', marginTop: 3},
  },
  ChatFeed: {
    content: {paddingHorizontal: 20, gap: 22},
    cleanContent: {paddingHorizontal: 20, gap: 22},
    role: {fontWeight: '500', fontSize: 12},
    message: {fontFamily: 'serif', color: '#E9E3D7'},
    bubble: {borderWidth: 0, borderRadius: 0, maxWidth: '100%'},
    userMessageRow: {borderBottomWidth: 0, borderLeftWidth: 2, borderLeftColor: '#515650', paddingVertical: 8},
  },
  ModeSurface: {
    cleanTitle: {fontSize: 14, fontWeight: '600', textTransform: 'none', color: '#E9E3D7'},
  },
  DesktopControlsSheet: {
    title: {fontWeight: '500', fontSize: 22},
    sectionTitle: {fontWeight: '600', fontSize: 16},
  },
  StoryPlanPanel: {heading: {fontFamily: 'serif', fontWeight: '400', fontSize: 24}},
  StoryLibraryPanel: {title: {fontFamily: 'serif', fontWeight: '400'}},
  AppHeader: {name: {fontFamily: 'serif', fontWeight: '400'}},
  ScreenHeader: {title: {fontWeight: '500'}},
};

export function applyPresentation<T>(
  base: T, presentation: PresentationStyle, profile?: string,
): T {
  if (presentation !== 'editorial' || !profile ||
      (!sections[profile] && !overrides[profile])) return base;
  const original = base as NamedStyles;
  const result = {...original};
  for (const key of sections[profile] ?? []) {
    if (original[key]) result[key] = {...original[key], ...openSection};
  }
  for (const [key, value] of Object.entries(overrides[profile] ?? {})) {
    if (original[key]) result[key] = {...result[key], ...value};
  }
  return result as T;
}
