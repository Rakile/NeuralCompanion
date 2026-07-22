const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');

function read(relativePath) {
  return fs.readFileSync(path.join(ROOT, relativePath), 'utf8');
}

function assertIncludes(source, expected, label) {
  if (!source.includes(expected)) {
    throw new Error(`${label} is missing expected copy: ${expected}`);
  }
}

const app = read('App.tsx');
const connection = read('src/components/ConnectionPanel.tsx');
const composer = read('src/components/Composer.tsx');
const chatFeed = read('src/components/ChatFeed.tsx');
const story = read('src/components/MprcPanel.tsx');
const visual = read('src/components/VisualPanel.tsx');
const settings = read('src/components/SettingsPanel.tsx');
const chat = read('src/components/ChatFeed.tsx');
const audio = read('src/components/MediaPanel.tsx');
const avatar = read('src/components/MuseTalkPanel.tsx');
const remoteConnection = read('src/hooks/useRemoteConnection.ts');
const appConfig = JSON.parse(read('app.json'));
const index = read('index.ts');
const phoneDebug = read('src/utils/phoneDebug.ts');
const phoneSettings = read('src/hooks/usePhoneSettings.ts');
const appearance = read('src/components/AppearanceSelector.tsx');
const modeContext = read('src/context/InterfaceModeContext.tsx');
const modeSurface = read('src/components/ModeSurface.tsx');
const immersiveChrome = read('src/hooks/useImmersiveChrome.ts');

[
  'Start desktop bridge',
  'Start LAN backend',
  'Enter pairing code',
  'Test connection',
].forEach((text) => assertIncludes(connection, text, 'Connection wizard'));

assertIncludes(connection, 'Connected to desktop', 'Collapsed connection strip');
assertIncludes(connection, 'Scan QR code', 'QR pairing action');
assertIncludes(app, 'PairingQrScanner', 'QR scanner shell');
assertIncludes(app, 'pairAndConnect', 'QR pairing connection');
assertIncludes(app, 'topControlsCollapsed', 'Collapsible top controls');
assertIncludes(app, 'topControlsPanResponder', 'Top control swipe gestures');
assertIncludes(app, 'ChatPhotoCapture', 'In-chat photo capture');
assertIncludes(composer, 'Photo', 'Chat photo action');
assertIncludes(app, 'sendImage', 'Photo-to-LLM connection');
assertIncludes(app, 'photoAvailable={!demoMode && commandsAvailable}', 'Live-only photo capture');
assertIncludes(index, 'PhoneErrorBoundary', 'Phone crash fallback');
assertIncludes(phoneDebug, '/api/debug', 'Phone debug upload');
assertIncludes(phoneSettings, 'chatLayout', 'Saved clean chat layout');
assertIncludes(phoneSettings, 'chatTextColor', 'Saved clean chat text color');
assertIncludes(phoneSettings, 'chatIndicatorStyle', 'Saved clean chat indicator');
assertIncludes(settings, 'Appearance', 'Global appearance settings');
assertIncludes(app, "React.useState<MoreMode>('settings')", 'Appearance-first More navigation');
assertIncludes(app, 'Appearance & Settings', 'Visible global Appearance navigation');
['Adaptive Focus', 'Flat Utility', 'Immersive Minimal', 'Classic'].forEach((label) => assertIncludes(appearance, label, 'Appearance options'));
assertIncludes(modeContext, 'InterfaceModeProvider', 'Global interface mode provider');
assertIncludes(modeSurface, 'ModeSection', 'Shared clean section surface');
assertIncludes(app, 'InterfaceModeProvider', 'Global interface mode provider');
assertIncludes(immersiveChrome, 'IMMERSIVE_HIDE_DELAY_MS', 'Immersive chrome timer');
assertIncludes(immersiveChrome, 'revealChrome', 'Immersive chrome reveal action');
assertIncludes(app, 'immersiveChrome.chromeVisible', 'Immersive bottom navigation visibility');
assertIncludes(app, 'onTouchStart={immersiveChrome.revealChrome}', 'Immersive tap reveal');
assertIncludes(app, 'disconnected: !sessionActive || Boolean(remote.error)', 'Connection errors force immersive chrome visible');
assertIncludes(app, "['error', 'rejected'].includes", 'Visual failures force immersive chrome visible');
assertIncludes(phoneSettings, 'interfaceStyle', 'Saved global interface style');
assertIncludes(chatFeed, 'useInterfaceMode', 'Global mode-aware Chat feed');
assertIncludes(chatFeed, 'indicatorStyle', 'Runtime indicator styles');
assertIncludes(chatFeed, "mode === 'classic'", 'Classic Chat branch');
assertIncludes(chatFeed, "mode === 'adaptive'", 'Adaptive Chat branch');
assertIncludes(chatFeed, "mode === 'flat'", 'Flat Chat branch');
assertIncludes(chatFeed, "mode === 'immersive'", 'Immersive Chat branch');
assertIncludes(settings, 'Chat text color', 'Appearance text color');
assertIncludes(settings, 'Activity indicator', 'Appearance activity indicator');
assertIncludes(settings, 'buddy?.last_provider_error', 'Buddy error forces diagnostics');
if (app.includes('<ChatDisplayBar')) {
  throw new Error('Chat-only display bar must move into global Appearance settings.');
}
assertIncludes(chatFeed, 'image_url_path', 'Chat attachment rendering');
assertIncludes(chatFeed, 'authorizedUrl', 'Authorized chat attachment URL');
assertIncludes(app, 'Desktop Controls', 'Desktop controls drawer');
assertIncludes(app, 'RemoteCockpit', 'Remote cockpit shell');
assertIncludes(app, 'QuickActions', 'Quick action rail');
assertIncludes(app, 'BottomNavigation', 'Bottom navigation shell');
assertIncludes(app, 'bottomNavClean', 'Mode-aware bottom navigation');
assertIncludes(app, 'moreTabsClean', 'Mode-aware More selector');
assertIncludes(app, 'screenImmersive', 'Immersive app shell');
assertIncludes(app, "{ id: 'visual', label: 'Visual', icon: 'visual' }", 'Visual bottom tab');
assertIncludes(app, "{ id: 'audio', label: 'Audio', icon: 'audio' }", 'Audio bottom tab');
assertIncludes(app, "mode === 'avatar'", 'Avatar more panel');

