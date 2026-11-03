export function visibleMessageText(content: string, stripMoodTags: boolean, portraitMoods: string[] = []): string {
  if (!stripMoodTags) return content;
  const recognized = new Set(['neutral', 'happy', 'sad', 'angry', 'calm', 'curious', 'excited', 'fear',
    'tension', 'focus', 'dark', 'epic', 'energetic', ...portraitMoods.map(name => name.toLowerCase())]);
  return content.replace(/\[([A-Za-z][A-Za-z0-9_-]{0,31})\]\s*/g,
    (tag, name: string) => recognized.has(name.toLowerCase()) ? '' : tag).trim();
}
