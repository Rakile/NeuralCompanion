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
const story = read('src/components/MprcPanel.tsx');
const visual = read('src/components/VisualPanel.tsx');
const settings = read('src/components/SettingsPanel.tsx');
const chat = read('src/components/ChatFeed.tsx');
const audio = read('src/components/MediaPanel.tsx');
const avatar = read('src/components/MuseTalkPanel.tsx');

[
  'Start desktop bridge',
  'Start LAN backend',
  'Enter pairing code',
  'Test connection',
].forEach((text) => assertIncludes(connection, text, 'Connection wizard'));

assertIncludes(connection, 'Connected to desktop', 'Collapsed connection strip');
assertIncludes(app, 'Desktop Controls', 'Desktop controls drawer');
assertIncludes(app, "icon: 'IMG'", 'Visual tab icon token');
assertIncludes(app, "icon: 'AUD'", 'Audio tab icon token');
assertIncludes(app, "icon: 'AV'", 'Avatar tab icon token');

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

[
  'Connect to desktop or tap Demo.',
  'Visual Reply is unavailable because desktop provider is off.',
].forEach((text) => assertIncludes(visual, text, 'Visual empty states'));

assertIncludes(chat, 'Connect to desktop or tap Demo.', 'Chat empty state');
assertIncludes(audio, 'Connect to desktop or tap Demo.', 'Audio empty state');
assertIncludes(avatar, 'Connect to desktop or tap Demo.', 'Avatar empty state');

[
  'Phone Audio',
  'Voice Input',
  'Connection',
  'Avatar Stream',
  'Diagnostics',
].forEach((text) => assertIncludes(settings, text, 'Settings grouping'));

console.log('Phone UI copy smoke passed.');