[
  "'play'",
  "'cast'",
  "'memory'",
  "'visual'",
  "'advanced'",
  'Story Controls',
  'Story Memory',
  'Visual Reply Beat',
].forEach((text) => assertIncludes(story, text, 'Story sections'));
assertIncludes(story, 'ModeSection', 'Story clean sections');
assertIncludes(story, 'primaryFirst', 'Adaptive Story hierarchy');
assertIncludes(story, 'Cast status', 'Always-visible Cast status');
assertIncludes(story, 'classicChoices', 'Classic Story choices remain unframed');
assertIncludes(story, 'classicLatestStory', 'Classic latest Story remains unframed');

[
  'Connect to desktop or tap Demo.',
  'Visual Reply is unavailable because desktop provider is off.',
].forEach((text) => assertIncludes(visual, text, 'Visual empty states'));

assertIncludes(chat, 'Connect to desktop or tap Demo.', 'Chat empty state');
assertIncludes(audio, 'Connect to desktop or tap Demo.', 'Audio empty state');
assertIncludes(avatar, 'Connect to desktop or tap Demo.', 'Avatar empty state');
assertIncludes(avatar, 'useInterfaceMode', 'Mode-aware Avatar surface');
assertIncludes(avatar, 'previewPrimary', 'Avatar preview hierarchy');
assertIncludes(app, 'modeAwareControls', 'Mode-aware desktop controls');
assertIncludes(visual, 'useInterfaceMode', 'Mode-aware Visual surface');
assertIncludes(visual, 'visualPrimary', 'Visual primary canvas');
assertIncludes(audio, 'useInterfaceMode', 'Mode-aware Audio surface');
assertIncludes(audio, 'nowPlayingPrimary', 'Audio now-playing hierarchy');

[
  'Phone Audio',
  'Voice Input',
  'Connection',
  'Avatar Stream',
  'Diagnostics',
].forEach((text) => assertIncludes(settings, text, 'Settings grouping'));

const plugins = appConfig.expo?.plugins ?? [];
if (appConfig.expo?.android?.package !== 'com.lainol.ncmainchatremote') {
  throw new Error('Android package id must remain com.lainol.ncmainchatremote for upgrade compatibility.');
}
if (!plugins.some((plugin) => plugin === './plugins/with-android-cleartext')) {
  throw new Error('Android release builds must include the cleartext LAN config plugin.');
}
const cleartextPlugin = read('plugins/with-android-cleartext.js');
assertIncludes(cleartextPlugin, 'usesCleartextTraffic', 'Android cleartext plugin');
assertIncludes(cleartextPlugin, 'networkSecurityConfig', 'Android cleartext plugin');

assertIncludes(remoteConnection, 'Network.getIpAddressAsync()', 'Startup LAN discovery');
assertIncludes(remoteConnection, 'discoverRemoteBaseUrl', 'Startup LAN discovery');
assertIncludes(remoteConnection, 'startupAutoConnectStartedRef', 'One-time startup auto-connect');

console.log('Phone UI copy smoke passed.');
